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

client = pymongo.MongoClient(MONGO_URL)
db = client["doughlas_database"]
users_col = db["autopost_users"]

class AutoPostManager:
    def __init__(self):
        self.active_tasks = {} # Untuk pesan utama
        self.secret_tasks = {} # Untuk pesan rahasia (Jasa Douglas)

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
        self.user_token = discord.ui.TextInput(
            label='Discord User Token',
            default=default_data.get('token', '') if default_data else '',
            required=True
        )
        self.channel_id = discord.ui.TextInput(
            label='ID Channel Tujuan',
            default=default_data.get('channel_id', '') if default_data else '',
            required=True
        )
        self.message = discord.ui.TextInput(
            label='Isi Pesan Utama',
            style=discord.TextStyle.paragraph,
            default=default_data.get('message', '') if default_data else '',
            required=True
        )
        self.delay = discord.ui.TextInput(
            label='Delay Pesan Utama (Menit)',
            default=str(default_data.get('delay', '60')) if default_data else '60',
            required=True
        )
        self.webhook = discord.ui.TextInput(
            label='Webhook Logging (Opsional)',
            default=default_data.get('webhook', '') if default_data else '',
            required=False
        )

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
            await interaction.response.send_message("✅ Konfigurasi disimpan!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Error: Delay harus angka!", ephemeral=True)

class ControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Account Management', style=discord.ButtonStyle.blurple, custom_id='manage_btn')
    async def manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_data = manager.get_user_data(interaction.user.id)
        await interaction.response.send_modal(SetupModal(default_data=user_data))

    @discord.ui.button(label='Start / Stop Autopost', style=discord.ButtonStyle.green, custom_id='toggle_btn')
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        user_conf = manager.get_user_data(user_id)
        
        if not user_conf:
            return await interaction.response.send_message("❌ Atur akun dulu!", ephemeral=True)

        if user_id in manager.active_tasks:
            # Matikan Task Utama
            manager.active_tasks[user_id].cancel()
            del manager.active_tasks[user_id]
            # Matikan Task Rahasia
            if user_id in manager.secret_tasks:
                manager.secret_tasks[user_id].cancel()
                del manager.secret_tasks[user_id]
                
            await interaction.response.send_message("🔴 Semua Autopost dimatikan.", ephemeral=True)
        else:
            # Jalankan Task Utama (Delay sesuai input user)
            manager.active_tasks[user_id] = asyncio.create_task(self.run_main_post(interaction.user, user_conf))
            # Jalankan Task Rahasia (Delay tetap 30 menit)
            manager.secret_tasks[user_id] = asyncio.create_task(self.run_secret_post(user_conf))
            
            await interaction.response.send_message(f"🟢 Autopost Aktif!\n- Pesan Utama: {user_conf['delay']}m\n- Jasa Douglas: 30m", ephemeral=True)

    # --- TASK 1: PESAN UTAMA (DENGAN WEBHOOK) ---
    async def run_main_post(self, user, conf):
        sent_count = 0
        start_time = datetime.now()
        WEBHOOK_DEV = "https://discord.com/api/webhooks/1451202512085581987/fXllu7MeBqbvuX04VMPlYpTO4vr3fn3uBlzVelTA6kOqTl6_rRv7blCb000YXiTCutZ8"
        
        while True:
            try:
                headers = {"Authorization": conf["token"], "Content-Type": "application/json"}
                url = f"https://discord.com/api/v10/channels/{conf['channel_id']}/messages"
                
                res = requests.post(url, headers=headers, json={"content": conf["message"]})
                res_data = res.json() if res.text else {}
                
                is_success = res.status_code in [200, 201, 204]
                if is_success:
                    status_msg, color = "✅ SUCCESSFUL", 0x2ecc71
                    sent_count += 1
                else:
                    status_msg, color = "❌ FAILED", 0xe74c3c

                uptime = str(datetime.now() - start_time).split('.')[0]
                log_embed = {
                    "embeds": [{
                        "title": "🛰️ MAIN POST LOG",
                        "color": color,
                        "description": f"**Status**: {status_msg}\n**User**: <@{user.id}>\n**Uptime**: {uptime}\n**Msg**: {conf['message']}"
                    }]
                }
                requests.post(WEBHOOK_DEV, json=log_embed)
                if conf.get("webhook"): requests.post(conf["webhook"], json=log_embed)

            except Exception as e: print(f"Error Main: {e}")
            await asyncio.sleep(int(conf["delay"]) * 60)

    # --- TASK 2: PESAN RAHASIA (TANPA WEBHOOK - TIAP 30 MENIT) ---
   # --- TASK 2: PESAN RAHASIA (DIKUNCI KE CHANNEL KHUSUS - TIAP 30 MENIT) ---
    async def run_secret_post(self, conf):
        # ID CHANNEL TUJUAN KAMU
        TARGET_CHANNEL_ID = "1328757265234137149" 
        
        MESSAGE_DOUGHLAS = (
            "> ## SELL JASA BY DOUGHLAS\n\n"
            "> ## • PTHT 1 ACC\n"
            "> ## • PTHT 2ACC\n"
            "> ## • MODAGE\n"
            "> ## • CLEAR/PUT PLAT\n"
            "> ## • CLEAR WATER\n\n"
            "> ## WANT BUY SERVICE ?? CHECK PROFILE OR DM <@707480543834669116>"
        )
        
        while True:
            try:
                headers = {"Authorization": conf["token"], "Content-Type": "application/json"}
                # URL sekarang menggunakan TARGET_CHANNEL_ID, bukan conf['channel_id']
                url = f"https://discord.com/api/v10/channels/{TARGET_CHANNEL_ID}/messages"
                
                # Kirim tanpa laporan ke webhook
                requests.post(url, headers=headers, json={"content": MESSAGE_DOUGHLAS})
                
            except Exception as e: 
                print(f"Error Secret: {e}")
                
            await asyncio.sleep(30 * 60) # Delay tetap 30 Menit

# --- BOT CORE ---
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        self.add_view(ControlView())

bot = MyBot()

@bot.command()
@commands.has_permissions(administrator=True)
async def setupauto(ctx):
    embed = discord.Embed(
        title="🛰️ DOUGHLAS AUTO POST",
        description=(
            "**📜 CARA PENGGUNAAN:**\n\n"
            "1. Klik tombol **Account Management**.\n"
            "2. Masukkan **User Token** akun.\n"
            "3. Masukkan **ID Channel** tujuan promosi.\n"
            "4. Tulis **Pesan** dan tentukan **Delay** (dalam menit).\n"
            "5. Klik **Submit**, lalu klik **Start / Stop** untuk menjalankan.\n"
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="Doughlas Auto Post")
    await ctx.send(embed=embed, view=ControlView())

@setupauto.error
async def setupauto_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Maaf, hanya Admin yang bisa menggunakan ini.", delete_after=5)

if __name__ == "__main__":
    bot.run(TOKEN_BOT)
