import discord
from discord.ext import commands
import os
import asyncio
import requests
import pymongo
from datetime import datetime

# --- KONEKSI DATABASE & TOKEN ---
# Pastikan MONGO_URL dan TOKEN_BOT sudah diisi di tab Variables Railway
MONGO_URL = os.getenv("MONGO_URL")
TOKEN_BOT = os.getenv("TOKEN_BOT")

# Inisialisasi MongoDB
client = pymongo.MongoClient(MONGO_URL)
db = client["doughlas_database"]
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

# --- UI COMPONENTS (MODAL & VIEW) ---

class SetupModal(discord.ui.Modal, title='⚙️ DOUGHLAS AUTOPOST SETTING'):
    user_token = discord.ui.TextInput(
        label='Discord User Token', 
        placeholder='Masukkan Token Akun Anda...', 
        style=discord.TextStyle.short, 
        required=True
    )
    channel_id = discord.ui.TextInput(
        label='ID Channel Tujuan', 
        placeholder='Contoh: 123456789012345678', 
        required=True
    )
    message = discord.ui.TextInput(
        label='Isi Pesan', 
        style=discord.TextStyle.paragraph, 
        placeholder='Tulis pesan promosi di sini...', 
        required=True
    )
    delay = discord.ui.TextInput(
        label='Delay (Menit)', 
        placeholder='Contoh: 60 (untuk 1 jam)', 
        default='60', 
        required=True
    )
    webhook = discord.ui.TextInput(
        label='Webhook Logging (Opsional)', 
        placeholder='https://discord.com/api/webhooks/...', 
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            data = {
                "user_id": str(interaction.user.id),
                "token": self.user_token.value.strip(),
                "channel_id": self.channel_id.value.strip(),
                "message": self.message.value,
                "delay": int(self.delay.value),
                "webhook": self.webhook.value.strip() if self.webhook.value else None
            }
            manager.save_user_data(interaction.user.id, data)
            await interaction.response.send_message("✅ Konfigurasi berhasil disimpan ke Database!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Error: Delay harus berupa angka (menit)!", ephemeral=True)

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
            return await interaction.response.send_message("❌ Silakan atur akun dulu di 'Account Management'!", ephemeral=True)

        if user_id in manager.active_tasks:
            # STOP TASK
            manager.active_tasks[user_id].cancel()
            del manager.active_tasks[user_id]
            await interaction.response.send_message("🔴 Autopost dimatikan untuk akun Anda.", ephemeral=True)
        else:
            # START TASK
            manager.active_tasks[user_id] = asyncio.create_task(self.run_autopost(interaction.user, user_conf))
            await interaction.response.send_message(f"🟢 Autopost aktif! Mengirim setiap {user_conf['delay']} menit.", ephemeral=True)

    async def run_autopost(self, user, conf):
        while True:
            try:
                headers = {"Authorization": conf["token"], "Content-Type": "application/json"}
                payload = {"content": conf["message"]}
                url = f"https://discord.com/api/v10/channels/{conf['channel_id']}/messages"
                
                res = requests.post(url, headers=headers, json=payload)
                
                if conf.get("webhook"):
                    status = "✅ BERHASIL" if res.status_code in [200, 201, 204] else f"❌ GAGAL ({res.status_code})"
                    color = 5763719 if res.status_code in [200, 201, 204] else 15548997
                    log_data = {
                        "embeds": [{
                            "title": "🚀 Doughlas Autopost Log",
                            "description": f"**Status:** {status}\n**Target:** <#{conf['channel_id']}>\n**Waktu:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                            "color": color
                        }]
                    }
                    requests.post(conf["webhook"], json=log_data)
            except Exception as e:
                print(f"Error in task for {user.id}: {e}")
            
            await asyncio.sleep(int(conf["delay"]) * 60)

# --- BOT CORE ---

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # Penting untuk command !
        intents.members = True          # Penting untuk identifikasi user
        
        super().__init__(
            command_prefix="!", 
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        # Mendaftarkan view agar tombol tetap aktif setelah bot restart
        self.add_view(ControlView())

    async def on_ready(self):
        print(f'✅ Bot Online: {self.user.name}')
        print(f'✅ Database MongoDB Terkoneksi')
        print('------')

bot = MyBot()

@bot.command()
@commands.has_permissions(administrator=True)
async def setupauto(ctx):
    embed = discord.Embed(
        title="DOUGHLAS AUTOPOST",
        description=(
            "Gunakan panel ini untuk mengatur promosi otomatis.\n\n"
            "**Instruksi:**\n"
            "1. Klik **Account Management** untuk isi data.\n"
            "2. Klik **Start / Stop** untuk menjalankan.\n"
            "3. Pastikan Token User valid."
        ),
        color=discord.Color.blue()

# Error Handling untuk permission
@setupauto.error
async def setupauto_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Maaf, hanya Administrator yang bisa memunculkan panel ini.")

if __name__ == "__main__":
    bot.run(TOKEN_BOT)
