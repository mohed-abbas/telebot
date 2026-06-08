---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: React/Vite dashboard rewrite
status: executing
last_updated: "2026-06-08T17:00:00.000Z"
last_activity: 2026-06-08 -- Phase 13 Plan 05 (direct-zone multi-stage _handle_open, EXEC2-06) complete
progress:
  total_phases: 9
  completed_phases: 8
  total_plans: 47
  completed_plans: 47
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-01)

**Core value:** Preserve existing trading reliability while making the bot safer and more resilient — no regressions on live trading
**Current focus:** Phase 13 — staged-entry-execution-correctness-and-direct-zone-multi-sta

## Current Position

Phase: 13 (staged-entry-execution-correctness-and-direct-zone-multi-sta) — ALL PLANS EXECUTED (awaiting /gsd:verify-work 13)
Plan: 5 of 5 COMPLETE (13-01/02/03/04/05 all complete)
Status: Phase 13 code-complete (all 6 EXEC2 gaps closed: EXEC2-01..06). Wave 2 done (13-04 EXEC2-05 + 13-05 EXEC2-06). Live MT5 sign-offs deferred to single VPS end-to-end acceptance (deploy-at-end).
Last activity: 2026-06-08 -- Phase 13 Plan 05 (direct-zone multi-stage _handle_open, EXEC2-06) complete; live MT5 sign-off deferred to VPS end-to-end acceptance

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

- Total plans completed: 15 (v1.2)
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 08 | 5 | - | - |
| 09 | 4 | - | - |
| 11 | 6 | - | - |

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
| Phase 09 P01 | 15min | 3 tasks | 17 files |
| Phase 09 P02 | 8min | 3 tasks | 4 files |
| Phase 09 P03 | 6min | 2 tasks | 6 files |
| Phase 09 P04 | 12min | 3 tasks | 6 files |
| Phase 11 P01 | 3min | 3 tasks | 12 files |
| Phase 11 P02 | 2min | 2 tasks | 5 files |
| Phase 11 P06 | 12min | 2 tasks | 3 files |

## Accumulated Context

### Roadmap Evolution

- Phase 13 added (2026-06-08): Staged-entry execution correctness and direct-zone multi-stage — 6 execution-engine gaps found in live real-money testing (EXEC2-01..06: late-stage SL/TP loss, percent-mode risk not split across stages, /staged display mismatch, SL-less signal crash, unmanaged orphan text-only, and the new behavior making direct zone+SL+TP signals multi-stage). Backend-only (Phase 6 lineage; `trade_manager.py`/`executor.py`/`signal_parser.py`); independent of the v1.2 dashboard chain; MT5 bridge untouched. Next: `/gsd:discuss-phase 13`.

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
- [Phase 09-01]: Greenfield frontend/ Vite 8 + React 19 + TS SPA scaffolded; base:/app/ (D-01), Tailwind v4 via @tailwindcss/vite with NO tailwind.config.js (D-10), dark brand palette mapped to shadcn @theme semantic roles (D-10), minimal 5-component set button/input/label/card/sonner (D-11), dev /api proxy to 8090 same-origin cookies (D-12)
- [Phase 09-01]: Stack adjustments — rolldown binding kept out of package.json (transitive), dropped TS baseUrl, rejected shadcn nova extras (tw-animate-css/next-themes/webfonts), unified radix-ui umbrella package, sonner Toaster theme="dark"
- [Phase 09-02]: SPA served at /app via uvicorn StaticFiles with SpaStaticFiles 404->index.html deep-link fallback (D-01, Pitfall 1); mount registered AFTER api_router so /api/v2 is never shadowed (D-02); Dockerfile node:22-slim AS spa-build stage builds the bundle, runtime stays python:3.12-slim with no prod Node, css-build coexists (D-03)
- [Phase 09-03]: Single api() fetch wrapper echoes telebot_csrf as X-CSRF-Token on mutations only + credentials:same-origin + throws HttpError on non-2xx (D-04/D-06); one global onAuthError on QueryCache+MutationCache hard-navs to /app/login with loop-break (SPA-04); QueryClient inherited defaults keepPreviousData + refetchIntervalInBackground:false, staleTime:1000, retry:false (D-09); login view seeds CSRF on mount (Pitfall 5) and submits {password, csrf_token} only; zero auth token in browser storage (SPA-03)
- [Phase 11-01]: Phase 11 foundation shipped — react-hook-form ^7.77 + zod ^4 (v4 API, resolver import `@hookform/resolvers/zod`) + @hookform/resolvers ^5 + vitest (node env, not jsdom); 5 shadcn components (dialog/tooltip/select/badge/popover) verified opaque on dark brand (Pitfall-9 gate Playwright-confirmed: DialogContent oklch(0.12 0.02 275), SelectContent oklch(0.17 0.03 275)). footgun() mode-aware (percent multiplies risk_value×max_stages; fixed_lot does NOT — riskValue is TOTAL across stages, Pitfall 6); makeSettingsSchema(maxLotSize) mirrors server caps (percent ≤5.0, fixed_lot ≤ per-account max_lot_size, ints 1-10/1-500/1-100, no cap on read-only max_open_trades — SUX-03). Package legitimacy T-11-SC approved (0 vulns, no postinstall hooks). Both pure fns vitest-proven (15 tests green).
- [Phase 11-02]: Five live-money mutation hooks shipped (frontend/src/hooks/) — useClose/useLevels/usePartialClose (PAGE-06), useEmergency (PAGE-07), useSettingsMutations (PAGE-08/SUX-01). Money-safe discipline baked in once: api()-only CSRF (no raw fetch — Pitfall 2/T-11-03), NO setQueryData (SC#1/Pitfall 1 — UI re-derives via invalidateQueries onSuccess), 401 handled by inherited global onAuthError, errors via shared errorMessage() into sonner (T-11-06). usePartialClose: absolute close_volume (D-04, no percent) + request_id useRef(crypto.randomUUID) reused on pure retries + regenerateRequestId on amount change + HttpError 409 → specific toast (Pitfall 3/T-11-04). useSettingsMutations.validate honors 200-on-invalid (no onSuccess/no throw; caller branches on data.valid — Pitfall 7). NOT vitest-unit-tested (node-env/pure-fn-only runner; @testing-library/react+jsdom not installed = excluded package install); gated by npm run build + grep acceptance — exercised by Wave-2 page plans.
- [Phase 11-06]: Overview (PAGE-05) shipped + Phase-11 routing/sidebar cutover. OverviewView is the live-money landing surface: 3 useQuery sources (overview/trading-status/stages, each refetchInterval 3000) + the embedded <PositionsView/>'s own ["positions"] poll. Red TRADING PAUSED banner (text-destructive) above the positions section when trading-status.paused. Per-account cards (overview_cards.html parity): Connected/Offline chip, Balance/Equity/Open-P&L via *_display, daily-trades yellow≥80%/red≥100%, margin-used ratio bar (margin/balance — Pitfall-5-exempt). Open Positions = rendered <PositionsView/> (SC#3 poll-safe modal/drilldown inherited wholesale, zero shared state). Pending Stages = top-5 active from GET /api/v2/stages (Open Question 2, no new endpoint). Emergency Kill Switch entry = Button asChild + <Link to="/emergency"> → KillSwitchView. router.tsx: /app index now renders OverviewView (was Navigate to /analytics); overview/positions/emergency routes added; pre-existing /app/settings route preserved. Sidebar: Positions→to:/positions, Settings→to:/settings (now live NavLinks). npm run build green; dev_dashboard.py NOT staged. Phase 11 feature-complete (all 4 live-money pages built + routed).
- [Phase 12-03]: CUT-03 HTMX/Jinja decommission landed in 4 grouped, independently-revertable commits (D-10): 143b7f0 dashboard.py surgery (HTML page/partial/SSE routes + Jinja setup + asset-manifest + legacy /login + dead legacy money routes deleted; -985/+43; the 6 api/-imported helpers — validate_settings_form/_compute_dry_run/_enrich_stage_for_ui/_client_ip/_password_hasher/app_settings — KEPT; _verify_auth + /logout repointed to /app/login per Pitfall 4), e14e11f templates/+Basecoat+HTMX-bridge delete (-2851), 35b4d4f Dockerfile Stage-1 css-build removal + Stage-3 COPY fix (Pitfall 1) + tailwind.config.js/input.css/_compat.css/build_css.sh delete + nginx SSE block removal (/login rate-limit preserved), 7cf93d0 HTMX test prune (test_ui_substrate/pending_stages_sse/settings_form/login_flow deleted; test_auth_session + test_api_csrf surgically pruned). Verified in python:3.12 container: import dashboard + import api OK, ALL_6_RESOLVE, post-teardown/cutover/auth guards 4-passed/22-skipped, full suite 227-passed/157-skipped (only 3 pre-existing out-of-scope MT5 REST-connector failures — logged to deferred-items.md, fail identically at 12-02 baseline), docker build green (Pitfall 1 avoided), SPA npm run build green. DEPLOY-AT-END deviation: post-cutover 7-day bake + operator GO (D-07/D-08) WAIVED for this run (operator pre-authorized); teardown code complete + guards green locally 2026-06-08; live bake + GO DEFERRED to single VPS end-to-end acceptance — no fabricated sign-offs. VPS deploy step: copy nginx/telebot.conf to /home/murx/shared/nginx/conf.d/ + docker exec shared-nginx nginx -s reload.
- [Phase 12-02]: CUT-02 per-page cutover landed. All 7 legacy @app.get page routes 303-redirect to /app/<page> (analytics 5322670 → signals 0cece3d → history be31662 → staged 3e7fbbd → overview 9560a45 → settings 22dd45d → positions e303675), root / flips /overview→/app/ as the FINAL commit 498114a — one page per commit (D-01), D-05 order, root LAST (D-02). Every route keeps Depends(_verify_auth) (T-12-04) and status_code=303 (T-12-05). Kill-switch (row 8, commit 1bf6f42) has no GET page — verified-then-decommissioned, no code change, gates the 12-03 /api/emergency-preview deletion. NO nginx/Dockerfile/template change, ZERO deletions (legacy reachable by direct URL for the bake; deletion is 12-03). DEPLOY-AT-END deviation: per-page blocking parity sign-off WAIVED by operator; checklist rows annotated "code complete + guard green locally; live sign-off DEFERRED to VPS end-to-end acceptance" (Summary tally code-complete:8/live-signed:0) — no fabricated signatures. test_unauth_redirects_to_app_login stays RED until 12-03 repoints _verify_auth→/app/login (Pitfall 4). Guard ran 8 skipped (Postgres absent) in python:3.12 container — green-or-skip bar.
- [Phase 12-01]: Wave-0 cutover guards shipped (no production code). CUT-01 confirmed satisfied by existing Phase-9 routing with ZERO code change — evidence is tests/test_spa_serving.py::test_api_not_shadowed_by_spa_mount (/api/v2 router registered before /app mount; green-or-skip). tests/test_cutover_redirects.py = CUT-02 guard (7 D-05 page rows 303->/app/<page> + unauth->/app/login), tests/test_post_teardown.py = CUT-03 guard (deleted /overview|/stream|/partials/positions real-404 + surviving /health|/app/|/api/v2|/->303/app/ + import-api MUST-SURVIVE-symbol guard). Both intentionally RED per-row until 12-02/12-03 land; collect-clean (16 items, exit 0) is the Wave-0 bar. 12-CUTOVER-CHECKLIST.md = D-04 operator parity sign-off (8 D-05-ordered rows; kill-switch row is verified-then-decommissioned, gates /api/emergency-preview deletion not a redirect). Tests run in python:3.12-slim container (host has no pytest, Postgres absent locally).
- [Phase 13-05]: EXEC2-06 direct-zone multi-stage shipped (commits 65e2f01 RED → 629e858 GREEN Task 1; 3551b58 RED → ac6b8e2 GREEN Task 2). `_handle_open` rewritten from the v1.0 single zone_mid full-fill into a per-account band scale-in mirroring `_handle_correlated_followup`: snapshot → compute_bands → create_staged_entries(awaiting_zone) → fetch price → fire at-arrival-crossed bands → arm the rest (NO resting limits, D2-01 → inherits D-21/D-14/D-24/D-25). KEY DECISION: direct-zone bands numbered 1..N (lowest = stage 1, unlike correlated 2..N) — call `compute_bands(max_stages+1)` to get N bands then re-base; gives the executor D-16 cascade a real telebot-{id}-s1 anchor that may never fill (verified safe executor.py:733-736, Pitfall 6). D2-04: max_stages=1 synthesizes ONE whole-zone Band(1, zone_low, zone_high) — no zone_mid fallback, no `no_bands` reuse (Pitfall 5). D2-02: only crossed bands fire at arrival; price outside zone → all arm. D2-14: pre-band `_check_stale` runs FIRST per account (price fetched once, reused) → moved-market arrival = clean skip with NO staged rows; D-14 per-band pre-flight stays the 2nd backstop. EXEC2-01 carry: every row persists signal_sl/signal_tp from the OPEN's own log_signal id. DEVIATIONS: (Rule 1) compute_bands(max_stages+1) to hit N stages; (Rule 1) updated 8 pre-EXEC2-06 tests that encoded the v1.0 single-fill/resting-limit contract (test_open_with_real_sl_unchanged + 7 in test_trade_manager_integration; all passed pre-plan at c1d8103, deliberately changed by EXEC2-06); (Rule 3) promoted _PricedDry/priced_connector/tm_with_store to conftest. (Rule 4 DEFERRED) staged mt5_comment is globally UNIQUE with no account discriminator → one signal_id across N accounts collides on stage-1 (PRE-EXISTING Phase-6 scheme, shared by correlated path, db.py:1023-1024; surfaced by making all standalone OPENs staged) — logged to deferred-items.md, recommend account-scoped-comment follow-up; failure-isolated + safe under single-account deploy-at-end. Tests: 81 passed (integration + staged_executor + trade_manager + safety_hooks) + 18 passed/1 skipped (staged_db/attribution/contract/schema) on dev Postgres tb13pg. DEPLOY-AT-END: live MT5 staged scale-in sign-off DEFERRED to single VPS end-to-end acceptance (operator-approved, mirrors 12-02/12-03/13-04); 5-step VPS smoke in 13-05-SUMMARY. Phase 13 ALL 6 EXEC2 gaps closed.
- [Phase 13-04]: EXEC2-05 orphan protective-TP (D2-09..D2-12) shipped (commit 6795e81). db.get_orphan_candidate_stage1s(window_seconds) is the DB-side window-expiry oracle (filled stage-1 + created_at < NOW()-window + live mt5_ticket + NOT EXISTS stage_number>=2 sibling) — the in-memory correlator pops the orphan on pairing so it cannot be queried at expiry (RESEARCH Open Q1). executor._run_orphan_protective_tp_watchdog runs FIRST each 10s _zone_watch_loop tick and self-fetches candidates (an orphan has NO siblings → never appears in get_active_stages, so the plan's inline-after-positions_by_comment sketch could never see it — Rule 3 structural deviation, but still NO new asyncio task: create_task count 5→5 unchanged). _attach_one_orphan_protective_tp: TP = entry ± default_sl_pips*pip_size, R=1:1 literal constant (grep tp_ratio = 0, no config knob, D2-10/D2-11); SL preserved (D-08); idempotent via reading position.tp and skipping non-zero (Open Q2, no schema); failure-isolated at 3 layers (mirrors stage-1-align); orphan_protective_tp log_signal audit row. 4 orphan tests GREEN in python:3.12 + dev-Postgres. Supersedes Phase 6 D-09. DEPLOY-AT-END: live MT5 modify/TP round-trip DEFERRED to single VPS end-to-end acceptance (operator-approved option (a), mirrors Plans 12-02/12-03) — 5-step VPS smoke in 13-04-SUMMARY + deferred-items.md; no fabricated live sign-off.
- [Phase 09-04]: Declarative react-router-dom 7 router (createBrowserRouter basename /app) in lockstep with Vite base + uvicorn StaticFiles mount (D-07); main.tsx wires QueryClientProvider over RouterProvider + root sonner Toaster; App.tsx boot guard GET /auth/me (200→shell, 401 delegated to the single global onAuthError, no competing redirect — single bounce, D-05/SPA-04); 224px AppShell + Telebot-cyan Sidebar (Overview live, 6 disabled-visible future links, Sign out logout POST) — cyan reserved for wordmark/active/focus only (D-07); THROWAWAY ProbeView proved SC#5 LIVE — useQuery(trading-status, refetchInterval 3000) vs useState input survived ≥2 refetch cycles unclobbered (D-08/SPA-05). Phase 9 manual gate APPROVED by human (cold login no-403, no localStorage token, deep-link reload, single 401 redirect, input survives refetches). Phase 9 complete — ready for verification.

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

Last activity: 2026-06-08 — Phase 13 Plan 05 (EXEC2-06 direct-zone multi-stage `_handle_open`) COMPLETE. 2 TDD tasks committed (65e2f01 RED + 629e858 GREEN Task 1; 3551b58 RED + ac6b8e2 GREEN Task 2). `_handle_open` rewritten into a per-account band scale-in mirroring `_handle_correlated_followup` (compute_bands → create_staged_entries → fire at-arrival-crossed bands → arm the rest; NO resting limits → inherits D-21/D-14/D-24/D-25). Direct-zone bands numbered 1..N (lowest = stage 1) via compute_bands(max_stages+1) then re-base — real telebot-{id}-s1 anchor that may never fill (safe executor.py:733-736). D2-04 max_stages=1 → ONE synthesized whole-zone band (no zone_mid, no no_bands). D2-02 only crossed bands fire at arrival. D2-14 pre-band _check_stale rejects moved-market arrivals before any staged row. Every row persists signal_sl/signal_tp. Deviations: Rule-1 compute_bands(max_stages+1) for N stages; Rule-1 updated 8 pre-EXEC2-06 tests encoding the v1.0 single-fill/resting-limit contract (all passed pre-plan at c1d8103); Rule-3 promoted staged fixtures to conftest; Rule-4 DEFERRED multi-account mt5_comment UNIQUE collision (pre-existing Phase-6 scheme → deferred-items.md, account-scoped-comment follow-up). 81 + 18-passed/1-skipped on dev Postgres tb13pg. DEPLOY-AT-END: live MT5 sign-off DEFERRED to single VPS end-to-end acceptance (5-step smoke in SUMMARY). Phase 13 code-complete (EXEC2-01..06 all closed). Resume file: .planning/phases/13-staged-entry-execution-correctness-and-direct-zone-multi-sta/13-05-SUMMARY.md. Next action: /gsd:verify-work 13, then VPS end-to-end acceptance (deferred live sign-offs for 13-04 + 13-05 + the multi-account comment follow-up).

Prior: 2026-06-08 — Phase 13 Plan 04 (EXEC2-05 orphan protective-TP) COMPLETE. 1 task committed (6795e81): db.get_orphan_candidate_stage1s DB-side window-expiry oracle + executor._run_orphan_protective_tp_watchdog (self-fetching, runs first each 10s _zone_watch_loop tick, NO new asyncio task — create_task 5→5) + _attach_one_orphan_protective_tp (R=1:1 TP=entry±default_sl_pips*pip_size, no config knob, SL preserved, idempotent via live position.tp skip, failure-isolated, orphan_protective_tp audit row). 4 orphan tests GREEN (python:3.12 + dev-Postgres tb13pg); 3 remaining failures are out-of-scope Plan-05 RED stubs (deferred-items.md). Structural deviation (Rule 3): watchdog self-fetches candidates because an orphan has no siblings and never appears in get_active_stages — the plan's inline sketch could not see it. Supersedes Phase 6 D-09. DEPLOY-AT-END: live MT5 sign-off DEFERRED to single VPS end-to-end acceptance (operator option (a), mirrors 12-02/12-03); 5-step VPS smoke in SUMMARY + deferred-items.md; no fabricated sign-off. Phase 13: 4/5 plans done (13-01/02/03/04); 13-05 (EXEC2-06 direct-zone multistage) remains. Resume file: .planning/phases/13-staged-entry-execution-correctness-and-direct-zone-multi-sta/13-04-SUMMARY.md. Next action: execute 13-05 (Wave 2, parallel to 13-04 — both depend on Wave 1).

Prior: 2026-06-08 — Phase 12 Plan 03 (HTMX/Jinja decommission, CUT-03) COMPLETE. 4 grouped, independently-revertable commits (D-10): 143b7f0 dashboard.py reduced to wiring (D-09; 6 api/-imported helpers kept, _verify_auth→/app/login), e14e11f templates/+Basecoat+HTMX-bridge delete, 35b4d4f Dockerfile Stage-1+Stage-3-COPY-fix (Pitfall 1) + tailwind/input/_compat/build_css delete + nginx SSE block removal, 7cf93d0 HTMX test prune. Verified in python:3.12 container: import dashboard + import api OK, ALL_6_RESOLVE, guards 4-passed/22-skipped, full suite 227-passed/157-skipped (only 3 pre-existing out-of-scope MT5 REST-connector fails — deferred-items.md), docker build green, SPA build green. DEPLOY-AT-END: post-cutover 7-day bake + operator GO WAIVED (operator pre-authorized); teardown code complete + guards green locally; live bake + GO DEFERRED to single VPS end-to-end acceptance — no fabricated sign-offs. Phase 12 (CUT-01/02/03) feature-complete; HTMX/Jinja stack fully decommissioned. v1.2 milestone code-complete. Next: VPS final deploy — copy nginx/telebot.conf to /home/murx/shared/nginx/conf.d/ + docker exec shared-nginx nginx -s reload; then the single live MT5-demo parity bake + operator GO (all 8 cutover rows incl. kill-switch) as end-to-end VPS acceptance. Resume file: .planning/phases/12-parallel-run-cutover-htmx-decommission/12-03-SUMMARY.md.

Prior: Phase 12 Plan 01 (Wave-0 cutover guards) COMPLETE. 3 tasks committed atomically (b7e9a88 test_cutover_redirects.py CUT-02 guard, 109af05 test_post_teardown.py CUT-03 guard, 789617c 12-CUTOVER-CHECKLIST.md D-04 sign-off). CUT-01 confirmed by existing routing (zero code change). Guards intentionally RED per-row until 12-02/12-03; collect-clean (16 items) verified in python:3.12 container.

Prior: Phase 11 Plan 06 (Wave 3 — Overview PAGE-05 + routing/sidebar cutover) COMPLETE. 2 tasks committed atomically (c8293a5 OverviewView, 4d75984 router+sidebar wiring). OverviewView composes the embedded PositionsView (SC#3 inherited), per-account cards, TRADING PAUSED banner, top-5 pending stages (no new endpoint), and an /emergency entry. /app index now lands on Overview; Positions + Settings are live NavLinks; /app/settings preserved. npm run build green; dev_dashboard.py NOT staged. Phase 11 feature-complete (all 6 plans shipped: PAGE-05/06/07/08 + SUX). Phase 10 still has its live-DB human verification gate outstanding; Phase 11 has its own wave-merge MANUAL browser gate (VPS + MT5 demo).
Resume file: .planning/phases/13-staged-entry-execution-correctness-and-direct-zone-multi-sta/13-CONTEXT.md
Next action: (a) wave-merge MANUAL browser verification on VPS + MT5 demo (TRADING PAUSED banner, account-card/positions/pending-stages parity vs legacy /, SC#3 open modal/drilldown survives ≥2 refetch cycles) + full gate `pytest tests/ -x && cd frontend && npm run build && npx vitest run`; then (b) Phase 12 — parallel-run cutover + HTMX decommission; and/or (c) complete Phase 10's live-DB human verification gate via /gsd-verify-work 10.
