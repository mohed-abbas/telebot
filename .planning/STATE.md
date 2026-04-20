---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: — Improved trade executions and UI
status: executing
last_updated: "2026-04-20T19:59:16Z"
last_activity: 2026-04-20 -- Phase 07 Plan 05 complete (analytics time filter + source drill-down)
progress:
  total_phases: 3
  completed_phases: 1
  total_plans: 18
  completed_plans: 10
  percent: 55
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-18)

**Core value:** Preserve existing trading reliability while making the bot safer and more resilient — no regressions on live trading
**Current focus:** Phase 06 — staged-entry-execution

## Current Position

Phase: 07 (dashboard-redesign) — EXECUTING
Plan: 5 of 8 complete
Status: Plan 05 shipped — analytics time filter + per-source drill-down. Wave 3 in progress.
Last activity: 2026-04-20 -- Phase 07 Plan 05 complete (3 tasks, 4 files)

## Pending UAT

- `.planning/phases/06-staged-entry-execution/06-HUMAN-UAT.md` — 6 live-infra tests (text-only signal, correlated follow-up, kill-switch drain, reconnect reconcile, SSE price flash, settings form UX) — run on VPS with MT5 demo + real Telegram channel after Phase 07 ships.

## Seeds Planted

- SEED-001 — settings UX polish (toasts, inline help, copywriting) — surfaces at Phase 07 discuss-phase.

## v1.1 Milestone Map

| Phase | Name | Requirements | Depends on |
|-------|------|--------------|------------|
| 5 | Foundation — UI substrate, auth, and settings data model | 15 (UI-01..05, AUTH-01..06, SET-01/02/04/05) | Phase 4 (v1.0 complete) |
| 6 | Staged entry execution | 10 (STAGE-01..09, SET-03) | Phase 5 |
| 7 | Dashboard redesign | 5 (DASH-01..05) | Phase 5, Phase 6 |

## Performance Metrics

**Velocity:**

- Total plans completed: 0
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend (v1.0 carryover):**

| Phase 01 P03 | 1min | 1 tasks | 1 files |
| Phase 01 P01 | 2min | 2 tasks | 4 files |
| Phase 01 P02 | 2min | 2 tasks | 2 files |
| Phase 03 P02 | 2min | 2 tasks | 4 files |
| Phase 03 P01 | 2min | 3 tasks | 4 files |
| Phase 03 P03 | 2min | 3 tasks | 6 files |
| Phase 04 P01 | 4min | 2 tasks | 6 files |
| Phase 04 P02 | 4min | 2 tasks | 2 files |
| Phase 04 P03 | 6min | 2 tasks | 2 files |
| Phase 05 P05 | 5min | 3 tasks | 5 files |
| Quick 260330-shy | 4min | 3 tasks | 7 files |
| Phase 07 P01 | 5min | 3 tasks | 7 files |
| Phase 07 P02 | 3min | 2 tasks | 4 files |
| Phase 07 P03 | 2min | 3 tasks | 4 files |
| Phase 07 P04 | 2min | 3 tasks | 4 files |
| Phase 07 P05 | 2min | 3 tasks | 4 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [v1.1 Init]: Focused milestone — 3 phases (not 5); consolidate UI + auth + settings data into one foundation phase
- [v1.1 Init]: Staged-entry isolated in its own phase (Phase 6) because it's the highest-risk live-money logic
- [v1.1 Init]: Two-signal correlation model (text-only signal + follow-up with zone/SL/TP), NOT one-signal zone-watcher
- [v1.1 Init]: UI substrate — Basecoat UI (`basecoat-css@0.3.3`) + Tailwind v3.4 standalone CLI on HTMX + Jinja; no SPA rewrite
- [v1.1 Init]: Auth — argon2-cffi + Starlette SessionMiddleware; no fastapi-users / JWT
- [v1.1 Init]: Schema — hand-written additive-only DDL; alembic (DBE-01) stays deferred to v1.2
- [v1.0 Phase 01]: Password cleared to empty string (not None) for type consistency; retained on failed connection for retry
- [v1.0 Phase 01]: Removed dashboard.py hardcoded changeme fallback to fully eliminate default credentials (SEC-02)
- [v1.0 Phase 01]: Pool sizing min=2, max=5 for asyncpg — conservative for single-process trading bot
- [v1.0 Phase 03]: FastAPI lifespan used instead of deprecated on_event pattern for ASGI lifecycle
- [v1.0 Phase 03]: Stay on Telethon 1.42.0 — 2.x alpha with breaking changes; re-evaluate when stable
- [v1.0 Phase 03]: Docker external networks (proxy-net, data-net) with no direct port exposure
- [v1.0 Phase 04]: Session-scoped event loop for DB-dependent tests to share asyncpg pool
- [Quick]: Single container with isolated Wine prefixes per account instead of one container per account
- [v1.1 Phase 05-05]: Bump Tailwind standalone CLI v3.4.19 → v4.2.2 (Basecoat v0.3.3 is v4-native; v4 resolves @import natively; kept tailwind.config.js alive via v4 @config directive — minimum-churn migration)
- [v1.1 Phase 05-05]: Dockerfile TARGETARCH-aware binary selection (linux-x64 on amd64, linux-arm64 on arm64) — v4's native Rust binary doesn't tolerate Rosetta/qemu emulation where v3's did

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 6]: Live-money staged-entry logic is the highest-risk phase — isolate it and gate on thorough integration tests before enabling
- [Phase 6]: Text-only signal must open with non-zero default SL; `sl=0.0` is never an acceptable submit (Pitfall 1)
- [Phase 6]: Duplicate-direction guard in `trade_manager.py:187-190` must be signal-id-aware or stages 2..N silently fail (Pitfall 2)
- [Phase 6]: Kill switch must drain `staged_entries` BEFORE closing positions (Pitfall 4)
- [Phase 6]: Reconnect must reconcile `staged_entries` against MT5 by comment-based idempotency key (Pitfall 5)
- [Phase 5]: Tailwind `content` glob must include `*.py` files; classes inlined in `dashboard.py` HTMLResponse fragments will otherwise be purged (Pitfall 10)
- [Phase 5]: Login CSRF uses double-submit cookie on `/login` ONLY; existing HTMX-header CSRF preserved elsewhere (Pitfall 13)
- [Phase 5]: Login form must land before any editable settings UI is exposed — avoid editable settings under HTTPBasic

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260330-shy | Optimize mt5-bridge and telebot Docker images | 2026-03-30 | 892de47 | [260330-shy-optimize-mt5-bridge-and-telebot-docker-i](./quick/260330-shy-optimize-mt5-bridge-and-telebot-docker-i/) |

## Session Continuity

Last activity: 2026-04-20 — Phase 07 Plan 05 complete (analytics time filter + source drill-down)
Resume file: .planning/phases/07-dashboard-redesign/07-06-PLAN.md
Next action: Wave 3 continues [07-06, 07-07 parallel] → Wave 4 [07-08]
