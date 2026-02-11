#!/usr/bin/env python3
from aiohttp import web
import discord
from discord.ext import commands
import asyncio
import json
import time
import re
import traceback
import argparse

parser = argparse.ArgumentParser(usage = '%(prog)s [-h] [<token> <channel_id>\n'
                '[-p,--port PORT] [--command_prefix PREFIX]\n'
                '[--no_allow_command] [--no_allow_logins]\n'
                '[--allow_remote] [--no_use_nicknames]\n'
                '[--no_use_embeds] [--no_allow_send_to_offline_players]\n'
                '[--no_allow_whereis] [--server_down_color COLOR]\n'
                '[--not_logged_in_color COLOR] [--password_leak_color COLOR]]')

parser.add_argument('token_and_channel_id', nargs='*', default=['', ''], metavar='<token> <channel_id>', help='token and channel id, if '
    'omitted then any other arguments will be ignored, the program will use relay.conf instead')
parser.add_argument('--command_prefix', default='!', metavar='PREFIX', help='prefix Discord commands should have to be considered command, '
    'e.g. if this set to ! (the default) user will need to type !login to run login command.')
parser.add_argument('-p', '--port', type=int, default=8080, help='Port server.py listens on, default: 8080')

parser.add_argument('--allow_remote', action='store_true', help='Allow clients not running locally to connect, e.g. not from localhost')
parser.add_argument('--no_allow_command', action='store_true', help='Disables user\'s ability to run any Discord commands')
parser.add_argument('--no_allow_logins', action='store_true', help='Disables user\'s ability to use login command')
parser.add_argument('--no_allow_send_to_offline_players', action='store_true', help='Disables user\'s ability to login in-game from Discord')
parser.add_argument('--no_allow_whereis', action='store_true', help='Disables user\'s ability to know players position')
parser.add_argument('--no_use_nicknames', action='store_true', help='Discord messages nick format, use discord username if set, nickname otherwise')
parser.add_argument('--no_use_embeds', action='store_true', help='Use embeds when reasonable if not set')

parser.add_argument('--server_down_color', default='#ede442', metavar='COLOR', help='Color of the messages informing that luanti server is not running, color format is: #RRGGBB')
parser.add_argument('--not_logged_in_color', default='#46e8e8', metavar='COLOR', help='Color of the messages informing that user is not logged in, color format is: #RRGGBB')
parser.add_argument('--password_leak_color', default='#ed9d42', metavar='COLOR', help='Color of the messages informing that login was attempted in a public channel, color format is: #RRGGBB')
args = parser.parse_args()

if len(args.token_and_channel_id) != 2:
    parser.error('You have to provide both token and channel id')

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
status_queue = Queue()
coords_queue = Queue()

if len(args.token_and_channel_id[0]) and len(args.token_and_channel_id[1]):
    token = args.token_and_channel_id[0]
    channel_id = args.token_and_channel_id[1]
    port = args.port
    prefix = args.command_prefix

    commands_allowed = not args.no_allow_command
    logins_allowed = not args.no_allow_logins
    remote_allowed = args.allow_remote
    do_use_nicknames = not args.no_use_nicknames
    do_use_embeds = not args.no_use_embeds
    send_to_offline_players_allowed = not args.no_allow_send_to_offline_players
    whereis_allowed = not args.no_allow_whereis
    server_down_color = args.server_down_color
    not_logged_in_color = args.not_logged_in_color
    password_leak_color = args.password_leak_color
else:
    import configparser

    config = configparser.ConfigParser()
    config.read('relay.conf')

    token = config['BOT']['token']
    channel_id = int(config['RELAY']['channel_id'])
    port = int(config['RELAY']['port'])
    prefix = config['BOT']['command_prefix']

    commands_allowed = config['RELAY'].getboolean('allow_commands')
    logins_allowed = config['RELAY'].getboolean('allow_logins')
    remote_allowed = config['RELAY'].getboolean('allow_remote')
    do_use_nicknames = config['RELAY'].getboolean('use_nicknames')
    do_use_embeds = config['RELAY'].getboolean('use_embeds')
    send_to_offline_players_allowed = config['RELAY'].getboolean('allow_send_to_offline_players')
    whereis_allowed = config['RELAY'].getboolean('allow_whereis')
    server_down_color = config['RELAY']['server_down_color']
    not_logged_in_color = config['RELAY']['not_logged_in_color']
    password_leak_color = config['RELAY']['password_leak_color']
    # if config['RELAY'].getboolean('send_every_3s'):
    #     incoming_msgs = collections.deque()
    # else:
    #     incoming_msgs = None

bot = commands.Bot(
    command_prefix=prefix,
    intents=discord.Intents(messages=True, message_content=True),
)

last_request = 0

channel = bot.get_partial_messageable(channel_id)
# user id -> playername
authenticated_users = {}
# playername -> user id
authenticated_users_ids = {}

announce_loguot = False

def check_timeout():
    return time.time() - last_request <= 1

translation_re = re.compile(r'\x1b(T|F|E|\(T@[^\)]*\))')

async def handle(request):
    global last_request, announce_loguot
    last_request = time.time()
    send_user_list = False
    try:
        data = {}
        if request.method == 'POST':
            data = await request.json()
        if request.method == 'POST' and data['type'] == 'DISCORD-RELAY-MESSAGE':
            if 'content' in data:
                msg = translation_re.sub('', data['content'])
                msg = discord.utils.escape_mentions(msg)
                chunks = [msg[i:i+2000] for i in range(0, len(msg), 2000)]
            else:
                msg = None
                chunks = []
            if 'embed_description' in data:
                embed_description = translation_re.sub('', data['embed_description'])
                embed_description = discord.utils.escape_mentions(embed_description)
            else:
                embed_description = None
            if 'embed_color' in data:
                if not data['embed_color'] == 'NOT_SET':
                    color = discord.Color.from_str(data['embed_color'])
                else:
                    color = None
                if 'context' in data:
                    id = int(data['context'])
                    target_channel = bot.get_partial_messageable(id)
                    # for chunk in chunks:
                    await target_channel.send(embed=discord.Embed(title=chunks[0] if len(chunks) > 0 else None, color=color,
                            description=embed_description))
                # elif incoming_msgs is None:
                else:
                    # for chunk in chunks:
                    await channel.send(embed=discord.Embed(title=chunks[0] if len(chunks) > 0 else None, color=color,
                            description=embed_description))
                # else:
                #     for chunk in chunks:
                #         incoming_msgs.append({'msg': chunk, 'color': discord.Color.from_str(data['embed_color']),
                #             'description': (data['embed_description'] if data['embed_description'] else None)})
            else:
                if 'context' in data:
                    id = int(data['context'])
                    target_channel = bot.get_partial_messageable(id)
                    for chunk in chunks:
                        await target_channel.send(chunk)
                # elif incoming_msgs is None:
                else:
                    for chunk in chunks:
                        await channel.send(chunk)
                # else:
                #     for chunk in chunks:
                #         incoming_msgs.append({'msg': chunk})

            # discord.send should NOT block extensively on the Lua side
            return web.Response(text='Acknowledged')
        if request.method == 'POST' and data['type'] == 'DISCORD-LOGIN-RESULT':
            user_id = int(data['user_id'])
            user = bot.get_user(user_id)
            if user is None:
                user = await bot.fetch_user(user_id)

            if data['success']:
                if send_to_offline_players_allowed:
                    send_user_list = True
                    if user_id in authenticated_users:
                        del authenticated_users_ids[authenticated_users[user_id]]
                    authenticated_users_ids[data['username']] = user_id
                authenticated_users[user_id] = data['username']
        if send_to_offline_players_allowed and request.method == 'POST' and data['type'] == 'DISCORD-DIRECT-MESSAGE':
            if data['playername'] in authenticated_users_ids:
                msg = translation_re.sub('', data['content'])
                msg = discord.utils.escape_mentions(msg)
                id = authenticated_users_ids[data['playername']]
                user = bot.get_user(id)
                if user is None:
                    user = await bot.fetch_user(id)
                await user.send(msg)

            # discord.send should NOT block extensively on the Lua side
            return web.Response(text='Acknowledged')

        if send_to_offline_players_allowed and request.method == 'POST' and data['type'] == 'DISCORD-STARTUP-REQUEST':
            send_user_list = True
    except Exception:
        traceback.print_exc()

    responseObject = {
        'messages': outgoing_msgs.get_all(),
        'commands': command_queue.get_all(),
        'logins': login_queue.get_all(),
        'statuses': status_queue.get_all(),
        'coords': coords_queue.get_all()
    }
    if send_user_list or announce_loguot:
        announce_loguot = False
        responseObject['logged_in_users'] = list(authenticated_users_ids.keys())
    response = json.dumps(responseObject)
    return web.Response(text=response)

app = web.Application()
app.add_routes([web.get('/', handle),
                web.post('/', handle)])

@bot.event
async def on_message(message):
    global outgoing_msgs
    if check_timeout():
        if (message.channel.id == channel_id and
                message.author.id != bot.user.id):
            msg = {
                'author': (message.author.display_name
                           if do_use_nicknames else message.author.name),
                'content': message.content.replace('\n', '/')
            }
            if msg['content'] != '':
                outgoing_msgs.add(msg)

    await bot.process_commands(message)

if commands_allowed:
    @bot.command(help='Runs an ingame command from Discord.')
    async def cmd(ctx, command=commands.parameter(description='in-game command without leading /, if command is for example //help it become /help'), *, args=commands.parameter(description='arguments, like `player text` in `/msg player text`', default='')):
        if not check_timeout():
            if not do_use_embeds:
                await ctx.send("The server currently appears to be down.")
            else:
                await ctx.send(embed = discord.Embed(title = 'The server currently appears to be down.', color = discord.Color.from_str(server_down_color)))
            return
        if ((ctx.channel.id != channel_id and ctx.guild is not None) or
                not logins_allowed):
            return
        if ctx.author.id not in authenticated_users.keys():
            if not do_use_embeds:
                await ctx.send('Not logged in.')
            else:
                await ctx.send(embed = discord.Embed(title = 'Not logged in.', color = discord.Color.from_str(not_logged_in_color)))
            return
        command = {
            'name': authenticated_users[ctx.author.id],
            'command': command,
            'params': args.replace('\n', '')
        }
        if ctx.guild is None:
            command['context'] = str(ctx.channel.id)
        command_queue.add(command)

    @bot.command(help='Logs into your ingame account from Discord so you can run '
                      'commands and receive direct messages if allowed. You '
                      'should only run this command in DMs with the bot.')
    async def login(ctx, username=commands.parameter(description='in-game player name'), password=commands.parameter(description='in-game password', default='')):
        if not logins_allowed:
            return
        if ctx.guild is not None:
            if not do_use_embeds:
                await ctx.send(ctx.author.mention + ' You\'ve quite possibly just '
                               'leaked your password by using this command outside of '
                               'DMs; it is advised that you change it at once.\n*This '
                               'message will be automatically deleted.*',
                               delete_after=10)
            else:
                await ctx.send(embed = discord.Embed(title = ctx.author.mention + ' You\'ve quite possibly just '
                               'leaked your password by using this command outside of '
                               'DMs; it is advised that you change it at once.\n*This '
                               'message will be automatically deleted.*', color = discord.Color.from_str(password_leak_color)),
                               delete_after=10)
            try:
                await ctx.message.delete()
            except discord.errors.Forbidden:
                print(f"Unable to delete possible password leak by user ID "
                      f"{ctx.author.id} due to insufficient permissions.")
            return
        login_queue.add({
            'username': username,
            'password': password,
            'user_id': str(ctx.author.id),
            'context': str(ctx.channel.id)
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

    @bot.command(help='Logs out your ingame account from Discord so you no more appear ingame.')
    async def logout(ctx):
        global announce_loguot
        if send_to_offline_players_allowed:
            announce_loguot = True
            if authenticated_users[ctx.author.id] in authenticated_users_ids:
                del authenticated_users_ids[authenticated_users[ctx.author.id]]
        if ctx.author.id in authenticated_users:
            del authenticated_users[ctx.author.id]

    @bot.command(help='Get ingame player name you\'re now logged in.')
    async def whoami(ctx):
        if ctx.author.id in authenticated_users:
            if not do_use_embeds:
                await ctx.send('your ingame name is: ' + authenticated_users[ctx.author.id])
            else:
                await ctx.send(embed = discord.Embed(title = 'your ingame name is: ' + authenticated_users[ctx.author.id]))
        else:
            if not do_use_embeds:
                await ctx.send('Not logged in.')
            else:
                await ctx.send(embed = discord.Embed(title = 'Not logged in.', color = discord.Color.from_str(not_logged_in_color)))

    @bot.command(help='Lists connected players and server information.')
    async def status(ctx):
        if not check_timeout():
            if not do_use_embeds:
                await ctx.send("The server currently appears to be down.")
            else:
                await ctx.send(embed = discord.Embed(title = "The server currently appears to be down.", color = discord.Color.from_str(server_down_color)))
            return
        if ctx.channel.id != channel_id and ctx.guild is not None:
            return
        data = {}
        if ctx.guild is None:
            data['context'] = str(ctx.channel.id)
        status_queue.add(data)

    if whereis_allowed:
        @bot.command(help='Get player coordinates.')
        async def whereis(ctx, player=commands.parameter(description='player name in-game')):
            if not check_timeout():
                if not do_use_embeds:
                    await ctx.send("The server currently appears to be down.")
                else:
                    await ctx.send(embed = discord.Embed(title = "The server currently appears to be down.", color = discord.Color.from_str(server_down_color)))
                return
            if ctx.channel.id != channel_id and ctx.guild is not None:
                return
            data = {
                'player': player,
            }
            if ctx.guild is None:
                data['context'] = str(ctx.channel.id)
            coords_queue.add(data)

# async def send_messages():
#     while True:
#         await asyncio.sleep(3)
#         # if channel is None or not incoming_msgs:
#         if channel is None:
#             continue

#         to_send = []
#         msglen = 0
#         while incoming_msgs and msglen + len(incoming_msgs[0]['msg']) <= 2000:
#             msg = incoming_msgs.popleft()
#             to_send.append(msg['msg'])
#             msglen += len(msg['msg']) + 1

#         try:
#             await asyncio.wait_for(channel.send('\n'.join(to_send)),
#                                    timeout=10)
#         except Exception:
#             traceback.print_exc()

async def on_startup(app):
    asyncio.create_task(bot.start(token))
    # if incoming_msgs is not None:
    #     asyncio.create_task(send_messages())

app.on_startup.append(on_startup)

if __name__ == '__main__':
    try:
        print('='*37+'\nStarting relay. Press Ctrl-C to exit.\n'+'='*37)
        if remote_allowed:
            web.run_app(app, host='0.0.0.0', port=port)
        else:
            web.run_app(app, host='localhost', port=port)
    except KeyboardInterrupt:
        pass