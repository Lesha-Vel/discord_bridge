#!/usr/bin/env python3
# import sys
from aiohttp import web
# import aiohttp
import discord
from discord.ext import commands
import asyncio
# import collections
import json
import time
import configparser
import re
import traceback

config = configparser.ConfigParser()

config.read('relay.conf')


class Queue:
    def __init__(self):
        self.queue = []

    def add(self, item):
        self.queue.append(item)

    def get(self):
        if len(self.queue) >= 1:
            return self.queue.pop(0)

    def get_all(self):
        items = self.queue
        self.queue = []
        return items

    def isEmpty(self):
        return len(self.queue) == 0


outgoing_msgs = Queue()
command_queue = Queue()
login_queue = Queue()

prefix = config['BOT']['command_prefix']

bot = commands.Bot(
    command_prefix=prefix,
    intents=discord.Intents(messages=True, message_content=True),
)

channel_id = int(config['RELAY']['channel_id'])

port = int(config['RELAY']['port'])
token = config['BOT']['token']
logins_allowed = config['RELAY'].getboolean('allow_logins')
remote_allowed = config['RELAY'].getboolean('allow_remote')
do_use_nicknames = config['RELAY'].getboolean('use_nicknames')
do_use_embeds = config['RELAY'].getboolean('use_embeds')
server_down_color = config['RELAY']['server_down_color']
not_logged_in_color = config['RELAY']['not_logged_in_color']
password_leak_color = config['RELAY']['password_leak_color']
# if config['RELAY'].getboolean('send_every_3s'):
#     incoming_msgs = collections.deque()
# else:
#     incoming_msgs = None

last_request = 0

channel = bot.get_partial_messageable(channel_id)
authenticated_users = {}


def check_timeout():
    return time.time() - last_request <= 1


translation_re = re.compile(r'\x1b(T|F|E|\(T@[^\)]*\))')


async def handle(request):
    global last_request
    last_request = time.time()
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
                authenticated_users[user_id] = data['username']
    except Exception:
        traceback.print_exc()

    response = json.dumps({
        'messages': outgoing_msgs.get_all(),
        'commands': command_queue.get_all(),
        'logins': login_queue.get_all()
    })
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


@bot.command(help='Runs an ingame command from Discord.')
async def cmd(ctx, command, *, args=''):
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
                  'commands. You should only run this command in DMs with the '
                  'bot.')
async def login(ctx, username, password=''):
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


@bot.command(help='Lists connected players and server information.')
async def status(ctx, *, args=None):
    if not check_timeout():
        if not do_use_embeds:
            await ctx.send("The server currently appears to be down.")
        else:
            await ctx.send(embed = discord.Embed(title = "The server currently appears to be down.", color = discord.Color.from_str(server_down_color)))
        return
    if ctx.channel.id != channel_id and ctx.guild is not None:
        return
    data = {
        'name': 'discord_relay',
        'command': 'status',
        'params': '',
    }
    if ctx.guild is None:
        data['context'] = str(ctx.channel.id)
    command_queue.add(data)


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
