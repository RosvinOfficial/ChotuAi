import os
import sqlite3
import qrcode
import discord
from discord import app_commands
from discord.ext import commands

DB_FILE = "bot.db"

UPI_ID = "talentroze@upi"
UPI_NAME = "Talentroze"
PRICE = 399

def init_db():
conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS advertisements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    username TEXT,
    link TEXT,
    status TEXT
)
""")

conn.commit()
conn.close()

init_db()

class Advertisement(commands.Cog):

def __init__(self, bot):
    self.bot = bot

@app_commands.command(
    name="advertisement",
    description="Submit a server, website, or product link."
)
async def advertisement(
    self,
    interaction: discord.Interaction,
    link: str
):

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO advertisements
        (user_id, username, link, status)
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
    conn.close()

    upi_uri = (
        f"upi://pay?"
        f"pa={UPI_ID}"
        f"&pn={UPI_NAME}"
        f"&am={PRICE}"
        f"&cu=INR"
        f"&tn={link}"
    )

    qr = qrcode.make(upi_uri)

    qr_file = f"payment_{interaction.user.id}.png"
    qr.save(qr_file)

    embed = discord.Embed(
        title="Advertisement Request",
        description="Payment required before review.",
        color=discord.Color.green()
    )

    embed.add_field(
        name="Link",
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
        name="UPI URI",
        value=upi_uri[:1024],
        inline=False
    )

    file = discord.File(
        qr_file,
        filename="payment_qr.png"
    )

    embed.set_image(
        url="attachment://payment_qr.png"
    )

    await interaction.response.send_message(
        embed=embed,
        file=file,
        ephemeral=True
    )

async def setup(bot):
await bot.add_cog(
Advertisement(bot)
)