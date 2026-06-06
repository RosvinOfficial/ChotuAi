import os
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands
from google import genai

=========================

CONFIG

=========================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not DISCORD_TOKEN:
raise ValueError("DISCORD_TOKEN is missing")

if not GEMINI_API_KEY:
raise ValueError("GEMINI_API_KEY is missing")

=========================

GEMINI

=========================

client = genai.Client(
api_key=GEMINI_API_KEY
)

=========================

DATABASE

=========================

conn = sqlite3.connect("bot.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS memory(
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id TEXT,
message TEXT
)
""")

conn.commit()

=========================

DISCORD

=========================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(
command_prefix="!",
intents=intents
)

=========================

GEMINI FUNCTION

=========================

def ask_gemini(prompt):

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt
)

if hasattr(response, "text"):
    return response.text

return "No response generated."

=========================

EVENTS

=========================

@bot.event
async def on_ready():

try:
    synced = await bot.tree.sync()

    print("=" * 50)
    print(f"Logged in as {bot.user}")
    print(f"Servers: {len(bot.guilds)}")
    print(f"Commands Synced: {len(synced)}")
    print("=" * 50)

except Exception as e:
    print(e)

=========================

PING COMMAND

=========================

@bot.tree.command(
name="ping",
description="Check bot latency"
)
async def ping(interaction: discord.Interaction):

await interaction.response.send_message(
    f"Pong! {round(bot.latency * 1000)}ms"
)

=========================

ASK COMMAND

=========================

@bot.tree.command(
name="ask",
description="Ask AI anything"
)
@app_commands.describe(
question="Your question"
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

    cursor.execute(
        "INSERT INTO memory(user_id, message) VALUES(?, ?)",
        (
            str(interaction.user.id),
            question
        )
    )

    conn.commit()

    await interaction.followup.send(answer)

except Exception as e:

    await interaction.followup.send(
        f"Error: {str(e)}"
    )

=========================

MENTION CHAT

=========================

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

    if not prompt:
        return

    async with message.channel.typing():

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

=========================

START BOT

=========================

bot.run(DISCORD_TOKEN)