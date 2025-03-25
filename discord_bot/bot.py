import discord
from discord import app_commands
import requests
import re
import json
import os
from keep_alive import keep_alive

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

VERIFIED_USERS_FILE = "verified_users.json"

def load_verified_users():
    if not os.path.exists(VERIFIED_USERS_FILE):
        return {}
    try:
        with open(VERIFIED_USERS_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError:
        print("❌ Fehler: verified_users.json ist beschädigt.")
        return {}

def save_verified_users(data):
    try:
        with open(VERIFIED_USERS_FILE, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)
        print("✅ JSON erfolgreich gespeichert:", data)
    except Exception as e:
        print(f"❌ Fehler beim Speichern der JSON-Datei: {e}")

verified_users = load_verified_users()

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

            current_rank_roles = [role for role in member.roles if role.id in RANK_ROLE_IDS.values()]
            if current_rank_roles:
                await member.remove_roles(*current_rank_roles)

            if verified_role:
                await member.add_roles(verified_role)

            if rank_role:
                await member.add_roles(rank_role)
                try:
                    await member.edit(nick=player_name)
                except discord.Forbidden:
                    print("⚠️ Keine Berechtigung zum Ändern des Nicknames.")
                except Exception as e:
                    print(f"❌ Fehler beim Nickname ändern: {e}")

            verified_users[str(member.id)] = player_name
            save_verified_users(verified_users)

            await interaction.followup.send(
                f"✅ Verifiziert als {player_data['name']} – Liga **{rank_role.name if rank_role else 'Unbekannt'}**.",
                ephemeral=True
            )
        except Exception as e:
            print(f"❌ Fehler in VerifyModal: {e}")
            await interaction.followup.send("❌ Ein Fehler ist aufgetreten.", ephemeral=True)

class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__()

    @discord.ui.button(label="Verifizieren", style=discord.ButtonStyle.green)
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal(interaction.user))

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

        # /rankcheck
        @self.tree.command(name="rankcheck", description="Zeigt dein aktuelles The Finals Ranking an", guild=guild)
        @app_commands.describe(player="Dein Spielername", privat="Nur du kannst die Antwort sehen?")
        async def rankcheck(interaction: discord.Interaction, player: str, privat: bool = True):
            player_data = get_player_data(player)
            if not player_data:
                await interaction.response.send_message("❌ Spieler nicht gefunden.", ephemeral=privat)
                return

            name = player_data.get("name", "Unbekannt")
            rank = player_data.get("rank", "Unbekannt")
            league = player_data.get("league", "Unbekannt")
            rating = player_data.get("rankScore", "Unbekannt")

            msg = (
                f"🔹 **Spieler:** {name}\n"
                f"🏆 **Rang:** {rank}\n"
                f"💎 **Liga:** {league}\n"
                f"🔢 **Punkte:** {rating}"
            )
            await interaction.response.send_message(msg, ephemeral=privat)

        # /removejson
        @self.tree.command(name="removejson", description="Entfernt einen Nutzer aus der JSON-Datei", guild=guild)
        @app_commands.describe(user="Wähle den Nutzer, der entfernt werden soll")
        async def removejson(interaction: discord.Interaction, user: discord.User):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Du brauchst Administratorrechte!", ephemeral=True)
                return

            if str(user.id) in verified_users:
                del verified_users[str(user.id)]
                save_verified_users(verified_users)
                await interaction.response.send_message(f"🗑️ Nutzer **{user.name}** wurde entfernt.", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ Nutzer **{user.name}** ist nicht in der JSON-Datei.", ephemeral=True)

        # /debug
        @self.tree.command(name="debug", description="Testet ob der Bot richtig läuft", guild=guild)
        async def debug(interaction: discord.Interaction):
            await interaction.response.send_message("✅ Der Bot läuft einwandfrei!", ephemeral=True)

        await self.tree.sync(guild=guild)

    async def on_ready(self):
        print(f"✅ Bot ist online als {self.user}")
        channel = self.get_channel(VERIFY_CHANNEL_ID)
        if channel:
            await channel.purge(limit=5)
            await channel.send(
                "**🔒 Willkommen! Bitte verifiziere dich mit deinem *The Finals*-Namen!**",
                view=VerifyButton()
            )

bot = MyBot()

def get_player_data(player_name):
    clean_name = re.sub(r'#\d+', '', player_name).strip()
    url = f"https://api.the-finals-leaderboard.com/v1/leaderboard/s6/crossplay?name={clean_name}"
    print(f"🔍 API-Request: {url}")
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if "data" in data and len(data["data"]) > 0:
            return data["data"][0]
    print("❌ Kein Spieler gefunden")
    return None

keep_alive()
bot.run(TOKEN)

