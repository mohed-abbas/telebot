---
phase: 11-live-money-pages-settings
plan: 05
subsystem: ui
tags: [tanstack-query, kill-switch, live-money, destructive, two-step-confirm, csrf, footgun]

# Dependency graph
requires:
  - phase: 11-live-money-pages-settings
    plan: 01
    provides: opaque-verified shadcn components + react-hook-form/zod/vitest foundation (Pitfall-9 gate cleared)
  - phase: 11-live-money-pages-settings
    plan: 02
    provides: useEmergency() — close + resume mutations (api()/CSRF, no setQueryData, invalidate overview/trading-status/positions on server-confirmed success)
  - phase: 09-spa-scaffold-auth-design-system
    provides: api() CSRF fetch wrapper, ErrorPanel/errorMessage envelope parser, Loading skeleton, shadcn Button (destructive + default variants), sonner Toaster
  - phase: 10-read-only-page-migration
    provides: StagedView read pattern (useQuery Loading/ErrorPanel branch order, page shell)
provides:
  - "KillSwitchView (PAGE-07) — two-step preview->confirm kill switch: reads emergency/preview counts + trading-status, arms CONFIRM CLOSE ALL (disabled-while-pending), hides confirm when nothing to close, Resume Trading while paused"
affects: [11-06, overview-page]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-step destructive guard in local React useState (armed flag): step 1 preview card → arm → step 2 CONFIRM CLOSE ALL; 'Keep trading active' disarms. The arm/disarm is local UI state (T-11-17); the close itself is server-confirmed only (no optimistic state — SC#1), the paused pill and counts re-derive via the hook's invalidateQueries"
    - "Destructive button discipline: variant=destructive size=default (UI-SPEC min-h floor), disabled={close.isPending} with label morph CONFIRM CLOSE ALL -> Closing all... (LoginView submit-disabled-while-pending parity) — a double-click cannot re-fire"
    - "Conditional-action visibility: confirm action HIDDEN when open_positions==0 && pending_orders==0 (T-11-19, legacy {% if count>0 %} parity); Resume Trading shown ONLY while trading-status.paused"

key-files:
  created:
    - frontend/src/routes/KillSwitchView.tsx
  modified: []

key-decisions:
  - "Router/Overview wiring is OUT of scope for this plan — files_modified lists only KillSwitchView.tsx, and the kill-switch entry button + route registration belong with the Overview page (11-06 / PAGE-05). This plan ships the self-contained route component so it can build in parallel with Positions (11-03) and Settings (11-04)."
  - "The two-step flow is implemented as an in-app armed-state morph (local useState), not a shadcn Dialog: parity with the legacy kill_switch_preview.html which is itself an inline preview card with a 'Cancel' escape, and it keeps the destructive confirm in the same red card the operator is reading (no modal indirection). 'Keep trading active' is the non-destructive escape (disarm)."
  - "No vitest unit for this page: vitest is node-env / pure-fn-only (11-01 precedent) and @testing-library/react + jsdom are not installed (a package-install action, excluded from auto-fix). The executable gate is `npm run build` (tsc -b + vite build) + the plan's grep acceptance assertions — both green."
  - "Type-checked + built via a TEMPORARY symlink of the shared checkout's node_modules into the worktree (the worktree has no installed deps; `npm install` is an excluded package-install action). The symlink and dist/ were removed before staging — neither was committed. Build ran the REAL tsconfig + vite config against the full dependency graph (1924 modules transformed, 0 type errors)."

requirements-completed: [PAGE-07]

# Metrics
duration: ~6min
completed: 2026-06-07
---

# Phase 11 Plan 05: Emergency Kill Switch Page (PAGE-07) Summary

**The Emergency Kill Switch route (PAGE-07) — a two-step preview→confirm flow that reads the open-positions + pending-orders counts that WILL be closed, requires an explicit armed CONFIRM CLOSE ALL (variant=destructive, disabled-while-pending, hidden when nothing to close), offers Resume Trading (cyan) only while paused, and stays server-confirmed (no optimistic state) by deferring entirely to useEmergency's invalidateQueries — the single most consequential destructive action, closing ALL positions, cancelling ALL orders, and pausing trading.**

## Performance
- **Started:** 2026-06-07 (worktree wave 2, parallel executor)
- **Tasks:** 1 (autonomous, no checkpoints)
- **Files:** 1 created (frontend/src/routes/KillSwitchView.tsx)

## Accomplishments
- **Task 1 — KillSwitchView (PAGE-07):** Built the kill-switch route. Reads `GET /api/v2/emergency/preview` (→ `{open_positions, pending_orders, accounts[]}`) and `GET /api/v2/trading-status` (→ `{paused, status}`) via `useQuery` using the StagedView Loading/ErrorPanel branch order (isPending → `<Loading>`, isError → inline `<ErrorPanel onRetry={refetch}>`). Renders a red `--destructive` card (border-destructive/50) with Open Positions + Pending Orders count rows and the warning body. Two-step confirm via a local `armed` flag: step 1 entry button arms → step 2 `CONFIRM CLOSE ALL` (`variant="destructive"`, `size="default"`, `disabled={close.isPending}` → "Closing all…") wired to `useEmergency().close`; "Keep trading active" disarms back to the preview without closing. The confirm action is hidden entirely when `open_positions === 0 && pending_orders === 0`. "Resume Trading" (`variant="default"` cyan, `disabled={resume.isPending}` → "Resuming…") wired to `useEmergency().resume`, rendered only when `trading-status.paused`.

## Task Commits
1. **Task 1: KillSwitchView — preview read + two-step confirm + resume (PAGE-07)** — `bafa73a` (feat)

**Plan metadata:** this SUMMARY commit (docs). STATE.md / ROADMAP.md are NOT touched — worktree mode; the orchestrator updates shared files centrally after merge.

## Files Created
- `frontend/src/routes/KillSwitchView.tsx` (183 lines) — exports `KillSwitchView`. Two `useQuery` reads (`["emergency-preview"]`, `["trading-status"]`), local `armed` two-step guard, `useEmergency().close` / `.resume`, conditional confirm visibility, conditional Resume visibility. No `setQueryData`, no raw `fetch` (all mutation traffic via the hook → `api()`/CSRF).

## Decisions Made
- **Scope:** only `KillSwitchView.tsx` (per `files_modified`). Router registration + the Overview kill-switch entry button are 11-06 / PAGE-05 work; shipping the route as a standalone component keeps this plan parallel-safe with 11-03 / 11-04.
- **Two-step UX as an in-app armed-state morph** (local `useState`), not a Dialog — parity with the legacy inline `kill_switch_preview.html` card + its Cancel escape; keeps the destructive confirm inside the same red card. "Keep trading active" = the non-destructive disarm.
- **No optimistic state** — the page holds no copy of the counts/pause beyond `useQuery`'s server cache; `useEmergency` invalidates `overview` / `trading-status` / `positions` on server-confirmed success, so the UI re-derives only after the server confirms (SC#1 / Pitfall 1).
- **Verification surface:** `npm run build` + grep acceptance assertions (no jsdom/testing-library; package-install excluded). Built via a temporary shared-`node_modules` symlink (removed before staging).

## Deviations from Plan
None — plan executed exactly as written. No Rule 1–4 deviations; autonomous plan, no checkpoints reached.

## TDD Gate Compliance
The task is `tdd="true"`, but (as in 11-02) the only executable verification surface for a route component is `npm run build` (`tsc -b && vite build`) plus the `<acceptance_criteria>` grep assertions — the page cannot be rendered/asserted without `@testing-library/react` + jsdom (not installed; installing them is an excluded package-install action requiring a checkpoint). RED was established first (KillSwitchView.tsx absent, baseline `npm run build` green), then GREEN was proven before the single commit: the real `tsc -b && vite build` passed (1924 modules, 0 type errors, CSS bundle grew 36.45→36.75 kB confirming the new classes compiled in) and every acceptance grep passed. There is no isolatable pure-function logic in this view to RED/GREEN as a separate `test(...)` commit, so the gate is a single `feat(...)` commit gated by build + acceptance — consistent with the 11-02 precedent for render-only Wave-2 artifacts.

## must_haves Verification
- ✅ "Reads GET /api/v2/emergency/preview and renders a red card with the open-positions + pending-orders counts" — `useQuery(["emergency-preview"], api("/api/v2/emergency/preview"))`; red `border-destructive/50 bg-card` card with `Open Positions` + `Pending Orders` `CountRow`s.
- ✅ "Confirm runs a two-step flow: preview → CONFIRM CLOSE ALL (disabled-while-pending) → POST /api/v2/emergency/close" — `armed` flag gates the `variant="destructive"` `disabled={close.isPending}` button (label "CONFIRM CLOSE ALL" → "Closing all…") wired to `useEmergency().close` (POST /api/v2/emergency/close).
- ✅ "The confirm action is hidden when there is nothing to close (both counts == 0)" — `nothingToClose = open_positions === 0 && pending_orders === 0` renders the "No open positions or pending orders." line instead of any confirm/arm button (T-11-19).
- ✅ "Resume Trading (POST /api/v2/emergency/resume) is shown only while paused" — `{paused && (<Button … onClick={() => resume.mutate()}>)}` where `paused = trading-status.data?.paused === true`.
- ✅ artifact `frontend/src/routes/KillSwitchView.tsx` (183 lines ≥ 40 min, contains "CONFIRM CLOSE ALL").
- ✅ key_links: KillSwitchView → `emergency/preview` (useQuery) and → `useEmergency` (close + resume) both present.

## Threat Mitigations (plan §threat_model)
- ✅ **T-11-17 (Tampering / accidental double-fire):** two-step armed preview→confirm (deliberate second action) + `disabled={close.isPending}` (no double-fire) + no optimistic state (server-confirmed via the hook's invalidate).
- ✅ **T-11-18 (Spoofing):** both close + resume go through `useEmergency` → `api()` → X-CSRF-Token (rejected 403 without it — Phase 8 `test_api_csrf`).
- ✅ **T-11-19 (DoS / operator-error empty close):** confirm/arm button hidden when both counts == 0.

## Verification Results
- `cd frontend && npm run build` (`tsc -b && vite build`) exits 0 — 1924 modules transformed, 0 type errors (run via a temporary shared-`node_modules` symlink; symlink + `dist/` removed before staging — neither committed).
- grep acceptance: `emergency/preview` ✓, `trading-status` ✓, `CONFIRM CLOSE ALL` ✓, `variant="destructive"` ✓, `disabled={close.isPending}` ✓, hide-when-zero (`nothingToClose`) ✓, `Resume Trading` ✓, `useEmergency` ✓.
- grep: NO code-level `setQueryData` — the only `setQueryData` occurrence is the comment documenting the "NO setQueryData" discipline (line 14); no code-level raw `fetch(` (all mutation traffic via the hook).
- `pytest tests/test_api_csrf.py` is server-side, already shipped/green (per 11-RESEARCH) — not re-run in this frontend-only worktree (needs the Python 3.12 container); assert at wave merge.
- MANUAL (VPS + MT5 demo, deferred to merge): preview render → CONFIRM CLOSE ALL (disabled while pending) → resume; confirm hidden when no positions/orders.

## Known Stubs
None — the view is fully wired to the real `/api/v2/emergency/preview`, `/api/v2/trading-status`, `/api/v2/emergency/close`, and `/api/v2/emergency/resume` endpoints (the last two via `useEmergency` → `api()`). No placeholder data, no hardcoded empties.

## Issues Encountered
- The worktree has no installed `node_modules` (deps live in the shared checkout). Resolved without a package install: type-checked + built the worktree file against the shared checkout's `node_modules` via a temporary symlink, removed before staging. `npm install` was deliberately NOT run (excluded package-install action).

## User Setup Required
None.

## Next Phase Readiness
- 11-06 (Overview / PAGE-05) can register the `/app/kill-switch` route and wire the Emergency Kill Switch entry button to navigate here; the TRADING PAUSED banner on Overview shares the `["trading-status"]` query key this page already reads, so they re-derive together.

## Self-Check: PASSED

- `frontend/src/routes/KillSwitchView.tsx` verified present on disk (183 lines).
- Task commit `bafa73a` verified in git log.
- `npm run build` green (real tsc + vite, 0 type errors).

---
*Phase: 11-live-money-pages-settings*
*Completed: 2026-06-07*
