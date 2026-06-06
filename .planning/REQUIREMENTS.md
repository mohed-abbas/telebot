# Requirements: Telebot v1.2 — React/Vite dashboard rewrite

**Defined:** 2026-06-01
**Milestone:** v1.2
**Core Value:** Preserve existing trading reliability while making the bot safer and more resilient — no regressions on live trading

**Source material:**
- Research synthesis: `.planning/research/SUMMARY.md` (commit `235bd53`)
- User brief (captured in PROJECT.md Current Milestone section)
- Folded seed: `.planning/seeds/SEED-001-settings-ux-polish.md`

**Locked stack decisions (FINAL — not for re-litigation):** React 19 · Vite 8 · shadcn/ui · Tailwind CSS v4. Vite SPA (static behind nginx) chosen over Next.js to avoid a Node runtime in production. Research corrected two version assumptions the roadmap absorbs: **Vite 8** (not 7) + `@vitejs/plugin-react` 6, and **Tailwind v4 is mandatory** for shadcn/ui + React 19 (no `tailwind.config.js`; use `@tailwindcss/vite` + `@theme` tokens — aligns with the backend's existing Tailwind v4.2.2).

**Open questions resolved during phase planning (not requirements scope):**
1. Exact CSRF cookie/header names — verify against `dashboard.py:128-135` (collision with existing `telebot_login_csrf`).
2. SPA URL strategy — `/app/` subpath (recommended) vs whitelisted paths — drives Vite `base` + nginx config; lock before SPA scaffold.
3. Static-serving mechanism — uvicorn `StaticFiles` mount (recommended) vs nginx `alias` + volume — lock before Dockerfile/nginx changes.
4. Idempotency storage for money-op dedupe (API-05) — in-memory vs Redis vs PostgreSQL — decide before the API actions layer.

---

## v1.2 Requirements

### API — JSON API Layer

- [x] **API-01**: All dashboard data is available via a versioned JSON API (`/api/v2`, `APIRouter`) with Pydantic response models that wrap the existing in-process helpers (`_get_all_positions`, `_get_accounts_overview`, `db.get_*`, etc.) — bot core (`executor.py`, `trade_manager.py`, `db.py`, `mt5_connector.py`) and the MT5 REST bridge are not modified
- [x] **API-02**: Mutating endpoints (close, modify levels, partial-close, kill switch, settings confirm/revert) return a structured JSON result (`{success, error, ...}`) instead of HTML fragments
- [x] **API-03**: CSRF protection on JSON mutations uses a double-submit cookie (readable `X-CSRF-Token` echoed from a cookie, `secrets.compare_digest`), independent of the HTMX `HX-Request` heuristic; login's existing double-submit flow is preserved verbatim; covered by a regression test
- [x] **API-04**: Numbers, prices, and timestamps are formatted server-side and sent display-ready plus machine-precise (ISO-8601 + timezone for times); the SPA never re-derives precision (guards the XAUUSD pip-size class of bug)
- [x] **API-05**: Partial-close is made safe against double-fire / retry — switched from percent-of-current-volume to an absolute volume, with a request-id idempotency guard so a duplicate submit cannot close the wrong amount

### SPA — Frontend Foundation

- [x] **SPA-01**: A Vite 8 + React 19 single-page app is scaffolded and served same-origin behind nginx as static files, with no Node runtime in production
- [x] **SPA-02**: Styling uses Tailwind v4 (`@tailwindcss/vite` + `@theme`) with shadcn/ui components; the existing dark palette (`#252542` / `#1a1a2e` / `#0f0f1a`) is mapped to theme tokens
- [x] **SPA-03**: Operator can log in through the SPA; the httpOnly session cookie auth is retained; no auth tokens are stored in `localStorage`
- [x] **SPA-04**: Expired or unauthenticated sessions are detected globally (401 handler) and redirect to the login view without redirect loops
- [ ] **SPA-05**: Server-state (TanStack Query background polling) is kept separate from form/UI state so a background refetch can never clobber an open input or modal — the structural fix for the HTMX refresh-race bug class

### PAGE — Page Migration (parity)

- [ ] **PAGE-01**: Analytics page (read-only pilot) reaches parity on the SPA — win rate, profit factor, per-source deep-dive
- [ ] **PAGE-02**: Signals page reaches parity on the SPA
- [ ] **PAGE-03**: History page reaches parity on the SPA, including trade-history filters
- [ ] **PAGE-04**: Staged-entries page reaches parity on the SPA (pending stages per account)
- [ ] **PAGE-05**: Overview page reaches parity on the SPA with live polling
- [ ] **PAGE-06**: Positions page reaches parity with safe live-money actions — close, modify SL+TP, partial-close — using server-confirmed mutations only (no optimistic clear), disabled-while-pending, and error toasts
- [ ] **PAGE-07**: Emergency kill switch reaches parity on the SPA with its two-step preview → confirm flow
- [ ] **PAGE-08**: Settings page reaches parity on the SPA — per-account form, two-step dangerous-change confirmation with diff, audit timeline, and revert

### SUX — Settings UX (folds SEED-001)

- [ ] **SUX-01**: Settings actions surface viewport-level save and error toasts (sonner) — success on confirm, explicit rejection on validation failure, revert confirmation
- [ ] **SUX-02**: Each settings field has inline help/tooltip describing what it controls, its units, recommended range, and its footgun (e.g. live compounded-exposure warning when `max_stages` × `risk_value` is high)
- [ ] **SUX-03**: Client-side validation (react-hook-form + zod) mirrors the server hard-caps, including the mode-dependent and per-account `risk_value` caps
- [ ] **SUX-04**: Copywriting pass on labels, placeholders, and confirmation-modal text for operator legibility (DB-column names → operator mental models with units)

### CUT — Cutover

- [ ] **CUT-01**: The SPA and the legacy HTMX dashboard run in parallel behind nginx (e.g. `/app` for the SPA, `/` for legacy) so cutover is incremental and reversible
- [ ] **CUT-02**: Each page is cut over individually; a legacy HTMX route is decommissioned only after its React replacement is verified at parity against the MT5 demo
- [ ] **CUT-03**: After full cutover, the HTMX/Jinja templates, Tailwind standalone-CLI build stage, and Basecoat vendor assets are removed

---

## Carried Forward from v1.1

These are not v1.2 requirements but remain open outstanding items (tracked in STATE.md, not mapped to v1.2 phases):

- **Phase 6 (staged-entry execution, STAGE-01..09 + SET-03)** — code complete, awaiting live VPS UAT with MT5 demo (`.planning/phases/06-staged-entry-execution/06-HUMAN-UAT.md`). Backend-only; unaffected by the frontend rewrite. Full v1.1 requirement detail archived at `.planning/milestones/v1.1-REQUIREMENTS.md`.
- **Phase 7 (HTMX dashboard redesign, DASH-01)** — SUPERSEDED by v1.2; remaining HTMX work descoped, not completed.

---

## Future Requirements (deferred)

- **alembic migrations (DBE-01)** — still deferred; v1.2 backend changes are additive JSON-API surface, no schema migration framework needed yet.
- **Real-time push (SSE/WebSocket)** — explicitly rejected for v1.2 (3s TanStack Query polling suffices for a single operator); revisit only if polling load becomes a problem.
- **Scoped OpenAPI docs for `/api/v2`** — `docs_url` is app-disabled; could be re-enabled scoped for internal use. Not load-bearing; deferred.

## Out of Scope (explicit exclusions)

| Excluded | Reason |
|----------|--------|
| Any new analytics, charts, or metrics beyond current parity | v1.2 is a substrate migration, not a feature expansion |
| Any new trading capability or signal-handling change | Bot core is untouched by design |
| Signal filtering / new dashboard views | New capability — belongs in a future milestone |
| Next.js / SSR / Node production runtime | Deliberately rejected — minimize-deps, internal single-operator tool |
| Auth tokens in `localStorage` / JWT | Security — httpOnly session cookie retained |
| Redux / external client-state store | TanStack Query covers server-state; React local state covers UI |
| Tailwind v3 | shadcn/ui + React 19 require v4; backend already on v4 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| API-01 | Phase 8 | Complete |
| API-02 | Phase 8 | Complete |
| API-03 | Phase 8 | Complete |
| API-04 | Phase 8 | Complete |
| API-05 | Phase 8 | Complete |
| SPA-01 | Phase 9 | Complete |
| SPA-02 | Phase 9 | Complete |
| SPA-03 | Phase 9 | Complete |
| SPA-04 | Phase 9 | Complete |
| SPA-05 | Phase 9 | Pending |
| PAGE-01 | Phase 10 | Pending |
| PAGE-02 | Phase 10 | Pending |
| PAGE-03 | Phase 10 | Pending |
| PAGE-04 | Phase 10 | Pending |
| PAGE-05 | Phase 11 | Pending |
| PAGE-06 | Phase 11 | Pending |
| PAGE-07 | Phase 11 | Pending |
| PAGE-08 | Phase 11 | Pending |
| SUX-01 | Phase 11 | Pending |
| SUX-02 | Phase 11 | Pending |
| SUX-03 | Phase 11 | Pending |
| SUX-04 | Phase 11 | Pending |
| CUT-01 | Phase 12 | Pending |
| CUT-02 | Phase 12 | Pending |
| CUT-03 | Phase 12 | Pending |

**Coverage:** 25/25 v1.2 requirements mapped, no orphans, no duplicates.

---
*Requirements defined: 2026-06-01 — milestone v1.2.*
*Traceability filled by roadmapper: 2026-06-01 — Phases 8–12.*
