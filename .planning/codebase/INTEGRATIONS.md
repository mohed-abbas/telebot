# External Integrations

**Analysis Date:** 2026-03-19

## APIs & External Services

**Telegram:**
- Service: Telegram messaging platform
- What it's used for: Group message relay, signal detection, media download (photos/videos)
- SDK/Client: telethon (1.42.0)
- Auth: TG_API_ID, TG_API_HASH (via https://my.telegram.org), TG_SESSION (string session)
- Features used:
  - `TelegramClient.get_entity()` - Resolve group names
  - `events.NewMessage(chats=...)` - Listen to specific group chats
  - `client.download_media()` - Download photos/videos up to 8MB
  - StringSession for stateless authentication

**Discord Webhooks:**
- Service: Discord
- What it's used for: Multi-channel message relay and notifications
- SDK/Client: httpx (1.42.0) - raw HTTP POST to webhook URLs
- Auth: Webhook URLs (no API key needed, URL itself is secret)
- Webhooks:
  - `DISCORD_WEBHOOK_URL` - #signals channel (raw Telegram relay, text + media)
  - `DISCORD_WEBHOOK_EXECUTIONS` (optional) - #executions channel (trade fills, closes, P&L)
  - `DISCORD_WEBHOOK_ALERTS` (optional) - #alerts channel (errors, connection drops, daily limits)
- Implementation: `discord_sender.py` with retry logic (3 attempts, exponential backoff)
- Rate limits: Respects Discord's per-webhook rate limits, retries with exponential backoff

## Data Storage

**Databases:**
- Type: SQLite 3
- Location: `data/telebot.db` (path configurable via `DB_PATH` env var, default: data/telebot.db)
- Client: sqlite3 (stdlib) with aiosqlite (0.20.0) wrapper
- Connection: `sqlite3.connect(check_same_thread=False)` with WAL mode enabled
- Tables:
  - `signals` - Parsed trading signals (timestamp, raw text, symbol, direction, entry zone, SL, TP)
  - `trades` - Executed trades with entry/exit prices, lot size, P&L tracking
  - `daily_stats` - Per-account daily aggregates (trade count, server messages, P&L)
  - `pending_orders` - Limit orders with expiry time and status tracking

**File Storage:**
- None (no cloud storage)
- Media downloaded from Telegram stored in memory (BytesIO) and streamed to Discord
- No local file caching of Telegram media

**Caching:**
- None detected (stateless per-message processing)
- In-memory state in Python objects (executor, trade manager, connectors)

## Authentication & Identity

**Telegram API:**
- Auth Provider: Telegram (custom protocol via telethon)
- Implementation: StringSession (persisted session token)
- Flow:
  - Initial: `python generate_session.py` - Interactive login to generate TG_SESSION token
  - Runtime: Session string stored in `TG_SESSION` env var, passed to `TelegramClient(StringSession(...))`
  - No browser/OTP required after initial generation

**Dashboard:**
- Auth Provider: Custom HTTP Basic auth
- Implementation: `fastapi.security.HTTPBasic()`
- Credentials: `DASHBOARD_USER` (default: admin), `DASHBOARD_PASS` (default: changeme)
- Stored as: Plain environment variables (no hashing)
- Protection: Constant-time comparison via `secrets.compare_digest()`

**MT5 Connection:**
- Auth Provider: MetaTrader5 account credentials
- Implementation: Accounts configured in `accounts.json`
- Fields per account:
  - login (MT5 account number)
  - password (resolved from env var, e.g., MT5_PASS_1)
  - server (MT5 server name, e.g., FundedNext-Server)
- Backends:
  - dry_run: No auth needed (simulator)
  - mt5linux: RPyC-based connection to Wine MT5 terminal (credentials passed to `mt5.login()`)

## Monitoring & Observability

**Error Tracking:**
- None detected (no external error tracking service)
- Logging: Python stdlib `logging` module (captured to console, logged by Docker)

**Logs:**
- Approach: Console logging via `logging.basicConfig()` with format `[timestamp] [level] module: message`
- Destinations:
  - Container stdout (captured by Docker JSON file driver)
  - Docker logging config: max-size 10m, max 3 files (log rotation)
- Log levels: INFO for normal operation, WARNING for recoverable errors, ERROR for failures
- No persistent log storage (ephemeral unless logs are saved by Docker driver)

**Metrics:**
- None (no Prometheus, Datadog, or equivalent)
- Runtime state accessible via dashboard endpoints (positions, daily stats, recent trades)

## CI/CD & Deployment

**Hosting:**
- Docker container (location: user's VPS or local)
- Base image: python:3.12-slim
- Orchestration: docker-compose.yml (single service, port 8080)
- Deployment: Pull code, `docker-compose up -d`

**CI Pipeline:**
- None detected (no GitHub Actions, GitLab CI, etc.)
- Manual deployment via docker-compose

**Versioning:**
- No API versioning
- Code versioning via git

## Environment Configuration

**Required Environment Variables:**

### Telegram
- `TG_API_ID` (int) - Telegram API ID from https://my.telegram.org
- `TG_API_HASH` (str) - Telegram API hash from https://my.telegram.org
- `TG_SESSION` (str) - StringSession token (generated via `generate_session.py`)
- `TG_CHAT_IDS` (comma-separated int list) - Group chat IDs to monitor (e.g., -1001234567890,-1009876543210)

### Discord
- `DISCORD_WEBHOOK_URL` (str) - Required, #signals channel webhook
- `DISCORD_WEBHOOK_EXECUTIONS` (str) - Optional, #executions channel webhook
- `DISCORD_WEBHOOK_ALERTS` (str) - Optional, #alerts channel webhook

### Trading
- `TRADING_ENABLED` (bool, default: false) - Master switch to enable trade execution
- `TRADING_DRY_RUN` (bool, default: true) - Dry-run mode (logs trades, doesn't execute)
- `MT5_BACKEND` (str, default: dry_run) - Backend: "dry_run" or "mt5linux"
- `MT5_HOST` (str, default: localhost) - RPyC server host for mt5linux backend
- `MT5_PORT` (int, default: 18812) - RPyC server port for mt5linux backend
- `ACCOUNTS_CONFIG` (str, default: accounts.json) - Path to accounts.json file
- `DB_PATH` (str, default: data/telebot.db) - Path to SQLite database

### Dashboard
- `DASHBOARD_ENABLED` (bool, default: true) - Enable web dashboard
- `DASHBOARD_PORT` (int, default: 8080) - Port to bind dashboard
- `DASHBOARD_USER` (str, default: admin) - Basic auth username
- `DASHBOARD_PASS` (str, default: changeme) - Basic auth password

### General
- `TIMEZONE` (str, required) - IANA timezone (e.g., Europe/Berlin) for timestamp formatting

**MT5 Account Passwords:**
- Referenced by accounts.json `password_env` field
- Examples: `MT5_PASS_1`, `MT5_PASS_2`, `MT5_PASS_3`
- Loaded into account config via `config.load_accounts_config()`

**Secrets Location:**
- `.env` file (not committed, matches `.env.example` template)
- accounts.json passwords via environment variables (not in file)
- Telegram session generated and stored in `TG_SESSION` env var

## Webhooks & Callbacks

**Incoming:**
- None (this is a receiving-only bot for Telegram groups)

**Outgoing:**
- Discord Webhook POST (3 channels, asynchronous via httpx)
  - #signals: Raw Telegram message relay + parsed trade signals
  - #executions: Trade execution results (fill prices, closes, P&L)
  - #alerts: System alerts (connection drops, daily limits, errors)
- MT5 RPyC calls (if mt5linux backend active)
  - `mt5.login(login, password, server)` - Connect to account
  - `mt5.order_send(request)` - Place/modify/close orders
  - `mt5.positions_get()` - Get open positions
  - `mt5.orders_get()` - Get pending orders

## Rate Limiting & Quotas

**Telegram:**
- Handled by telethon (respects Telegram's rate limits automatically)
- Max file download: 8MB (enforced in `bot.py` MAX_FILE_SIZE)

**Discord:**
- Webhook per-second rate limit (10 messages/second per webhook)
- Handled by httpx with retry logic (exponential backoff: 1s, 2s, 4s)
- Max message length: 2000 characters (enforced in `discord_sender.py`)

**MT5:**
- No explicit rate limits in code (depends on broker)
- Daily trading limits per account (configurable in accounts.json):
  - max_daily_trades_per_account (default: 30)
  - max_daily_server_messages (default: 500)

## Data Flow

**Signal Relay (Text Only):**
```
Telegram Group
  ↓ (NewMessage event)
bot.py (format_message)
  ↓ (httpx.post)
Discord #signals channel
```

**Signal Relay (With Media):**
```
Telegram Group (photo/video)
  ↓ (client.download_media → BytesIO)
bot.py (httpx.post with file attachment)
  ↓
Discord #signals channel (embedded media)
```

**Trade Execution Flow:**
```
Telegram Group (text)
  ↓ (parse_signal)
signal_parser.py (pattern matching)
  ↓ (matches OPEN/CLOSE/MODIFY signal)
executor.py (execute_signal)
  ↓ (risk_calculator → lot size)
trade_manager.py (route to MT5 account)
  ↓ (mt5_connector → order_send/close_position)
MT5 Account (order placed/closed)
  ↓
notifier.py (build execution summary)
  ↓ (httpx.post)
Discord #executions channel
```

**Daily Stats Tracking:**
```
Trade Execution
  ↓ (db.log_trade, increment_daily_stat)
SQLite (trades, daily_stats tables)
  ↓ (dashboard reads via db.get_recent_trades)
FastAPI /overview endpoint
  ↓ (Jinja2 render)
Dashboard HTML (live positions, P&L)
```

---

*Integration audit: 2026-03-19*
