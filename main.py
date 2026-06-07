import os
import time
import qrcode
import discord
import random
import asyncio
import urllib.parse
import aiohttp
from io import BytesIO
from discord.ext import commands, tasks
from discord import app_commands
from google import genai
from gradio_client import Client

from database import (
    initialize_database,
    save_message,
    create_advertisement,
    save_memory,
    get_memory
)

# =====================================
# CONFIG & CREDENTIALS
# =====================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")

# API Key Rotation Setup
GEMINI_KEYS = [
    os.getenv("GEMINI_API_KEY"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3")
]

# Keep only the keys that are actually filled in your .env
VALID_KEYS = [key for key in GEMINI_KEYS if key]

UPI_ID = "talentroze@upi"
UPI_NAME = "Talentroze"
AD_PRICE = 399

# ⚠️ REPLACE THIS WITH YOUR DISCORD USER ID ⚠️
DEVELOPER_ID = 1451643734956445839

if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN is missing. Make sure it is set in your environment variables.")

if not VALID_KEYS:
    raise ValueError("No GEMINI_API_KEY found. Please add at least one key to your environment variables.")

# 👇 YAHAN AAP APNE ADS DALENGE 👇
ADS_LIST = [
    """╔═══════════════════════════════════════╗
║               🌟 𝗘𝗡𝗧𝗘𝗥 𝗣𝗥𝗜𝗠𝗘 𝗫 𝗦𝗬𝗡𝗖𝗔𝗧𝗘! 🌟
╚═══════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 **Looking for a gaming server that's fun, active, and full of events?**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🏆 𝗣𝗥𝗜𝗠𝗘 𝗫 𝗦𝗬𝗡𝗖𝗔𝗧𝗘 𝗜𝗦 𝗧𝗛𝗘 𝗣𝗟𝗔𝗖𝗘 𝗧𝗢 𝗕𝗘! 🏆

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎮 **Minecraft | Roblox | GTA | BGMI | Free Fire | Fortnite | COD**

   → Java + PE Crossplay | Land Claim | Grave System
   → Daily Events | Giveaways | Special Roles

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎉 **𝗪𝗛𝗬 𝗣𝗥𝗜𝗠𝗘 𝗫 𝗦𝗬𝗡𝗖𝗔𝗧𝗘?**

✅ Friendly and active community
✅ Regular events & giveaways
✅ Self-roles & active staff
✅ No toxicity — just pure gaming fun

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚡ **𝗥𝗲𝗮𝗱𝘆 𝘁𝗼 𝗝𝗼𝗶𝗻?**

Don't miss out — jump in now and be part of the adventure!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

👉 𝗝𝗢𝗜𝗡 𝗡𝗢𝗪  👈

https://discord.gg/TPzgS8g9xr

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
]
# 👆 YAHAN AAP APNE ADS DALENGE 👆

# =====================================
# DATABASE INIT
# =====================================
initialize_database()

# =====================================
# GEMINI CLIENTS (API ROTATION SETUP)
# =====================================
gemini_clients = [genai.Client(api_key=key) for key in VALID_KEYS]

# =====================================
# DISCORD BOT SETUP
# =====================================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# =====================================
# AI FUNCTION (AUTO-SWITCHING & RETRY)
# =====================================
def ask_gemini(prompt):
    last_error = None
    
    for i, client in enumerate(gemini_clients):
        # Try each key 2 times before giving up on it
        for attempt in range(2): 
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt
                )
                if hasattr(response, "text"):
                    return response.text
            except Exception as e:
                last_error = str(e)
                # If Google is overloaded (503), wait 2 seconds and try again
                if "503" in last_error or "UNAVAILABLE" in last_error:
                    print(f"Google is busy. Retrying API Key {i + 1} (Attempt {attempt + 1})...")
                    time.sleep(2) 
                    continue
                else:
                    print(f"API Key {i + 1} failed: {e}. Switching keys...")
                    break 

    return f"Sorry, all my AI brains are exhausted right now! (Limits reached). Last Error: {last_error}"

# =====================================
# RANDOM ADVERTISEMENT TASK
# =====================================
@tasks.loop(hours=1)
async def random_ad_task():
    if not ADS_LIST:
        return 

    wait_time = random.randint(600, 2700)
    await asyncio.sleep(wait_time)

    ad_message = random.choice(ADS_LIST)

    if not bot.guilds:
        return
        
    random_guild = random.choice(bot.guilds)
    channel = None
    
    try:
        from database import get_announcement_channel
        channel_id = get_announcement_channel(random_guild.id)
        if channel_id:
            channel = bot.get_channel(int(channel_id))
    except ImportError:
        pass

    if not channel:
        for c in random_guild.text_channels:
            if c.name.lower() == "general" and c.permissions_for(random_guild.me).send_messages:
                channel = c
                break

    if not channel and random_guild.system_channel:
        if random_guild.system_channel.permissions_for(random_guild.me).send_messages:
            channel = random_guild.system_channel
        
    if not channel:
        for c in random_guild.text_channels:
            if c.permissions_for(random_guild.me).send_messages:
                channel = c
                break

    if channel:
        try:
            await channel.send(f"📢 **Sponsored Advertisement** 📢\n\n{ad_message}")
            print(f"Ad sent to #{channel.name} in server: {random_guild.name}")
        except Exception as e:
            print(f"Ad bhejne mein error aayi: {e}")

# =====================================
# GLOBAL ANNOUNCEMENT (DEVELOPER ONLY)
# =====================================
@bot.tree.command(name="announce", description="[DEV ONLY] Secretly blast an announcement to all servers")
@app_commands.describe(message="The message to broadcast to everyone")
async def announce(interaction: discord.Interaction, message: str):
    if interaction.user.id != DEVELOPER_ID:
        await interaction.response.send_message("❌ You do not have permission to use this developer command.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    
    success_count = 0
    fail_count = 0

    for guild in bot.guilds:
        channel = None
        
        try:
            from database import get_announcement_channel
            channel_id = get_announcement_channel(guild.id)
            if channel_id:
                channel = bot.get_channel(int(channel_id))
        except ImportError:
            pass

        if not channel:
            for c in guild.text_channels:
                if c.name.lower() == "general" and c.permissions_for(guild.me).send_messages:
                    channel = c
                    break

        if not channel and guild.system_channel:
            if guild.system_channel.permissions_for(guild.me).send_messages:
                channel = guild.system_channel
            
        if not channel:
            for c in guild.text_channels:
                if c.permissions_for(guild.me).send_messages:
                    channel = c
                    break

        if channel:
            try:
                await channel.send(f"⚠️ **DEVELOPER ANNOUNCEMENT** ⚠️\n\n{message}")
                success_count += 1
            except Exception:
                fail_count += 1
                
        # Wait 1 second between servers to avoid Discord banning the bot for spam
        await asyncio.sleep(1)

    await interaction.followup.send(f"✅ **Broadcast Complete!**\nSent to: `{success_count}` servers.\nFailed: `{fail_count}` servers.")

# =====================================
# SERVER MANAGEMENT (GOD MODE - ADMIN ONLY)
# =====================================
@bot.tree.command(name="server_setup", description="[ADMIN] Auto-build a beautiful server layout with channels")
@app_commands.default_permissions(administrator=True)
async def server_setup(interaction: discord.Interaction):
    await interaction.response.defer()
    guild = interaction.guild

    try:
        info_cat = await guild.create_category("🔰 SERVER INFO")
        await guild.create_text_channel("📜・rules", category=info_cat)
        await guild.create_text_channel("📢・announcements", category=info_cat)

        chat_cat = await guild.create_category("💬 COMMUNITY")
        await guild.create_text_channel("💬・general", category=chat_cat)
        await guild.create_text_channel("🤖・bot-commands", category=chat_cat)
        await guild.create_text_channel("🐸・memes", category=chat_cat)

        voice_cat = await guild.create_category("🔊 VOICE CHANNELS")
        await guild.create_voice_channel("🎧 Lounge", category=voice_cat)
        await guild.create_voice_channel("🎮 Gaming 1", category=voice_cat)

        await interaction.followup.send("✅ **Server successfully structured!** Beautiful channels have been created.")
    except Exception as e:
        await interaction.followup.send(f"❌ Error creating channels: {e}")

@bot.tree.command(name="create_channel", description="[ADMIN] Tell the bot to build a new channel")
@app_commands.describe(
    name="Name of the channel (e.g., chotu-ka-adda)",
    channel_type="Type 'text' or 'voice' (Defaults to text)"
)
@app_commands.default_permissions(administrator=True)
async def create_channel(interaction: discord.Interaction, name: str, channel_type: str = "text"):
    await interaction.response.defer()
    guild = interaction.guild
    try:
        if channel_type.lower() == "voice":
            await guild.create_voice_channel(name)
            icon = "🔊"
        else:
            await guild.create_text_channel(name)
            icon = "💬"
            
        await interaction.followup.send(f"✅ **Done!** I have built the {icon} `{name}` channel for you.")
    except Exception as e:
        await interaction.followup.send(f"❌ Error creating channel: {e}")

@bot.tree.command(name="server_logo", description="[ADMIN] Change the server icon")
@app_commands.describe(image="Upload the new logo image")
@app_commands.default_permissions(administrator=True)
async def server_logo(interaction: discord.Interaction, image: discord.Attachment):
    await interaction.response.defer()
    if not image.content_type.startswith("image/"):
        await interaction.followup.send("❌ Please upload a valid image file!")
        return
    try:
        image_bytes = await image.read()
        await interaction.guild.edit(icon=image_bytes)
        await interaction.followup.send("✅ **Server logo successfully updated!**")
    except Exception as e:
        await interaction.followup.send(f"❌ Error updating logo. Ensure bot has permissions. {e}")

@bot.tree.command(name="server_rename", description="[ADMIN] Change the server name")
@app_commands.describe(new_name="The new name for the server")
@app_commands.default_permissions(administrator=True)
async def server_rename(interaction: discord.Interaction, new_name: str):
    try:
        await interaction.guild.edit(name=new_name)
        await interaction.response.send_message(f"✅ **Server renamed to:** `{new_name}`")
    except Exception as e:
        await interaction.response.send_message(f"❌ Error renaming server: {e}")

@bot.tree.command(name="clear", description="[MOD] Delete multiple messages at once")
@app_commands.describe(amount="Number of messages to delete (1-100)")
@app_commands.default_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int):
    if amount < 1 or amount > 100:
        await interaction.response.send_message("❌ You can only delete between 1 and 100 messages at a time.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 Successfully deleted **{len(deleted)}** messages.")

@bot.tree.command(name="nuke", description="[ADMIN] Deletes and recreates this channel (Clears ALL history)")
@app_commands.default_permissions(administrator=True)
async def nuke(interaction: discord.Interaction):
    channel = interaction.channel
    try:
        new_channel = await channel.clone(reason="Nuke command requested by Admin")
        await channel.delete()
        await new_channel.send("💥 **CHANNEL NUKED** 💥\nAll previous history has been permanently destroyed.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Could not nuke channel: {e}", ephemeral=True)

# =====================================
# STANDARD COMMANDS (AI, MEMORY, ADS, IMAGES)
# =====================================
@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! {round(bot.latency * 1000)}ms")

@bot.tree.command(name="ask", description="Ask AI anything")
@app_commands.describe(question="Your question")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    try:
        answer = ask_gemini(question)  
        save_message(interaction.user.id, str(interaction.user), question)  
        if len(answer) > 1900:  
            answer = answer[:1900] + "... [Truncated]"
        await interaction.followup.send(answer)
    except Exception as e:
        await interaction.followup.send(f"Error: {str(e)}")

@bot.tree.command(name="imagine", description="Generate a high-quality image using Z-Image-Turbo!")
@app_commands.describe(prompt="What do you want Chotu Chaiwala to draw?")
async def imagine(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()

    try:
        # Pass the HF_TOKEN here to use your ZeroGPU quota
        # ✅ THE FIXED LINE:
gradio_client = Client("mrfakename/Z-Image-Turbo", token=HF_TOKEN)


        def generate():
            return gradio_client.predict(
                prompt=prompt,
                randomize_seed=True,
                api_name="/generate_image"
            )

        # Run in a background thread to prevent freezing the bot
        result_tuple = await asyncio.to_thread(generate)
        image_path = result_tuple[0]

        # Read the generated physical file
        with open(image_path, 'rb') as f:
            image_data = f.read()

        buffer = BytesIO(image_data)
        file = discord.File(buffer, filename="z_image_turbo.jpg")

        safe_prompt = prompt if len(prompt) < 230 else prompt[:230] + "..."
        embed = discord.Embed(title=f"🎨 Drawing for: {safe_prompt}", color=discord.Color.purple())
        
        if len(prompt) >= 230:
            embed.description = f"**Full Prompt:** {prompt}"

        embed.set_image(url="attachment://z_image_turbo.jpg")
        embed.set_footer(text="Generated by Z-Image-Turbo • Chotu Chaiwala")

        await interaction.followup.send(embed=embed, file=file)

    except discord.HTTPException as e:
        # If Discord blocks it for being explicit (Error 20009)
        if e.code == 20009:
            await interaction.followup.send("🚨 **Blocked!** Discord's safety filters deleted this image because it looked explicit or NSFW. Try a safer prompt!")
        else:
            await interaction.followup.send(f"Sorry, my drawing tablet broke! Error: {str(e)}")
    except Exception as e:
        print(f"Image generation error: {e}")
        await interaction.followup.send(f"Sorry, my drawing tablet broke! Error: {str(e)}")

@bot.tree.command(name="remember", description="Save a memory")
async def remember(interaction: discord.Interaction, key: str, value: str):
    save_memory(interaction.user.id, key, value)
    await interaction.response.send_message(f"Saved memory: {key}")

@bot.tree.command(name="memory", description="Get a saved memory")
async def memory(interaction: discord.Interaction, key: str):
    value = get_memory(interaction.user.id, key)
    if value:
        await interaction.response.send_message(f"{key}: {value}")
    else:
        await interaction.response.send_message("No memory found.")

@bot.tree.command(name="advertisement", description="Submit a link for advertisement review")
@app_commands.describe(link="Website, Discord server invite, or product link")
async def advertisement(interaction: discord.Interaction, link: str):
    ad_id = create_advertisement(interaction.user.id, str(interaction.user), link)
    upi_uri = f"upi://pay?pa={UPI_ID}&pn={UPI_NAME}&am={AD_PRICE}&cu=INR&tn={link}"

    qr = qrcode.make(upi_uri)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)
    
    file = discord.File(buffer, filename="payment_qr.png")

    embed = discord.Embed(title="Advertisement Request", color=discord.Color.green())
    embed.add_field(name="Advertisement ID", value=str(ad_id), inline=False)
    embed.add_field(name="Submitted Link", value=link, inline=False)
    embed.add_field(name="Price", value=f"₹{AD_PRICE}", inline=False)
    embed.add_field(name="UPI ID", value=UPI_ID, inline=False)
    embed.add_field(name="Payment Note", value=link, inline=False)
    embed.set_image(url="attachment://payment_qr.png")
    embed.set_footer(text=f"Pay ₹{AD_PRICE} and your request will be reviewed.")

    await interaction.response.send_message(embed=embed, file=file, ephemeral=True)


# =====================================
# EVENTS
# =====================================
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()  
        print("=" * 50)  
        print("BOT ONLINE - CHOTU CHAIWALA IS READY")  
        print(f"Logged in as: {bot.user}")  
        print(f"Servers: {len(bot.guilds)}")  
        print(f"Commands Synced: {len(synced)}")  
        print(f"Active API Keys: {len(VALID_KEYS)}") 
        print("=" * 50)

        if not random_ad_task.is_running():
            random_ad_task.start()
            print("Random Ad Task Started.")

    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if bot.user in message.mentions:
        prompt = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()  

        if prompt:  
            try:  
                response = ask_gemini(prompt)  
                save_message(message.author.id, str(message.author), prompt)  
                if len(response) > 1900:  
                    response = response[:1900] + "... [Truncated]" 
                await message.reply(response)  
            except Exception as e:  
                await message.reply(f"AI Error: {str(e)}")

    await bot.process_commands(message)

# =====================================
# START BOT
# =====================================
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
