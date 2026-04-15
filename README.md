# Telebot

**A 24/7 Telegram → Discord signal relay and automated MetaTrader 5 trading bot.**

Telebot listens to one or more Telegram groups over MTProto, relays every message to Discord, parses trading signals (entry zones, SL, multiple TPs), and executes them across multiple MT5 broker accounts with per-account risk management, lot sizing, jitter, stagger, and a kill switch. A web dashboard shows live positions, P&L, signal history, and execution analytics.

![Python](https://img.shields.io/badge/python-3.12-blue.svg)
![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![MT5](https://img.shields.io/badge/MT5-REST%20bridge-orange.svg)

---

## Table of Contents

- [At a Glance](#at-a-glance)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [MT5 Trading (REST Bridge)](#mt5-trading-rest-bridge)
- [Deployment](#deployment)
- [Operations](#operations)
- [Development](#development)
- [Project Structure](#project-structure)
- [Documentation](#documentation)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## At a Glance

| What | Detail |
|------|--------|
| **Input**  | One or more Telegram groups (view-only access is enough) |
| **Relay**  | Discord webhooks (signals, executions, alerts — separate channels) |
| **Execute**| MetaTrader 5 via REST bridge on a Windows host |
| **Store**  | PostgreSQL (signals, trades, fills, analytics) |
| **Observe**| FastAPI dashboard with live positions, P&L, kill switch |
| **Run**    | Docker Compose on any small Linux VPS (~30–50 MB RAM) |

### Features

- Real-time Telegram listener via Telethon (MTProto userbot — no bot token needed)
- Regex-based signal parser: entry zones, stop-loss, multiple take-profits, direction, symbol
- Multi-account MT5 execution with per-account lot sizing, jitter, stagger delay, magic numbers
- Dry-run mode with a full GBM price simulator for local development
- Kill switch, heartbeat monitoring, auto-reconnect, structured Discord alerts
- Web dashboard (FastAPI + Jinja2) with HTTPS via nginx
- Trade archival CLI for long-term retention
- 113+ pytest tests covering parser, risk calc, connectors, concurrency

---

## Architecture

```
  Telegram Group(s)          Discord Channels            MT5 Accounts
    (new message)         ┌── #signals (relay)       ┌── Vantage Demo
         │                │   #executions (fills)     │   FundedNext
         │ MTProto        │   #alerts (errors)        │   ...
         ▼                │                           │
  ┌─────────────────────────────────────────────────────────────┐
  │                     telebot (Python)                        │
  │                                                             │
  │  Telethon ──► Signal Parser ──► Trade Manager ──► Executor  │
  │  (listener)   (regex+rules)     (risk calc)      (MT5 API)  │
  │      │                                               │      │
  │      ▼                                               │      │
  │  Discord ◄── Notifier ◄─────────────────────────────┘      │
  │  (httpx)     (fills, alerts)                                │
  └────────────────────┼─────────────────────────┼──────────────┘
                       │                         │
                proxy-net                    data-net
                       │                 │          │
                    nginx ◄──┘       postgres    mt5-rest-server
                    (HTTPS)          (shared)    (REST API on Windows)
```

Each MT5 account is fully isolated: its own terminal, its own Python process, its own port. The Linux bot talks to each broker over plain HTTP on the Windows host. Both MT5 and uvicorn run as startup apps in the same desktop session (required for MT5's named-pipe IPC — Windows services don't work, see [Issue #10](docs/issues-solved.md#issue-10-nssm-service--mt5-ipc-timeout-session-0-isolation)).

---

## Prerequisites

- A Telegram account that is a member of the target group(s)
- A Discord server where you can create webhooks
- Docker + docker compose on your deployment machine
- Python 3.12+ on your local machine (for one-time session generation)
- A Windows machine (VPS or mini PC) if you want MT5 execution

---

## Quick Start

```bash
# Clone
git clone https://github.com/mohed-abbas/telebot.git && cd telebot

# One-time: generate Telegram session on your local machine
pip install telethon python-dotenv
python generate_session.py

# Configure
cp .env.example .env
$EDITOR .env

# Run
docker compose up -d --build
docker logs -f telebot
```

Expected log output:
```
Bot started. Listening to 2 chat(s)
Watching: My Group (-1001234567890)
Watching: Another Group (-5059521329)
```

---

## Configuration

### 1. Telegram API credentials

1. Visit [my.telegram.org](https://my.telegram.org) and log in.
2. Open **API development tools** and create an application.
3. Note the `api_id` and `api_hash`.

### 2. Generate a session string

Run **on your local machine** (interactive prompts cannot be answered headlessly on a VPS):

```bash
python generate_session.py
```

Provide:
- `api_id` / `api_hash`
- phone number (with country code, e.g. `+33...`)
- the 5-digit login code Telegram sends you
- your 2FA password (if enabled)

Copy the output into `.env` as `TG_SESSION`.

### 3. Find Telegram chat IDs

Fill `TG_API_ID`, `TG_API_HASH`, `TG_SESSION` in `.env`, then:

```bash
python list_groups.py
```

```
GROUP NAME                               CHAT ID              TYPE
---------------------------------------------------------------------------
My Group                                 -1001234567890       Channel
Another Group                            -5059521329          Chat
```

Put the `CHAT ID` values (comma-separated) into `TG_CHAT_IDS`.

### 4. Create a Discord webhook

In Discord: right-click channel → **Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL**. No bot, no developer portal — just a URL.

### 5. Fill `.env`

```env
# Telegram
TG_API_ID=12345678
TG_API_HASH=your_api_hash
TG_SESSION=your_session_string
TG_CHAT_IDS=-1001234567890,-5059521329

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Timezone
TIMEZONE=Europe/Berlin
```

| Variable              | Description                                                                                         |
| --------------------- | --------------------------------------------------------------------------------------------------- |
| `TG_API_ID`           | From [my.telegram.org](https://my.telegram.org)                                                     |
| `TG_API_HASH`         | From [my.telegram.org](https://my.telegram.org)                                                     |
| `TG_SESSION`          | Output of `generate_session.py`                                                                     |
| `TG_CHAT_IDS`         | Comma-separated group IDs from `list_groups.py`                                                     |
| `DISCORD_WEBHOOK_URL` | Relay channel webhook                                                                               |
| `TIMEZONE`            | [IANA timezone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) for message stamps    |

See `.env.example` for the full set including MT5, dashboard, and simulator knobs.

---

## MT5 Trading (REST Bridge)

The bot doesn't link against MetaTrader5 directly. It talks to a small FastAPI REST server that wraps the native `MetaTrader5` Python package and runs on a Windows host — one process per broker account.

```
  Linux VPS (bot)                    Windows host (VPS or home mini PC)
  ┌───────────────────┐              ┌────────────────────────────────┐
  │ telebot           │              │ mt5-rest-server                │
  │                   │   HTTP       │                                │
  │ RestApiConnector──┼────:8001───► │ server.py #1  →  MT5 terminal#1│
  │ RestApiConnector──┼────:8002───► │ server.py #2  →  MT5 terminal#2│
  │                   │              │  ...                           │
  └───────────────────┘              └────────────────────────────────┘
```

### Why a bridge?

The `MetaTrader5` Python package is **Windows-only** and pins session state to the interpreter's main thread inside the same desktop session as the MT5 terminal. This makes it unsuitable for running directly inside a Linux container. The bridge isolates the Windows-only piece and lets the bot stay containerized and cloud-native on Linux.

### Deployment options for the bridge

| Option             | Cost      | Docs                                                  |
|--------------------|-----------|-------------------------------------------------------|
| Windows VPS        | ~$10–20/mo| [docs/windows-vps-setup.md](docs/windows-vps-setup.md)|
| Home mini PC       | $0/mo     | [docs/deployment-home-mini-pc.md](docs/deployment-home-mini-pc.md) |

Switching between them is a hostname change in `accounts.json`. Architectural rationale and protocol spec: [docs/architecture-rest-api-bridge.md](docs/architecture-rest-api-bridge.md).

### Adding / managing broker accounts

See [docs/adding-new-account.md](docs/adding-new-account.md).

### Important: symbols must be in MT5 Market Watch

Every symbol the bot trades (e.g. `XAUUSD`, `EURUSD`) **must be visible in the MT5 terminal's Market Watch** on the Windows host. `mt5.symbol_info_tick()` returns `None` for symbols that aren't in Market Watch, even if the symbol is correct and tradeable on the broker — this surfaces as `FAILED — Cannot get current price` at execution time.

To add a symbol: open the MT5 terminal → **Ctrl+M** to open Market Watch → right-click → **Symbols** (or **Ctrl+U**) → search → **Show** → save the profile. Do this once per account, per symbol. Details: [Issue #13](docs/issues-solved.md#issue-13-cannot-get-current-price-on-live-account--symbol-not-in-market-watch).

### Important: enable Algo Trading on the terminal

The MT5 toolbar has an **Algo Trading** toggle (green ▶ when on). If it's off, `order_check` passes but `order_send` returns `retcode=10027 AutoTrading disabled by client` and your trade is silently rejected at the terminal. Persist the setting via **Tools → Options → Expert Advisors → Allow algorithmic trading**. Details: [Issue #15](docs/issues-solved.md#issue-15-retcode10027-autotrading-disabled-by-client).

---

## Deployment

### Requirements

- Any Linux VPS with Docker (tested on Ubuntu 22.04+)
- Minimum 1 vCPU / 512 MB RAM

### Steps

```bash
# On the VPS
git clone https://github.com/mohed-abbas/telebot.git && cd telebot
scp user@local:.env .env          # or create .env manually
docker compose up -d --build
docker logs -f telebot
```

The stack auto-restarts on crashes and host reboots (`restart: unless-stopped`).

### Resource footprint

| Resource | Usage                                   |
| -------- | --------------------------------------- |
| RAM      | ~30–50 MB                               |
| CPU      | < 1 % idle between messages             |
| Disk     | ~150 MB image + 30 MB max logs          |
| Network  | ~1–5 MB/day                             |

---

## Operations

### Everyday commands

| Command                         | Purpose                                     |
| ------------------------------- | ------------------------------------------- |
| `docker compose up -d --build`  | Start or rebuild the bot                    |
| `docker compose up -d`          | Recreate containers (picks up `.env` edits) |
| `docker compose down`           | Stop the bot                                |
| `docker logs -f telebot`        | Follow live logs                            |
| `docker logs --tail 50 telebot` | Last 50 log lines                           |

### Adding more Telegram groups

1. Find the chat ID with `list_groups.py`.
2. Append it to `TG_CHAT_IDS` in `.env` (comma-separated).
3. `docker compose restart`.

### Swapping the Telegram account

1. `python generate_session.py` with the new phone number.
2. Update `TG_SESSION` in `.env`.
3. `docker compose restart`.

No code changes, no rebuild.

### Error handling

| Scenario                       | Behavior                                                                |
| ------------------------------ | ----------------------------------------------------------------------- |
| Telegram network drop          | Auto-reconnect (10 retries, 5 s delay)                                  |
| Discord webhook failure        | 3 retries with exponential backoff (1 s, 2 s, 4 s), then drops the message |
| Message with no text/caption   | Silently skipped                                                        |
| Missing `.env` variable        | Bot refuses to start with a clear error                                 |
| Unhandled exception in handler | Telethon catches it — bot continues                                     |

### Limitations

- Messages sent while the bot is offline are not recovered (MTProto userbots don't replay).
- Discord messages are truncated at 2 000 characters (Discord limit).
- Media files are not forwarded; only text and captions.
- Discord webhook rate limit: 30 msg/min per webhook.

---

## Development

### Local dev environment (no Windows required)

```bash
docker compose -f docker-compose.dev.yml up --build
```

Brings up PostgreSQL, the in-memory MT5 simulator on port 8001, and the bot. End-to-end testing (Telegram signal → parse → REST execution → Discord relay) runs on macOS and Linux.

Dashboard: <http://localhost:8080> (default `admin` / `devpass123`).

### Running tests

```bash
pip install -r requirements-dev.txt
docker compose -f docker-compose.dev.yml up -d db   # test Postgres on :5433

# Pure unit tests (no DB)
python -m pytest tests/test_mt5_connector.py tests/test_signal_parser.py \
                 tests/test_signal_regression.py tests/test_risk_calculator.py -v

# Integration tests (require Postgres on :5433)
python -m pytest tests/test_trade_manager.py tests/test_trade_manager_integration.py \
                 tests/test_concurrency.py -v

# Full suite
python -m pytest tests/ -v
```

### Database maintenance

```bash
# Archive closed trades older than 3 months into CSV
docker compose exec telebot python maintenance.py --archive --months 3
```

---

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
├── price_simulator.py      # GBM engine for dry-run simulation
├── accounts.json           # Per-account MT5 config (gitignored)
├── docker-compose.yml      # Production compose
├── docker-compose.dev.yml  # Dev compose with local PostgreSQL + simulator
├── Dockerfile              # Python 3.12 slim image
├── mt5-rest-server/        # REST API wrapping native MT5 (Windows host)
│   ├── server.py           # FastAPI app
│   ├── config.py           # Env vars (API key, MT5 credentials)
│   ├── requirements.txt
│   └── diag*.py            # Diagnostic scripts (see issues-solved.md)
├── mt5-simulator/          # Docker-based MT5 simulator (local dev)
│   ├── simulator.py
│   ├── state.py
│   └── Dockerfile
├── nginx/                  # Reverse proxy config
├── templates/              # Dashboard HTML templates
├── docs/                   # Documentation (see below)
└── tests/                  # pytest suite (113+ tests)
```

---

## Documentation

| Document                                                                        | What it covers                                     |
|---------------------------------------------------------------------------------|----------------------------------------------------|
| [docs/windows-vps-setup.md](docs/windows-vps-setup.md)                          | Windows VPS setup for the MT5 REST bridge          |
| [docs/deployment-home-mini-pc.md](docs/deployment-home-mini-pc.md)              | Running the MT5 bridge on a home mini PC           |
| [docs/architecture-rest-api-bridge.md](docs/architecture-rest-api-bridge.md)    | Rationale and protocol for the REST bridge         |
| [docs/adding-new-account.md](docs/adding-new-account.md)                        | Adding, disabling, or removing broker accounts     |
| [docs/server-messages.md](docs/server-messages.md)                              | MT5 server message limits and behaviour            |
| [docs/issues-solved.md](docs/issues-solved.md)                                  | Historical record of issues and their diagnoses    |

---

## Troubleshooting

For any production incident, start at [`docs/issues-solved.md`](docs/issues-solved.md). It indexes every issue we've hit in deployment, with symptom, root cause, and exact fix. Recent highlights:

| Symptom                                                     | See                                                                                                              |
|-------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| `FAILED — Cannot get current price`                         | [Issue #13](docs/issues-solved.md#issue-13-cannot-get-current-price-on-live-account--symbol-not-in-market-watch) |
| `(-2, 'Unnamed arguments not allowed')` on every order      | [Issue #14](docs/issues-solved.md#issue-14-mt5-order_send--order_check-returns--2-unnamed-arguments-not-allowed) |
| `retcode=10027 AutoTrading disabled by client`              | [Issue #15](docs/issues-solved.md#issue-15-retcode10027-autotrading-disabled-by-client)                          |
| `IPC timeout` from NSSM-hosted REST server                  | [Issue #10](docs/issues-solved.md#issue-10-nssm-service--mt5-ipc-timeout-session-0-isolation)                    |
| REST server returns `connected: false` despite `200 OK`     | [Issue #6](docs/issues-solved.md#issue-6-rest-api-connect-always-returns-false)                                  |

---

## License

MIT
