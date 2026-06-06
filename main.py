import os

print("=" * 50)
print("DEBUGGING ENVIRONMENT VARIABLES")
print("=" * 50)

print("DISCORD_TOKEN EXISTS:", "DISCORD_TOKEN" in os.environ)
print("GEMINI_API_KEY EXISTS:", "GEMINI_API_KEY" in os.environ)

discord_token = os.getenv("DISCORD_TOKEN")
gemini_key = os.getenv("GEMINI_API_KEY")

print("DISCORD_TOKEN VALUE:", repr(discord_token))
print("GEMINI_API_KEY VALUE:", repr(gemini_key))

print("=" * 50)