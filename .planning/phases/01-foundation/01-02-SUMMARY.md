---
phase: 01-foundation
plan: 02
subsystem: database
tags: [asyncpg, postgresql, connection-pool, sql-injection, utc-timestamps, security]

# Dependency graph
requires:
  - phase: 01-foundation/01
    provides: "config.py with database_url field, asyncpg in requirements.txt"
provides:
  - "Complete asyncpg-based db.py with connection pool, PostgreSQL DDL, all functions migrated"
  - "Async _setup_trading() in bot.py wired to await db.init_db(database_url)"
  - "Field name whitelist preventing SQL injection on dynamic column names"
  - "UTC-consistent daily stat dates via _utc_today() helper"
  - "Password dict clearing after connector creation"
affects: [01-03, database, dashboard, trade_manager, executor]

# Tech tracking
tech-stack:
  added: []
  patterns: [asyncpg connection pool, fetchval for RETURNING id, frozenset field whitelist, _utc_today helper]

key-files:
  created: []
  modified: [db.py, bot.py]

key-decisions:
  - "Pool sizing min=2, max=5 -- sufficient for ~30 trades/day bot with occasional bursts; avoids wasting shared PG connections"
  - "log_signal passes explicit timestamp via $1 parameter instead of relying on DEFAULT NOW() -- consistent with original code pattern"
  - "log_pending_order accepts both str and datetime for expires_at -- backward compatible with callers passing ISO strings"

patterns-established:
  - "asyncpg pool pattern: _pool.fetchval() for INSERT RETURNING, _pool.fetch() for SELECT lists, _pool.execute() for UPDATE/DELETE"
  - "Field whitelist: _validate_field() with frozenset lookup before any dynamic SQL column injection"
  - "UTC dates: _utc_today() helper used everywhere instead of date.today()"

requirements-completed: [DB-01, DB-02, SEC-01]

# Metrics
duration: 2min
completed: 2026-03-22
---

# Phase 01 Plan 02: Database Migration Summary

**Full asyncpg rewrite of db.py with PostgreSQL DDL, field whitelist injection prevention, UTC timestamps, and async bot.py wiring**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-22T10:42:33Z
- **Completed:** 2026-03-22T10:44:29Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- db.py completely rewritten from sqlite3 to asyncpg connection pool with PostgreSQL-native DDL (TIMESTAMPTZ, SERIAL PRIMARY KEY, BIGINT, DOUBLE PRECISION)
- All ~12 database functions migrated: fetchval for inserts, fetch for selects, execute for updates -- no sqlite3, no asyncio.Lock, no cursor.lastrowid
- SQL injection prevention via frozenset field whitelist on dynamic column names in increment_daily_stat and get_daily_stat
- UTC-consistent daily stats using _utc_today() helper instead of date.today()
- bot.py _setup_trading() made async, wired to await db.init_db(settings.database_url), password dicts cleared after connector creation

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite db.py -- asyncpg connection pool with PostgreSQL DDL and all functions migrated** - `e94bce4` (feat)
2. **Task 2: Update bot.py -- async _setup_trading, database_url, password clearing** - `b94110a` (feat)

## Files Created/Modified
- `db.py` - Complete rewrite: asyncpg pool, PostgreSQL DDL, all functions migrated, field whitelist, UTC helper, close_db
- `bot.py` - async _setup_trading, await db.init_db(database_url), password dict clearing, await _setup_trading in main()

## Decisions Made
- Pool sizing (min=2, max=5): conservative for a single-process trading bot with ~30 trades/day; avoids wasting shared PostgreSQL connections on the VPS
- log_signal passes explicit `datetime.now(timezone.utc)` as `$1` parameter instead of relying solely on `DEFAULT NOW()` -- consistent with original code pattern where timestamp was explicitly provided
- log_pending_order accepts both `str` and `datetime` for `expires_at` parameter -- callers in trade_manager.py pass ISO string from `datetime.utcnow().isoformat()`, and asyncpg needs datetime objects, so we parse with `fromisoformat()` for backward compatibility

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required. The DATABASE_URL environment variable was already added to config.py in Plan 01.

## Next Phase Readiness
- db.py is fully migrated to asyncpg -- all consumers (trade_manager.py, executor.py, dashboard.py) call the same async function signatures
- bot.py is wired for async database initialization via database_url
- close_db() is available for future graceful shutdown implementation (Phase 2 or 3 scope)
- Pending order expires_at in trade_manager.py still uses `datetime.utcnow()` (deprecated) -- this is pre-existing and out of scope for this plan

## Self-Check: PASSED

All files verified present. All commit hashes found in git log.

---
*Phase: 01-foundation*
*Completed: 2026-03-22*
