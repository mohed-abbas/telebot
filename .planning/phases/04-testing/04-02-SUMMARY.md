---
phase: 04-testing
plan: 02
subsystem: testing
tags: [pytest, mt5, dry-run, signal-parser, regression, tdd]

requires:
  - phase: 04-testing-01
    provides: "Test infrastructure (conftest.py, pytest config, dev dependencies)"
provides:
  - "38 MT5 connector unit tests covering DryRunConnector and FailingConnector"
  - "28 signal parser regression/edge-case tests with REAL_SIGNALS parametrized placeholder"
affects: [04-testing-03]

tech-stack:
  added: []
  patterns: ["FailingConnector subclass pattern for error simulation", "autouse fixture for class-level state reset"]

key-files:
  created:
    - tests/test_mt5_connector.py
    - tests/test_signal_regression.py
  modified: []

key-decisions:
  - "Reset DryRunConnector._ticket_counter in autouse fixture to prevent cross-test interference"
  - "FailingConnector uses fail_on set parameter for configurable failure simulation"
  - "REAL_SIGNALS list kept empty as placeholder -- users paste real Telegram signals during/after execution"

patterns-established:
  - "FailingConnector(DryRunConnector) with fail_on set for error path testing"
  - "Regression test file with parametrized placeholder for real-world data"

requirements-completed: [TEST-02, TEST-05]

duration: 4min
completed: 2026-03-22
---

# Phase 04 Plan 02: MT5 Connector and Signal Parser Tests Summary

**38 DryRunConnector unit tests with FailingConnector error simulation plus 28 signal parser regression/edge-case tests with parametrized real-signal placeholder**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-22T20:52:29Z
- **Completed:** 2026-03-22T20:56:31Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- 38 MT5 connector tests covering connect/disconnect/ping, get_price, open_order, modify_position, close_position (full/partial), pending orders, position filtering, factory function, and FailingConnector error scenarios
- 28 signal parser edge-case tests covering is_signal_like heuristic, symbol extraction, case insensitivity, whitespace resilience, unicode dashes, TP open trailing, emoji resilience, close variants, and SL breakeven variants
- Parametrized REAL_SIGNALS placeholder ready for real Telegram signal regression data
- FailingConnector pattern established for simulating ping/get_price/open_order failures

## Task Commits

Each task was committed atomically:

1. **Task 1: MT5 connector tests** - `a00ae2b` (test) - 38 tests via TDD
2. **Task 2: Signal parser regression tests** - `bb79157` (test) - 28 edge-case tests + placeholder

## Files Created/Modified
- `tests/test_mt5_connector.py` - 38 tests for DryRunConnector state management, FailingConnector error simulation, and create_connector factory
- `tests/test_signal_regression.py` - 28 edge-case tests plus parametrized REAL_SIGNALS regression placeholder

## Decisions Made
- Reset `DryRunConnector._ticket_counter = 100000` via autouse fixture to prevent cross-test state leakage from the class-level shared counter
- FailingConnector takes `fail_on: set[str]` to selectively fail configured operations while letting others pass through to parent
- REAL_SIGNALS list intentionally empty -- users add real Telegram signals for regression testing over time

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- MT5 connector and signal parser test coverage complete
- 122 total unit tests pass across all test files (0 failures, 1 skip for empty parametrize)
- Ready for 04-03 (trade manager integration tests / async concurrency tests)

## Self-Check: PASSED

- FOUND: tests/test_mt5_connector.py
- FOUND: tests/test_signal_regression.py
- FOUND: .planning/phases/04-testing/04-02-SUMMARY.md
- FOUND: commit a00ae2b (Task 1)
- FOUND: commit bb79157 (Task 2)

---
*Phase: 04-testing*
*Completed: 2026-03-22*
