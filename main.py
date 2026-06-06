import os
import asyncio
import discord
from discord.ext import commands
from google import genai

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN is missing")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is missing")

client = genai.Client(api_key=GEMINI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

SYSTEM_PROMPT = """
You are PRIMEXSYNDIC AI.
Be helpful, friendly and concise.
"""

def ask_gemini(prompt: str) -> str:
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"{SYSTEM_PROMPT}\n\nUser: {prompt}"
    )

    if hasattr(response, "text") and response.text:
        return response.text

    return "I couldn't generate a response."

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.change_presence(
        activity=discord.Game("PRIMEXSYNDIC AI")
    )

@bot.command()
async def ping(ctx):
    await ctx.send(f"Pong! {round(bot.latency * 1000)}ms")

@bot.command()
async def ai(ctx, *, prompt):
    async with ctx.typing():
        try:
            response = await asyncio.to_thread(
                ask_gemini,
                prompt
            )

            if len(response) > 1900:
                response = response[:1900]

            await ctx.reply(response)

        except Exception as e:
            await ctx.reply(
                f"Error: {str(e)[:300]}"
            )

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
            async with message.channel.typing():
                try:
                    response = await asyncio.to_thread(
                        ask_gemini,
                        prompt
                    )

                    if len(response) > 1900:
                        response = response[:1900]

                    await message.reply(response)

                except Exception:
                    await message.reply(
                        "AI service unavailable."
                    )

    await bot.process_commands(message)

bot.run(DISCORD_TOKEN)