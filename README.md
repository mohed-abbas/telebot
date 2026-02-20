# Telebot — Telegram to Discord Message Relay

A lightweight Python bot that listens to Telegram group chats and forwards text messages to a Discord channel via webhook. Designed to run 24/7 as a Docker container.

## How It Works

```
Telegram Group(s)                    Discord Channel
  (new message)                      (webhook POST)
       |                                  ^
       |  MTProto (real-time push)        |  HTTPS POST
       v                                  |
  +-----------------------------------------+
  |            telebot (Python)             |
  |                                         |
  |  Telethon -----> Format -----> httpx    |
  |  (listener)      message       (sender) |
  +-----------------------------------------+
```

Messages are formatted as:

```
[Group Name] [Sender Name . 14:32]: message text here
```

- Listens to one or more Telegram groups (even with view-only access)
- Forwards text content and media captions (not media files)
- Auto-resolves Telegram group names
- Sends to a single Discord channel via webhook
- Auto-reconnects on network drops
- Retries failed sends with exponential backoff

## Tech Stack

| Component       | Technology                                               | Purpose                                             |
| --------------- | -------------------------------------------------------- | --------------------------------------------------- |
| Telegram client | [Telethon](https://docs.telethon.dev/) v1.42             | MTProto userbot — listens to groups in real-time    |
| Discord output  | Discord Webhooks                                         | Simple HTTP POST, no bot or API registration needed |
| HTTP client     | [httpx](https://www.python-httpx.org/) v0.28             | Async HTTP for Discord webhook calls                |
| Config          | [python-dotenv](https://pypi.org/project/python-dotenv/) | Loads `.env` file                                   |
| Runtime         | Python 3.12                                              |                                                     |
| Deployment      | Docker + docker compose                                  | Auto-restart, log rotation                          |

## Project Structure

```
telebot/
├── bot.py                # Main entrypoint — Telethon event handler, message formatting
├── config.py             # Loads .env, validates settings, exposes Settings dataclass
├── discord_sender.py     # Discord webhook client with retry logic
├── generate_session.py   # One-time script to create Telethon StringSession
├── list_groups.py        # Utility to list all Telegram groups with their IDs
├── requirements.txt      # Pinned Python dependencies
├── Dockerfile            # Python 3.12 slim image
├── docker-compose.yml    # Single service with auto-restart and log rotation
├── .env.example          # Template for all required environment variables
└── .dockerignore         # Excludes secrets and dev files from Docker image
```

## Prerequisites

- A Telegram account that is a member of the target group(s)
- A Discord server where you can create webhooks
- Docker and docker compose installed on your deployment machine
- Python 3.12+ on your local machine (for one-time session generation only)

## Setup

### 1. Get Telegram API Credentials

1. Go to [https://my.telegram.org](https://my.telegram.org)
2. Log in with your phone number
3. Click **"API development tools"**
4. Create an application — note your `api_id` and `api_hash`

### 2. Generate Telegram Session String

Run this on your **local machine** (not the server). It requires interactive input.

```bash
pip install telethon
python generate_session.py
```

It will prompt for:

- Your `api_id` and `api_hash`
- Your phone number (with country code, e.g. `+33...`)
- A 5-digit login code (sent to your Telegram app or via SMS)
- Your 2FA password (if enabled)

Copy the output session string — it goes into your `.env` as `TG_SESSION`.

### 3. Find Telegram Group Chat IDs

After generating your session, fill in `TG_API_ID`, `TG_API_HASH`, and `TG_SESSION` in your `.env`, then run:

```bash
pip install python-dotenv
python list_groups.py
```

This prints all groups your account is in with their chat IDs:

```
GROUP NAME                               CHAT ID              TYPE
---------------------------------------------------------------------------
My Group                                 -1001234567890       Channel
Another Group                            -5059521329          Chat
```

Use the `CHAT ID` values in your `.env`.

### 4. Create Discord Webhook

1. Open Discord — go to your server
2. Right-click the target channel > **Edit Channel**
3. Go to **Integrations** > **Webhooks** > **New Webhook**
4. Name it, then click **Copy Webhook URL**

No Discord Developer Portal signup, no bot creation, no API keys needed. Just the webhook URL.

### 5. Configure Environment

```bash
cp .env.example .env
```

Fill in all values:

```env
# Telegram
TG_API_ID=12345678
TG_API_HASH=your_api_hash
TG_SESSION=your_session_string
TG_CHAT_IDS=-1001234567890,-5059521329

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1234567890/xxxx...

# Timezone (IANA format)
TIMEZONE=Europe/Berlin
```

| Variable              | Description                                                                                          |
| --------------------- | ---------------------------------------------------------------------------------------------------- |
| `TG_API_ID`           | From [my.telegram.org](https://my.telegram.org)                                                      |
| `TG_API_HASH`         | From [my.telegram.org](https://my.telegram.org)                                                      |
| `TG_SESSION`          | Output of `generate_session.py`                                                                      |
| `TG_CHAT_IDS`         | Comma-separated Telegram group IDs (from `list_groups.py`)                                           |
| `DISCORD_WEBHOOK_URL` | From Discord channel settings > Integrations > Webhooks                                              |
| `TIMEZONE`            | [IANA timezone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) for message timestamps |

### 6. Run

```bash
docker compose up -d --build
```

Check logs:

```bash
docker logs -f telebot
```

You should see:

```
Bot started. Listening to 2 chat(s)
Watching: My Group (-1001234567890)
Watching: Another Group (-5059521329)
```

## Deployment to a VPS

### Requirements

- Any Linux VPS with Docker installed (tested on Ubuntu 22.04+)
- Minimum: 1 vCPU, 512MB RAM (the bot uses ~30-50MB)

### Steps

```bash
# On the VPS
git clone https://github.com/mohed-abbas/telebot.git
cd telebot

# Copy your .env (from local machine via scp, or create manually)
scp user@local:.env .env    # or create it manually

# Start
docker compose up -d --build

# Verify
docker logs -f telebot
```

The bot auto-restarts on crashes and VPS reboots (`restart: unless-stopped`).

### Resource Usage

| Resource | Usage                                   |
| -------- | --------------------------------------- |
| RAM      | ~30-50MB                                |
| CPU      | <1% (idle between messages)             |
| Disk     | ~150MB (Docker image) + 30MB max (logs) |
| Network  | ~1-5MB/day                              |

## Operations

| Command                         | Description                         |
| ------------------------------- | ----------------------------------- |
| `docker compose up -d --build`  | Start or rebuild the bot            |
| `docker compose down`           | Stop the bot                        |
| `docker compose restart`        | Restart (e.g. after `.env` changes) |
| `docker logs -f telebot`        | Follow live logs                    |
| `docker logs --tail 50 telebot` | View last 50 log lines              |

## Error Handling

| Scenario                       | Behavior                                                                |
| ------------------------------ | ----------------------------------------------------------------------- |
| Telegram network drop          | Auto-reconnect (10 retries, 5s delay)                                   |
| Discord webhook failure        | 3 retries with exponential backoff (1s, 2s, 4s), then drops the message |
| Message has no text/caption    | Silently skipped                                                        |
| Missing `.env` variable        | Bot refuses to start with a clear error message                         |
| Unhandled exception in handler | Telethon catches it — bot continues running                             |

## Limitations

- Messages sent while the bot is offline are not recovered (Telegram does not replay them for userbot sessions)
- Discord messages are truncated at 2,000 characters (Discord limit)
- Media files are not forwarded — only text and media captions
- Discord webhook rate limit: 30 messages/minute (sufficient for typical group activity)

## Adding More Telegram Groups

1. Find the chat ID using `list_groups.py`
2. Add it to `TG_CHAT_IDS` in `.env` (comma-separated)
3. `docker compose restart`

## Swapping Telegram Account

1. Run `generate_session.py` with the new phone number
2. Update `TG_SESSION` in `.env`
3. `docker compose restart`

No code changes or Docker rebuild needed.

## License

MIT
