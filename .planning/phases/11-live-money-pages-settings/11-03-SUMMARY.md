---
phase: 11-live-money-pages-settings
plan: 03
subsystem: ui
tags: [react, tanstack-query, live-money, positions, dialog, inline-confirm, partial-close, zod, footgun]

# Dependency graph
requires:
  - phase: 11-live-money-pages-settings
    plan: 01
    provides: shadcn dialog (opaque-verified), zod v4, Button/Input/Label primitives
  - phase: 11-live-money-pages-settings
    plan: 02
    provides: useClose / useLevels / usePartialClose money-safe mutation hooks
  - phase: 10-read-only-page-migration
    provides: StagedView polling template, DataTable Column model, DirectionBadge, Loading/Empty/ErrorPanel state trio
  - phase: 09-spa-scaffold-auth-design-system
    provides: api() CSRF wrapper, queryClient polling defaults (refetchIntervalInBackground:false), global onAuthError, sonner Toaster
provides:
  - "PositionsView (PAGE-06) — 3s-polling positions table with per-row Close (two-click confirm) + Edit + drilldown, all server-confirmed and poll-safe"
  - "EditPositionDialog — combined modal with TWO independent submits (Save SL/TP via useLevels + Close lots via usePartialClose), absolute-lots partial-close with live 'Remaining after' readout, stays open on error"
  - "InlineConfirm — reusable two-click destructive confirm (D-03) replacing legacy hx-confirm; disabled-while-pending"
  - "PositionDrilldown — fill-history + current P/L + signal-attribution drilldown reading GET /api/v2/positions/{account}/{ticket}"
affects: [11-05-overview, positions-page]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-click in-app destructive confirm (InlineConfirm button-morph variant — D-03): no window.confirm; armed prompt ✓/✕, ✓ disabled-while-pending guards against double-fire, ✕ recoverable; controlled by internal useState so a background refetch cannot reset it"
    - "Poll-safe modal/drilldown (SC#3): Edit-dialog open state + drilldown expand-state (a Set of open tickets) held in LOCAL React state, never the query cache; the shadcn Dialog portals out of the table/polling subtree so a 3s refetch never clobbers typed input or collapses an open drilldown"
    - "Server-confirmed-only row clear (SC#1): per-row Close scopes useClose.isPending to the closing ticket via close.variables?.ticket; the row clears ONLY when useClose's onSuccess invalidateQueries refetches — no optimistic setQueryData"
    - "Two independent submits in one modal (D-02): separate forms / buttons / isPending / api() CSRF calls / toasts; each passes a per-call onSuccess that closes the dialog, so the modal closes only on that submit's confirmed success and stays open (values preserved) on error"
    - "Absolute-lots partial-close (D-04): a numeric lots input with a live 'Remaining after: X.XX' client readout (a Pitfall-5-safe calc off two bare numerics) + a zod 0<value<volume check (lot-step rounded); request_id regenerated on every amount change so a pure retry hits the cached-200 replay — never a percent/slider"

key-files:
  created:
    - frontend/src/components/positions/InlineConfirm.tsx
    - frontend/src/components/positions/PositionDrilldown.tsx
    - frontend/src/components/positions/EditPositionDialog.tsx
    - frontend/src/routes/PositionsView.tsx
  modified: []

key-decisions:
  - "PositionsView hand-renders the table (reusing DataTable's Column<Position> model for header/cell/sign parity) rather than calling <DataTable> — DataTable has no expandable-row slot, and the per-row drilldown must render an extra <tr> immediately after each position row. The Column model stays the single source for the column shape (Pitfall-5 *_display rendering + raw-profit sign coloring), so parity is preserved."
  - "Per-row Close pending is scoped via close.variables?.ticket: useClose is a single page-level hook (one shared isPending), so only the row whose ticket matches the in-flight mutation shows 'Closing…' — avoids disabling/animating every row's Close during one close."
  - "Edit dialog closes via a per-call mutate onSuccess (mutate(vars, { onSuccess: () => onClose() })) layered ON TOP of the hook's own onSuccess (invalidate+toast) — so the dialog closes only on confirmed success and stays open with typed values on error, without the hook needing to know about the modal."
  - "InlineConfirm ships the in-place button-morph variant (D-03 'one only' — NOT the shadcn popover)."
  - "The partial-close 'Remaining after: X.XX' readout uses .toFixed(2) — this is the D-04-mandated live readout computed off two bare numerics (volume - entered), the same Pitfall-5-exempt category as the footgun/elapsed client calcs; it is NOT a re-format of a server *_display money string. The plan's verification grep set (percent/window.confirm/setQueryData) is clean."

requirements-completed: [PAGE-06]

# Metrics
duration: 14min
completed: 2026-06-07
---

# Phase 11 Plan 03: Positions Page (PAGE-06) Summary

**The highest-blast-radius interactive surface — a 3s-polling positions DataTable where every row carries a two-click destructive Close (InlineConfirm → useClose, server-confirmed clear only), an Edit button opening a combined modal with TWO independent submits (Save SL/TP + absolute-lots Close lots with a live "Remaining after" readout), and an expandable drilldown — with the Edit modal and drilldown held in local React state outside the polling subtree so a background refetch never clobbers typed input (SC#3).**

## Performance
- **Duration:** ~14 min (3 implementation tasks; included a one-time worktree `npm ci` + a native-binding fix)
- **Tasks:** 3 (all autonomous, no checkpoints)
- **Files:** 4 created (3 components + 1 route)

## Accomplishments
- **Task 1 — InlineConfirm + PositionDrilldown (D-03/D-01):** InlineConfirm is a two-click destructive button-morph (idle "Close" → armed "Confirm close #{ticket}? ✓ / ✕"; ✓ disabled-while-pending, ✕ recoverable) replacing the legacy `hx-confirm` browser dialog — no `window.confirm`. PositionDrilldown reads `GET /api/v2/positions/{account}/{ticket}` and lays out a Fill-History DataTable (Stage|Time|Lots|Band|SL at Fill|Status), a Current-P/L + Entry/SL/TP row, and a Signal-Source block with raw text in a `<details>` — every money/lot value via its `*_display` twin, sl/tp raw.
- **Task 2 — EditPositionDialog (D-01/D-02/D-04):** a shadcn Dialog (portaled outside the poll subtree) with a position-summary grid (`*_display`), a SL/TP `<form>` (cyan "Save SL/TP" → useLevels, only the changed fields), a divider, and a partial-close block (destructive "Close lots" wrapped in InlineConfirm → usePartialClose). Partial-close is **absolute lots** with a live "Remaining after: X.XX" readout + a zod `0 < value < volume` check; the request_id regenerates on every amount change. Each submit owns its `isPending`/CSRF call/toast; the modal stays open (values preserved) on error and closes only on confirmed success. No combined Save, no percent.
- **Task 3 — PositionsView (PAGE-06):** `useQuery(["positions"], …, refetchInterval 3000)` with the StagedView state-branch order (Loading / inline ErrorPanel / Empty "No open positions"). Columns at parity (Account|Symbol|Direction|Volume|Entry|SL|TP|P&L|Actions); P&L `cell=profit_display` + `sign=profit` for green/red; SL/TP raw. Actions render Close (InlineConfirm → useClose, per-row "Closing…", row clears only in onSuccess via invalidateQueries — never setQueryData) + Edit (opens EditPositionDialog) + a drilldown toggle. Drilldown expand-state (a Set of tickets) and the Edit-dialog state are local React state outside the polling subtree (SC#3); multiple drilldowns may be open.

## Task Commits
1. **Task 1: InlineConfirm + PositionDrilldown** — `75a10de` (feat)
2. **Task 2: EditPositionDialog** — `947765e` (feat)
3. **Task 3: PositionsView route** — `058d066` (feat)

**Plan metadata:** this SUMMARY commit.

## Files Created
- `frontend/src/components/positions/InlineConfirm.tsx` — two-click destructive confirm (D-03); button-morph variant; disabled-while-pending ✓; recoverable ✕; min-h-10; no `window.confirm`.
- `frontend/src/components/positions/PositionDrilldown.tsx` — reads `/api/v2/positions/{account}/{ticket}`; Fill-History DataTable + Current P/L + Entry/SL/TP + Signal Source (raw text in `<details>`); `*_display` twins, sl/tp raw.
- `frontend/src/components/positions/EditPositionDialog.tsx` — combined modal, two independent submits (useLevels + usePartialClose), absolute-lots partial-close + "Remaining after" + zod `0<value<volume`, Close lots wrapped in InlineConfirm; local-state inputs; closes only on confirmed success.
- `frontend/src/routes/PositionsView.tsx` — PAGE-06 polling table + row Close/Edit/drilldown wiring; inline ErrorPanel on read failure; local drilldown/dialog state outside the poll subtree.

## Decisions Made
- **Hand-rendered table reusing the `Column<Position>` model** — DataTable has no expandable-row slot, and the drilldown needs an extra `<tr>` after each row; the Column model still drives header/cell/sign so Pitfall-5 `*_display` rendering and raw-`profit` sign coloring are byte-equivalent to a `<DataTable>`.
- **Per-row Close pending via `close.variables?.ticket`** — one page-level `useClose` hook; only the closing row shows "Closing…".
- **Dialog closes via a per-call `mutate(vars, { onSuccess })`** layered on the hook's own onSuccess — modal closes only on confirmed success; stays open (values preserved) on error.
- **InlineConfirm ships the button-morph variant** (D-03 "one only", not the popover).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree had no node_modules — installed from the committed lockfile**
- **Found during:** baseline build (before Task 1)
- **Issue:** the fresh worktree had no `frontend/node_modules`, so `npm run build` failed (`tsc: command not found`). This is not a new package install — the lockfile (vetted/approved in 11-01) already pins every dependency.
- **Fix:** ran `npm ci` (materializes the committed lockfile only; 0 vulnerabilities, no package.json/lockfile change).
- **Files modified:** none tracked (node_modules is gitignored).

**2. [Rule 3 - Blocking] rolldown native binding missing after `npm ci` (npm optional-deps bug)**
- **Found during:** baseline build (before Task 1)
- **Issue:** after `npm ci`, `npm run build`'s vite step threw `Cannot find module '@rolldown/binding-darwin-arm64'` — the well-known npm optional-dependency placement bug (npm/cli#4828). `tsc -b` alone passed; only the vite bundle step was affected.
- **Fix:** copied the **same version** (1.0.3, already pinned in the worktree lockfile) of `@rolldown/binding-darwin-arm64` from the main checkout's `node_modules` into the worktree's `node_modules`. No tracked file changed; the binary matches the lockfile pin exactly.
- **Files modified:** none tracked (node_modules is gitignored).

**3. [Rule 3 - Blocking] PositionsView `DataTable` value-import unused (TS6133)**
- **Found during:** Task 3
- **Issue:** the hand-rendered table uses only the `Column` type, so importing the `DataTable` value tripped `tsc`'s noUnusedLocals.
- **Fix:** changed to a type-only import `import type { Column } from "@/components/data/DataTable"`.
- **Files modified:** `frontend/src/routes/PositionsView.tsx`.

## TDD Gate Compliance
Tasks are marked `tdd="true"`, but (as established in 11-02) these are JSX presentation components with no isolatable pure-function logic, and `@testing-library/react`+jsdom are not installed (vitest is node-env/pure-fn-only per 11-01; installing the React test stack is an excluded package-install action requiring a checkpoint). The executable verification surface is the plan's `<verify>` block (`npm run build`) plus the `<acceptance_criteria>` grep assertions. RED was established (the four target files absent + a green baseline build), then each task's build + grep gate was asserted GREEN before its commit. No `test(...)` / `feat(...)` RED/GREEN commit pair exists for these components for that reason — this is the same documented compliance posture as 11-02.

## must_haves Verification
- ✅ "Polls GET /api/v2/positions every ~3s, renders DataTable with Account|Symbol|Direction|Volume|Entry|SL|TP|P&L|Actions at parity" — `useQuery(["positions"], refetchInterval:3000)`; columns built from the `Column<Position>` model in the parity order; build green.
- ✅ "Each row has Close (destructive, inline two-click) + Edit; read-load failure shows inline ErrorPanel (not toast)" — Actions column renders `<InlineConfirm>` + Edit `<Button>`; `isError` branch renders `<ErrorPanel … />`, no toast in the view.
- ✅ "Edit modal holds two independent submits, stays open on error with typed values preserved, closes only on confirmed success" — separate `handleSaveLevels`/`handleCloseLots`, each `mutate(vars, { onSuccess: () => onClose() })`; on error the hook toasts and `onClose` is never called.
- ✅ "Partial-close types absolute lots with a live 'Remaining after: X.XX' readout — no percent/slider" — numeric lots input + `Remaining after: {remainingAfter.toFixed(2)}`; grep clean of code-level `percent`.
- ✅ "Edit modal + drilldown render outside the polling subtree (local state) so refetch never clobbers typed input (SC#3)" — `editing` (dialog) + `openTickets` Set (drilldown) are `useState`; the shadcn Dialog portals out; drilldown is its own keyed query mounted by local state.

## Verification Results
- `cd frontend && npm run build` exits 0 (tsc -b + vite build green) after each task and finally.
- grep over `routes/PositionsView.tsx` + `components/positions/`: no code-level `percent`, `window.confirm`, or `setQueryData` (only doc-comment references).
- MANUAL (VPS + MT5 demo) — DEFERRED to wave merge (require live broker): SC#1 row clears only after 200; forced error keeps modal open with typed values; SC#3 modal+drilldown survive ≥2 refetch cycles; 409 toast on partial-close id-reuse-diff-params. `pytest test_api_idempotency.py` / `test_api_csrf.py` are server-side (Phase 8, already green) — assert at wave merge.

## Known Stubs
None — all four artifacts are wired to their real `/api/v2` endpoints (positions list, drilldown, close/levels/close-partial via the Wave-1 hooks). No placeholder data, no hardcoded empties.

## Threat Flags
None — no security surface introduced beyond the plan's `<threat_model>`. All three live-money mutations route through the existing `api()` (CSRF-echoing) via the Wave-1 hooks; no new endpoint, auth path, or trust boundary.

## Issues Encountered
The fresh worktree lacked `node_modules` and hit the npm optional-dependency placement bug for the rolldown native binding — both resolved without any tracked-file change (documented under Deviations). No code-logic issues.

## User Setup Required
None.

## Next Phase Readiness
- 11-05 (Overview, PAGE-05) can reuse the Positions table / drilldown surface for its open-positions panel.
- Route + Sidebar wiring (router.tsx flip + the Positions NavLink) is intentionally OUT of this plan's scope (`files_modified` lists only the four route/component files) — it lands with the router-wiring plan.

## Self-Check: PASSED

All 4 created files verified present on disk; all 3 task commits (`75a10de`, `947765e`, `058d066`) verified in git log; final `npm run build` green.

---
*Phase: 11-live-money-pages-settings*
*Completed: 2026-06-07*
