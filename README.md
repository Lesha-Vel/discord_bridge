## Luanti-Discord Relay `[discord_bridge]`

# THIS README FILE IS WORK IN PROGRESS, will be fixed soon

A feature-filled Discord relay for Luanti, supporting:

- Relaying server chat to Discord, and Discord chat to the server
- Allowing anyone to get the server status via a command
- Logging into the server from Discord *(configurable)*
- Running commands from Discord *(configurable)*
- Support podman/docker
- direct messaging
- realy welcome/join/leave/death
- xban2 support
- online/offline players position command
- slash commands!

## Great! How do I use it?

Easy! `discord_bridge` works by running a Python program which converses with a serverside mod using HTTP requests.

Python 3.8+, `aiohttp` 3.7.4+ and `discord.py` 2.0.0+ are required.

### Basic setup

1. Download the source code and its dependencies.
2. Create an application at the [Discord Developer Dashboard](https://discordapp.com/developers/applications/) and enable it as a bot (in the Bot tab.) Also enable the **Message Content Intent**.
3. Copy the token from your newly-created bot, and use it to finish setting up `minetest.conf`.
Example `minetest.conf`:
```
discord_bridge.setup_channel_id = 123456789987654321
discord_bridge.setup_token = AbCdEfGhIjKlMnOpQrStUvWxYz.123456.aBcDeFgHiJkLmNoPqRsTuVwXyZ0987654321_-
```

4. Set `discord.port` in your `minetest.conf` to match the port that is set with `--port` (or leave the default), and grant the mod permission to use the HTTP API.

Example `minetest.conf` excerpt:
```
secure.enable_security = true
secure.http_mods = discord_bridge
discord_bridge.host = 127.0.0.1
discord_bridge.port = 9692
discord_bridge.escape_formatting = true
```
*(Side note: The port must be set in both `server.py` `--port` and `minetest.conf` because users may decide to run the relay in a different location than the mod, or to run multiple relays/servers at once.)*

5. Run the relay and, when you're ready, the Luanti server. The relay may be left up even when the server goes down, or may run continuously between several server restarts, for maximum convenience.

## Frequently Asked Questions

**Q: I just want a normal relay. Can I disable logins?**

*A: Yep! Just set `discord_bridge.setup_allow_logins = false` in `minetest.conf`.*

**Q: Do I need to re-login after a server restart, like with the IRC mod?**

*A: Nope, logins persist as long as the relay is up.*

**Q: I'm getting an HTTP error - it says the server can't be found?**

*A: Make sure the relay is running and that you've configured the correct port in both `minetest.conf` and `server.py` command line arguments.*

**Q: Why is an external program required at all? And why use HTTP polling?**

*A: Discord's API uses websockets, which require a continuous connection. Luanti's Lua API is not set up to handle these, so running a Discord relay entirely within Luanti is infeasible. HTTP polling is used because it avoids additional dependencies (such as luasocket). But it looks like external lua dependency+trusted mod can potentially do it*
