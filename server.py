#!/usr/bin/env python3
import argparse
import asyncio
import json
import sys
import time
import traceback
import warnings

import discord
from aiohttp import web
from discord import ui
from discord.ext import commands

warnings.filterwarnings('ignore', 'Changing state of started or joined application is deprecated', DeprecationWarning)

parser = argparse.ArgumentParser(usage = '%(prog)s [-h|--help] [-p,--port PORT] [--allow-remote]')
parser.add_argument('-p', '--port', type=int, default=9692, help='Port server.py listens on, default: 9692')
parser.add_argument('--allow-remote', action='store_true', help='Allow clients not running locally to connect, e.g. not from localhost')
args = parser.parse_args()

port = int(args.port)
remote_allowed = args.allow_remote

token = ''
prefix = ''
channel_ids = []
channel_names = {}

commands_allowed = True
logins_allowed = True
do_use_nicknames = True
send_backend_startups = True
do_use_embeds = True
whereis_allowed = True
mirror_chats = True
moderators_table = []

server_down_color = '#ede442'
password_leak_color = '#ed9d42'

setup_packet_received = web.AppKey('setup_packet_received', bool)
setup_finished = web.AppKey('setup_finished', asyncio.Event)

async def handle_setup_root(request):
    return web.Response(text='NO_SETUP')

async def handle_setup_packet(request):
    global token, prefix, commands_allowed, logins_allowed, do_use_nicknames, send_backend_startups, do_use_embeds
    global whereis_allowed, mirror_chats, moderators_table, server_down_color, password_leak_color
    if request.app[setup_packet_received]:
        print('setup packet already received')
        return web.Response()
    request.app[setup_packet_received] = True
    response = await request.json()

    token = response['token']
    prefix = response['command_prefix']
    channel_ids_str = response['channel_ids']
    for i in channel_ids_str:
        channel_ids.append(int(i[0]))
        if len(i) == 2:
            channel_names[int(i[0])] = i[1]
    commands_allowed = response['allow_commands']
    logins_allowed = response['allow_logins']
    do_use_nicknames = response['use_nicknames']
    send_backend_startups = response['send_backend_startups']
    do_use_embeds = response['use_embeds']
    whereis_allowed = response['allow_whereis']
    mirror_chats = response['mirror_chats']
    moderators_table = response['moderators_table']
    server_down_color = response['server_down_color']
    password_leak_color = response['password_leak_color']

    request.app[setup_finished].set()
    return web.Response(text='{"status": "SUCCESS"}')

async def srv():
    print(f"{'='*15}\nSetting it up.\n{'='*15}")
    finished = asyncio.Event()
    app = web.Application()
    app[setup_packet_received] = False
    app[setup_finished] = finished
    app.add_routes([web.get('/', handle_setup_root),
        web.post('/', handle_setup_root),
        web.post('/setup', handle_setup_packet)])
    runner = web.AppRunner(app)
    await runner.setup()
    if remote_allowed:
        site = web.TCPSite(runner, '0.0.0.0', port)
    else:
        site = web.TCPSite(runner, 'localhost', port)
    await site.start()
    await finished.wait()
    await asyncio.sleep(0)
    await site.stop()
    await runner.cleanup()

if __name__ == '__main__':
    try:
        asyncio.run(srv())
    except KeyboardInterrupt:
        sys.exit()

class Queue:
    def __init__(self):
        self.queue = []

    def add(self, item):
        self.queue.append(item)

    def get_all(self):
        items = self.queue
        self.queue = []
        return items

outgoing_msgs = Queue()
command_queue = Queue()
login_queue = Queue()
service_command_queue = Queue()

bot = commands.Bot(
    command_prefix=prefix,
    intents=discord.Intents(messages=True, message_content=True),
    help_command=None
)

last_request = 0

channels = []
for i in channel_ids:
    channels.append([i, bot.get_partial_messageable(i)])

def check_timeout():
    return time.time() - last_request <= 1

async def handle(request):
    global last_request
    last_request = time.time()
    try:
        data = {}
        if request.method == 'POST':
            data = await request.json()
        if request.method == 'POST' and data['type'] == 'DISCORD-RELAY-MESSAGE':
            if 'content' in data:
                msg = discord.utils.escape_mentions(data['content'])
                chunks = [msg[i:i+2000] for i in range(0, len(msg), 2000)]
            else:
                msg = None
                chunks = []
            if 'embed_description' in data:
                embed_description = discord.utils.escape_mentions(data['embed_description'])
            else:
                embed_description = None
            if 'embed_color' in data:
                if data['embed_color'] != 'NOT_SET':
                    color = discord.Color.from_str(data['embed_color'])
                else:
                    color = None
                if 'context' in data:
                    id = int(data['context'])
                    async def send():
                        target_channel = bot.get_partial_messageable(id)
                        await target_channel.send(embed=discord.Embed(title=chunks[0] if len(chunks) > 0 else None, color=color,
                                description=embed_description))
                    asyncio.create_task(send())
                elif 'userid' in data:
                    userid = int(data['userid'])
                    async def send():
                        user = bot.get_user(userid)
                        if user is None:
                            user = await bot.fetch_user(userid)
                        await user.send(embed=discord.Embed(title=chunks[0] if len(chunks) > 0 else None, color=color,
                                description=embed_description))
                    asyncio.create_task(send())
                else:
                    for channel in channels:
                        asyncio.create_task(channel[1].send(embed=discord.Embed(title=chunks[0] if len(chunks) > 0 else None, color=color,
                                description=embed_description)))
            else:
                if 'context' in data:
                    id = int(data['context'])
                    async def send():
                        target_channel = bot.get_partial_messageable(id)
                        for chunk in chunks:
                            await target_channel.send(chunk)
                    asyncio.create_task(send())
                elif 'userid' in data:
                    userid = int(data['userid'])
                    async def send():
                        user = bot.get_user(userid)
                        if user is None:
                            user = await bot.fetch_user(userid)
                        for chunk in chunks:
                            await user.send(chunk)
                    asyncio.create_task(send())
                else:
                    for channel in channels:
                        for chunk in chunks:
                            asyncio.create_task(channel[1].send(chunk))
        if request.method == 'POST' and data['type'] == 'DISCORD-DIRECT-MESSAGE':
                msg = discord.utils.escape_mentions(data['content'])
                async def send():
                    user = bot.get_user(data['id'])
                    if user is None:
                        user = await bot.fetch_user(data['id'])
                    await user.send(msg)
                asyncio.create_task(send())
    except Exception:
        traceback.print_exc()

    responseObject = {
        'messages': outgoing_msgs.get_all(),
        'commands': command_queue.get_all(),
        'logins': login_queue.get_all(),
        'service_commands': service_command_queue.get_all()
    }
    response = json.dumps(responseObject)
    return web.Response(text=response)

async def setup_already_completed(response):
    return web.Response(text='{"status": "SUCCESS", "running": true}')

app = web.Application()
app.add_routes([web.get('/', handle),
                web.post('/', handle),
                web.post('/setup', setup_already_completed)])

@bot.event
async def on_message(message):
    if message.channel.id in channel_ids and message.author.id != bot.user.id:
        author = (message.author.display_name if do_use_nicknames else message.author.name)
        if check_timeout():
            msg = {
                'author': author,
                'server': channel_names.get(message.channel.id, 'Discord'),
                'content': message.content.replace('\n', '/')
            }
            if msg['content'] != '':
                outgoing_msgs.add(msg)

        if mirror_chats and not message.content.startswith('!login '):
            for channel in channels:
                if channel[0] != message.channel.id:
                    asyncio.create_task(channel[1].send(f"{author}@{channel_names.get(message.channel.id, 'Discord')}: {message.content.replace('\n', '/')}"))

    await bot.process_commands(message)

if send_backend_startups:
    @bot.event
    async def on_ready():
        for channel in channels:
            await channel[1].send("discord_bridge backend started")

@bot.event
async def on_command_error(context, exception):
    if not isinstance(exception, (commands.MissingRequiredArgument, commands.errors.CommandNotFound)):
        traceback.print_exception(exception)

if commands_allowed:
    @bot.tree.command(name='help', description='Want to know how to use discord_bridge? use this command')
    async def help_slash(interaction: discord.Interaction):
        await interaction.response.send_message(embed = discord.Embed(description=f'''There're three slash commands, `/login`, `/logout`, and you guessed it `/help`:
1. `/login`:        Will ask your in-game login and password, so you can run in-game commands whil not being in-game
2. `/logout`:       Will log you out, meaning you'll not be online anymore
3. `/help`:         Prints this text

These commands are prefix commands, the prefix is: `{prefix}`, those can be run only in designated channels, those includes:
1. `{prefix}cmd`:     Runs an ingame command from Discord, e.g. `{prefix}cmd msg player hello from discord`
2. `{prefix}say`:     An alias for `!cmd dc_send`
3. `{prefix}login`:   Please use `/login` instead
4. `{prefix}logout`:  Please use `/logout` instead
5. `{prefix}logins`:  List logged in players
6. `{prefix}status`:  Lists connected players and server information.
7. `{prefix}whereis`: Get player coordinates.
8. `{prefix}whoami`:  Get ingame player name you're now logged in.
The login will:
1. allow you to run in-game commands
2. will show you in `/status` in-game
3. allow in-game players to dm you in discord

Admin only commands:
1. `{prefix}sync`:    Sync command tree globally (makes slash commands work)
2. `{prefix}kick`:    Kicks player

* some commands can be disabled by a server admin
'''), ephemeral=True)

    @bot.command()
    @commands.is_owner()
    async def sync(ctx):
        if not ctx.channel.id in channel_ids and ctx.guild is not None:
            return
        synced_count = await bot.tree.sync()
        await ctx.send(f'command tree is synced: {len(synced_count)}')

    async def run_cmd(ctx, command, args, bypass_auth = False, request_type=''):
        if not ctx.channel.id in channel_ids and ctx.guild is not None:
            return
        user = bot.get_user(ctx.author.id)
        if user is None:
            user = await bot.fetch_user(ctx.author.id)
        if not check_timeout():
            if not do_use_embeds:
                await user.send("The server currently appears to be down.")
            else:
                await user.send(embed = discord.Embed(title = 'The server currently appears to be down.', color = discord.Color.from_str(server_down_color)))
            return
        command = {
            'id': str(ctx.author.id),
            'command': command,
            'params': args.replace('\n', ''),
            'type': request_type,
            'bypass_auth': bypass_auth
        }
        if ctx.guild is None:
            command['context'] = str(ctx.channel.id)
        command_queue.add(command)

    if logins_allowed:
        @bot.command()
        async def cmd(ctx, command=commands.parameter(description='in-game command without leading /, if command is for example //help it become /help'), *, args=commands.parameter(description='arguments, like `player text` in `/msg player text`', default='')):
            return await run_cmd(ctx=ctx, command=command, args=args)

        @bot.command()
        async def say(ctx, *, args=commands.parameter(description='arguments, like `player text` in `/msg player text`')):
            return await run_cmd(ctx=ctx, command='dc_send', args=args)

        @bot.command()
        async def logins(ctx):
            if not ctx.channel.id in channel_ids and ctx.guild is not None:
                return
            service_command_queue.add({
                "cmd": "logins",
                "context": str(ctx.channel.id) if ctx.guild is None else None
            })

        @bot.command(name='login')
        async def login_prefix(ctx, username=commands.parameter(description='in-game player name'), password=commands.parameter(description='in-game password', default='')):
            if not ctx.channel.id in channel_ids and ctx.guild is not None:
                return
            if ctx.guild is not None:
                if not do_use_embeds:
                    await ctx.send(ctx.author.mention + ' You\'ve quite possibly just '
                                   'leaked your password by using this command outside of '
                                   'DMs; it is advised that you change it at once.\n*This '
                                   'message will be automatically deleted.*',
                                   delete_after=10, ephemeral=True)
                else:
                    await ctx.send(embed = discord.Embed(title = ' You\'ve quite possibly just '
                                   'leaked your password by using this command outside of '
                                   'DMs; it is advised that you change it at once.\n*This '
                                   'message will be automatically deleted.*', color = discord.Color.from_str(password_leak_color)),
                                   delete_after=10, ephemeral=True)
                try:
                    await ctx.message.delete()
                except discord.errors.Forbidden:
                    print(f"Unable to delete possible password leak by user ID "
                          f"{ctx.author.id} due to insufficient permissions.")
                return
            login_queue.add({
                'username': username,
                'password': password,
                'dc_name': f"{ctx.author.name}:{ctx.author.display_name}",
                'user_id': str(ctx.author.id)
            })
            if not check_timeout():
                if not do_use_embeds:
                    await ctx.send("The server currently appears to be down, but your "
                               "login attempt has been added to the queue and will be "
                               "executed as soon as the server returns.")
                else:
                    await ctx.send(embed = discord.Embed(title = "The server currently appears to be down, but your "
                               "login attempt has been added to the queue and will be "
                               "executed as soon as the server returns.",
                               color = discord.Color.from_str(server_down_color)))

        @bot.tree.command(name='login', description='Login to ingame account to run cmds and receive DMs')
        async def login_slash(interaction: discord.Interaction):
            class password_modal(ui.Modal, title='Enter your luanti server\'s credential'):
                txt = ui.TextDisplay('this should be safe enough, but be cautious')
                username = ui.TextInput(label='Name', placeholder='Username')
                password = ui.TextInput(label='Password', placeholder='********', required=False)

                async def on_submit(self, interaction: discord.Interaction):
                    login_queue.add({
                        'username': self.username.value,
                        'password': self.password.value,
                        'user_id': str(interaction.user.id),
                        'dc_name': f"{interaction.user.name}:{interaction.user.display_name}"
                    })
                    if not check_timeout():
                        if not do_use_embeds:
                            await interaction.response.send_message("The server currently appears to be down, but your "
                                       "login attempt has been added to the queue and will be "
                                       "executed as soon as the server returns.", ephemeral=True)
                        else:
                            await interaction.response.send_message(embed = discord.Embed(title = "The server currently appears to be down, but your "
                                       "login attempt has been added to the queue and will be "
                                       "executed as soon as the server returns.",
                                       color = discord.Color.from_str(server_down_color)), ephemeral=True)
                    else:
                        await interaction.response.defer()
            await interaction.response.send_modal(password_modal())

        @bot.hybrid_command(help='Logs out your ingame account')
        async def logout(ctx):
            if not ctx.channel.id in channel_ids and ctx.guild is not None and not ctx.interaction:
                return
            if not do_use_embeds:
                await ctx.send("logout was invoked", delete_after=10, ephemeral=True)
            else:
                await ctx.send(embed = discord.Embed(title = "logout was invoked"), delete_after=10, ephemeral=True)
            service_command_queue.add({
                "cmd": "logout",
                "author_id": str(ctx.author.id),
                "context": str(ctx.channel.id) if ctx.guild is None else None
            })

        @bot.command()
        async def kick(ctx, username=commands.parameter(description='in-game name to kick')):
            if not await bot.is_owner(ctx.author) and not str(ctx.author.id) in moderators_table:
                return
            if not ctx.channel.id in channel_ids and ctx.guild is not None:
                return
            service_command_queue.add({
                "cmd": "kick",
                "username": username,
                "context": str(ctx.channel.id) if ctx.guild is None else None
            })

        @bot.command()
        async def whoami(ctx):
            if not ctx.channel.id in channel_ids and ctx.guild is not None:
                return
            service_command_queue.add({
                "cmd": "whoami",
                "author_id": str(ctx.author.id),
                "context": str(ctx.channel.id) if ctx.guild is None else None
            })

    @bot.command()
    async def status(ctx):
        return await run_cmd(ctx=ctx, command='status', args='', bypass_auth=True, request_type='status')

    if whereis_allowed:
        @bot.command()
        async def whereis(ctx, player=commands.parameter(description='player name in-game')):
            return await run_cmd(ctx=ctx, command='dc_whereis', args=player, bypass_auth=True, request_type='whereis')

async def on_startup(app):
    asyncio.create_task(bot.start(token))

app.on_startup.append(on_startup)

if __name__ == '__main__':
    try:
        print(f"Starting relay.\n{'='*15}")
        if remote_allowed:
            web.run_app(app, host='0.0.0.0', port=port)
        else:
            web.run_app(app, host='localhost', port=port)
    except KeyboardInterrupt:
        pass