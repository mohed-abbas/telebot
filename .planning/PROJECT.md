# Telebot Hardening

## What This Is

A systematic hardening pass on an existing Telegram-to-Discord trading relay bot. The bot listens to Telegram signal groups, parses trading signals, executes trades across multiple MT5 accounts, and provides a web dashboard for monitoring. This project addresses all identified concerns: security vulnerabilities, race conditions, missing reconnection logic, test coverage gaps, performance bottlenecks, and missing critical features.

## Core Value

Every change must preserve existing trading reliability while making the bot safer and more resilient — no regressions on live trading functionality.

## Requirements

### Validated

- ✓ Telegram message relay to Discord with photo/video support — existing
- ✓ Trading signal parsing from Telegram messages (regex-based) — existing
- ✓ Multi-account MT5 trade execution with staggered delays — existing
- ✓ Zone-based entry logic (market vs limit orders) — existing
- ✓ Risk-based lot sizing with per-account configuration — existing
- ✓ SL/TP modification and partial close signal handling — existing
- ✓ SQLite audit trail for all signals and trades — existing
- ✓ FastAPI web dashboard with HTTP Basic auth — existing
- ✓ Discord notifications to separate channels (signals, executions, alerts) — existing
- ✓ Pending order tracking and expiry cleanup — existing
- ✓ Docker containerized deployment — existing
- ✓ Dry-run mode for testing without live MT5 — existing

### Active

- [ ] Fix database thread safety (migrate to aiosqlite)
- [ ] Add SQL field name whitelisting to prevent injection
- [ ] Standardize all timestamps to UTC
- [ ] Fix pending order cleanup race condition
- [ ] Fix zone-based entry logic for SELL order boundary conditions
- [ ] Add MT5 position state reconciliation after reconnection
- [ ] Move magic number to configuration
- [ ] Add environment variable validation with fail-fast on startup
- [ ] Clear MT5 passwords from memory after initialization
- [ ] Remove default dashboard credentials, require explicit config
- [ ] Improve database concurrency (connection pooling or aiosqlite)
- [ ] Optimize symbol map lookup (compiled regex)
- [ ] Fix dashboard N+1 position query problem
- [ ] Add comprehensive signal parser logging on parse failures
- [ ] Extract zone logic into testable functions
- [ ] Add double stale-check before order execution
- [ ] Implement emergency kill switch in dashboard
- [ ] Add daily trade limit warnings and dashboard status
- [ ] Document and validate server message limits
- [ ] Implement SQLite database archival and cleanup
- [ ] Update Telethon to latest compatible version
- [ ] Create requirements-dev.txt with test dependencies
- [ ] Run dashboard in separate process with proper ASGI server
- [ ] Implement MT5 connection monitoring and auto-reconnect
- [ ] Add position direction validation before SL/TP modification
- [ ] Add historical signal accuracy tracking
- [ ] Add MT5 connector tests with mocking
- [ ] Add trade manager integration tests
- [ ] Add signal parser regression tests with real-world data
- [ ] Add async concurrency tests (race conditions, lock contention)

### Out of Scope

- New features beyond what's needed to fix concerns — this is a hardening pass
- UI redesign of dashboard — only functional changes (kill switch, limit status)
- Migration away from SQLite — optimize what exists
- Rewriting signal parser with ML/NLP — improve logging and tests instead

## Context

The bot is deployed on a VPS (Hostinger) via Docker. It handles real money through MT5, so changes must be conservative — small, isolated, and tested. The codebase already has `aiosqlite` in requirements.txt but doesn't use it. Test files exist but pytest is not in requirements. The concerns were identified through systematic codebase analysis and range from critical (security, race conditions) to lower priority (regex caching, DB growth).

## Constraints

- **Safety**: Real money at stake — every change must be tested before deployment
- **Backwards compatibility**: No breaking changes to .env or accounts.json config format
- **Deployment**: Must continue to work in existing Docker setup
- **Dependencies**: Minimize new dependencies — prefer stdlib and already-installed packages

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Conservative approach (small isolated changes) | Bot handles real money, regressions are costly | — Pending |
| Address all concerns, not just critical | Comprehensive hardening prevents accumulating more debt | — Pending |
| Migrate to aiosqlite (already in requirements) | Solves both thread safety and performance concerns | — Pending |

---
*Last updated: 2026-03-19 after initialization*
