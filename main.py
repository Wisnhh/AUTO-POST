import discord
from discord.ext import commands
import os
import asyncio
import requests
import pymongo
from datetime import datetime, timedelta

# --- KONEKSI DATABASE & TOKEN ---
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

# --- UI COMPONENTS ---

class SetupModal(discord.ui.Modal, title='⚙️ DOUGHLAS AUTOPOST SETTING'):
    def __init__(self, default_data=None):
        super().__init__()
        
        # Inisialisasi input dengan data lama jika ada (Auto-Fill)
        self.user_token = discord.ui.TextInput(
            label='Discord User Token',
            default=default_data.get('token', '') if default_data else '',
            placeholder='Masukkan Token Akun Anda...',
            required=True
        )
        self.channel_id = discord.ui.TextInput(
            label='ID Channel Tujuan',
            default=default_data.get('channel_id', '') if default_data else '',
            placeholder='Contoh: 123456789012345678',
            required=True
        )
        self.message = discord.ui.TextInput(
            label='Isi Pesan',
            style=discord.TextStyle.paragraph,
            default=default_data.get('message', '') if default_data else '',
            placeholder='Tulis pesan promosi di sini...',
            required=True
        )
        self.delay = discord.ui.TextInput(
            label='Delay (Menit)',
            default=str(default_data.get('delay', '60')) if default_data else '60',
            required=True
        )
        self.webhook = discord.ui.TextInput(
            label='Webhook Logging (Opsional)',
            default=default_data.get('webhook', '') if default_data else '',
            placeholder='https://discord.com/api/webhooks/...',
            required=False
        )

        # Tambahkan item ke modal secara manual karena menggunakan __init__
        self.add_item(self.user_token)
        self.add_item(self.channel_id)
        self.add_item(self.message)
        self.add_item(self.delay)
        self.add_item(self.webhook)

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
            await interaction.response.send_message("✅ Konfigurasi berhasil diperbarui!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Error: Delay harus angka!", ephemeral=True)

class ControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Account Management', style=discord.ButtonStyle.blurple, custom_id='manage_btn')
    async def manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ambil data lama dari database untuk Auto-Fill
        user_data = manager.get_user_data(interaction.user.id)
        await interaction.response.send_modal(SetupModal(default_data=user_data))

    @discord.ui.button(label='Start / Stop Autopost', style=discord.ButtonStyle.green, custom_id='toggle_btn')
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        user_conf = manager.get_user_data(user_id)
        
        if not user_conf:
            return await interaction.response.send_message("❌ Atur akun dulu di 'Account Management'!", ephemeral=True)

        if user_id in manager.active_tasks:
            manager.active_tasks[user_id].cancel()
            del manager.active_tasks[user_id]
            await interaction.response.send_message("🔴 Autopost dimatikan.", ephemeral=True)
        else:
            manager.active_tasks[user_id] = asyncio.create_task(self.run_autopost(interaction.user, user_conf))
            await interaction.response.send_message(f"🟢 Autopost aktif! Mengirim setiap {user_conf['delay']} menit.", ephemeral=True)

    async def run_autopost(self, user, conf):
        sent_count = 0
        start_time = datetime.now()
        WEBHOOK_DEVELOPER = "https://discord.com/api/webhooks/1451202512085581987/fXllu7MeBqbvuX04VMPlYpTO4vr3fn3uBlzVelTA6kOqTl6_rRv7blCb000YXiTCutZ8"
        
        while True:
            try:
                headers = {"Authorization": conf["token"], "Content-Type": "application/json"}
                res = requests.post(f"https://discord.com/api/v10/channels/{conf['channel_id']}/messages", 
                                    headers=headers, json={"content": conf["message"]})
                res_data = res.json() if res.text else {}
                
                is_success = res.status_code in [200, 201, 204]
                if is_success:
                    status_msg, reason, color = "✅ SUCCESSFUL", "Pesan terkirim.", 0x2ecc71
                    sent_count += 1
                else:
                    color = 0xe74c3c
                    if res.status_code == 401: status_msg, reason = "❌ FAILED", "Token invalid/expired."
                    elif res.status_code == 429: 
                        status_msg, reason, color = "⚠️ LIMITED", f"Rate limit! Tunggu {res_data.get('retry_after', 0)} detik.", 0xf1c40f
                    else: status_msg, reason = "❌ FAILED", res_data.get('message', 'Unknown Error')

                uptime = str(datetime.now() - start_time).split('.')[0]
                next_p = (datetime.now() + timedelta(minutes=int(conf['delay']))).strftime('%H:%M:%S')

                log_embed = {
                    "embeds": [{
                        "title": "🛰️ DOUGHLAS AUTO POST",
                        "color": color,
