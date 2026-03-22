---
phase: 04-testing
plan: 01
subsystem: testing
tags: [pytest, pytest-asyncio, asyncpg, test-infrastructure]

# Dependency graph
requires:
  - phase: 01-security
    provides: asyncpg database layer and models used by test fixtures
provides:
  - pytest test runner with asyncio auto mode
  - shared conftest.py with DB pool, connector, and signal factory fixtures
  - migrated test suite (69 tests) in tests/ directory
affects: [04-02, 04-03]

# Tech tracking
tech-stack:
  added: [pytest 8.3.5, pytest-asyncio 0.25.3, pytest-mock 3.15.1, pytest-cov 6.1.1]
  patterns: [session-scoped asyncpg pool for integration tests, autouse table truncation, DryRunConnector fixture]

key-files:
  created: [requirements-dev.txt, pyproject.toml, tests/conftest.py, tests/test_signal_parser.py, tests/test_risk_calculator.py, tests/test_trade_manager.py]
  modified: []

key-decisions:
  - "Session-scoped event loop for DB-dependent tests to share asyncpg pool across test functions"
  - "pytest.skip() in db_pool fixture when PostgreSQL unreachable -- allows unit tests to run without Docker"

patterns-established:
  - "DB fixtures: session-scoped pool with autouse truncation between tests for isolation"
  - "Async test classes with DB access use @pytest.mark.asyncio(loop_scope='session')"
  - "DryRunConnector for all trade execution tests -- no MT5 dependency"

requirements-completed: [TEST-01]

# Metrics
duration: 4min
completed: 2026-03-22
---

# Phase 4 Plan 1: Test Infrastructure Summary

**Pytest test runner with asyncio auto mode, shared asyncpg/DryRunConnector fixtures, and 69 migrated tests in tests/ directory**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-22T20:45:56Z
- **Completed:** 2026-03-22T20:50:31Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Created requirements-dev.txt with pinned test dependencies (pytest, pytest-asyncio, pytest-mock, pytest-cov)
- Created pyproject.toml with pytest asyncio auto mode, session fixture loop scope, and test markers
- Created tests/conftest.py with session-scoped DB pool, autouse table truncation, DryRunConnector, and signal factory fixtures
- Migrated all 3 test files from project root to tests/ with updated fixtures (removed SQLite, async connector, clean imports)
- All 69 tests pass (56 unit + 13 trade manager)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create requirements-dev.txt and pyproject.toml** - `535d7b7` (feat)
2. **Task 2: Create tests/conftest.py and move existing test files** - `6f72565` (feat)

## Files Created/Modified
- `requirements-dev.txt` - Pinned test dependency versions
- `pyproject.toml` - pytest configuration with asyncio auto mode and session loop scope
- `tests/conftest.py` - Shared fixtures: db_pool, clean_tables, global_config, account, connector, make_signal
- `tests/test_signal_parser.py` - 42 signal parser tests (moved from root, unchanged)
- `tests/test_risk_calculator.py` - 14 risk calculator tests (moved from root, unchanged)
- `tests/test_trade_manager.py` - 13 trade manager tests (migrated: removed SQLite, async fixtures, clean imports)

## Decisions Made
- Session-scoped event loop for DB-dependent tests: asyncpg pool is bound to the loop where it was created, so tests using handle_signal() (which calls db.log_signal()) must share that loop. Used @pytest.mark.asyncio(loop_scope="session") on TestCloseSignal and TestModifySL classes.
- pytest.skip() in db_pool fixture when PostgreSQL is unreachable: allows signal parser and risk calculator unit tests to run even without Docker Compose up.
- Created .venv virtual environment (already in .gitignore) for isolated dependency installation on PEP 668 systems.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed asyncpg event loop mismatch for DB-dependent tests**
- **Found during:** Task 2 (test migration)
- **Issue:** TestCloseSignal and TestModifySL async tests failed with "Future attached to a different loop" because asyncpg pool was created on session loop but tests ran on function-scoped loops
- **Fix:** Added session-scoped event_loop fixture in conftest.py and @pytest.mark.asyncio(loop_scope="session") on DB-dependent test classes
- **Files modified:** tests/conftest.py, tests/test_trade_manager.py
- **Verification:** All 69 tests pass including the 2 previously failing async tests
- **Committed in:** 6f72565 (Task 2 commit)

**2. [Rule 3 - Blocking] Created .venv for PEP 668 compatibility**
- **Found during:** Task 1 (pip install)
- **Issue:** System Python on macOS refused pip install due to PEP 668 externally-managed environment
- **Fix:** Created .venv virtual environment, installed all dependencies there
- **Files modified:** None committed (.venv is gitignored)
- **Verification:** pip install succeeds, all imports work
- **Committed in:** N/A (runtime environment only)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both fixes necessary for correct test execution. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviations above.

## User Setup Required
None - no external service configuration required. Tests use the existing docker-compose.dev.yml PostgreSQL instance.

## Next Phase Readiness
- Test infrastructure complete: pytest runner, fixtures, and directory structure ready
- Plans 04-02 (MT5 connector tests) and 04-03 (concurrency tests) can build on these fixtures
- conftest.py provides all shared fixtures needed by subsequent test plans

## Self-Check: PASSED

- All 6 created files exist
- Both task commits (535d7b7, 6f72565) found in git log
- No test_*.py files remain in project root

---
*Phase: 04-testing*
*Completed: 2026-03-22*
