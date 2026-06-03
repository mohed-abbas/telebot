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
| Rewrite dashboard as React 19 + Vite SPA | HTMX refresh-race bugs (input clobbering, flicker, modal mounting) recurred; client-side state model eliminates the class; operator fluent in React | v1.2 (in progress) |
| Vite SPA over Next.js | No Node runtime in prod (minimize-deps); internal single-operator tool needs no SSR/SEO | v1.2 (in progress) |
| FastAPI dashboard → JSON API (bot core untouched) | Confine blast radius to presentation layer; dangerous trading code unchanged | v1.2 (in progress) |
| Parallel-run + page-by-page cutover behind nginx | Live-money control surface must never regress; reversible at every step | v1.2 (in progress) |
| Keep httpOnly session-cookie auth, same-origin | Avoid SPA token-in-localStorage risk and CORS+cookie complexity; preserve CSRF | v1.2 (in progress) |

## Previous Milestone: v1.1 — Improved trade executions and UI (closing — partially shipped)

- **Phase 5 (UI substrate, auth, settings data)** — shipped.
- **Phase 6 (staged-entry execution)** — code complete; **carried forward into v1.2 as an outstanding item** (awaiting live VPS UAT with MT5 demo). Backend-only; unaffected by the frontend rewrite.
- **Phase 7 (HTMX dashboard redesign)** — **SUPERSEDED by v1.2.** The HTMX substrate proved glitchy (recurring refresh-race bugs that clobber open inputs, flicker, modal mounting issues). Remaining HTMX work descoped rather than completed; replaced wholesale by the React rewrite.

## Current Milestone: v1.2 — React/Vite dashboard rewrite

**Goal:** Replace the FastAPI + HTMX + Jinja server-rendered dashboard with a separate React 19 + Vite SPA, eliminating the HTMX refresh-race bug class and moving to a stack the operator is fluent in — with zero regression to live-money controls.

**Locked stack (final, not for re-litigation):** React 19 · Vite · shadcn/ui · Tailwind CSS.

**Target features:**
- **JSON API layer** — refactor `dashboard.py`'s ~31 HTML-fragment endpoints into a JSON API (the computation already exists; only the response shape changes). Bot core (`executor.py`, `trade_manager.py`, `db.py`, `mt5_connector.py`, signal parsing/correlation) and the MT5 REST bridge are untouched.
- **React/Vite SPA + auth + design system** — Vite-built React 19 app, shadcn/ui components, Tailwind theming mapped from the existing dark palette (`#252542` / `#1a1a2e` / `#0f0f1a`). Keep httpOnly session-cookie auth (argon2 + itsdangerous); no `localStorage` tokens; served same-origin behind nginx; CSRF preserved on mutations.
- **Page migration** — re-implement all 9 views: overview, positions, history, signals, staged, settings, analytics, login, root(redirect).
- **Settings UX (folds SEED-001)** — save/error toasts (sonner), per-field help/tooltips with recommended ranges + footgun warnings, operator-legible copywriting.
- **Parallel-run cutover** — run the existing HTMX dashboard alongside the SPA behind nginx; cut over page-by-page; decommission an HTMX page only after its React replacement is verified against the MT5 demo. Analytics is the low-risk pilot (read-only, no live-money actions).

**Key context:**
- Likely phase shape: (1) JSON API layer → (2) SPA scaffold + auth + design system → (3) page migration waves → (4) parallel-run cutover + HTMX decommission. ~4–6 weeks solo to parity, naturally incremental.
- Chose **Vite SPA (static files behind nginx)** over Next.js to avoid adding a Node runtime in production (PROJECT.md "minimize dependencies").
- Live-money operator control surface (close position, modify SL/TP, partial close, kill switch) must NEVER regress — this is the non-negotiable constraint shaping the cutover strategy.
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
*Last updated: 2026-06-03 — Phase 8 (JSON API Foundation) complete: versioned `/api/v2` JSON contract with Pydantic models, double-submit CSRF, server-side dual-value formatting, and idempotent absolute-volume partial-close (API-01–API-05 all validated); bot core byte-for-byte untouched. Next: Phase 9 (SPA scaffold + auth + design system).*
