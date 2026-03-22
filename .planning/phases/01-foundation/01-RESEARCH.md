# Phase 1: Foundation - Research

**Researched:** 2026-03-22
**Domain:** Security hardening + SQLite-to-PostgreSQL migration (asyncpg)
**Confidence:** HIGH

## Summary

Phase 1 migrates the trading bot's database layer from synchronous SQLite (with `check_same_thread=False` and a global `asyncio.Lock`) to PostgreSQL via asyncpg with connection pooling. Simultaneously, it hardens startup validation, removes default dashboard credentials, clears MT5 passwords from memory after initialization, enforces UTC timestamps everywhere, and whitelists dynamic SQL field names.

The user has an existing shared PostgreSQL instance on their VPS. The bot connects via `DATABASE_URL` environment variable. This is a fresh schema start -- no data migration from SQLite is needed. All ~15 database functions in `db.py` must be migrated at once (no mixed sync/async state).

asyncpg 0.31.0 is the current release and the right choice -- it is 5x faster than psycopg3 in benchmarks, supports native connection pooling via `create_pool()`, uses `$1, $2, ...` parameter syntax, and returns `Record` objects that support dict-like access (replacing `sqlite3.Row`).

**Primary recommendation:** Replace the entire `db.py` module to use an asyncpg connection pool, convert all SQL to PostgreSQL dialect, make `init_db()` async, and harden `config.py` with strict validation and no default credentials.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Migrate to PostgreSQL** instead of aiosqlite -- user has existing shared PostgreSQL on VPS at /home/murx/shared
- Use **asyncpg** as the async driver (fastest, built-in connection pooling)
- Connect via **DATABASE_URL** environment variable (standard connection string)
- **Fresh start** -- create new PostgreSQL tables, no SQLite data migration needed
- Make `_setup_trading()` **async** to support async db initialization
- **Remove the global asyncio.Lock** entirely -- PostgreSQL handles concurrency natively
- Migrate **all ~15 db functions at once** in a single commit (no mixed sync/async state)
- Replace `sqlite3.Row` with asyncpg Record objects
- Replace SQLite-specific `PRAGMA journal_mode=WAL` with PostgreSQL defaults
- Replace `?` parameter placeholders with `$1, $2, ...` (asyncpg syntax)
- Replace `INTEGER PRIMARY KEY AUTOINCREMENT` with `SERIAL PRIMARY KEY`
- Replace `ON CONFLICT` syntax with PostgreSQL `ON CONFLICT ... DO UPDATE SET`

### Claude's Discretion
- Startup validation: strictness level, format checks, connectivity pre-check
- Password & credential policy: how to handle missing DASHBOARD_PASS, MT5 password clearing timing
- UTC migration: whether daily limit reset timezone is configurable or UTC-only
- SQL field whitelisting implementation approach (frozenset, enum, etc.)
- Connection pool sizing (asyncpg pool_min_size, pool_max_size)
- Whether to keep aiosqlite as a fallback or remove it from requirements.txt
- Schema details (indexes, constraints beyond what SQLite had)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SEC-01 | SQL field names in dynamic queries validated against explicit whitelist | Whitelist pattern using `frozenset` + validation function; see Architecture Patterns |
| SEC-02 | Dashboard requires explicitly configured credentials; no hardcoded defaults; startup fails if DASHBOARD_PASS not set | Make DASHBOARD_PASS a required env var via `_req()`; remove "changeme" default |
| SEC-03 | All required env vars validated at startup with format checks; bot fails fast with clear messages | Enhanced `_req()` with format validators; TG_API_ID numeric, TG_SESSION format, DATABASE_URL format |
| SEC-04 | MT5 passwords cleared from memory after initialization; never logged | Clear `self.password` after `connect()`, clear `_password` from account dicts; add log filter |
| DB-01 | All db operations use asyncpg (PostgreSQL); no sqlite3 check_same_thread; no global asyncio.Lock | Full asyncpg pool migration; see Standard Stack and Architecture Patterns |
| DB-02 | All timestamps UTC; daily_stats dates use UTC date; timezone conversion only at display | Use `TIMESTAMPTZ` columns; `datetime.now(timezone.utc)` everywhere; `date.today()` replaced with UTC date |
| DB-04 | MT5 magic number loaded from configuration instead of hardcoded | Add `MT5_MAGIC_NUMBER` env var with `_opt()` default |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | 0.31.0 | Async PostgreSQL driver | Fastest Python PG driver (5x psycopg3); native connection pooling; `$1` params prevent injection; `Record` objects work like dicts |
| python-dotenv | 1.0.1 | Env var loading | Already in use; loads .env before config validation |

### Supporting (already in project)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| fastapi | 0.115.0 | Dashboard web framework | Already used for dashboard; no changes needed this phase |
| uvicorn[standard] | 0.32.0 | ASGI server | Already used; no changes needed this phase |

### Remove
| Library | Reason |
|---------|--------|
| aiosqlite | 0.20.0 in requirements.txt but never used; no longer needed with PostgreSQL migration |
| sqlite3 (stdlib) | All imports removed from db.py |

**Installation change:**
```bash
# In requirements.txt, replace:
#   aiosqlite==0.20.0
# With:
asyncpg==0.31.0
```

**Version verification:** asyncpg 0.31.0 confirmed as latest via `pip index versions asyncpg` on 2026-03-22. Requires Python 3.9+; project uses Python 3.12 (compatible). Supports PostgreSQL 9.5 through 18.

## Architecture Patterns

### Recommended Changes to Project Structure
```
telebot/
├── config.py          # MODIFIED: strict validation, no defaults for DASHBOARD_PASS, add DATABASE_URL
├── db.py              # REWRITTEN: asyncpg pool, PostgreSQL DDL, all functions async with pool
├── bot.py             # MODIFIED: _setup_trading() becomes async, await db.init_db()
├── mt5_connector.py   # MODIFIED: clear password after connect()
├── .env.example       # MODIFIED: add DATABASE_URL, remove DB_PATH, update DASHBOARD_PASS comment
├── requirements.txt   # MODIFIED: asyncpg replaces aiosqlite
├── trade_manager.py   # NO CHANGES (db function signatures unchanged)
├── dashboard.py       # NO CHANGES (db function signatures unchanged)
├── executor.py        # NO CHANGES (db function signatures unchanged)
└── models.py          # NO CHANGES (database-agnostic dataclasses)
```

### Pattern 1: asyncpg Connection Pool Module

**What:** Replace the global `_db` sqlite3 connection and `_lock` with an asyncpg connection pool.
**When to use:** All database access throughout the application.

```python
# db.py - new module-level state
import asyncpg
from typing import Optional

_pool: Optional[asyncpg.Pool] = None

async def init_db(database_url: str) -> None:
    """Initialize the connection pool and create tables."""
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=2,
        max_size=5,
        command_timeout=30,
    )
    await _create_tables()
    logger.info("Database initialized (PostgreSQL pool: min=2, max=5)")

async def close_db() -> None:
    """Close the connection pool (call on shutdown)."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
```

**Pool sizing rationale (Claude's Discretion):** `min_size=2, max_size=5`. This bot processes ~30 trades/day with occasional bursts. Two connections handle normal load (one read, one write). Five handles dashboard + signal burst. The default of 10 is overkill for a single-process trading bot and wastes shared PostgreSQL connections.

### Pattern 2: Query Migration (SQLite to PostgreSQL)

**What:** Convert all SQL queries from SQLite dialect to PostgreSQL.
**Key differences:**

| SQLite | PostgreSQL (asyncpg) |
|--------|---------------------|
| `?` parameters | `$1, $2, $3` positional |
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` |
| `executescript("""...""")` | Separate `await conn.execute()` per DDL statement |
| `cursor.lastrowid` | `RETURNING id` clause in INSERT |
| `_db.execute(...).fetchone()` | `await _pool.fetchrow(...)` |
| `_db.execute(...).fetchall()` | `await _pool.fetch(...)` |
| `_db.execute(...)` (write) | `await _pool.execute(...)` |
| `dict(row)` from `sqlite3.Row` | `dict(row)` from `asyncpg.Record` |
| `_db.commit()` | Auto-commit (or explicit transaction) |
| `ON CONFLICT(date, account_name) DO UPDATE SET {field} = {field} + ?` | `ON CONFLICT(date, account_name) DO UPDATE SET {field} = daily_stats.{field} + $3` |

**Critical: asyncpg does not support multi-statement execute.** Each `CREATE TABLE` must be a separate `await conn.execute()` call. Use `pool.acquire()` to get a connection, then execute each DDL statement sequentially.

```python
async def _create_tables() -> None:
    """Create tables if they don't exist. Each DDL is a separate execute."""
    async with _pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                raw_text TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                symbol TEXT,
                direction TEXT,
                entry_zone_low DOUBLE PRECISION,
                entry_zone_high DOUBLE PRECISION,
                sl DOUBLE PRECISION,
                tp DOUBLE PRECISION,
                action_taken TEXT NOT NULL,
                details TEXT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                signal_id INTEGER REFERENCES signals(id),
                timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                account_name TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price DOUBLE PRECISION,
                sl DOUBLE PRECISION,
                tp DOUBLE PRECISION,
                lot_size DOUBLE PRECISION,
                ticket BIGINT,
                status TEXT NOT NULL,
                pnl DOUBLE PRECISION DEFAULT 0.0,
                close_price DOUBLE PRECISION,
                close_time TIMESTAMPTZ,
                raw_signal TEXT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL,
                account_name TEXT NOT NULL,
                trades_count INTEGER DEFAULT 0,
                server_messages INTEGER DEFAULT 0,
                daily_pnl DOUBLE PRECISION DEFAULT 0.0,
                starting_balance DOUBLE PRECISION DEFAULT 0.0,
                UNIQUE(date, account_name)
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS pending_orders (
                id SERIAL PRIMARY KEY,
                signal_id INTEGER REFERENCES signals(id),
                account_name TEXT NOT NULL,
                ticket BIGINT NOT NULL,
                symbol TEXT NOT NULL,
                order_type TEXT NOT NULL,
                volume DOUBLE PRECISION,
                price DOUBLE PRECISION,
                sl DOUBLE PRECISION,
                tp DOUBLE PRECISION,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMPTZ NOT NULL,
                status TEXT DEFAULT 'active'
            )
        ''')
```

**Schema notes:**
- `REAL` replaced with `DOUBLE PRECISION` (PostgreSQL equivalent of SQLite's REAL; 8-byte float)
- `TEXT` timestamps replaced with `TIMESTAMPTZ` (native timezone-aware timestamps; stored as UTC internally)
- `INTEGER` for MT5 tickets replaced with `BIGINT` (MT5 tickets can exceed 32-bit range)
- `DATE` type used for daily_stats.date (proper date type vs TEXT ISO string)
- Added `DEFAULT NOW()` to timestamp columns for safety

### Pattern 3: INSERT with RETURNING (replace cursor.lastrowid)

**What:** asyncpg does not have `cursor.lastrowid`. Use `RETURNING id` with `fetchval()`.

```python
async def log_signal(
    raw_text: str,
    signal_type: str,
    action_taken: str,
    symbol: str = "",
    direction: str = "",
    entry_zone_low: float = 0.0,
    entry_zone_high: float = 0.0,
    sl: float = 0.0,
    tp: float = 0.0,
    details: str = "",
) -> int:
    """Log a parsed signal. Returns the signal ID."""
    return await _pool.fetchval(
        """INSERT INTO signals
           (timestamp, raw_text, signal_type, symbol, direction,
            entry_zone_low, entry_zone_high, sl, tp, action_taken, details)
           VALUES (NOW(), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
           RETURNING id""",
        raw_text, signal_type, symbol, direction,
        entry_zone_low, entry_zone_high, sl, tp,
        action_taken, details,
    )
```

### Pattern 4: SQL Field Name Whitelist (SEC-01)

**What:** Validate dynamic field names against an explicit allowlist before use in SQL.
**Recommendation (Claude's Discretion):** Use a `frozenset` -- simple, immutable, O(1) lookup. No need for an enum since the field names are just strings used in one function.

```python
# db.py
_DAILY_STAT_FIELDS: frozenset[str] = frozenset({
    "trades_count",
    "server_messages",
    "daily_pnl",
    "starting_balance",
})

def _validate_field(field: str) -> str:
    """Validate a field name against the whitelist. Raises ValueError if invalid."""
    if field not in _DAILY_STAT_FIELDS:
        raise ValueError(f"Invalid daily_stat field: {field!r}")
    return field

async def increment_daily_stat(account_name: str, field: str, amount: int = 1) -> None:
    """Increment a daily stat counter."""
    safe_field = _validate_field(field)
    today = datetime.now(timezone.utc).date()
    await _pool.execute(
        f"""INSERT INTO daily_stats (date, account_name, {safe_field})
            VALUES ($1, $2, $3)
            ON CONFLICT(date, account_name)
            DO UPDATE SET {safe_field} = daily_stats.{safe_field} + $3""",
        today, account_name, amount,
    )
```

**Note on PostgreSQL ON CONFLICT:** The `EXCLUDED` pseudo-table references the proposed INSERT values. However, for incrementing, we reference the existing row with `daily_stats.{field} + $3`. Column references in `DO UPDATE SET` must NOT be prefixed with the table name on the left side of `=` (PostgreSQL constraint).

### Pattern 5: Startup Validation (SEC-02, SEC-03)

**What:** Enhanced env var validation with format checks and no default credentials.

```python
# config.py - enhanced validation
def _load_settings() -> Settings:
    def _req(key: str, validator=None) -> str:
        val = environ.get(key)
        if not val:
            raise SystemExit(f"FATAL: Missing required env var: {key}")
        if validator and not validator(val):
            raise SystemExit(f"FATAL: Invalid format for {key}")
        return val

    def _opt(key: str, default: str = "") -> str:
        return environ.get(key, default)

    def _is_numeric(v: str) -> bool:
        return v.isdigit()

    def _is_pg_url(v: str) -> bool:
        return v.startswith(("postgres://", "postgresql://"))

    return Settings(
        tg_api_id=int(_req("TG_API_ID", validator=_is_numeric)),
        # ... other fields ...
        database_url=_req("DATABASE_URL", validator=_is_pg_url),
        # DASHBOARD_PASS is now required -- no default
        dashboard_pass=_req("DASHBOARD_PASS"),
    )
```

**Recommendation (Claude's Discretion):**
- `DASHBOARD_PASS` becomes a required env var (via `_req()`). If not set, bot refuses to start. This is simpler and more secure than checking for "changeme" at runtime.
- `DASHBOARD_USER` can remain optional with default "admin" (username is not a security secret).
- Format validators should be simple and not leak information -- just check basic shape (numeric, URL prefix), not detailed format.
- Remove `db_path` field from Settings; replace with `database_url`.

### Pattern 6: MT5 Password Clearing (SEC-04)

**What:** Clear password from memory after MT5 connection is established.

```python
# mt5_connector.py - in MT5Connector base class
async def connect(self) -> bool:
    raise NotImplementedError

def _clear_password(self) -> None:
    """Clear password from memory after successful connection."""
    self.password = ""

# In MT5LinuxConnector.connect():
async def connect(self) -> bool:
    try:
        # ... rpyc connection setup ...
        result = self._mt5.login(login=self.login, password=self.password, server=self.server)
        if result:
            self._connected = True
            self._clear_password()  # Clear after successful auth
            return True
        return False
    except Exception:
        # Don't clear on failure -- may need to retry
        raise

# In DryRunConnector.connect():
async def connect(self) -> bool:
    logger.info("[DRY-RUN] %s: Connected", self.account_name)
    self._connected = True
    self._clear_password()  # Clear even in dry-run for consistency
    return True
```

**Also clear `_password` from account config dicts in bot.py after all connectors are created:**
```python
# bot.py - after connector creation loop
for raw in accts_raw:
    raw.pop("_password", None)
```

**Log safety:** Add a check that no logger formats include password fields. Python logging with `%s` formatting is safe as long as the password variable is never passed to a logger call. Verify no `logger.info/debug/warning` calls include `password` anywhere in the codebase.

### Pattern 7: UTC Timestamp Consistency (DB-02)

**What:** All timestamps stored as UTC. Daily stats use UTC date.

```python
# Replace date.today() with UTC-aware version everywhere:
from datetime import datetime, date, timezone

def _utc_today() -> date:
    """Get today's date in UTC (not local timezone)."""
    return datetime.now(timezone.utc).date()

# In increment_daily_stat and get_daily_stat:
today = _utc_today()
```

**Recommendation (Claude's Discretion):** Daily limit reset should be UTC-only (not configurable per timezone). Rationale:
1. The bot trades forex which operates on UTC-aligned sessions
2. Making it configurable adds complexity for a single-user bot
3. The user's `TIMEZONE` config setting is already used for display formatting only
4. Document that daily limits reset at 00:00 UTC

### Anti-Patterns to Avoid
- **Multi-statement `execute()`:** asyncpg raises `PostgresSyntaxError: cannot insert multiple commands into a prepared statement` when using parameterized multi-statement queries. Execute each DDL separately.
- **Forgetting `RETURNING id`:** asyncpg has no `cursor.lastrowid`. Every INSERT that needs the new ID must include `RETURNING id` and use `fetchval()`.
- **Using `date.today()` for daily stats:** Returns local date, not UTC. Always use `datetime.now(timezone.utc).date()`.
- **Table name prefix in `DO UPDATE SET`:** PostgreSQL does not allow `SET table.col = ...` in upsert -- use bare column name on left side.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Connection pooling | Custom connection manager | `asyncpg.create_pool()` | Built-in, handles min/max sizing, connection health, timeouts |
| Parameter escaping | String formatting for SQL values | `$1, $2, ...` positional params | asyncpg handles escaping; prevents SQL injection |
| Transaction management | Manual BEGIN/COMMIT | `async with conn.transaction():` | Auto-rollback on exception; supports savepoints |
| Timestamp generation | `datetime.now().isoformat()` strings | `TIMESTAMPTZ` column + `NOW()` default | PostgreSQL handles timezone conversion; asyncpg returns proper datetime objects |
| Env var validation framework | Custom schema validator class | Simple validators in `_req()` helper | Keep it minimal; pydantic-settings is overkill for ~15 vars |

**Key insight:** asyncpg handles the three hardest parts of database access -- connection lifecycle, parameter escaping, and type conversion. Let it do its job. The only custom code needed is the field name whitelist (because column names cannot be parameterized in any SQL driver).

## Common Pitfalls

### Pitfall 1: asyncpg Requires Separate DDL Executions
**What goes wrong:** Copying the SQLite `executescript()` pattern and putting all CREATE TABLE statements in one `execute()` call. asyncpg raises `PostgresSyntaxError`.
**Why it happens:** SQLite's `executescript()` splits on semicolons. asyncpg uses prepared statements which only support a single command.
**How to avoid:** Execute each `CREATE TABLE IF NOT EXISTS` as a separate `await conn.execute()` call within a single acquired connection.
**Warning signs:** `cannot insert multiple commands into a prepared statement` error at startup.

### Pitfall 2: Missing RETURNING Clause
**What goes wrong:** `log_signal()` and `log_trade()` return `None` instead of the new row ID because `pool.execute()` returns a status string, not a cursor.
**Why it happens:** SQLite pattern of `cursor.lastrowid` doesn't exist in asyncpg.
**How to avoid:** Use `pool.fetchval('INSERT ... RETURNING id', ...)` for every INSERT that needs the ID back.
**Warning signs:** `TypeError: cannot unpack non-integer` or signal_id is None in trade records.

### Pitfall 3: Daily Stat Date Shifts to UTC
**What goes wrong:** `date.today()` returns local date (e.g., Europe/Berlin = UTC+1/+2). Switching to UTC shifts daily limit reset time. User may hit limit earlier/later than expected.
**Why it happens:** `date.today()` uses OS local time. `datetime.now(timezone.utc).date()` uses UTC.
**How to avoid:** Document that daily limits reset at 00:00 UTC. Use `_utc_today()` helper consistently. Since this is a fresh schema start, no historical data needs converting.
**Warning signs:** Daily trade count seems wrong around midnight local time.

### Pitfall 4: asyncpg Record vs dict
**What goes wrong:** Code that does `row["field"]` works (asyncpg Records support dict-like access), but code that does `row.field` (attribute access) fails -- asyncpg Records don't support attribute access.
**Why it happens:** `sqlite3.Row` and asyncpg `Record` have similar but not identical APIs. Both support `row["field"]` and `dict(row)`, but neither supports `row.field`.
**How to avoid:** The existing code uses `dict(row)` to convert rows, which works identically with asyncpg Records. Keep this pattern.
**Warning signs:** `AttributeError` on Record objects.

### Pitfall 5: Pool Exhaustion on Startup
**What goes wrong:** `init_db()` acquires a connection for DDL, and if `min_size=1` and another startup task also needs the pool, it deadlocks.
**Why it happens:** Pool initialization with `min_size` connections happens in `create_pool()`. If DDL takes too long and something else tries to acquire, pool blocks.
**How to avoid:** Use `min_size=2` (our recommendation). DDL runs on one connection; the second is available for any concurrent startup task.
**Warning signs:** Startup hangs after "Database initialized" log message.

### Pitfall 6: ON CONFLICT Syntax Difference
**What goes wrong:** SQLite's `ON CONFLICT(date, account_name) DO UPDATE SET field = field + ?` doesn't work in PostgreSQL because unqualified column `field` in the `SET` expression is ambiguous.
**Why it happens:** PostgreSQL requires qualifying the column reference in the expression (right side of `=`) with the table name: `daily_stats.field + $3`.
**How to avoid:** Use `daily_stats.{safe_field} + $3` in the SET expression. Left side of `=` must NOT have table prefix.
**Warning signs:** `ambiguous column reference` error on upsert.

## Code Examples

### Complete Migrated Function: increment_daily_stat
```python
# Source: asyncpg docs + PostgreSQL ON CONFLICT docs
_DAILY_STAT_FIELDS: frozenset[str] = frozenset({
    "trades_count", "server_messages", "daily_pnl", "starting_balance",
})

def _validate_field(field: str) -> str:
    if field not in _DAILY_STAT_FIELDS:
        raise ValueError(f"Invalid daily_stat field: {field!r}")
    return field

async def increment_daily_stat(account_name: str, field: str, amount: int = 1) -> None:
    safe_field = _validate_field(field)
    today = datetime.now(timezone.utc).date()
    await _pool.execute(
        f"""INSERT INTO daily_stats (date, account_name, {safe_field})
            VALUES ($1, $2, $3)
            ON CONFLICT(date, account_name)
            DO UPDATE SET {safe_field} = daily_stats.{safe_field} + $3""",
        today, account_name, amount,
    )
```

### Complete Migrated Function: get_expired_pending_orders
```python
# Source: asyncpg docs (pool.fetch returns list of Records)
async def get_expired_pending_orders() -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = await _pool.fetch(
        "SELECT * FROM pending_orders WHERE status='active' AND expires_at < $1",
        now,
    )
    return [dict(r) for r in rows]
```

### Connection Pool Lifecycle in bot.py
```python
# bot.py - _setup_trading becomes async
async def _setup_trading(http: httpx.AsyncClient):
    if not settings.trading_enabled:
        logger.info("Trading is DISABLED")
        return None, None

    import db
    # ... other imports ...

    # Initialize database (async now)
    await db.init_db(settings.database_url)

    # ... rest of setup ...
    # After creating all connectors, clear passwords from raw dicts:
    for raw in accts_raw:
        raw.pop("_password", None)

    return executor, notifier
```

### Startup Validation (config.py)
```python
# Key change: DASHBOARD_PASS is required, DATABASE_URL replaces DB_PATH
database_url=_req("DATABASE_URL", validator=_is_pg_url),
dashboard_pass=_req("DASHBOARD_PASS"),
# Remove: dashboard_pass=_opt("DASHBOARD_PASS", "changeme"),
# Remove: db_path=_opt("DB_PATH", "data/telebot.db"),
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `sqlite3` with `check_same_thread=False` | asyncpg connection pool | This phase | Eliminates thread safety issues; true async I/O |
| Global `asyncio.Lock` for all DB ops | No lock needed (pool manages concurrency) | This phase | Concurrent reads don't block; pool handles connection allocation |
| `?` parameter placeholders | `$1, $2, ...` positional params | This phase | asyncpg requirement; same injection safety |
| `cursor.lastrowid` | `RETURNING id` + `fetchval()` | This phase | PostgreSQL standard; more explicit |
| `TEXT` for timestamps | `TIMESTAMPTZ` | This phase | Native UTC storage; proper datetime handling |
| `date.today()` for daily stats | `datetime.now(timezone.utc).date()` | This phase | Consistent UTC; no local timezone leaks |
| Default "changeme" dashboard password | Required env var; startup fails if missing | This phase | No default credentials in code |

**Deprecated/outdated:**
- `aiosqlite`: Was recommended in original STACK.md research but superseded by user decision to go PostgreSQL. Remove from requirements.txt.
- `sqlite3` module: All imports removed. No fallback needed (fresh PostgreSQL start).

## Open Questions

1. **Graceful pool shutdown**
   - What we know: `asyncpg.Pool.close()` must be called on application shutdown to release connections cleanly.
   - What's unclear: The current bot.py does not have a structured shutdown sequence. The pool close needs to happen after all DB consumers stop.
   - Recommendation: Add `db.close_db()` call in bot shutdown. This is a minor concern -- the OS reclaims connections on process exit anyway, and PostgreSQL handles abandoned connections via `tcp_keepalives_idle`.

2. **asyncpg's DSN parsing with special characters in DATABASE_URL password**
   - What we know: asyncpg requires URL-encoded special characters in DSN passwords. Characters like `@`, `#`, `/` in passwords must be percent-encoded.
   - What's unclear: Whether the user's existing DATABASE_URL already handles this.
   - Recommendation: Document this in .env.example comments. If password contains special chars, use `urllib.parse.quote_plus()` or pass password as a separate kwarg.

3. **Indexes on frequently queried columns**
   - What we know: SQLite had no explicit indexes beyond primary keys. PostgreSQL benefits more from indexes on `trades(account_name)`, `daily_stats(date, account_name)`, `pending_orders(status, expires_at)`.
   - What's unclear: Exact query patterns for dashboard reads.
   - Recommendation: Add indexes on the UNIQUE constraint columns (daily_stats already gets one from UNIQUE). Add index on `pending_orders(status)` for expired order queries. Skip others until proven needed.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (no version pinned; not in requirements yet) |
| Config file | none -- no pytest.ini or pyproject.toml [tool.pytest] section exists |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v --tb=short` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SEC-01 | Field whitelist rejects invalid names | unit | `pytest tests/test_db.py::test_field_whitelist -x` | No -- Wave 0 |
| SEC-02 | Startup fails without DASHBOARD_PASS | unit | `pytest tests/test_config.py::test_dashboard_pass_required -x` | No -- Wave 0 |
| SEC-03 | Startup fails with invalid env var format | unit | `pytest tests/test_config.py::test_env_var_validation -x` | No -- Wave 0 |
| SEC-04 | Password cleared after connect | unit | `pytest tests/test_mt5_connector.py::test_password_cleared -x` | No -- Wave 0 |
| DB-01 | All queries use asyncpg pool | smoke | `pytest tests/test_db.py::test_basic_crud -x` | No -- Wave 0 |
| DB-02 | Timestamps are UTC | unit | `pytest tests/test_db.py::test_utc_timestamps -x` | No -- Wave 0 |
| DB-04 | Magic number from config | unit | `pytest tests/test_config.py::test_magic_number_config -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_db.py tests/test_config.py -x -q`
- **Per wave merge:** `pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/` directory -- does not exist (test files are in project root)
- [ ] `tests/test_db.py` -- covers SEC-01, DB-01, DB-02
- [ ] `tests/test_config.py` -- covers SEC-02, SEC-03, DB-04
- [ ] `tests/test_mt5_connector.py` -- covers SEC-04
- [ ] `tests/conftest.py` -- shared fixtures (test database URL, env var mocking)
- [ ] `pytest.ini` or `pyproject.toml` `[tool.pytest.ini_options]` -- asyncio_mode config
- [ ] Framework install: `pip install pytest pytest-asyncio pytest-mock` (not in requirements yet; testing is Phase 4 scope but we need minimal test infra for verification)

**Note:** Full test infrastructure is Phase 4 (TEST-01 through TEST-05). For Phase 1 verification, we need only minimal smoke tests that confirm the requirements are met. These can be simple scripts or minimal pytest tests.

## Sources

### Primary (HIGH confidence)
- [asyncpg API Reference](https://magicstack.github.io/asyncpg/current/api/index.html) -- pool creation, query methods, Record API, DSN format
- [asyncpg GitHub README](https://github.com/MagicStack/asyncpg) -- version 0.31.0 confirmed, Python 3.9+ requirement, PostgreSQL 9.5-18 support
- [PostgreSQL 18 INSERT docs](https://www.postgresql.org/docs/current/sql-insert.html) -- ON CONFLICT syntax, EXCLUDED pseudo-table
- [PostgreSQL datetime types](https://www.postgresql.org/docs/current/datatype-datetime.html) -- TIMESTAMPTZ behavior (stores UTC internally)
- Local codebase: `db.py`, `config.py`, `bot.py`, `mt5_connector.py` -- current implementation verified directly

### Secondary (MEDIUM confidence)
- [asyncpg issue #588](https://github.com/MagicStack/asyncpg/issues/588) -- confirmed multi-statement limitation
- [asyncpg issue #30](https://github.com/MagicStack/asyncpg/issues/30) -- confirmed "cannot insert multiple commands into prepared statement"
- [asyncpg issue #481](https://github.com/MagicStack/asyncpg/issues/481) -- TIMESTAMPTZ returns UTC in binary format
- PyPI `pip index versions asyncpg` -- 0.31.0 confirmed latest (2026-03-22)

### Tertiary (LOW confidence)
- Pool sizing recommendations (min=2, max=5) -- derived from general best practices and project load analysis, not benchmarked for this specific application

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- asyncpg 0.31.0 verified on PyPI, API verified from official docs
- Architecture: HIGH -- patterns verified from asyncpg docs and PostgreSQL docs; existing code analyzed directly
- Pitfalls: HIGH -- multi-statement limitation confirmed via GitHub issues; ON CONFLICT syntax confirmed via PG docs; daily stat UTC shift identified from codebase analysis
- Password clearing: MEDIUM -- best-effort approach in Python (GC may retain copies); meets SEC-04 requirement for "not present after initialization"

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable domain; asyncpg releases infrequently)
