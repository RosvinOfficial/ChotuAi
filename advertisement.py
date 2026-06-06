import sqlite3
import uuid

DB = "bot.db"

def init_ads_table():
conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS advertisements (
    request_id TEXT PRIMARY KEY,
    user_id TEXT,
    username TEXT,
    link TEXT,
    status TEXT
)
""")

conn.commit()
conn.close()

def create_ad_request(user_id, username, link):
request_id = f"AD-{uuid.uuid4().hex[:8].upper()}"

conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute(
    """
    INSERT INTO advertisements
    VALUES (?, ?, ?, ?, ?)
    """,
    (
        request_id,
        str(user_id),
        username,
        link,
        "pending_payment"
    )
)

conn.commit()
conn.close()

return request_id