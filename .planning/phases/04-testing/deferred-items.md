# Phase 04 Testing - Deferred Items

## Pre-existing: Event loop conflict between test_mt5_connector.py and test_trade_manager.py

**Discovered during:** 04-03 execution
**Scope:** Pre-existing issue from 04-01/04-02

When `test_mt5_connector.py` runs before `test_trade_manager.py` in the same pytest session, the `clean_tables` autouse fixture (which depends on `db_pool`) causes asyncpg connection state corruption. The `test_trade_manager.py::TestCloseSignal::test_close_all_positions` and `test_trade_manager.py::TestModifySL::test_move_sl_to_breakeven` fail with "RuntimeError: Task got Future attached to a different loop" or "asyncpg.exceptions._base.InterfaceError: cannot perform operation: another operation is in progress".

**Root cause:** The `clean_tables` autouse fixture acquires a DB pool connection during `test_mt5_connector.py` tests (which don't need DB), causing the pool to enter a conflicted state by the time `test_trade_manager.py` runs.

**Fix suggestion:** Make `clean_tables` skip when `db_pool` fixture didn't actually initialize (e.g., check `db._pool is not None`), or scope the `clean_tables` fixture to only apply to tests marked `@pytest.mark.integration`.

**Impact:** 2 tests fail when full suite runs; pass individually.
