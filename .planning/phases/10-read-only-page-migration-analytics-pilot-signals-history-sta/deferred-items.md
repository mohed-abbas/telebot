# Phase 10 — Deferred Items (out-of-scope discoveries)

> **RESOLUTION UPDATE (post-Wave-2, orchestrator):** Plan 10-03's two contract tests
> (`test_signals_contract.py`, `test_history_contract.py`) were **re-authored** onto the
> proven single-loop `httpx.ASGITransport` + `loop_scope="session"` harness (mirrors
> `test_analytics_contract.py`), so they now execute green — `6 passed, 7 skipped, 0 errors`
> across the full Phase-10 contract suite (Python 3.12 + dev PG). Porting also surfaced a
> latent `/api/v2/history` date-filter binding bug (fixed in `api/history.py`; commit
> `a9c9ade`). **The item below is therefore narrowed:** only the *pre-existing*
> `tests/test_api_contract.py` (Phase-8) `TestClient`/`session_client` suite remains blocked
> by the conftest loop bug (`10 passed, 14 errors`). Phase 10's own contract tests no longer
> depend on a conftest fix — the recommended path is to migrate `test_api_contract.py` to the
> same ASGITransport pattern.

## [10-03] Pre-existing test-harness event-loop incompatibility (DB-touching contract tests)

**Discovered during:** Plan 10-03 Task 2/3 verification.

**Symptom:** Any `/api/v2` contract test that drives `TestClient` against a route
touching the asyncpg pool errors with:

```
asyncpg.exceptions._base.InterfaceError: cannot perform operation: another operation is in progress
# (and) RuntimeError: Task <...> got Future <...> attached to a different loop
```

**Proven pre-existing:** Running the untouched `tests/test_api_contract.py` on the
clean base commit `9bd2e77` (NO plan 10-03 changes) reproduces it exactly:
`10 passed, 14 errors` — the 14 errors are precisely the `session_client`/DB-touching
tests; the 10 passes are the no-DB 401 auth-gate tests.

**Root cause (analysis):** `tests/conftest.py::api_app` (module-scoped) initialises the
asyncpg pool via `asyncio.get_event_loop().run_until_complete(...)`, binding pool
connections to the fixture loop. Starlette's synchronous `TestClient` runs each request
on its own anyio portal loop, so the in-request `db.*` pool acquire/release happens on a
different loop than the one the pool was created on. The deprecated session-scoped
`event_loop` fixture (deprecated in pytest-asyncio ≥0.25, which the image installs) no
longer governs the sync TestClient path, so the two loops diverge.

**Why deferred (not auto-fixed):** The fix belongs in `tests/conftest.py` (init the pool
inside an ASGI lifespan / on the TestClient portal loop, or drive the app via
`httpx.ASGITransport` within the pytest-asyncio session loop). `conftest.py` and
`test_api_contract.py` are OUTSIDE plan 10-03's `files_modified` scope, and the defect
predates this plan. Per the executor SCOPE BOUNDARY rule, harness changes are not made here.

**Plan 10-03 deliverables verified by other means:**
- `python -c "ast.parse(...)"` clean on schemas.py / signals.py / history.py.
- All Task-1 acceptance greps pass (widened fields + price `_display` twins declared,
  zero string `_display` twins, `price_display` usage count ≥3 in signals).
- Both new contract test files `--collect-only` clean (5 tests collected, valid imports).
- Tests follow the exact mandated `api_app`/`session_client`/`_login` pattern from
  `tests/test_api_contract.py` (which passes in CI).

**Recommended owner:** A harness-focused plan (or quick task) that fixes the
`api_app` pool/loop binding once, unblocking the entire `/api/v2` DB-touching contract
test class (Phase 8 `test_api_contract.py` + Phase 10 signals/history/analytics/stages
contract tests).
