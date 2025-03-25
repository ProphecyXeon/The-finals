import sqlite3
import json
import os
import re
import requests
import discord
from discord import app_commands
from discord.ext import tasks
from keep_alive import keep_alive

# --- Konfiguration ---
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1351070896441528351
VERIFY_CHANNEL_ID = 1351657754888110193
VERIFIED_ROLE_ID = 1351658061067976755
ADMIN_ID = 598187531040718900  # Deine eigene Discord-ID
RANK_ROLE_IDS = {
    "Gold": 1351088401880977419,
    "Platinum": 1351088645120987196,
    "Diamond": 1351088880715042906,
    "Ruby": 1351089295238103122
}
DB_FILE = "verified_users.db"

# --- Datenbank ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS verified_users (
                        user_id TEXT PRIMARY KEY,
                        player_name TEXT NOT NULL
                    )""")
    conn.commit()
    conn.close()

def get_verified_users():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, player_name FROM verified_users")
    users = cursor.fetchall()
    conn.close()
    return {user_id: name for user_id, name in users}

def save_verified_user(user_id, player_name):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO verified_users (user_id, player_name) VALUES (?, ?)", (user_id, player_name))
    conn.commit()
    conn.close()
    print(f"[✅ DB] Gespeichert: {user_id} → {player_name}")

def remove_verified_user_by_name(player_name):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM verified_users WHERE player_name = ?", (player_name,))
    conn.commit()
    removed = cursor.rowcount
    conn.close()
    print(f"[🗑️ DB] Entfernt: {player_name} ({removed} Einträge)")
    return removed > 0

# --- Discord Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

class VerifyModal(discord.ui.Modal, title="Verifizierung"):
    def __init__(self, user):
        super().__init__()
        self.user = user

    name_input = discord.ui.TextInput(label="Gib deinen *The Finals*-Namen ein", placeholder="ProphecyXeon", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        player_name = self.name_input.value.strip()
        player_data = get_player_data(player_name)
        if not player_data:
            await interaction.followup.send("❌ Kein Spieler mit diesem Namen gefunden.", ephemeral=True)
            return

        guild = interaction.guild
        member = interaction.user
        league = player_data.get("league", "Unbekannt").split()[0]
        rank_role_id = RANK_ROLE_IDS.get(league)
        rank_role = guild.get_role(rank_role_id) if rank_role_id else None
        verified_role = guild.get_role(VERIFIED_ROLE_ID)

        current_rank_roles = [r for r in member.roles if r.id in RANK_ROLE_IDS.values()]
        if current_rank_roles:
            await member.remove_roles(*current_rank_roles)

        if verified_role:
            await member.add_roles(verified_role)
        if rank_role:
            await member.add_roles(rank_role)

        try:
            await member.edit(nick=player_name)
        except Exception as e:
            print(f"[⚠️ Nickname] {e}")

        save_verified_user(str(member.id), player_name)
        await interaction.followup.send(f"✅ Verifiziert als {player_name} – Liga: **{league}**", ephemeral=True)

class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__()
    @discord.ui.button(label="Verifizieren", style=discord.ButtonStyle.green)
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal(interaction.user))

class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.synced = False

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)

        @self.tree.command(name="rankcheck", description="Zeigt dein aktuelles Ranking", guild=guild)
        @app_commands.describe(player="Spielername", privat="Nur du siehst die Antwort?")
        async def rankcheck(interaction: discord.Interaction, player: str, privat: bool = False):
            player_data = get_player_data(player)
            if not player_data:
                await interaction.response.send_message("❌ Spieler nicht gefunden.", ephemeral=privat)
                return
            msg = (
                f"🔹 **Spieler:** {player_data['name']}\n"
                f"🏆 **Rang:** {player_data.get('rank', '?')}\n"
                f"💎 **Liga:** {player_data.get('league', '?')}\n"
                f"🔢 **Punkte:** {player_data.get('rankScore', '?')}"
            )
            await interaction.response.send_message(msg, ephemeral=privat)

        @self.tree.command(name="list_users", description="Zeigt alle verifizierten Spieler", guild=guild)
        async def list_users(interaction: discord.Interaction):
            if interaction.user.id != ADMIN_ID:
                await interaction.response.send_message("🚫 Keine Berechtigung!", ephemeral=True)
                return
            users = get_verified_users()
            if not users:
                await interaction.response.send_message("📭 Keine verifizierten Benutzer.", ephemeral=True)
                return
            text = "\n".join([f"<@{uid}> → `{name}`" for uid, name in users.items()])
            await interaction.response.send_message(f"📋 Verifizierte Nutzer:\n{text}", ephemeral=True)

        @self.tree.command(name="remove_user", description="Löscht einen verifizierten Spieler (nach Name)", guild=guild)
        @app_commands.describe(name="Spielername")
        async def remove_user(interaction: discord.Interaction, name: str):
            if interaction.user.id != ADMIN_ID:
                await interaction.response.send_message("🚫 Keine Berechtigung!", ephemeral=True)
                return
            result = remove_verified_user_by_name(name)
            msg = f"✅ **{name}** wurde entfernt." if result else f"❌ Spieler **{name}** nicht gefunden."
            await interaction.response.send_message(msg, ephemeral=True)

        await self.tree.sync(guild=guild)
        print("✅ Slash-Befehle synchronisiert.")

    async def on_ready(self):
        print(f"✅ Bot ist online als {self.user}")
        channel = self.get_channel(VERIFY_CHANNEL_ID)
        if channel:
            await channel.purge(limit=5)
            await channel.send("🔒 Bitte verifiziere dich:", view=VerifyButton())
        update_roles_task.start(self)

# --- API ---
def get_player_data(player_name):
    clean_name = re.sub(r'#\d+', '', player_name).strip()
    url = f"https://api.the-finals-leaderboard.com/v1/leaderboard/s6/crossplay?name={clean_name}"
    print(f"🌐 Anfrage an API: {url}")
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data["data"][0] if data.get("data") else None
    return None

# --- Rollen-Aktualisierung alle 30 Minuten ---
@tasks.loop(minutes=30)
async def update_roles_task(bot: MyBot):
    print("🔄 Starte automatische Rollen-Aktualisierung ...")
    guild = bot.get_guild(GUILD_ID)
    users = get_verified_users()
    for user_id, player_name in users.items():
        member = guild.get_member(int(user_id))
        if not member:
            continue
        player_data = get_player_data(player_name)
        if not player_data:
            continue
        league = player_data.get("league", "").split()[0]
        rank_role_id = RANK_ROLE_IDS.get(league)
        rank_role = guild.get_role(rank_role_id) if rank_role_id else None
        current_roles = [r for r in member.roles if r.id in RANK_ROLE_IDS.values()]
        if current_roles:
            await member.remove_roles(*current_roles)
        if rank_role:
            await member.add_roles(rank_role)
            print(f"✅ Aktualisiert: {member.name} → {league}")
        else:
            print(f"⚠️ Keine Liga-Rolle gefunden für {player_name}")

# --- Main ---
init_db()
bot = MyBot()
keep_alive()
bot.run(TOKEN)
