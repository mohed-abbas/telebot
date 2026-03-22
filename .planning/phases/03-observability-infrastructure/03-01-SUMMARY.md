---
phase: 03-observability-infrastructure
plan: 01
subsystem: observability
tags: [regex, logging, discord-alerts, signal-parser, documentation]

# Dependency graph
requires:
  - phase: 01-security-database
    provides: "asyncpg database with daily_stats table, notifier.notify_alert()"
provides:
  - "is_signal_like() heuristic for detecting trading signal text"
  - "_SYMBOL_PATTERN compiled regex for O(1) symbol lookup"
  - "Parse failure Discord alerts via PARSE FAILED notifications"
  - "Server message limit documentation in docs/server-messages.md"
affects: [03-observability-infrastructure, testing]

# Tech tracking
tech-stack:
  added: []
  patterns: ["compiled regex for hot-path lookups", "signal-like heuristic for alert filtering"]

key-files:
  created: ["docs/server-messages.md"]
  modified: ["signal_parser.py", "models.py", "bot.py"]

key-decisions:
  - "Signal-like heuristic requires 2+ keywords OR 1 keyword + price-like number to reduce false positives"
  - "Symbol regex sorted by key length descending so xau/usd matches before xau"

patterns-established:
  - "Compiled regex pattern: build _PATTERN from dict keys at module load, use .search() at call time"
  - "Alert filtering: use heuristic to avoid spamming Discord with every non-signal message"

requirements-completed: [OBS-01, OBS-02, OBS-04]

# Metrics
duration: 2min
completed: 2026-03-22
---

# Phase 3 Plan 1: Signal Parse Observability Summary

**Structured logging on parse failures with is_signal_like() heuristic, Discord PARSE FAILED alerts, compiled regex symbol lookup, and server message limit docs**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-22T19:07:07Z
- **Completed:** 2026-03-22T19:09:57Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Compiled _SYMBOL_PATTERN regex replaces O(n) SYMBOL_MAP iteration with O(1) regex match for symbol lookup
- is_signal_like() heuristic detects trading-like text (2+ keywords OR keyword + price) to filter meaningful parse failures
- Parse failures on signal-like text now produce both a log warning and a Discord PARSE FAILED alert
- Server message limits fully documented with tracking mechanism, configuration, and broker caveats

## Task Commits

Each task was committed atomically:

1. **Task 1: Add compiled symbol regex and signal-like heuristic** - `8c5c5cb` (feat)
2. **Task 2: Wire parse failure Discord alerts in bot.py** - `4381226` (feat)
3. **Task 3: Create server message limit documentation** - `811c379` (docs)

## Files Created/Modified
- `models.py` - Added _SYMBOL_PATTERN compiled regex built from sorted SYMBOL_MAP keys
- `signal_parser.py` - Added is_signal_like() heuristic, replaced _extract_symbol_from_text with regex lookup, added warning log at return-None path
- `bot.py` - Added elif is_signal_like(text) branch with PARSE FAILED Discord alert
- `docs/server-messages.md` - Server message limit documentation (what counts, tracking, config, broker limits)

## Decisions Made
- Signal-like heuristic requires 2+ keywords OR 1 keyword + price-like number -- balances sensitivity vs false positive rate for Discord alerts
- Symbol regex keys sorted by length descending so "xau/usd" matches before "xau" -- prevents partial match on longer variants

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Signal parse observability complete -- parse failures now visible in logs and Discord
- Dashboard N+1 fix (03-02) and analytics/infra (03-03) can proceed independently
- is_signal_like() available for any future signal processing improvements

---
*Phase: 03-observability-infrastructure*
*Completed: 2026-03-22*
