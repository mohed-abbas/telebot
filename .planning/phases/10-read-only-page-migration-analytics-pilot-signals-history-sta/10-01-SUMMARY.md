---
phase: 10-read-only-page-migration-analytics-pilot-signals-history-sta
plan: 01
subsystem: api
tags: [analytics, pydantic, fastapi, contract-test, dual-value, httpx]

# Dependency graph
requires:
  - phase: 08-json-api-foundation
    provides: "versioned /api/v2 JSON contract, schemas.py dual-value rule, money_display formatter, get_analytics route + db.get_analytics_with_filters/get_analytics_sources"
  - phase: 09-spa-scaffold
    provides: "SPA shell + auth; analytics is the read-only pilot page this widening gates"
provides:
  - "Analytics schema widened to full legacy parity (D-01): by_source[] deep-dive, extremes, avg_stages, sources"
  - "AnalyticsBySource + AnalyticsExtremes nested Pydantic models (money _display twins; ratios bare per D-14)"
  - "GET /api/v2/analytics surfaces the previously-discarded get_analytics_sources() result"
  - "Wave-0 contract test (tests/test_analytics_contract.py) gating PAGE-01 backend parity"
affects: [10-02 analytics SPA page, signals/history/staged read-only migrations, PAGE-01 verification]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Nested-model widening of an existing flat schema while keeping all prior fields (additive serialization only)"
    - "httpx ASGITransport + AsyncClient + session-loop db_pool for DB-backed /api/v2 contract tests (single-loop pattern from test_pending_stages_sse.py) — avoids the TestClient blocking-portal loop split"
    - "require_user dependency override to auth read-only route tests without the DB-writing form-login path"

key-files:
  created:
    - "tests/test_analytics_contract.py"
  modified:
    - "api/schemas.py"
    - "api/analytics.py"

key-decisions:
  - "Authenticate read-only contract tests via app.dependency_overrides[require_user] instead of the form-login round-trip — /login calls db.get_failed_login_count mid-request, which races the asyncpg pool under TestClient's blocking-portal loop"
  - "Adopt the httpx ASGITransport + asyncio(loop_scope=session) pattern (test_pending_stages_sse.py) so the pool and the request handler share one event loop; TestClient-based DB-route tests fail with 'another operation is in progress' / 'attached to a different loop' in isolation"
  - "win_rate / profit_factor stay bare floats (no _display twin) per D-14; only money fields (net_pnl/best/worst) get _display twins"
  - "avg_stages passed through unchanged (None on the all-source view, Pitfall 3) — never defaulted to 0, so the SPA renders the Avg-Stages card only when a source filter is active"

patterns-established:
  - "Additive schema widening: nested BaseModel classes declared ABOVE the widened model; existing fields untouched"
  - "None-guarded money_display twins for nullable money fields (best_trade/worst_trade): value plus '*_display = money_display(v) if v is not None else None'"

requirements-completed: [PAGE-01]

# Metrics
duration: ~35min
completed: 2026-06-06
---

# Phase 10 Plan 01: Analytics API Parity Widening Summary

**Widened `/api/v2/analytics` to full legacy parity (D-01) — surfacing the per-source `by_source[]` deep-dive, overall `extremes`, conditional `avg_stages`, and the previously-discarded `sources` list — all additive serialization over the data `db.get_analytics_with_filters()` already computes, gated by a Wave-0 contract test.**

## Performance

- **Duration:** ~35 min (extended by test-harness event-loop investigation)
- **Tasks:** 3 completed
- **Files modified:** 2 (+1 created)

## Accomplishments
- Added `AnalyticsBySource` + `AnalyticsExtremes` nested models and widened `Analytics` with `by_source`/`extremes`/`avg_stages`/`sources` (all prior flat-summary fields preserved).
- Rewired `get_analytics` to capture `sources = await db.get_analytics_sources()` (no longer discarded) and map the by-source/extremes deep-dive with None-guarded `money_display()` twins; ratios kept raw (D-14); `avg_stages` passed through (None on all-source view).
- Authored a green Wave-0 contract test proving the PAGE-01 backend parity surface; bot core (`executor.py`/`trade_manager.py`/`db.py`/`mt5_connector.py`) byte-for-byte unchanged.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add AnalyticsBySource + AnalyticsExtremes models, widen Analytics** - `39d07fb` (feat)
2. **Task 2: Surface by_source/extremes/avg_stages/sources in the route** - `1c89069` (feat)
3. **Task 3: Wave-0 analytics contract test** - `e40b74d` (test)

_Tasks 1/2 carried `tdd="true"`; the gating behavioral test is the Wave-0 contract (Task 3). Tasks 1/2 are additive schema/serialization changes verified by `ast.parse` + acceptance greps, then proven by the Task 3 contract test._

## Files Created/Modified
- `api/schemas.py` - Added `AnalyticsBySource` (money `_display` twins on net_pnl/best/worst; `win_rate`/`profit_factor` bare per D-14) and `AnalyticsExtremes`; widened `Analytics` with `by_source: list[AnalyticsBySource] = []`, `extremes: AnalyticsExtremes`, `avg_stages: float | None = None`, `sources: list[str] = []`.
- `api/analytics.py` - Captured `sources` (was discarded); built `by_source` list and `extremes` with None-guarded `money_display()` twins; `avg_stages` passed through; imported the two new models; updated module docstring.
- `tests/test_analytics_contract.py` (new) - 5 contract tests (4 active, 1 source-filter test skips on empty DB) over GET `/api/v2/analytics` via httpx ASGITransport on the session loop.

## Verification

- `pytest tests/test_analytics_contract.py -x` → **4 passed, 1 skipped, exit 0** (Python 3.12 container against dev Postgres on :5433).
- The skipped test (`test_source_filtered_call_is_well_formed`) skips cleanly when no analytics sources are seeded — it asserts contract shape for the source-filter path only when data exists; documented as intentional.
- `git diff executor.py trade_manager.py db.py mt5_connector.py` → ZERO changes (bot core untouched).
- No `:.Nf` / `toFixed` literal in `api/analytics.py` (formatting routes through `api/formatting.money_display` only).
- `ast.parse` clean on `api/schemas.py` and `api/analytics.py`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Contract test harness rewritten to the single-loop httpx pattern**
- **Found during:** Task 3
- **Issue:** The plan instructed copying the `_login` + `session_client` (form-login over `TestClient`) pattern from `tests/test_api_contract.py`. For a DB-touching route under the installed pytest-asyncio 0.25.3 / anyio / httpx 0.28.1 stack, `TestClient`'s blocking portal runs each request on a fresh loop while the asyncpg pool is bound to the conftest session loop, raising `asyncpg.InterfaceError: another operation is in progress` / `RuntimeError: ... attached to a different loop`. The existing `test_api_contract.py` `session_client` tests reproduce the identical failure in isolation — this is the documented pre-existing single-loop constraint (08-02-SUMMARY), not a new defect.
- **Fix:** Modeled the test on `tests/test_pending_stages_sse.py` — `pytest.mark.asyncio(loop_scope="session")` + `httpx.ASGITransport`/`AsyncClient` + the session-scoped `db_pool` fixture, so the pool and the request handler share one loop. Auth is seeded via `app.dependency_overrides[require_user]` (read-only route) to avoid the DB-writing `/login` path entirely. The 401-without-session contract remains covered in `test_api_contract.py`.
- **Files modified:** tests/test_analytics_contract.py
- **Commit:** e40b74d

## Known Stubs

None — the widening wires real `db.get_analytics_with_filters()` / `db.get_analytics_sources()` output end to end; no hardcoded empty values flow to the response beyond the model defaults (`by_source=[]`, `sources=[]`, `avg_stages=None`), which correctly mirror the empty-data and all-source-view cases.

## Threat Flags

None — the widening adds response fields only. The route stays `Depends(require_user)` (session-gated, inherited Phase 8/9); no new endpoints, auth paths, or query construction were introduced (T-10-01 mitigation preserved; T-10-02 filter params remain int-coerced / asyncpg-parameterized).
