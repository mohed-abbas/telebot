# Architecture Research

**Domain:** Trading bot hardening (brownfield)
**Researched:** 2026-03-19
**Confidence:** HIGH

## Standard Architecture

### Hardening Change Map

```
┌─────────────────────────────────────────────────────────────┐
│                     EXISTING LAYERS                          │
├─────────────────────────────────────────────────────────────┤
│  ┌───────────┐  ┌───────────┐  ┌───────────┐               │
│  │ Telegram   │  │ Signal    │  │ Dashboard │               │
│  │ Listener   │  │ Parser    │  │ (FastAPI) │               │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘               │
│        │              │              │                      │
│  ┌─────┴──────────────┴──────────────┴─────┐                │
│  │          Trade Execution Layer            │                │
│  │  (executor.py + trade_manager.py)         │                │
│  └─────────────────┬─────────────────────────┘                │
│                    │                                         │
│  ┌─────────────────┴─────────────────────────┐                │
│  │        MT5 Connection Layer                │                │
│  │  (mt5_connector.py)                        │                │
│  └─────────────────┬─────────────────────────┘                │
│                    │                                         │
│  ┌─────────────────┴─────────────────────────┐                │
│  │        Database Layer (db.py)              │                │
│  └───────────────────────────────────────────┘                │
├─────────────────────────────────────────────────────────────┤
│                     CHANGES BY LAYER                         │
├─────────────────────────────────────────────────────────────┤
│  Database:     sqlite3 → aiosqlite, field whitelisting       │
│  MT5 Layer:    + heartbeat, + auto-reconnect, + reconcile    │
│  Execution:    + zone fix, + order race fix, + stale check   │
│  Dashboard:    + kill switch, + limit status, + validation   │
│  Config:       + env validation, + magic number config       │
│  Security:     - default creds, + password clearing          │
│  Testing:      + dev deps, + MT5 mocks, + integration tests │
└─────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Changes Needed |
|-----------|----------------|----------------|
| `db.py` | All database operations | Migrate to aiosqlite, add field whitelisting, UTC timestamps |
| `mt5_connector.py` | MT5 broker communication | Add heartbeat, auto-reconnect, position reconciliation |
| `trade_manager.py` | Trade logic per account | Fix zone SELL logic, pending order race, stale signal check, SL/TP validation |
| `executor.py` | Multi-account orchestration | Integrate reconnection awareness, expose kill switch |
| `dashboard.py` | Web monitoring UI | Add kill switch endpoint, daily limit display |
| `config.py` | Configuration loading | Add env validation, move magic number, remove default creds |
| `bot.py` | Application entry point | Wire reconnection, startup validation |
| `signal_parser.py` | Signal extraction | Add failure logging, optimize symbol lookup |

## Recommended Build Order

The hardening changes have dependencies that dictate ordering:

### Phase 1: Foundation (database + security + config)
**Must come first** — other changes depend on stable database and validated config.

1. **aiosqlite migration** — all database operations become truly async
2. **SQL field whitelisting** — prevent injection vectors
3. **Env validation + fail-fast** — catch config errors at startup
4. **Remove default credentials** — security baseline
5. **Magic number to config** — minor config improvement
6. **Password memory clearing** — defense in depth
7. **UTC timestamp standardization** — consistent time handling

### Phase 2: Reliability (connection + execution fixes)
**Depends on Phase 1** — needs stable database for logging reconnection events.

1. **MT5 heartbeat + auto-reconnect** — core reliability
2. **Position reconciliation after reconnect** — correctness after reconnect
3. **Pending order cleanup race fix** — verify MT5 state before cancel
4. **Zone-based SELL boundary fix** — extract into testable functions
5. **Stale signal double-check** — re-verify before execution
6. **SL/TP modification validation** — direction-aware validation
7. **Emergency kill switch** — dashboard endpoint to close all positions

### Phase 3: Observability (logging + monitoring + dashboard)
**Depends on Phase 2** — monitors the reliability features.

1. **Signal parser failure logging** — track why signals are missed
2. **Daily limit warnings + dashboard status** — capacity awareness
3. **Server message limit documentation** — clarify what counts
4. **Dashboard N+1 fix** — batch position queries

### Phase 4: Test coverage
**Can partially overlap with earlier phases** but benefits from all fixes being in place.

1. **Test infrastructure** (requirements-dev.txt, pytest config)
2. **MT5 connector tests** with mocks
3. **Trade manager integration tests**
4. **Signal parser regression tests** with real-world data
5. **Async concurrency tests** (race conditions, lock contention)

### Phase 5: Maintenance + optimization
**After all critical fixes** — lower priority improvements.

1. **SQLite database archival and cleanup**
2. **Symbol map regex optimization**
3. **Signal accuracy tracking**
4. **Telethon version evaluation** (assess 2.x readiness)
5. **Production ASGI improvements** (uvicorn lifecycle)

## Architectural Patterns

### Pattern 1: aiosqlite Migration (Replace-in-Place)

**What:** Replace all `sqlite3.connect()` + `asyncio.Lock` with `aiosqlite.connect()` async context manager
**When to use:** When migrating sync sqlite3 to async
**Trade-offs:** Minimal API change (cursor.execute → await cursor.execute), but must update every db function

```python
# Before (current)
conn = sqlite3.connect("data/telebot.db", check_same_thread=False)
_lock = asyncio.Lock()

async def log_signal(signal):
    async with _lock:
        conn.execute("INSERT INTO signals ...", params)
        conn.commit()

# After (aiosqlite)
async def get_connection():
    return await aiosqlite.connect("data/telebot.db")

async def log_signal(signal):
    async with aiosqlite.connect("data/telebot.db") as db:
        await db.execute("INSERT INTO signals ...", params)
        await db.commit()
```

### Pattern 2: Heartbeat + Auto-Reconnect

**What:** Periodic health check on MT5 connections with automatic recovery
**When to use:** Any long-lived external connection
**Trade-offs:** Adds background task complexity, must handle partial reconnection state

```python
async def _heartbeat_loop(self, interval=30):
    while True:
        await asyncio.sleep(interval)
        if not await self._ping():
            await self._reconnect_with_backoff()
            await self._reconcile_positions()
```

### Pattern 3: Field Name Whitelisting

**What:** Validate dynamic SQL identifiers against an explicit allowlist
**When to use:** Any dynamic column/table names in SQL
**Trade-offs:** Must update allowlist when adding new fields

```python
ALLOWED_FIELDS = {"trades_count", "server_messages", "signals_count"}

def _validate_field(field: str) -> str:
    if field not in ALLOWED_FIELDS:
        raise ValueError(f"Invalid field name: {field}")
    return field
```

## Data Flow

### Reconnection Flow (New)

```
[Heartbeat Timer]
    ↓ (every 30s)
[Ping MT5] → success → [Continue]
    ↓ fail
[Mark disconnected] → [Notify Discord #alerts]
    ↓
[Reconnect with backoff] → fail → [Retry (1s, 2s, 4s, 8s...)]
    ↓ success
[Full position sync from MT5]
    ↓
[Reconcile with database state]
    ↓
[Mark connected] → [Notify Discord #alerts "restored"]
```

### Kill Switch Flow (New)

```
[Dashboard: Press Kill Switch]
    ↓
[POST /emergency-close]
    ↓
[For each account:]
    ↓
[Close all open positions]
    ↓
[Cancel all pending orders]
    ↓
[Set executor.trading_paused = True]
    ↓
[Log to audit trail]
    ↓
[Notify Discord #alerts]
    ↓
[Dashboard shows "TRADING PAUSED - Re-enable required"]
```

## Anti-Patterns

### Anti-Pattern 1: Big Bang Migration

**What people do:** Rewrite all db.py functions at once, test nothing until done
**Why it's wrong:** Hard to isolate which change broke what; merge conflicts if other work happening
**Do this instead:** Migrate one function at a time, test each, commit each

### Anti-Pattern 2: Reconnect Without Reconcile

**What people do:** Reconnect to MT5 and resume as if nothing happened
**Why it's wrong:** Positions may have been opened/closed while disconnected; bot state diverges from reality
**Do this instead:** Always full position sync after reconnect before accepting new signals

### Anti-Pattern 3: Testing Against Live MT5

**What people do:** Run tests against actual MT5 to "be realistic"
**Why it's wrong:** Flaky tests, real money risk, can't test edge cases (disconnection mid-trade)
**Do this instead:** Mock MT5 connector for unit tests; use dry-run mode for integration; live only for manual validation

## Sources

- aiosqlite documentation — connection lifecycle, transaction patterns
- Python asyncio — task management, graceful shutdown
- FastAPI — lifecycle events, background tasks
- MT5 protocol — reconnection semantics, position query API

---
*Architecture research for: trading bot hardening*
*Researched: 2026-03-19*
