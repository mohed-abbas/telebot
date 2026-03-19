# Technology Stack

**Analysis Date:** 2026-03-19

## Languages

**Primary:**
- Python 3.12 - Core application, signal parsing, trading logic, dashboard

**Secondary:**
- HTML/Jinja2 3.1.4 - Dashboard templates
- JavaScript - Minimal HTMX/SSE interactions in dashboard frontend
- JSON - Configuration (accounts, signal keywords)

## Runtime

**Environment:**
- Python 3.12 (slim container image from Docker)

**Package Manager:**
- pip
- Lockfile: `requirements.txt` (pinned versions, not lock format)

## Frameworks

**Core Application:**
- Telethon 1.42.0 - Telegram client library, session management, message/media handling
- FastAPI 0.115.0 - Web dashboard, REST endpoints, HTTP Basic auth
- Uvicorn 0.32.0 - ASGI server (runs dashboard in background during bot operation)

**HTTP/Networking:**
- httpx 0.28.1 - Async HTTP client for Discord webhooks and external APIs

**Database:**
- sqlite3 (stdlib) - Trade logging, signal tracking, daily stats
- aiosqlite 0.20.0 - Async SQLite adapter (enables non-blocking DB ops)

**Templating:**
- Jinja2 3.1.4 - HTML template rendering (dashboard pages)

**Configuration:**
- python-dotenv 1.0.1 - Environment variable loading from `.env`

**Utilities:**
- python-multipart 0.0.12 - Form data parsing for FastAPI (file uploads, dashboard forms)

## Key Dependencies

**Critical for Core Function:**
- telethon 1.42.0 - Telegram client connectivity, message relay, group/chat interaction
- httpx 0.28.1 - Asynchronous webhooks to Discord (signals, executions, alerts)
- aiosqlite 0.20.0 - Non-blocking database access for trade logging

**Infrastructure & Execution:**
- uvicorn 0.32.0 - ASGI application server (dashboard runs as background task)
- fastapi 0.115.0 - Web framework for dashboard and monitoring UI
- jinja2 3.1.4 - Template rendering for HTML pages

**Configuration:**
- python-dotenv 1.0.1 - Secure env var handling (no hardcoded secrets)

**Trading Backend (Optional):**
- mt5linux (external, imported conditionally) - RPyC-based MT5 connection on Wine
- MetaTrader5 (conditional import) - Constants for MT5 API (only imported when mt5linux backend active)

## Configuration

**Environment Variables:**
- Loaded from `.env` file via `python-dotenv`
- Config validation in `config.py` using `_load_settings()` with required/optional vars
- `.env.example` provides template with all required vars

**Key Configuration Files:**
- `.env` - Runtime secrets (Telegram API, Discord webhooks, MT5 passwords) [NOT COMMITTED]
- `.env.example` - Template showing all config keys
- `accounts.json` - MT5 account credentials, trading limits, risk settings (path configurable via `ACCOUNTS_CONFIG` env var)
- `signal_keywords.json` - Trade signal pattern definitions
- `Dockerfile` - Python 3.12 slim image, pip install, port 8080 expose
- `docker-compose.yml` - Single telebot service, mounts data/accounts, logging config

## Build & Deployment

**Development:**
- No build step — Python scripts run directly
- `requirements.txt` lists all dependencies with pinned versions

**Docker:**
- Base image: `python:3.12-slim`
- Entrypoint: `python -u bot.py`
- Exposed port: 8080 (dashboard)
- Volume mounts: `./data:/app/data` (trade logs, database), `./accounts.json:/app/accounts.json`
- Restart policy: `unless-stopped`

**Database:**
- SQLite 3 with WAL mode (Write-Ahead Logging) for concurrent read/write
- Path: `data/telebot.db` (created automatically in data directory)
- Tables: signals, trades, daily_stats, pending_orders

## Platform Requirements

**Development:**
- Python 3.12+
- pip package manager
- Git
- Docker/Docker Compose (optional, for containerized deployment)

**Production:**
- Docker container (Linux-based host)
- Telegram API credentials (TG_API_ID, TG_API_HASH from https://my.telegram.org)
- Discord webhook URLs (3 separate webhooks: #signals, #executions, #alerts)
- MT5 backend (either DRY_RUN mode or mt5linux Wine instance with RPyC server on port 18812)
- Persistent volume for SQLite database and trade logs

## Package Dependency Tree

```
telethon (1.42.0)
  ├─ Handles Telegram protocol, message events, media download
  └─ Requires: TG_API_ID, TG_API_HASH, TG_SESSION (string session)

httpx (0.28.1)
  ├─ Async HTTP client for Discord webhooks
  ├─ Retry logic with exponential backoff (1s, 2s, 4s delays)
  └─ Timeout: 30.0s per request

fastapi (0.115.0)
  ├─ Web framework for dashboard
  ├─ HTTP Basic auth for dashboard access
  └─ Jinja2Templates for HTML rendering

uvicorn (0.32.0)
  ├─ ASGI server, runs dashboard in background task
  ├─ Bound to 0.0.0.0:{DASHBOARD_PORT}
  └─ Log level: warning

aiosqlite (0.20.0)
  └─ Wraps sqlite3 for async operations (no blocking I/O)

python-dotenv (1.0.1)
  └─ Loads .env file before config initialization

jinja2 (3.1.4)
  └─ Renders HTML templates for dashboard pages

python-multipart (0.0.12)
  └─ Parses FormData in FastAPI endpoints
```

## Runtime Behavior

**Startup Sequence:**
1. `bot.py` entry point (runs via `python -u bot.py` in Docker)
2. Load `.env` via `python-dotenv`
3. Initialize config from environment variables (`config.py`)
4. Create `httpx.AsyncClient` (reused for all Discord webhooks)
5. Connect Telegram client with StringSession
6. If `TRADING_ENABLED=true`:
   - Initialize SQLite database (`db.py`)
   - Load accounts config (`accounts.json`)
   - Create MT5 connectors (dry_run or mt5linux)
   - Start trade executor background task
7. Resolve Telegram group names
8. Register message event handler
9. If `DASHBOARD_ENABLED=true`:
   - Initialize FastAPI app
   - Start Uvicorn in background task
   - Listen on port 8080 with HTTP Basic auth
10. Block on `client.run_until_disconnected()` (Telegram event loop)

**Concurrent Tasks:**
- Telegram message listener (main async loop)
- Dashboard FastAPI server (background uvicorn task)
- Executor background task (pending order cleanup every 5 minutes)

---

*Stack analysis: 2026-03-19*
