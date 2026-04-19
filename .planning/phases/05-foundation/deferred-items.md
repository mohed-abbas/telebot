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
