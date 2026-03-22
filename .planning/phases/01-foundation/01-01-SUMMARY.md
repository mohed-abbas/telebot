---
phase: 01-foundation
plan: 01
subsystem: config
tags: [validation, security, postgres, asyncpg, env-vars]

# Dependency graph
requires: []
provides:
  - "Hardened config.py with startup validators, DATABASE_URL field, mt5_magic_number field"
  - "DASHBOARD_PASS required (no default credentials)"
  - "asyncpg in requirements.txt replacing aiosqlite"
affects: [01-02, 01-03, database, dashboard]

# Tech tracking
tech-stack:
  added: [asyncpg==0.31.0]
  patterns: [fail-fast startup validation, format validators on _req()]

key-files:
  created: []
  modified: [config.py, .env.example, requirements.txt, dashboard.py]

key-decisions:
  - "Removed dashboard.py hardcoded 'changeme' fallback (Rule 1 deviation) to fully eliminate default credentials"
  - "Skipped pip install asyncpg in parallel execution context -- requirements.txt documents the dependency"

patterns-established:
  - "Validator pattern: _req(key, validator=fn) for format checks at startup"
  - "Fail-fast: SystemExit with FATAL prefix on missing/invalid env vars"

requirements-completed: [SEC-02, SEC-03, DB-04]

# Metrics
duration: 2min
completed: 2026-03-22
---

# Phase 01 Plan 01: Config Hardening Summary

**Fail-fast startup validation with format checks, DATABASE_URL field replacing db_path, required DASHBOARD_PASS (no default), and asyncpg replacing aiosqlite**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-22T10:38:36Z
- **Completed:** 2026-03-22T10:40:30Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- DASHBOARD_PASS is now required with no default -- bot refuses to start without explicit config
- TG_API_ID validates numeric format, DATABASE_URL validates postgres:// prefix at startup
- MT5 magic number is configurable via MT5_MAGIC_NUMBER env var (default: 202603)
- db_path replaced with database_url throughout config, preparing for PostgreSQL migration
- asyncpg replaces aiosqlite in requirements.txt

## Task Commits

Each task was committed atomically:

1. **Task 1: Harden config.py with validation, DATABASE_URL, and no default credentials** - `8145cc7` (feat)
2. **Task 2: Update requirements.txt -- replace aiosqlite with asyncpg** - `1f7cf8b` (chore)

## Files Created/Modified
- `config.py` - Hardened Settings dataclass: database_url, mt5_magic_number, validators, required DASHBOARD_PASS
- `.env.example` - Updated template: DATABASE_URL, MT5_MAGIC_NUMBER, required DASHBOARD_PASS documentation
- `requirements.txt` - Replaced aiosqlite==0.20.0 with asyncpg==0.31.0
- `dashboard.py` - Removed hardcoded "changeme" fallback in _verify_auth

## Decisions Made
- Removed the `or "changeme"` fallback from dashboard.py `_verify_auth` to fully eliminate default credentials (deviation from plan scope, but directly caused by DASHBOARD_PASS becoming required)
- Skipped `pip install asyncpg` during parallel execution to avoid contention; requirements.txt is the source of truth

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed hardcoded "changeme" fallback in dashboard.py**
- **Found during:** Task 1 (config hardening)
- **Issue:** dashboard.py line 52 had `or "changeme"` fallback on expected_pass, undermining the removal of default credentials from config.py
- **Fix:** Removed the fallback so dashboard_pass is used as-is from Settings (which now requires explicit config)
- **Files modified:** dashboard.py
- **Verification:** Confirmed no "changeme" string remains in dashboard.py auth path
- **Committed in:** 8145cc7 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Essential for correctness -- without this fix, removing the default password from config.py would be undermined by dashboard.py's own fallback.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- config.py is ready for Plan 02 (database layer migration) -- database_url field is available
- bot.py currently references settings.db_path which no longer exists; Plan 02 will update this
- asyncpg is declared in requirements.txt for Plan 02 to use

## Self-Check: PASSED

All files verified present. All commit hashes found in git log.

---
*Phase: 01-foundation*
*Completed: 2026-03-22*
