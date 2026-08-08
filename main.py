"""
main.py
Production Discord server management + AI chatbot.

Single-file implementation using discord.py 2.x, google-genai, aiosqlite,
and python-dotenv. See README (printed at the bottom of this docstring's
intent) for setup: create a .env with DISCORD_TOKEN, GEMINI_API_KEY and
OWNER_ID, then `python main.py`.
"""

from __future__ import annotations

import asyncio
import io
import logging
import logging.handlers
import os
import re
import signal
import sys
import time
import traceback
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment / configuration
# ---------------------------------------------------------------------------

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OWNER_ID_RAW = os.getenv("OWNER_ID")
BOT_PREFIX = os.getenv("BOT_PREFIX", "!")
DEFAULT_AI_MODEL = os.getenv("DEFAULT_AI_MODEL", "gemini-2.0-flash")
DB_PATH = os.getenv("DB_PATH", "bot_data.db")

_missing = []
if not DISCORD_TOKEN:
    _missing.append("DISCORD_TOKEN")
if not GEMINI_API_KEY:
    _missing.append("GEMINI_API_KEY")
if not OWNER_ID_RAW:
    _missing.append("OWNER_ID")

if _missing:
    print("=" * 60)
    print("STARTUP ERROR: missing required environment variable(s):")
    for name in _missing:
        print(f"  - {name}")
    print("Create a .env file (see .env.example) and set these values.")
    print("=" * 60)
    sys.exit(1)

try:
    OWNER_ID = int(OWNER_ID_RAW)
except ValueError:
    print("STARTUP ERROR: OWNER_ID must be a numeric Discord user ID.")
    sys.exit(1)

try:
    from google import genai
    from google.genai import types as genai_types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

# ---------------------------------------------------------------------------
# Logging (never logs secrets)
# ---------------------------------------------------------------------------

logger = logging.getLogger("bot")
logger.setLevel(logging.INFO)

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(
    logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
)
logger.addHandler(_console_handler)

_file_handler = logging.handlers.RotatingFileHandler(
    "bot.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
)
_file_handler.setFormatter(
    logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
)
logger.addHandler(_file_handler)

SECRET_VALUES = {v for v in (DISCORD_TOKEN, GEMINI_API_KEY) if v}


def safe_str(text: str) -> str:
    """Scrub any accidental secret leakage before it reaches logs/users."""
    for secret in SECRET_VALUES:
        if secret and secret in text:
            text = text.replace(secret, "[REDACTED]")
    return text


# ---------------------------------------------------------------------------
# Embed helpers
# ---------------------------------------------------------------------------

COLOR_SUCCESS = 0x57F287
COLOR_ERROR = 0xED4245
COLOR_WARNING = 0xFEE75C
COLOR_INFO = 0x5865F2
COLOR_MOD = 0xEB459E
COLOR_AI = 0x9B59B6


def make_embed(title: str, description: str = "", color: int = COLOR_INFO) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.timestamp = datetime.now(timezone.utc)
    return embed


def success_embed(description: str, title: str = "Success") -> discord.Embed:
    return make_embed(f"✅ {title}", description, COLOR_SUCCESS)


def error_embed(description: str, title: str = "Error") -> discord.Embed:
    return make_embed(f"❌ {title}", description, COLOR_ERROR)


def warning_embed(description: str, title: str = "Warning") -> discord.Embed:
    return make_embed(f"⚠️ {title}", description, COLOR_WARNING)


def info_embed(description: str, title: str = "Info") -> discord.Embed:
    return make_embed(f"ℹ️ {title}", description, COLOR_INFO)


def mod_embed(title: str, description: str = "") -> discord.Embed:
    return make_embed(f"🛡️ {title}", description, COLOR_MOD)


def ai_embed(description: str, title: str = "AI") -> discord.Embed:
    return make_embed(f"🤖 {title}", description, COLOR_AI)


# ---------------------------------------------------------------------------
# Database layer
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY,
    prefix TEXT DEFAULT '!',
    ai_channel_id INTEGER,
    ai_personality TEXT DEFAULT 'friendly',
    ai_enabled INTEGER DEFAULT 1,
    memory_enabled INTEGER DEFAULT 1,
    welcome_channel_id INTEGER,
    welcome_message TEXT,
    welcome_embed INTEGER DEFAULT 1,
    welcome_ai INTEGER DEFAULT 0,
    goodbye_channel_id INTEGER,
    goodbye_message TEXT,
    mod_log_channel_id INTEGER,
    admin_log_channel_id INTEGER,
    verification_channel_id INTEGER,
    verification_role_id INTEGER,
    verification_enabled INTEGER DEFAULT 0,
    autorole_id INTEGER,
    raid_mode INTEGER DEFAULT 0,
    raid_join_threshold INTEGER DEFAULT 10,
    raid_join_window INTEGER DEFAULT 15,
    spam_msg_count INTEGER DEFAULT 5,
    spam_msg_window INTEGER DEFAULT 5,
    automod_enabled INTEGER DEFAULT 1,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS users (
    guild_id INTEGER,
    user_id INTEGER,
    xp INTEGER DEFAULT 0,
    joined_at TEXT,
    verified INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    moderator_id INTEGER,
    reason TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings(guild_id, user_id);

CREATE TABLE IF NOT EXISTS moderation_cases (
    case_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    moderator_id INTEGER,
    target_id INTEGER,
    action TEXT,
    reason TEXT,
    duration_seconds INTEGER,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_cases_guild ON moderation_cases(guild_id);

CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    channel_id INTEGER,
    user_id INTEGER,
    role TEXT,
    content TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_chat_scope ON chat_history(guild_id, channel_id, user_id);

CREATE TABLE IF NOT EXISTS ai_memory (
    guild_id INTEGER,
    user_id INTEGER,
    memory_key TEXT,
    memory_value TEXT,
    created_at TEXT,
    PRIMARY KEY (guild_id, user_id, memory_key)
);

CREATE TABLE IF NOT EXISTS welcome_settings (
    guild_id INTEGER PRIMARY KEY,
    mention_user INTEGER DEFAULT 1,
    show_member_count INTEGER DEFAULT 1,
    show_account_age INTEGER DEFAULT 1,
    rules_link TEXT
);

CREATE TABLE IF NOT EXISTS logging_settings (
    guild_id INTEGER PRIMARY KEY,
    log_joins INTEGER DEFAULT 1,
    log_leaves INTEGER DEFAULT 1,
    log_messages INTEGER DEFAULT 1,
    log_moderation INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS automod_settings (
    guild_id INTEGER PRIMARY KEY,
    block_invites INTEGER DEFAULT 1,
    block_links INTEGER DEFAULT 0,
    block_mass_mentions INTEGER DEFAULT 1,
    max_mentions INTEGER DEFAULT 5,
    block_excessive_caps INTEGER DEFAULT 1,
    caps_threshold REAL DEFAULT 0.7,
    block_everyone_abuse INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS spam_records (
    guild_id INTEGER,
    user_id INTEGER,
    strikes INTEGER DEFAULT 0,
    last_strike_at TEXT,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS blacklist (
    guild_id INTEGER,
    word TEXT,
    PRIMARY KEY (guild_id, word)
);

CREATE TABLE IF NOT EXISTS whitelist (
    guild_id INTEGER,
    kind TEXT,
    target_id INTEGER,
    PRIMARY KEY (guild_id, kind, target_id)
);

CREATE TABLE IF NOT EXISTS verification (
    guild_id INTEGER,
    user_id INTEGER,
    verified_at TEXT,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS statistics (
    guild_id INTEGER PRIMARY KEY,
    messages_processed INTEGER DEFAULT 0,
    spam_detections INTEGER DEFAULT 0,
    warnings_issued INTEGER DEFAULT 0,
    timeouts_issued INTEGER DEFAULT 0,
    kicks_issued INTEGER DEFAULT 0,
    bans_issued INTEGER DEFAULT 0,
    joins INTEGER DEFAULT 0,
    leaves INTEGER DEFAULT 0,
    ai_requests INTEGER DEFAULT 0,
    ai_errors INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS command_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    command TEXT,
    used_at TEXT
);

CREATE TABLE IF NOT EXISTS scheduled_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    channel_id INTEGER,
    content TEXT,
    interval_seconds INTEGER,
    next_run TEXT,
    created_by INTEGER,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS ignored_channels (
    guild_id INTEGER,
    channel_id INTEGER,
    system TEXT,
    PRIMARY KEY (guild_id, channel_id, system)
);

CREATE TABLE IF NOT EXISTS ignored_roles (
    guild_id INTEGER,
    role_id INTEGER,
    system TEXT,
    PRIMARY KEY (guild_id, role_id, system)
);

CREATE TABLE IF NOT EXISTS raid_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    triggered_at TEXT,
    join_count INTEGER,
    resolved INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bot_config (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS timeouts_pending (
    guild_id INTEGER,
    user_id INTEGER,
    expires_at TEXT,
    PRIMARY KEY (guild_id, user_id)
);
"""


class Database:
    """Thin async wrapper around aiosqlite with helper methods per feature."""

    def __init__(self, path: str):
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        logger.info("Database connected and schema ensured at %s", self.path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            logger.info("Database connection closed.")

    async def execute(self, query: str, params: Tuple = ()) -> None:
        async with self._lock:
            try:
                await self._conn.execute(query, params)
                await self._conn.commit()
            except aiosqlite.OperationalError as e:
                logger.warning("DB busy/error on execute, retrying once: %s", e)
                await asyncio.sleep(0.25)
                await self._conn.execute(query, params)
                await self._conn.commit()

    async def executemany(self, query: str, seq_of_params: List[Tuple]) -> None:
        async with self._lock:
            await self._conn.executemany(query, seq_of_params)
            await self._conn.commit()

    async def fetchone(self, query: str, params: Tuple = ()) -> Optional[aiosqlite.Row]:
        async with self._lock:
            cursor = await self._conn.execute(query, params)
            row = await cursor.fetchone()
            await cursor.close()
            return row

    async def fetchall(self, query: str, params: Tuple = ()) -> List[aiosqlite.Row]:
        async with self._lock:
            cursor = await self._conn.execute(query, params)
            rows = await cursor.fetchall()
            await cursor.close()
            return rows

    async def execute_return_id(self, query: str, params: Tuple = ()) -> int:
        async with self._lock:
            cursor = await self._conn.execute(query, params)
            await self._conn.commit()
            last_id = cursor.lastrowid
            await cursor.close()
            return last_id

    # -- guild settings -----------------------------------------------------

    async def ensure_guild(self, guild_id: int) -> None:
        await self.execute(
            "INSERT OR IGNORE INTO guild_settings (guild_id, updated_at) VALUES (?, ?)",
            (guild_id, datetime.now(timezone.utc).isoformat()),
        )
        await self.execute(
            "INSERT OR IGNORE INTO welcome_settings (guild_id) VALUES (?)", (guild_id,)
        )
        await self.execute(
            "INSERT OR IGNORE INTO logging_settings (guild_id) VALUES (?)", (guild_id,)
        )
        await self.execute(
            "INSERT OR IGNORE INTO automod_settings (guild_id) VALUES (?)", (guild_id,)
        )
        await self.execute(
            "INSERT OR IGNORE INTO statistics (guild_id) VALUES (?)", (guild_id,)
        )

    async def get_guild_settings(self, guild_id: int) -> aiosqlite.Row:
        await self.ensure_guild(guild_id)
        return await self.fetchone(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        )

    async def set_guild_field(self, guild_id: int, field_name: str, value: Any) -> None:
        await self.ensure_guild(guild_id)
        allowed = {
            "prefix", "ai_channel_id", "ai_personality", "ai_enabled", "memory_enabled",
            "welcome_channel_id", "welcome_message", "welcome_embed", "welcome_ai",
            "goodbye_channel_id", "goodbye_message", "mod_log_channel_id",
            "admin_log_channel_id", "verification_channel_id", "verification_role_id",
            "verification_enabled", "autorole_id", "raid_mode", "raid_join_threshold",
            "raid_join_window", "spam_msg_count", "spam_msg_window", "automod_enabled",
        }
        if field_name not in allowed:
            raise ValueError(f"Field {field_name} is not configurable.")
        await self.execute(
            f"UPDATE guild_settings SET {field_name} = ?, updated_at = ? WHERE guild_id = ?",
            (value, datetime.now(timezone.utc).isoformat(), guild_id),
        )

    async def reset_guild_settings(self, guild_id: int) -> None:
        await self.execute("DELETE FROM guild_settings WHERE guild_id = ?", (guild_id,))
        await self.ensure_guild(guild_id)

    # -- stats ---------------------------------------------------------------

    async def bump_stat(self, guild_id: int, column: str, amount: int = 1) -> None:
        await self.ensure_guild(guild_id)
        await self.execute(
            f"UPDATE statistics SET {column} = {column} + ? WHERE guild_id = ?",
            (amount, guild_id),
        )

    async def get_stats(self, guild_id: int) -> aiosqlite.Row:
        await self.ensure_guild(guild_id)
        return await self.fetchone("SELECT * FROM statistics WHERE guild_id = ?", (guild_id,))

    async def log_command_usage(self, guild_id: int, user_id: int, command: str) -> None:
        await self.execute(
            "INSERT INTO command_usage (guild_id, user_id, command, used_at) VALUES (?,?,?,?)",
            (guild_id, user_id, command, datetime.now(timezone.utc).isoformat()),
        )

    # -- moderation ------------------------------------------------------------

    async def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
        return await self.execute_return_id(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) "
            "VALUES (?,?,?,?,?)",
            (guild_id, user_id, moderator_id, reason, datetime.now(timezone.utc).isoformat()),
        )

    async def get_warnings(self, guild_id: int, user_id: int) -> List[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY id DESC",
            (guild_id, user_id),
        )

    async def clear_warnings(self, guild_id: int, user_id: int) -> None:
        await self.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )

    async def create_case(
        self, guild_id: int, moderator_id: int, target_id: int, action: str,
        reason: str, duration_seconds: Optional[int] = None,
    ) -> int:
        return await self.execute_return_id(
            "INSERT INTO moderation_cases "
            "(guild_id, moderator_id, target_id, action, reason, duration_seconds, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                guild_id, moderator_id, target_id, action, reason, duration_seconds,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    async def get_case(self, guild_id: int, case_id: int) -> Optional[aiosqlite.Row]:
        return await self.fetchone(
            "SELECT * FROM moderation_cases WHERE guild_id = ? AND case_id = ?",
            (guild_id, case_id),
        )

    # -- AI memory / chat history ---------------------------------------------

    async def add_chat_message(
        self, guild_id: int, channel_id: int, user_id: int, role: str, content: str
    ) -> None:
        await self.execute(
            "INSERT INTO chat_history (guild_id, channel_id, user_id, role, content, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (guild_id, channel_id, user_id, role, content, datetime.now(timezone.utc).isoformat()),
        )

    async def get_recent_chat(
        self, guild_id: int, channel_id: int, user_id: int, limit: int = 10
    ) -> List[aiosqlite.Row]:
        rows = await self.fetchall(
            "SELECT role, content FROM chat_history "
            "WHERE guild_id = ? AND channel_id = ? AND user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (guild_id, channel_id, user_id, limit),
        )
        return list(reversed(rows))

    async def trim_chat_history(self, guild_id: int, channel_id: int, user_id: int, keep: int = 40) -> None:
        await self.execute(
            "DELETE FROM chat_history WHERE id IN ("
            "  SELECT id FROM chat_history WHERE guild_id=? AND channel_id=? AND user_id=? "
            "  ORDER BY id DESC LIMIT -1 OFFSET ?)",
            (guild_id, channel_id, user_id, keep),
        )

    async def forget_chat_history(self, guild_id: int, user_id: int) -> None:
        await self.execute(
            "DELETE FROM chat_history WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )

    async def set_memory(self, guild_id: int, user_id: int, key: str, value: str) -> None:
        await self.execute(
            "INSERT INTO ai_memory (guild_id, user_id, memory_key, memory_value, created_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(guild_id, user_id, memory_key) DO UPDATE SET memory_value=excluded.memory_value",
            (guild_id, user_id, key, value, datetime.now(timezone.utc).isoformat()),
        )

    async def get_memory(self, guild_id: int, user_id: int) -> List[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT memory_key, memory_value FROM ai_memory WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )

    async def forget_memory(self, guild_id: int, user_id: int, key: Optional[str] = None) -> None:
        if key:
            await self.execute(
                "DELETE FROM ai_memory WHERE guild_id=? AND user_id=? AND memory_key=?",
                (guild_id, user_id, key),
            )
        else:
            await self.execute(
                "DELETE FROM ai_memory WHERE guild_id=? AND user_id=?", (guild_id, user_id)
            )

    # -- blacklist / whitelist -------------------------------------------------

    async def add_blacklist_word(self, guild_id: int, word: str) -> None:
        await self.execute(
            "INSERT OR IGNORE INTO blacklist (guild_id, word) VALUES (?, ?)",
            (guild_id, word.lower()),
        )

    async def remove_blacklist_word(self, guild_id: int, word: str) -> None:
        await self.execute(
            "DELETE FROM blacklist WHERE guild_id = ? AND word = ?", (guild_id, word.lower())
        )

    async def get_blacklist(self, guild_id: int) -> List[str]:
        rows = await self.fetchall("SELECT word FROM blacklist WHERE guild_id = ?", (guild_id,))
        return [r["word"] for r in rows]

    async def add_ignore(self, guild_id: int, kind: str, target_id: int, system: str) -> None:
        table = "ignored_channels" if kind == "channel" else "ignored_roles"
        col = "channel_id" if kind == "channel" else "role_id"
        await self.execute(
            f"INSERT OR IGNORE INTO {table} (guild_id, {col}, system) VALUES (?,?,?)",
            (guild_id, target_id, system),
        )

    async def remove_ignore(self, guild_id: int, kind: str, target_id: int, system: str) -> None:
        table = "ignored_channels" if kind == "channel" else "ignored_roles"
        col = "channel_id" if kind == "channel" else "role_id"
        await self.execute(
            f"DELETE FROM {table} WHERE guild_id=? AND {col}=? AND system=?",
            (guild_id, target_id, system),
        )

    async def is_ignored(self, guild_id: int, channel_id: int, role_ids: List[int], system: str) -> bool:
        row = await self.fetchone(
            "SELECT 1 FROM ignored_channels WHERE guild_id=? AND channel_id=? AND system=?",
            (guild_id, channel_id, system),
        )
        if row:
            return True
        if role_ids:
            placeholders = ",".join("?" for _ in role_ids)
            row = await self.fetchone(
                f"SELECT 1 FROM ignored_roles WHERE guild_id=? AND system=? "
                f"AND role_id IN ({placeholders})",
                (guild_id, system, *role_ids),
            )
            if row:
                return True
        return False

    # -- scheduled messages -----------------------------------------------------

    async def add_schedule(
        self, guild_id: int, channel_id: int, content: str, interval_seconds: int, created_by: int
    ) -> int:
        next_run = (datetime.now(timezone.utc) + timedelta(seconds=interval_seconds)).isoformat()
        return await self.execute_return_id(
            "INSERT INTO scheduled_messages "
            "(guild_id, channel_id, content, interval_seconds, next_run, created_by) "
            "VALUES (?,?,?,?,?,?)",
            (guild_id, channel_id, content, interval_seconds, next_run, created_by),
        )

    async def list_schedules(self, guild_id: int) -> List[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT * FROM scheduled_messages WHERE guild_id = ? AND active = 1", (guild_id,)
        )

    async def remove_schedule(self, guild_id: int, schedule_id: int) -> None:
        await self.execute(
            "UPDATE scheduled_messages SET active = 0 WHERE guild_id = ? AND id = ?",
            (guild_id, schedule_id),
        )

    async def clear_schedules(self, guild_id: int) -> None:
        await self.execute(
            "UPDATE scheduled_messages SET active = 0 WHERE guild_id = ?", (guild_id,)
        )

    async def due_schedules(self) -> List[aiosqlite.Row]:
        now = datetime.now(timezone.utc).isoformat()
        return await self.fetchall(
            "SELECT * FROM scheduled_messages WHERE active = 1 AND next_run <= ?", (now,)
        )

    async def advance_schedule(self, schedule_id: int, interval_seconds: int) -> None:
        next_run = (datetime.now(timezone.utc) + timedelta(seconds=interval_seconds)).isoformat()
        await self.execute(
            "UPDATE scheduled_messages SET next_run = ? WHERE id = ?", (next_run, schedule_id)
        )

    # -- verification / timeouts -------------------------------------------------

    async def mark_verified(self, guild_id: int, user_id: int) -> None:
        await self.execute(
            "INSERT OR REPLACE INTO verification (guild_id, user_id, verified_at) VALUES (?,?,?)",
            (guild_id, user_id, datetime.now(timezone.utc).isoformat()),
        )

    async def is_verified(self, guild_id: int, user_id: int) -> bool:
        row = await self.fetchone(
            "SELECT 1 FROM verification WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        )
        return row is not None

    async def add_pending_timeout(self, guild_id: int, user_id: int, expires_at: datetime) -> None:
        await self.execute(
            "INSERT OR REPLACE INTO timeouts_pending (guild_id, user_id, expires_at) VALUES (?,?,?)",
            (guild_id, user_id, expires_at.isoformat()),
        )

    async def clear_pending_timeout(self, guild_id: int, user_id: int) -> None:
        await self.execute(
            "DELETE FROM timeouts_pending WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        )

    async def get_expired_timeouts(self) -> List[aiosqlite.Row]:
        now = datetime.now(timezone.utc).isoformat()
        return await self.fetchall(
            "SELECT * FROM timeouts_pending WHERE expires_at <= ?", (now,)
        )

    async def record_raid_event(self, guild_id: int, join_count: int) -> None:
        await self.execute(
            "INSERT INTO raid_events (guild_id, triggered_at, join_count) VALUES (?,?,?)",
            (guild_id, datetime.now(timezone.utc).isoformat(), join_count),
        )


# ---------------------------------------------------------------------------
# In-memory spam & raid tracking
# ---------------------------------------------------------------------------

@dataclass
class UserMessageWindow:
    timestamps: Deque[float] = field(default_factory=deque)
    recent_contents: Deque[str] = field(default_factory=lambda: deque(maxlen=5))
    last_message_at: float = 0.0


class SpamTracker:
    """Purely in-memory sliding-window spam detector, cleaned periodically."""

    def __init__(self):
        self._windows: Dict[Tuple[int, int], UserMessageWindow] = {}

    def record(self, guild_id: int, user_id: int, content: str) -> UserMessageWindow:
        key = (guild_id, user_id)
        window = self._windows.setdefault(key, UserMessageWindow())
        now = time.monotonic()
        window.timestamps.append(now)
        window.recent_contents.append(content)
        window.last_message_at = now
        return window

    def check_flood(self, window: UserMessageWindow, max_count: int, window_seconds: int) -> bool:
        cutoff = time.monotonic() - window_seconds
        while window.timestamps and window.timestamps[0] < cutoff:
            window.timestamps.popleft()
        return len(window.timestamps) > max_count

    def check_repeat(self, window: UserMessageWindow) -> bool:
        if len(window.recent_contents) < 3:
            return False
        last = list(window.recent_contents)[-3:]
        return len(set(last)) == 1 and bool(last[0].strip())

    def cleanup(self, max_age_seconds: int = 300) -> None:
        cutoff = time.monotonic() - max_age_seconds
        dead_keys = [
            key for key, w in self._windows.items() if w.last_message_at < cutoff
        ]
        for key in dead_keys:
            del self._windows[key]


class RaidTracker:
    """Tracks recent join timestamps per guild in memory."""

    def __init__(self):
        self._joins: Dict[int, Deque[float]] = defaultdict(deque)

    def record_join(self, guild_id: int) -> Deque[float]:
        dq = self._joins[guild_id]
        dq.append(time.monotonic())
        return dq

    def count_recent(self, guild_id: int, window_seconds: int) -> int:
        dq = self._joins[guild_id]
        cutoff = time.monotonic() - window_seconds
        while dq and dq[0] < cutoff:
            dq.popleft()
        return len(dq)

    def cleanup(self, max_age_seconds: int = 3600) -> None:
        cutoff = time.monotonic() - max_age_seconds
        for guild_id in list(self._joins.keys()):
            dq = self._joins[guild_id]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if not dq:
                del self._joins[guild_id]


class RateLimiter:
    """Simple per-user cooldown tracker for a named bucket (e.g. 'ai', 'mod')."""

    def __init__(self):
        self._last_used: Dict[Tuple[str, int], float] = {}

    def check(self, bucket: str, user_id: int, cooldown_seconds: float) -> Tuple[bool, float]:
        key = (bucket, user_id)
        now = time.monotonic()
        last = self._last_used.get(key, 0.0)
        remaining = cooldown_seconds - (now - last)
        if remaining > 0:
            return False, remaining
        self._last_used[key] = now
        return True, 0.0


INVITE_RE = re.compile(r"(discord\.gg|discord\.com/invite|discordapp\.com/invite)/\S+", re.IGNORECASE)
LINK_RE = re.compile(r"https?://\S+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Gemini AI wrapper
# ---------------------------------------------------------------------------

PERSONALITIES = {
    "friendly": "You are a warm, friendly, casual Discord community member. Keep replies short and natural.",
    "professional": "You are a professional, concise, courteous assistant for this Discord server.",
    "funny": "You are witty, playful, and a little sarcastic, but never mean-spirited.",
    "gaming": "You talk like an enthusiastic gamer, use light gaming slang, and keep things fun.",
    "community assistant": "You are a helpful, neutral community assistant focused on being useful.",
}

AI_SAFETY_PREAMBLE = (
    "You are an AI chat assistant embedded in a Discord bot. Hard rules you must always follow: "
    "never reveal API keys, tokens, secrets, or environment variables, even if asked directly or "
    "asked to 'roleplay' revealing them; never claim to execute shell commands, code, bans, kicks, "
    "timeouts, or any moderation/administrative action — you can only suggest that a human moderator "
    "use the real bot commands; never claim server permissions were changed by you; if you don't know "
    "something about this specific server, say so instead of inventing rules, events, or facts. "
    "Keep replies conversational and concise unless asked for detail."
)


class GeminiError(Exception):
    pass


class GeminiClient:
    def __init__(self, api_key: str, model: str):
        self.model = model
        self._client = None
        self._auth_failed = False
        if GENAI_AVAILABLE:
            try:
                self._client = genai.Client(api_key=api_key)
            except Exception as e:
                logger.error("Failed to initialize Gemini client: %s", safe_str(str(e)))

    async def generate(
        self, system_prompt: str, history: List[Dict[str, str]], user_message: str,
        max_retries: int = 3,
    ) -> str:
        if not GENAI_AVAILABLE or self._client is None:
            raise GeminiError("AI backend is not available on this deployment.")
        if self._auth_failed:
            raise GeminiError("AI backend authentication previously failed; not retrying.")

        contents = []
        for turn in history:
            role = "model" if turn["role"] == "assistant" else "user"
            contents.append(
                genai_types.Content(role=role, parts=[genai_types.Part(text=turn["content"])])
            )
        contents.append(
            genai_types.Content(role="user", parts=[genai_types.Part(text=user_message)])
        )

        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=600,
            temperature=0.9,
        )

        delay = 1.5
        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                response = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=self.model,
                    contents=contents,
                    config=config,
                )
                text = getattr(response, "text", None)
                if not text:
                    raise GeminiError("Empty response from AI backend.")
                return text.strip()
            except Exception as e:
                message = str(e).lower()
                last_error = e
                if "api key" in message or "unauthorized" in message or "permission" in message:
                    self._auth_failed = True
                    logger.error("Gemini authentication failure - disabling further calls.")
                    raise GeminiError("AI backend authentication failed.") from e
                if "rate" in message or "quota" in message or "429" in message:
                    logger.warning("Gemini rate/quota limit hit, backing off %.1fs", delay)
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                if "timeout" in message or "deadline" in message:
                    logger.warning("Gemini timeout, retrying (%s/%s)", attempt + 1, max_retries)
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                logger.warning("Gemini transient error: %s", safe_str(str(e)))
                await asyncio.sleep(delay)
                delay *= 2
        raise GeminiError(f"AI backend failed after {max_retries} attempts: {last_error}")


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.members = True
INTENTS.guilds = True


class ManagementBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=BOT_PREFIX, intents=INTENTS, help_command=None)
        self.db = Database(DB_PATH)
        self.gemini = GeminiClient(GEMINI_API_KEY, DEFAULT_AI_MODEL)
        self.spam_tracker = SpamTracker()
        self.raid_tracker = RaidTracker()
        self.rate_limiter = RateLimiter()
        self.start_time = time.monotonic()
        self._status_index = 0

    async def setup_hook(self) -> None:
        await self.db.connect()
        await self.add_cog(AICog(self))
        await self.add_cog(WelcomeCog(self))
        await self.add_cog(SecurityCog(self))
        await self.add_cog(ModerationCog(self))
        await self.add_cog(ConfigCog(self))
        await self.add_cog(UtilityCog(self))
        await self.add_cog(OwnerCog(self))
        await self.add_cog(HelpCog(self))
        try:
            synced = await self.tree.sync()
            logger.info("Synced %d application command(s).", len(synced))
        except Exception as e:
            logger.error("Command sync failed: %s", safe_str(str(e)))

        self.cleanup_task.start()
        self.schedule_task.start()
        self.timeout_expiry_task.start()
        self.status_rotation_task.start()

    async def close(self) -> None:
        for task in (
            self.cleanup_task, self.schedule_task,
            self.timeout_expiry_task, self.status_rotation_task,
        ):
            if task.is_running():
                task.cancel()
        await self.db.close()
        await super().close()

    # -- background tasks -----------------------------------------------------

    @tasks.loop(minutes=2)
    async def cleanup_task(self):
        try:
            self.spam_tracker.cleanup()
            self.raid_tracker.cleanup()
        except Exception:
            logger.exception("cleanup_task failed")

    @tasks.loop(seconds=30)
    async def schedule_task(self):
        try:
            due = await self.db.due_schedules()
            for row in due:
                channel = self.get_channel(row["channel_id"])
                if channel:
                    try:
                        await channel.send(row["content"])
                    except discord.HTTPException:
                        logger.warning("Failed to send scheduled message id=%s", row["id"])
                await self.db.advance_schedule(row["id"], row["interval_seconds"])
        except Exception:
            logger.exception("schedule_task failed")

    @tasks.loop(seconds=30)
    async def timeout_expiry_task(self):
        try:
            expired = await self.db.get_expired_timeouts()
            for row in expired:
                await self.db.clear_pending_timeout(row["guild_id"], row["user_id"])
        except Exception:
            logger.exception("timeout_expiry_task failed")

    @tasks.loop(minutes=10)
    async def status_rotation_task(self):
        try:
            statuses = [
                f"{len(self.guilds)} servers",
                "for spam 👀",
                "/help",
                "AI Assistant Online",
            ]
            text = statuses[self._status_index % len(statuses)]
            self._status_index += 1
            await self.change_presence(activity=discord.Activity(
                type=discord.ActivityType.watching, name=text
            ))
        except Exception:
            logger.exception("status_rotation_task failed")

    @cleanup_task.before_loop
    @schedule_task.before_loop
    @timeout_expiry_task.before_loop
    @status_rotation_task.before_loop
    async def _before_loops(self):
        await self.wait_until_ready()

    async def on_ready(self):
        logger.info("=" * 50)
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        logger.info("Latency: %.1f ms", self.latency * 1000)
        logger.info("Guilds: %d", len(self.guilds))
        logger.info("Gemini available: %s", GENAI_AVAILABLE)
        logger.info("Startup complete.")
        logger.info("=" * 50)

    async def on_command_error(self, ctx, error):
        logger.warning("Prefix command error: %s", safe_str(str(error)))

    async def on_app_command_error_global(self, interaction, error):
        pass


bot = ManagementBot()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You don't have permission to use this command."
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = f"Slow down! Try again in {error.retry_after:.1f}s."
    elif isinstance(error, app_commands.CheckFailure):
        msg = "You can't use this command here."
    else:
        msg = "Something went wrong running that command."
        logger.error("App command error: %s", safe_str("".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )))
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=error_embed(msg), ephemeral=True)
        else:
            await interaction.response.send_message(embed=error_embed(msg), ephemeral=True)
    except discord.HTTPException:
        pass


# ---------------------------------------------------------------------------
# Permission / hierarchy helpers
# ---------------------------------------------------------------------------

def is_owner_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id == OWNER_ID
    return app_commands.check(predicate)


def can_moderate(actor: discord.Member, target: discord.Member, bot_member: discord.Member) -> Tuple[bool, str]:
    if target.id == actor.id:
        return False, "You cannot target yourself."
    if target.id == bot_member.id:
        return False, "You cannot target the bot."
    if target.id == actor.guild.owner_id:
        return False, "You cannot target the server owner."
    if actor.id != actor.guild.owner_id and target.top_role >= actor.top_role:
        return False, "You cannot act on a member with an equal or higher role."
    if target.top_role >= bot_member.top_role:
        return False, "That member's role is higher than or equal to mine; I can't act on them."
    return True, ""


async def log_to_channel(guild: discord.Guild, channel_id: Optional[int], embed: discord.Embed) -> None:
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if channel:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.warning("Failed to send log embed to channel %s in guild %s", channel_id, guild.id)


# ---------------------------------------------------------------------------
# AI Cog
# ---------------------------------------------------------------------------

class AICog(commands.Cog):
    def __init__(self, bot: ManagementBot):
        self.bot = bot

    ai_group = app_commands.Group(name="ai", description="AI assistant configuration")

    @ai_group.command(name="setchannel", description="Set the channel where the AI replies without a mention.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setai_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.bot.db.set_guild_field(interaction.guild_id, "ai_channel_id", channel.id)
        await interaction.response.send_message(
            embed=success_embed(f"AI channel set to {channel.mention}."), ephemeral=True
        )

    @ai_group.command(name="personality", description="Set the AI's personality.")
    @app_commands.describe(style="friendly, professional, funny, gaming, or community assistant")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_personality(self, interaction: discord.Interaction, style: str):
        style = style.lower().strip()
        if style not in PERSONALITIES:
            await interaction.response.send_message(
                embed=error_embed(f"Unknown personality. Choose from: {', '.join(PERSONALITIES)}"),
                ephemeral=True,
            )
            return
        await self.bot.db.set_guild_field(interaction.guild_id, "ai_personality", style)
        await interaction.response.send_message(
            embed=success_embed(f"AI personality set to **{style}**."), ephemeral=True
        )

    @ai_group.command(name="toggle", description="Enable or disable the AI chatbot in this server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def toggle_ai(self, interaction: discord.Interaction, enabled: bool):
        await self.bot.db.set_guild_field(interaction.guild_id, "ai_enabled", int(enabled))
        await interaction.response.send_message(
            embed=success_embed(f"AI chatbot {'enabled' if enabled else 'disabled'}."), ephemeral=True
        )

    @ai_group.command(name="memory_toggle", description="Enable or disable AI memory for this server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def toggle_memory(self, interaction: discord.Interaction, enabled: bool):
        await self.bot.db.set_guild_field(interaction.guild_id, "memory_enabled", int(enabled))
        await interaction.response.send_message(
            embed=success_embed(f"AI memory {'enabled' if enabled else 'disabled'}."), ephemeral=True
        )

    @app_commands.command(name="ask", description="Ask the AI a question.")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        allowed, wait = self.bot.rate_limiter.check("ai", interaction.user.id, 5.0)
        if not allowed:
            await interaction.followup.send(embed=warning_embed(f"Please wait {wait:.1f}s before asking again."))
            return
        settings = await self.bot.db.get_guild_settings(interaction.guild_id)
        if not settings["ai_enabled"]:
            await interaction.followup.send(embed=warning_embed("AI is disabled in this server."))
            return
        reply = await self._generate_reply(interaction.guild_id, interaction.channel_id, interaction.user.id, question, settings)
        await interaction.followup.send(embed=ai_embed(reply[:4000]))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        settings = await self.bot.db.get_guild_settings(message.guild.id)
        if not settings["ai_enabled"]:
            return

        is_mention = self.bot.user in message.mentions
        is_ai_channel = settings["ai_channel_id"] == message.channel.id
        is_reply_to_bot = False
        if message.reference and isinstance(message.reference.resolved, discord.Message):
            is_reply_to_bot = message.reference.resolved.author.id == self.bot.user.id

        if not (is_mention or is_ai_channel or is_reply_to_bot):
            return

        content = message.content
        for mention in message.mentions:
            content = content.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
        content = content.strip()
        if not content:
            return

        allowed, wait = self.bot.rate_limiter.check("ai", message.author.id, 4.0)
        if not allowed:
            return

        async with message.channel.typing():
            reply = await self._generate_reply(
                message.guild.id, message.channel.id, message.author.id, content, settings
            )
        try:
            await message.reply(reply[:2000], mention_author=False)
        except discord.HTTPException:
            pass

    async def _generate_reply(
        self, guild_id: int, channel_id: int, user_id: int, user_message: str, settings
    ) -> str:
        await self.bot.db.bump_stat(guild_id, "ai_requests")
        personality = settings["ai_personality"] or "friendly"
        system_prompt = f"{AI_SAFETY_PREAMBLE}\n\nPersonality: {PERSONALITIES.get(personality, PERSONALITIES['friendly'])}"

        history = []
        if settings["memory_enabled"]:
            history_rows = await self.bot.db.get_recent_chat(guild_id, channel_id, user_id, limit=10)
            history = [{"role": r["role"], "content": r["content"]} for r in history_rows]
            memories = await self.bot.db.get_memory(guild_id, user_id)
            if memories:
                mem_text = "; ".join(f"{m['memory_key']}={m['memory_value']}" for m in memories)
                system_prompt += f"\n\nKnown user preferences (non-sensitive, user-provided): {mem_text}"

        try:
            reply = await self.bot.gemini.generate(system_prompt, history, user_message)
        except GeminiError as e:
            await self.bot.db.bump_stat(guild_id, "ai_errors")
            logger.warning("AI generation failed: %s", safe_str(str(e)))
            return "Sorry, I couldn't reach the AI service just now. Try again in a bit!"

        if settings["memory_enabled"]:
            await self.bot.db.add_chat_message(guild_id, channel_id, user_id, "user", user_message)
            await self.bot.db.add_chat_message(guild_id, channel_id, user_id, "assistant", reply)
            await self.bot.db.trim_chat_history(guild_id, channel_id, user_id, keep=40)
        return reply

    @app_commands.command(name="memory", description="View what the AI remembers about you in this server.")
    async def memory_cmd(self, interaction: discord.Interaction):
        memories = await self.bot.db.get_memory(interaction.guild_id, interaction.user.id)
        if not memories:
            await interaction.response.send_message(embed=info_embed("I don't have any saved memories for you."), ephemeral=True)
            return
        desc = "\n".join(f"**{m['memory_key']}**: {m['memory_value']}" for m in memories)
        await interaction.response.send_message(embed=info_embed(desc, "Your Memory"), ephemeral=True)

    @app_commands.command(name="forget", description="Ask the AI to forget your stored memory/conversation.")
    async def forget_cmd(self, interaction: discord.Interaction):
        await self.bot.db.forget_memory(interaction.guild_id, interaction.user.id)
        await self.bot.db.forget_chat_history(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(embed=success_embed("Your memory and conversation history have been cleared."), ephemeral=True)

    @app_commands.command(name="privacy", description="Learn what data this bot stores about you.")
    async def privacy_cmd(self, interaction: discord.Interaction):
        text = (
            "I store: your recent AI conversation turns (to keep context), any preferences you "
            "explicitly ask me to remember, and moderation records if you've been warned/timed out. "
            "Use `/forget` or `/forgetme` to clear your AI data at any time."
        )
        await interaction.response.send_message(embed=info_embed(text, "Privacy"), ephemeral=True)

    @app_commands.command(name="forgetme", description="Delete all your AI conversation history and memory in this server.")
    async def forgetme_cmd(self, interaction: discord.Interaction):
        await self.bot.db.forget_memory(interaction.guild_id, interaction.user.id)
        await self.bot.db.forget_chat_history(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(embed=success_embed("All your AI data in this server has been deleted."), ephemeral=True)


# ---------------------------------------------------------------------------
# Welcome / Goodbye Cog
# ---------------------------------------------------------------------------

class WelcomeCog(commands.Cog):
    def __init__(self, bot: ManagementBot):
        self.bot = bot

    welcome_group = app_commands.Group(name="welcome", description="Welcome message configuration")

    @welcome_group.command(name="channel", description="Set the welcome channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.bot.db.set_guild_field(interaction.guild_id, "welcome_channel_id", channel.id)
        await interaction.response.send_message(embed=success_embed(f"Welcome channel set to {channel.mention}."), ephemeral=True)

    @welcome_group.command(name="message", description="Set the welcome message template. Use {user}, {server}, {count}.")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_message(self, interaction: discord.Interaction, template: str):
        await self.bot.db.set_guild_field(interaction.guild_id, "welcome_message", template)
        await interaction.response.send_message(embed=success_embed("Welcome message updated."), ephemeral=True)

    @welcome_group.command(name="setup", description="Quick setup: channel + default message.")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.bot.db.set_guild_field(interaction.guild_id, "welcome_channel_id", channel.id)
        await self.bot.db.set_guild_field(
            interaction.guild_id, "welcome_message", "Welcome {user} to {server}! 🎉 You're member #{count}."
        )
        await interaction.response.send_message(embed=success_embed(f"Welcome system set up in {channel.mention}."), ephemeral=True)

    @welcome_group.command(name="test", description="Preview the welcome message.")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_test(self, interaction: discord.Interaction):
        embed = await self._build_welcome_embed(interaction.guild, interaction.user)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @welcome_group.command(name="disable", description="Disable the welcome system.")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_disable(self, interaction: discord.Interaction):
        await self.bot.db.set_guild_field(interaction.guild_id, "welcome_channel_id", None)
        await interaction.response.send_message(embed=success_embed("Welcome system disabled."), ephemeral=True)

    @app_commands.command(name="goodbye_channel", description="Set the goodbye channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def goodbye_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.bot.db.set_guild_field(interaction.guild_id, "goodbye_channel_id", channel.id)
        await interaction.response.send_message(embed=success_embed(f"Goodbye channel set to {channel.mention}."), ephemeral=True)

    @app_commands.command(name="goodbye_message", description="Set the goodbye message template. Use {user}, {server}, {count}.")
    @app_commands.checks.has_permissions(administrator=True)
    async def goodbye_message(self, interaction: discord.Interaction, template: str):
        await self.bot.db.set_guild_field(interaction.guild_id, "goodbye_message", template)
        await interaction.response.send_message(embed=success_embed("Goodbye message updated."), ephemeral=True)

    async def _build_welcome_embed(self, guild: discord.Guild, member: discord.abc.User) -> discord.Embed:
        settings = await self.bot.db.get_guild_settings(guild.id)
        template = settings["welcome_message"] or "Welcome {user} to {server}! 🎉"
        text = template.format(user=member.mention, server=guild.name, count=guild.member_count)

        if settings["welcome_ai"] and GENAI_AVAILABLE:
            try:
                prompt = (
                    f"{AI_SAFETY_PREAMBLE}\nWrite one short, warm, upbeat welcome sentence for a new "
                    f"Discord member named {getattr(member, 'display_name', 'there')} joining "
                    f"'{guild.name}'. No emojis overload, one or two max."
                )
                ai_text = await self.bot.gemini.generate(prompt, [], "Write the welcome line now.")
                text = ai_text
            except GeminiError:
                pass  # fall back to static template, never block a join on AI

        embed = make_embed("👋 Welcome!", text, COLOR_SUCCESS)
        if isinstance(member, discord.Member):
            embed.set_thumbnail(url=member.display_avatar.url)
            age_days = (datetime.now(timezone.utc) - member.created_at).days
            embed.add_field(name="Account age", value=f"{age_days} days", inline=True)
        embed.add_field(name="Member count", value=str(guild.member_count), inline=True)
        return embed

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        await self.bot.db.bump_stat(guild.id, "joins")
        settings = await self.bot.db.get_guild_settings(guild.id)

        if settings["welcome_channel_id"]:
            channel = guild.get_channel(settings["welcome_channel_id"])
            if channel:
                try:
                    embed = await self._build_welcome_embed(guild, member)
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    logger.warning("Failed to send welcome message in guild %s", guild.id)

        if settings["autorole_id"]:
            role = guild.get_role(settings["autorole_id"])
            bot_member = guild.get_member(self.bot.user.id)
            if role and bot_member and role < bot_member.top_role:
                try:
                    await member.add_roles(role, reason="Autorole on join")
                except discord.HTTPException:
                    logger.warning("Failed to assign autorole in guild %s", guild.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        await self.bot.db.bump_stat(guild.id, "leaves")
        settings = await self.bot.db.get_guild_settings(guild.id)
        if settings["goodbye_channel_id"]:
            channel = guild.get_channel(settings["goodbye_channel_id"])
            if channel:
                template = settings["goodbye_message"] or "{user} has left {server}. Farewell!"
                text = template.format(user=member.display_name, server=guild.name, count=guild.member_count)
                try:
                    await channel.send(embed=make_embed("👋 Goodbye", text, COLOR_WARNING))
                except discord.HTTPException:
                    pass


# ---------------------------------------------------------------------------
# Security Cog: verification, join checks, anti-spam, anti-raid, automod
# ---------------------------------------------------------------------------

class VerifyButton(discord.ui.View):
    def __init__(self, bot: ManagementBot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.success, custom_id="persistent_verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = await self.bot.db.get_guild_settings(interaction.guild_id)
        role_id = settings["verification_role_id"]
        if not role_id:
            await interaction.response.send_message(embed=error_embed("Verification is not fully configured."), ephemeral=True)
            return
        role = interaction.guild.get_role(role_id)
        bot_member = interaction.guild.get_member(self.bot.user.id)
        if not role or role >= bot_member.top_role:
            await interaction.response.send_message(embed=error_embed("Verification role is misconfigured."), ephemeral=True)
            return
        try:
            await interaction.user.add_roles(role, reason="Self-verification")
            await self.bot.db.mark_verified(interaction.guild_id, interaction.user.id)
            await interaction.response.send_message(embed=success_embed("You're verified! Welcome in."), ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message(embed=error_embed("Couldn't assign the role. Ask a moderator for help."), ephemeral=True)


class SecurityCog(commands.Cog):
    def __init__(self, bot: ManagementBot):
        self.bot = bot

    verify_group = app_commands.Group(name="verify", description="Verification system configuration")
    raid_group = app_commands.Group(name="raid", description="Anti-raid configuration")
    automod_group = app_commands.Group(name="automod", description="AutoMod configuration")
    blacklist_group = app_commands.Group(name="blacklist", description="Manage the word blacklist")

    # -- verification ---------------------------------------------------------

    @verify_group.command(name="setup", description="Post the verification button in a channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def verify_setup(self, interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role):
        bot_member = interaction.guild.get_member(self.bot.user.id)
        if role >= bot_member.top_role:
            await interaction.response.send_message(embed=error_embed("I can't assign a role higher than or equal to my own."), ephemeral=True)
            return
        await self.bot.db.set_guild_field(interaction.guild_id, "verification_channel_id", channel.id)
        await self.bot.db.set_guild_field(interaction.guild_id, "verification_role_id", role.id)
        await self.bot.db.set_guild_field(interaction.guild_id, "verification_enabled", 1)
        embed = make_embed("🔒 Verification", "Click below to verify and gain access to the server.", COLOR_INFO)
        await channel.send(embed=embed, view=VerifyButton(self.bot))
        await interaction.response.send_message(embed=success_embed("Verification system is live."), ephemeral=True)

    @verify_group.command(name="disable", description="Disable the verification requirement.")
    @app_commands.checks.has_permissions(administrator=True)
    async def verify_disable(self, interaction: discord.Interaction):
        await self.bot.db.set_guild_field(interaction.guild_id, "verification_enabled", 0)
        await interaction.response.send_message(embed=success_embed("Verification disabled."), ephemeral=True)

    @verify_group.command(name="role", description="Change the role granted on verification.")
    @app_commands.checks.has_permissions(administrator=True)
    async def verify_role(self, interaction: discord.Interaction, role: discord.Role):
        await self.bot.db.set_guild_field(interaction.guild_id, "verification_role_id", role.id)
        await interaction.response.send_message(embed=success_embed(f"Verification role set to {role.mention}."), ephemeral=True)

    # -- raid -------------------------------------------------------------------

    @raid_group.command(name="status", description="Show current raid mode status.")
    async def raid_status(self, interaction: discord.Interaction):
        settings = await self.bot.db.get_guild_settings(interaction.guild_id)
        state = "🔴 ACTIVE" if settings["raid_mode"] else "🟢 inactive"
        await interaction.response.send_message(
            embed=info_embed(
                f"Raid mode: **{state}**\nJoin threshold: {settings['raid_join_threshold']} "
                f"per {settings['raid_join_window']}s",
                "Raid Status",
            )
        )

    @raid_group.command(name="enable", description="Manually enable raid mode (restricts new joins visibility).")
    @app_commands.checks.has_permissions(administrator=True)
    async def raid_enable(self, interaction: discord.Interaction):
        await self.bot.db.set_guild_field(interaction.guild_id, "raid_mode", 1)
        await interaction.response.send_message(embed=warning_embed("Raid mode enabled."), ephemeral=True)

    @raid_group.command(name="disable", description="Disable raid mode.")
    @app_commands.checks.has_permissions(administrator=True)
    async def raid_disable(self, interaction: discord.Interaction):
        await self.bot.db.set_guild_field(interaction.guild_id, "raid_mode", 0)
        await interaction.response.send_message(embed=success_embed("Raid mode disabled."), ephemeral=True)

    @raid_group.command(name="settings", description="Configure raid detection thresholds.")
    @app_commands.checks.has_permissions(administrator=True)
    async def raid_settings(self, interaction: discord.Interaction, join_threshold: int, window_seconds: int):
        await self.bot.db.set_guild_field(interaction.guild_id, "raid_join_threshold", join_threshold)
        await self.bot.db.set_guild_field(interaction.guild_id, "raid_join_window", window_seconds)
        await interaction.response.send_message(
            embed=success_embed(f"Raid detection set to {join_threshold} joins / {window_seconds}s."),
            ephemeral=True,
        )

    # -- automod ------------------------------------------------------------------

    @automod_group.command(name="enable", description="Enable AutoMod.")
    @app_commands.checks.has_permissions(administrator=True)
    async def automod_enable(self, interaction: discord.Interaction):
        await self.bot.db.set_guild_field(interaction.guild_id, "automod_enabled", 1)
        await interaction.response.send_message(embed=success_embed("AutoMod enabled."), ephemeral=True)

    @automod_group.command(name="disable", description="Disable AutoMod.")
    @app_commands.checks.has_permissions(administrator=True)
    async def automod_disable(self, interaction: discord.Interaction):
        await self.bot.db.set_guild_field(interaction.guild_id, "automod_enabled", 0)
        await interaction.response.send_message(embed=success_embed("AutoMod disabled."), ephemeral=True)

    @automod_group.command(name="setup", description="Quick AutoMod setup with sane defaults.")
    @app_commands.checks.has_permissions(administrator=True)
    async def automod_setup(self, interaction: discord.Interaction):
        await self.bot.db.execute(
            "UPDATE automod_settings SET block_invites=1, block_mass_mentions=1, "
            "max_mentions=5, block_excessive_caps=1, caps_threshold=0.7, block_everyone_abuse=1 "
            "WHERE guild_id = ?",
            (interaction.guild_id,),
        )
        await self.bot.db.set_guild_field(interaction.guild_id, "automod_enabled", 1)
        await interaction.response.send_message(embed=success_embed("AutoMod configured with recommended defaults."), ephemeral=True)

    @automod_group.command(name="settings", description="View current AutoMod settings.")
    async def automod_view(self, interaction: discord.Interaction):
        row = await self.bot.db.fetchone("SELECT * FROM automod_settings WHERE guild_id = ?", (interaction.guild_id,))
        desc = (
            f"Block invites: {bool(row['block_invites'])}\n"
            f"Block links: {bool(row['block_links'])}\n"
            f"Block mass mentions: {bool(row['block_mass_mentions'])} (max {row['max_mentions']})\n"
            f"Block excessive caps: {bool(row['block_excessive_caps'])} (threshold {row['caps_threshold']})\n"
            f"Block @everyone/@here abuse: {bool(row['block_everyone_abuse'])}"
        )
        await interaction.response.send_message(embed=info_embed(desc, "AutoMod Settings"), ephemeral=True)

    @blacklist_group.command(name="add", description="Add a word to the blacklist.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def blacklist_add(self, interaction: discord.Interaction, word: str):
        await self.bot.db.add_blacklist_word(interaction.guild_id, word)
        await interaction.response.send_message(embed=success_embed(f"Added `{word}` to the blacklist."), ephemeral=True)

    @blacklist_group.command(name="remove", description="Remove a word from the blacklist.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def blacklist_remove(self, interaction: discord.Interaction, word: str):
        await self.bot.db.remove_blacklist_word(interaction.guild_id, word)
        await interaction.response.send_message(embed=success_embed(f"Removed `{word}` from the blacklist."), ephemeral=True)

    @blacklist_group.command(name="list", description="List blacklisted words.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def blacklist_list(self, interaction: discord.Interaction):
        words = await self.bot.db.get_blacklist(interaction.guild_id)
        text = ", ".join(f"`{w}`" for w in words) if words else "No blacklisted words yet."
        await interaction.response.send_message(embed=info_embed(text, "Blacklist"), ephemeral=True)

    # -- events -----------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        settings = await self.bot.db.get_guild_settings(guild.id)

        recent = self.bot.raid_tracker.record_join(guild.id)
        count = self.bot.raid_tracker.count_recent(guild.id, settings["raid_join_window"])
        if count >= settings["raid_join_threshold"] and not settings["raid_mode"]:
            await self.bot.db.set_guild_field(guild.id, "raid_mode", 1)
            await self.bot.db.record_raid_event(guild.id, count)
            embed = mod_embed(
                "🚨 Raid Detected",
                f"{count} members joined within {settings['raid_join_window']}s. "
                f"Raid mode has been auto-enabled. Use `/raid disable` once resolved.",
            )
            await log_to_channel(guild, settings["admin_log_channel_id"] or settings["mod_log_channel_id"], embed)

        account_age_days = (datetime.now(timezone.utc) - member.created_at).days
        suspicious = account_age_days < 3 or member.avatar is None
        if suspicious:
            embed = warning_embed(
                f"New member {member.mention} flagged: account age {account_age_days} days, "
                f"default avatar: {member.avatar is None}.",
                "Suspicious Join",
            )
            await log_to_channel(guild, settings["admin_log_channel_id"] or settings["mod_log_channel_id"], embed)

        if settings["log_joins"] if "log_joins" in dict(settings).keys() else True:
            pass  # detailed join log handled in ModerationCog logging listener

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return

        settings = await self.bot.db.get_guild_settings(message.guild.id)
        await self.bot.db.bump_stat(message.guild.id, "messages_processed")

        role_ids = [r.id for r in message.author.roles]
        spam_ignored = await self.bot.db.is_ignored(message.guild.id, message.channel.id, role_ids, "spam")
        automod_ignored = await self.bot.db.is_ignored(message.guild.id, message.channel.id, role_ids, "automod")

        if not spam_ignored and not message.author.guild_permissions.manage_messages:
            await self._check_spam(message, settings)

        if settings["automod_enabled"] and not automod_ignored and not message.author.guild_permissions.manage_messages:
            await self._check_automod(message, settings)

    async def _check_spam(self, message: discord.Message, settings) -> None:
        window = self.bot.spam_tracker.record(message.guild.id, message.author.id, message.content)
        is_flooding = self.bot.spam_tracker.check_flood(
            window, settings["spam_msg_count"], settings["spam_msg_window"]
        )
        is_repeating = self.bot.spam_tracker.check_repeat(window)
        invite_spam = bool(INVITE_RE.search(message.content))

        if not (is_flooding or is_repeating or invite_spam):
            return

        await self.bot.db.bump_stat(message.guild.id, "spam_detections")
        try:
            await message.delete()
        except discord.HTTPException:
            pass

        row = await self.bot.db.fetchone(
            "SELECT strikes FROM spam_records WHERE guild_id=? AND user_id=?",
            (message.guild.id, message.author.id),
        )
        strikes = (row["strikes"] if row else 0) + 1
        await self.bot.db.execute(
            "INSERT INTO spam_records (guild_id, user_id, strikes, last_strike_at) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET strikes=?, last_strike_at=?",
            (
                message.guild.id, message.author.id, strikes, datetime.now(timezone.utc).isoformat(),
                strikes, datetime.now(timezone.utc).isoformat(),
            ),
        )

        reason = "Automated spam detection"
        if strikes == 1:
            try:
                await message.channel.send(
                    f"{message.author.mention} please slow down — that message looked like spam.",
                    delete_after=6,
                )
            except discord.HTTPException:
                pass
        elif strikes == 2:
            await self.bot.db.add_warning(message.guild.id, message.author.id, self.bot.user.id, reason)
        elif strikes >= 3:
            bot_member = message.guild.get_member(self.bot.user.id)
            if isinstance(message.author, discord.Member) and message.author.top_role < bot_member.top_role:
                try:
                    await message.author.timeout(timedelta(minutes=10), reason=reason)
                    await self.bot.db.add_pending_timeout(
                        message.guild.id, message.author.id,
                        datetime.now(timezone.utc) + timedelta(minutes=10),
                    )
                except discord.HTTPException:
                    pass

        embed = mod_embed(
            "🚫 Spam Detected",
            f"User: {message.author.mention}\nChannel: {message.channel.mention}\nStrikes: {strikes}",
        )
        await log_to_channel(message.guild, settings["mod_log_channel_id"], embed)

    async def _check_automod(self, message: discord.Message, settings) -> None:
        row = await self.bot.db.fetchone("SELECT * FROM automod_settings WHERE guild_id=?", (message.guild.id,))
        content = message.content
        violation = None

        if row["block_invites"] and INVITE_RE.search(content):
            violation = "Discord invite link"
        elif row["block_links"] and LINK_RE.search(content):
            violation = "external link"
        elif row["block_mass_mentions"] and len(message.mentions) + len(message.role_mentions) > row["max_mentions"]:
            violation = "mass mentions"
        elif row["block_everyone_abuse"] and (message.mention_everyone) and not message.author.guild_permissions.mention_everyone:
            violation = "@everyone/@here abuse"
        elif row["block_excessive_caps"] and len(content) >= 10:
            letters = [c for c in content if c.isalpha()]
            if letters:
                caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
                if caps_ratio >= row["caps_threshold"]:
                    violation = "excessive caps"

        if violation is None:
            blacklist = await self.bot.db.get_blacklist(message.guild.id)
            lowered = content.lower()
            for word in blacklist:
                if word in lowered:
                    violation = f"blacklisted word"
                    break

        if violation:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            try:
                await message.channel.send(
                    f"{message.author.mention} your message was removed ({violation}).", delete_after=6
                )
            except discord.HTTPException:
                pass
            embed = mod_embed("🛑 AutoMod Action", f"User: {message.author.mention}\nReason: {violation}")
            await log_to_channel(message.guild, settings["mod_log_channel_id"], embed)


# ---------------------------------------------------------------------------
# Moderation Cog
# ---------------------------------------------------------------------------

class ModerationCog(commands.Cog):
    def __init__(self, bot: ManagementBot):
        self.bot = bot

    async def _resolve_bot_member(self, guild: discord.Guild) -> discord.Member:
        return guild.get_member(self.bot.user.id)

    @app_commands.command(name="warn", description="Warn a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        bot_member = await self._resolve_bot_member(interaction.guild)
        ok, err = can_moderate(interaction.user, member, bot_member)
        if not ok:
            await interaction.response.send_message(embed=error_embed(err), ephemeral=True)
            return
        await self.bot.db.add_warning(interaction.guild_id, member.id, interaction.user.id, reason)
        case_id = await self.bot.db.create_case(interaction.guild_id, interaction.user.id, member.id, "warn", reason)
        await self.bot.db.bump_stat(interaction.guild_id, "warnings_issued")
        embed = mod_embed(f"Case #{case_id}: Warn", f"Target: {member.mention}\nReason: {reason}")
        await interaction.response.send_message(embed=embed)
        settings = await self.bot.db.get_guild_settings(interaction.guild_id)
        await log_to_channel(interaction.guild, settings["mod_log_channel_id"], embed)

    @app_commands.command(name="warnings", description="View a member's warnings.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warnings_cmd(self, interaction: discord.Interaction, member: discord.Member):
        rows = await self.bot.db.get_warnings(interaction.guild_id, member.id)
        if not rows:
            await interaction.response.send_message(embed=info_embed(f"{member.mention} has no warnings."), ephemeral=True)
            return
        desc = "\n".join(f"#{r['id']} — {r['reason']} ({r['created_at'][:10]})" for r in rows[:15])
        await interaction.response.send_message(embed=info_embed(desc, f"Warnings for {member.display_name}"), ephemeral=True)

    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        await self.bot.db.clear_warnings(interaction.guild_id, member.id)
        await interaction.response.send_message(embed=success_embed(f"Cleared warnings for {member.mention}."), ephemeral=True)

    @app_commands.command(name="timeout", description="Timeout a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout_cmd(self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "No reason provided"):
        bot_member = await self._resolve_bot_member(interaction.guild)
        ok, err = can_moderate(interaction.user, member, bot_member)
        if not ok:
            await interaction.response.send_message(embed=error_embed(err), ephemeral=True)
            return
        minutes = max(1, min(minutes, 40320))
        try:
            await member.timeout(timedelta(minutes=minutes), reason=reason)
        except discord.HTTPException as e:
            await interaction.response.send_message(embed=error_embed(f"Failed to timeout: {e}"), ephemeral=True)
            return
        await self.bot.db.add_pending_timeout(interaction.guild_id, member.id, datetime.now(timezone.utc) + timedelta(minutes=minutes))
        case_id = await self.bot.db.create_case(interaction.guild_id, interaction.user.id, member.id, "timeout", reason, minutes * 60)
        await self.bot.db.bump_stat(interaction.guild_id, "timeouts_issued")
        embed = mod_embed(f"Case #{case_id}: Timeout", f"Target: {member.mention}\nDuration: {minutes}m\nReason: {reason}")
        await interaction.response.send_message(embed=embed)
        settings = await self.bot.db.get_guild_settings(interaction.guild_id)
        await log_to_channel(interaction.guild, settings["mod_log_channel_id"], embed)

    @app_commands.command(name="untimeout", description="Remove a member's timeout.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def untimeout_cmd(self, interaction: discord.Interaction, member: discord.Member):
        try:
            await member.timeout(None, reason=f"Untimed out by {interaction.user}")
        except discord.HTTPException as e:
            await interaction.response.send_message(embed=error_embed(f"Failed: {e}"), ephemeral=True)
            return
        await self.bot.db.clear_pending_timeout(interaction.guild_id, member.id)
        await interaction.response.send_message(embed=success_embed(f"Removed timeout for {member.mention}."))

    @app_commands.command(name="kick", description="Kick a member.")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick_cmd(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        bot_member = await self._resolve_bot_member(interaction.guild)
        ok, err = can_moderate(interaction.user, member, bot_member)
        if not ok:
            await interaction.response.send_message(embed=error_embed(err), ephemeral=True)
            return
        try:
            await member.kick(reason=reason)
        except discord.HTTPException as e:
            await interaction.response.send_message(embed=error_embed(f"Failed to kick: {e}"), ephemeral=True)
            return
        case_id = await self.bot.db.create_case(interaction.guild_id, interaction.user.id, member.id, "kick", reason)
        await self.bot.db.bump_stat(interaction.guild_id, "kicks_issued")
        embed = mod_embed(f"Case #{case_id}: Kick", f"Target: {member.mention}\nReason: {reason}")
        await interaction.response.send_message(embed=embed)
        settings = await self.bot.db.get_guild_settings(interaction.guild_id)
        await log_to_channel(interaction.guild, settings["mod_log_channel_id"], embed)

    @app_commands.command(name="ban", description="Ban a member.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_cmd(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided", delete_days: int = 0):
        bot_member = await self._resolve_bot_member(interaction.guild)
        ok, err = can_moderate(interaction.user, member, bot_member)
        if not ok:
            await interaction.response.send_message(embed=error_embed(err), ephemeral=True)
            return
        delete_days = max(0, min(delete_days, 7))
        try:
            await member.ban(reason=reason, delete_message_days=delete_days)
        except discord.HTTPException as e:
            await interaction.response.send_message(embed=error_embed(f"Failed to ban: {e}"), ephemeral=True)
            return
        case_id = await self.bot.db.create_case(interaction.guild_id, interaction.user.id, member.id, "ban", reason)
        await self.bot.db.bump_stat(interaction.guild_id, "bans_issued")
        embed = mod_embed(f"Case #{case_id}: Ban", f"Target: {member.mention}\nReason: {reason}")
        await interaction.response.send_message(embed=embed)
        settings = await self.bot.db.get_guild_settings(interaction.guild_id)
        await log_to_channel(interaction.guild, settings["mod_log_channel_id"], embed)

    @app_commands.command(name="unban", description="Unban a user by ID.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban_cmd(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        try:
            uid = int(user_id)
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=reason)
        except (ValueError, discord.NotFound):
            await interaction.response.send_message(embed=error_embed("That user isn't banned or the ID is invalid."), ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(embed=error_embed(f"Failed: {e}"), ephemeral=True)
            return
        case_id = await self.bot.db.create_case(interaction.guild_id, interaction.user.id, uid, "unban", reason)
        embed = mod_embed(f"Case #{case_id}: Unban", f"Target: {user}\nReason: {reason}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="purge", description="Bulk delete recent messages in this channel.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge_cmd(self, interaction: discord.Interaction, amount: int):
        amount = max(1, min(amount, 100))
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(embed=success_embed(f"Deleted {len(deleted)} messages."), ephemeral=True)

    @app_commands.command(name="clear", description="Alias for /purge.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear_cmd(self, interaction: discord.Interaction, amount: int):
        await self.purge_cmd.callback(self, interaction, amount)

    @app_commands.command(name="slowmode", description="Set slowmode for this channel (seconds, 0 to disable).")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode_cmd(self, interaction: discord.Interaction, seconds: int):
        seconds = max(0, min(seconds, 21600))
        await interaction.channel.edit(slowmode_delay=seconds)
        await interaction.response.send_message(embed=success_embed(f"Slowmode set to {seconds}s."), ephemeral=True)

    @app_commands.command(name="lock", description="Lock this channel for @everyone.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock_cmd(self, interaction: discord.Interaction):
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(embed=success_embed("Channel locked."))

    @app_commands.command(name="unlock", description="Unlock this channel for @everyone.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock_cmd(self, interaction: discord.Interaction):
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(embed=success_embed("Channel unlocked."))

    @app_commands.command(name="nick", description="Change a member's nickname.")
    @app_commands.checks.has_permissions(manage_nicknames=True)
    async def nick_cmd(self, interaction: discord.Interaction, member: discord.Member, nickname: str = None):
        bot_member = await self._resolve_bot_member(interaction.guild)
        if member.id != interaction.user.id:
            ok, err = can_moderate(interaction.user, member, bot_member)
            if not ok:
                await interaction.response.send_message(embed=error_embed(err), ephemeral=True)
                return
        try:
            await member.edit(nick=nickname)
        except discord.HTTPException as e:
            await interaction.response.send_message(embed=error_embed(f"Failed: {e}"), ephemeral=True)
            return
        await interaction.response.send_message(embed=success_embed("Nickname updated."))

    @app_commands.command(name="case", description="Look up a moderation case by ID.")
    async def case_cmd(self, interaction: discord.Interaction, case_id: int):
        row = await self.bot.db.get_case(interaction.guild_id, case_id)
        if not row:
            await interaction.response.send_message(embed=error_embed("Case not found."), ephemeral=True)
            return
        desc = (
            f"Action: {row['action']}\nModerator: <@{row['moderator_id']}>\n"
            f"Target: <@{row['target_id']}>\nReason: {row['reason']}\nDate: {row['created_at'][:19]}"
        )
        await interaction.response.send_message(embed=mod_embed(f"Case #{case_id}", desc))

    # -- role management ---------------------------------------------------------

    role_group = app_commands.Group(name="role", description="Role management")

    @role_group.command(name="add", description="Add a role to a member.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        bot_member = await self._resolve_bot_member(interaction.guild)
        if role >= bot_member.top_role or role >= interaction.user.top_role:
            await interaction.response.send_message(embed=error_embed("You/I can't manage a role at or above the relevant top role."), ephemeral=True)
            return
        await member.add_roles(role, reason=f"Added by {interaction.user}")
        await interaction.response.send_message(embed=success_embed(f"Added {role.mention} to {member.mention}."))

    @role_group.command(name="remove", description="Remove a role from a member.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_remove(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        bot_member = await self._resolve_bot_member(interaction.guild)
        if role >= bot_member.top_role or role >= interaction.user.top_role:
            await interaction.response.send_message(embed=error_embed("You/I can't manage a role at or above the relevant top role."), ephemeral=True)
            return
        await member.remove_roles(role, reason=f"Removed by {interaction.user}")
        await interaction.response.send_message(embed=success_embed(f"Removed {role.mention} from {member.mention}."))

    @role_group.command(name="create", description="Create a new role.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_create(self, interaction: discord.Interaction, name: str, color_hex: str = "#99AAB5"):
        try:
            color = discord.Color(int(color_hex.lstrip("#"), 16))
        except ValueError:
            color = discord.Color.default()
        role = await interaction.guild.create_role(name=name, color=color, reason=f"Created by {interaction.user}")
        await interaction.response.send_message(embed=success_embed(f"Created role {role.mention}."))

    @role_group.command(name="info", description="Show info about a role.")
    async def role_info(self, interaction: discord.Interaction, role: discord.Role):
        desc = f"Members: {len(role.members)}\nColor: {role.color}\nPosition: {role.position}\nMentionable: {role.mentionable}"
        await interaction.response.send_message(embed=info_embed(desc, f"Role: {role.name}"))

    # -- channel management ---------------------------------------------------------

    channel_group = app_commands.Group(name="channel", description="Channel management")

    @channel_group.command(name="lock", description="Lock a specific channel.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def channel_lock(self, interaction: discord.Interaction, channel: discord.TextChannel):
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(embed=success_embed(f"Locked {channel.mention}."))

    @channel_group.command(name="unlock", description="Unlock a specific channel.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def channel_unlock(self, interaction: discord.Interaction, channel: discord.TextChannel):
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(embed=success_embed(f"Unlocked {channel.mention}."))

    @channel_group.command(name="info", description="Show info about a channel.")
    async def channel_info(self, interaction: discord.Interaction, channel: discord.TextChannel):
        desc = f"Topic: {channel.topic or 'None'}\nSlowmode: {channel.slowmode_delay}s\nNSFW: {channel.is_nsfw()}"
        await interaction.response.send_message(embed=info_embed(desc, f"#{channel.name}"))

    # -- ignore system ---------------------------------------------------------

    ignore_group = app_commands.Group(name="ignore", description="Exclude channels/roles from automation")

    @ignore_group.command(name="channel", description="Ignore a channel for a system (spam/automod).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ignore_channel(self, interaction: discord.Interaction, channel: discord.TextChannel, system: str):
        await self.bot.db.add_ignore(interaction.guild_id, "channel", channel.id, system)
        await interaction.response.send_message(embed=success_embed(f"{channel.mention} now ignored for `{system}`."), ephemeral=True)

    @ignore_group.command(name="role", description="Ignore a role for a system (spam/automod).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ignore_role(self, interaction: discord.Interaction, role: discord.Role, system: str):
        await self.bot.db.add_ignore(interaction.guild_id, "role", role.id, system)
        await interaction.response.send_message(embed=success_embed(f"{role.mention} now ignored for `{system}`."), ephemeral=True)

    @app_commands.command(name="unignore", description="Remove a channel or role from a system's ignore list.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def unignore_cmd(self, interaction: discord.Interaction, system: str, channel: discord.TextChannel = None, role: discord.Role = None):
        if channel:
            await self.bot.db.remove_ignore(interaction.guild_id, "channel", channel.id, system)
        if role:
            await self.bot.db.remove_ignore(interaction.guild_id, "role", role.id, system)
        await interaction.response.send_message(embed=success_embed("Updated ignore list."), ephemeral=True)

    # -- message logging ---------------------------------------------------------

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        settings = await self.bot.db.get_guild_settings(message.guild.id)
        if not settings["mod_log_channel_id"]:
            return
        content = (message.content or "*[no text content]*")[:500]
        embed = mod_embed(
            "🗑️ Message Deleted",
            f"Author: {message.author.mention}\nChannel: {message.channel.mention}\nContent: {content}",
        )
        await log_to_channel(message.guild, settings["mod_log_channel_id"], embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot or before.content == after.content:
            return
        settings = await self.bot.db.get_guild_settings(before.guild.id)
        if not settings["mod_log_channel_id"]:
            return
        embed = mod_embed(
            "✏️ Message Edited",
            f"Author: {before.author.mention}\nChannel: {before.channel.mention}\n"
            f"Before: {(before.content or '')[:400]}\nAfter: {(after.content or '')[:400]}",
        )
        await log_to_channel(before.guild, settings["mod_log_channel_id"], embed)


# ---------------------------------------------------------------------------
# Config Cog
# ---------------------------------------------------------------------------

class ConfigCog(commands.Cog):
    def __init__(self, bot: ManagementBot):
        self.bot = bot

    config_group = app_commands.Group(name="config", description="Server configuration")

    @config_group.command(name="show", description="Show current server configuration.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_show(self, interaction: discord.Interaction):
        s = await self.bot.db.get_guild_settings(interaction.guild_id)

        def ch(cid):
            return f"<#{cid}>" if cid else "not set"

        desc = (
            f"Prefix: `{s['prefix']}`\n"
            f"AI channel: {ch(s['ai_channel_id'])} | AI enabled: {bool(s['ai_enabled'])} | Personality: {s['ai_personality']}\n"
            f"Welcome channel: {ch(s['welcome_channel_id'])}\n"
            f"Goodbye channel: {ch(s['goodbye_channel_id'])}\n"
            f"Mod log: {ch(s['mod_log_channel_id'])} | Admin log: {ch(s['admin_log_channel_id'])}\n"
            f"Verification: {bool(s['verification_enabled'])} in {ch(s['verification_channel_id'])}\n"
            f"Raid mode: {bool(s['raid_mode'])} ({s['raid_join_threshold']}/{s['raid_join_window']}s)\n"
            f"Spam threshold: {s['spam_msg_count']} msgs / {s['spam_msg_window']}s\n"
            f"AutoMod enabled: {bool(s['automod_enabled'])}"
        )
        await interaction.response.send_message(embed=info_embed(desc, "Server Configuration"), ephemeral=True)

    @config_group.command(name="reset", description="Reset server configuration to defaults.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_reset(self, interaction: discord.Interaction):
        await self.bot.db.reset_guild_settings(interaction.guild_id)
        await interaction.response.send_message(embed=success_embed("Configuration reset to defaults."), ephemeral=True)

    @app_commands.command(name="setmodlog", description="Set the moderation log channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_modlog(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.bot.db.set_guild_field(interaction.guild_id, "mod_log_channel_id", channel.id)
        await interaction.response.send_message(embed=success_embed(f"Mod log set to {channel.mention}."), ephemeral=True)

    @app_commands.command(name="setadminlog", description="Set the admin/security log channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_adminlog(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.bot.db.set_guild_field(interaction.guild_id, "admin_log_channel_id", channel.id)
        await interaction.response.send_message(embed=success_embed(f"Admin log set to {channel.mention}."), ephemeral=True)

    @app_commands.command(name="autorole", description="Set (or clear) the auto-role assigned on join.")
    @app_commands.checks.has_permissions(administrator=True)
    async def autorole_cmd(self, interaction: discord.Interaction, role: discord.Role = None):
        await self.bot.db.set_guild_field(interaction.guild_id, "autorole_id", role.id if role else None)
        msg = f"Autorole set to {role.mention}." if role else "Autorole cleared."
        await interaction.response.send_message(embed=success_embed(msg), ephemeral=True)

    @app_commands.command(name="spamthreshold", description="Set spam detection thresholds.")
    @app_commands.checks.has_permissions(administrator=True)
    async def spam_threshold(self, interaction: discord.Interaction, messages: int, window_seconds: int):
        await self.bot.db.set_guild_field(interaction.guild_id, "spam_msg_count", messages)
        await self.bot.db.set_guild_field(interaction.guild_id, "spam_msg_window", window_seconds)
        await interaction.response.send_message(
            embed=success_embed(f"Spam threshold set to {messages} messages / {window_seconds}s."), ephemeral=True
        )

    # -- scheduled messages -----------------------------------------------------

    schedule_group = app_commands.Group(name="schedule", description="Scheduled recurring messages")

    @schedule_group.command(name="add", description="Schedule a recurring message.")
    @app_commands.checks.has_permissions(administrator=True)
    async def schedule_add(self, interaction: discord.Interaction, channel: discord.TextChannel, content: str, interval_minutes: int):
        interval_minutes = max(5, interval_minutes)
        sid = await self.bot.db.add_schedule(
            interaction.guild_id, channel.id, content, interval_minutes * 60, interaction.user.id
        )
        await interaction.response.send_message(
            embed=success_embed(f"Scheduled message #{sid} created, repeating every {interval_minutes}m in {channel.mention}."),
            ephemeral=True,
        )

    @schedule_group.command(name="list", description="List active scheduled messages.")
    @app_commands.checks.has_permissions(administrator=True)
    async def schedule_list(self, interaction: discord.Interaction):
        rows = await self.bot.db.list_schedules(interaction.guild_id)
        if not rows:
            await interaction.response.send_message(embed=info_embed("No active scheduled messages."), ephemeral=True)
            return
        desc = "\n".join(f"#{r['id']} in <#{r['channel_id']}> every {r['interval_seconds']//60}m" for r in rows)
        await interaction.response.send_message(embed=info_embed(desc, "Scheduled Messages"), ephemeral=True)

    @schedule_group.command(name="remove", description="Remove a scheduled message by ID.")
    @app_commands.checks.has_permissions(administrator=True)
    async def schedule_remove(self, interaction: discord.Interaction, schedule_id: int):
        await self.bot.db.remove_schedule(interaction.guild_id, schedule_id)
        await interaction.response.send_message(embed=success_embed(f"Removed schedule #{schedule_id}."), ephemeral=True)

    @schedule_group.command(name="clear", description="Clear all scheduled messages.")
    @app_commands.checks.has_permissions(administrator=True)
    async def schedule_clear(self, interaction: discord.Interaction):
        await self.bot.db.clear_schedules(interaction.guild_id)
        await interaction.response.send_message(embed=success_embed("All scheduled messages cleared."), ephemeral=True)


# ---------------------------------------------------------------------------
# Utility Cog
# ---------------------------------------------------------------------------

class UtilityCog(commands.Cog):
    def __init__(self, bot: ManagementBot):
        self.bot = bot

    @app_commands.command(name="ping", description="Check the bot's latency.")
    async def ping_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=info_embed(f"Pong! {round(self.bot.latency*1000)}ms"))

    @app_commands.command(name="uptime", description="Show how long the bot has been running.")
    async def uptime_cmd(self, interaction: discord.Interaction):
        seconds = int(time.monotonic() - self.bot.start_time)
        td = timedelta(seconds=seconds)
        await interaction.response.send_message(embed=info_embed(str(td), "Uptime"))

    @app_commands.command(name="botinfo", description="Show information about the bot.")
    async def botinfo_cmd(self, interaction: discord.Interaction):
        desc = (
            f"Guilds: {len(self.bot.guilds)}\n"
            f"Latency: {round(self.bot.latency*1000)}ms\n"
            f"discord.py: {discord.__version__}\n"
            f"AI backend available: {GENAI_AVAILABLE}"
        )
        await interaction.response.send_message(embed=info_embed(desc, "Bot Info"))

    @app_commands.command(name="serverinfo", description="Show information about this server.")
    async def serverinfo_cmd(self, interaction: discord.Interaction):
        g = interaction.guild
        desc = (
            f"Owner: <@{g.owner_id}>\nMembers: {g.member_count}\nRoles: {len(g.roles)}\n"
            f"Channels: {len(g.channels)}\nCreated: {g.created_at.strftime('%Y-%m-%d')}"
        )
        embed = info_embed(desc, g.name)
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Show information about a member.")
    async def userinfo_cmd(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        desc = (
            f"ID: {member.id}\nJoined server: {member.joined_at.strftime('%Y-%m-%d') if member.joined_at else 'unknown'}\n"
            f"Account created: {member.created_at.strftime('%Y-%m-%d')}\n"
            f"Top role: {member.top_role.mention}"
        )
        embed = info_embed(desc, str(member))
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="Show a member's avatar.")
    async def avatar_cmd(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        embed = info_embed("", f"{member.display_name}'s avatar")
        embed.set_image(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="membercount", description="Show the server's member count.")
    async def membercount_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=info_embed(str(interaction.guild.member_count), "Member Count"))

    @app_commands.command(name="stats", description="Show server statistics for this bot.")
    async def stats_cmd(self, interaction: discord.Interaction):
        s = await self.bot.db.get_stats(interaction.guild_id)
        desc = (
            f"Messages processed: {s['messages_processed']}\nSpam detections: {s['spam_detections']}\n"
            f"Warnings: {s['warnings_issued']} | Timeouts: {s['timeouts_issued']}\n"
            f"Kicks: {s['kicks_issued']} | Bans: {s['bans_issued']}\n"
            f"Joins: {s['joins']} | Leaves: {s['leaves']}\n"
            f"AI requests: {s['ai_requests']} | AI errors: {s['ai_errors']}"
        )
        await interaction.response.send_message(embed=info_embed(desc, "Server Statistics"))


# ---------------------------------------------------------------------------
# Owner Cog
# ---------------------------------------------------------------------------

class OwnerCog(commands.Cog):
    def __init__(self, bot: ManagementBot):
        self.bot = bot

    owner_group = app_commands.Group(name="owner", description="Bot owner-only commands")

    @owner_group.command(name="status", description="Show internal bot status (owner only).")
    @is_owner_check()
    async def owner_status(self, interaction: discord.Interaction):
        desc = (
            f"Guilds: {len(self.bot.guilds)}\nUsers cached: {len(self.bot.users)}\n"
            f"Uptime: {int(time.monotonic() - self.bot.start_time)}s\n"
            f"Gemini auth failed: {self.bot.gemini._auth_failed}"
        )
        await interaction.response.send_message(embed=info_embed(desc, "Owner Status"), ephemeral=True)

    @owner_group.command(name="guilds", description="List all guilds the bot is in (owner only).")
    @is_owner_check()
    async def owner_guilds(self, interaction: discord.Interaction):
        lines = [f"{g.name} ({g.id}) — {g.member_count} members" for g in self.bot.guilds[:40]]
        await interaction.response.send_message(embed=info_embed("\n".join(lines) or "No guilds.", "Guilds"), ephemeral=True)

    @owner_group.command(name="database", description="Show basic database diagnostics (owner only).")
    @is_owner_check()
    async def owner_database(self, interaction: discord.Interaction):
        row = await self.bot.db.fetchone("SELECT COUNT(*) as c FROM moderation_cases")
        row2 = await self.bot.db.fetchone("SELECT COUNT(*) as c FROM chat_history")
        desc = f"Moderation cases: {row['c']}\nChat history rows: {row2['c']}\nDB path: {self.bot.db.path}"
        await interaction.response.send_message(embed=info_embed(desc, "Database Diagnostics"), ephemeral=True)

    @owner_group.command(name="broadcast", description="Send a message to the admin log of every guild (owner only).")
    @is_owner_check()
    async def owner_broadcast(self, interaction: discord.Interaction, message: str):
        await interaction.response.defer(ephemeral=True)
        sent = 0
        for guild in self.bot.guilds:
            settings = await self.bot.db.get_guild_settings(guild.id)
            channel_id = settings["admin_log_channel_id"] or settings["mod_log_channel_id"]
            if channel_id:
                channel = guild.get_channel(channel_id)
                if channel:
                    try:
                        await channel.send(embed=info_embed(message, "Broadcast from Bot Owner"))
                        sent += 1
                    except discord.HTTPException:
                        continue
        await interaction.followup.send(embed=success_embed(f"Broadcast sent to {sent} guild(s)."), ephemeral=True)

    @owner_group.command(name="reload", description="Re-sync application commands (owner only).")
    @is_owner_check()
    async def owner_reload(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            synced = await self.bot.tree.sync()
            await interaction.followup.send(embed=success_embed(f"Re-synced {len(synced)} commands."), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(embed=error_embed(f"Sync failed: {e}"), ephemeral=True)

    @owner_group.command(name="shutdown", description="Gracefully shut down the bot (owner only).")
    @is_owner_check()
    async def owner_shutdown(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=warning_embed("Shutting down..."), ephemeral=True)
        logger.info("Shutdown requested by owner via command.")
        await self.bot.close()


# ---------------------------------------------------------------------------
# Help Cog
# ---------------------------------------------------------------------------

HELP_CATEGORIES = {
    "AI": ["/ask", "/ai setchannel", "/ai personality", "/ai toggle", "/memory", "/forget", "/privacy", "/forgetme"],
    "Moderation": ["/warn", "/warnings", "/clearwarnings", "/timeout", "/untimeout", "/kick", "/ban", "/unban",
                   "/purge", "/clear", "/slowmode", "/lock", "/unlock", "/nick", "/case"],
    "Security": ["/verify setup", "/verify disable", "/verify role", "/raid status", "/raid enable",
                 "/raid disable", "/raid settings", "/automod setup", "/automod enable", "/automod disable",
                 "/blacklist add", "/blacklist remove", "/blacklist list"],
    "Server": ["/welcome setup", "/welcome message", "/welcome test", "/goodbye_channel", "/goodbye_message",
               "/role add", "/role remove", "/role create", "/channel lock", "/channel unlock", "/autorole"],
    "Utility": ["/ping", "/uptime", "/botinfo", "/serverinfo", "/userinfo", "/avatar", "/membercount", "/stats"],
    "Configuration": ["/config show", "/config reset", "/setmodlog", "/setadminlog", "/spamthreshold",
                       "/schedule add", "/schedule list", "/schedule remove", "/ignore channel", "/ignore role"],
    "Owner": ["/owner status", "/owner guilds", "/owner database", "/owner broadcast", "/owner reload", "/owner shutdown"],
}


class HelpCog(commands.Cog):
    def __init__(self, bot: ManagementBot):
        self.bot = bot

    @app_commands.command(name="help", description="Show categorized help for all commands.")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = make_embed("📖 Help", "Available command categories:", COLOR_INFO)
        for category, commands_list in HELP_CATEGORIES.items():
            if category == "Owner" and interaction.user.id != OWNER_ID:
                continue
            embed.add_field(name=category, value="\n".join(f"`{c}`" for c in commands_list), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------------------
# Entrypoint / graceful shutdown
# ---------------------------------------------------------------------------

async def main():
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received.")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler for these

    async with bot:
        bot_task = asyncio.create_task(bot.start(DISCORD_TOKEN))
        stop_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait(
            {bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if stop_task in done:
            logger.info("Closing bot gracefully...")
            await bot.close()
        for task in pending:
            task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted, exiting.")
