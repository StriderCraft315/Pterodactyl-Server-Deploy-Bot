# bot.py

# ⚡ Flash Nodes — Full Pterodactyl Deploy Bot

# Features: slash + prefix commands, DM embed system, log channels, admin flows, manage UI buttons,

#           Pterodactyl client & application API helpers, DB persistence, Watching status.

import os

import json

import sqlite3

import secrets

import asyncio

from typing import Optional, Dict, Any, List

import aiohttp

import discord

from discord.ext import commands

from discord import app_commands

# -------------------------

# Configuration & constants

# -------------------------

CONFIG_PATH = "config.json"

DB_PATH = "bot_data.db"

DEFAULT_TIMEOUT = 60  # seconds for interactive waits

if not os.path.exists(CONFIG_PATH):

    raise FileNotFoundError("Missing config.json. Create it from the template provided below and fill tokens/keys.")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:

    CONFIG = json.load(f)

TOKEN = CONFIG.get("bot_token")

PREFIX = CONFIG.get("prefix", ".")

ADMINS = set(CONFIG.get("admins", []))  # list of strings (discord id strings)

PANELS = CONFIG.get("panels", {})      # dict: panel_key -> {url, api_key, application_api_key}

if not TOKEN:

    raise RuntimeError("Bot token missing in config.json")

# -------------------------

# Database initialization

# -------------------------

def init_db():

    conn = sqlite3.connect(DB_PATH)

    cur = conn.cursor()

    cur.execute("""

    CREATE TABLE IF NOT EXISTS users (

      id INTEGER PRIMARY KEY AUTOINCREMENT,

      email TEXT UNIQUE,

      password TEXT,

      panel_key TEXT,

      discord_id TEXT,

      nickname TEXT,

      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

    )""")

    cur.execute("""

    CREATE TABLE IF NOT EXISTS servers (

      id INTEGER PRIMARY KEY AUTOINCREMENT,

      panel_key TEXT,

      server_uuid TEXT,

      name TEXT,

      owner_email TEXT,

      owner_discord TEXT,

      description TEXT,

      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

    )""")

    cur.execute("""

    CREATE TABLE IF NOT EXISTS log_channels (

      id INTEGER PRIMARY KEY AUTOINCREMENT,

      panel_key TEXT,

      server_id TEXT,

      channel_id TEXT,

      UNIQUE(panel_key, server_id)

    )""")

    conn.commit()

    conn.close()

init_db()

# -------------------------

# HTTP helpers (Pterodactyl)

# -------------------------

async def app_api_request(panel_key: str, path: str, method: str="GET", json_body: Optional[Dict]=None) -> Dict:

    panel = PANELS.get(panel_key)

    if not panel:

        return {"error": "panel_not_found"}

    api_key = panel.get("application_api_key")

    if not api_key:

        return {"error": "missing_application_key"}

    url = panel["url"].rstrip("/") + "/api/application" + path

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"}

    async with aiohttp.ClientSession() as sess:

        async with sess.request(method, url, headers=headers, json=json_body) as resp:

            if resp.status == 204:

                return {"status": 204}

            try:

                return await resp.json()

            except Exception:

                return {"error": f"invalid_json_response_{resp.status}"}

async def client_api_request(panel_key: str, path: str, method: str="GET", json_body: Optional[Dict]=None) -> Dict:

    panel = PANELS.get(panel_key)

    if not panel:

        return {"error": "panel_not_found"}

    api_key = panel.get("api_key")

    if not api_key:

        return {"error": "missing_client_key"}

    url = panel["url"].rstrip("/") + "/api/client" + path

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"}

    async with aiohttp.ClientSession() as sess:

        async with sess.request(method, url, headers=headers, json=json_body) as resp:

            if resp.status == 204:

                return {"status": 204}

            try:

                return await resp.json()

            except Exception:

                return {"error": f"invalid_json_response_{resp.status}"}

# -------------------------

# DB helpers

# -------------------------

def save_created_user(panel_key: str, email: str, password: str, discord_id: Optional[str]=None, nickname: Optional[str]=None):

    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()

    cur.execute("INSERT OR IGNORE INTO users (email, password, panel_key, discord_id, nickname) VALUES (?, ?, ?, ?, ?)",

                (email, password, panel_key, discord_id, nickname))

    conn.commit(); conn.close()

def save_created_server(panel_key: str, server_uuid: str, name: str, owner_email: str, owner_discord: Optional[str]=None, description: Optional[str]=None):

    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()

    cur.execute("INSERT INTO servers (panel_key, server_uuid, name, owner_email, owner_discord, description) VALUES (?, ?, ?, ?, ?, ?)",

                (panel_key, server_uuid, name, owner_email, owner_discord, description))

    conn.commit(); conn.close()

def set_log_channel(panel_key: str, channel_id: int, server_id: Optional[str]=None):

    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()

    cur.execute("""

      INSERT INTO log_channels (panel_key, server_id, channel_id) VALUES (?, ?, ?)

      ON CONFLICT(panel_key, server_id) DO UPDATE SET channel_id=excluded.channel_id

    """, (panel_key, server_id, str(channel_id)))

    conn.commit(); conn.close()

def get_log_channel(panel_key: str, server_id: Optional[str]=None) -> Optional[int]:

    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()

    if server_id:

        cur.execute("SELECT channel_id FROM log_channels WHERE panel_key=? AND server_id=?", (panel_key, server_id))

        row = cur.fetchone()

        if row:

            conn.close(); return int(row[0])

    cur.execute("SELECT channel_id FROM log_channels WHERE panel_key=? AND server_id IS NULL", (panel_key,))

    row = cur.fetchone(); conn.close()

    if row:

        return int(row[0])

    return None

def find_user_by_discord(discord_id: str) -> Optional[Dict[str,str]]:

    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()

    cur.execute("SELECT email, password, panel_key FROM users WHERE discord_id = ?", (discord_id,))

    row = cur.fetchone(); conn.close()

    if not row:

        return None

    return {"email": row[0], "password": row[1], "panel_key": row[2]}

def list_saved_servers(limit: int=100) -> List:

    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()

    cur.execute("SELECT id, panel_key, server_uuid, name, owner_email, owner_discord, created_at FROM servers ORDER BY created_at DESC LIMIT ?", (limit,))

    rows = cur.fetchall(); conn.close()

    return rows

# -------------------------

# Discord bot setup

# -------------------------

intents = discord.Intents.default()

intents.message_content = True

intents.dm_messages = True

intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

tree = bot.tree

# -------------------------

# Utilities: embeds, DM, logs

# -------------------------

def is_admin_user(user: discord.User) -> bool:

    return str(user.id) in ADMINS

def lightning_embed(title: str, description: str, color: int = 0x1E90FF) -> discord.Embed:

    e = discord.Embed(title=title, description=description, color=color)

    e.set_footer(text="⚡ Flash Nodes Deploy")

    return e

async def dm_user_embed(user: discord.User, title: str, description: str, color: int = 0x1E90FF):

    embed = lightning_embed(title, description, color)

    try:

        await user.send(embed=embed)

        return True

    except Exception:

        return False

async def send_log_embed(panel_key: str, server_id: Optional[str], title: str, description: str, color: int = 0x1E90FF):

    channel_id = get_log_channel(panel_key, server_id)

    if not channel_id:

        return

    # fetch channel

    channel = bot.get_channel(channel_id)

    if not channel:

        try:

            channel = await bot.fetch_channel(channel_id)

        except Exception:

            return

    embed = lightning_embed(title, description, color)

    embed.set_footer(text=f"Panel: {panel_key} | Server: {server_id or 'N/A'}")

    try:

        await channel.send(embed=embed)

    except Exception:

        pass

# -------------------------

# Prefix: help (.help)

# -------------------------

@bot.command(name="help")

async def help_command(ctx: commands.Context):

    embed = discord.Embed(title="⚡ Deploy Bot — Help", description="All commands (Prefix + Slash).", color=0x1E90FF)

    embed.add_field(name="Prefix Commands", value=(

        f"`{PREFIX}manage <panel> <server_id>` — Manage server (buttons)\n"

        f"`{PREFIX}manageshare <panel> <server_id>` — Share/revoke interactive\n"

        f"`{PREFIX}shareuser <panel> <server_id> <email> <@member (optional)>` — Quick share\n"

        f"`{PREFIX}revoke <panel> <server_id> <email>` — Revoke share\n"

        f"`{PREFIX}help` — This help"

    ), inline=False)

    embed.add_field(name="Slash Commands (Admin)", value=(

        "/createuser, /createserver, /deleteserver, /viewservers, /setlogchannel, /setserverlog"

    ), inline=False)

    embed.add_field(name="DM Commands (User)", value=(

        "/myservers — see your servers (DM)\n"

        "/myaccount — see your panel account info (DM)\n"

        "/support — contact support (DM)"

    ), inline=False)

    embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/1722/1722667.png")

    await ctx.send(embed=embed)

# -------------------------

# Prefix: manage (with buttons)

# -------------------------

@bot.command(name="manage")

async def manage_cmd(ctx: commands.Context, panel_key: str, server_id: str):

    if panel_key not in PANELS:

        return await ctx.send("❌ Panel key not configured.")

    embed = discord.Embed(title="🖥️ Server Management", description=f"Panel: `{panel_key}`\nServer: `{server_id}`", color=0x1E90FF)

    embed.add_field(name="Controls", value="Start | Stop | Restart | Reinstall | IP | Status | Ping | Share", inline=False)

    class ManageView(discord.ui.View):

        def __init__(self, timeout: Optional[float]=DEFAULT_TIMEOUT):

            super().__init__(timeout=timeout)

        async def perform(self, interaction: discord.Interaction, action: str):

            await interaction.response.defer(ephemeral=True)

            try:

                if action in ("start","stop","restart"):

                    res = await client_api_request(panel_key, f"/servers/{server_id}/power", "POST", {"signal": action})

                    await interaction.followup.send(f"Sent `{action}` — result: `{res}`", ephemeral=True)

                    await send_log_embed(panel_key, server_id, f"Power: {action}", f"Sent `{action}` — result: {res}")

                    await dm_user_embed(interaction.user, f"Action {action.title()} Sent", f"Server `{server_id}` on `{panel_key}` — result: {res}")

                elif action == "reinstall":

                    res = await client_api_request(panel_key, f"/servers/{server_id}/reinstall", "POST")

                    await interaction.followup.send(f"Reinstall requested — {res}", ephemeral=True)

                    await send_log_embed(panel_key, server_id, "Reinstall requested", f"{res}")

                    await dm_user_embed(interaction.user, "Reinstall Requested", f"Server `{server_id}`: {res}")

                elif action == "status":

                    res = await client_api_request(panel_key, f"/servers/{server_id}/resources", "GET")

                    await interaction.followup.send(f"Status: {res}", ephemeral=True)

                    await send_log_embed(panel_key, server_id, "Status", f"{res}")

                elif action == "ip":

                    res = await client_api_request(panel_key, f"/servers/{server_id}/network", "GET")

                    await interaction.followup.send(f"Network: {res}", ephemeral=True)

                    await send_log_embed(panel_key, server_id, "Network", f"{res}")

                elif action == "ping":

                    res = await client_api_request(panel_key, f"/servers/{server_id}/resources", "GET")

                    await interaction.followup.send(f"Ping/Resources: {res}", ephemeral=True)

                    await send_log_embed(panel_key, server_id, "Ping", f"{res}")

                elif action == "share":

                    await interaction.followup.send("Opening share manager...", ephemeral=True)

                    await manageshare_cmd_internal(interaction, panel_key, server_id)

            except Exception as e:

                await interaction.followup.send(f"Error: {e}", ephemeral=True)

        @discord.ui.button(label="Start", style=discord.ButtonStyle.success)

        async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):

            await self.perform(interaction, "start")

        @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)

        async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):

            await self.perform(interaction, "stop")

        @discord.ui.button(label="Restart", style=discord.ButtonStyle.primary)

        async def restart_btn(self, interaction: discord.Interaction, button: discord.ui.Button):

            await self.perform(interaction, "restart")

        @discord.ui.button(label="Reinstall", style=discord.ButtonStyle.secondary)

        async def reinstall_btn(self, interaction: discord.Interaction, button: discord.ui.Button):

            await self.perform(interaction, "reinstall")

        @discord.ui.button(label="IP", style=discord.ButtonStyle.secondary)

        async def ip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):

            await self.perform(interaction, "ip")

        @discord.ui.button(label="Status", style=discord.ButtonStyle.secondary)

        async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):

            await self.perform(interaction, "status")

        @discord.ui.button(label="Ping", style=discord.ButtonStyle.secondary)

        async def ping_btn(self, interaction: discord.Interaction, button: discord.ui.Button):

            await self.perform(interaction, "ping")

        @discord.ui.button(label="Share", style=discord.ButtonStyle.success)

        async def share_btn(self, interaction: discord.Interaction, button: discord.ui.Button):

            await self.perform(interaction, "share")

    await ctx.send(embed=embed, view=ManageView())

# -------------------------

# Share flows (internal + prefix wrapper)

# -------------------------

async def manageshare_cmd_internal(interaction_or_ctx, panel_key: str, server_id: str):

    # works with Interaction or Context

    res = await client_api_request(panel_key, f"/servers/{server_id}/users", "GET")

    subusers = res.get("data", []) if isinstance(res, dict) else []

    emails = [u.get("attributes", {}).get("email", "unknown") for u in subusers]

    embed = discord.Embed(title="Manage Shared Users", description=f"Server `{server_id}` on `{panel_key}`", color=0x1E90FF)

    embed.add_field(name="Shared users", value="\n".join(emails) if emails else "No shared users", inline=False)

    is_interaction = isinstance(interaction_or_ctx, discord.Interaction)

    class ShareView(discord.ui.View):

        @discord.ui.button(label="Add Share User", style=discord.ButtonStyle.success)

        async def add_user(self, inner_interaction: discord.Interaction, button: discord.ui.Button):

            await inner_interaction.response.send_message("Reply with the email to invite (60s).", ephemeral=True)

            def check(m): return m.author.id == inner_interaction.user.id and m.channel.id == inner_interaction.channel_id

            try:

                msg = await bot.wait_for("message", check=check, timeout=DEFAULT_TIMEOUT)

                email = msg.content.strip()

                payload = {"email": email, "permissions": ["control.start","control.stop","control.restart","control.console","websocket.connect"]}

                r = await client_api_request(panel_key, f"/servers/{server_id}/users", "POST", payload)

                await inner_interaction.followup.send(f"Invited `{email}` — result: {r}", ephemeral=True)

                await send_log_embed(panel_key, server_id, "Subuser Invited", f"{email} — {r}")

            except asyncio.TimeoutError:

                await inner_interaction.followup.send("Timed out. Try again.", ephemeral=True)

        @discord.ui.button(label="Revoke User", style=discord.ButtonStyle.danger)

        async def revoke_user(self, inner_interaction: discord.Interaction, button: discord.ui.Button):

            await inner_interaction.response.send_message("Reply with email to revoke (60s).", ephemeral=True)

            def check(m): return m.author.id == inner_interaction.user.id and m.channel.id == inner_interaction.channel_id

            try:

                msg = await bot.wait_for("message", check=check, timeout=DEFAULT_TIMEOUT)

                email = msg.content.strip()

                for u in subusers:

                    if u.get("attributes", {}).get("email") == email:

                        uid = u.get("attributes", {}).get("uuid")

                        r = await client_api_request(panel_key, f"/servers/{server_id}/users/{uid}", "DELETE")

                        await inner_interaction.followup.send(f"Revoked `{email}` — result: {r}", ephemeral=True)

                        await send_log_embed(panel_key, server_id, "Subuser Revoked", f"{email} — {r}")

                        return

                await inner_interaction.followup.send("User not found among subusers.", ephemeral=True)

            except asyncio.TimeoutError:

                await inner_interaction.followup.send("Timed out. Try again.", ephemeral=True)

    view = ShareView()

    if is_interaction:

        await interaction_or_ctx.followup.send(embed=embed, view=view, ephemeral=True)

    else:

        await interaction_or_ctx.send(embed=embed, view=view)

@bot.command(name="manageshare")

async def manageshare_cmd(ctx: commands.Context, panel_key: str, server_id: str):

    await manageshare_cmd_internal(ctx, panel_key, server_id)

@bot.command(name="shareuser")

async def shareuser_cmd(ctx: commands.Context, panel_key: str, server_id: str, email: str, member: Optional[discord.Member]=None):

    payload = {"email": email, "permissions": ["control.start","control.stop","control.restart","control.console","websocket.connect"]}

    r = await client_api_request(panel_key, f"/servers/{server_id}/users", "POST", payload)

    if member:

        conn = sqlite3.connect(DB_PATH); cur = conn.cursor()

        cur.execute("UPDATE users SET discord_id = ? WHERE email = ?", (str(member.id), email))

        conn.commit(); conn.close()

    await ctx.send(f"Share requested: {r}")

    await send_log_embed(panel_key, server_id, "Subuser Shared", f"{email} — {r}")

@bot.command(name="revoke")

async def revoke_cmd(ctx: commands.Context, panel_key: str, server_id: str, email: str):

    res = await client_api_request(panel_key, f"/servers/{server_id}/users", "GET")

    subusers = res.get("data", []) if isinstance(res, dict) else []

    for u in subusers:

        if u.get("attributes", {}).get("email") == email:

            uid = u.get("attributes", {}).get("uuid")

            r = await client_api_request(panel_key, f"/servers/{server_id}/users/{uid}", "DELETE")

            await ctx.send(f"Revoked {email} — result: {r}")

            await send_log_embed(panel_key, server_id, "Subuser Revoked", f"{email} — {r}")

            return

    await ctx.send("No such subuser found.")

# -------------------------

# Slash commands (admin)

# -------------------------

@tree.command(name="createuser", description="Create a Pterodactyl user (admin)")

@app_commands.describe(panel="Panel key", email="Email", password="Password (optional)", firstname="First name", lastname="Last name", is_admin="Grant admin", nickname="Nickname (optional)", discord_member="Discord member to DM/associate")

async def slash_createuser(interaction: discord.Interaction, panel: str, email: str, password: Optional[str], firstname: str, lastname: str, is_admin: bool, nickname: Optional[str], discord_member: Optional[discord.Member]):

    if not is_admin_user(interaction.user):

        return await interaction.response.send_message("❌ Not authorized.", ephemeral=True)

    await interaction.response.defer(thinking=True)

    pwd = password or secrets.token_urlsafe(10)

    username = email.split("@")[0]

    payload = {"email": email, "username": username, "first_name": firstname, "last_name": lastname, "password": pwd}

    res = await app_api_request(panel, "/users", "POST", payload)

    save_created_user(panel, email, pwd, str(discord_member.id) if discord_member else None, nickname)

    # DM command user

    dm_desc = f"User `{email}` created on `{panel}`.\nPassword: ||{pwd}||\nResponse: `{res}`"

    dm_ok = await dm_user_embed(interaction.user, "User Created", dm_desc)

    # DM target user if mention provided

    if discord_member:

        await dm_user_embed(discord_member, "Your Panel Account", f"Email: `{email}`\nPassword: ||{pwd}||\nPanel: `{panel}`")

    await send_log_embed(panel, None, "User Created", dm_desc)

    if dm_ok:

        await interaction.followup.send("✅ User created. Check your DM.", ephemeral=True)

    else:

        await interaction.followup.send(f"✅ User created. DM blocked — response: {res}", ephemeral=True)

@tree.command(name="createserver", description="Create a server (admin)")

@app_commands.describe(panel="Panel key", owner_email="Owner email (or use owner_discord)", owner_discord="Owner Discord (mention)", name="Server name", egg="Egg id", docker_image="Docker image", memory="Memory MB", disk="Disk MB", cpu="CPU limit", startup="Startup command", description="Description")

async def slash_createserver(interaction: discord.Interaction, panel: str, owner_email: Optional[str], owner_discord: Optional[discord.Member], name: str, egg: int, docker_image: str, memory: int, disk: int, cpu: int, startup: str, description: Optional[str]):

    if not is_admin_user(interaction.user):

        return await interaction.response.send_message("❌ Not authorized.", ephemeral=True)

    await interaction.response.defer(thinking=True)

    resolved_owner_email = owner_email

    owner_discord_id = None

    if not resolved_owner_email and owner_discord:

        dbuser = find_user_by_discord(str(owner_discord.id))

        if dbuser:

            resolved_owner_email = dbuser.get("email")

            owner_discord_id = str(owner_discord.id)

    if not resolved_owner_email:

        return await interaction.followup.send("Provide owner_email or mention owner_discord registered in DB.", ephemeral=True)

    payload = {

        "name": name,

        "user": resolved_owner_email,

        "egg": egg,

        "docker_image": docker_image,

        "startup": startup,

        "environment": {},

        "limits": {"memory": memory, "swap": 0, "disk": disk, "io": 500, "cpu": cpu},

        "allocation": {"default": 0},

        "pack": None,

        "feature_limits": {}

    }

    res = await app_api_request(panel, "/servers", "POST", payload)

    server_uuid = None

    if isinstance(res, dict):

        server_uuid = res.get("attributes", {}).get("uuid") or (res.get("object", {}).get("attributes", {}).get("uuid") if res.get("object") else None)

    save_created_server(panel, server_uuid or "unknown", name, resolved_owner_email, owner_discord_id, description)

    # DM command user and owner

    dm_desc = f"Server `{name}` created for `{resolved_owner_email}`\nUUID: `{server_uuid}`\nResponse: `{res}`"

    await dm_user_embed(interaction.user, "Server Created", dm_desc)

    if owner_discord and owner_discord_id:

        await dm_user_embed(owner_discord, "Your Server Created", dm_desc)

    await send_log_embed(panel, server_uuid, "Server Created", dm_desc)

    await interaction.followup.send("✅ Server creation requested. Details sent to DM.", ephemeral=True)

@tree.command(name="deleteserver", description="Delete a server by UUID (admin)")

@app_commands.describe(panel="Panel key", server_uuid="Server UUID")

async def slash_deleteserver(interaction: discord.Interaction, panel: str, server_uuid: str):

    if not is_admin_user(interaction.user):

        return await interaction.response.send_message("❌ Not authorized.", ephemeral=True)

    await interaction.response.defer(thinking=True)

    res = await app_api_request(panel, f"/servers/{server_uuid}", "DELETE")

    desc = f"Delete requested for `{server_uuid}` — response: {res}"

    await dm_user_embed(interaction.user, "Server Delete Requested", desc, color=0xE74C3C)

    await send_log_embed(panel, server_uuid, "Server Delete", desc, color=0xE74C3C)

    await interaction.followup.send("✅ Delete requested. Check your DM.", ephemeral=True)

@tree.command(name="viewservers", description="List servers recorded by bot (admin)")

async def slash_viewservers(interaction: discord.Interaction):

    if not is_admin_user(interaction.user):

        return await interaction.response.send_message("❌ Not authorized.", ephemeral=True)

    rows = list_saved_servers(200)

    if not rows:

        return await interaction.response.send_message("No stored servers.", ephemeral=True)

    text_lines = [f"#{r[0]} | panel:{r[1]} | uuid:{r[2]} | name:{r[3]} | owner:{r[4]}" for r in rows]

    text = "\n".join(text_lines)

    # DM in chunks (Discord message limit)

    for chunk in [text[i:i+1900] for i in range(0, len(text), 1900)]:

        try:

            await interaction.user.send(f"Servers:\n{chunk}")

        except Exception:

            pass

    await interaction.response.send_message("Sent server list to your DMs.", ephemeral=True)

# -------------------------

# Log-channel slash commands

# -------------------------

@tree.command(name="setlogchannel", description="Set panel-level log channel (admin)")

@app_commands.describe(panel="Panel key", channel="Discord channel")

async def slash_setlogchannel(interaction: discord.Interaction, panel: str, channel: discord.TextChannel):

    if not is_admin_user(interaction.user):

        return await interaction.response.send_message("❌ Not authorized.", ephemeral=True)

    set_log_channel(panel, channel.id, None)

    await interaction.response.send_message(f"✅ Panel `{panel}` logs set to {channel.mention}", ephemeral=True)

@tree.command(name="setserverlog", description="Set server-level log channel (admin)")

@app_commands.describe(panel="Panel key", server_id="Server ID/UUID", channel="Discord channel")

async def slash_setserverlog(interaction: discord.Interaction, panel: str, server_id: str, channel: discord.TextChannel):

    if not is_admin_user(interaction.user):

        return await interaction.response.send_message("❌ Not authorized.", ephemeral=True)

    set_log_channel(panel, channel.id, server_id)

    await interaction.response.send_message(f"✅ Server `{server_id}` logs set to {channel.mention}", ephemeral=True)

# -------------------------

# DM slash commands for users

# -------------------------

@tree.command(name="myservers", description="List your servers (DM)")

async def slash_myservers(interaction: discord.Interaction):

    await interaction.response.defer(ephemeral=True)

    # find by discord id in DB

    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()

    cur.execute("SELECT server_uuid, name, panel_key FROM servers WHERE owner_discord = ?", (str(interaction.user.id),))

    rows = cur.fetchall(); conn.close()

    if not rows:

        # reply ephemeral and attempt DM

        await interaction.followup.send("You have no servers recorded. Attempting to DM details...", ephemeral=True)

        await dm_user_embed(interaction.user, "Your Servers", "No servers recorded for your Discord account.")

        return

    text = "\n".join([f"{r[1]} (UUID: {r[0]}) — Panel: {r[2]}" for r in rows])

    ok = await dm_user_embed(interaction.user, "Your Servers", text)

    if ok:

        await interaction.followup.send("✅ Sent your servers to DM.", ephemeral=True)

    else:

        await interaction.followup.send(f"✅ Here are your servers:\n{text}", ephemeral=True)

@tree.command(name="myaccount", description="Show your panel account info (DM)")

async def slash_myaccount(interaction: discord.Interaction):

    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()

    cur.execute("SELECT email, panel_key, nickname FROM users WHERE discord_id = ?", (str(interaction.user.id),))

    row = cur.fetchone(); conn.close()

    if not row:

        await interaction.response.send_message("No account linked. An admin must create and link a panel user to your Discord.", ephemeral=True)

        return

    email, panel_key, nickname = row

    text = f"Email: {email}\nPanel: {panel_key}\nNickname: {nickname or '—'}"

    ok = await dm_user_embed(interaction.user, "Your Panel Account", text)

    if ok:

        await interaction.response.send_message("✅ Sent account info to DM.", ephemeral=True)

    else:

        await interaction.response.send_message(f"Account info:\n{text}", ephemeral=True)

@tree.command(name="support", description="Contact support (DM)")

@app_commands.describe(message="Describe your issue")

async def slash_support(interaction: discord.Interaction, message: str):

    await interaction.response.defer(thinking=True)

    # DM to user

    ok = await dm_user_embed(interaction.user, "Support Request Received", f"Message: {message}\nOur staff will contact you soon.")

    # Log it to admin channels across configured panels

    for panel_key in PANELS:

        await send_log_embed(panel_key, None, "Support Request", f"User: {interaction.user} ({interaction.user.id})\nMessage: {message}")

    if ok:

        await interaction.followup.send("✅ Support request received. Check your DM.", ephemeral=True)

    else:

        await interaction.followup.send("✅ Support request received. DM blocked — noted.", ephemeral=True)

# -------------------------

# DM receive handler (also replies)

# -------------------------

@bot.event

async def on_message(message: discord.Message):

    # If DM and not bot

    if message.guild is None and not message.author.bot:

        print(f"💬 DM from {message.author}: {message.content}")

        # send confirmation to user

        try:

            await message.channel.send("👋 Got your DM! Our Flash Nodes team will respond soon.")

        except Exception:

            pass

        # forward DM to panel-level log channels (broadcast to all panels configured)

        for panel_key in PANELS:

            await send_log_embed(panel_key, None, "User DM Received", f"From: {message.author} ({message.author.id})\nContent: {message.content}")

    await bot.process_commands(message)

# -------------------------

# On ready — set status & sync

# -------------------------

@bot.event

async def on_ready():

    # ensure presence shows Watching Flash Nodes...

    try:

        await bot.change_presence(

            status=discord.Status.online,

            activity=discord.Activity(

                type=discord.ActivityType.watching,

                name="⚡ Flash Nodes | Best Uptime Hosting | Free Hosting"

            )

        )

    except Exception:

        pass

    # sync commands

    try:

        await tree.sync()

    except Exception:

        pass

    print(f"✅ Logged in as {bot.user} — Watching Flash Nodes | Best Uptime Hosting | Free Hosting")

# -------------------------

# Run

# -------------------------

bot.run(TOKEN)