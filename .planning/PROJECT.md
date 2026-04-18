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

## Current Milestone: v1.1 Improved trade executions and UI

**Goal:** Stop missing trades via a staged-entry strategy, modernize the dashboard with shadcn + tailwind, and replace basic-auth with a proper login form.

**Target features:**
- **Staged entry strategy** — text-only signals ("Gold buy now") open 1 initial position immediately; follow-up signal with zone/SL/TP opens additional positions when price enters the zone. Max positions and risk mode (percentage OR fixed lot) are configurable per account.
- **Per-account settings page** — UI for editing risk mode, lot size, and max positions at runtime (beyond static accounts.json).
- **Dashboard redesign** — shadcn + tailwind via `/frontend-design`, mobile-responsive, richer positions/trades views and analytics drilldowns.
- **Proper login form** — styled login UX replacing the current basic-auth prompt.

**Key context:**
- Focused milestone (2–3 phases).
- Open item for `/gsd-discuss-phase`: shadcn targets React/Vue while the current dashboard is FastAPI + HTMX — the frontend substrate (stay HTMX + Tailwind w/ shadcn CSS tokens vs. SPA rewrite) must be decided before UI phases start.
- Safety bar from v1.0 still applies: real money; no regressions on live trading.

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-18 — milestone v1.1 started*
