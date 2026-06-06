import os
import discord
from dotenv import load_dotenv
from google import genai

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

if not DISCORD_TOKEN:
raise ValueError("DISCORD_TOKEN is missing.")

if not GEMINI_API_KEY:
raise ValueError("GEMINI_API_KEY is missing.")

client = genai.Client(api_key=GEMINI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)

async def ask_gemini(prompt: str) -> str:
try:
response = client.models.generate_content(
model="gemini-2.5-flash",
contents=prompt
)

    if hasattr(response, "text") and response.text:
        return response.text

    return "I couldn't generate a response."
except Exception as e:
    return f"Error: {str(e)}"

@bot.event
async def on_ready():
print(f"Logged in as {bot.user}")
print("Bot is online.")

@bot.event
async def on_message(message):
if message.author.bot:
return

should_reply = (
    bot.user in message.mentions
    or message.content.lower().startswith("!ai ")
)

if not should_reply:
    return

prompt = message.content

if bot.user in message.mentions:
    prompt = prompt.replace(f"<@{bot.user.id}>", "")
    prompt = prompt.replace(f"<@!{bot.user.id}>", "")

if prompt.lower().startswith("!ai "):
    prompt = prompt[4:]

prompt = prompt.strip()

if not prompt:
    await message.reply("Please provide a message.")
    return

async with message.channel.typing():
    answer = await ask_gemini(prompt)

if len(answer) > 1900:
    answer = answer[:1900]

await message.reply(answer)

bot.run(DISCORD_TOKEN)