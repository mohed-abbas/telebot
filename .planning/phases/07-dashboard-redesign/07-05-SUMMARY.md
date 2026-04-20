---
phase: 07-dashboard-redesign
plan: 05
subsystem: ui
tags: [htmx, analytics, pill-tabs, time-filter, source-filter, postgresql]

# Dependency graph
requires:
  - phase: 07-01
    provides: source_name column on signals table for per-source analytics
provides:
  - Time-range filter (7d/30d/90d/All) for analytics via pill tabs
  - Per-source analytics drill-down with clickable table rows
  - get_analytics_with_filters() supporting time and source parameters
  - get_analytics_sources() for source dropdown population
  - Analytics partial template for HTMX swaps
affects: [07-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pill tabs for time range filtering via HTMX hx-get with URL push"
    - "Clickable table rows for drill-down filtering"
    - "Parameterized SQL with allowlist for time range (injection mitigation)"

key-files:
  created:
    - templates/partials/analytics_table.html
  modified:
    - db.py
    - dashboard.py
    - templates/analytics.html

key-decisions:
  - "Time range parsed from allowlist (7d/30d/90d/all -> days) for T-07-09 injection mitigation"
  - "avg_stages only computed when source is filtered (expensive query)"

patterns-established:
  - "HTMX partial swap for filter changes with URL push (hx-push-url=true)"
  - "Per-source breakdown table with clickable rows for drill-down"

requirements-completed: [DASH-04]

# Metrics
duration: 2min
completed: 2026-04-20
---

# Phase 07-05: Analytics Time Filter and Source Drill-down Summary

**Pill tabs for 7d/30d/90d/All time range with per-source clickable table rows for analytics deep-dive (DASH-04)**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-20T19:56:43Z
- **Completed:** 2026-04-20T19:59:16Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Analytics page now has horizontal pill tabs for time range selection (D-07)
- Per-source breakdown table with clickable rows for source-filtered metrics (D-08)
- Full D-09 metrics: win rate, profit factor, avg stages, total trades, net P/L, best/worst trade
- HTMX partial swap with URL push for shareable filter state

## Task Commits

Each task was committed atomically:

1. **Task 1: Add get_analytics_with_filters() to db.py** - `04f6802` (feat)
2. **Task 2: Update analytics route with time and source filters** - `cc9b256` (feat)
3. **Task 3: Restyle analytics.html with pill tabs and source drill-down** - `cceec72` (feat)

## Files Created/Modified
- `db.py` - Added get_analytics_with_filters() and get_analytics_sources() query functions
- `dashboard.py` - Updated /analytics route with range and source query params
- `templates/analytics.html` - Restyled with pill tabs and source filter badge
- `templates/partials/analytics_table.html` - New partial for HTMX swap (summary cards + by-source table)

## Decisions Made
- Time range parsed from allowlist (T-07-09: injection mitigation) - only 7d/30d/90d/all accepted
- avg_stages query only runs when source is filtered (expensive COUNT per signal_id)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Analytics page ready with time range and source filters
- Wave 3 continues with 07-06 (settings toasts) and 07-07 (settings help text)

## Self-Check: PASSED

All files exist and all commits verified:
- templates/partials/analytics_table.html: FOUND
- templates/analytics.html: FOUND
- db.py: FOUND
- dashboard.py: FOUND
- Commit 04f6802: FOUND
- Commit cc9b256: FOUND
- Commit cceec72: FOUND

---
*Phase: 07-dashboard-redesign*
*Completed: 2026-04-20*
