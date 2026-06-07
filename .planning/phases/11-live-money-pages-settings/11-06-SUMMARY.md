---
phase: 11-live-money-pages-settings
plan: 06
subsystem: ui
tags: [react, tanstack-query, live-money, overview, polling, router, sidebar, capstone]

# Dependency graph
requires:
  - phase: 11-live-money-pages-settings
    plan: 03
    provides: PositionsView (PAGE-06) — the 3s-polling positions table + Edit modal/drilldown held in local state outside the poll subtree (SC#3), reused wholesale as the Open Positions section
  - phase: 11-live-money-pages-settings
    plan: 05
    provides: KillSwitchView (PAGE-07) — the /emergency route the Overview kill-switch entry navigates to
  - phase: 11-live-money-pages-settings
    plan: 04
    provides: SettingsView + the already-registered /app/settings route (preserved, not clobbered)
  - phase: 10-read-only-page-migration
    provides: StagedView polling template + active-stage card layout (reused for the pending-stages section), DirectionBadge, Loading/Empty/ErrorPanel state trio
  - phase: 09-spa-scaffold-auth-design-system
    provides: api() CSRF wrapper, queryClient polling defaults (refetchIntervalInBackground:false), router.tsx (createBrowserRouter basename "/app"), Sidebar NAV_ENTRIES shape, shadcn Button (asChild Slot)
  - phase: 08-json-api-foundation
    provides: GET /api/v2/overview (OverviewMeta), /trading-status (TradingStatus), /stages (StagesPayload) — all consumed read-only here
provides:
  - "OverviewView (PAGE-05) — the live-money landing surface: one useQuery per source (overview/trading-status/stages, 3s) + the embedded PositionsView poll, a red TRADING PAUSED banner, per-account cards, the open-positions table, a top-5 pending-stages card, and an Emergency Kill Switch entry"
  - "Router/Sidebar cutover — /app index now resolves to Overview (no longer the analytics redirect); Positions + Settings are live NavLinks; overview/positions/emergency routes registered; pre-existing /app/settings route preserved"
affects: [phase-11-complete, live-money-landing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Composition-over-duplication: Overview RENDERS <PositionsView/> as its Open Positions section rather than re-implementing the table — PositionsView owns its own [\"positions\"] 3s poll AND keeps its Edit modal + drilldown in local state portaled outside the polling subtree, so SC#3 (open modal/drilldown survives background refetch) is inherited for free with zero shared state"
    - "Multi-source poll page: one useQuery per source ([\"overview\"], [\"trading-status\"], [\"stages\"]) each refetchInterval 3000; the [\"trading-status\"] key is SHARED with KillSwitchView so the PAUSED banner and that page re-derive together on a paused change"
    - "Margin-used bar percentage = a dimensionless ratio (margin/balance × 100) off two BARE numerics — the Pitfall-5-exempt category (same as win_rate/elapsed/'Remaining after'); NEVER a re-format of a money *_display string"

key-files:
  created:
    - frontend/src/routes/OverviewView.tsx
  modified:
    - frontend/src/routes/router.tsx
    - frontend/src/components/shell/Sidebar.tsx

key-decisions:
  - "Open Positions section RENDERS <PositionsView/> (the whole shipped page component) rather than re-deriving a condensed DataTable — the plan grants 'reuse the PositionsView table (or a condensed DataTable — discretion)'. Rendering the component reuses its poll, its Close/Edit/drilldown wiring, and — critically — its SC#3 poll-safe local-state-outside-the-poll-subtree mechanism, so an open Edit modal/drilldown on Overview survives ≥2 background refetch cycles with no new code. The page-shell h2 'Positions' nests under the Overview 'Open Positions' SectionHeading (acceptable double-label; no parity copy violated)."
  - "Index resolves to Overview by rendering <OverviewView/> directly at index AND registering an explicit /overview path (both render the same component) — the simplest cutover that makes /app land on Overview while keeping /app/overview reachable. The Navigate import was removed (no longer used)."
  - "Margin-used bar computed client-side off bare margin/balance (a ratio), NOT from the margin_display/free_margin_display money strings — matches the legacy overview_cards.html margin bar (which computes (balance-free_margin)/balance) and stays Pitfall-5-safe. open_trades/daily_trades/risk_percent are bare counts/percentages rendered raw; all true money (balance/equity/Open P&L) renders the server *_display twin only."
  - "Emergency Kill Switch entry is a <Button asChild><Link to=/emergency> (destructive) — navigates to the shipped KillSwitchView where the two-step CONFIRM CLOSE ALL guard lives; no separate kill-switch nav entry per UI-SPEC."

requirements-completed: [PAGE-05]

# Metrics
duration: ~12min
completed: 2026-06-07
---

# Phase 11 Plan 06: Overview Page + Routing Cutover (PAGE-05) Summary

**The capstone of Phase 11 — OverviewView, the live-money landing surface that COMPOSES the already-shipped pieces (a red TRADING PAUSED banner from trading-status, per-account cards from overview, the embedded PositionsView table whose SC#3 poll-safe modal/drilldown is inherited wholesale, and a top-5 pending-stages card from the shipped GET /api/v2/stages — no new endpoint) with an Emergency Kill Switch entry — plus the routing/nav cutover that flips the /app index from the analytics pilot to Overview and makes Positions + Settings live NavLinks, leaving the pre-existing /app/settings route intact.**

## Performance
- **Duration:** ~12 min (2 tasks, sequential executor on main tree)
- **Tasks:** 2 (both autonomous, no checkpoints)
- **Files:** 1 created (OverviewView.tsx) + 2 modified (router.tsx, Sidebar.tsx)

## Accomplishments
- **Task 1 — OverviewView (PAGE-05):** Built the live-money landing surface. Three `useQuery`s (`["overview"]`, `["trading-status"]`, `["stages"]`) each `refetchInterval: 3000`; the `["positions"]` poll is owned by the embedded `<PositionsView/>` (not duplicated). A red `--destructive` TRADING PAUSED banner ("TRADING PAUSED" / "Kill switch active — no signals will be processed") renders above the Open Positions section whenever `trading-status.paused`. Per-account cards mirror `overview_cards.html` structure: name + Connected/Offline chip, Balance/Equity (`*_display`), Open P&L (`total_profit_display`, green/red by raw `total_profit`), Open Trades, Daily Trades (yellow ≥80% / red ≥100% off `daily_limit_pct`), Risk%, and a margin-used bar (a `margin/balance` ratio, Pitfall-5-exempt). Empty accounts → "No accounts configured." The Open Positions section renders `<PositionsView/>` (SC#3 inherited). The Pending Stages section renders the top-5 `active` stages from `GET /api/v2/stages` (RESEARCH Open Question 2 — reuse the shipped contract, NO new endpoint). An Emergency Kill Switch entry (`Button asChild` → `<Link to="/emergency">`, destructive) navigates to KillSwitchView.
- **Task 2 — Router + Sidebar cutover:** `router.tsx` imports OverviewView/PositionsView/KillSwitchView/SettingsView; registers child routes `overview`, `positions`, `emergency` (paths WITHOUT the `/app` prefix; basename adds it); the index child now renders `<OverviewView/>` (was `<Navigate to="/analytics" replace/>` — the `Navigate` import was removed). The pre-existing `/app/settings` route (registered by 11-04) was preserved untouched. `Sidebar.tsx` NAV_ENTRIES gained `to:"/positions"` and `to:"/settings"` so Positions + Settings render as live NavLinks via the generic branch (were disabled-visible spans).

## Task Commits
1. **Task 1: OverviewView landing surface (PAGE-05)** — `c8293a5` (feat)
2. **Task 2: router + sidebar wiring** — `4d75984` (feat)

**Plan metadata:** this SUMMARY commit (docs) — includes STATE.md + ROADMAP.md (sequential mode).

## Files Created/Modified
- `frontend/src/routes/OverviewView.tsx` (347 lines, created) — exports `OverviewView`. Three 3s-polling `useQuery`s + embedded `<PositionsView/>`; TRADING PAUSED banner; `AccountCard`/`PendingStageCard`/`CardRow`/`SectionHeading` helpers; destructive kill-switch entry `<Link to="/emergency">`. Every money value via `*_display`; the only client number is the margin-used ratio.
- `frontend/src/routes/router.tsx` (modified) — +4 imports, +3 child routes (overview/positions/emergency), index flipped to `<OverviewView/>`, `Navigate` import removed; `/app/settings` route preserved.
- `frontend/src/components/shell/Sidebar.tsx` (modified) — NAV_ENTRIES Positions→`to:"/positions"`, Settings→`to:"/settings"`.

## Decisions Made
- **Open Positions = rendered `<PositionsView/>`** (not a re-derived table) — reuses the poll, the Close/Edit/drilldown wiring, and the SC#3 poll-safe local-state mechanism with zero new code; plan grants the discretion.
- **Index renders `<OverviewView/>` directly** + an explicit `/overview` path (both same component) — simplest cutover that lands `/app` on Overview; `Navigate` import removed.
- **Margin-used bar off bare `margin`/`balance`** (a ratio) — matches legacy `overview_cards.html`, stays Pitfall-5-safe; all true money via `*_display`.
- **Kill-switch entry = `Button asChild` + `<Link to="/emergency">`** — navigates to the shipped two-step KillSwitchView; no separate nav entry (UI-SPEC).

## Deviations from Plan
None — plan executed exactly as written. No Rule 1–4 deviations; autonomous plan, no checkpoints reached. The `<sequential_execution>` constraints (do not clobber the existing /app/settings route, do not stage dev_dashboard.py) were honored.

## TDD Gate Compliance
Task 1 is marked `tdd="true"`, but — exactly as established in 11-02/11-03/11-05 — OverviewView is a JSX presentation/composition component with no isolatable pure-function logic, and `@testing-library/react`+jsdom are not installed (vitest is node-env/pure-fn-only per 11-01; installing the React test stack is an excluded package-install action requiring a checkpoint). The executable verification surface is the plan's `<verify>` block (`npm run build`) plus the `<acceptance_criteria>` grep assertions. RED was established (OverviewView.tsx absent + a green baseline build), then each task's build + grep gate was asserted GREEN before its commit. No separate `test(...)`/`feat(...)` RED/GREEN pair exists for this render-only artifact for that reason — the same documented compliance posture as the other Wave-2/3 page plans.

## must_haves Verification
- ✅ "Overview polls overview + trading-status + positions + stages (~3s) and is the operator's live-money landing surface" — three `useQuery`s at `refetchInterval:3000` (`overview`/`trading-status`/`stages`) + the embedded `<PositionsView/>`'s own `["positions"]` 3s poll; `/app` index resolves here.
- ✅ "A red TRADING PAUSED banner shows above the positions section whenever trading-status reports paused" — `{paused ? <div …text-destructive>TRADING PAUSED…</div> : null}` rendered immediately above the Open Positions `<section>`.
- ✅ "Overview composes the positions table, a pending-stages card (top-5 via GET /api/v2/stages), per-account cards, and an Emergency Kill Switch entry" — `<PositionsView/>` + `stages.data.active.slice(0,5)` + `AccountCard` map + `<Link to="/emergency">` button.
- ✅ "The /app index resolves to Overview; Positions and Settings are live nav links; the kill-switch route is reachable" — index element `<OverviewView/>`; Sidebar `to:"/positions"`/`to:"/settings"`; `emergency` child route registered.
- ✅ "An open Edit modal / drilldown on Overview survives ≥2 background refetch cycles (SC#3)" — inherited: the embedded PositionsView holds the Edit dialog + drilldown in local React state portaled outside the polling subtree; Overview shares no state with it. (Manual browser confirmation deferred to wave merge — requires live broker.)
- ✅ artifact `frontend/src/routes/OverviewView.tsx` (347 lines ≥ 60 min; contains "TRADING PAUSED").
- ✅ artifact `router.tsx` contains "OverviewView"; `key_links` OverviewView → overview/trading-status/positions/stages via `refetchInterval`, and router → OverviewView/PositionsView/KillSwitchView/SettingsView present.

## Threat Mitigations (plan §threat_model)
- ✅ **T-11-20 (UX-integrity — open modal/drilldown under poll):** the Open Positions section is the embedded `<PositionsView/>`, which holds its Edit modal + drilldown in local state outside the polling subtree (SC#3) — a 3s refetch cannot clobber typed SL/TP/lots. Overview adds no shared state.
- ✅ **T-11-21 (Tampering — Overview-initiated mutations):** the only mutations reachable from Overview are PositionsView's (close/levels/partial-close via the Wave-1 hooks → `api()`/CSRF) and the kill-switch entry, which only NAVIGATES to /emergency (the actual close-all confirm is the two-step guard in KillSwitchView). No new mutation surface.
- ✅ **T-11-22 (Information disclosure — account cards/positions render):** Overview reads only the server's `_display`-formatted data + bare counts/ratios; no client re-derivation of money — same read-only trust posture as the Phase-10 pages.

## Verification Results
- `cd frontend && npm run build` (`tsc -b && vite build`) exits 0 after each task and finally — 2016→ (Task 1) modules, 0 type errors; CSS grew 38.34→39.38 kB (Task 1 new classes) and JS grew 595.99→617.16 kB (Task 2 — the four newly-routed views bundled in), confirming the changes compiled in.
- Task-1 grep: 3× `refetchInterval: 3000`; `overview`/`trading-status`/`stages` query keys; `TRADING PAUSED` + `text-destructive` conditional on `paused`; `<Link to="/emergency">`; 16 `_display` usages; the only `toFixed` is the margin-used ratio (Pitfall-5-exempt), no `Intl`/`Math.round` on money.
- Task-2 grep: router imports + routes all four views (KillSwitchView at `emergency`), index renders OverviewView (no `Navigate`), `/app/settings` route preserved (`path: "settings"`), Sidebar `to:"/positions"` + `to:"/settings"`.
- MANUAL (browser, VPS + MT5 demo) — DEFERRED to wave merge: TRADING PAUSED banner shows when paused; account cards + positions + pending-stages render at parity vs legacy /; SC#3 open modal/drilldown on Overview survives ≥2 refetch cycles. Server-side `pytest tests/` (Phase 8 contracts) is green/shipped — assert at wave merge (needs the Python 3.12 container).
- `dev_dashboard.py` (pre-existing untracked file) was NOT staged.

## Known Stubs
None — OverviewView is fully wired to the real `/api/v2/overview`, `/trading-status`, `/stages` endpoints + the embedded PositionsView's `/positions` and per-position drilldown/mutation endpoints. No placeholder data, no hardcoded empties.

## Threat Flags
None — no new security surface beyond the plan's `<threat_model>`. The kill-switch entry only navigates; all live-money mutations flow through the existing Wave-1 hooks (`api()`/CSRF) via the embedded PositionsView. No new endpoint, auth path, or trust boundary.

## Issues Encountered
None. `node_modules` was present on the main tree (sequential mode), so no worktree dependency-install workaround was needed.

## User Setup Required
None.

## Next Phase Readiness
- Phase 11 is feature-complete: all four live-money pages (Positions PAGE-06, Settings PAGE-08, Kill Switch PAGE-07, Overview PAGE-05) are built and routed; `/app` lands on Overview; Positions + Settings are live nav links.
- Remaining before HTMX decommission: the wave-merge MANUAL browser verification on the VPS + MT5 demo (TRADING PAUSED banner, parity vs legacy /, SC#3) + the full `pytest tests/ -x && npm run build && npx vitest run` gate.

## Self-Check: PASSED

- `frontend/src/routes/OverviewView.tsx` verified present on disk (347 lines).
- Both task commits (`c8293a5`, `4d75984`) verified in git log.
- Final `npm run build` green (tsc -b + vite build, 0 type errors).
- `dev_dashboard.py` confirmed NOT staged.

---
*Phase: 11-live-money-pages-settings*
*Completed: 2026-06-07*
