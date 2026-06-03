---
phase: 08-json-api-foundation
plan: 02
subsystem: api
tags: [fastapi, csrf, double-submit, argon2, rate-limit, auth, pytest]

# Dependency graph
requires:
  - phase: 08-json-api-foundation
    plan: 01
    provides: "api/router.py (single-owner assembly, auth stub pre-included), api/deps.verify_csrf_token, api/schemas.LoginIn, conftest api_app fixture"
  - phase: 05-foundation
    provides: "telebot_session SessionMiddleware, argon2 + db failed_login rate-limit, legacy /login HTMX flow + telebot_login_csrf"
provides:
  - "POST /api/v2/auth/login — double-submit CSRF -> per-IP rate-limit -> argon2 verify -> session; sets readable telebot_csrf cookie + returns {user}"
  - "POST /api/v2/auth/logout — clears session, guarded by verify_csrf_token (the representative D-16 mutation)"
  - "GET /api/v2/auth/me — {user} or 401"
  - "GET /api/v2/auth/csrf — issues/refreshes telebot_csrf, returns the token in the body (no session required)"
  - "tests/test_api_csrf.py — the D-16 CSRF go-live gate (missing-token->403, valid->pass, cookie-name non-collision)"
affects: [09-spa-scaffold-auth, 10-read-only-page-migration, 11-live-money-pages-settings, 12-parallel-run-cutover]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Side-effect-free resource module: api/auth.py lazy-imports dashboard/api.deps inside handlers so `import api.auth` (via router.py at collection) never triggers config._load_settings() -> SystemExit"
    - "Double-submit CSRF on /api/v2: telebot_csrf cookie (httponly=False, path=/) vs X-CSRF-Token header, secrets.compare_digest"
    - "Four-step login pipeline ported verbatim from dashboard.py (CSRF -> rate-limit BEFORE argon2 CPU -> verify -> session), JSON response shape only"

key-files:
  created:
    - tests/test_api_csrf.py
  modified:
    - api/auth.py

key-decisions:
  - "Lazy-imported dashboard/api.deps inside auth handlers (Rule 3): a top-level `from dashboard import ...` crashed pytest collection for the whole suite via the config SystemExit path"
  - "logout chosen as the representative verify_csrf_token-guarded mutation so the D-16 gate is exercisable now, before the money-mutation routes land (Plan 04)"
  - "auth.py imports nothing from dashboard at module top level — only db + LoginIn — keeping the eager-import path clean"

requirements-completed: [API-02, API-03]

# Metrics
duration: 8min
completed: 2026-06-03
---

# Phase 08 Plan 02: Auth + CSRF JSON Contract Summary

**Shipped the complete `/api/v2/auth/{login,logout,me,csrf}` JSON contract — a verbatim port of the legacy four-step login pipeline (CSRF -> per-IP rate-limit -> argon2 verify -> session) with a SPA-readable `telebot_csrf` double-submit cookie — plus the D-16 CSRF regression gate proving any `/api/v2` mutation rejects a request with no valid `X-CSRF-Token` (403).**

## Performance
- **Duration:** ~8 min
- **Completed:** 2026-06-03T17:15:52Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- `POST /api/v2/auth/login` ports `dashboard.py:269-316` verbatim, changing only the response shape to JSON: double-submit CSRF (`secrets.compare_digest`) -> per-IP `db.get_failed_login_count >= 5` -> 429 (D-14, before the argon2 CPU) -> `_password_hasher.verify` (401 generic on failure, T-08-08) -> session + `db.clear_failed_logins`. On success it sets `telebot_csrf` (`httponly=False`, `path="/"`) and returns `{"user":"admin"}`.
- `POST /auth/logout` clears the session and is guarded by `verify_csrf_token` — the representative `/api/v2` mutation the D-16 gate fires against. `GET /auth/me` gates on session (401/`{user}`). `GET /auth/csrf` issues/refreshes the cookie and returns the token in the body so the SPA can read it on first load (no session required).
- The reused machinery (`_password_hasher`, `app_settings`, `_client_ip`) is imported from dashboard, never re-instantiated; `db.py` rate-limit helpers are accessor-only — bot core, `mt5-rest-server/`, and `api/router.py` show an empty git diff.
- `tests/test_api_csrf.py` is the documented D-16 hard gate: missing-token -> 403 (no HTML/traceback), valid-token -> 200, and `telebot_csrf` vs `telebot_login_csrf` non-collision with the legacy `/login` flow proven untouched (D-13).

## Task Commits
1. **Task 1: api/auth.py — login/logout/me/csrf JSON contract** — `9cb9d48` (feat)
2. **Task 2: tests/test_api_csrf.py — the D-16 regression gate** — `8335bf9` (test)

## Files Created/Modified
- `api/auth.py` (MOD) — replaced the Plan-01 stub with the four auth handlers, `_issue_csrf` helper (parameterised `secure`), and a lazy `_verify_csrf` proxy dependency.
- `tests/test_api_csrf.py` (NEW) — 6 tests: `/auth/me` 401, `/auth/csrf` readable token, login->me round-trip, **missing-token->403**, **valid-token->pass**, **cookie-name non-collision**. Module docstring marks it the D-16 go-live gate.

## Decisions Made
- **Lazy dashboard/deps imports (the one substantive deviation, below).** Login/csrf handlers `from dashboard import ...` at call time, and the logout dependency is a thin `_verify_csrf` proxy that imports `api.deps.verify_csrf_token` lazily. This keeps `import api.auth` (which `api/router.py` performs eagerly at collection) free of the `dashboard -> config._load_settings()` chain.
- **logout as the D-16 representative mutation.** No money-mutation route is mergeable in this wave (Plan 04 lands the actions routes), so the gate fires against `POST /auth/logout`, which carries the identical `verify_csrf_token` guard. When the actions routes land they inherit the same guard, so the gate generalises.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Lazy-imported dashboard / api.deps inside the auth handlers**
- **Found during:** Task 1, surfaced by the full non-integration suite (`pytest -m "not integration"`).
- **Issue:** The plan's interface note imports `_password_hasher/app_settings/_client_ip` from dashboard and `verify_csrf_token` from api.deps. Done at module top level, these run at `api/router.py` collection time (which eagerly `from api import (auth, ...)`). When an earlier test fixture has popped `config` from `sys.modules` without the env set, the transitive `from config import settings` calls `config._load_settings()` -> `raise SystemExit("Missing required env var: DATABASE_URL")`, which pytest surfaces as an INTERNALERROR that **halts collection for the entire suite** (not just the auth tests).
- **Fix:** Deferred every dashboard/deps import into the handler bodies (login, csrf) and wrapped the logout dependency in a lazy `_verify_csrf` proxy. `import api.auth` now imports only `db` + `LoginIn` and has zero `dashboard`/`config` side-effect (verified: `'config' not in sys.modules` after `import api.auth`). The runtime behaviour is unchanged — these objects are stable module-level singletons in dashboard.py, so resolving them at request time is equivalent.
- **Files modified:** api/auth.py
- **Verification:** `import api.auth` leaves `config`/`dashboard` out of `sys.modules`; the full `pytest -m "not integration"` run no longer INTERNALERRORs (matches the Plan-01 baseline of 55 failed / 251 passed / 19 errors, +6 clean skips from this plan's new file).
- **Committed in:** `9cb9d48`

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking collection crash).
**Impact on plan:** No scope creep, no behaviour change. The wiring shape the plan specified is preserved; only the import *timing* moved from module-load to request-time to keep the eager-import path side-effect-free.

## Issues Encountered
- **Local interpreter is Python 3.14; the project targets 3.12 (Dockerfile `python:3.12-slim`).** The conftest `api_app` fixture (and `test_login_flow.py`) use the `asyncio.get_event_loop().run_until_complete(...)` pattern, which raises "There is no current event loop" on 3.14, so every DB-backed test (Plan 01's and this plan's) **skips** rather than runs under the local `.venv`. This is a pre-existing environment mismatch, not a code defect, and equally affects Plan 01. To prove the auth + CSRF logic actually works I stood up the dev Postgres (`docker-compose.dev.yml`, port 5433) and exercised all four routes end-to-end through a `TestClient` on a single event loop: **9/9 behavioural checks passed** — csrf-token-readable, me-401/-admin, login-401/-200+session, logout-403-without-token / -200-with-token, legacy-`/login`-still-sets-`telebot_login_csrf`, and rate-limit-429-after-5-failures. The committed `tests/test_api_csrf.py` collects cleanly and skips gracefully when Postgres is absent (per the conftest skip contract); it will run green on the project's 3.12 CI.
- The acceptance grep for "no `httponly=True` / no `telebot_login_csrf` / no `PasswordHasher()`" flags matches in `api/auth.py` — all are in docstrings/comments as the explicit "contrast to AVOID" warnings (lines 15, 18-20, 49, 57, 59). The two executable `set_cookie` calls use `httponly=False`; `_password_hasher` is imported, never instantiated. This is the identical situation Plan 01's SUMMARY documented for `api/deps.py`.

## User Setup Required
None — zero new packages. Deploy note carried from the threat model (T-08-06): extend the nginx `limit_req zone=telebot_login` to also cover `/api/v2/auth/login` (D-14) at cutover.

## Next Phase Readiness
- The cross-phase auth + CSRF contract Phases 9-12 inherit is now exact: the `telebot_csrf` cookie name, the 401/429 JSON shapes, and the 403-without-token guarantee all originate and are gated here.
- **Note for Plan 04:** every money-mutation route must carry the `verify_csrf_token` (or the `_verify_csrf` proxy) dependency so it inherits the D-16 gate; the gate test already proves the mechanism on `/auth/logout`.
- **Note for conftest (cross-cutting, not this plan):** the `authed_client` fixture can now finalise a real session by POSTing `/api/v2/auth/login` instead of seeding the cookie directly; and the `asyncio.get_event_loop()` pattern in `api_app` / `test_login_flow.py` should be modernised (`asyncio.new_event_loop()`) if/when CI moves to Python 3.13+.

## Self-Check: PASSED
- `api/auth.py` and `tests/test_api_csrf.py` verified on disk.
- Task commits `9cb9d48` (feat) and `8335bf9` (test) verified in git history.
- Bot core (`db.py`/`mt5_connector.py`/`executor.py`/`trade_manager.py`), `mt5-rest-server/`, and `api/router.py` confirmed byte-for-byte unchanged (`git diff --exit-code` exit 0).

---
*Phase: 08-json-api-foundation*
*Completed: 2026-06-03*
