# ChotuAi

# Discord Server Management + AI Chatbot

A single-file (`main.py`) production Discord bot: moderation, automod,
anti-spam, anti-raid, verification, welcome/goodbye, scheduled messages,
statistics, owner tools, and a Gemini-powered AI chatbot with per-user
memory — all backed by SQLite (via `aiosqlite`).

## Setup

1. **Python 3.11+** required.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in:
   - `DISCORD_TOKEN` — from the Discord Developer Portal (Bot tab).
   - `GEMINI_API_KEY` — from Google AI Studio.
   - `OWNER_ID` — your numeric Discord user ID (enable Developer Mode in
     Discord, right-click your name, "Copy User ID").
4. In the Discord Developer Portal, under **Bot**, enable these
   **Privileged Gateway Intents**:
   - Server Members Intent
   - Message Content Intent
5. Invite the bot with the `applications.commands` and `bot` scopes and
   at least: Manage Roles, Manage Channels, Kick Members, Ban Members,
   Moderate Members (timeout), Manage Messages, Manage Nicknames,
   View Channels, Send Messages, Embed Links.
6. Run it:
   ```
   python main.py
   ```

On first run the bot creates `bot_data.db` (SQLite) automatically and
syncs its slash commands. Run `/help` in any server it's in to see all
categorized commands (owner-only commands are hidden from everyone else).

## Notable design choices

- **No secrets ever reach chat, logs, or the AI prompt.** The AI system
  prompt explicitly forbids revealing keys/tokens or claiming to perform
  moderation actions — the model can only *talk*, never execute anything.
- **All moderation actions** (`/warn`, `/timeout`, `/kick`, `/ban`, ...)
  check Discord role hierarchy, prevent self-targeting, prevent targeting
  the server owner or the bot itself, and record a case in SQLite.
- **Spam and raid detection** run in-memory (sliding windows) for speed,
  with periodic cleanup; only durable state (warnings, cases, config)
  goes to SQLite.
- **Multi-guild safe**: every query is scoped by `guild_id`; nothing
  leaks between servers.
- **Graceful shutdown** on `SIGINT`/`SIGTERM` closes the DB and
  background tasks cleanly.

## Files

- `main.py` — the entire bot.
- `requirements.txt` — pinned minimum dependency versions.
- `.env.example` — template for your `.env`.
