import os
import time
import discord
import random
import asyncio
import urllib.parse
import aiohttp
from io import BytesIO
from discord.ext import commands
from discord import app_commands
from google import genai
from gradio_client import Client
from gtts import gTTS # NEW: Google Text-to-Speech

from database import (
    initialize_database,
    save_message,
    save_memory,
    get_memory
)

# =====================================
# CONFIG & CREDENTIALS
# =====================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")

GEMINI_KEYS = [
    os.getenv("GEMINI_API_KEY"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3")
]
VALID_KEYS = [key for key in GEMINI_KEYS if key]

DEVELOPER_ID = 123456789012345678 # ⚠️ REPLACE WITH YOUR ID ⚠️

if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN is missing.")
if not VALID_KEYS:
    raise ValueError("No GEMINI_API_KEY found.")

initialize_database()

gemini_clients = [genai.Client(api_key=key) for key in VALID_KEYS]

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True # Required for VC

bot = commands.Bot(command_prefix="!", intents=intents)

# =====================================
# AI FUNCTION (TEXT)
# =====================================
def ask_gemini(prompt):
    last_error = None
    for i, client in enumerate(gemini_clients):
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
                if "503" in last_error or "UNAVAILABLE" in last_error:
                    time.sleep(2) 
                    continue
                else:
                    break 
    return f"Sorry, all my AI brains are exhausted! Error: {last_error}"

# =====================================
# DEVELOPER BROADCAST (10x SPAM)
# =====================================
@bot.tree.command(name="announce", description="[DEV ONLY] Send a message 10 times to all servers")
@app_commands.describe(message="The message to broadcast")
async def announce(interaction: discord.Interaction, message: str):
    if interaction.user.id != DEVELOPER_ID:
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    success_count = fail_count = 0

    for guild in bot.guilds:
        channel = None
        for c in guild.text_channels:
            if c.permissions_for(guild.me).send_messages:
                channel = c
                break

        if channel:
            try:
                for _ in range(10):
                    await channel.send(message)
                    await asyncio.sleep(1.5) 
                success_count += 1
            except Exception:
                fail_count += 1
        await asyncio.sleep(1)

    await interaction.followup.send(f"✅ **Broadcast Complete!** Sent to: `{success_count}` servers.")

# =====================================
# NEW: VOICE CALL FEATURE
# =====================================
@bot.tree.command(name="chotu_vc", description="Make Chotu join VC and answer your question out loud!")
@app_commands.describe(question="What do you want to ask Chotu?")
async def chotu_vc(interaction: discord.Interaction, question: str):
    if not interaction.user.voice:
        await interaction.response.send_message("❌ You must be in a Voice Channel first!", ephemeral=True)
        return

    await interaction.response.defer()
    
    # 1. Join Voice Channel
    vc_channel = interaction.user.voice.channel
    voice_client = discord.utils.get(bot.voice_clients, guild=interaction.guild)
    
    if not voice_client:
        voice_client = await vc_channel.connect()
    elif voice_client.channel != vc_channel:
        await voice_client.move_to(vc_channel)

    # 2. Get Answer from Gemini
    # Adding a prompt instruction to keep it conversational and brief for speech
    speech_prompt = f"Please answer this conversationally and briefly (under 3 sentences) because it will be spoken out loud: {question}"
    answer = ask_gemini(speech_prompt)
    
    # 3. Convert Answer to Speech (Using Indian English accent)
    try:
        tts = gTTS(text=answer, lang='en', tld='co.in')
        tts.save("chotu_speech.mp3")
        
        # 4. Play the audio in VC
        if voice_client.is_playing():
            voice_client.stop()
            
        voice_client.play(discord.FFmpegPCMAudio("chotu_speech.mp3"))
        
        await interaction.followup.send(f"🗣️ **Chotu is speaking...**\n*You asked:* {question}")
    except Exception as e:
        await interaction.followup.send(f"❌ Audio Error: {e}\n(Make sure FFmpeg is installed on your server!)")

@bot.tree.command(name="leave_vc", description="Make Chotu leave the voice channel")
async def leave_vc(interaction: discord.Interaction):
    voice_client = discord.utils.get(bot.voice_clients, guild=interaction.guild)
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        await interaction.response.send_message("👋 Chotu left the voice channel.")
    else:
        await interaction.response.send_message("I'm not in a voice channel!", ephemeral=True)

# =====================================
# SERVER MANAGEMENT (GOD MODE)
# =====================================
@bot.tree.command(name="server_setup", description="[ADMIN] Auto-build a beautiful server layout")
@app_commands.default_permissions(administrator=True)
async def server_setup(interaction: discord.Interaction):
    await interaction.response.defer()
    guild = interaction.guild
    try:
        info_cat = await guild.create_category("🔰 SERVER INFO")
        await guild.create_text_channel("📜・rules", category=info_cat)
        
        chat_cat = await guild.create_category("💬 COMMUNITY")
        await guild.create_text_channel("💬・general", category=chat_cat)
        
        voice_cat = await guild.create_category("🔊 VOICE CHANNELS")
        await guild.create_voice_channel("🎧 Lounge", category=voice_cat)
        
        await interaction.followup.send("✅ **Server successfully structured!**")
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}")

@bot.tree.command(name="nuke", description="[ADMIN] Deletes and recreates this channel")
@app_commands.default_permissions(administrator=True)
async def nuke(interaction: discord.Interaction):
    channel = interaction.channel
    try:
        new_channel = await channel.clone(reason="Nuked by Admin")
        await channel.delete()
        await new_channel.send("💥 **CHANNEL NUKED** 💥")
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(name="clear", description="[MOD] Delete multiple messages")
@app_commands.default_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int):
    if amount < 1 or amount > 100:
        return await interaction.response.send_message("❌ Choose 1-100.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 Deleted **{len(deleted)}** messages.")

# =====================================
# STANDARD COMMANDS
# =====================================
@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! {round(bot.latency * 1000)}ms")

@bot.tree.command(name="ask", description="Ask AI anything")
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

@bot.tree.command(name="imagine", description="Generate an image using Z-Image-Turbo!")
async def imagine(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    try:
        gradio_client = Client("mrfakename/Z-Image-Turbo", token=HF_TOKEN)
        def generate():
            return gradio_client.predict(prompt=prompt, randomize_seed=True, api_name="/generate_image")
            
        result_tuple = await asyncio.to_thread(generate)
        image_path = result_tuple[0]

        with open(image_path, 'rb') as f:
            image_data = f.read()

        file = discord.File(BytesIO(image_data), filename="z_image_turbo.jpg")
        embed = discord.Embed(title=f"🎨 {prompt[:200]}...", color=discord.Color.purple())
        embed.set_image(url="attachment://z_image_turbo.jpg")
        await interaction.followup.send(embed=embed, file=file)
    except Exception as e:
        await interaction.followup.send(f"Sorry, my drawing tablet broke! Error: {str(e)}")

# =====================================
# EVENTS
# =====================================
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()  
        print("=" * 50)  
        print("BOT ONLINE - CHOTU CHAIWALA IS READY (ADS REMOVED)")  
        print(f"Logged in as: {bot.user}")  
        print(f"Commands Synced: {len(synced)}")  
        print("=" * 50)
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.event
async def on_message(message):
    if message.author.bot: return
    if bot.user in message.mentions:
        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip()  
        if prompt:  
            response = ask_gemini(prompt)  
            await message.reply(response[:1900])  
    await bot.process_commands(message)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
