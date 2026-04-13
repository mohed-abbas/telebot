# Telebot — Telegram Signal Relay + Automated MT5 Trading

A Python bot that listens to Telegram group chats, relays messages to Discord, and optionally executes parsed trading signals on MetaTrader 5 accounts. Designed to run 24/7 as Docker containers.

## How It Works

```
  Telegram Group(s)            Discord Channels          MT5 Accounts
    (new message)          ┌─── #signals (relay)     ┌── Vantage Demo
         │                 │    #executions (fills)   │   FundedNext
         │ MTProto         │    #alerts (errors)      │   ...
         ▼                 │                          │
  ┌─────────────────────────────────────────────────────────────┐
  │                    telebot (Python)                         │
  │                                                             │
  │  Telethon ──► Signal Parser ──► Trade Manager ──► Executor  │
  │  (listener)   (regex+rules)     (risk calc)      (MT5 API) │
  │      │                                               │      │
  │      ▼                                               │      │
  │  Discord ◄── Notifier ◄────────────────────────────┘      │
  │  (httpx)     (fills, alerts)                               │
  └──────────────────┼─────────────────────────┼───────────────┘
                     │                         │
               proxy-net                  data-net
                     │                    │         │
                  nginx ◄─┘          postgres    mt5-rest-server
                  (HTTPS)            (shared)    (REST API on Windows)
```

### Features

- Listens to one or more Telegram groups (even with view-only access)
- Relays messages + media to Discord via webhook
- Parses trading signals (entry zones, SL, TP levels)
- Executes trades on MT5 accounts with risk management
- Per-account lot sizing, jitter, and stagger delays
- Kill switch, heartbeat monitoring, auto-reconnect
- Web dashboard with analytics (HTTPS via nginx)

## Tech Stack

| Component       | Technology                                               | Purpose                                         |
| --------------- | -------------------------------------------------------- | ----------------------------------------------- |
| Telegram client | [Telethon](https://docs.telethon.dev/) v1.42             | MTProto userbot — real-time message listener     |
| Discord output  | Discord Webhooks                                         | Relay signals, trade fills, and alerts           |
| HTTP client     | [httpx](https://www.python-httpx.org/) v0.28             | Async HTTP for Discord + external calls          |
| Trading         | REST API + [httpx](https://www.python-httpx.org/)        | MT5 via REST server on Windows VPS               |
| Database        | [asyncpg](https://github.com/MagicStack/asyncpg) + PostgreSQL | Trade log, signal audit, analytics          |
| Dashboard       | [FastAPI](https://fastapi.tiangolo.com/) + Jinja2        | Web UI with kill switch and analytics            |
| Config          | [python-dotenv](https://pypi.org/project/python-dotenv/) | Loads `.env` file                                |
| Runtime         | Python 3.12                                              |                                                  |
| Deployment      | Docker + docker compose                                  | Auto-restart, log rotation, shared networking    |

## Project Structure

```
telebot/
├── bot.py                  # Entrypoint — Telethon handler, signal dispatch
├── config.py               # Env validation, Settings dataclass
├── signal_parser.py        # Regex-based signal extraction
├── models.py               # SignalAction, AccountConfig, GlobalConfig
├── trade_manager.py        # Risk calc, order placement, zone logic
├── executor.py             # Heartbeat, reconnect, kill switch
├── mt5_connector.py        # MT5 abstraction (DryRun + RestApi backends)
├── notifier.py             # Discord notifications (fills, alerts)
├── db.py                   # asyncpg database layer
├── dashboard.py            # FastAPI web dashboard
├── discord_sender.py       # Discord webhook client with retry
├── maintenance.py          # Trade archival CLI
├── risk_calculator.py      # Position sizing logic
├── accounts.json           # Per-account MT5 config (gitignored)
├── docker-compose.yml      # Production compose (proxy-net + data-net)
├── docker-compose.dev.yml  # Dev compose with local PostgreSQL
├── Dockerfile              # Python 3.12 slim image
├── mt5-rest-server/        # REST API wrapping native MT5 (Windows VPS)
│   ├── server.py           # FastAPI app — all mt5.* via run_in_executor
│   ├── config.py           # Env var reader (API key, MT5 credentials)
│   └── requirements.txt    # fastapi, uvicorn, MetaTrader5
├── mt5-simulator/          # Docker-based MT5 simulator (local dev)
│   ├── simulator.py        # FastAPI app — same REST API, in-memory state
│   ├── state.py            # Positions, orders, P&L calculation
│   └── Dockerfile          # python:3.12-slim + uvicorn
├── nginx/                  # Reverse proxy config
│   └── telebot.conf
├── templates/              # Dashboard HTML templates
├── price_simulator.py      # GBM price engine for dry-run simulation
├── docs/                   # Documentation
│   ├── windows-vps-setup.md          # Windows VPS setup guide
│   ├── adding-new-account.md         # Adding/removing MT5 accounts
│   ├── issues-solved.md              # Troubleshooting history
│   ├── architecture-rest-api-bridge.md # REST API architecture
│   ├── deployment-home-mini-pc.md    # Home mini PC deployment
│   └── server-messages.md            # MT5 server message limits
├── tests/                  # pytest test suite (113+ tests)
└── .env.example            # All environment variables
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
| `docker compose up -d`          | Recreate (picks up `.env` changes)  |
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

## MT5 Trading (REST API)

The telebot connects to MetaTrader 5 via a REST API. The MT5 REST server runs natively
on a Windows machine (VPS or home mini PC), one FastAPI process per broker account.

```
  Hostinger VPS (Linux)              Windows (VPS or mini PC)
  ┌──────────────────┐              ┌──────────────────────────┐
  │ telebot           │              │ mt5-rest-server          │
  │                   │    HTTPS     │                          │
  │ RestApiConnector──┼────:8001───► │ server.py #1 → MT5 #1   │
  │ RestApiConnector──┼────:8002───► │ server.py #2 → MT5 #2   │
  │                   │              │ ...                      │
  └──────────────────┘              └──────────────────────────┘
```

Each account is fully isolated: separate MT5 terminal, separate Python process,
separate port. Both MT5 and uvicorn run as startup apps in the same desktop
session (required for MT5 IPC — Windows services won't work).

### Deployment Options

- **Windows VPS** (~$10-20/mo) — see [docs/windows-vps-setup.md](docs/windows-vps-setup.md)
- **Home mini PC** ($0/mo) — see [docs/deployment-home-mini-pc.md](docs/deployment-home-mini-pc.md)
- **Architecture details** — see [docs/architecture-rest-api-bridge.md](docs/architecture-rest-api-bridge.md)

Switching between them is just a hostname change in `accounts.json`.

### Adding / Managing Accounts

See [docs/adding-new-account.md](docs/adding-new-account.md) for the complete
guide on adding, disabling, or removing broker accounts.

### Important: Symbols Must Be in MT5 Market Watch

Every symbol the bot trades (e.g. `XAUUSD`, `EURUSD`) **must be visible in the
MT5 terminal's Market Watch** on the Windows machine. The MT5 Python API
(`mt5.symbol_info_tick`) returns `None` for symbols that aren't in Market Watch,
even if the symbol name is exactly correct and tradeable on the broker — this
surfaces as `FAILED — Cannot get current price` at signal execution time.

To add a symbol on the Windows VPS:

1. Open the MT5 terminal for the affected account
2. Press **Ctrl+M** to open Market Watch
3. Right-click → **Symbols** (or Ctrl+U) → search the instrument → click **Show**
4. Save the terminal profile so the symbol persists across restarts

Do this once per account, for every symbol your signals reference. See
[docs/issues-solved.md](docs/issues-solved.md) Issue #13 for diagnostic details.

## Development

### Local Dev Environment

```bash
# Start local PostgreSQL + MT5 simulator + bot
docker compose -f docker-compose.dev.yml up --build
```

This starts the MT5 simulator on port 8001, allowing full pipeline testing
(Telegram signal → parse → REST execution → Discord notification) on Mac/Linux.

Dashboard at http://localhost:8080 (admin / devpass123).

### Running Tests

```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Start test database (if not already running)
docker compose -f docker-compose.dev.yml up -d db

# Run unit tests (no database needed)
python -m pytest tests/test_mt5_connector.py tests/test_signal_parser.py tests/test_signal_regression.py tests/test_risk_calculator.py -v

# Run integration tests (requires PostgreSQL on port 5433)
python -m pytest tests/test_trade_manager.py tests/test_trade_manager_integration.py tests/test_concurrency.py -v

# Run all tests
python -m pytest tests/ -v
```

### Database Maintenance

```bash
# Archive closed trades older than 3 months to CSV
docker compose exec telebot python maintenance.py --archive --months 3
```

## License

MIT
