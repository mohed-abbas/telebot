# Architecture

**Analysis Date:** 2026-03-19

## Pattern Overview

**Overall:** Async event-driven pipeline with layered signal processing and multi-account execution.

**Key Characteristics:**
- Real-time Telegram listener with Discord relay (base functionality)
- Optional automated trading signal parsing and execution pipeline (opt-in via TRADING_ENABLED)
- Multi-account support with staggered execution to avoid detection
- Separate concerns: parsing, validation, execution, notification
- Database-backed audit trail for all signals and trades
- Optional web dashboard for real-time monitoring

## Layers

**Telegram Listener Layer:**
- Purpose: Listen to Telegram groups in real-time via MTProto, format messages, relay to Discord
- Location: `bot.py` (event handler), `config.py` (settings)
- Contains: Telethon event handlers, message formatting, media relay logic
- Depends on: `config.py` (settings), `discord_sender.py` (webhook sender)
- Used by: Main event loop

**Signal Parsing Layer:**
- Purpose: Extract structured trading signals from raw Telegram messages
- Location: `signal_parser.py`, `models.py` (SignalAction dataclass)
- Contains: Regex-based signal detection, symbol mapping, multi-TP parsing
- Depends on: `models.py` (SignalType, Direction, SYMBOL_MAP)
- Used by: `bot.py` (handler), `dashboard.py` (signal history)

**Trade Execution Layer:**
- Purpose: Convert parsed signals into multi-account trades with all constraints and checks
- Location: `trade_manager.py`, `executor.py`
- Contains: Zone-based execution logic, position tracking, SL/TP modification, daily limits
- Depends on: `mt5_connector.py` (broker connection), `risk_calculator.py` (lot sizing), `db.py` (audit log), `models.py`
- Used by: `bot.py` (event handler), `dashboard.py` (trade management endpoints)

**MT5 Connection Layer:**
- Purpose: Abstract MT5 broker integration — supports multiple backend implementations
- Location: `mt5_connector.py` (abstract), backend implementations chosen via factory in `bot.py`
- Contains: Connection management, order placement, position queries, account info
- Depends on: Backend-specific connectors (dry_run or mt5linux via RPyC)
- Used by: `trade_manager.py`, `executor.py`

**Notification Layer:**
- Purpose: Route execution results and alerts to Discord channels
- Location: `notifier.py`, `discord_sender.py`
- Contains: Multi-webhook routing, formatted messages for each event type
- Depends on: `httpx.AsyncClient` (async HTTP), `discord_sender.py`
- Used by: `bot.py` (on signal execution), `executor.py` (on errors)

**Database Layer:**
- Purpose: Persistent audit log for signals, trades, and daily stats
- Location: `db.py`
- Contains: SQLite schema, async query wrappers, transaction management
- Depends on: `asyncio.Lock`, `sqlite3`
- Used by: `trade_manager.py` (log all actions), `dashboard.py` (read history)

**Web Dashboard Layer:**
- Purpose: Real-time monitoring and manual trade management via FastAPI
- Location: `dashboard.py`, `templates/` directory
- Contains: HTTP endpoints, SSE streams, HTML templates with HTMX
- Depends on: FastAPI, Jinja2, `db.py`, injected `executor`, `notifier`
- Used by: Browser clients (authenticated via HTTP Basic)

## Data Flow

**Telegram Message → Discord:**

1. Telegram event triggers (NewMessage on watched chats)
2. `handler()` in `bot.py` receives event
3. Extract text, media (photo/video), metadata
4. Format as "[Group] [Sender • HH:MM]: text"
5. Relay via `discord_sender.send_message()` to DISCORD_WEBHOOK_URL (#signals)
6. If media exceeds 8MB, skip download and send text-only notice

**Telegram Signal → Trade Execution:**

1. Same Telegram event triggers
2. `parse_signal(text)` extracts trading intent (open, close, modify SL/TP)
3. If trading enabled and signal valid:
   - `executor.execute_signal(signal)` shuffles account order
   - For each account (with random 1-5s stagger delay):
     - `trade_manager.handle_signal(signal)` processes on single account
     - Applies all checks: enabled, connected, daily limits, zone-based execution
     - Calls `connector.open_order()` (market or limit based on current price)
     - Logs to database via `db.log_signal()`, `db.log_trade()`
4. `notifier.notify_execution(signal, results)` sends formatted results to #executions
5. On error or stale signal: `notifier.notify_alert()` to #alerts

**State Management:**

- **Telegram connection:** Maintained by Telethon with auto-reconnect (connection_retries=10, retry_delay=5s)
- **MT5 connectors:** One per account, stored in `executor.tm.connectors` dict (keyed by account name)
- **Position tracking:** Queried on-demand from MT5 via `connector.get_positions()`
- **Daily stats:** Stored in SQLite `daily_stats` table, queried for limit enforcement
- **Pending orders:** Tracked in `pending_orders` table, expired orders cleaned up via background loop every 60s

## Key Abstractions

**SignalAction:**
- Purpose: Immutable representation of a parsed trading signal
- Examples: `models.py:29-46`
- Pattern: Frozen dataclass with type variants (OPEN, CLOSE, MODIFY_SL, MODIFY_TP, CLOSE_PARTIAL)
- Fields: symbol, direction, entry_zone, sl, tps, target_tp, raw_text for audit

**MT5Connector:**
- Purpose: Abstract interface to MT5 broker, hiding backend details
- Examples: `mt5_connector.py:60-100`
- Pattern: Base class with async methods (connect, get_price, open_order, modify_order, close_position)
- Implementations: Swapped via factory in `bot.py:98-106` based on MT5_BACKEND setting

**TradeManager:**
- Purpose: Orchestrate all trade logic for a single account execution
- Examples: `trade_manager.py:36-59`
- Pattern: Holds connectors, accounts, global config; routes signals to handlers by type
- Responsibilities: Signal logging, position mapping, limit checks, execution, order management

**Executor:**
- Purpose: Wrapper around TradeManager for humanization (shuffling, random delays)
- Examples: `executor.py:21-79`
- Pattern: Manages staggered account execution, spawns background cleanup task
- Used by: `bot.py:240-241` for orchestrated multi-account execution

## Entry Points

**Main Bot:**
- Location: `bot.py:274-275` (main async function)
- Triggers: Container startup via `python bot.py`
- Responsibilities:
  1. Load config (env vars, accounts.json)
  2. Initialize Telegram client with StringSession
  3. Set up trading pipeline (if TRADING_ENABLED)
  4. Connect all MT5 accounts
  5. Register Telegram event handler
  6. Launch optional dashboard (FastAPI + uvicorn)
  7. Block on `client.run_until_disconnected()`

**Dashboard:**
- Location: `dashboard.py:66` (FastAPI app)
- Entry: `bot.py:256-268` (uvicorn.Server in background task)
- Endpoints: `/overview`, `/positions`, `/history`, `/signals`, `/settings` (GET/POST)
- Auth: HTTP Basic (DASHBOARD_USER, DASHBOARD_PASS from env)

**One-time Utilities:**
- `generate_session.py`: Interactive prompt to generate Telegram StringSession (run locally)
- `list_groups.py`: Query all Telegram groups user is member of (run locally with valid .env)

## Error Handling

**Strategy:** Async exception handling with fallback notifications and connection resilience.

**Patterns:**

- **Telegram reconnection:** Telethon built-in auto_reconnect=True, connection_retries=10
- **MT5 connector failures:** Try/catch in `trade_manager._execute_open_on_account()`, notify via `notifier.notify_connection_lost()`
- **Trade execution errors:** Caught in `bot.py:240-248`, logged to db, alert sent to #alerts
- **Discord webhook failures:** Retry with exponential backoff in `discord_sender.py` (up to 5 retries)
- **Database errors:** Wrapped in `db.py` with transaction rollback, logged as warnings
- **Signal parsing errors:** Silent fallthrough (returns None), signal ignored

**Stale Signal Detection:**

- In `trade_manager._handle_open()`, check current price vs entry zone
- If price already past TP1: notify stale skip to #alerts, skip execution
- Prevents trades on signals that are already partially filled

## Cross-Cutting Concerns

**Logging:**
- Framework: Python `logging` module
- Configuration: `bot.py:17-21`, all modules use `logger = logging.getLogger(__name__)`
- Levels: INFO for milestones (signal parsed, trade executed), DEBUG for stagger delays, WARNING for connection drops, ERROR for exceptions

**Validation:**
- Signal parsing: Regex patterns validate format, symbol mapping validates symbol
- Zone entry: Prices must be in valid range, low < high after normalization
- SL/TP: Must not be equal, direction-aware (BUY SL below entry, SELL SL above)
- Lot size: Clamped to [0.01, max_lot_size], risk % >= 0.1%

**Authentication:**
- Telegram: StringSession (persistent login, survives container restarts)
- Dashboard: HTTP Basic auth with secrets comparison (timing-safe)
- Discord webhooks: URL-based auth (webhook is the secret)
- MT5 accounts: login/password loaded from env vars (password_env field in accounts.json)

**Rate Limiting & Throttling:**
- Discord: Webhook rate limits (100 requests per 60s) — retries with backoff
- MT5 server messages: Daily limit per account (max_daily_server_messages, default 500)
- Trade frequency: Daily limit per account (max_daily_trades_per_account, default 30)
- Stagger delays: Random 1-5s between accounts (configurable via config)

---

*Architecture analysis: 2026-03-19*
