# Requirements: Telebot Hardening

**Defined:** 2026-03-19
**Core Value:** Every change must preserve existing trading reliability while making the bot safer and more resilient

## v1 Requirements

### Security

- [ ] **SEC-01**: SQL field names in dynamic queries are validated against an explicit whitelist before use
- [ ] **SEC-02**: Dashboard requires explicitly configured credentials; no hardcoded defaults; startup fails if DASHBOARD_PASS not set
- [ ] **SEC-03**: All required environment variables are validated at startup with format checks (TG_API_ID is numeric, sessions are valid format); bot fails fast with clear error messages
- [ ] **SEC-04**: MT5 passwords are cleared from memory after MT5 initialization completes; never logged or printed

### Database

- [ ] **DB-01**: All database operations use aiosqlite instead of sync sqlite3; no check_same_thread=False; global asyncio.Lock removed
- [ ] **DB-02**: All database timestamps use UTC; daily_stats dates use UTC date; timezone conversion happens only at display time
- [ ] **DB-03**: Database has archival mechanism: trades older than 3 months moved to CSV/JSON archive files; maintenance command available
- [ ] **DB-04**: MT5 magic number is loaded from configuration (env var or config file) instead of hardcoded

### Reliability

- [ ] **REL-01**: MT5 connections have heartbeat check (every 30s); auto-reconnect with exponential backoff on failure; Discord alert on disconnect and restore
- [ ] **REL-02**: After MT5 reconnection, full position sync from MT5 occurs before accepting new signals; stale state detected via last_sync_time
- [ ] **REL-03**: Dashboard has emergency kill switch that closes all positions, cancels all pending orders, pauses executor, and requires manual re-enable
- [ ] **REL-04**: Pending order cleanup verifies MT5 order state before cancellation; distinguishes "order filled" from "cancel failed"; retries failed cancellations

### Execution

- [ ] **EXEC-01**: Zone-based entry logic for SELL orders correctly handles boundary conditions; zone logic extracted into named testable functions
- [ ] **EXEC-02**: Stale signal check runs again immediately before order placement (not just once at signal receipt)
- [ ] **EXEC-03**: SL/TP modifications validate that new values are valid for position direction before sending to MT5
- [ ] **EXEC-04**: Dashboard shows daily trade limit status per account with warnings when approaching limit (e.g., at 25/30)

### Observability

- [ ] **OBS-01**: Signal parser logs detailed reason when parse_signal returns None; Discord alert sent when signal-like text detected but not parsed
- [ ] **OBS-02**: Server message limits documented: what counts as a server message, sync with MT5 broker limits, configurable per account
- [ ] **OBS-03**: Dashboard position queries batched across accounts; no N+1 query pattern; optional short-TTL cache
- [ ] **OBS-04**: Symbol map uses compiled combined regex for lookup instead of iterating full SYMBOL_MAP on every call

### Testing

- [ ] **TEST-01**: requirements-dev.txt created with pytest, pytest-asyncio, pytest-mock, pytest-cov; documented in README
- [ ] **TEST-02**: MT5 connector has mock-based tests covering: connect, disconnect, get_price, open_order, modify_order, close_position, error scenarios
- [ ] **TEST-03**: Trade manager has integration tests covering: full signal flow, multi-account execution, daily limit enforcement, zone-based execution
- [ ] **TEST-04**: Async concurrency tests verify: no race conditions with concurrent signals, database lock contention under load, reconnection during signal processing
- [ ] **TEST-05**: Signal parser has regression tests using real-world Telegram signal formats including edge cases and format variations

### Analytics

- [ ] **ANLYT-01**: Signal accuracy tracking: win rate and profit factor per signal source and symbol; stored in database; displayed on dashboard

### Infrastructure

- [ ] **INFRA-01**: Dashboard runs with proper ASGI lifecycle management; graceful shutdown on SIGTERM; no blocking of Telegram handler
- [ ] **INFRA-02**: Telethon version evaluated: document compatibility with current setup, identify security patches, create upgrade plan if needed
- [ ] **INFRA-03**: Docker compose configured to join existing shared services network at /home/murx/shared; bot accessible to nginx reverse proxy
- [ ] **INFRA-04**: Nginx reverse proxy configuration provided for dashboard with HTTPS via existing certbot/Let's Encrypt setup

## v2 Requirements

### Advanced Monitoring

- **MON-01**: Structured JSON logging (structlog) for production debugging
- **MON-02**: Connection uptime metrics tracked and displayed on dashboard
- **MON-03**: Trade execution latency metrics (signal received → order placed)

### Database Evolution

- **DBE-01**: Schema migration tooling (alembic) for safe database schema changes
- **DBE-02**: PostgreSQL migration path for multi-process access if needed

## Out of Scope

| Feature | Reason |
|---------|--------|
| ML/NLP signal parser | High complexity, requires training data; better logging + tests is sufficient |
| Telethon 2.x migration | 2.x is alpha with breaking changes; evaluate only, don't migrate |
| Multi-process dashboard | Complicates shared state (executor, notifier); single process with proper lifecycle is sufficient |
| Real-time continuous position polling | Hammers MT5 API; on-demand sync + event-driven updates is better |
| UI redesign of dashboard | Only functional changes needed (kill switch, limits); no visual overhaul |
| Migration from SQLite to PostgreSQL | Optimize existing SQLite with aiosqlite; PostgreSQL is v2 if needed |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SEC-01 | TBD | Pending |
| SEC-02 | TBD | Pending |
| SEC-03 | TBD | Pending |
| SEC-04 | TBD | Pending |
| DB-01 | TBD | Pending |
| DB-02 | TBD | Pending |
| DB-03 | TBD | Pending |
| DB-04 | TBD | Pending |
| REL-01 | TBD | Pending |
| REL-02 | TBD | Pending |
| REL-03 | TBD | Pending |
| REL-04 | TBD | Pending |
| EXEC-01 | TBD | Pending |
| EXEC-02 | TBD | Pending |
| EXEC-03 | TBD | Pending |
| EXEC-04 | TBD | Pending |
| OBS-01 | TBD | Pending |
| OBS-02 | TBD | Pending |
| OBS-03 | TBD | Pending |
| OBS-04 | TBD | Pending |
| TEST-01 | TBD | Pending |
| TEST-02 | TBD | Pending |
| TEST-03 | TBD | Pending |
| TEST-04 | TBD | Pending |
| TEST-05 | TBD | Pending |
| ANLYT-01 | TBD | Pending |
| INFRA-01 | TBD | Pending |
| INFRA-02 | TBD | Pending |
| INFRA-03 | TBD | Pending |
| INFRA-04 | TBD | Pending |

**Coverage:**
- v1 requirements: 30 total
- Mapped to phases: 0
- Unmapped: 30 ⚠️

---
*Requirements defined: 2026-03-19*
*Last updated: 2026-03-19 after initial definition*
