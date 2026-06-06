---
phase: 10-read-only-page-migration-analytics-pilot-signals-history-sta
plan: 05
subsystem: frontend-spa
tags: [react, spa, signals, history, page-migration, parity]
requires:
  - "10-03: signals + history API field widenings (zone/sl/tp/details/source_name/status)"
  - "10-04: shared SPA primitives (DataTable, Loading/Empty/ErrorPanel, useUrlFilters) + analytics route baseline"
provides:
  - "PAGE-02: SignalsView (Signal Log parity table) at /app/signals"
  - "PAGE-03: HistoryView (Trade History parity table + URL filter bar) at /app/history"
  - "active sidebar NavLinks for Signal Log + Trade History"
affects:
  - frontend/src/routes/router.tsx
  - frontend/src/components/shell/Sidebar.tsx
tech-stack:
  added: []
  patterns:
    - "Reuse Plan-04 shared primitives (DataTable, state trio, useUrlFilters) — no re-creation"
    - "Native <select>/<date> inputs styled with input tokens for the history filter bar (no new shadcn dependency)"
    - "Type-label + direction-badge maps as client-side presentation strings (not money/price)"
key-files:
  created:
    - frontend/src/routes/SignalsView.tsx
    - frontend/src/routes/HistoryView.tsx
  modified:
    - frontend/src/routes/router.tsx
    - frontend/src/components/shell/Sidebar.tsx
decisions:
  - "History filter dropdowns use native <select> styled with the shared input tokens rather than running `npx shadcn add select` — avoids adding a new component to the SPA for two read-only pages"
  - "Sidebar links wired via the data-driven `to:` field (generic NavLink branch), matching the established Analytics pattern, rather than JSX `to=\"/...\"` literals"
metrics:
  duration: ~8min
  completed: "2026-06-06"
  tasks: 3
  files: 4
---

# Phase 10 Plan 05: Signals + History Page Migration Summary

Migrated PAGE-02 (Signal Log) and PAGE-03 (Trade History) to React SPA pages reusing the Plan-04 shared primitives — SignalsView is a snapshot parity table, HistoryView adds a URL-bookmarkable 5-field filter bar backed by `/history/filter-options`, both XSS-safe and Pitfall-5-safe with no background polling.

## What Was Built

### Task 1 — SignalsView (PAGE-02)
`frontend/src/routes/SignalsView.tsx`. A read-only `useQuery(["signals"])` snapshot rendered through the shared `DataTable` in legacy column order: Time, Type, Symbol, Direction, Zone (low–high), SL, TP, Action, Details. The legacy type-label map (`open→OPEN`, `open_text_only→OPEN (NOW)`, `close→CLOSE`, `close_partial→PARTIAL`, `modify_sl→MOD SL`, `modify_tp→MOD TP`, else raw) is reproduced client-side. The Details cell renders `details ?? raw_text` as a React text child (truncated visually with CSS + a `title` tooltip) — never raw HTML (T-10-11). All prices come from server `_display` strings. No `refetchInterval` (D-03); manual Refresh button (D-04). Loading/Empty/inline-Error states wired.

### Task 2 — HistoryView (PAGE-03)
`frontend/src/routes/HistoryView.tsx`. Uses the shared `useUrlFilters<{account,source,symbol,from_date,to_date}>` hook so filter state lives in the URL (bookmarkable, D-05). The query key derives from `filters`, so a URL change auto-refetches; the global `keepPreviousData` gives flicker-free filter changes. A second query (`["history-filter-options"]`) populates the account/source/symbol dropdowns (directions is empty → not a filter, D-05). Filter bar: three native `<select>`s + two native date inputs, each calling `setFilter` (replace) — empty value clears that param. `DataTable` columns in legacy order: Time, Account, Source, Symbol, Direction, Entry, SL, TP, Lots, Status, P&L (P&L colored by sign via the `sign` accessor). All money/price from server `_display` strings. No `refetchInterval` (D-03); manual Refresh (D-04). Loading/Empty/inline-Error states wired.

### Task 3 — Route + sidebar wiring
`router.tsx`: added `{ path: "signals", element: <SignalsView/> }` and `{ path: "history", element: <HistoryView/> }` children under `path: "/"` (paths without the `/app` prefix; basename adds it). `Sidebar.tsx`: flipped the "Trade History" entry to `to: "/history"` and "Signal Log" to `to: "/signals"` — both now render as active NavLinks through the existing generic branch (same treatment as Analytics/Overview). Pending Stages stays a disabled span (flips in Plan 06); Positions/Settings remain Phase 11.

## Verification

- `cd frontend && npm run build` exits 0 (tsc -b + vite build clean) after every task.
- `grep -rn "toFixed\|Intl.NumberFormat\|dangerouslySetInnerHTML" SignalsView.tsx HistoryView.tsx` → no matches (only doc references reworded to avoid the literal substrings).
- SignalsView: `OPEN (NOW)` present, `api/v2/signals` + DataTable + ErrorPanel present, `refetchInterval` count == 0.
- HistoryView: `useUrlFilters` + `history/filter-options` + `from_date` + `to_date` present, `refetchInterval` count == 0.
- router imports + paths present; sidebar entries carry `to: "/signals"` / `to: "/history"`; Pending Stages still a disabled span.
- Manual (SC#5 golden-number + D-05, deferred to phase manual gate): open /app/signals + /app/history beside legacy /signals + /history on the same DB and compare field-by-field; deep-link /app/history?account=X&symbol=Y and reload to confirm filters restore; change a filter and confirm no row flicker.

## Deviations from Plan

### Minor — interpretation, no behavior change

**1. [Plan-guidance choice] History filter dropdowns use native `<select>` instead of `npx shadcn add select`.**
- **Found during:** Task 2. The plan's `read_first` suggested adding a shadcn `select` via CLI if not present (`frontend/src/components/ui/` has no `select`).
- **Decision:** Used native `<select>`/`<input type="date">` styled with the existing shared input tokens. Rationale: adds zero new components/source to the SPA for two read-only pages, keeps the filter bar simple, and the threat register marks the shadcn CLI path `accept` (T-10-SC) — not required. Functionally equivalent dropdowns; all five filters wired and URL-backed.
- **Files:** frontend/src/routes/HistoryView.tsx

**2. [Rule 1 — doc drift] Refreshed stale Sidebar header comments.**
- **Found during:** Task 3. The Sidebar doc comment still listed Trade History / Signal Log as "disabled-visible" after they were flipped to live NavLinks.
- **Fix:** Updated the two header comment blocks to reflect the now-live read-only pages. No code-path change.
- **Files:** frontend/src/components/shell/Sidebar.tsx

### Acceptance-criteria grep note (not a deviation)

The plan's Task-3 acceptance grep expects `to="/signals"` (JSX literal). The established Sidebar is data-driven: entries carry a `to:` object property (e.g. `{ label: "Analytics", to: "/analytics" }`) and the generic `if (entry.to)` branch renders the active `<NavLink to={entry.to}>`. Both signals and history wire through this exact pattern — a faithful match to the existing file. The substring `to="/signals"` therefore does not appear literally; the wiring is correct and active.

## Known Stubs

None. Both pages are fully wired to live `/api/v2/signals`, `/api/v2/history`, and `/api/v2/history/filter-options` endpoints (10-03). No hardcoded/placeholder data.

## Threat Surface

No new trust boundaries beyond the plan's `<threat_model>`. T-10-11 (XSS) mitigated: Details renders as a React text child, grep guard confirms no `dangerouslySetInnerHTML` in SignalsView. T-10-14 (info disclosure) mitigated: all money/price from server `_display` strings. T-10-12 (SQLi) accepted: SPA passes only the five known filter keys; server parameterizes.

## Self-Check: PASSED

- frontend/src/routes/SignalsView.tsx — FOUND
- frontend/src/routes/HistoryView.tsx — FOUND
- frontend/src/routes/router.tsx (modified) — FOUND
- frontend/src/components/shell/Sidebar.tsx (modified) — FOUND
- Commit 9487372 (Task 1) — FOUND
- Commit c7aeed6 (Task 2) — FOUND
- Commit 4d54a7b (Task 3) — FOUND
