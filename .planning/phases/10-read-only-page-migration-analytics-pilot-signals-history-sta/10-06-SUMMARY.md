---
phase: 10-read-only-page-migration-analytics-pilot-signals-history-sta
plan: 06
subsystem: frontend-spa
tags: [react, vite, staged-entries, polling, page-migration, PAGE-04]
requires: ["10-02", "10-04", "10-05"]
provides:
  - "PAGE-04 staged-entries page at /app/stages (active cards + resolved table, 3s poll)"
  - "useElapsed per-second ticking timer hook off a server ISO epoch"
  - "/app/ index redirect to the analytics pilot; ProbeView removed"
affects:
  - frontend/src/routes/router.tsx
  - frontend/src/components/shell/Sidebar.tsx
  - frontend/src/components/shell/AppShell.tsx
tech-stack:
  added: []
  patterns:
    - "Single background-polling page via useQuery refetchInterval:3000 (D-07)"
    - "Client-side relative-duration timer off a server epoch (Pitfall-5-exempt, D-06)"
    - "Card-per-account active rendering + shared DataTable for resolved rows (D-08)"
key-files:
  created:
    - frontend/src/lib/useElapsed.ts
    - frontend/src/routes/StagedView.tsx
  modified:
    - frontend/src/routes/router.tsx
    - frontend/src/components/shell/Sidebar.tsx
    - frontend/src/components/shell/AppShell.tsx
  deleted:
    - frontend/src/routes/ProbeView.tsx
decisions:
  - "D-13 parity exception: SPA shows CORRECT filled/total/distance from the enriched dict's real keys; legacy template renders them BLANK (field-name bug) — documented, not replicated"
  - "OQ2: /app/ index redirects to /analytics (the shipped pilot) since Overview is Phase 11; ProbeView (the prior index landing) removed"
  - "Resolved-stages rows expose account_name (not account) — used the real DB key from get_recently_resolved_stages"
metrics:
  duration: 9min
  completed: 2026-06-06
---

# Phase 10 Plan 06: Staged-Entries Page Migration (PAGE-04) Summary

Migrated the STAGED-ENTRIES page (PAGE-04) — the only page that background-polls (~3s, D-07) — as a card-per-account active view with a smooth client-side ticking elapsed timer off the server `started_at` epoch, plus a shared-DataTable resolved view; this is the last read-only page, and the run also removed the throwaway ProbeView and redirected `/app/` to the analytics pilot.

## What Was Built

**Task 1 — `useElapsed` hook (`frontend/src/lib/useElapsed.ts`, commit 93f9434):**
A `useElapsed(startedAtIso): string` hook copied verbatim from PATTERNS.md — a 1s `setInterval` re-renders a `now` state and returns an `MM:SS` / `H:MM:SS` duration computed as `Date.parse(startedAtIso)` subtracted from `now`, clamped at 0, cleaning the interval up on unmount. This is the ONE client-side number computation the phase allows: a relative wall-clock duration off a server epoch is neither money nor price, so it is Pitfall-5-exempt (D-06). The epoch is the server machine `started_at` from the 10-02 widening — the timer ticks smoothly per-second between the 3s polls rather than jumping in poll-cadence steps.

**Task 2 — `StagedView` (`frontend/src/routes/StagedView.tsx`, commit 1c2ee49):**
A `useQuery({ queryKey: ["stages"], queryFn: api("/api/v2/stages"), refetchInterval: 3000 })` page — the ONLY polling page (D-07); background pause on a hidden tab is free via the inherited `refetchIntervalInBackground:false`. Active stages render as a `StageCard` per account (D-08): symbol + BUY/SELL badge + `account_name`, then Stages (`s.filled`/`s.total` — the CORRECT enriched keys, D-13), Target Band (`band_low_display – band_high_display`, mono), Current Price (`current_price_display ?? "—"`, mono), and Elapsed (`useElapsed(s.started_at)`, mono). Resolved stages render in the shared `DataTable` with legacy columns (Account, Symbol, Direction, Stage, Status, Reason, Time); the `_RESOLVED_STATUS_LABELS` map is applied CLIENT-SIDE (pure presentation strings, including `cancelled_by_kill_switch → "Kill-switch drain"`). Loading / Empty / inline ErrorPanel states are wired; every money/price cell renders the server `_display` string only (Pitfall 5).

**Task 3 — Route wiring + cleanup (`router.tsx` + `Sidebar.tsx` + `AppShell.tsx`, commit 141ec06):**
Mounted `{ path: "stages", element: <StagedView/> }` under `/`; the index child now `<Navigate to="/analytics" replace/>` (OQ2 — Overview is Phase 11). Flipped the sidebar "Pending Stages" entry to a live `NavLink to="/stages"` via the data-driven generic branch; Positions and Settings remain disabled-visible spans (Phase 11). Deleted the throwaway `ProbeView.tsx` diagnostic and refreshed the one stale comment in `AppShell.tsx` that referenced it. No live import/usage of ProbeView remains.

## Verification

- `cd frontend && npm run build` exits 0 after each task (tsc -b type-check + vite build; 1925 modules).
- StagedView contains no `toFixed` / `Intl.NumberFormat` / `filled_count` / `total_stages` (Pitfall 5 + D-13); contains `refetchInterval`, `useElapsed`, `started_at`, and `"Kill-switch drain"`.
- `frontend/src/routes/ProbeView.tsx` is removed; no live references remain.
- `path: "stages"` mounted in router.tsx; Pending Stages renders a live NavLink to `/stages`.
- Manual parity (SC#4/SC#5 — deferred to human gate): open `/app/stages` beside legacy `/staged` on the same DB; the legacy blank-cell Stages/Distance bug is an accepted parity exception (SPA correct, legacy buggy); a card watched ≥10s should tick elapsed smoothly per-second; `/app/` should redirect to `/app/analytics`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Restored lockfile-pinned frontend dependencies + rolldown native binding**
- **Found during:** Task 1 (first `npm run build` — `tsc: command not found`, then `Cannot find native binding @rolldown/binding-darwin-arm64`).
- **Issue:** The fresh worktree had no `frontend/node_modules`. `npm ci` restored the lockfile-pinned deps but, due to the known npm optional-dependencies bug (npm/cli#4828), did not fetch the transitive `@rolldown/binding-darwin-arm64` native binding (this is the documented STATE note: "rolldown binding kept out of package.json (transitive)").
- **Fix:** Ran `npm ci` (restores existing lockfile-pinned deps — NOT a new package install), then copied the already-present `@rolldown/binding-darwin-arm64` directory from the main repo's `node_modules` into the worktree's `node_modules`. No new dependency was added; `package.json` / `package-lock.json` are unchanged. This is environment restoration, not a package-manager install of a new/unknown package, so the slopsquat checkpoint does not apply.
- **Files modified:** none tracked (node_modules is gitignored).
- **Commit:** n/a (no source change).

**2. [Comment-only adjustment] Reworded StagedView comments to avoid literal banned tokens**
- **Found during:** Task 2 verification.
- **Issue:** Explanatory comments documenting the legacy bug literally contained `filled_count`/`total_stages`/`toFixed`/`Intl.NumberFormat`, tripping the acceptance grep as false positives (they were never code).
- **Fix:** Reworded the comments to describe the banned patterns without spelling the literal tokens, so the grep cleanly reports no matches and stays a reliable guard.
- **Files modified:** frontend/src/routes/StagedView.tsx.
- **Commit:** 1c2ee49 (folded into the Task 2 commit before it landed).

### Notes on the Plan Interface

- The plan's `<interfaces>` described resolved rows as carrying `account`; the actual `db.get_recently_resolved_stages` query returns `account_name`. Used the real key. No code impact (verified against db.py:1144).

## Known Stubs

None. The page is fully data-wired to `/api/v2/stages`; the only client-computed value is the elapsed duration (intentional, D-06).

## Self-Check: PASSED

- FOUND: frontend/src/lib/useElapsed.ts
- FOUND: frontend/src/routes/StagedView.tsx
- FOUND (removed as intended): frontend/src/routes/ProbeView.tsx absent
- FOUND: commit 93f9434 (useElapsed)
- FOUND: commit 1c2ee49 (StagedView)
- FOUND: commit 141ec06 (route wiring + ProbeView removal)
- Build: `npm run build` exits 0.
