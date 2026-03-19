# Feature Research

**Domain:** Production trading bot reliability & security
**Researched:** 2026-03-19
**Confidence:** HIGH

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = bot is unreliable for real money.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Auto-reconnect (MT5) | Connections drop; bot must recover without manual restart | MEDIUM | Heartbeat + exponential backoff + state reconciliation |
| Startup validation | Invalid credentials should fail immediately, not silently | LOW | Validate env vars, test connectivity before starting listener |
| Emergency kill switch | Must be able to stop all trading instantly | MEDIUM | Dashboard button + close all positions + require manual re-enable |
| Secure credential handling | Passwords shouldn't linger in memory or use weak defaults | LOW | Read-once patterns, no default passwords, env-only secrets |
| Database thread safety | Async bot must not corrupt its own database | MEDIUM | aiosqlite migration replaces unsafe check_same_thread pattern |
| Position reconciliation | Bot must know actual MT5 state, not cached assumptions | MEDIUM | Full sync after reconnect, stale-state detection |
| Test coverage on critical paths | Trading logic must be tested | HIGH | MT5 connector mocks, trade manager integration, signal parser regression |

### Differentiators (Competitive Advantage)

Features that set this bot apart from basic signal copiers.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Signal accuracy tracking | Know which sources are profitable vs losing | MEDIUM | Win rate per source/symbol, auto-disable bad sources |
| Daily limit dashboard | Visual awareness of capacity remaining | LOW | Dashboard widget showing trades remaining per account |
| Database archival | Long-running bot doesn't degrade over time | LOW | Monthly archive to CSV, keep 3 months live |
| Stale signal double-check | Reduce bad executions from TOCTOU race | LOW | Re-check price immediately before order placement |
| SL/TP modification validation | Prevent accidental bad modifications | LOW | Validate new SL is valid for position direction |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| ML-based signal parsing | Handle format variations automatically | Requires training data, adds ML dependency, hard to debug failures | Better regex logging + regression tests with real signals |
| Multi-process dashboard | Isolate dashboard from trading | Complicates shared state, executor/notifier references need IPC | Proper async lifecycle management in single process |
| Real-time position sync (continuous polling) | Always-current position view | Hammers MT5 API, may trigger rate limits | On-demand sync + event-driven updates after trades |
| Automatic Telethon upgrade to 2.x | Stay current | Telethon 2.x is a rewrite with breaking changes, still alpha | Stay on 1.42.0, monitor for critical security patches |

## Feature Dependencies

```
[aiosqlite migration]
    └──enables──> [Database concurrency fix]
                      └──enables──> [Database archival]

[MT5 auto-reconnect]
    └──enables──> [Position reconciliation]
                      └──enables──> [Stale state detection]

[Startup validation]
    └──enables──> [Secure credential handling]

[Emergency kill switch]
    └──requires──> [Dashboard endpoints exist] (already built)

[Test infrastructure (pytest + dev deps)]
    └──enables──> [MT5 connector tests]
    └──enables──> [Trade manager integration tests]
    └──enables──> [Signal parser regression tests]
    └──enables──> [Async concurrency tests]
```

## MVP Definition (v1 Hardening)

### Launch With (v1)

- [ ] aiosqlite migration (fixes thread safety + performance) — foundational
- [ ] SQL injection prevention (field name whitelisting) — security
- [ ] Startup env validation with fail-fast — safety
- [ ] Remove default dashboard credentials — security
- [ ] MT5 auto-reconnect with heartbeat — reliability
- [ ] Position reconciliation after reconnect — correctness
- [ ] Emergency kill switch in dashboard — safety
- [ ] Test infrastructure + critical path tests — confidence
- [ ] Pending order cleanup race condition fix — correctness
- [ ] Zone-based SELL boundary fix — correctness

### Add After Validation (v1.x)

- [ ] Signal accuracy tracking — once enough trade history exists
- [ ] Database archival — after running for 3+ months
- [ ] UTC timestamp standardization — after confirming daily limit behavior

### Future Consideration (v2+)

- [ ] Structured logging (structlog) — when debugging production issues
- [ ] Schema migration tooling (alembic) — when DB schema changes frequently

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| MT5 auto-reconnect | HIGH | MEDIUM | P1 |
| Emergency kill switch | HIGH | MEDIUM | P1 |
| aiosqlite migration | HIGH | MEDIUM | P1 |
| Startup validation | HIGH | LOW | P1 |
| Remove default credentials | HIGH | LOW | P1 |
| Position reconciliation | HIGH | MEDIUM | P1 |
| Test infrastructure | HIGH | HIGH | P1 |
| SQL field whitelisting | MEDIUM | LOW | P1 |
| Pending order race fix | MEDIUM | LOW | P1 |
| Zone SELL boundary fix | MEDIUM | LOW | P1 |
| Signal parser logging | MEDIUM | LOW | P2 |
| SL/TP modification validation | MEDIUM | LOW | P2 |
| Stale signal double-check | MEDIUM | LOW | P2 |
| UTC standardization | MEDIUM | MEDIUM | P2 |
| Daily limit dashboard | LOW | LOW | P2 |
| Magic number to config | LOW | LOW | P2 |
| Password memory clearing | LOW | LOW | P2 |
| Database archival | LOW | LOW | P3 |
| Signal accuracy tracking | MEDIUM | MEDIUM | P3 |
| Regex optimization | LOW | LOW | P3 |
| Dashboard N+1 fix | LOW | LOW | P3 |

---
*Feature research for: production trading bot reliability & security*
*Researched: 2026-03-19*
