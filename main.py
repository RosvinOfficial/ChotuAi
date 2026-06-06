main.py

import os
import sqlite3
import qrcode
import discord

from io import BytesIO
from discord.ext import commands
from discord import app_commands
from google import genai

=====================================

CONFIG

=====================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

UPI_ID = "talentroze@upi"
UPI_NAME = "Talentroze"
AD_PRICE = 399

if not DISCORD_TOKEN:
raise ValueError("DISCORD_TOKEN is missing")

if not GEMINI_API_KEY:
raise ValueError("GEMINI_API_KEY is missing")

=====================================

GEMINI

=====================================

client = genai.Client(api_key=GEMINI_API_KEY)

=====================================

DATABASE

=====================================

conn = sqlite3.connect("bot.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS advertisements (
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id TEXT,
username TEXT,
link TEXT,
status TEXT
)
""")

conn.commit()

=====================================

DISCORD

=====================================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
command_prefix="!",
intents=intents
)

=====================================

AI FUNCTION

=====================================

def ask_gemini(prompt):

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt
)

return response.text

=====================================

EVENTS

=====================================

@bot.event
async def on_ready():

synced = await bot.tree.sync()

print("=" * 50)
print("BOT ONLINE")
print(bot.user)
print(f"Slash Commands: {len(synced)}")
print("=" * 50)

=====================================

/PING

=====================================

@bot.tree.command(
name="ping",
description="Check bot latency"
)
async def ping(interaction: discord.Interaction):

await interaction.response.send_message(
    f"Pong! {round(bot.latency * 1000)}ms"
)

=====================================

/ASK

=====================================

@bot.tree.command(
name="ask",
description="Ask the AI anything"
)
async def ask(
interaction: discord.Interaction,
question: str
):

await interaction.response.defer()

try:

    answer = ask_gemini(question)

    if len(answer) > 1900:
        answer = answer[:1900]

    await interaction.followup.send(answer)

except Exception as e:

    await interaction.followup.send(
        f"Error: {e}"
    )

=====================================

/ADVERTISEMENT

=====================================

@bot.tree.command(
name="advertisement",
description="Submit a link for advertisement review"
)
async def advertisement(
interaction: discord.Interaction,
link: str
):

cursor.execute(
    """
    INSERT INTO advertisements
    (
        user_id,
        username,
        link,
        status
    )
    VALUES (?, ?, ?, ?)
    """,
    (
        str(interaction.user.id),
        str(interaction.user),
        link,
        "pending_payment"
    )
)

conn.commit()

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

file = discord.File(
    buffer,
    filename="payment_qr.png"
)

embed = discord.Embed(
    title="Advertisement Request",
    color=discord.Color.green()
)

embed.add_field(
    name="Submitted Link",
    value=link,
    inline=False
)

embed.add_field(
    name="Price",
    value="₹399",
    inline=False
)

embed.add_field(
    name="UPI ID",
    value=UPI_ID,
    inline=False
)

embed.add_field(
    name="Payment Note",
    value=link,
    inline=False
)

embed.set_image(
    url="attachment://payment_qr.png"
)

embed.set_footer(
    text="Pay ₹399 and your request will be reviewed."
)

await interaction.response.send_message(
    embed=embed,
    file=file,
    ephemeral=True
)

=====================================

MENTION CHAT

=====================================

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

            if len(response) > 1900:
                response = response[:1900]

            await message.reply(response)

        except Exception:

            await message.reply(
                "AI service unavailable."
            )

await bot.process_commands(message)

=====================================

START

=====================================

bot.run(DISCORD_TOKEN)