import sqlite3
from datetime import datetime

DB_NAME = "bot.db"

# ==========================================
# CONNECTION
# ==========================================
def get_connection():
    return sqlite3.connect(DB_NAME)

# ==========================================
# DATABASE SETUP
# ==========================================
def initialize_database():
    conn = get_connection()
    cursor = conn.cursor()

    # User Messages
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        username TEXT,
        message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Advertisement Requests
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS advertisements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        username TEXT,
        link TEXT,
        status TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Bot Memory
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        memory_key TEXT,
        memory_value TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Server Settings
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS server_settings (
        guild_id TEXT PRIMARY KEY,
        guild_name TEXT,
        announcement_channel TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

# ==========================================
# MESSAGE FUNCTIONS
# ==========================================
def save_message(user_id, username, message):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO messages
        (user_id, username, message)
        VALUES (?, ?, ?)
        """,
        (str(user_id), username, message)
    )

    conn.commit()
    conn.close()

def get_last_messages(user_id, limit=10):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT message
        FROM messages
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (str(user_id), limit)
    )

    rows = cursor.fetchall()
    conn.close()
    
    return rows

# ==========================================
# ADVERTISEMENT FUNCTIONS
# ==========================================
def create_advertisement(user_id, username, link):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO advertisements
        (user_id, username, link, status)
        VALUES (?, ?, ?, ?)
        """,
        (str(user_id), username, link, "pending_payment")
    )

    ad_id = cursor.lastrowid

    conn.commit()
    conn.close()
    
    return ad_id

def approve_advertisement(ad_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE advertisements
        SET status = 'approved'
        WHERE id = ?
        """,
        (ad_id,)
    )

    conn.commit()
    conn.close()

def reject_advertisement(ad_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE advertisements
        SET status = 'rejected'
        WHERE id = ?
        """,
        (ad_id,)
    )

    conn.commit()
    conn.close()

def get_pending_ads():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM advertisements
        WHERE status = 'pending_payment'
        """
    )

    data = cursor.fetchall()
    conn.close()
    
    return data

# ==========================================
# MEMORY FUNCTIONS
# ==========================================
def save_memory(user_id, key, value):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO memory
        (user_id, memory_key, memory_value)
        VALUES (?, ?, ?)
        """,
        (str(user_id), key, value)
    )

    conn.commit()
    conn.close()

def get_memory(user_id, key):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT memory_value
        FROM memory
        WHERE user_id = ?
        AND memory_key = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (str(user_id), key)
    )

    row = cursor.fetchone()
    conn.close()

    if row:
        return row[0]
        
    return None

# ==========================================
# SERVER SETTINGS
# ==========================================
def set_announcement_channel(guild_id, guild_name, channel_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO
        server_settings
        (guild_id, guild_name, announcement_channel)
        VALUES (?, ?, ?)
        """,
        (str(guild_id), guild_name, str(channel_id))
    )

    conn.commit()
    conn.close()

def get_announcement_channel(guild_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT announcement_channel
        FROM server_settings
        WHERE guild_id = ?
        """,
        (str(guild_id),)
    )

    row = cursor.fetchone()
    conn.close()

    if row:
        return row[0]
        
    return None

# ==========================================
# STARTUP
# ==========================================
if __name__ == "__main__":
    initialize_database()
