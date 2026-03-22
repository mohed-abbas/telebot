# Roadmap: Telebot Hardening

## Overview

A systematic hardening pass on the existing Telegram-to-Discord trading relay bot. Work proceeds from the inside out: first secure and stabilize the data layer, then harden trading execution, then improve operational visibility, and finally lock in correctness with a test suite. Each phase leaves the bot deployable and no worse than before.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation** - Security hardening and database migration to PostgreSQL (asyncpg) with UTC timestamps
- [ ] **Phase 2: Reliability** - MT5 reconnection, kill switch, execution correctness, and position safety
- [ ] **Phase 3: Observability & Infrastructure** - Signal logging, dashboard fixes, DB archival, and deployment hardening
- [ ] **Phase 4: Testing** - Full test suite covering MT5 mocks, integration flows, async concurrency, and signal regression

## Phase Details

### Phase 1: Foundation
**Goal**: The bot starts safely, stores data correctly, and has no credential or injection vulnerabilities
**Depends on**: Nothing (first phase)
**Requirements**: SEC-01, SEC-02, SEC-03, SEC-04, DB-01, DB-02, DB-04
**Success Criteria** (what must be TRUE):
  1. Bot refuses to start if any required environment variable is missing or malformed, printing a clear error
  2. Dashboard returns 401 if DASHBOARD_PASS is not explicitly set in environment; no default credentials exist in code
  3. All database reads and writes use asyncpg (PostgreSQL); no sqlite3 check_same_thread=False appears anywhere; no global asyncio.Lock for DB
  4. MT5 passwords are not present in memory after initialization and never appear in logs
  5. All timestamps stored in the database are UTC; dynamic SQL field names are validated against an explicit whitelist
**Plans:** 3 plans

Plans:
- [x] 01-01-PLAN.md -- Config hardening: strict validation, DATABASE_URL, no default credentials, requirements update
- [x] 01-02-PLAN.md -- Database migration: full db.py rewrite to asyncpg with PostgreSQL DDL, bot.py async wiring
- [x] 01-03-PLAN.md -- MT5 password clearing: _clear_password after successful connect

### Phase 2: Reliability
**Goal**: The bot recovers from MT5 disconnections without losing state, and trading execution is correct and safe
**Depends on**: Phase 1
**Requirements**: REL-01, REL-02, REL-03, REL-04, EXEC-01, EXEC-02, EXEC-03, EXEC-04, DB-03
**Success Criteria** (what must be TRUE):
  1. When MT5 disconnects, the bot auto-reconnects with exponential backoff and sends a Discord alert on disconnect and on restore
  2. After reconnect, bot syncs full position state from MT5 before processing any new signals; signals received during reconnect are not executed with stale data
  3. Dashboard kill switch closes all positions, cancels all pending orders, and pauses the executor; bot does not accept new signals until manually re-enabled
  4. Pending order cleanup confirms MT5 order state before cancellation; correctly distinguishes filled-vs-failed rather than silently misclassifying
  5. Dashboard shows per-account daily trade count with a warning indicator when approaching the configured limit
**Plans:** 4 plans

Plans:
- [x] 02-01-PLAN.md -- MT5 connector hardening: ping(), EOFError wrapping, reconnect password support
- [x] 02-02-PLAN.md -- Execution correctness: zone logic extraction, stale re-check, SL/TP validation, cleanup race fix, DB archival
- [x] 02-03-PLAN.md -- Heartbeat, reconnect, kill switch core: executor + bot.py signal gating
- [x] 02-04-PLAN.md -- Dashboard: kill switch UI with confirmation, daily limit display with color coding

### Phase 3: Observability & Infrastructure
**Goal**: Operational problems are visible before they become outages, and the deployment is production-hardened
**Depends on**: Phase 2
**Requirements**: OBS-01, OBS-02, OBS-03, OBS-04, ANLYT-01, INFRA-01, INFRA-02, INFRA-03, INFRA-04
**Success Criteria** (what must be TRUE):
  1. When a signal-like message fails to parse, a detailed reason is logged and a Discord alert is sent to the alerts channel
  2. Dashboard position data is fetched without N+1 queries; positions load without per-position round-trips to MT5
  3. Signal accuracy (win rate, profit factor) per source and symbol is stored in the database and visible on the dashboard
  4. Dashboard runs with proper ASGI lifecycle; graceful shutdown on SIGTERM; Nginx reverse proxy config and Docker network config are documented and applied
  5. Telethon compatibility is documented with a version-locked decision; DB archival command exists and moves records older than 3 months to archive files
**Plans**: TBD

### Phase 4: Testing
**Goal**: Correctness of all prior hardening changes is verified by an automated test suite that runs in CI
**Depends on**: Phase 3
**Requirements**: TEST-01, TEST-02, TEST-03, TEST-04, TEST-05
**Success Criteria** (what must be TRUE):
  1. Running `pip install -r requirements-dev.txt && pytest` succeeds from a clean checkout
  2. MT5 connector tests cover connect, disconnect, get_price, open_order, modify_order, close_position, and error scenarios using mocks
  3. Trade manager integration tests verify full signal flow, multi-account execution, daily limit enforcement, and zone-based entry
  4. Async concurrency tests confirm no race conditions with concurrent signals and no database lock contention under load
  5. Signal parser regression tests cover all known real-world Telegram signal formats including edge cases
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 3/3 | Complete | 2026-03-22 |
| 2. Reliability | 0/4 | Planning complete | - |
| 3. Observability & Infrastructure | 0/TBD | Not started | - |
| 4. Testing | 0/TBD | Not started | - |
