# Phase 1: Foundation - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Security hardening and database migration from SQLite to PostgreSQL with UTC timestamps. The bot starts safely, stores data correctly, and has no credential or injection vulnerabilities.

Requirements: SEC-01, SEC-02, SEC-03, SEC-04, DB-01, DB-02, DB-04

</domain>

<decisions>
## Implementation Decisions

### Database migration (SQLite → PostgreSQL)
- **Migrate to PostgreSQL** instead of aiosqlite — user has an existing shared PostgreSQL instance on VPS at /home/murx/shared
- Use **asyncpg** as the async driver (fastest, built-in connection pooling)
- Connect via **DATABASE_URL** environment variable (standard connection string)
- **Fresh start** — create new PostgreSQL tables, no SQLite data migration needed
- Make `_setup_trading()` **async** to support async db initialization
- **Remove the global asyncio.Lock** entirely — PostgreSQL handles concurrency natively
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Database layer
- `db.py` — Current SQLite implementation with ~15 async functions, global lock, sync connection. All functions need asyncpg migration.
- `bot.py:43-57` — `_setup_trading()` calls `db.init_db()` synchronously. Must become async.

### Configuration
- `config.py` — Settings dataclass with `_req()` and `_opt()` helpers. Dashboard defaults at line 77-78 ("admin"/"changeme"). Env var loading at line 49-78.
- `.env.example` — Template for all required env vars. Needs DATABASE_URL added.

### Concerns driving this phase
- `.planning/codebase/CONCERNS.md` — Full list of issues being addressed
- `.planning/research/PITFALLS.md` — Migration pitfalls and prevention strategies
- `.planning/research/STACK.md` — Stack recommendations (note: recommends aiosqlite; we're going PostgreSQL instead)

### VPS infrastructure
- Shared PostgreSQL at `/home/murx/shared` — bot joins shared Docker network to access postgres

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `config.py:Settings` dataclass — extend with DATABASE_URL field
- `config.py:_req()/_opt()` helpers — reuse for new env var validation
- `models.py` — dataclasses (SignalAction, AccountConfig, etc.) are database-agnostic, no changes needed

### Established Patterns
- All db functions are already `async def` — migration to asyncpg is mostly changing the connection/cursor internals
- Parameterized queries already used for values (`?` placeholders → `$1, $2, ...`)
- Global module-level state (`_db`, `_lock`, `_DB_PATH`) — replace with connection pool

### Integration Points
- `bot.py:57` — `db.init_db()` call must become `await db.init_db()`
- `trade_manager.py` — imports and calls db functions directly (db.log_signal, db.log_trade, etc.)
- `dashboard.py` — reads from db for history/stats display
- `executor.py` — calls db functions for pending order management

</code_context>

<specifics>
## Specific Ideas

- User has existing shared PostgreSQL on VPS — don't create a new database service, connect to existing one
- Docker compose must join the shared services network (handled in Phase 3, INFRA-03/INFRA-04)
- DATABASE_URL is the standard connection pattern already used by user's other apps

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-03-22*
