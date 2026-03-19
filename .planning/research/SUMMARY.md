# Research Summary

**Domain:** Async Python trading bot hardening
**Synthesized:** 2026-03-19

## Key Findings

### Stack
- **aiosqlite 0.20.0** is already in requirements.txt but unused — drop-in migration from sync sqlite3 solves thread safety AND performance
- **pytest + pytest-asyncio** needed for test infrastructure — add via requirements-dev.txt
- Stay on **Telethon 1.42.0** (2.x is alpha, breaking changes) — monitor only
- No new major dependencies needed; hardening is mostly refactoring existing code

### Table Stakes (Must Fix)
1. **Database thread safety** — aiosqlite migration (foundational, everything depends on this)
2. **MT5 auto-reconnect** — single disconnection currently kills all trading
3. **Emergency kill switch** — no way to stop trading without restarting bot or using MT5 terminal
4. **Startup validation** — invalid credentials fail silently deep in execution
5. **Default credential removal** — "admin/changeme" is a production risk
6. **Position reconciliation** — bot can diverge from actual MT5 state after reconnect

### Watch Out For
1. **aiosqlite transaction semantics** — multi-statement transactions (log_signal + log_trade) must stay atomic; don't naively split into separate connections
2. **Reconnect cascade** — signals queuing during reconnect can execute with stale data; need "paused" state
3. **Kill switch must cancel pending orders** — not just close positions, or orphaned limits will fill later
4. **UTC migration shifts daily limit reset** — document and test carefully
5. **Test mocks diverging from real MT5** — base mocks on actual response captures

### Recommended Build Order
1. **Foundation** — database (aiosqlite), security (creds, validation), config (magic number, UTC)
2. **Reliability** — MT5 reconnect, position reconciliation, execution fixes (zone, pending orders, stale check, kill switch)
3. **Observability** — signal parser logging, daily limit dashboard, server message docs, N+1 fix
4. **Testing** — test infrastructure, MT5 mocks, integration tests, regression tests, async tests
5. **Maintenance** — database archival, regex optimization, signal accuracy tracking

### Risk Assessment
- **Highest risk change:** aiosqlite migration (touches every database operation) — mitigate with function-by-function migration + tests
- **Highest value change:** MT5 auto-reconnect (eliminates #1 operational pain point)
- **Lowest risk, high value:** startup validation + default credential removal (simple config changes)

## Research Files

| File | Contents |
|------|----------|
| `STACK.md` | Technology recommendations, alternatives, what to avoid |
| `FEATURES.md` | Feature prioritization, dependencies, MVP definition |
| `ARCHITECTURE.md` | Build order, migration patterns, data flows |
| `PITFALLS.md` | Critical pitfalls, recovery strategies, phase mapping |

---
*Research synthesized: 2026-03-19*
