import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import asyncio
import requests
import pymongo
from datetime import datetime

# --- KONEKSI DATABASE (MONGODB) ---
# Di Railway, masukkan MONGO_URL di tab Variables
MONGO_URL = os.getenv("MONGO_URL")
TOKEN_BOT = os.getenv("TOKEN_BOT")

client = pymongo.MongoClient(MONGO_URL)
db = client["lantas_database"]
users_col = db["autopost_users"]

class AutoPostManager:
    def __init__(self):
        self.active_tasks = {}

    def get_user_data(self, user_id):
        return users_col.find_one({"user_id": str(user_id)})

    def save_user_data(self, user_id, data):
        users_col.update_one(
            {"user_id": str(user_id)},
            {"$set": data},
            upsert=True
        )

manager = AutoPostManager()

# --- UI COMPONENTS ---

class SetupModal(discord.ui.Modal, title='⚙️ Lantas AutoPost Config'):
    user_token = discord.ui.TextInput(label='Discord User Token', placeholder='Token akun anda...', style=discord.TextStyle.short, required=True)
    channel_id = discord.ui.TextInput(label='ID Channel Tujuan', placeholder='Contoh: 1400548908...', required=True)
    message = discord.ui.TextInput(label='Isi Pesan', style=discord.TextStyle.paragraph, placeholder='Tulis pesan promosi...', required=True)
    delay = discord.ui.TextInput(label='Delay (Menit)', placeholder='Contoh: 60', default='60', required=True)
    webhook = discord.ui.TextInput(label='Webhook Logging (Opsional)', placeholder='https://discord.com/api/webhooks/...', required=False)

    async def on_submit(self, interaction: discord.Interaction):
        data = {
            "user_id": str(interaction.user.id),
            "token": self.user_token.value,
            "channel_id": self.channel_id.value,
            "message": self.message.value,
            "delay": int(self.delay.value),
            "webhook": self.webhook.value
        }
        manager.save_user_data(interaction.user.id, data)
        await interaction.response.send_message("✅ Konfigurasi tersimpan di Database!", ephemeral=True)

class ControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Account Management', style=discord.ButtonStyle.blurple, custom_id='manage_btn')
    async def manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetupModal())

    @discord.ui.button(label='Start / Stop Autopost', style=discord.ButtonStyle.green, custom_id='toggle_btn')
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        user_conf = manager.get_user_data(user_id)
        
        if not user_conf:
            return await interaction.response.send_message("❌ Atur akun dulu!", ephemeral=True)

        if user_id in manager.active_tasks:
            manager.active_tasks[user_id].cancel()
            del manager.active_tasks[user_id]
            await interaction.response.send_message("🔴 Autopost Berhenti.", ephemeral=True)
        else:
            manager.active_tasks[user_id] = asyncio.create_task(self.run_autopost(interaction.user, user_conf))
            await interaction.response.send_message("🟢 Autopost Berjalan 24/7!", ephemeral=True)

    async def run_autopost(self, user, conf):
        while True:
            try:
                headers = {"Authorization": conf["token"], "Content-Type": "application/json"}
                payload = {"content": conf["message"]}
                url = f"https://discord.com/api/v10/channels/{conf['channel_id']}/messages"
                res = requests.post(url, headers=headers, json=payload)
                
                if conf.get("webhook"):
                    status = "✅ SUKSES" if res.status_code == 200 else f"❌ ERROR ({res.status_code})"
                    log = {"embeds": [{"title": "Log Autopost", "description": f"Status: {status}\nTarget: <#{conf['channel_id']}>", "color": 5763719}]}
                    requests.post(conf["webhook"], json=log)
            except Exception as e:
                print(f"Error: {e}")
            await asyncio.sleep(int(conf["delay"]) * 60)

# --- BOT SETUP ---

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(ControlView())

bot = MyBot()

@bot.command()
async def setup(ctx):
    if not ctx.author.guild_permissions.administrator: return
    embed = discord.Embed(title="🚀 Lantas Autopost Panel", description="Kelola pesan otomatis anda di sini.", color=discord.Color.blue())
    await ctx.send(embed=embed, view=ControlView())

bot.run(TOKEN_BOT)
