local http = minetest.request_http_api()
local settings = minetest.settings

local host = settings:get('discord_bridge.host') or 'localhost'
local port = settings:get('discord_bridge.port') or 8080
local escape_formatting = settings:get_bool('discord_bridge.escape_formatting', false)
local timeout = 10

local discord_bridge = {}
discord = {}

-- Configuration
discord_bridge.text_colorization = settings:get('discord_bridge.text_color') or '#ffffff'

discord_bridge.clean_invites = settings:get_bool('discord_bridge.clean_invites', true)
discord_bridge.date = settings:get('discord_bridge.date') or '%m/%d/%Y %I:%M%p'

discord_bridge.send_server_startup = settings:get_bool('discord_bridge.send_server_startup', true)
discord_bridge.send_server_shutdown = settings:get_bool('discord_bridge.send_server_shutdown', true)
discord_bridge.include_server_status_on_startup = settings:get_bool('discord_bridge.include_server_status_on_startup', true)
discord_bridge.include_server_status_on_shutdown = settings:get_bool('discord_bridge.include_server_status_on_shutdown', true)
discord_bridge.send_joins = settings:get_bool('discord_bridge.send_joins', true)
discord_bridge.send_last_login = settings:get_bool('discord_bridge.send_last_login', false)
discord_bridge.send_leaves = settings:get_bool('discord_bridge.send_leaves', true)
discord_bridge.send_welcomes = settings:get_bool('discord_bridge.send_welcomes', true)
discord_bridge.send_deaths = settings:get_bool('discord_bridge.send_deaths', true)

discord_bridge.name_wrapper = settings:get('discord_bridge.name_wrapper') or '<**@1**>  '
discord_bridge.startup_text = settings:get('discord_bridge.startup_text') or '*** Server started!'
discord_bridge.shutdown_text = settings:get('discord_bridge.shutdown_text') or '*** Server shutting down...'
discord_bridge.join_text = settings:get('discord_bridge.join_text') or '\\*\\*\\* **@1** joined the game'
discord_bridge.last_login_text = settings:get('discord_bridge.last_login_text') or '\\*\\*\\* **@1** joined the game. Last login: @2'
discord_bridge.leave_text = settings:get('discord_bridge.leave_text') or '\\*\\*\\* **@1** left the game'
discord_bridge.welcome_text = settings:get('discord_bridge.welcome_text') or '\\*\\*\\* **@1** joined the game for the first time. Welcome!'
discord_bridge.death_text = settings:get('discord_bridge.death_text') or '\\*\\*\\* **@1** died'
discord_bridge.chat_message_format = settings:get('discord_bridge.chat_message_format') or '<%s@Discord> %s'

discord_bridge.use_embeds_on_joins_and_leaves = settings:get_bool('discord_bridge.use_embeds_on_joins_and_leaves', true)
discord_bridge.use_embeds_on_welcomes = settings:get_bool('discord_bridge.use_embeds_on_welcomes', true)
discord_bridge.use_embeds_on_deaths = settings:get_bool('discord_bridge.use_embeds_on_deaths', true)
discord_bridge.use_embeds_on_server_updates = settings:get_bool('discord_bridge.use_embeds_on_server_updates', true)
discord_bridge.use_embeds_on_dm_cmd = settings:get_bool('discord_bridge.use_embeds_on_dm_cmd', false)
discord_bridge.use_embeds_on_svc_dms = settings:get_bool('discord_bridge.use_embeds_on_svc_dms', false)

discord_bridge.startup_color = settings:get('discord_bridge.startup_color') or '#5865f2'
discord_bridge.shutdown_color = settings:get('discord_bridge.shutdown_color') or 'NOT_SET'
discord_bridge.join_color = settings:get('discord_bridge.join_color') or '#57f287'
discord_bridge.leave_color = settings:get('discord_bridge.leave_color') or '#ed4245'
discord_bridge.welcome_color = settings:get('discord_bridge.welcome_color') or '#57f287'
discord_bridge.death_color = settings:get('discord_bridge.death_color') or 'NOT_SET'
discord_bridge.cmd_chat_send_player_color = settings:get('discord_bridge.cmd_chat_send_player_color') or 'NOT_SET'
discord_bridge.cmd_ret_value_color = settings:get('discord_bridge.cmd_ret_value_color') or 'NOT_SET'
discord_bridge.svc_dms_banned_color = settings:get('discord_bridge.svc_dms_banned_color') or '#ed4245'
discord_bridge.svc_dms_privs_color = settings:get('discord_bridge.svc_dms_privs_color') or '#ede442'
discord_bridge.svc_dms_cnf_color = settings:get('discord_bridge.svc_dms_cnf_color') or '#ed9d42'
discord_bridge.login_success_color = settings:get('discord_bridge.login_success_color') or '#57f287'
discord_bridge.login_fail_color = settings:get('discord_bridge.login_fail_color') or '#ed4245'

discord_bridge.registered_on_messages = {}
discord_bridge.authenticated_users = {}

discord_bridge.old_msg_func = minetest.registered_chatcommands['msg'].func
minetest.override_chatcommand('msg', {
    func = function(name, param)
        local target_player, message = param:match('^(%S+) (.+)$')
        if discord_bridge.authenticated_users[target_player] then
            minetest.log('action', 'DM from ' .. name .. ' to a discord user ' .. target_player .. ': ' .. message)
            if not target_player then
                return false, "Invalid usage, see /help msg."
            end
            discord_bridge.send_dm_to_discord(target_player, message)
            if not minetest.get_player_by_name(target_player) then
                return true, 'DM sent to a discord user ' .. target_player .. ': ' .. message
            end
        end
	    return discord_bridge.old_msg_func(name, param)
    end
})

core.register_privilege('discord_bridge', 'allows to run list_discord_users')
minetest.register_chatcommand("list_discord_users", {
    description = "get list of users logged-in in discord",
    privs = {discord_bridge = true},
    func = function(name, param)
        local users = 'logged in users: '
        for username, _ in pairs(discord_bridge.authenticated_users) do
            users = users .. username .. ', '
        end
        minetest.chat_send_player(name, users)
    end
})

local irc_enabled = minetest.get_modpath("irc")
local xban2_enabled = minetest.get_modpath("xban2")

function discord_bridge.register_on_message(func)
    table.insert(discord_bridge.registered_on_messages, func)
end
discord.register_on_message = discord_bridge.register_on_message

discord_bridge.chat_send_all = minetest.chat_send_all
discord.chat_send_all = minetest.chat_send_all

-- a part from dcwebhook
local function replace(str, ...)
    local arg = {...}
    return (str:gsub("@(.)", function(matched)
        return arg[tonumber(matched)]
    end))
end
-- Allow the chat message format to be customised by other mods
function discord_bridge.format_chat_message(name, msg)
    return (discord_bridge.chat_message_format):format(name, msg)
end

function discord_bridge.handle_response(response)
    local data = response.data
    if data == '' or data == nil then
        return
    end
    local data = minetest.parse_json(response.data)
    if not data then
        return
    end
    if data.messages then
        for _, message in pairs(data.messages) do
            for _, func in pairs(discord_bridge.registered_on_messages) do
                func(message.author, message.content)
            end
            if discord_bridge.clean_invites then
                message.content = message.content:gsub("%S*discord%.gg%S*", ""):gsub("%S*discordapp%.com/invite%S*", "")
            end
            local msg = discord_bridge.format_chat_message(message.author, message.content)
            discord_bridge.chat_send_all(minetest.colorize(discord_bridge.text_colorization, msg))
            if irc_enabled then
                irc.say(msg)
            end
            minetest.log('action', '[Discord] Message: '..msg)
        end
    end
    if data.commands then
        local commands = minetest.registered_chatcommands
        for _, v in pairs(data.commands) do
            local xban2_banned = false
            if xban2_enabled then
                local names, banned, record = xban.get_info(v.name)
                xban2_banned = (banned and record) or false
            end
            if minetest.get_ban_description(v.name) ~= '' or xban2_banned then
                if not discord_bridge.use_embeds_on_svc_dms then
                    discord_bridge.send('You cannot run commands because you are banned.', v.context or nil)
                else
                    discord_bridge.send('You cannot run commands because you are banned.', v.context or nil, discord_bridge.svc_dms_banned_color)
                end
                return
            end
            if commands[v.command] then
                -- Check player privileges
                local required_privs = commands[v.command].privs or {}
                local player_privs = minetest.get_player_privs(v.name)
                for priv, value in pairs(required_privs) do
                    if player_privs[priv] ~= value then
                        if not discord_bridge.use_embeds_on_svc_dms then
                            discord_bridge.send('Insufficient privileges.', v.context or nil)
                        else
                            discord_bridge.send('Insufficient privileges.', v.context or nil, discord_bridge.svc_dms_privs_color)
                        end
                        return
                    end
                end
                local old_chat_send_player = minetest.chat_send_player
                minetest.chat_send_player = function(name, message)
                    old_chat_send_player(name, message)
                    if name == v.name then
                        if escape_formatting then
                            message = message:gsub("\\", "\\\\"):gsub("%*", "\\*"):gsub("_", "\\_"):gsub("^#", "\\#")
                        end
                        if not discord_bridge.use_embeds_on_dm_cmd then
                            discord_bridge.send(message, v.context or nil)
                        else
                            discord_bridge.send(nil, v.context or nil, discord_bridge.cmd_chat_send_player_color, message)
                        end
                    end
                end
                local success, ret_val = commands[v.command].func(v.name, v.params or '')
                if ret_val then
                    if escape_formatting then
                        ret_val = ret_val:gsub("\\", "\\\\"):gsub("%*", "\\*"):gsub("_", "\\_"):gsub("^#", "\\#")
                    end
                    if not discord_bridge.use_embeds_on_dm_cmd then
                        discord_bridge.send(ret_val, v.context or nil)
                    else
                        discord_bridge.send(nil, v.context or nil, discord_bridge.cmd_ret_value_color, ret_val)
                    end
                end
                minetest.chat_send_player = old_chat_send_player
            else
                if not discord_bridge.use_embeds_on_svc_dms then
                    discord_bridge.send(('Command not found: `%s`'):format(v.command), v.context or nil)
                else
                    discord_bridge.send(('Command not found: `%s`'):format(v.command), v.context or nil, discord_bridge.svc_dms_cnf_color)
                end
            end
        end
    end
    if data.status_requests then
        local admin = minetest.settings:get('name')
        if admin == '' then admin = 'discord_relay' end
        for _, v in pairs(data.status_requests) do
            local success, ret_val = minetest.registered_chatcommands['status'].func(admin, '')
            if ret_val then
                ret_val = ret_val:gsub("\\", "\\\\"):gsub("%*", "\\*"):gsub("_", "\\_"):gsub("^#", "\\#")
                if not discord_bridge.use_embeds_on_svc_dms then
                    discord_bridge.send(ret_val, v.context or nil)
                else
                    discord_bridge.send(ret_val, v.context or nil, discord_bridge.cmd_ret_value_color)
                end
            end
        end
    end
    if data.logins then
        local auth = minetest.get_auth_handler()
        for _, v in pairs(data.logins) do
            local authdata = auth.get_auth(v.username)
            local result = false
            if authdata then
                result = minetest.check_password_entry(v.username, authdata.password, v.password)
            end
            local request = {
                type = 'DISCORD-LOGIN-RESULT',
                user_id = v.user_id,
                username = v.username,
                success = result
            }
            http.fetch({
                url = tostring(host)..':'..tostring(port),
                timeout = timeout,
                post_data = minetest.write_json(request)
            }, discord_bridge.handle_response)
            if result then
                discord_bridge.authenticated_users[v.username] = os.time()
                if not discord_bridge.use_embeds_on_svc_dms then
                    discord_bridge.send('Login successful.', v.context or nil)
                else
                    discord_bridge.send('Login successful.', v.context or nil, discord_bridge.login_success_color)
                end
            else
                if not discord_bridge.use_embeds_on_svc_dms then
                    discord_bridge.send('Login failed.', v.context or nil)
                else
                    discord_bridge.send('Login failed.', v.context or nil, discord_bridge.login_fail_color)
                end
            end
        end
    end
end

function discord_bridge.send(message, id, embed_color, embed_description)
    local content
    local data = {
        type = 'DISCORD-RELAY-MESSAGE'
    }
    if message then
        content = minetest.strip_colors(message)
        data['content'] = content
    else
        data['content'] = nil
    end
    if id then
        data['context'] = id
    end
    if embed_color then
        data['embed_color'] = embed_color
    end
    if embed_description then
        data['embed_description'] = embed_description
    end
    http.fetch_async({
        url = tostring(host)..':'..tostring(port),
        timeout = timeout,
        post_data = minetest.write_json(data)
    })
end
discord.send = discord_bridge.send

function discord_bridge.send_dm_to_discord(playername, message)
    local content
    local data = {
        type = 'DISCORD-DIRECT-MESSAGE',
        playername = playername
    }
    content = minetest.strip_colors(message)
    data['content'] = content
    http.fetch_async({
        url = tostring(host) .. ':' .. tostring(port),
        timeout = timeout,
        post_data = minetest.write_json(data)
    })
end

-- function minetest.chat_send_all(message)
--     discord_bridge.chat_send_all(message)
--     discord_bridge.send(message)
-- end

-- Register the chat message callback after other mods load so that anything
-- that overrides chat will work correctly
minetest.after(0, minetest.register_on_chat_message, function(name, message)
    if not escape_formatting then
        discord_bridge.send(replace(discord_bridge.name_wrapper, name) .. message)
    else
        discord_bridge.send(replace(discord_bridge.name_wrapper, name) .. message:gsub("\\", "\\\\"):gsub("%*", "\\*"):gsub("_", "\\_"):gsub("^#", "\\#"))
    end
end)


if discord_bridge.send_joins then
    minetest.after(0, minetest.register_on_joinplayer, function(player, last_login)
        local name = player:get_player_name()

        if last_login == nil and discord_bridge.send_welcomes then
            if not discord_bridge.use_embeds_on_welcomes then
                discord_bridge.send(replace(discord_bridge.welcome_text, name))
            else
                discord_bridge.send(nil, nil, discord_bridge.welcome_color,
                    replace(discord_bridge.welcome_text, name))
            end
        else
            if not discord_bridge.use_embeds_on_joins_and_leaves then
                discord_bridge.send(discord_bridge.send_last_login and
                    replace(discord_bridge.last_login_text, name, os.date(discord_bridge.date, last_login)) or
                    replace(discord_bridge.join_text, name))
            else
                discord_bridge.send(nil, nil, discord_bridge.join_color,
                    (discord_bridge.send_last_login and
                    replace(discord_bridge.last_login_text, name, os.date(discord_bridge.date, last_login)) or
                    replace(discord_bridge.join_text, name)))
            end
        end
    end)
end

if discord_bridge.send_leaves then
    minetest.register_on_leaveplayer(function(player)
        local name = player:get_player_name()

        if not discord_bridge.use_embeds_on_joins_and_leaves then
            discord_bridge.send(replace(discord_bridge.leave_text, name))
        else
            discord_bridge.send(nil, nil, discord_bridge.leave_color, replace(discord_bridge.leave_text, name))
        end

    end)
end

if discord_bridge.send_deaths then
    minetest.register_on_dieplayer(function(player)
        local name = player:get_player_name()

        if not discord_bridge.use_embeds_on_deaths then
            discord_bridge.send(replace(discord_bridge.death_text, name))
        else
            discord_bridge.send(nil, nil, discord_bridge.death_color, replace(discord_bridge.death_text, name))
        end

    end)
end

local timer = 0
local ongoing = nil
minetest.register_globalstep(function(dtime)
    if dtime then
        timer = timer + dtime
        if timer > 0.2 then
            if not ongoing then
                ongoing = http.fetch_async({
                    url = tostring(host)..':'..tostring(port),
                    timeout = timeout,
                })
            else
                local res = http.fetch_async_get(ongoing)

                if res.completed == true then
                    discord_bridge.handle_response(res)
                    ongoing = http.fetch_async({
                        url = tostring(host)..':'..tostring(port),
                        timeout = timeout,
                    })
                end
            end

            timer = 0
        end
    end
end)

minetest.register_on_shutdown(function()
    if discord_bridge.send_server_shutdown then
        if discord_bridge.use_embeds_on_server_updates then
            discord_bridge.send(discord_bridge.shutdown_text, nil, discord_bridge.shutdown_color,
                (discord_bridge.include_server_status_on_shutdown and minetest.get_server_status():gsub("^#", "\\#") or nil))
        else
            discord_bridge.send(discord_bridge.shutdown_text ..
                (discord_bridge.include_server_status_on_shutdown and " - " .. minetest.get_server_status() or ""))
        end
    end
end)

if irc_enabled then
    discord_bridge.old_irc_sendLocal = irc.sendLocal
    function irc.sendLocal(msg)
        discord_bridge.old_irc_sendLocal(msg)
        if not escape_formatting then
            discord_bridge.send(msg)
        else
            discord_bridge.send(msg:gsub("\\", "\\\\"):gsub("%*", "\\*"):gsub("_", "\\_"):gsub("^#", "\\#"))
        end
    end
end

if discord_bridge.send_server_startup then
    if discord_bridge.use_embeds_on_server_updates then
        discord_bridge.send(discord_bridge.startup_text, nil, discord_bridge.startup_color,
            (discord_bridge.include_server_status_on_startup and minetest.get_server_status():gsub("^#", "\\#") or nil))
    else
        discord_bridge.send(discord_bridge.startup_text ..
            (discord_bridge.include_server_status_on_startup and " - " .. minetest.get_server_status() or ""))
    end
end
