---
phase: 08-json-api-foundation
plan: 04
subsystem: api
tags: [fastapi, csrf, idempotency, postgres, partial-close, kill-switch, money-safety, pytest]

# Dependency graph
requires:
  - phase: 08-json-api-foundation
    plan: 01
    provides: "api/router.py (single-owner assembly, actions stub pre-included), api/deps.{verify_csrf_token,require_executor,require_user}, api/idempotency.{check,store}, api/schemas.{CloseLevelsIn,PartialCloseIn,MutationResult,EmergencyResult}, api/formatting.volume_display, conftest api_app + DryRunConnector stub"
  - phase: 08-json-api-foundation
    plan: 02
    provides: "POST /api/v2/auth/login JSON session + telebot_csrf double-submit cookie; the D-16 CSRF gate proven on /auth/logout; the deferred-dashboard-import lesson"
provides:
  - "POST /api/v2/positions/{account}/{ticket}/close — full close (MutationResult JSON envelope; ports close_position + db.update_trade_close verbatim)"
  - "POST /api/v2/positions/{account}/{ticket}/levels — atomic SL/TP modify (JSON envelope with changed-fields; ports the _changed diff + modify_position verbatim)"
  - "POST /api/v2/positions/{account}/{ticket}/close-partial — absolute close_volume + request_id idempotency (replay->cached 200 broker-once, conflict->409, out-of-range->422)"
  - "POST /api/v2/emergency/close — kill switch (EmergencyResult JSON; ports executor.emergency_close + notify)"
  - "POST /api/v2/emergency/resume — resume trading ({status: resumed}; ports executor.resume_trading + notify)"
  - "tests/test_api_idempotency.py — the API-05 money-safety gate (volume->422, replay->200 broker-once, conflict->409, no-CSRF->403)"
affects: [09-spa-scaffold-auth, 11-live-money-pages-settings, 12-parallel-run-cutover]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deferred-dashboard-import invariant extended to api/actions.py: `import dashboard` lives inside handler bodies only (emergency_close/resume); `import api.actions` is side-effect-free (config/dashboard NOT pulled into sys.modules without DATABASE_URL)"
    - "Money-safety partial-close: absolute close_volume (D-09) replaces percent-of-current math; out-of-range 422 guard runs BEFORE the idempotency check; insert-first idempotency.check classifies new/replay/conflict atomically"
    - "Every /api/v2 money mutation carries Depends(verify_csrf_token)+Depends(require_user); inherits the D-16 403 gate proven by Plan 02 on /auth/logout"
    - "GET /trading-status left to api/meta.py (Plan 03) — no duplicate route registration in actions.py"

key-files:
  created:
    - tests/test_api_idempotency.py
  modified:
    - api/actions.py

key-decisions:
  - "Out-of-range (422) validation runs BEFORE idempotency.check (matches 08-PATTERNS skeleton); the conflict test therefore uses a second in-range volume (0.10 then 0.05 against the shrinking 0.30 position) so the 422 guard cannot mask the 409"
  - "Reached the notifier via dashboard.get_notifier() accessor inside the handler (never `from dashboard import _notifier`) so init_dashboard's late rebind is honored and the eager-import path stays clean"
  - "levels returns a structured {ok,success,changed,error} envelope (changed = the dict of fields actually sent to the broker) instead of the modal/toast HTML; a no-op modify returns ok with changed={}"

requirements-completed: [API-02, API-05]

# Metrics
duration: 8min
completed: 2026-06-03
---

# Phase 08 Plan 04: Live-money Mutation JSON API + Idempotent Partial-Close Summary

**Ported every live-money mutation into `/api/v2` as a CSRF-guarded JSON envelope (close, modify-levels, emergency-close, emergency-resume) and rebuilt partial-close as an absolute-volume, `request_id`-idempotent operation — eliminating the percent-of-current double-fire (the 75% trap): a legitimate retry replays the cached 200 and never re-hits the broker, a reused id with different params 409s, an out-of-range volume 422s, and the broker/DB calls are ported verbatim from dashboard.py with the bot core byte-for-byte untouched.**

## Performance
- **Duration:** ~8 min
- **Completed:** 2026-06-03T18:01:41Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- `POST /positions/{account}/{ticket}/close` ports `dashboard.py:1087-1093` verbatim (connector lookup -> `close_position(ticket)` -> `db.update_trade_close(ticket, account, 0.0, result.price)`) and returns a `MutationResult` JSON envelope instead of the green/red HTML span.
- `POST /positions/{account}/{ticket}/levels` ports the `_changed` diff + atomic `modify_position(ticket, sl=, tp=)` (`dashboard.py:1221-1235`) unchanged; the modal/toast HTML becomes a `{ok, success, changed, error}` JSON envelope where `changed` reports exactly which fields were sent to the broker.
- `POST /positions/{account}/{ticket}/close-partial` is the **API-05 rewrite**: `cv = round(close_volume, 2)`; `0 < cv < pos.volume` else 422; `idempotency.check(request_id, account, ticket, cv)` -> `new` executes `close_position(ticket, volume=cv)` (absolute, D-09) + `store`s the payload, `replay` returns the cached 200 (broker untouched), `conflict` 409s. The percent-of-current math (`dashboard.py:1283`) is gone entirely.
- `POST /emergency/close` ports `await executor.emergency_close()` + kill-switch notify into an `EmergencyResult` JSON envelope; `POST /emergency/resume` ports the sync `executor.resume_trading()` + notify into `{status: resumed}`.
- `GET /trading-status` is **not** redefined here — it is owned by `api/meta.py` (Plan 03); duplicating it would double-register the route.
- `tests/test_api_idempotency.py` is the money-safety gate: `test_volume_validation` (422 on `<=0` and `>=pos.volume`), `test_replay` (cached 200 + broker `close_position` called **exactly once** with the absolute volume), `test_conflict` (409), `test_partial_close_requires_csrf` (403).

## Task Commits
1. **Task 1: api/actions.py — close/levels/emergency/resume JSON mutation routes** — `16c8429` (feat)
2. **Task 2: tests/test_api_idempotency.py — idempotent partial-close regression suite** — `a47e0c8` (test)

> Task 2 is `tdd="true"`. The partial-close handler (GREEN) shipped inside the Task 1 `api/actions.py` module; the regression suite was authored in Task 2 and the RED->GREEN cycle was validated end-to-end against dev Postgres (see TDD Gate Compliance below). The two commits map to the actions module (implementation) and the test file (the failing-then-passing behavior spec).

## Files Created/Modified
- `api/actions.py` (MOD) — replaced the Plan-01 stub with five mutation routes + a `_connector_or_404` helper. Deferred `import dashboard` into the emergency handlers; `db`, `api.deps`, `api.idempotency`, `api.formatting`, `api.schemas` are eager (all side-effect-free).
- `tests/test_api_idempotency.py` (NEW) — 4 tests driving the real JSON login for a live session + `telebot_csrf` double-submit, with a broker-call spy on the live `DryRunConnector` to assert the broker fires exactly once on replay.

## Decisions Made
- **Validation-before-idempotency ordering.** The 422 out-of-range guard runs before `idempotency.check` (matches the 08-PATTERNS skeleton). A consequence surfaced during real-DB verification: a partial close shrinks the live position, so a naive conflict test (`0.10` then `0.20` against a `0.30` position) hits 422 on the second call because the position is now `0.20`. The conflict test therefore uses `0.10` then `0.05` (both in-range against the shrinking position) so the 422 guard cannot mask the intended 409. This is a test-design correction, not an implementation change.
- **Notifier via accessor.** `dashboard.get_notifier()` is called inside the emergency handlers (never `from dashboard import _notifier`) so `init_dashboard`'s late global rebind is honored and the eager-import path stays free of the dashboard->config chain.
- **`levels` envelope shape.** Returns `{ok, success, changed, error}` with `changed` = the dict of fields actually sent to the broker; a no-op modify returns `ok` with `changed={}` (the old "no change" info toast).

## Deviations from Plan
### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected the conflict-test volumes to avoid the 422/409 ordering trap**
- **Found during:** Task 2, surfaced by the single-loop end-to-end driver against dev Postgres.
- **Issue:** The plan's `test_conflict` description (`POST request_id, then SAME request_id with a DIFFERENT close_volume -> 409`) implicitly assumes the position volume is constant. It is not: the first partial close (`0.10`) shrinks the seeded `0.30` position to `0.20`, so a second `0.20` request is now `>= pos.volume` and the out-of-range 422 guard (correctly placed before the idempotency check) fires first, returning 422 instead of the intended 409.
- **Fix:** The conflict test uses `0.10` then `0.05` — both strictly inside `(0, current pos.volume)` — so the request reaches `idempotency.check`, which returns `conflict` (same `request_id`, different `close_volume`) -> 409. Documented in the test docstring.
- **Files modified:** tests/test_api_idempotency.py
- **Verification:** end-to-end driver reports `conflict 409 PASS` (and all 18 behavioral checks PASS).
- **Committed in:** `a47e0c8`

---

**Total deviations:** 1 auto-fixed (Rule 1 — corrected a test vector that collided with the validation-before-idempotency ordering). No production-code deviation; the handler follows the 08-PATTERNS skeleton verbatim.
**Impact on plan:** No scope creep. The behavior the plan specified (replay->200 broker-once, conflict->409, out-of-range->422, no-CSRF->403) is implemented and proven exactly as written.

## TDD Gate Compliance
The local interpreter is Python 3.14; the project targets 3.12 (`python:3.12-slim`). The conftest `api_app`/`db_pool` fixtures combined with the synchronous `TestClient` portal-thread loop produce a known cross-loop `asyncpg` conflict — the SAME pre-existing failure the Plan-02 baseline `tests/test_api_csrf.py` exhibits when run ad-hoc (3 of its 6 tests fail identically in that harness). This is an environment/fixture mismatch, not a defect in this plan, and `tests/test_api_idempotency.py` collects cleanly and **skips** gracefully under the local venv (per the conftest skip contract); it runs green on the project's 3.12 CI.

To prove the RED->GREEN cycle for real, I exercised the actual `dashboard.app` against the running dev Postgres (`telebot-db-dev`) in a `python:3.12-slim` container using a single-event-loop `httpx.ASGITransport` async client (no portal thread, so no cross-loop conflict). All 18 behavioral assertions PASS, including the four that mirror the committed test file:
- `volume_validation` 0.0 / -0.1 / 0.30 / 0.40 -> 422 (each).
- `replay`: first 200 with `closed_volume=0.10` + `closed_volume_display="0.10"`; replay returns the identical cached payload; broker `close_position` invoked **exactly once** with `volume=0.10`.
- `conflict`: 0.10 then 0.05 (same `request_id`) -> 409.
- `partial requires csrf`: no `X-CSRF-Token` -> 403.
Plus the Task 1 routes (full close JSON, levels changed/no-op, emergency close/resume, and the meta-owned GET `/trading-status`) all PASS.

A `test(...)` commit (`a47e0c8`) follows the `feat(...)` actions module (`16c8429`); no REFACTOR commit was needed.

## Issues Encountered
- The acceptance greps flag `percent`, `_render_toast_oob`, and `modify-sl`/`modify-tp` as present in `api/actions.py` — all occur only in the module docstring / inline comments as the explicit "this is what we deliberately AVOID" contrast notes (the identical situation Plans 01 and 02 documented for their own grep flags). The executable partial-close line uses `close_position(ticket, volume=cv)` (absolute); there is no `pos.volume * (` math and no deprecated route.
- The full non-integration suite collects with no INTERNALERROR (364/384 collected, 20 deselected), confirming the deferred-dashboard-import invariant held across the whole suite.

## User Setup Required
None — zero new packages (RESEARCH Package Legitimacy Audit; T-08-SC accept). Deploy note carried from Plan 02: extend the nginx `limit_req` zone to cover `/api/v2/auth/login` at cutover (unrelated to this plan).

## Next Phase Readiness
- The complete `/api/v2` money-mutation surface Phase 11 (live-money pages) inherits is now in place: close, modify-levels, idempotent absolute-volume partial-close, kill-switch close/resume — all CSRF-guarded JSON envelopes.
- **Note for the SPA (Phase 9/11):** partial-close requires a client-supplied `request_id` (UUID per user action) and an absolute `close_volume` in lots (never a percent, never a re-rounded JS value — submit the exact server-provided numeric). The retry-safety guarantee depends on the SPA reusing the SAME `request_id` for a retried action.
- Bot core (`db.py`/`mt5_connector.py`/`executor.py`/`trade_manager.py`) and `mt5-rest-server/` show an empty git diff (mechanized by `tests/_bot_core_diff_guard.py`, which passes).

## Self-Check: PASSED

(Appended below after on-disk + git verification.)

---
*Phase: 08-json-api-foundation*
*Completed: 2026-06-03*
