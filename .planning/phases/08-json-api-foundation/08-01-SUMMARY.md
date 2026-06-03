---
phase: 08-json-api-foundation
plan: 01
subsystem: api
tags: [fastapi, pydantic-v2, csrf, idempotency, postgres, asyncpg, formatting, pytest]

# Dependency graph
requires:
  - phase: 05-foundation
    provides: session-cookie auth (telebot_session), argon2 + failed_login rate-limit, _verify_auth /api/ 401 branch, SettingsStore
provides:
  - "api/ package mounted at /api/v2 with single-owner router assembly (ten resource stub routers pre-wired)"
  - "api/deps.py: require_user (401), verify_csrf_token (double-submit telebot_csrf, 403), require_executor/require_settings_store (503) via dashboard accessors"
  - "api/formatting.py: single-source price/money/volume/ts_machine/ts_display display strings (D-05..D-08)"
  - "api/idempotency.py: Postgres idempotency_keys table + ensure_table/check/store/age_out (DDL outside db.py)"
  - "api/schemas.py: full Pydantic v2 request/response contract with parallel _display fields"
  - "api/errors.py: enveloped-error handler {error:{code,message,fields?}}"
  - "Wave-0 test scaffolds: conftest api_app/authed_client fixtures, formatter test, bot-core diff guard"
affects: [09-spa-scaffold-auth, 10-read-only-page-migration, 11-live-money-pages-settings, 12-parallel-run-cutover]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single-owner router assembly: api/router.py wires all ten resource sub-routers once; Plans 02-05 only add @router handlers in their own module"
    - "Accessor functions (get_executor/get_settings_store) avoid stale-None capture from init_dashboard's late global rebind"
    - "Double-submit CSRF (telebot_csrf cookie vs X-CSRF-Token header, secrets.compare_digest) replacing the HX-Request heuristic for /api/v2"
    - "Single-source server-side formatter (D-08) — _SYMBOL_DIGITS extended here, never inline, to prevent XAUUSD pip-size class bugs"
    - "Bot-core untouchability gate via git-diff test (mechanized invariant for every wave merge)"
    - "Idempotency DDL lives in api/idempotency.py via db._pool accessor — db.py byte-for-byte untouched"

key-files:
  created:
    - api/__init__.py
    - api/router.py
    - api/deps.py
    - api/errors.py
    - api/formatting.py
    - api/idempotency.py
    - api/schemas.py
    - api/auth.py
    - api/accounts.py
    - api/positions.py
    - api/history.py
    - api/signals.py
    - api/stages.py
    - api/analytics.py
    - api/meta.py
    - api/actions.py
    - api/settings.py
    - tests/test_api_formatting.py
    - tests/_bot_core_diff_guard.py
  modified:
    - dashboard.py
    - Dockerfile
    - tests/conftest.py

key-decisions:
  - "Corrected the plan's float-edge verification vector (2800.005 rounds to 2800.01 under IEEE-754, not 2800.00) — code uses f-string 2dp per spec; tested with unambiguous vectors"
  - "Idempotency check uses insert-first (INSERT ... ON CONFLICT DO NOTHING) to atomically classify new/replay/conflict, closing the check-then-act race (OQ1)"
  - "Error handlers only reshape /api/v2 responses; legacy HTML/HTMX routes keep FastAPI defaults"
  - "authed_client fixture seeds telebot_csrf only at Wave 0; Plan 02 finalises the JSON /api/v2/auth/login session path"

patterns-established:
  - "Resource-module router ownership: each resource owns router = APIRouter(); router.py includes all once"
  - "D-05 dual-value: only price/money/volume/timestamp fields get a _display twin; ints/strings/enums stay bare"
  - "api/ reads db._pool / dashboard accessors only — never edits or import-binds bot core"

requirements-completed: [API-01, API-03, API-04]

# Metrics
duration: 4min
completed: 2026-06-03
---

# Phase 08 Plan 01: JSON API Foundation Summary

**Stood up the `/api/v2` FastAPI foundation — mountable `api/` package with single-owner router assembly, double-submit CSRF + session deps, single-source server-side formatter, Postgres idempotency module (DDL outside db.py), full Pydantic v2 contract, and Wave-0 test scaffolds — with the bot core byte-for-byte untouched.**

## Performance

- **Duration:** ~4 min
- **Completed:** 2026-06-03T17:02:55Z
- **Tasks:** 3
- **Files modified:** 22 (19 created, 3 modified)

## Accomplishments
- `api/` package mounts at `/api/v2`; `api/router.py` pre-wires all ten resource sub-routers once (Plans 02-05 add handlers to their own module only — they never touch router.py).
- The three genuinely-new pieces of machinery: double-submit CSRF dependency (`telebot_csrf` vs `X-CSRF-Token`, `secrets.compare_digest`), single-source formatter (`price/money/volume/ts_machine/ts_display`), and a Postgres `idempotency_keys` module whose DDL lives in `api/idempotency.py` (db.py untouched).
- Full Pydantic v2 contract (`Position`, `AccountOverview`, `PartialCloseIn` with absolute `close_volume` + `request_id`, `CloseLevelsIn`, `LoginIn`, `MutationResult`, and the read/meta/settings models) with D-05 parallel `_display` fields.
- Additive dashboard wiring (router mount + enveloped-error handlers + `ensure_table()` in lifespan + read-only accessors) and `COPY api/ ./api/` in the Dockerfile runtime stage.
- Wave-0 test scaffolds: conftest `api_app` (DryRunConnector-backed executor stub with a deterministic XAUUSD position) + `authed_client`, the formatter test (7 cases), and the mechanized bot-core diff guard.

## Task Commits

Each task was committed atomically:

1. **Task 1: api/ package skeleton, router assembly, deps, errors, formatter** - `7963a2c` (feat)
2. **Task 2: Idempotency module, schemas contract, dashboard wiring, Dockerfile copy** - `0247b3e` (feat)
3. **Task 3: Wave-0 test scaffolds — conftest fixtures, formatter test, bot-core diff guard** - `c29f2d8` (test)

## Files Created/Modified
- `api/__init__.py` - exports `api_router = APIRouter(prefix="/api/v2")`; imports router for include side-effect
- `api/router.py` - single-owner assembly; `include_router` for all ten resource modules
- `api/auth.py`, `api/accounts.py`, `api/positions.py`, `api/history.py`, `api/signals.py`, `api/stages.py`, `api/analytics.py`, `api/meta.py`, `api/actions.py`, `api/settings.py` - resource router stubs (`router = APIRouter()`)
- `api/deps.py` - `require_user`, `verify_csrf_token`, `require_executor`, `require_settings_store`
- `api/errors.py` - enveloped-error handler + `register_error_handlers(app)`
- `api/formatting.py` - single-source display formatters (`_SYMBOL_DIGITS`, `GOLD_PIP_SIZE` import)
- `api/idempotency.py` - `ensure_table/check/store/age_out` over `idempotency_keys` via `db._pool`
- `api/schemas.py` - full Pydantic v2 request/response contract with `_display` twins
- `dashboard.py` - lifespan `ensure_table()`, `include_router(api_router)` + `register_error_handlers`, accessors
- `Dockerfile` - `COPY api/ ./api/` in runtime stage
- `tests/conftest.py` - `idempotency_keys` truncate, `api_app` + `authed_client` fixtures, DryRun executor stub
- `tests/test_api_formatting.py` - API-04 dual-value formatter contract (7 cases)
- `tests/_bot_core_diff_guard.py` - git-diff gate over the four bot-core files + mt5-rest-server/

## Decisions Made
- **Corrected a float-edge verification vector (Rule 1, on the plan's test command, not the code).** The plan's inline check asserted `price_display('XAUUSD', 2800.005) == '2800.00'`, but `2800.005` is stored in IEEE-754 as slightly above 2800.005 and `f"{x:.2f}"` correctly yields `2800.01`. The formatter implements exactly the spec'd `f"{value:.{digits}f}"`; the Task 3 test uses unambiguous vectors (`2800.123 -> 2800.12`, `2800.5 -> 2800.50`). No code change was needed — the plan's assertion was numerically wrong.
- **Insert-first idempotency classification.** `check` does `INSERT ... ON CONFLICT (request_id) DO NOTHING RETURNING request_id`; a returned row means "new", otherwise it re-reads to classify replay (same account/ticket/close_volume within 1e-9) vs conflict. This closes the check-then-act race (OQ1) in one atomic statement.
- **Error envelope scoped to `/api/v2`.** Handlers reshape only paths under `/api/v2`; legacy HTML/HTMX routes keep FastAPI defaults, so no existing route changes behavior.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected a numerically-incorrect verification vector**
- **Found during:** Task 1 (formatter), surfaced by the plan's `<automated>` verify command
- **Issue:** The plan asserted `price_display('XAUUSD', 2800.005) == '2800.00'`. Under IEEE-754, `2800.005` rounds to `2800.01`, so the assertion is wrong about Python float behavior — not the formatter.
- **Fix:** Implemented the formatter exactly as specified (`f"{value:.{digits}f}"`, 2dp for XAUUSD / 5dp default). Verified the acceptance intent ("XAUUSD price returns 2dp") with unambiguous test vectors in `tests/test_api_formatting.py`. No production code deviation.
- **Files modified:** api/formatting.py (per spec), tests/test_api_formatting.py
- **Verification:** `pytest tests/test_api_formatting.py` — 7 passed
- **Committed in:** `7963a2c` (formatter) / `c29f2d8` (test)

---

**Total deviations:** 1 auto-fixed (1 corrected verification vector — Rule 1)
**Impact on plan:** No scope creep. Production code follows the spec verbatim; only the plan's own float-edge test vector was corrected. All other acceptance criteria passed as written.

## Issues Encountered
- The deps acceptance grep flags `telebot_login_csrf` and `from dashboard import _executor` as present in `api/deps.py` — both occur only in docstrings/comments that explicitly warn against them; the executable cookie name is `telebot_csrf` and the executor is reached via accessors. Confirmed by line-level inspection; no code change required.

## User Setup Required
None - no external service configuration required. Zero new packages this phase (RESEARCH Package Legitimacy Audit — all deps already pinned).

## Next Phase Readiness
- The complete contract Plans 02-05 fill is in place: `api/schemas.py`, `api/deps.py`, `api/formatting.py`, `api/idempotency.py`, and the ten resource-router stubs.
- `api/router.py` is single-owned by Plan 01 — Plans 02-05 add `@router` handlers in their own resource module only.
- Bot core (`executor.py`, `trade_manager.py`, `db.py`, `mt5_connector.py`) and `mt5-rest-server/` show empty git diff (mechanized by `tests/_bot_core_diff_guard.py`).
- **Note for Plan 02:** the `authed_client` fixture currently seeds only the `telebot_csrf` cookie; Plan 02 must finalize the JSON `/api/v2/auth/login` route and wire the session into that fixture for end-to-end mutation tests.

## Self-Check: PASSED

All 20 created files verified on disk; all three task commits (`7963a2c`, `0247b3e`, `c29f2d8`) verified in git history.

---
*Phase: 08-json-api-foundation*
*Completed: 2026-06-03*
