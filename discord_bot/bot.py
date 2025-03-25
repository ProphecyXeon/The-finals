import discord
from discord import app_commands
import requests
import re
import json
import os
import asyncio
from keep_alive import keep_alive
from datetime import datetime

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1351070896441528351
VERIFY_CHANNEL_ID = 1351657754888110193
ADMIN_ROLE_ID = 1351089469389930519  # Nur diese Rolle darf JSON verwalten

VERIFIED_ROLE_ID = 1351658061067976755
RANK_ROLE_IDS = {
    "Gold": 1351088401880977419,
    "Platinum": 1351088645120987196,
    "Diamond": 1351088880715042906,
    "Ruby": 1351089295238103122
}

VERIFIED_USERS_FILE = "verified_users.json"

def load_verified_users():
    if not os.path.exists(VERIFIED_USERS_FILE):
        return {}
    try:
        with open(VERIFIED_USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Fehler beim Laden von JSON: {e}")
        return {}

def save_verified_users(data):
    try:
        with open(VERIFIED_USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        print(f"✅ JSON gespeichert ({len(data)} Nutzer)")
    except Exception as e:
        print(f"❌ Fehler beim Speichern von JSON: {e}")

verified_users = load_verified_users()

def get_player_data(player_name):
    clean_name = re.sub(r'#\d+', '', player_name).strip()
    url = f"https://api.the-finals-leaderboard.com/v1/leaderboard/s6/crossplay?name={clean_name}"
    print(f"🔍 API-Request: {url}")
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "data" in data and len(data["data"]) > 0:
                return data["data"][0]
    except Exception as e:
        print(f"❌ API-Fehler: {e}")
    print("❌ Kein Spieler gefunden")
    return None

class VerifyModal(discord.ui.Modal, title="Verifizierung"):
    def __init__(self, user):
        super().__init__()
        self.user = user

    name_input = discord.ui.TextInput(
        label="Gib deinen *The Finals*-Namen ein",
        placeholder="ProphecyXeon",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            player_name = self.name_input.value.strip()
            print(f"📝 Verifizierung für {interaction.user} mit Namen: {player_name}")
            await interaction.response.defer(ephemeral=True)

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

            # Immer überschreiben
            current_rank_roles = [r for r in member.roles if r.id in RANK_ROLE_IDS.values()]
            if current_rank_roles:
                await member.remove_roles(*current_rank_roles)

            await member.add_roles(verified_role)
            if rank_role:
                await member.add_roles(rank_role)

            try:
                await member.edit(nick=player_name)
            except discord.Forbidden:
                print("⚠️ Keine Berechtigung zum Nickname ändern.")

            verified_users[str(member.id)] = player_name
            save_verified_users(verified_users)

            await interaction.followup.send(
                f"✅ Verifiziert als {player_data['name']} – Liga **{league}**.",
                ephemeral=True
            )
        except Exception as e:
            print(f"❌ Fehler in Modal: {e}")
            await interaction.followup.send("❌ Fehler bei der Verifizierung.", ephemeral=True)

class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verifizieren", style=discord.ButtonStyle.green)
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            print(f"🔘 Button gedrückt von {interaction.user} (ID: {interaction.user.id})")
            await interaction.response.send_modal(VerifyModal(interaction.user))
            print("✅ Modal gesendet")
        except discord.HTTPException as e:
            print(f"❌ HTTPException beim Button: {e}")
        except Exception as e:
            print(f"❌ Fehler im Button-Handler: {e}")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)

        @self.tree.command(name="rankcheck", description="Zeigt dein aktuelles The Finals Ranking an", guild=guild)
        @app_commands.describe(player="Spielername")
        async def rankcheck(interaction: discord.Interaction, player: str):
            data = get_player_data(player)
            if not data:
                await interaction.response.send_message("❌ Spieler nicht gefunden.", ephemeral=False)
                return
            msg = (
                f"🔹 **Spieler:** {data['name']}\n"
                f"🏆 **Rang:** {data['rank']}\n"
                f"💎 **Liga:** {data['league']}\n"
                f"🔢 **Punkte:** {data.get('rankScore', 'Unbekannt')}"
            )
            await interaction.response.send_message(msg, ephemeral=False)

        @self.tree.command(name="showjson", description="Zeigt gespeicherte Verifizierungen", guild=guild)
        async def showjson(interaction: discord.Interaction):
            if ADMIN_ROLE_ID not in [r.id for r in interaction.user.roles]:
                await interaction.response.send_message("🚫 Keine Berechtigung", ephemeral=True)
                return
            if not verified_users:
                await interaction.response.send_message("📭 Keine Einträge vorhanden.", ephemeral=True)
                return
            text = "\n".join([f"{k}: {v}" for k, v in verified_users.items()])
            await interaction.response.send_message(f"📄 Verifizierte Nutzer:\n{text}", ephemeral=True)

        @self.tree.command(name="removeuser", description="Löscht einen Nutzer aus der JSON-Datei", guild=guild)
        @app_commands.describe(userid="Die Discord-ID oder Name des Nutzers")
        async def removeuser(interaction: discord.Interaction, userid: str):
            if ADMIN_ROLE_ID not in [r.id for r in interaction.user.roles]:
                await interaction.response.send_message("🚫 Keine Berechtigung", ephemeral=True)
                return

            removed = False
            if userid in verified_users:
                del verified_users[userid]
                removed = True
            else:
                for k, v in list(verified_users.items()):
                    if v.lower() == userid.lower():
                        del verified_users[k]
                        removed = True
                        break

            if removed:
                save_verified_users(verified_users)
                await interaction.response.send_message("🗑️ Nutzer gelöscht.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Nutzer nicht gefunden.", ephemeral=True)

        await self.tree.sync(guild=guild)

    async def on_ready(self):
        print(f"✅ Bot online als {self.user}")
        await self.wait_until_ready()
        await self.send_verification_view()
        self.bg_task = self.loop.create_task(self.auto_update_roles())

    async def send_verification_view(self):
        channel = self.get_channel(VERIFY_CHANNEL_ID)
        if channel:
            await channel.purge(limit=5)
            await channel.send(
                "**🔒 Willkommen! Bitte verifiziere dich mit deinem *The Finals*-Namen!**",
                view=VerifyButton()
            )

    async def auto_update_roles(self):
        await self.wait_until_ready()
        guild = self.get_guild(GUILD_ID)
        while True:
            print(f"🔁 Starte Auto-Update: {datetime.now()}")
            for uid, pname in verified_users.items():
                member = guild.get_member(int(uid))
                if not member:
                    print(f"⚠️ Mitglied nicht gefunden: {uid}")
                    continue
                data = get_player_data(pname)
                if not data:
                    continue
                league = data.get("league", "Unbekannt").split()[0]
                role_id = RANK_ROLE_IDS.get(league)
                if role_id:
                    new_role = guild.get_role(role_id)
                    await member.remove_roles(*[r for r in member.roles if r.id in RANK_ROLE_IDS.values()])
                    await member.add_roles(new_role)
                    print(f"🔄 {pname} → Neue Rolle: {league}")
            await asyncio.sleep(1800)  # Alle 30 Minuten

bot = MyBot()
keep_alive()
bot.run(TOKEN)
