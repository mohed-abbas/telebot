# Telebot

## Current State (v1.0 — Shipped)

A Telegram-to-Discord trading relay bot with automated signal execution across multiple MT5 accounts. Hardened in v1.0 with PostgreSQL migration, MT5 resilience, emergency controls, and comprehensive test suite.

### What's Deployed
- **PostgreSQL** via asyncpg (migrated from SQLite) connected to shared VPS database
- **MT5 resilience** — 30s heartbeat, auto-reconnect with exponential backoff, position sync after reconnect
- **Emergency kill switch** — two-step confirmation, closes all positions + cancels orders, pauses trading
- **Execution correctness** — zone logic extraction, stale signal re-check, SL/TP direction validation
- **Dashboard** — daily limit colors, analytics page (win rate/profit factor), TRADING PAUSED banner
- **Infrastructure** — Docker networking (proxy-net + data-net), nginx reverse proxy, graceful shutdown
- **Test suite** — 113 tests (80 unit + 33 integration) covering connectors, trade flows, concurrency

### Tech Stack
- Python 3.12, asyncpg, FastAPI, Telethon 1.42.0, HTMX
- PostgreSQL 16 (shared VPS instance via data-net)
- Docker + nginx reverse proxy (proxy-net)
- pytest + pytest-asyncio for testing

## Core Value

Every change must preserve existing trading reliability while making the bot safer and more resilient.

## Constraints

- **Safety**: Real money at stake — every change must be tested before deployment
- **Backwards compatibility**: No breaking changes to .env or accounts.json config format
- **Deployment**: Docker with shared VPS services (proxy-net, data-net)
- **Dependencies**: Minimize new dependencies

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| PostgreSQL via asyncpg (not aiosqlite) | User has shared PostgreSQL on VPS | v1.0 shipped |
| Conservative approach | Bot handles real money | v1.0 shipped |
| Stay on Telethon 1.42.0 | 2.x is alpha with breaking changes | v1.0 shipped |
| Kill switch with confirmation | Prevent accidental activation | v1.0 shipped |
| Drop signals during reconnect | Safest approach for stale data prevention | v1.0 shipped |

## Next Milestone Goals

*Not yet defined — run `/gsd:new-milestone` to start the next cycle.*

Potential areas:
- v2 monitoring: structured logging, connection uptime metrics, execution latency
- CI/CD pipeline (GitHub Actions)
- Signal accuracy auto-disable for low-performing sources
- Schema migration tooling (alembic)

---
*Last updated: 2026-03-23 after v1.0 milestone completion*
