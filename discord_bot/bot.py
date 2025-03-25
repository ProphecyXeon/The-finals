import discord
from discord import app_commands
import requests
import re
import os
import sqlite3
import asyncio
from discord.ext import tasks
from keep_alive import keep_alive

# CONFIG
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1351070896441528351
VERIFY_CHANNEL_ID = 1351657754888110193
VERIFIED_ROLE_ID = 1351658061067976755
RANK_ROLE_IDS = {
    "Gold": 1351088401880977419,
    "Platinum": 1351088645120987196,
    "Diamond": 1351088880715042906,
    "Ruby": 1351089295238103122
}
ADMIN_ID = 598187531040718900  # Deine Discord-ID

# Datenbank Setup
def init_db():
    conn = sqlite3.connect("verified_users.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            player_name TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_user(user_id, player_name):
    conn = sqlite3.connect("verified_users.db")
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO users (user_id, player_name) VALUES (?, ?)", (user_id, player_name))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect("verified_users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    rows = cursor.fetchall()
    conn.close()
    return rows

def delete_user_by_name(name):
    conn = sqlite3.connect("verified_users.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE player_name = ?", (name,))
    conn.commit()
    conn.close()

def clear_users():
    conn = sqlite3.connect("verified_users.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users")
    conn.commit()
    conn.close()

# API
def get_player_data(player_name):
    clean_name = re.sub(r'#\d+', '', player_name).strip()
    url = f"https://api.the-finals-leaderboard.com/v1/leaderboard/s6/crossplay?name={clean_name}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if "data" in data and len(data["data"]) > 0:
            return data["data"][0]
    return None

# Modal
class VerifyModal(discord.ui.Modal, title="Verifizierung"):
    def __init__(self, user):
        super().__init__()
        self.user = user

    name_input = discord.ui.TextInput(
        label="Gib deinen *The Finals*-Namen ein",
        placeholder="z. B. ProphecyXeon",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        player_name = self.name_input.value.strip()
        player_data = get_player_data(player_name)
        if not player_data:
            await interaction.response.send_message("❌ Kein Spieler gefunden.", ephemeral=True)
            return

        guild = interaction.guild
        member = interaction.user
        league = player_data.get("league", "Unbekannt").split()[0]
        rank_role_id = RANK_ROLE_IDS.get(league)
        verified_role = guild.get_role(VERIFIED_ROLE_ID)
        rank_role = guild.get_role(rank_role_id) if rank_role_id else None

        if verified_role:
            await member.add_roles(verified_role)
        if rank_role:
            await member.add_roles(rank_role)
        try:
            await member.edit(nick=player_name)
        except:
            pass

        save_user(str(member.id), player_name)
        await interaction.response.send_message(f"✅ Verifiziert als **{player_name}** – Liga **{league}**", ephemeral=True)

# Button View
class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__()

    @discord.ui.button(label="Verifizieren", style=discord.ButtonStyle.green)
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal(interaction.user))

# Discord Client
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)

        @self.tree.command(name="rankcheck", description="Zeigt dein Ranking", guild=guild)
        @app_commands.describe(player="Dein Spielername")
        async def rankcheck(interaction: discord.Interaction, player: str):
            player_data = get_player_data(player)
            if not player_data:
                await interaction.response.send_message("❌ Spieler nicht gefunden.", ephemeral=True)
                return

            msg = (
                f"🔹 **Spieler:** {player_data['name']}\n"
                f"🏆 **Rang:** {player_data['rank']}\n"
                f"💎 **Liga:** {player_data['league']}\n"
                f"🔢 **Punkte:** {player_data.get('rankScore', 'Unbekannt')}"
            )
            await interaction.response.send_message(msg, ephemeral=False)

        # Admin-only
        @self.tree.command(name="list_users", description="Alle verifizierten User", guild=guild)
        async def list_users(interaction: discord.Interaction):
            if interaction.user.id != ADMIN_ID:
                await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)
                return
            users = get_all_users()
            if not users:
                await interaction.response.send_message("Keine verifizierten User.", ephemeral=True)
                return
            message = "\n".join([f"{u[0]} – {u[1]}" for u in users])
            await interaction.response.send_message(f"📄 Verifizierte:\n{message}", ephemeral=True)

        @self.tree.command(name="remove_user", description="Lösche einen Spieler", guild=guild)
        @app_commands.describe(player="Spielername")
        async def remove_user(interaction: discord.Interaction, player: str):
            if interaction.user.id != ADMIN_ID:
                await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)
                return
            delete_user_by_name(player)
            await interaction.response.send_message(f"❌ {player} wurde gelöscht.", ephemeral=True)

        @self.tree.command(name="clear_users", description="Löscht alle verifizierten", guild=guild)
        async def clear_users_cmd(interaction: discord.Interaction):
            if interaction.user.id != ADMIN_ID:
                await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)
                return
            clear_users()
            await interaction.response.send_message("⚠️ Alle verifizierten User wurden gelöscht.", ephemeral=True)

        await self.tree.sync(guild=guild)

    async def on_ready(self):
        print(f"✅ Bot ist online als {self.user}")
        channel = self.get_channel(VERIFY_CHANNEL_ID)
        if channel:
            await channel.purge(limit=5)
            await channel.send("**🔒 Bitte verifiziere dich:**", view=VerifyButton())
        update_roles.start(self)

# Hintergrund-Task
@tasks.loop(minutes=30)
async def update_roles(bot):
    print("🔄 Starte automatische Rollen-Aktualisierung...")
    guild = bot.get_guild(GUILD_ID)
    users = get_all_users()
    for user_id, player_name in users:
        member = guild.get_member(int(user_id))
        if not member:
            continue
        data = get_player_data(player_name)
        if not data:
            continue
        league = data.get("league", "Unbekannt").split()[0]
        rank_role_id = RANK_ROLE_IDS.get(league)
        if not rank_role_id:
            continue
        rank_role = guild.get_role(rank_role_id)
        if not rank_role:
            continue
        current_roles = [r for r in member.roles if r.id in RANK_ROLE_IDS.values()]
        if current_roles:
            await member.remove_roles(*current_roles)
        await member.add_roles(rank_role)
        print(f"✅ Rolle von {player_name} aktualisiert zu {rank_role.name}")

# Starte Bot
init_db()
keep_alive()
bot = MyBot()
bot.run(TOKEN)


