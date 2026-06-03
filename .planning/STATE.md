---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: React/Vite dashboard rewrite
status: ready_to_plan
last_updated: 2026-06-03T18:23:37.241Z
last_activity: 2026-06-03 -- Phase 08 Plan 01 complete (JSON API foundation)
progress:
  total_phases: 8
  completed_phases: 3
  total_plans: 22
  completed_plans: 36
  percent: 38
stopped_at: Phase 08 complete (5/5) — ready to discuss Phase 9
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-01)

**Core value:** Preserve existing trading reliability while making the bot safer and more resilient — no regressions on live trading
**Current focus:** Phase 9 — spa scaffold + auth + design system

## Current Position

Phase: 9
Plan: Not started
Status: Ready to plan
Last activity: 2026-06-03

## v1.2 Milestone Map

5 phases (coarse granularity). Dependency-forced order: JSON API first, live-money pages + settings late, parallel-run cutover last.

| Phase | Name | Requirements | Depends on |
|-------|------|--------------|------------|
| 8 | JSON API Foundation | 5 (API-01..05) | Phase 5 (auth + settings data shipped); independent of 6/7 |
| 9 | SPA Scaffold + Auth + Design System | 5 (SPA-01..05) | Phase 8 (JSON contract + CSRF + number/time contract) |
| 10 | Read-only Page Migration (analytics pilot → signals → history → staged) | 4 (PAGE-01..04) | Phase 9 |
| 11 | Live-money Pages + Settings | 8 (PAGE-05..08, SUX-01..04) | Phases 10 + 8 |
| 12 | Parallel-run Cutover + HTMX Decommission | 3 (CUT-01..03) | Phases 10 + 11 |

**Execution order:** 8 -> 9 -> 10 -> 11 -> 12

**Phases needing planning-phase research:**

- Phase 8 — idempotency storage decision (in-memory / Redis / PostgreSQL) before the actions layer; check `docker-compose.yml` for existing Redis wiring (Open Question 4).
- Phase 9 — lock CSRF cookie/header names (OQ1), SPA URL strategy `/app/` (OQ2), static-serving mechanism (OQ3) before scaffold coding.
- Phase 11 — partial-close API shape note (percent → absolute volume) before coding.

## v1.1 Milestone Map (closing)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 5 | Foundation — UI substrate, auth, settings data model | 15 (UI-01..05, AUTH-01..06, SET-01/02/04/05) | In progress (3/5 plans) |
| 6 | Staged entry execution | 10 (STAGE-01..09, SET-03) | CARRIED FORWARD into v1.2 (code complete; awaiting VPS UAT) |
| 7 | Dashboard redesign (HTMX) | 5 (DASH-01..05) | SUPERSEDED / DESCOPED by v1.2 |

## Pending UAT

- `.planning/phases/06-staged-entry-execution/06-HUMAN-UAT.md` — 6 live-infra tests (text-only signal, correlated follow-up, kill-switch drain, reconnect reconcile, SSE price flash, settings form UX) — Phase 6 carried forward into v1.2; run on VPS with MT5 demo + real Telegram channel. NOT gated on the v1.2 frontend rewrite (backend-only).

## Seeds Planted

- SEED-001 — settings UX polish (toasts, inline help, copywriting) — FOLDED into v1.2 Phase 11 (SUX-01..04). Was previously slated for the now-superseded Phase 7.

## Performance Metrics

**Velocity:**

- Total plans completed: 5 (v1.2)
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 08 | 5 | - | - |

**Recent Trend (v1.0/v1.1 carryover):**

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
| Phase 07 P06 | 2min | 3 tasks | 5 files |
| Phase 07 P07 | 2min | 2 tasks | 3 files |
| Phase 08 P01 | 4min | - tasks | - files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [v1.2 Roadmap]: 5 phases (coarse) — page migration split at the read-only/live-money safety boundary (Phase 10 read-only, Phase 11 live-money) rather than one monolithic page phase
- [v1.2 Roadmap]: JSON API foundation (Phase 8) precedes all UI; it locks the CSRF double-submit contract + server-side number/timestamp formatting that every page inherits
- [v1.2 Roadmap]: Live-money pages (overview, positions, kill switch) + settings land LAST (Phase 11) — highest blast radius; settings + positions are the two HIGH-complexity pages
- [v1.2 Roadmap]: Phase 6 staged-entry carried forward (not part of v1.2); Phase 7 HTMX redesign superseded/descoped, not completed
- [v1.2 Init]: Rewrite dashboard as React 19 + Vite SPA — HTMX refresh-race bugs recurred; client-side state model eliminates the class
- [v1.2 Init]: Vite SPA (static behind nginx) over Next.js — no Node runtime in prod (minimize-deps)
- [v1.2 Init]: FastAPI dashboard → JSON API; bot core untouched (confine blast radius to presentation layer)
- [v1.2 Init]: Keep httpOnly session-cookie auth, same-origin; no localStorage tokens; preserve CSRF
- [v1.1 Phase 05-05]: Bump Tailwind standalone CLI v3.4.19 → v4.2.2 (backend already on Tailwind v4 — SPA alignment natural)
- [Phase ?]: Phase 08-01: api/ mounts at /api/v2; router.py single-owns ten resource sub-routers (Plans 02-05 add handlers only)
- [Phase ?]: Phase 08-01: idempotency_keys DDL lives in api/idempotency.py via db._pool accessor — db.py byte-for-byte untouched (D-01..D-04)
- [Phase ?]: Phase 08-01: double-submit CSRF (telebot_csrf vs X-CSRF-Token, compare_digest) replaces HX-Request heuristic for /api/v2 (D-15)

### Pending Todos

- [Phase 8 prep]: Decide idempotency storage for partial-close dedupe (check `docker-compose.yml` for Redis); verify `telebot_csrf` cookie name does not collide with `telebot_login_csrf` (dashboard.py:142); confirm `/api/v2/` is caught by the `_verify_auth` `/api/` prefix 401 branch
- [Phase 9 prep]: Lock SPA URL strategy (`/app/`) and static-serving mechanism (uvicorn StaticFiles vs nginx alias) before Dockerfile/nginx edits

### Blockers/Concerns

- [v1.2 — all live-money phases]: NO optimistic updates on close/modify/partial-close/kill-switch — UI changes state only on server-confirmed success (Pitfall 1)
- [v1.2 — Phase 8]: HTMX-coupled CSRF (`HX-Request` check) silently breaks for the SPA; correct fix is double-submit cookie + `X-CSRF-Token`, NOT deleting the check; regression test required before any page goes live (Pitfall 2)
- [v1.2 — Phase 8/11]: Partial-close non-idempotent server-side (percent-of-remaining double-fire = 75%); switch to absolute volume + request-id (Pitfall 3)
- [v1.2 — Phase 12]: nginx `try_files` catch-all must NOT cover the whole origin during parallel-run; SSE `proxy_buffering off` / `proxy_read_timeout 86400s` preserved until HTMX overview/staged decommissioned (Pitfall 4)
- [v1.2 — Phase 8]: Number/timestamp formatting stays server-side (XAUUSD pip-size already bit this project — quick task 260501-i7u); SPA submits exact server-provided numeric value, never a re-rounded JS value (Pitfall 5)
- [Phase 6 — carried forward]: Live-money staged-entry logic still the highest-risk backend; gate on VPS UAT before enabling on real channel

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260330-shy | Optimize mt5-bridge and telebot Docker images | 2026-03-30 | 892de47 | [260330-shy-optimize-mt5-bridge-and-telebot-docker-i](./quick/260330-shy-optimize-mt5-bridge-and-telebot-docker-i/) |
| 260501-i7u | Fix XAUUSD pip-size and add fixed_lot order branch | 2026-05-01 | 0ad60c3 | [260501-i7u-fix-xauusd-pip-size-and-add-fixed-lot-or](./quick/260501-i7u-fix-xauusd-pip-size-and-add-fixed-lot-or/) |
| 260501-mrw | Align stage-1 SL+TP with correlated follow-up signal | 2026-05-01 | 08477cf | [260501-mrw-align-stage-1-sl-tp-with-correlated-foll](./quick/260501-mrw-align-stage-1-sl-tp-with-correlated-foll/) |

## Session Continuity

Last activity: 2026-06-01 — v1.2 roadmap created (Phases 8–12); REQUIREMENTS.md traceability filled (25/25); v1.1 transition status recorded (Phase 6 carried forward, Phase 7 superseded)
Resume file: None
Next action: `/gsd:plan-phase 8` — JSON API Foundation (resolve idempotency-storage Open Question 4 during planning)
