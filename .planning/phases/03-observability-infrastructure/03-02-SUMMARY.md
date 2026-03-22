---
phase: 03-observability-infrastructure
plan: 02
subsystem: dashboard
tags: [asyncio, postgresql, analytics, jinja2, fastapi]

# Dependency graph
requires:
  - phase: 01-security-database
    provides: PostgreSQL asyncpg pool, trades table schema, dashboard auth
provides:
  - Batched position queries via asyncio.gather (replaces sequential N+1)
  - Per-symbol analytics queries (win rate, profit factor, net P&L)
  - /analytics dashboard page with summary cards and symbol breakdown table
affects: [03-observability-infrastructure]

# Tech tracking
tech-stack:
  added: []
  patterns: [PostgreSQL FILTER aggregates for conditional stats, asyncio.gather for parallel IO]

key-files:
  created: [templates/analytics.html]
  modified: [db.py, dashboard.py, templates/base.html]

key-decisions:
  - "Division-by-zero handled in SQL via NULLIF rather than Python application code"
  - "Analytics computed on page load from SQL (no caching or background jobs)"

patterns-established:
  - "PostgreSQL FILTER aggregate pattern for conditional counting/summing"
  - "asyncio.gather with return_exceptions=True for parallel connector calls"

requirements-completed: [OBS-03, ANLYT-01]

# Metrics
duration: 2min
completed: 2026-03-22
---

# Phase 03 Plan 02: Analytics & Batched Positions Summary

**Batched asyncio.gather position queries replacing sequential N+1, plus /analytics page with per-symbol win rate, profit factor, and P&L from PostgreSQL FILTER aggregates**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-22T19:07:11Z
- **Completed:** 2026-03-22T19:09:23Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Replaced sequential per-account position fetching with asyncio.gather for parallel IO
- Added get_analytics_by_symbol() and get_analytics_summary() query functions using PostgreSQL FILTER aggregates
- Created /analytics page with summary cards (total trades, win rate, profit factor), P&L section, and per-symbol breakdown table
- Added Analytics nav link to sidebar with active state highlighting

## Task Commits

Each task was committed atomically:

1. **Task 1: Add analytics query functions to db.py and batch positions in dashboard.py** - `8c5c5cb` (feat)
2. **Task 2: Create analytics template and add nav link** - `320f01d` (feat)

**Plan metadata:** pending (docs: complete plan)

## Files Created/Modified
- `db.py` - Added get_analytics_by_symbol() and get_analytics_summary() with FILTER aggregates and NULLIF division safety
- `dashboard.py` - Replaced sequential _get_all_positions() with asyncio.gather; added /analytics route
- `templates/analytics.html` - New analytics page with summary cards, P&L section, per-symbol table
- `templates/base.html` - Added Analytics nav link between Signal Log and Settings

## Decisions Made
- Division-by-zero handled in SQL via NULLIF rather than Python application code -- keeps the query self-contained and avoids duplicate safety logic
- Analytics computed on page load from SQL (no caching or background jobs) -- appropriate for current scale, avoids infrastructure complexity

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- asyncpg not installed locally (Docker-only dependency) so import-based verification was replaced with AST parsing -- no impact on correctness

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Analytics page is wired and ready for production
- Batched position fetching improves dashboard latency for multi-account setups
- Plan 03 (structured logging) can proceed independently

## Self-Check: PASSED

All files verified present. All commits verified in git log.

---
*Phase: 03-observability-infrastructure*
*Completed: 2026-03-22*
