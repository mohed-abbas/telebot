---
phase: 04-testing
plan: 03
subsystem: testing
tags: [pytest, asyncio, asyncpg, integration-tests, concurrency, trade-manager, executor]

# Dependency graph
requires:
  - phase: 04-testing-01
    provides: "conftest.py with db_pool, clean_tables, connector, account, global_config, make_signal fixtures"
  - phase: 01-security
    provides: "db.py with asyncpg pool, trade_manager.py with zone logic, mt5_connector.py with DryRunConnector"
  - phase: 02-reliability
    provides: "executor.py with kill switch, signal gating, heartbeat reconnect"
provides:
  - "Integration tests for trade manager full signal-to-trade pipeline with real DB"
  - "Concurrency tests for duplicate signal prevention and DB contention"
  - "Executor kill switch and signal gating tests"
  - "PricedDryRunConnector subclass for configurable price simulation"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "PricedDryRunConnector pattern for overriding get_price in integration tests"
    - "asyncio.gather for concurrent signal dispatch in tests"
    - "Session-scoped event loop sharing for DB-dependent test classes"

key-files:
  created:
    - tests/test_trade_manager_integration.py
    - tests/test_concurrency.py
  modified: []

key-decisions:
  - "PricedDryRunConnector defined locally in each test file to avoid cross-file import fragility"
  - "Tests use clean_tables autouse fixture for DB isolation between tests"
  - "Stale signal assertion checks for TP1 in reason string rather than word Stale"
  - "BUY limit tests use TPs above price to avoid stale signal false positives"

patterns-established:
  - "PricedDryRunConnector: subclass DryRunConnector with configurable prices dict for integration tests"
  - "Multi-account test pattern: create 2 AccountConfig + 2 PricedDryRunConnectors in fixture"

requirements-completed: [TEST-03, TEST-04]

# Metrics
duration: 6min
completed: 2026-03-22
---

# Phase 04 Plan 03: Integration and Concurrency Tests Summary

**20 integration tests covering trade manager signal-to-trade pipeline, concurrent signal deduplication, executor kill switch, and signal gating with real PostgreSQL**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-22T20:52:46Z
- **Completed:** 2026-03-22T20:58:50Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- 11 trade manager integration tests covering full OPEN signal flow, close/modify operations, daily limit enforcement, multi-account execution, zone logic, and stale signal rejection
- 9 concurrency and executor tests covering duplicate signal prevention, concurrent DB writes without deadlock, kill switch position closing, signal gating when paused, and signal gating when reconnecting
- PricedDryRunConnector pattern established for integration tests requiring realistic price data

## Task Commits

Each task was committed atomically:

1. **Task 1: Trade manager integration tests** - `434c676` (test)
2. **Task 2: Async concurrency and executor tests** - `4df5604` (test)

## Files Created/Modified
- `tests/test_trade_manager_integration.py` - 356 lines: PricedDryRunConnector, 6 test classes, 11 integration tests for trade manager with real DB
- `tests/test_concurrency.py` - 276 lines: concurrent signal handling, DB contention, kill switch, signal gating, 9 tests

## Decisions Made
- **PricedDryRunConnector defined locally in each test file:** Avoids fragile cross-file test imports. Each test file is self-contained.
- **BUY limit test TPs placed above price:** Original plan used TPs at/below the ask price, which triggered stale signal rejection. Adjusted TPs to be well above current price to test zone logic without stale interference.
- **Stale assertion checks for TP1 keyword:** The trade manager returns the raw stale reason from `_check_stale()` which contains "TP1" but not "Stale". Assertions adjusted to match actual behavior.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed BUY limit test TP values to avoid stale signal false rejection**
- **Found during:** Task 1 (TDD RED phase)
- **Issue:** Plan specified BUY limit test with TPs=[2150, 2155] and ask price 2151. Since current_price (2151) >= TP1 (2150), the stale check rejected the signal before zone logic could execute.
- **Fix:** Changed TPs to [2160, 2170] and target_tp to 2170 so they are above the test price.
- **Files modified:** tests/test_trade_manager_integration.py
- **Verification:** Tests pass with correct limit order at zone midpoint 2142.5

**2. [Rule 1 - Bug] Fixed stale signal assertion to match actual reason format**
- **Found during:** Task 1 (TDD RED phase)
- **Issue:** Test asserted "Stale" in reason string, but `_check_stale()` returns "Price (X) already at/below TP1 (Y)" without the word "Stale".
- **Fix:** Changed assertion to check for "TP1" in the reason string.
- **Files modified:** tests/test_trade_manager_integration.py
- **Verification:** Test correctly verifies stale signal rejection

---

**Total deviations:** 2 auto-fixed (2 bugs in test data/assertions)
**Impact on plan:** Both fixes corrected test expectations to match actual code behavior. No scope creep.

## Issues Encountered

- **Pre-existing event loop conflict:** When `test_mt5_connector.py` runs before `test_trade_manager.py` in the full suite, the session-scoped asyncpg pool gets into a corrupted state causing 2 pre-existing tests to fail. This is NOT caused by this plan's changes and was logged to `deferred-items.md`. All 20 new tests pass correctly.

## User Setup Required

None - no external service configuration required. Docker PostgreSQL must be running for integration tests.

## Next Phase Readiness
- All integration and concurrency tests complete
- Test suite provides confidence for the full signal-to-trade pipeline
- Pre-existing event loop conflict should be addressed in a future fix

---
*Phase: 04-testing*
*Completed: 2026-03-22*
