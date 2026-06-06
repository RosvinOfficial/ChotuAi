import os
import qrcode
import discord
import random
import asyncio
from io import BytesIO
from discord.ext import commands, tasks
from discord import app_commands
from google import genai

from database import (
    initialize_database,
    save_message,
    create_advertisement,
    save_memory,
    get_memory
)

# =====================================
# CONFIG & ADVERTISEMENTS
# =====================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
# Key 1: For text generation
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") 
# Key 2: For image generation
GEMINI_IMAGE_API_KEY = os.getenv("GEMINI_IMAGE_API_KEY") 

UPI_ID = "talentroze@upi"
UPI_NAME = "Talentroze"
AD_PRICE = 399

if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN is missing. Make sure it is set in your environment variables.")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is missing. Make sure it is set in your environment variables.")

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
# GEMINI CLIENTS
# =====================================
# Client for answering questions
client = genai.Client(api_key=GEMINI_API_KEY)

# Client for generating images (Only starts if the second key is provided)
if GEMINI_IMAGE_API_KEY:
    image_client = genai.Client(api_key=GEMINI_IMAGE_API_KEY)
else:
    image_client = None
    print("WARNING: GEMINI_IMAGE_API_KEY is missing. Image generation will be disabled.")

# =====================================
# DISCORD BOT SETUP
# =====================================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# =====================================
# AI FUNCTION (TEXT)
# =====================================
def ask_gemini(prompt):
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    if hasattr(response, "text"):
        return response.text
    return "No response generated."
# =====================================
# RANDOM ADVERTISEMENT TASK
# =====================================
@tasks.loop(hours=1)
async def random_ad_task():
    if not ADS_LIST:
        return 

    # 1. Random time wait karna
    wait_time = random.randint(600, 2700)
    await asyncio.sleep(wait_time)

    # 2. List mein se ek random ad uthana
    ad_message = random.choice(ADS_LIST)

    # 3. Ek random server uthana
    if not bot.guilds:
        return
        
    random_guild = random.choice(bot.guilds)
    channel = None
    
    # PRIORITY 1: Database mein set kiya hua announcement channel dhoondhna
    try:
        from database import get_announcement_channel
        channel_id = get_announcement_channel(random_guild.id)
        if channel_id:
            channel = bot.get_channel(int(channel_id))
    except ImportError:
        pass

    # PRIORITY 2: Agar DB mein koi channel nahi hai, toh "general" channel dhoondhna
    if not channel:
        for c in random_guild.text_channels:
            # Check karta hai ki channel ka naam 'general' ho aur bot ke paas message bhejne ki permission ho
            if c.name.lower() == "general" and c.permissions_for(random_guild.me).send_messages:
                channel = c
                break

    # PRIORITY 3: Agar "general" bhi nahi mila, toh server ke system channel mein bhejna
    if not channel and random_guild.system_channel:
        if random_guild.system_channel.permissions_for(random_guild.me).send_messages:
            channel = random_guild.system_channel
        
    # PRIORITY 4: Agar upar ka kuch bhi nahi mila, toh kisi bhi aise channel mein bhej do jahan permission ho
    if not channel:
        for c in random_guild.text_channels:
            if c.permissions_for(random_guild.me).send_messages:
                channel = c
                break

    # 4. Message send karna
    if channel:
        try:
            await channel.send(f"📢 **Sponsored Advertisement** 📢\n\n{ad_message}")
            print(f"Ad sent to #{channel.name} in server: {random_guild.name}")
        except Exception as e:
            print(f"Ad bhejne mein error aayi: {e}")

# =====================================
# EVENTS
# =====================================
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()  
        print("=" * 50)  
        print("BOT ONLINE")  
        print(f"Logged in as: {bot.user}")  
        print(f"Servers: {len(bot.guilds)}")  
        print(f"Commands Synced: {len(synced)}")  
        print("=" * 50)

        if not random_ad_task.is_running():
            random_ad_task.start()
            print("Random Ad Task Started.")

    except Exception as e:
        print(f"Failed to sync commands: {e}")

# =====================================
# /PING
# =====================================
@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"Pong! {round(bot.latency * 1000)}ms"
    )

# =====================================
# /ASK
# =====================================
@bot.tree.command(name="ask", description="Ask AI anything")
@app_commands.describe(question="Your question")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()

    try:
        answer = ask_gemini(question)  
        
        save_message(  
            interaction.user.id,  
            str(interaction.user),  
            question  
        )  
        
        if len(answer) > 1900:  
            answer = answer[:1900] + "... [Truncated]"
            
        await interaction.followup.send(answer)

    except Exception as e:
        await interaction.followup.send(f"Error: {str(e)}")
# =====================================
# /IMAGINE (UNLIMITED FREE IMAGE GENERATION)
# =====================================
import urllib.parse 

@bot.tree.command(name="imagine", description="Generate an image using AI for free!")
@app_commands.describe(prompt="What do you want Chotu Chaiwala to draw?")
async def imagine(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()

    try:
        # Convert the user's prompt into a format safe for web URLs
        encoded_prompt = urllib.parse.quote(prompt)
        
        # Add a random seed for variety
        seed = random.randint(1, 100000)
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?seed={seed}&nologo=true&width=1024&height=1024"

        # Discord Embed Titles have a strict 256 character limit. 
        # If the prompt is too long, we truncate it and add "..."
        safe_prompt = prompt if len(prompt) < 230 else prompt[:230] + "..."

        # Create a beautiful embed to display the image
        embed = discord.Embed(
            title=f"🎨 Drawing for: {safe_prompt}",
            color=discord.Color.blue()
        )
        
        # If the prompt was really long, we put the full text in the description so it's not lost
        if len(prompt) >= 230:
            embed.description = f"**Full Prompt:** {prompt}"

        embed.set_image(url=image_url)
        embed.set_footer(text="Generated by Chotu Chaiwala")

        # Send it back to the Discord channel
        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Sorry, my drawing tablet broke! Error: {str(e)}")


# =====================================
# /REMEMBER
# =====================================
@bot.tree.command(name="remember", description="Save a memory")
async def remember(interaction: discord.Interaction, key: str, value: str):
    save_memory(
        interaction.user.id,
        key,
        value
    )
    await interaction.response.send_message(f"Saved memory: {key}")

# =====================================
# /MEMORY
# =====================================
@bot.tree.command(name="memory", description="Get a saved memory")
async def memory(interaction: discord.Interaction, key: str):
    value = get_memory(
        interaction.user.id,
        key
    )
    if value:
        await interaction.response.send_message(f"{key}: {value}")
    else:
        await interaction.response.send_message("No memory found.")

# =====================================
# /ADVERTISEMENT
# =====================================
@bot.tree.command(name="advertisement", description="Submit a link for advertisement review")
@app_commands.describe(link="Website, Discord server invite, or product link")
async def advertisement(interaction: discord.Interaction, link: str):
    ad_id = create_advertisement(
        interaction.user.id,
        str(interaction.user),
        link
    )

    upi_uri = (
        f"upi://pay?"
        f"pa={UPI_ID}"
        f"&pn={UPI_NAME}"
        f"&am={AD_PRICE}"
        f"&cu=INR"
        f"&tn={link}"
    )

    qr = qrcode.make(upi_uri)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)
    
    file = discord.File(buffer, filename="payment_qr.png")

    embed = discord.Embed(
        title="Advertisement Request",
        color=discord.Color.green()
    )
    embed.add_field(name="Advertisement ID", value=str(ad_id), inline=False)
    embed.add_field(name="Submitted Link", value=link, inline=False)
    embed.add_field(name="Price", value=f"₹{AD_PRICE}", inline=False)
    embed.add_field(name="UPI ID", value=UPI_ID, inline=False)
    embed.add_field(name="Payment Note", value=link, inline=False)
    embed.set_image(url="attachment://payment_qr.png")
    embed.set_footer(text=f"Pay ₹{AD_PRICE} and your request will be reviewed.")

    await interaction.response.send_message(
        embed=embed,
        file=file,
        ephemeral=True
    )

# =====================================
# MENTION CHAT
# =====================================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if bot.user in message.mentions:
        prompt = (  
            message.content  
            .replace(f"<@{bot.user.id}>", "")  
            .replace(f"<@!{bot.user.id}>", "")  
            .strip()  
        )  

        if prompt:  
            try:  
                response = ask_gemini(prompt)  

                save_message(  
                    message.author.id,  
                    str(message.author),  
                    prompt  
                )  

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
