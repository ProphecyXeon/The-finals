import discord
from discord import app_commands
import requests
import re
import os
import psycopg2
from flask import Flask
from threading import Thread
import asyncio

# --- ENV-VARIABLEN ---
TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

# --- DISCORD KONFIG ---
GUILD_ID = 1351070896441528351
VERIFY_CHANNEL_ID = 1351657754888110193
VERIFIED_ROLE_ID = 1351658061067976755
RANK_ROLE_IDS = {
    "Gold": 1351088401880977419,
    "Platinum": 1351088645120987196,
    "Diamond": 1351088880715042906,
    "Ruby": 1351089295238103122
}

# --- DB FUNKTIONEN ---
def connect_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS verified_users (
            user_id BIGINT PRIMARY KEY,
            player_name TEXT NOT NULL
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

def save_user(user_id, player_name):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO verified_users (user_id, player_name)
        VALUES (%s, %s)
        ON CONFLICT (user_id)
        DO UPDATE SET player_name = EXCLUDED.player_name;
    """, (user_id, player_name))
    conn.commit()
    cur.close()
    conn.close()

def get_user(user_id):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT player_name FROM verified_users WHERE user_id = %s;", (user_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result[0] if result else None

def delete_user_by_name(name):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("DELETE FROM verified_users WHERE player_name ILIKE %s;", (name,))
    conn.commit()
    deleted = cur.rowcount
    cur.close()
    conn.close()
    return deleted

def get_all_users():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT user_id, player_name FROM verified_users;")
    result = cur.fetchall()
    cur.close()
    conn.close()
    return result

# --- DISCORD BOT SETUP ---
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

class VerifyModal(discord.ui.Modal, title="Verifizierung"):
    def __init__(self, user):
        super().__init__(timeout=None)
        self.user = user

    name_input = discord.ui.TextInput(
        label="Gib deinen *The Finals*-Namen ein",
        placeholder="ProphecyXeon",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        print(f"🔧 [Modal Submit] Nutzer: {interaction.user.name} ({interaction.user.id})")
        await interaction.response.defer(ephemeral=True)

        player_name = self.name_input.value.strip()
        player_data = get_player_data(player_name)
        if not player_data:
            await interaction.followup.send("❌ Kein Spieler mit diesem Namen gefunden.", ephemeral=True)
            return

        guild = interaction.guild
        member = interaction.user
        verified_role = guild.get_role(VERIFIED_ROLE_ID)
        league = player_data.get("league", "Unbekannt")
        normalized_league = league.split()[0]
        rank_role_id = RANK_ROLE_IDS.get(normalized_league)
        rank_role = guild.get_role(rank_role_id) if rank_role_id else None

        old_name = get_user(member.id)
        if old_name and old_name != player_name:
            await interaction.followup.send(
                f"❌ Du bist bereits als **{old_name}** verifiziert! Bitte kontaktiere einen Admin.",
                ephemeral=True
            )
            return

        try:
            await member.remove_roles(*[r for r in member.roles if r.id in RANK_ROLE_IDS.values()])
            if verified_role:
                await member.add_roles(verified_role)
            if rank_role:
                await member.add_roles(rank_role)
            await member.edit(nick=player_name)
        except discord.Forbidden:
            print("⚠️ Keine Berechtigung zum Ändern von Rollen/Nickname.")
        except Exception as e:
            print(f"❌ Fehler beim Anwenden der Rollen: {e}")

        save_user(member.id, player_name)
        print(f"✅ Gespeichert: {member.name} → {player_name}")

        await interaction.followup.send(
            f"✅ Verifiziert als **{player_data['name']}** – Liga **{rank_role.name if rank_role else 'Unbekannt'}**.",
            ephemeral=True
        )

class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verifizieren", style=discord.ButtonStyle.green)
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        print(f"👆 Button geklickt von: {interaction.user}")
        await interaction.response.send_modal(VerifyModal(interaction.user))

class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)

        @self.tree.command(name="rankcheck", description="Zeigt dein The Finals Ranking", guild=guild)
        @app_commands.describe(player="Spielername")
        async def rankcheck(interaction: discord.Interaction, player: str):
            data = get_player_data(player)
            if not data:
                await interaction.response.send_message("❌ Spieler nicht gefunden.", ephemeral=True)
                return
            msg = (
                f"🔹 **Spieler:** {data.get('name')}\n"
                f"🏆 **Rang:** {data.get('rank')}\n"
                f"💎 **Liga:** {data.get('league')}\n"
                f"🔢 **Punkte:** {data.get('rankScore')}"
            )
            await interaction.response.send_message(msg, ephemeral=False)

        @self.tree.command(name="list_users", description="Zeigt alle verifizierten User", guild=guild)
        async def list_users(interaction: discord.Interaction):
            if interaction.user.id != OWNER_ID:
                await interaction.response.send_message("❌ Nur für Admins!", ephemeral=True)
                return
            entries = get_all_users()
            if not entries:
                await interaction.response.send_message("📭 Keine gespeicherten Nutzer.")
                return
            msg = "\n".join(f"`{uid}` → **{name}**" for uid, name in entries)
            await interaction.response.send_message(f"📄 **Verifizierte Nutzer:**\n{msg}")

        @self.tree.command(name="delete_user", description="Löscht einen Nutzer aus der DB", guild=guild)
        @app_commands.describe(name="Spielername")
        async def delete_user(interaction: discord.Interaction, name: str):
            if interaction.user.id != OWNER_ID:
                await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
                return
            count = delete_user_by_name(name)
            await interaction.response.send_message(
                f"🗑️ {count} Nutzer{' wurde' if count == 1 else ' wurden'} gelöscht." if count else "❌ Kein Eintrag gefunden."
            )

        await self.tree.sync(guild=guild)

        # Start der Hintergrundaufgabe
        self.loop.create_task(update_roles_periodically(self))

    async def on_ready(self):
        print(f"✅ Bot online als {self.user}")
        channel = self.get_channel(VERIFY_CHANNEL_ID)
        if channel:
            await channel.purge(limit=5)
            await channel.send(
                "**🔒 Verifiziere dich mit deinem *The Finals*-Namen!**",
                view=VerifyButton()
            )

# --- API ---
def get_player_data(name):
    clean_name = re.sub(r'#\d+', '', name).strip()
    url = f"https://api.the-finals-leaderboard.com/v1/leaderboard/s6/crossplay?name={clean_name}"
    print(f"🔍 API Request: {url}")
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            json_data = response.json()
            if "data" in json_data and len(json_data["data"]) > 0:
                return json_data["data"][0]
    except Exception as e:
        print(f"❌ API Fehler: {e}")
    return None

# --- Hintergrundaufgabe ---
async def update_roles_periodically(bot):
    await bot.wait_until_ready()
    while not bot.is_closed():
        print("⏳ Starte automatische Rollenüberprüfung...")
        guild = bot.get_guild(GUILD_ID)
        if guild:
            users = get_all_users()
            for user_id, name in users:
                member = guild.get_member(user_id)
                if member:
                    data = get_player_data(name)
                    if data:
                        league = data.get("league", "Unbekannt")
                        normalized_league = league.split()[0]
                        role_id = RANK_ROLE_IDS.get(normalized_league)
                        if role_id:
                            new_role = guild.get_role(role_id)
                            current_roles = [r for r in member.roles if r.id in RANK_ROLE_IDS.values()]
                            try:
                                await member.remove_roles(*current_roles)
                                await member.add_roles(new_role)
                                print(f"✅ Rolle aktualisiert für {name}: {new_role.name}")
                            except Exception as e:
                                print(f"⚠️ Fehler beim Aktualisieren von {name}: {e}")
        await asyncio.sleep(1800)  # 30 Minuten

# --- Flask Server ---
app = Flask('')

@app.route('/')
def home():
    return "I'm alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    Thread(target=run).start()

# --- MAIN ---
connect_db()
keep_alive()
bot = MyBot()
bot.run(TOKEN)