---
phase: 10-read-only-page-migration-analytics-pilot-signals-history-sta
plan: 04
subsystem: frontend-spa
tags: [react, tanstack-query, react-router, analytics, shared-primitives, pilot]
requires:
  - "10-01 analytics API widening (GET /api/v2/analytics: by_source/extremes/avg_stages/sources + _display twins)"
  - "Phase 9 SPA scaffold (api() wrapper, QueryClient defaults, App boot guard, AppShell/Sidebar, react-router basename /app)"
provides:
  - "frontend/src/components/data/DataTable.tsx — shared column-driven table (Phase 11 inherits, D-10)"
  - "frontend/src/components/state/{Loading,Empty,ErrorPanel}.tsx — shared state trio (D-10/D-11)"
  - "frontend/src/lib/useUrlFilters.ts — useSearchParams-backed URL filter helper (analytics + history, D-02/D-05)"
  - "frontend/src/routes/AnalyticsView.tsx — PAGE-01 analytics pilot at /app/analytics"
affects:
  - "frontend/src/routes/router.tsx (analytics route child)"
  - "frontend/src/components/shell/Sidebar.tsx (Analytics nav link activated)"
  - ".gitignore (negate frontend/src/components/data/ from the runtime data/ rule)"
tech-stack:
  added: []
  patterns:
    - "Column-driven hand-rolled DataTable (no @tanstack/react-table) rendering server _display strings"
    - "URL as filter source-of-truth via react-router 7 useSearchParams; queryKey derives from filters"
    - "Inline ErrorPanel (not sonner toast) for read failures; toast reserved for action feedback"
    - "Range tabs as plain styled buttons (no shadcn tabs/select dependency — D-11 lean discipline)"
key-files:
  created:
    - frontend/src/components/data/DataTable.tsx
    - frontend/src/components/state/Loading.tsx
    - frontend/src/components/state/Empty.tsx
    - frontend/src/components/state/ErrorPanel.tsx
    - frontend/src/lib/useUrlFilters.ts
    - frontend/src/routes/AnalyticsView.tsx
  modified:
    - frontend/src/routes/router.tsx
    - frontend/src/components/shell/Sidebar.tsx
    - .gitignore
decisions:
  - "Range tabs + source filter built as plain styled buttons + URL chip — no shadcn tabs/select/badge/skeleton added (threat T-10-SC source-gen avoided; D-11 keep-lean honored). The page renders full parity without them."
  - "win_rate / profit_factor / avg_stages formatted client-side via toFixed (ratios/counts, NOT money/price) per D-14; all money/price render server _display strings only (Pitfall 5)."
  - "Index route stays ProbeView (Overview is Phase 11, OQ2); analytics mounted at its own /analytics child."
metrics:
  duration: ~12min
  completed: 2026-06-06
  tasks: 3
  files: 9
---

# Phase 10 Plan 04: Analytics Pilot + Shared Primitives Summary

PAGE-01 analytics pilot (`/app/analytics`) plus the four reusable SPA primitives — `DataTable`, the Loading/Empty/ErrorPanel state trio, and the `useUrlFilters` hook — that every later read-only page (signals/history/staged here, positions/history in Phase 11) inherits.

## What Was Built

**Task 1 — Shared primitives** (`ff884db`)
- `DataTable<Row>`: column-driven table (`Column<Row>{header, cell, align?, mono?, sign?}`). Sticky header, right-align + `font-mono` for numerics, color-by-sign green/red via the optional `sign` accessor, optional `onRowClick`/`rowClassName` (active-row `bg-primary/10`). The `cell` returns whatever the caller passes — for money/price that is the server `_display` string. No client number formatting in the file (Pitfall 5).
- `Loading`: skeleton rows (plain `animate-pulse` divs with border tokens — no shadcn `skeleton` dependency, keeps the trio self-contained). `role="status"`.
- `Empty`: lucide icon + title/message panel, dashed border.
- `ErrorPanel` (D-11): inline panel (NOT a sonner toast — sonner reserved for action feedback). Message derived from `HttpError.body` (`{error:{code,message}}` envelope) with a generic fallback; `Retry` button wired to `onRetry`. Exported `errorMessage(error)` helper. Does not import `toast`.
- `useUrlFilters<T>`: copied verbatim from PATTERNS.md — react-router 7 `useSearchParams`, `replace:true` on filter edits, `{push:true}` for explicit navigation (by-source row click).

**Task 2 — AnalyticsView** (`e536cb4`)
- `useUrlFilters<{range,source}>` drives the `useQuery` key `["analytics", filters]`; empty `range` → all-time, empty `source` → no filter. Query builds `/api/v2/analytics?range=&source=` (omits empty params). NO `refetchInterval` (D-03); manual Refresh button (D-04) calls `refetch()`.
- Range tabs (7d=7 / 30d=30 / 90d=90 / All="") write `?range=` via `setFilter` (replace), styled `role="tablist"` buttons with `aria-selected`.
- Four KPI cards: Total Trades (+ W/L sub), Win Rate (green ≥50 / red), Profit Factor (green >1.0 / red), Net P&L from `total_profit_display` (green >0 / red).
- P&L panel: `gross_profit_display` / `gross_loss_display` + extremes `best_trade_display` / `worst_trade_display`.
- Avg-Stages card rendered ONLY when `data.avg_stages` is truthy (Pitfall 3) — `avg_stages` is `null` on the all-source view.
- Performance-by-Source `DataTable` in legacy column order (Source | Trades | W/L | Win Rate | PF | Net P&L | Best/Worst). Net P&L cell uses `net_pnl_display` with `sign:(r)=>r.net_pnl` color-by-sign; each row `onClick` → `setFilter({source}, {push:true})`; active row `bg-primary/10`. An active-source chip with a Clear button surfaces the filter.
- States: `isPending`→`<Loading/>`, `isError`→`<ErrorPanel onRetry={refetch}/>`, `by_source.length===0`→`<Empty/>`.

**Task 3 — Route + Sidebar wiring** (`0f758f2`)
- `router.tsx`: added `{ path: "analytics", element: <AnalyticsView/> }` under the App boot-guard children (index stays `ProbeView`; Overview is Phase 11). Path written without the `/app` prefix (basename adds it) → reachable at `/app/analytics`.
- `Sidebar.tsx`: refactored the nav into a data-driven `NAV_ENTRIES` list in legacy order; Analytics rendered as an active `<NavLink to="/analytics">` (copied from the live Overview analog incl. the `isActive` cyan-accent class). Positions / Trade History / Signal Log / Pending Stages / Settings stay disabled `<span aria-disabled>` (Plans 05/06 + Phase 11 enable them in place).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `.gitignore` `data/` rule swallowed `frontend/src/components/data/`**
- **Found during:** Task 1 commit (staging `DataTable.tsx`)
- **Issue:** The root `.gitignore` line `data/` (intended for runtime DB/data directories) matched the new source directory `frontend/src/components/data/`, so `git add` refused the plan-required file.
- **Fix:** Added a scoped negation `!frontend/src/components/data/` immediately after the `data/` rule. Verified with `git check-ignore` (now trackable).
- **Files modified:** `.gitignore`
- **Commit:** `ff884db`

**2. [Rule 3 - Blocking] `tsc not found` in worktree (no `node_modules`)**
- **Found during:** Task 1 build verification
- **Issue:** The git worktree had no `node_modules`, so `npm run build` (`tsc -b && vite build`) failed with `tsc: command not found`. This is an environment/tooling issue, not a package install — the dependencies already exist in the shared checkout.
- **Fix:** Symlinked the shared checkout's `node_modules` into the worktree's `frontend/`. The symlink is untracked (gitignored) and not committed. No new package was installed (the Rule 3 package-install exclusion does not apply — nothing was fetched).
- **Files modified:** none committed.

**3. [Rule 1 - Bug] `verbatimModuleSyntax` type-only import**
- **Found during:** Task 2 build
- **Issue:** `import { Column, DataTable }` failed TS1484 — `Column` is a type and must be imported type-only.
- **Fix:** Changed to `import { DataTable, type Column }`.
- **Files modified:** `frontend/src/routes/AnalyticsView.tsx`
- **Commit:** `e536cb4`

### Design notes (within plan latitude)
- Built range tabs / source filter as plain styled buttons + a URL chip instead of running `npx shadcn@latest add tabs select badge skeleton`. The plan permitted shadcn additions "only what AnalyticsView actually renders" and the threat model marks the CLI source-gen `accept`; the page reaches full parity without adding any component source, honoring the D-11 keep-lean discipline. No new runtime dependency, no new `src/components/ui/*` files.

## Pitfall-5 (money/price precision) compliance
- All money/price cells render server `_display` strings (`total_profit_display`, `gross_profit_display`, `gross_loss_display`, `net_pnl_display`, `best_trade_display`, `worst_trade_display`).
- The only client `toFixed` calls are on `win_rate` (ratio → `%.1f%`), `profit_factor` (ratio → `%.2f`), and `avg_stages` (a stages count) — none are money/price, allowed per D-14.
- `grep "toFixed\|Intl.NumberFormat" frontend/src/components/data` → no matches.

## Verification

| Check | Result |
|-------|--------|
| `cd frontend && npm run build` (tsc -b + vite build) | exits 0 |
| `grep toFixed\|Intl frontend/src/components/data` | no matches |
| `useSearchParams` in `useUrlFilters.ts` | present |
| `onRetry` in `ErrorPanel.tsx`, no sonner import | present / clean |
| `useUrlFilters` + `api/v2/analytics` in AnalyticsView | present |
| `avg_stages` guarded by truthy check (Pitfall 3) | yes (`data.avg_stages ?`) |
| `refetchInterval` in AnalyticsView (D-03 — must be absent) | absent |
| `path: "analytics"` + `AnalyticsView` in router | present |
| `to="/analytics"` active NavLink in Sidebar | present |
| Other future links remain disabled `aria-disabled` spans | yes |

Manual golden-number parity (SC#5 — open `/app/analytics` vs legacy `/analytics` on the same DB, compare KPIs/by-source/extremes field-by-field, verify row-click `?source=` re-query and the Avg-Stages-card-only-under-source behavior) is a human verification step deferred to the phase manual gate.

## Self-Check: PASSED

- Created files all exist on disk (DataTable, Loading, Empty, ErrorPanel, useUrlFilters, AnalyticsView).
- Modified files present (router.tsx, Sidebar.tsx, .gitignore).
- Commits exist: `ff884db`, `e536cb4`, `0f758f2`.
