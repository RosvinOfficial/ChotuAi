import discord
from discord.ext import commands
from g4f.client import AsyncClient

# Set up Discord bot intents
intents = discord.Intents.default()
intents.message_content = True

# Initialize the bot with the command prefix '!'
bot = commands.Bot(command_prefix="!", intents=intents)

# Initialize the g4f asynchronous client
g4f_client = AsyncClient()

@bot.event
async def on_ready():
    print(f'Logged in successfully as {bot.user} (ID: {bot.user.id})')
    print('------')

@bot.command(name="chat", help="Chat with the free AI")
async def chat(ctx, *, prompt: str = None):
    # Ensure the user provided a message
    if not prompt:
        await ctx.send("Please provide a prompt! Example: `!chat Write a short story about a robot.`")
        return

    # Trigger Discord's typing indicator while waiting for the AI
    async with ctx.typing():
        try:
            # Request response from the g4f library asynchronously
            response = await g4f_client.chat.completions.create(
                model="gpt-3.5-turbo", # You can also test 'gpt-4o' or 'gpt-4o-mini'
                messages=[{"role": "user", "content": prompt}],
                web_search=False
            )
            
            # Extract the AI's string reply
            reply = response.choices[0].message.content
            
            # Discord limits a single message to 2000 characters
            # This logic splits the reply into chunks if the AI generates a long response
            if len(reply) > 2000:
                for chunk in [reply[i:i+2000] for i in range(0, len(reply), 2000)]:
                    await ctx.send(chunk)
            else:
                await ctx.send(reply)
                
        except Exception as e:
            await ctx.send(f"An error occurred while connecting to the free AI provider: {e}")

# Replace with your actual Discord Bot Token
bot.run('YOUR_DISCORD_BOT_TOKEN_HERE')
