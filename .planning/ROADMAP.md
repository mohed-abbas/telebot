# Roadmap: Telebot

## Completed Milestones

- **v1.0 — Hardening** (2026-03-22 → 2026-03-23): PostgreSQL migration, MT5 resilience, kill switch, execution correctness, observability, test suite. 4 phases, 13 plans, 30 requirements. [Details](milestones/v1.0-ROADMAP.md)

## Closing Milestone

### v1.1 — Improved trade executions and UI (closing — partially shipped)

**Started:** 2026-04-18
**Goal:** Stop missing trades via staged-entry strategy, modernize the dashboard with Basecoat + Tailwind, and replace HTTPBasic with a proper login form — without regressing v1.0 live-trading safety.
**Granularity:** coarse (3 phases, consolidated from 5 logical areas to respect the focused-milestone constraint)
**Coverage:** 30/30 v1.1 requirements mapped

**Transition status (set at v1.2 start):**

- **Phase 5** — shipped (UI substrate, auth, settings data model).
- **Phase 6 (staged entry)** — code complete; **CARRIED FORWARD** into v1.2 as an outstanding item (awaiting live VPS UAT with MT5 demo). Backend-only; unaffected by the frontend rewrite. NOT part of v1.2 scope.
- **Phase 7 (HTMX dashboard redesign)** — **SUPERSEDED / DESCOPED by v1.2.** The HTMX substrate proved glitchy (recurring refresh-race bugs: input clobbering, flicker, modal-mount issues). Remaining HTMX work is descoped (not completed); replaced wholesale by the React/Vite rewrite in v1.2.

## Active Milestone

### v1.2 — React/Vite dashboard rewrite

**Started:** 2026-06-01
**Goal:** Replace the FastAPI + HTMX + Jinja server-rendered dashboard with a separate React 19 + Vite SPA, eliminating the HTMX refresh-race bug class and moving to a stack the operator is fluent in — with zero regression to live-money controls.
**Locked stack (final):** React 19 · Vite 8 · @vitejs/plugin-react 6 · Tailwind CSS v4 (`@tailwindcss/vite` + `@theme`) · shadcn/ui · TanStack Query v5 · react-hook-form + zod · sonner · recharts · TypeScript.
**Granularity:** coarse (5 phases — JSON API → SPA scaffold → read-only page waves → live-money pages + settings → cutover; page migration split at the read-only/live-money safety boundary)
**Coverage:** 25/25 v1.2 requirements mapped

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3, 4): v1.0 milestone (complete)
- Integer phases (5, 6, 7): v1.1 milestone (closing — Phase 6 carried forward, Phase 7 superseded)
- Integer phases (8, 9, 10, 11, 12): v1.2 milestone (this milestone)
- Decimal phases (e.g. 8.1): reserved for urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

### v1.1 (closing)

- [x] **Phase 5: Foundation — UI substrate, auth, and settings data model** - Replace Play-CDN Tailwind with standalone-CLI build, vendor Basecoat UI, ship a styled login form backed by argon2 + sessions, and land the `account_settings` data layer with audit log.
- [~] **Phase 6: Staged entry execution** — CARRIED FORWARD into v1.2 (code complete 2026-04-20; awaiting VPS UAT with MT5 demo). Backend-only; unaffected by the frontend rewrite.
- [-] **Phase 7: Dashboard redesign (HTMX)** — SUPERSEDED / DESCOPED by v1.2. Remaining HTMX work replaced wholesale by the React/Vite rewrite.

### v1.2 (active)

- [x] **Phase 8: JSON API Foundation** - Refactor `dashboard.py`'s HTML-fragment endpoints into a versioned, curl/pytest-testable JSON API (`/api/v2`) with Pydantic models, double-submit CSRF, server-side number/timestamp formatting, and idempotent partial-close. Bot core untouched. (completed 2026-06-03)
- [x] **Phase 9: SPA Scaffold + Auth + Design System** - Stand up the Vite 8 + React 19 + Tailwind v4 + shadcn SPA served same-origin behind nginx, with session-cookie auth, global 401 redirect, and the TanStack-Query/local-form-state split that structurally kills the refresh-race bug class. No pages yet. (completed 2026-06-06)
- [x] **Phase 10: Read-only Page Migration (analytics pilot → signals → history → staged)** - Migrate the four no-live-money-action pages to the SPA at parity, starting with analytics as the read-only pipeline pilot. (completed 2026-06-06)
- [x] **Phase 11: Live-money Pages + Settings** - Migrate overview, positions (4 destructive actions), kill switch, and settings (folds SEED-001) using server-confirmed mutations only, disabled-while-pending, CSRF on every mutation, and client-side zod hard-cap mirroring. (all 6 plans shipped 2026-06-07; pending wave-merge MANUAL browser verification on VPS + MT5 demo)
- [ ] **Phase 12: Parallel-run Cutover + HTMX Decommission** - Run SPA and legacy HTMX in parallel behind nginx; cut over page-by-page gated on MT5-demo-verified parity; then remove HTMX/Jinja templates, the Tailwind standalone-CLI stage, and Basecoat vendor assets.

## Phase Details

### Phase 5: Foundation — UI substrate, auth, and settings data model

**Goal**: Operator can log in through a styled form, per-account runtime settings exist in the database with an audit trail, and every dashboard page is served from a production-grade Tailwind build with Basecoat primitives ready for later phases.
**Depends on**: Phase 4 (v1.0 Testing — complete)
**Requirements**: UI-01, UI-02, UI-03, UI-04, UI-05, AUTH-01, AUTH-02, AUTH-03, AUTH-04, AUTH-05, AUTH-06, SET-01, SET-02, SET-04, SET-05
**Success Criteria** (what must be TRUE):

  1. Dashboard serves its own CSS — no `cdn.tailwindcss.com` script in production HTML; stylesheet is a content-hashed file built from the standalone Tailwind CLI and Basecoat is vendored under `static/`
  2. Operator lands on a styled `/login` page (not a browser HTTPBasic prompt), authenticates with a password verified against an argon2 hash, and remains signed in across tabs and browser restarts via a signed session cookie
  3. Operator can log out from any page and is rate-limited after repeated failed attempts; bot refuses to start if `SESSION_SECRET` is missing or below the required entropy
  4. `account_settings` rows exist for every account in `accounts.json` on first boot, DB overrides supersede static JSON at lookup time, and every settings write produces an audit-log entry (field, old → new, timestamp, actor)
  5. Basecoat interactive components (dropdowns, tabs, dialogs) stay functional after HTMX partial swaps; no class names used by Python-side HTMX fragments are purged from the built CSS

**Plans**: 5 plans
Plans:

- [x] 05-01-PLAN.md — Data layer: 4 tables (accounts, account_settings, settings_audit, failed_login_attempts), SettingsStore abstraction, seed-from-JSON, migrate v1.0 callers (SET-01, SET-02, SET-04, SET-05)
- [x] 05-02-PLAN.md — UI substrate: Tailwind v3.4.19 standalone CLI build stage, Basecoat v0.3.3 vendoring, content-hashed CSS with manifest, compat shim for v1.0 classes, HTMX re-init bridge (UI-01..UI-05)
- [ ] 05-03-PLAN.md — Auth backend: argon2-cffi + SessionMiddleware wired, SESSION_SECRET/DASHBOARD_PASS_HASH fail-fast validation, _verify_auth swap to session cookie, hash_password CLI, asset_url helper + base.html cutover (AUTH-02, AUTH-03)
- [ ] 05-04-PLAN.md — /login + /logout + CSRF + rate-limit: styled login form, double-submit cookie CSRF, per-IP 5/15min lockout, nginx limit_req snippet, deployment runbook update (AUTH-01, AUTH-04, AUTH-05, AUTH-06)
- [x] 05-05-PLAN.md — Gap closure (UAT Gap #1): bump Tailwind standalone CLI v3.4.19 → v4.x (Basecoat v0.3.3 is v4-native + v4 resolves @import), v4 input.css syntax, regression guard in test_ui_substrate.py, operator-doc footgun notes ($→$$ env_file escape, .env.dev migration pointer, 8080 port collision comment)

**UI hint**: yes

### Phase 6: Staged entry execution

**Status**: CARRIED FORWARD into v1.2 (code complete; awaiting VPS UAT with MT5 demo). Backend-only; not part of v1.2 frontend scope; requirement mappings unchanged.
**Goal**: A text-only "Gold buy now" signal opens exactly one protected position immediately, and a correlated follow-up signal with zone/SL/TP opens additional positions as price enters the zone — without regressing any v1.0 safety primitive (kill switch, reconnect sync, daily limits, stale re-check, duplicate guard).
**Depends on**: Phase 5 (settings data model is a hard prerequisite — stages snapshot settings at signal receipt)
**Requirements**: STAGE-01, STAGE-02, STAGE-03, STAGE-04, STAGE-05, STAGE-06, STAGE-07, STAGE-08, STAGE-09, SET-03
**Success Criteria** (what must be TRUE):

  1. A text-only "Gold buy now" signal opens exactly one market position per enabled account with a non-zero default SL; no orphan position is ever submitted with `sl=0.0`
  2. A correlated follow-up signal (same symbol, same direction, within the configured window) opens up to `max_stages − 1` additional positions as price enters the declared zone, respecting per-account `max_stages`, daily limits, and kill-switch state
  3. Operator hitting the kill switch during an in-flight staged sequence drains all pending stages before any position is closed; no stage fires after kill-switch trigger, and `resume_trading` never un-cancels drained rows
  4. MT5 reconnect reconciles `staged_entries` against actual MT5 positions by comment-based idempotency key — no stage is duplicated, no stage is silently lost
  5. Dashboard shows a live pending-stages panel (symbol, direction, stages filled / total, price target band, elapsed time) and every staged fill is attributed to its originating signal in the trades table for per-source analytics
  6. Operator can edit per-account settings (risk mode, lot size, max stages, default SL pips) from a dashboard form; changes are validated against server-side hard caps and apply only to signals received after the edit

**Plans**: 5 plans
Plans:

- [ ] 06-01-PLAN.md — Data + parser + correlator: staged_entries DDL, signal_daily_counted idempotency table, db helpers, SignalType.OPEN_TEXT_ONLY + StagedEntryRecord, text-only "now" parser, SignalCorrelator module, bot.py wiring (STAGE-01, STAGE-03, STAGE-09)
- [ ] 06-02-PLAN.md — Stage-execution path: stage-aware _execute_open_on_account, default-SL hard reject, dup-guard bypass, daily-limit helper wrap, per-symbol cap, _handle_text_only_open + _handle_correlated_followup + compute_bands + in-zone-at-arrival (STAGE-02, STAGE-04, STAGE-05, STAGE-09)
- [ ] 06-03-PLAN.md — Per-account settings form: /settings GET + validate/confirm/revert POSTs + server-side hard caps + Basecoat tabs + two-step modal + audit timeline + revert button (SET-03)
- [ ] 06-04-PLAN.md — Safety hooks: _zone_watch_loop peer task + emergency_close drain + _sync_positions reconnect reconciliation + idempotency probe (STAGE-04, STAGE-06, STAGE-07)
- [ ] 06-05-PLAN.md — Pending-stages panel: SSE payload extension + /staged page + /partials/pending_stages polling fallback + overview.html include + templates + price-flash JS helper (STAGE-08)

### Phase 7: Dashboard redesign (HTMX)

**Status**: SUPERSEDED / DESCOPED by v1.2. The HTMX substrate proved glitchy (recurring refresh-race bugs); remaining HTMX work is replaced wholesale by the React/Vite rewrite (Phases 8–12). Completed plans (07-01..07-07) remain as historical record; this phase is NOT marked complete and its remaining work is not carried forward.
**Goal**: Every dashboard view is restyled on Basecoat components with richer drilldowns, the layout is usable on a phone, and operators can filter/analyze trade history by account, source, symbol, and date range — with zero regressions in any v1.0 or v1.1 functionality.
**Depends on**: Phase 5 (UI substrate) and Phase 6 (staged-entry data to display)
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05
**Success Criteria** (what must be TRUE):

  1. Every existing dashboard view (overview, positions, analytics, kill switch, daily-limit indicators, pending stages, settings, login) is rendered with Basecoat components; no existing functionality has regressed
  2. Dashboard is usable on a phone — sidebar collapses into a slide-over under `md`, tables adapt to card lists under `sm`, and all interactive controls remain reachable
  3. Operator can click a position row and see fill history (initial fill + each staged fill), current P/L, and per-stage SL/TP without leaving the positions view
  4. Analytics page supports per-source deep-dive (win rate, profit factor, avg stages filled) and a time-range filter (7d / 30d / all)
  5. Trade history view supports simultaneous filters by account, source, symbol, and date range

**Plans**: 8 plans
Plans:

- [x] 07-01-PLAN.md — Source tracking + mobile nav: source_name column on signals, log_signal() update, bot.py pass group_name, Basecoat sidebar drawer, sticky mobile header, page_title context (DASH-02)
- [x] 07-02-PLAN.md — Overview + positions restyle: Basecoat cards, btn-destructive kill switch, responsive table-to-card on mobile (DASH-01)
- [x] 07-03-PLAN.md — Positions drilldown: get_position_drilldown() query, accordion rows, fill history panel, signal attribution, live P/L (DASH-03)
- [x] 07-04-PLAN.md — Trade history filters: get_filtered_trades() query, inline filter bar, URL param persistence, responsive layout (DASH-05)
- [x] 07-05-PLAN.md — Analytics time/source filters: get_analytics_with_filters() query, pill tabs for time range, clickable source rows, per-source metrics (DASH-04)
- [x] 07-06-PLAN.md — Settings UX polish: toast notifications via OOB swap, inline help text, operator-legible labels (DASH-01, SEED-001)
- [x] 07-07-PLAN.md — Signals + staged pages restyle: responsive table-to-card, empty states, Basecoat components (DASH-01)
- [-] 07-08-PLAN.md — Compat shim removal + verification: SUPERSEDED — HTMX teardown now handled by v1.2 Phase 12 (CUT-03)

**UI hint**: yes

---

### Phase 8: JSON API Foundation

**Goal**: Every piece of dashboard data and every dashboard mutation is available as a versioned, curl/pytest-testable JSON contract (`/api/v2`) — display-ready and machine-precise — with double-submit CSRF and idempotent money operations, while the bot core (`executor.py`, `trade_manager.py`, `db.py`, `mt5_connector.py`) and the MT5 REST bridge stay byte-for-byte untouched.
**Depends on**: Phase 5 (auth + settings data layer shipped). Independent of Phases 6 and 7 — operates purely on the presentation/serialization layer.
**Requirements**: API-01, API-02, API-03, API-04, API-05
**Success Criteria** (what must be TRUE):

  1. Every read view (accounts, positions, history, signals, stages, analytics, overview meta) is retrievable via `GET /api/v2/...` returning Pydantic-modeled JSON; a `git diff` shows zero changes to `executor.py`, `trade_manager.py`, `db.py`, `mt5_connector.py`, and the MT5 bridge
  2. Every mutation (close, modify-levels, partial-close, kill-switch preview/confirm, resume, settings validate/confirm/revert) returns a structured `{success|error}` JSON envelope instead of an HTML fragment
  3. A `POST` to any mutation endpoint **without** a valid `X-CSRF-Token` (double-submit cookie, `secrets.compare_digest`) returns `403`, proven by an automated regression test; the existing login double-submit flow is unchanged and the new CSRF cookie name does not collide with `telebot_login_csrf`
  4. Every numeric/price/time field is returned both display-ready (server-formatted string) and machine-precise (raw numeric; times as ISO-8601 with UTC offset); a curl of a XAUUSD position shows correct pip-sized formatting with no client re-derivation required
  5. A duplicate partial-close submit (same request-id, absolute target volume) closes the position exactly once — the second submit is deduplicated server-side and cannot close the wrong amount

**Plans**: 5 plans (3 waves)
Plans:
**Wave 1**

- [x] 08-01-PLAN.md — Foundation: api/ package skeleton + router assembly, double-submit CSRF dep, shared formatter, Postgres idempotency module, full Pydantic schemas, dashboard wiring + accessors, Dockerfile COPY, Wave-0 test scaffolds (API-01, API-03, API-04)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 08-02-PLAN.md — Auth JSON contract: /auth/{login,logout,me,csrf}, telebot_csrf cookie, reused rate-limit, + the mandatory CSRF regression test (D-16 hard gate) (API-02, API-03)
- [x] 08-03-PLAN.md — Read endpoints: accounts/positions/drilldown/history/signals/stages/analytics/overview/trading-status/emergency-preview wrapping existing helpers with dual-value _display fields, + contract test (API-01, API-04)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 08-04-PLAN.md — Mutation actions: close/modify-levels/emergency/resume JSON envelopes + idempotent absolute-volume partial-close (replay/conflict/422), + idempotency regression test (API-02, API-05)
- [x] 08-05-PLAN.md — Settings mutations: GET settings + validate/confirm/revert as JSON with server-side hard caps + audit, + settings contract test (API-02)

**Research flag**: RESOLVED — idempotency storage = new PostgreSQL `idempotency_keys` table (D-01; Redis confirmed absent in both compose files); DDL lives in api/idempotency.py, NOT db.py.
**UI hint**: no

### Phase 9: SPA Scaffold + Auth + Design System

**Goal**: A Vite 8 + React 19 + Tailwind v4 + shadcn/ui single-page app is served same-origin behind nginx with no Node runtime in production, the operator can log in through it on the retained httpOnly session cookie, expired sessions redirect to login exactly once, and the server-state-vs-form-state separation (TanStack Query polling + local form state) is established as the convention every later page inherits — structurally eliminating the HTMX refresh-race bug class.
**Depends on**: Phase 8 (the JSON API contract, auth/CSRF endpoints, and number/time contracts the SPA consumes).
**Requirements**: SPA-01, SPA-02, SPA-03, SPA-04, SPA-05
**Success Criteria** (what must be TRUE):

  1. The Vite-built SPA is served as static files same-origin behind nginx (locked URL strategy + serving mechanism) and the production deployment runs with no Node process — only the built `dist/` is shipped
  2. The app renders with shadcn/ui components themed from the existing dark palette (`#252542` / `#1a1a2e` / `#0f0f1a`) mapped to Tailwind v4 `@theme` tokens; no `tailwind.config.js` exists
  3. Operator logs in through the SPA against the retained httpOnly session cookie; a browser check confirms no auth token is present in `localStorage`
  4. With an expired/cleared session, any authed view triggers a single global 401-handler redirect to the login view — no redirect loop, no repeated bounces
  5. A demonstrably wired TanStack Query background poll on a scaffold/probe view runs through ≥2 refetch cycles without clobbering an open input or modal, proving the server-state/form-state split before any real page is built

**Plans**: 4 plans (3 waves)
Plans:
**Wave 1**

- [x] 09-01-PLAN.md — Scaffold frontend/ (Vite 8 + React 19 + TS, base /app/, dev proxy), Tailwind v4 brand tokens (no config file), shadcn init + minimal component set + render/lockfile verify (SPA-01, SPA-02)
- [x] 09-02-PLAN.md — Backend serving: /app StaticFiles mount + deep-link fallback subclass, node:22-slim Dockerfile build stage, .dockerignore, Wave-0 serving test (SPA-01)

**Wave 2** *(blocked on 09-01)*

- [x] 09-03-PLAN.md — Data/auth layer: http.ts fetch wrapper (CSRF echo + HttpError + same-origin), queryClient global 401 handler + inherited polling defaults, cold-start CSRF seed + LoginView (SPA-03, SPA-04)

**Wave 3** *(blocked on 09-01 + 09-03)*

- [x] 09-04-PLAN.md — App shell + /app router + boot guard + throwaway polling probe proving the server-state/form-state split (SPA-04, SPA-05)
**Research flag**: RESOLVED — OQ1 CSRF names = telebot_csrf cookie / X-CSRF-Token header (Phase 8 D-15); OQ2 URL strategy = /app/ subpath (D-01); OQ3 serving = uvicorn StaticFiles + deep-link fallback subclass (D-02).
**UI hint**: yes

### Phase 10: Read-only Page Migration (analytics pilot → signals → history → staged)

**Goal**: The four pages that take no live-money action reach SPA parity, in ascending pipeline-validation order — analytics first as the read-only pilot that proves the full API + SPA + auth + nginx stack, then signals, history (with filters), and staged-entries — each verified against its live legacy page before that legacy route is eligible for decommission.
**Depends on**: Phase 9 (SPA scaffold, auth, QueryClient defaults, design tokens).
**Requirements**: PAGE-01, PAGE-02, PAGE-03, PAGE-04
**Success Criteria** (what must be TRUE):

  1. The SPA analytics page reaches parity — win rate, profit factor, per-source deep-dive — with numbers matching the legacy `/analytics` page on live data, validating the end-to-end pipeline in a no-live-money context
  2. The SPA signals page reaches parity with the legacy signals view
  3. The SPA history page reaches parity including all trade-history filters, with filter state reflected in the URL (bookmarkable) and `keepPreviousData` preventing flicker on refetch
  4. The SPA staged-entries page reaches parity (pending stages per account with live polling and elapsed-time display), matching the legacy staged view
  5. For each of the four pages, SPA output is verified equal to the live legacy page before that page is considered ready for cutover (no live-money action exists on any of these pages, so cutover risk is read-only)

**Plans**: 6 plans (4 waves)
Plans:
**Wave 1**

- [x] 10-01-PLAN.md — Analytics API widening (D-01): by_source/extremes/avg_stages/sources + contract test (PAGE-01)
- [x] 10-02-PLAN.md — Stages API widening (D-09): active started_at epoch (Pitfall-4-safe) + contract test (PAGE-04)

**Wave 2** *(blocked on Wave 1)*

- [x] 10-03-PLAN.md — Signals + History API parity widening (D-12): zone/sl/tp/details/source_name/status + contract tests (PAGE-02, PAGE-03) [depends 10-01: api/schemas.py]
- [x] 10-04-PLAN.md — Analytics pilot + shared primitives (DataTable, Loading/Empty/ErrorPanel, useUrlFilters) + route/sidebar wiring (PAGE-01) [depends 10-01]

**Wave 3** *(blocked on Wave 2)*

- [x] 10-05-PLAN.md — Signals + History SPA pages (URL filters, bookmarkable) reusing the primitives (PAGE-02, PAGE-03) [depends 10-03, 10-04]

**Wave 4** *(blocked on Wave 3)*

- [x] 10-06-PLAN.md — Staged SPA page (3s polling, card-per-account, useElapsed ticking timer) + ProbeView removal (PAGE-04) [depends 10-02, 10-04, 10-05]
**UI hint**: yes

### Phase 11: Live-money Pages + Settings

**Goal**: The highest-blast-radius surfaces — overview, positions (4 destructive actions), the two-step kill switch, and the SEED-001 settings page — reach SPA parity using the money-safe mutation discipline established in Phase 9: the UI changes state only after the server confirms success, every mutation carries CSRF, destructive buttons are disabled-while-pending, and client-side zod validation mirrors the server hard caps.
**Depends on**: Phase 10 (validated read-only pipeline + shared list/table patterns) and Phase 8 (idempotent partial-close API + structured mutation envelopes).
**Requirements**: PAGE-05, PAGE-06, PAGE-07, PAGE-08, SUX-01, SUX-02, SUX-03, SUX-04
**Success Criteria** (what must be TRUE):

  1. **Safety invariant — server-confirmed mutations only**: on positions, close / modify SL+TP / partial-close update or clear the UI **only** on server-confirmed success (no optimistic clear); on error the modal stays open with typed values preserved and surfaces the error toast; every destructive button is disabled-while-pending so a position can never appear closed while still live at the broker
  2. **Safety invariant — CSRF on every mutation**: every live-money POST (close, modify, partial-close, kill-switch confirm, settings confirm/revert) carries the `X-CSRF-Token` double-submit header and is rejected `403` without it — verified against the Phase 8 regression test
  3. Overview reaches parity with live polling (positions table + pending-stages card + kill-switch entry + TRADING PAUSED banner), and a background refetch through ≥2 cycles never clobbers an open positions drilldown or edit-levels modal
  4. The emergency kill switch reaches parity with its two-step preview → confirm flow (confirm disabled-while-pending), and partial-close uses absolute target volume + request-id so a double-fire cannot close the wrong amount
  5. Settings reaches parity — per-account form, two-step dangerous-change confirmation rendering a diff, audit timeline, and revert — with viewport-level sonner save/error/revert toasts (SUX-01), per-field help/tooltips including the live compounded-exposure footgun warning (SUX-02), react-hook-form + zod client validation mirroring the server hard-caps including mode-dependent and per-account `risk_value` caps (SUX-03), and operator-legible copywriting on labels/placeholders/confirmation text (SUX-04)

**Plans**: 6 plans (4 waves)
Plans:
**Wave 0**

- [x] 11-01-PLAN.md — Foundation: install rhf/zod/@hookform/resolvers + vitest + shadcn dialog/tooltip/select/badge/popover; mode-aware footgun.ts + settingsSchema.ts pure fns + their vitest units (SUX-02, SUX-03)

**Wave 1** *(blocked on 11-01)*

- [x] 11-02-PLAN.md — Live-money mutation hooks: useClose/useLevels/usePartialClose (request_id idempotency, no optimistic) + useEmergency + useSettingsMutations (validate branches on data.valid) (PAGE-06, PAGE-07, PAGE-08, SUX-01)

**Wave 2** *(blocked on 11-01 + 11-02)*

- [x] 11-03-PLAN.md — Positions page: polling DataTable + inline-confirm Close + combined Edit modal (two independent submits, absolute-lots partial-close, remaining-after) + drilldown, all poll-safe (PAGE-06)
- [x] 11-04-PLAN.md — Settings page: rhf+zod form (mode-aware caps/footgun, tooltips) + validate→confirm-diff→confirm + audit timeline + revert-latest + toasts (PAGE-08, SUX-01, SUX-02, SUX-03, SUX-04)
- [x] 11-05-PLAN.md — Emergency kill switch: two-step preview→confirm (disabled-while-pending, hidden when nothing to close) + resume (PAGE-07)

**Wave 3** *(blocked on 11-03 + 11-05)*

- [x] 11-06-PLAN.md — Overview page (multi-source poll + PAUSED banner + account cards + positions + pending-stages + kill-switch entry) + router/sidebar wiring (index→overview, live Positions/Settings) (PAGE-05)
**Research flag**: RESOLVED — partial-close uses absolute volume + client request_id (Phase 8 D-09/D-10/D-11 shipped). OQ1 revert = single "Revert last change" (API reverts latest-only, no audit_id — no new endpoint). OQ2 overview pending-stages = reuse shipped GET /api/v2/stages top-5.
**UI hint**: yes

### Phase 12: Parallel-run Cutover + HTMX Decommission

**Goal**: The SPA and the legacy HTMX dashboard run simultaneously behind one nginx instance sharing the session cookie, cutover happens one page at a time and is reversible at every step, each legacy route is removed only after its React replacement passes an MT5-demo parity gate, and after full cutover all HTMX/Jinja templates, the Tailwind standalone-CLI build stage, and Basecoat vendor assets are deleted.
**Depends on**: Phases 10 and 11 (every SPA page must exist and pass parity before its legacy twin can be decommissioned).
**Requirements**: CUT-01, CUT-02, CUT-03
**Success Criteria** (what must be TRUE):

  1. The SPA (`/app`) and the legacy HTMX dashboard (`/`) run in parallel behind nginx sharing the same session cookie, and rolling a single page back to legacy is one nginx edit (reversible at every step); the SSE/`proxy_buffering off` directives stay intact while any HTMX live page remains
  2. **Safety invariant — parity gate before decommission**: each legacy HTMX route is removed only after its React replacement is verified at parity against the MT5 demo (SPA numbers match legacy on live data; destructive actions confirmed against the demo broker; CSRF regression test green) — no page is decommissioned on "looks done"
  3. After full cutover the HTMX/Jinja templates directory, the legacy Tailwind standalone-CLI Dockerfile stage, the Basecoat vendor assets, and the `/stream` SSE endpoint (plus its nginx directives) are all removed, and `dashboard.py` is reduced to wiring (accessors + `include_router` + shared middleware)

**Plans**: 3 plans (3 waves)
Plans:
**Wave 1**

- [x] 12-01-PLAN.md — Wave-0 guards + CUT-01 confirm: `test_cutover_redirects.py` (303-target per page), `test_post_teardown.py` (deleted-404/surviving-200/import-api), `12-CUTOVER-CHECKLIST.md` (8 D-05-ordered parity rows); confirm parallel-run satisfied by Phase 9 (no code) (CUT-01) — COMPLETE 2026-06-07

**Wave 2** *(blocked on 12-01)*

- [x] 12-02-PLAN.md — Per-page cutover: `RedirectResponse('/app/<page>', 303)` one commit each in D-05 order (analytics→…→positions), kill-switch verified-only, root `/` flips LAST; gated on per-page MT5-demo parity sign-off (autonomous: false) (CUT-02) — COMPLETE 2026-06-07 (deploy-at-end: live parity sign-off deferred to single VPS end-to-end acceptance)

**Wave 3** *(blocked on 12-02; gated behind 7-day bake + operator GO)*

- [ ] 12-03-PLAN.md — HTMX teardown in 4 grouped commits (dashboard.py surgery keeping the 6 api/-imported helpers + `_verify_auth`→`/app/login`; templates/+Basecoat+JS-bridge; Dockerfile Stage-1+Stage-3-COPY-fix+nginx-SSE; HTMX test prune); bake-gated, autonomous: false (CUT-03)
**UI hint**: yes

## Progress

**Execution Order:**

- v1.1 phases execute in numeric order: 5 -> 6 -> 7 (Phase 6 carried forward; Phase 7 superseded)
- v1.2 phases execute in numeric order: 8 -> 9 -> 10 -> 11 -> 12

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 5. Foundation — UI, auth, settings data | 3/5 | In progress | - |
| 6. Staged entry execution | 5/5 | Carried forward (awaiting UAT) | - |
| 7. Dashboard redesign (HTMX) | 7/8 | Superseded by v1.2 | - |
| 8. JSON API Foundation | 5/5 | Complete   | 2026-06-03 |
| 9. SPA Scaffold + Auth + Design System | 4/4 | Complete   | 2026-06-06 |
| 10. Read-only Page Migration | 6/6 | Complete   | 2026-06-06 |
| 11. Live-money Pages + Settings | 6/6 | Complete    | 2026-06-07 |
| 12. Parallel-run Cutover + HTMX Decommission | 1/3 | In progress | - |
