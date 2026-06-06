import discord
from discord.ext import commands
import google.generativeai as genai

DISCORD_TOKEN = "DISCORD_TOKEN"

GEMINI_KEYS = [
    "GEMINI_KEY_1",
    "GEMINI_KEY_2",
    "GEMINI_KEY_3"
]

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def generate_response(prompt):
    last_error = None

    for key in GEMINI_KEYS:
        try:
            genai.configure(api_key=key)

            model = genai.GenerativeModel("gemini-2.5-flash")

            response = model.generate_content(prompt)

            return response.text

        except Exception as e:
            last_error = e
            continue

    raise Exception(f"All configured providers failed: {last_error}")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if bot.user in message.mentions:
        try:
            prompt = message.content.replace(
                f"<@{bot.user.id}>", ""
            ).strip()

            if not prompt:
                return

            async with message.channel.typing():
                answer = generate_response(prompt)

            await message.reply(answer[:2000])

        except Exception:
            await message.reply(
                "AI service is currently unavailable."
            )

    await bot.process_commands(message)


bot.run(DISCORD_TOKEN)