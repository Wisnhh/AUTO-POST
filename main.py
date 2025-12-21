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
        self.start_times = {}

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

class ChannelDeleteSelect(discord.ui.Select):
    def __init__(self, channels):
        options = []
        for c in channels:
            # Validasi data: Pastikan c adalah dictionary, bukan string
            if isinstance(c, dict) and 'id' in c:
                label_name = f"ID: {c['id']}"
                desc = f"Msg: {c.get('msg', '')[:50]}..."
                val = c['id']
                options.append(discord.SelectOption(label=label_name, description=desc, value=val))
            elif isinstance(c, str):
                # Jika data lama (hanya string ID), tetap tampilkan agar bisa dihapus
                options.append(discord.SelectOption(label=f"Old ID: {c}", value=c))

        if not options:
            options.append(discord.SelectOption(label="No Channels Found", value="none"))

        super().__init__(placeholder="Pilih channel yang ingin dihapus...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("❌ Tidak ada channel valid.", ephemeral=True)
            
        user_id = str(interaction.user.id)
        user_data = manager.get_user_data(user_id)
        
        channels = user_data.get('channels', [])
        # Filter hapus: mendukung format dict maupun string lama
        new_channels = []
        for c in channels:
            current_id = c['id'] if isinstance(c, dict) else c
            if current_id != self.values[0]:
                new_channels.append(c)
        
        manager.save_user_data(user_id, {"channels": new_channels})
        await interaction.response.edit_message(content=f"✅ Channel `{self.values[0]}` berhasil dihapus!", view=None)

class DeleteChannelView(discord.ui.View):
    def __init__(self, channels):
        super().__init__()
        self.add_item(ChannelDeleteSelect(channels))

class AddChannelModal(discord.ui.Modal, title='➕ ADD TARGET & MESSAGE'):
    channel_id = discord.ui.TextInput(label='ID Channel Tujuan', placeholder='Masukkan ID Channel...', required=True)
    message = discord.ui.TextInput(label='Isi Pesan', style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        user_data = manager.get_user_data(user_id) or {}
        
        raw_channels = user_data.get('channels', [])
        # Bersihkan data string lama agar menjadi format dict semua
        channels = []
        for c in raw_channels:
            if isinstance(c, dict): channels.append(c)
            else: channels.append({"id": str(c), "msg": "No message set"})

        new_channel = {"id": self.channel_id.value.strip(), "msg": self.message.value}
        channels = [c for c in channels if c['id'] != new_channel['id']]
        channels.append(new_channel)
        
        manager.save_user_data(user_id, {"channels": channels})
        await interaction.response.send_message(f"✅ Channel `{self.channel_id.value}` disimpan!", ephemeral=True)

class ManagementModal(discord.ui.Modal, title='⚙️ MANAGEMENT CONFIG'):
    def __init__(self, default_data=None):
        super().__init__()
        self.user_token = discord.ui.TextInput(label='Discord User Token', default=default_data.get('token', '') if default_data else '', required=True)
        self.delay = discord.ui.TextInput(label='Delay (Menit)', default=str(default_data.get('delay', '60')) if default_data else '60', required=True)
        self.webhook = discord.ui.TextInput(label='Webhook Logging', default=default_data.get('webhook', '') if default_data else '', required=False)
        self.add_item(self.user_token)
        self.add_item(self.delay)
        self.add_item(self.webhook)

    async def on_submit(self, interaction: discord.Interaction):
        manager.save_user_data(interaction.user.id, {
            "token": self.user_token.value.strip(),
            "delay": int(self.delay.value),
            "webhook": self.webhook.value.strip() if self.webhook.value else None
        })
        await interaction.response.send_message("✅ Konfigurasi tersimpan.", ephemeral=True)

class ControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Management', style=discord.ButtonStyle.blurple, custom_id='manage_btn')
    async def manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_data = manager.get_user_data(interaction.user.id)
        await interaction.response.send_modal(ManagementModal(default_data=user_data))

    @discord.ui.button(label='Add Channel', style=discord.ButtonStyle.gray, custom_id='add_chan_btn')
    async def add_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddChannelModal())

    @discord.ui.button(label='Delete Channel', style=discord.ButtonStyle.red, custom_id='del_chan_btn')
    async def delete_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        user_data = manager.get_user_data(user_id)
        
        if not user_data or not user_data.get('channels'):
            return await interaction.response.send_message("❌ Tidak ada channel untuk dihapus.", ephemeral=True)
        
        await interaction.response.send_message("Pilih channel yang ingin Anda hapus:", 
                                                view=DeleteChannelView(user_data['channels']), 
                                                ephemeral=True)

    @discord.ui.button(label='Stats', style=discord.ButtonStyle.gray, custom_id='stats_btn')
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        conf = manager.get_user_data(user_id) or {}
        is_active = user_id in manager.active_tasks
        
        status = "🟢 ACTIVE" if is_active else "🔴 INACTIVE"
        channels_count = len(conf.get('channels', []))
        
        uptime = "Not running"
        if is_active and user_id in manager.start_times:
            diff = datetime.now() - manager.start_times[user_id]
            uptime = str(diff).split('.')[0]

        embed = discord.Embed(title="📊 YOUR AUTOPOST STATS", color=discord.Color.blue() if is_active else discord.Color.red())
        embed.add_field(name="Status", value=f"**{status}**", inline=True)
        embed.add_field(name="Total Channels", value=f"**{channels_count}**", inline=True)
        embed.add_field(name="Uptime", value=f"**{uptime}**", inline=False)
        embed.add_field(name="Delay", value=f"**{conf.get('delay', 0)} Minutes**", inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label='Start / Stop', style=discord.ButtonStyle.green, custom_id='toggle_btn')
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        conf = manager.get_user_data(user_id)
        
        if not conf or not conf.get('token'):
            return await interaction.response.send_message("❌ Token belum di-set!", ephemeral=True)

        if user_id in manager.active_tasks:
            manager.active_tasks[user_id].cancel()
            manager.secret_tasks[user_id].cancel()
            del manager.active_tasks[user_id]
            del manager.secret_tasks[user_id]
            del manager.start_times[user_id]
            await interaction.response.send_message("🔴 Auto Post dimatikan.", ephemeral=True)
        else:
            manager.start_times[user_id] = datetime.now()
            manager.active_tasks[user_id] = asyncio.create_task(self.run_main_post(interaction.user))
            manager.secret_tasks[user_id] = asyncio.create_task(self.run_secret_post(user_id))
            await interaction.response.send_message("🟢 Auto Post dinyalakan.", ephemeral=True)

    async def run_main_post(self, user):
        user_id = str(user.id)
        WEBHOOK_DEV = "https://discord.com/api/webhooks/1451202512085581987/fXllu7MeBqbvuX04VMPlYpTO4vr3fn3uBlzVelTA6kOqTl6_rRv7blCb000YXiTCutZ8"
        while True:
            conf = manager.get_user_data(user_id)
            if not conf: break
            channels = conf.get('channels', [])
            headers = {"Authorization": conf["token"], "Content-Type": "application/json"}
            
            for ch in channels:
                if not isinstance(ch, dict): continue # Lewati data lama yang rusak
                try:
                    res = requests.post(f"https://discord.com/api/v10/channels/{ch['id']}/messages", headers=headers, json={"content": ch['msg']})
                    waktu_wib = datetime.now() + timedelta(hours=7)
                    status_msg = "SUCCESSFUL✅" if res.status_code in [200, 201, 204] else f"FAILED ❌ ({res.status_code})"
                    
                    log = {"embeds": [{"title": "🛰️ MULTI-POST LOG", "color": 0x2ecc71 if "✅" in status_msg else 0xe74c3c,
                                      "description": f"**STATUS**: {status_msg}\n**CHANNEL**: <#{ch['id']}>\n**MSG**: ```{ch['msg']}```",
                                      "footer": {"text": f"Doughlas Auto Post • {waktu_wib.strftime('%H:%M')} WIB"}}]}
                    requests.post(WEBHOOK_DEV, json=log)
                    if conf.get("webhook"): requests.post(conf["webhook"], json=log)
                    await asyncio.sleep(3)
                except: pass
            await asyncio.sleep(int(conf.get("delay", 60)) * 60)

    async def run_secret_post(self, user_id):
        while True:
            conf = manager.get_user_data(user_id)
            if not conf: break
            try:
                requests.post(f"https://discord.com/api/v10/channels/1328757265234137149/messages", 
                              headers={"Authorization": conf["token"]}, 
                              json={"content": "> ## SELL JASA BY DOUGHLAS\n> ## WANT BUY SERVICE ?? DM <@707480543834669116>"})
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
    embed = discord.Embed(title="🛰️ DOUGHLAS AUTO POST SYSTEM", 
                          description="Gunakan tombol di bawah untuk mengelola auto post.\nSemua menu bersifat **Private** (hanya Anda yang melihat).", 
                          color=discord.Color.blue())
    await ctx.send(embed=embed, view=ControlView())

if __name__ == "__main__":
    bot.run(TOKEN_BOT)
