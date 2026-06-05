import os
import discord
from discord.ext import commands
import g4f
from g4f.client import AsyncClient

# 1. Set up Discord intents so the bot can read messages
intents = discord.Intents.default()
intents.message_content = True

# 2. Initialize the bot with the command prefix '!'
bot = commands.Bot(command_prefix="!", intents=intents)

# 3. Force g4f to use Blackbox (highly stable provider without API key requirements)
g4f_client = AsyncClient(
    provider=g4f.Provider.Blackbox
)

@bot.event
async def on_ready():
    print(f'Logged in successfully as {bot.user} (ID: {bot.user.id})')
    print('------')
    print('Bot is online and ready 24/7!')

@bot.command(name="chat", help="Chat with the free AI")
async def chat(ctx, *, prompt: str = None):
    # Ensure the user provided a message
    if not prompt:
        await ctx.send("Please provide a prompt! Example: `!chat Tell me a joke.`")
        return

    # Trigger Discord's typing indicator while waiting for the AI
    async with ctx.typing():
        try:
            # Request response from the specific provider
            response = await g4f_client.chat.completions.create(
                model="gpt-3.5-turbo", 
                messages=[{"role": "user", "content": prompt}],
                web_search=False
            )
            
            # Extract the AI's string reply
            reply = response.choices[0].message.content
            
            # Discord limits a single message to 2000 characters
            if len(reply) > 2000:
                for chunk in [reply[i:i+2000] for i in range(0, len(reply), 2000)]:
                    await ctx.send(chunk)
            else:
                await ctx.send(reply)
                
        except Exception as e:
            await ctx.send(f"An error occurred while connecting to the free AI: {e}")

# 4. Run the bot using the secret environment variable from Railway
bot.run(os.environ['DISCORD_BOT_TOKEN'])
