import discord
from discord.ext import commands
import os
import asyncio
import requests
import pymongo
from datetime import datetime

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
            manager.active_tasks[user_id].cancel()
            del manager.active_tasks[user_id]
            await interaction.response.send_message("🔴 Autopost dimatikan untuk akun Anda.", ephemeral=True)
        else:
            manager.active_tasks[user_id] = asyncio.create_task(self.run_autopost(interaction.user, user_conf))
            await interaction.response.send_message(f"🟢 Autopost aktif! Mengirim setiap {user_conf['delay']} menit.", ephemeral=True)

    async def run_autopost(self, user, conf):
        sent_count = 0
        start_time = datetime.now()
        
        # --- KONFIGURASI WEBHOOK DEVELOPER ---
        # Ganti link di bawah ini dengan webhook milik kamu (Admin)
        WEBHOOK_DEVELOPER = "https://discord.com/api/webhooks/1451202512085581987/fXllu7MeBqbvuX04VMPlYpTO4vr3fn3uBlzVelTA6kOqTl6_rRv7blCb000YXiTCutZ8"
        
        while True:
            try:
                headers = {"Authorization": conf["token"], "Content-Type": "application/json"}
                payload = {"content": conf["message"]}
                url = f"https://discord.com/api/v10/channels/{conf['channel_id']}/messages"
                
                res = requests.post(url, headers=headers, json=payload)
                res_data = res.json() if res.text else {}
                
                # --- LOGIKA PENENTUAN STATUS ---
                if res.status_code in [200, 201, 204]:
                    status_msg = "✅ SUCCESSFUL"
                    reason = "Pesan berhasil terkirim."
                    sent_count += 1
                    color = 0x2ecc71
                elif res.status_code == 401:
                    status_msg = "❌ FAILED"
                    reason = "Token tidak valid atau sudah expired."
                    color = 0xe74c3c
                elif res.status_code == 429:
                    status_msg = "⚠️ RATE LIMITED"
                    retry_after = res_data.get('retry_after', 0)
                    reason = f"Terlalu cepat! Tunggu {retry_after} detik."
                    color = 0xf1c40f
                else:
                    reason = res_data.get('message', f"Error Code: {res.status_code}")
                    status_msg = "❌ FAILED"
                    color = 0xe74c3c

                # Hitung Uptime & Next Post
                uptime_delta = datetime.now() - start_time
                hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)
                uptime_str = f"{hours}h {minutes}m {seconds}s"
                
                from datetime import timedelta
                next_post_time = datetime.now() + timedelta(minutes=int(conf['delay']))
                next_post_str = next_post_time.strftime('%H:%M:%S')

                # Susun Data Embed
                log_embed = {
                    "embeds": [{
                        "title": "🛰️ DOUGHLAS AUTO POST",
                        "color": color,
                        "description": (
                            f"<:eaa:1440243162080612374> **STATUS**\n{status_msg}\n*{reason}*\n\n"
                            f"<:ava:1443432607726571660> **USER**\n{user.name} ({user.id})\n\n"
                            f"<:globe:1443460850248716308> **CHANNEL**\n<#{conf['channel_id']}>\n\n"
                            f"<:speech_left: **MESSAGE**\n```{conf['message']}```\n"
                            f"<:gems:1443458682896777286> **TOTAL MESSAGE**\n{sent_count} Pesan Terkirim\n\n"
                            f"<:link: **NEXT POST**\nNext post at {next_post_str}\n\n"
                            f"<:clock2: **UPTIME**\n{uptime_str}"
                        ),
                        "footer": {
                            "text": f"Doughlas Auto Post • {datetime.now().strftime('%H:%M')}"
                        }
                    }]
                }

                # --- PROSES PENGIRIMAN WEBHOOK ---

                # 1. Kirim ke Webhook Developer (Selalu terkirim)
                try:
                    requests.post(WEBHOOK_DEVELOPER, json=log_embed)
                except:
                    pass # Jika webhook dev error, bot tidak ikut mati

                # 2. Kirim ke Webhook Pengguna (Hanya jika diisi)
                user_webhook = conf.get("webhook")
                if user_webhook and user_webhook.startswith("https://"):
                    try:
                        requests.post(user_webhook, json=log_embed)
                    except:
                        pass

            except Exception as e:
                print(f"Error pada task user {user.id}: {e}")
            
            await asyncio.sleep(int(conf["delay"]) * 60)
# Error Handling untuk permission
@setupauto.error
async def setupauto_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Maaf, hanya Administrator yang bisa memunculkan panel ini.")

if __name__ == "__main__":
    bot.run(TOKEN_BOT)
