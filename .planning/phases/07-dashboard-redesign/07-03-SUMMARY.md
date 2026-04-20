---
phase: 07-dashboard-redesign
plan: 03
subsystem: ui
tags: [htmx, accordion, details-element, drilldown, positions, fill-history, signal-attribution]

# Dependency graph
requires:
  - phase: 07-02
    provides: Positions table with responsive table-to-card layout
  - phase: 06-01
    provides: staged_entries table with fill history data
provides:
  - Position drilldown accordion with inline expand/collapse
  - Fill history table showing stage, time, lots, band, SL at fill
  - Signal attribution display with source, timestamp, raw text
  - db.get_position_drilldown() query joining trades, staged_entries, signals
affects: [07-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "HTML <details> element with hx-trigger='toggle once' for lazy-load accordion"
    - "onclick toggle with stopPropagation for action buttons"
    - "drilldown-row class for accordion content container"

key-files:
  created:
    - templates/partials/position_drilldown.html
  modified:
    - db.py
    - dashboard.py
    - templates/partials/positions_table.html

key-decisions:
  - "Use native <details> element (not JS state) for accordion - multiple can be open simultaneously per D-06"
  - "Lazy-load drilldown content via HTMX toggle once trigger - no refetch on close/reopen"
  - "Single-stage trades show trade itself as stage 1 in fill history for consistency"

patterns-established:
  - "Inline accordion pattern: <details> with hidden <summary>, hx-trigger='toggle once'"
  - "Position drilldown data flow: db.get_position_drilldown() -> /partials/position_drilldown/{account}/{ticket}"

requirements-completed: [DASH-03]

# Metrics
duration: 2min
completed: 2026-04-20
---

# Phase 07-03: Positions Drilldown Accordion

**Expandable position rows showing fill history, per-stage SL/TP, current P/L, and signal attribution via inline accordion pattern**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-20T19:46:28Z
- **Completed:** 2026-04-20T19:48:30Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Implemented get_position_drilldown() query returning position, fill history, and signal data
- Created drilldown partial template with fill history table, P/L display, and signal attribution
- Added accordion rows to positions table using native <details> element with HTMX lazy loading
- Both desktop table and mobile cards support expandable drilldown panels

## Task Commits

Each task was committed atomically:

1. **Task 1: Add get_position_drilldown() query to db.py** - `daf1af6` (feat)
2. **Task 2: Add drilldown partial route and template** - `6ba71a3` (feat)
3. **Task 3: Add accordion rows to positions table** - `9ce1888` (feat)

## Files Created/Modified
- `db.py` - Added get_position_drilldown() function querying trades, staged_entries, signals
- `dashboard.py` - Added /partials/position_drilldown/{account}/{ticket} route
- `templates/partials/position_drilldown.html` - Drilldown panel with fill history, P/L, signal attribution
- `templates/partials/positions_table.html` - Accordion rows for desktop table and mobile cards

## Decisions Made
- Native <details> element chosen over JS-controlled accordion to support D-06 (multiple rows expanded simultaneously) without state tracking
- Lazy-load via hx-trigger="toggle once" prevents unnecessary refetches when toggling same row
- Single-stage trades (no staged_entries) show the trade itself as stage 1 for UI consistency

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Position drilldown accordion fully functional
- Fill history displays staged entries or single-stage fallback
- Signal attribution shows source_name (added in 07-01) when available
- Ready for 07-04 (analytics), 07-05 (history filters), or 07-08 (staged page restyle)

## Self-Check: PASSED

All files exist and all commits verified.

---
*Phase: 07-dashboard-redesign*
*Completed: 2026-04-20*
