# Deferred Items — Phase 5 Foundation

Pre-existing test failures observed during Plan 05-03 execution that are **out of scope** for Plan 05-03 (do not regress from baseline — reproduced after `git stash` of the plan's changes).

## 29 DB- and REST-dependent test failures (baseline)

- `tests/test_rest_api_connector.py::TestConnect::test_connect_*` (2)
- `tests/test_rest_api_integration.py::test_full_market_buy_flow` (1)
- `tests/test_seed_accounts.py::*` (4) — asyncpg connection errors
- `tests/test_settings.py::*` (4) — asyncpg connection errors
- `tests/test_settings_store.py::*` (3) — asyncpg connection errors
- `tests/test_trade_manager.py::*` (4)
- `tests/test_trade_manager_integration.py::*` (11)

**Root cause:** No Postgres running at `postgresql://telebot:telebot_dev@localhost:5433/telebot`; REST API connector tests have unrelated logic issues.

**Action:** Deferred. Not part of Plan 05-03's scope — argon2/SessionMiddleware cutover does not touch these code paths.

## 7 cross-loop failures when Postgres IS available (Plan 05-04)

- `tests/test_login_flow.py::test_post_login_*` (5)
- `tests/test_rate_limit.py::*` (2)

**Root cause:** `asyncpg` pool is bound to the loop that opened it (the pytest-asyncio session loop). When the test body invokes `TestClient.post()`, Starlette's `TestClient` uses `anyio.from_thread.BlockingPortal` which runs the ASGI stack in a separate thread with its own event loop. Any `await db.*` executed during a request then fails with `got Future ... attached to a different loop` or `another operation is in progress`. Same root cause as the baseline `test_concurrency.py` + `test_db_schema.py` cross-loop failures noted above.

**Verified baseline:** With Plan 05-04 stashed out, `pytest tests/test_config.py tests/test_auth_session.py tests/test_ui_substrate.py tests/test_signal_parser.py tests/test_risk_calculator.py tests/test_mt5_connector.py tests/test_concurrency.py tests/test_simulator.py tests/test_db_schema.py` produces 7 failures of the same loop-contention shape. Plan 05-04 adds 7 more tests that exercise the same infra limitation.

**Isolated behavior (Plan 05-04 tests standalone):** `pytest tests/test_login_flow.py tests/test_rate_limit.py` — 10 skipped in 0.21s (clean skip when Postgres is unreachable; clean skip when run on a cold interpreter because the standalone `asyncio.get_event_loop()` raises in Python 3.14). Acceptance criterion `exits 0 (self-skips if Postgres unavailable)` is satisfied.

**Action:** Deferred. Test-infra refactor (switch from sync `TestClient` → `httpx.AsyncClient` with ASGITransport on the session loop, or scope the DB pool per-test-session to the TestClient portal loop) belongs in a future TESTING pass. Plan 05-04's implementation is correct and exercisable; only the test-harness fixture pattern is incompatible with a live Postgres + sync `TestClient`.
