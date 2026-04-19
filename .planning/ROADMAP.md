# Roadmap: Telebot

## Completed Milestones

- **v1.0 — Hardening** (2026-03-22 → 2026-03-23): PostgreSQL migration, MT5 resilience, kill switch, execution correctness, observability, test suite. 4 phases, 13 plans, 30 requirements. [Details](milestones/v1.0-ROADMAP.md)

## Active Milestone

### v1.1 — Improved trade executions and UI

**Started:** 2026-04-18
**Goal:** Stop missing trades via staged-entry strategy, modernize the dashboard with Basecoat + Tailwind, and replace HTTPBasic with a proper login form — without regressing v1.0 live-trading safety.
**Granularity:** coarse (3 phases, consolidated from 5 logical areas to respect the focused-milestone constraint)
**Coverage:** 30/30 v1.1 requirements mapped

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3, 4): v1.0 milestone (complete)
- Integer phases (5, 6, 7): v1.1 milestone (this milestone)
- Decimal phases (e.g. 5.1): reserved for urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 5: Foundation — UI substrate, auth, and settings data model** - Replace Play-CDN Tailwind with standalone-CLI build, vendor Basecoat UI, ship a styled login form backed by argon2 + sessions, and land the `account_settings` data layer with audit log. No staged-entry execution yet — just the prerequisites.
- [ ] **Phase 6: Staged entry execution** - Text-only signal parser, two-signal correlation, staged execution engine with kill-switch drain and reconnect reconciliation, plus a dashboard pending-stages panel. Isolated to keep this live-money phase testable.
- [ ] **Phase 7: Dashboard redesign** - Full restyle of every dashboard view on Basecoat components, mobile-responsive layout, positions drilldown, per-source analytics deep-dive, and trade-history filters.

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
**Plans**: 4 plans
Plans:
- [x] 05-01-PLAN.md — Data layer: 4 tables (accounts, account_settings, settings_audit, failed_login_attempts), SettingsStore abstraction, seed-from-JSON, migrate v1.0 callers (SET-01, SET-02, SET-04, SET-05)
- [x] 05-02-PLAN.md — UI substrate: Tailwind v3.4.19 standalone CLI build stage, Basecoat v0.3.3 vendoring, content-hashed CSS with manifest, compat shim for v1.0 classes, HTMX re-init bridge (UI-01..UI-05)
- [ ] 05-03-PLAN.md — Auth backend: argon2-cffi + SessionMiddleware wired, SESSION_SECRET/DASHBOARD_PASS_HASH fail-fast validation, _verify_auth swap to session cookie, hash_password CLI, asset_url helper + base.html cutover (AUTH-02, AUTH-03)
- [ ] 05-04-PLAN.md — /login + /logout + CSRF + rate-limit: styled login form, double-submit cookie CSRF, per-IP 5/15min lockout, nginx limit_req snippet, deployment runbook update (AUTH-01, AUTH-04, AUTH-05, AUTH-06)
**UI hint**: yes

### Phase 6: Staged entry execution
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
**Plans**: TBD

### Phase 7: Dashboard redesign
**Goal**: Every dashboard view is restyled on Basecoat components with richer drilldowns, the layout is usable on a phone, and operators can filter/analyze trade history by account, source, symbol, and date range — with zero regressions in any v1.0 or v1.1 functionality.
**Depends on**: Phase 5 (UI substrate) and Phase 6 (staged-entry data to display)
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05
**Success Criteria** (what must be TRUE):
  1. Every existing dashboard view (overview, positions, analytics, kill switch, daily-limit indicators, pending stages, settings, login) is rendered with Basecoat components; no existing functionality has regressed
  2. Dashboard is usable on a phone — sidebar collapses into a slide-over under `md`, tables adapt to card lists under `sm`, and all interactive controls remain reachable
  3. Operator can click a position row and see fill history (initial fill + each staged fill), current P/L, and per-stage SL/TP without leaving the positions view
  4. Analytics page supports per-source deep-dive (win rate, profit factor, avg stages filled) and a time-range filter (7d / 30d / all)
  5. Trade history view supports simultaneous filters by account, source, symbol, and date range
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
v1.1 phases execute in numeric order: 5 -> 6 -> 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 5. Foundation — UI, auth, settings data | 2/4 | In progress | - |
| 6. Staged entry execution | 0/? | Not started | - |
| 7. Dashboard redesign | 0/? | Not started | - |
