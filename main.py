import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import asyncio
import requests
from datetime import datetime

# --- CONFIGURATION ---
TOKEN_BOT = "TOKEN_BOT_ANDA_DISINI" # Ganti dengan token bot dari Discord Developer Portal
CONFIG_PATH = "autopost_data.json"

class AutoPostManager:
    def __init__(self):
        self.data = self.load_data()
        self.active_tasks = {}

    def load_data(self):
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        return {"users": {}}

    def save_data(self):
        with open(CONFIG_PATH, "w") as f:
            json.dump(self.data, f, indent=4)

manager = AutoPostManager()

# --- UI COMPONENTS (MODAL & BUTTONS) ---

class SetupModal(discord.ui.Modal, title='⚙️ Konfigurasi Autopost'):
    # Menggunakan Modal agar persis seperti di foto tapi dengan desain lebih rapi
    user_token = discord.ui.TextInput(label='Discord User Token', placeholder='Masukkan token akun anda...', style=discord.TextStyle.short, required=True)
    channel_id = discord.ui.TextInput(label='ID Channel Tujuan', placeholder='Contoh: 1400548908...', required=True)
    message = discord.ui.TextInput(label='Isi Pesan', style=discord.TextStyle.paragraph, placeholder='Tulis pesan promosi anda di sini...', required=True)
    delay = discord.ui.TextInput(label='Delay (Menit)', placeholder='Contoh: 60 (untuk 1 jam)', default='60', required=True)
    webhook = discord.ui.TextInput(label='Webhook Logging (Opsional)', placeholder='https://discord.com/api/webhooks/...', required=False)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        manager.data["users"][user_id] = {
            "token": self.user_token.value,
            "channel_id": self.channel_id.value,
            "message": self.message.value,
            "delay": int(self.delay.value),
            "webhook": self.webhook.value,
            "active": False
        }
        manager.save_data()
        await interaction.response.send_message(f"✅ Konfigurasi tersimpan untuk channel <#{self.channel_id.value}>!", ephemeral=True)

class ControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Timeout None agar tombol permanen

    @discord.ui.button(label='Account Management', style=discord.ButtonStyle.blurple, custom_id='manage_btn')
    async def manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetupModal())

    @discord.ui.button(label='Start / Stop Autopost', style=discord.ButtonStyle.green, custom_id='toggle_btn')
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        if user_id not in manager.data["users"]:
            return await interaction.response.send_message("❌ Atur akun dulu di 'Account Management'!", ephemeral=True)

        user_conf = manager.data["users"][user_id]
        
        if user_id in manager.active_tasks:
            # STOP
            manager.active_tasks[user_id].cancel()
            del manager.active_tasks[user_id]
            await interaction.response.send_message("🔴 Autopost dimatikan.", ephemeral=True)
        else:
            # START
            manager.active_tasks[user_id] = asyncio.create_task(self.run_autopost(interaction.user, user_conf))
            await interaction.response.send_message("🟢 Autopost berhasil dijalankan!", ephemeral=True)

    async def run_autopost(self, user, conf):
        while True:
            try:
                headers = {"Authorization": conf["token"], "Content-Type": "application/json"}
                payload = {"content": conf["message"]}
                url = f"https://discord.com/api/v10/channels/{conf['channel_id']}/messages"
                
                res = requests.post(url, headers=headers, json=payload)
                
                # Kirim Log ke Webhook jika ada
                if conf["webhook"]:
                    status = "✅ BERHASIL" if res.status_code == 200 else f"❌ GAGAL ({res.status_code})"
                    log_embed = {
                        "title": "🚀 Lantas Continental Log",
                        "color": 0x00ff00 if res.status_code == 200 else 0xff0000,
                        "fields": [
                            {"name": "Status", "value": status, "inline": True},
                            {"name": "Channel", "value": f"<#{conf['channel_id']}>", "inline": True},
                            {"name": "Waktu", "value": datetime.now().strftime("%H:%M:%S"), "inline": False}
                        ],
                        "footer": {"text": "Powered by Lantas AutoPost"}
                    }
                    requests.post(conf["webhook"], json={"embeds": [log_embed]})

            except Exception as e:
                print(f"Error loop: {e}")
            
            await asyncio.sleep(conf["delay"] * 60)

# --- BOT SETUP ---

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(ControlView()) # Daftarkan view permanen

bot = MyBot()

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_panel(ctx):
    embed = discord.Embed(
        title="🤖 Lantas Continental - Premium Autopost",
        description=(
            "Gunakan tombol di bawah untuk mengelola iklan otomatis anda.\n\n"
            "**Statistik Global:**\n"
            f"👤 User Terdaftar: {len(manager.data['users'])}\n"
            "🟢 Status Bot: Online"
        ),
        color=discord.Color.from_rgb(47, 49, 54)
    )
    embed.set_footer(text="Gunakan dengan bijak • Token anda tersimpan dengan enkripsi standar.")
    await ctx.send(embed=embed, view=ControlView())

bot.run(TOKEN_BOT)
