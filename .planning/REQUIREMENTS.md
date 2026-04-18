# Requirements: Telebot v1.1 — Improved trade executions and UI

**Defined:** 2026-04-18
**Milestone:** v1.1 (focused — 3 phases)
**Core Value:** Preserve existing trading reliability while making the bot safer and more resilient — no regressions on live trading

**Source material:**
- Research synthesis: `.planning/research/SUMMARY.md` (commit `80f716e`)
- User brief (captured in PROJECT.md Current Milestone section)

**Lock-down items that will be resolved in `/gsd-discuss-phase` before planning:**
1. **Two-signal correlation model** — user brief is authoritative: initial text-only signal ("Gold buy now") opens 1 immediate market position; follow-up signal with zone/SL/TP opens additional positions as price enters the zone. Research temporarily explored a one-signal zone-watcher alternative; it's out.
2. **Daily-limit accounting rule** — 1 signal = 1 limit slot (recommended) vs. 1 stage = 1 slot.
3. **Schema discipline** — alembic (DBE-01) stays deferred to v1.2; v1.1 uses additive-only hand-written DDL.
4. **UI substrate** — Basecoat UI (`basecoat-css@0.3.3`) + Tailwind v3.4 standalone CLI on existing HTMX + Jinja (no SPA rewrite).

## v1.1 Requirements

### Staged Entry Execution

- [ ] **STAGE-01**: Signal parser recognizes text-only "now" signals (e.g. "Gold buy now", "XAU sell now") and emits a distinct signal type that does not require entry/SL/TP numerics
- [ ] **STAGE-02**: On a text-only "now" signal, bot opens exactly 1 market position per enabled account using that account's configured lot size or risk percentage, with a mandatory default SL (per-account setting) to prevent orphan exposure
- [ ] **STAGE-03**: Bot correlates a subsequent zone/SL/TP signal (same symbol, same direction, within a configurable correlation window — default 10 minutes) to the prior text-only signal and treats them as one trade sequence
- [ ] **STAGE-04**: On the correlated follow-up signal, bot opens up to `max_stages - 1` additional positions as price enters the declared zone, subject to per-account max positions, daily limits, and kill-switch state
- [ ] **STAGE-05**: The v1.0 duplicate-direction guard in `trade_manager.py` is bypassed for follow-up stages of the same correlated signal sequence (and only those)
- [ ] **STAGE-06**: Staged-entry state is persisted (`staged_entries` or equivalent table) and reconciled after MT5 reconnect so no stage is lost or duplicated across reconnect events
- [ ] **STAGE-07**: Kill switch drains all pending staged-entry rows (cancels watchers) before closing positions; no stage fills after a kill-switch trigger
- [ ] **STAGE-08**: Dashboard shows currently pending stages per account (symbol, direction, stages filled / total, price target band, elapsed time)
- [ ] **STAGE-09**: Each staged fill is attributed to its originating signal in the trades table so analytics can group by signal sequence

### Per-Account Settings

- [ ] **SET-01**: Per-account settings are persisted in the database (`account_settings` or equivalent table), editable at runtime, and supersede static `accounts.json` values at lookup time
- [ ] **SET-02**: Settings include at minimum: `risk_mode` (`percent` | `fixed_lot`), `risk_value` (percent of equity or fixed lot size like 0.04 / 0.1 / 0.5), `max_stages` per signal, `default_sl_pips` for text-only signals, `max_daily_trades`
- [ ] **SET-03**: Dashboard exposes a settings page with one form per account; changes require confirmation and are validated against server-side hard caps
- [ ] **SET-04**: Settings changes are recorded in an audit log (timestamp, field, old → new value, user identity from session)
- [ ] **SET-05**: Settings read by an in-flight staged-entry sequence are snapshotted at signal receipt; later settings edits do not mutate already-enqueued stages

### UI Foundation

- [ ] **UI-01**: Tailwind CSS is compiled via the standalone CLI at Docker image build time; the Tailwind Play CDN script is removed from `templates/base.html`
- [ ] **UI-02**: Basecoat UI (`basecoat-css`) is vendored into `static/` and provides shadcn-faithful components for buttons, forms, dialogs, tabs, and tables used by the dashboard
- [ ] **UI-03**: Tailwind content globs include `*.py` files that emit inline class strings (e.g. `dashboard.py` HTMLResponse fragments) so no class names are purged
- [ ] **UI-04**: CSS asset is deployed with a content-hashed filename to defeat browser cache on redeploy
- [ ] **UI-05**: Basecoat JS re-initializes after HTMX swaps so interactive components remain wired up on partial replacement

### Dashboard Redesign

- [ ] **DASH-01**: Every existing dashboard view (overview, positions, analytics, kill-switch control, daily-limit indicators) is restyled using Basecoat components; zero regressions in existing functionality
- [ ] **DASH-02**: Layout is mobile-responsive (usable on a phone for on-the-go monitoring) with a slide-over nav for small screens
- [ ] **DASH-03**: Positions view supports an inline drilldown per position showing fill history (initial fill + each staged fill), current P/L, and per-stage SL/TP
- [ ] **DASH-04**: Analytics view supports per-source deep-dive (win rate, profit factor, avg stages filled) and a time-range filter (7d, 30d, all)
- [ ] **DASH-05**: Trade history view supports filters by account, source, symbol, and date range

### Authentication

- [ ] **AUTH-01**: Dashboard is gated by a proper login page (styled form) that replaces HTTPBasic on all existing protected routes
- [ ] **AUTH-02**: Passwords are verified against an argon2 hash (`argon2-cffi`); plaintext `DASHBOARD_PASS` is migrated once and the plaintext env var is removed after migration
- [ ] **AUTH-03**: Sessions use Starlette `SessionMiddleware` with a server-generated `SESSION_SECRET`; bot refuses to start if `SESSION_SECRET` is unset or below 32 bytes of entropy
- [ ] **AUTH-04**: Login POST is CSRF-protected via double-submit cookie; existing HTMX routes continue to use the header-based CSRF pattern
- [ ] **AUTH-05**: Login has rate limiting (per-IP lockout after N failed attempts) with constant-time credential comparison to avoid username enumeration
- [ ] **AUTH-06**: Logout endpoint clears the session and redirects to the login page

## Future Requirements (v1.2+)

### Schema Evolution

- **DBE-01** (carried from v1.0 v2 section): Alembic migration tooling — v1.1 adds two tables via hand-written additive DDL; alembic becomes mandatory before any ALTER on live tables
- **SESSION-ROTATE**: `SESSION_SECRET` rotation with dual-key grace window so secret rotation doesn't log everyone out mid-action

### Monitoring (carried from v1.0 v2 section)

- **MON-01**: Structured JSON logging (structlog) for production debugging
- **MON-02**: Connection uptime metrics tracked and displayed on dashboard
- **MON-03**: Trade execution latency metrics (signal received → order placed)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Full SPA rewrite (React/Vue/Next/Nuxt) | Violates v1.0's "minimize new dependencies" constraint; Basecoat on HTMX meets the shadcn aesthetic goal |
| Martingale / averaging-down strategy | Staged entries fill pre-declared zones from a signal — they are NOT "open more on loss"; explicitly prohibited |
| Multi-user / role-based auth | Single admin user is sufficient; defer until there's a real second operator |
| Automated password reset flow | Single admin uses env-driven hash rotation; formal reset flow is overkill |
| Tailwind v4 migration | v4 introduced breaking changes; v1.1 locks on v3.4 for risk reduction |
| Live WebSocket market-data streaming inside the dashboard | Current HTMX polling is sufficient; streaming is a v1.2 nice-to-have |
| Signal-source auto-disable for low performers | Out of this milestone — analytics first, enforcement later |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| STAGE-01 | Phase 6 | Pending |
| STAGE-02 | Phase 6 | Pending |
| STAGE-03 | Phase 6 | Pending |
| STAGE-04 | Phase 6 | Pending |
| STAGE-05 | Phase 6 | Pending |
| STAGE-06 | Phase 6 | Pending |
| STAGE-07 | Phase 6 | Pending |
| STAGE-08 | Phase 6 | Pending |
| STAGE-09 | Phase 6 | Pending |
| SET-01 | Phase 5 | Pending |
| SET-02 | Phase 5 | Pending |
| SET-03 | Phase 6 | Pending |
| SET-04 | Phase 5 | Pending |
| SET-05 | Phase 5 | Pending |
| UI-01 | Phase 5 | Pending |
| UI-02 | Phase 5 | Pending |
| UI-03 | Phase 5 | Pending |
| UI-04 | Phase 5 | Pending |
| UI-05 | Phase 5 | Pending |
| DASH-01 | Phase 7 | Pending |
| DASH-02 | Phase 7 | Pending |
| DASH-03 | Phase 7 | Pending |
| DASH-04 | Phase 7 | Pending |
| DASH-05 | Phase 7 | Pending |
| AUTH-01 | Phase 5 | Pending |
| AUTH-02 | Phase 5 | Pending |
| AUTH-03 | Phase 5 | Pending |
| AUTH-04 | Phase 5 | Pending |
| AUTH-05 | Phase 5 | Pending |
| AUTH-06 | Phase 5 | Pending |

**Coverage:**
- v1.1 requirements: 30 total
- Mapped to phases: 30
- Unmapped: 0

**Distribution:**
- Phase 5 (Foundation — UI, auth, settings data): 15 requirements (UI-01..05, AUTH-01..06, SET-01, SET-02, SET-04, SET-05)
- Phase 6 (Staged entry execution): 10 requirements (STAGE-01..09, SET-03)
- Phase 7 (Dashboard redesign): 5 requirements (DASH-01..05)

---
*Requirements defined: 2026-04-18*
*Roadmap traceability filled: 2026-04-18 — 30/30 mapped.*
