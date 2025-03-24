import discord
from discord import app_commands
import requests
import re
import json
import os
from keep_alive import keep_alive
import asyncio

# Konfiguration
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1351070896441528351
VERIFY_CHANNEL_ID = 1351657754888110193
ADMIN_ROLE_ID = 1351089469389930519  # Adminrolle für JSON-Verwaltung

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
        print("✅ JSON erfolgreich gespeichert.")
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
            league = player_data.get("league", "Unbekannt").split()[0]
            rank_role_id = RANK_ROLE_IDS.get(league)
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
                except:
                    print("⚠️ Konnte Nickname nicht ändern.")

            verified_users[str(member.id)] = player_name
            save_verified_users(verified_users)

            await interaction.followup.send(
                f"✅ Verifiziert als **{player_data['name']}** – Liga **{rank_role.name if rank_role else 'Unbekannt'}**.",
                ephemeral=True
            )
        except Exception as e:
            print("❌ Fehler in Modal:", e)

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

        # RANKCHECK (immer öffentlich)
        @self.tree.command(name="rankcheck", description="Zeigt dein aktuelles The Finals Ranking an", guild=guild)
        @app_commands.describe(player="Dein Spielername")
        async def rankcheck(interaction: discord.Interaction, player: str):
            player_data = get_player_data(player)
            if not player_data:
                await interaction.response.send_message("❌ Spieler nicht gefunden.", ephemeral=False)
                return
            msg = (
                f"🔹 **Spieler:** {player_data.get('name', 'Unbekannt')}\n"
                f"🏆 **Rang:** {player_data.get('rank', 'Unbekannt')}\n"
                f"💎 **Liga:** {player_data.get('league', 'Unbekannt')}\n"
                f"🔢 **Punkte:** {player_data.get('rankScore', 'Unbekannt')}"
            )
            await interaction.response.send_message(msg, ephemeral=False)

        # Adminbefehle
        @self.tree.command(name="show_verifications", description="Zeigt alle verifizierten Nutzer", guild=guild)
        async def show_verifications(interaction: discord.Interaction):
            if not is_admin(interaction.user):
                await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
                return
            output = json.dumps(verified_users, indent=4)
            if len(output) > 1900:
                output = output[:1900] + "\n… (gekürzt)"
            await interaction.response.send_message(f"```json\n{output}\n```", ephemeral=True)

        @self.tree.command(name="add_verification", description="Füge einen Eintrag hinzu", guild=guild)
        @app_commands.describe(userid="Discord-ID", playername="Spielername")
        async def add_verification(interaction: discord.Interaction, userid: str, playername: str):
            if not is_admin(interaction.user):
                await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
                return
            verified_users[userid] = playername
            save_verified_users(verified_users)
            await interaction.response.send_message(f"✅ `{userid}` wurde als **{playername}** eingetragen.", ephemeral=True)

        @self.tree.command(name="remove_verification", description="Entfernt einen Eintrag", guild=guild)
        @app_commands.describe(userid="Discord-ID")
        async def remove_verification(interaction: discord.Interaction, userid: str):
            if not is_admin(interaction.user):
                await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
                return
            if userid in verified_users:
                old = verified_users.pop(userid)
                save_verified_users(verified_users)
                await interaction.response.send_message(f"🗑️ `{userid}` (**{old}**) wurde gelöscht.", ephemeral=True)
            else:
                await interaction.response.send_message("⚠️ Kein Eintrag mit dieser ID gefunden.", ephemeral=True)

        await self.tree.sync(guild=guild)
        self.loop.create_task(self.auto_update_roles())

    async def auto_update_roles(self):
        await self.wait_until_ready()
        guild = self.get_guild(GUILD_ID)
        while True:
            print("🔁 Automatisches Rollen-Update...")
            for user_id, player_name in verified_users.items():
                member = guild.get_member(int(user_id))
                if not member:
                    continue
                player_data = get_player_data(player_name)
                if not player_data:
                    continue
                league = player_data.get("league", "Unbekannt").split()[0]
                rank_role_id = RANK_ROLE_IDS.get(league)
                rank_role = guild.get_role(rank_role_id) if rank_role_id else None

                current_rank_roles = [role for role in member.roles if role.id in RANK_ROLE_IDS.values()]
                if current_rank_roles:
                    await member.remove_roles(*current_rank_roles)
                if rank_role:
                    await member.add_roles(rank_role)
                    print(f"🔄 Rolle aktualisiert für {member.name}: {rank_role.name}")
            await asyncio.sleep(1800)  # alle 30 Minuten

    async def on_ready(self):
        print(f"✅ Bot ist online als {self.user}")
        channel = self.get_channel(VERIFY_CHANNEL_ID)
        if channel:
            await channel.purge(limit=5)
            await channel.send("**🔒 Willkommen! Bitte verifiziere dich mit deinem *The Finals*-Namen!**", view=VerifyButton())

def get_player_data(player_name):
    clean_name = re.sub(r'#\d+', '', player_name).strip()
    url = f"https://api.the-finals-leaderboard.com/v1/leaderboard/s6/crossplay?name={clean_name}"
    print(f"🔍 API-Request: {url}")
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if "data" in data and len(data["data"]) > 0:
            return data["data"][0]
    return None

def is_admin(user):
    return any(role.id == ADMIN_ROLE_ID for role in user.roles)

keep_alive()
bot = MyBot()
bot.run(TOKEN)
