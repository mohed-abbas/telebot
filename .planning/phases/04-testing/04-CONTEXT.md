# Phase 4: Testing - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Full test suite covering MT5 mocks, integration flows, async concurrency, and signal regression. Correctness of all prior hardening changes is verified by an automated test suite.

Requirements: TEST-01, TEST-02, TEST-03, TEST-04, TEST-05

</domain>

<decisions>
## Implementation Decisions

### Test database strategy
- Use **local docker-compose.dev.yml PostgreSQL** for tests — same dev database, set DATABASE_URL in test config
- No CI/CD yet — tests run locally only for now
- Tests should create/drop a test schema or use transaction rollback to avoid polluting dev data

### Signal regression test data
- User will **provide real Telegram signal messages** for regression tests (mostly consistent format)
- Extend existing test_signal_parser.py fixtures with real-world samples
- Include edge cases based on parser regex patterns
- User provides samples during execution — plan should include a placeholder test file that's easy to extend

### Claude's Discretion
- pytest configuration (pyproject.toml vs pytest.ini vs conftest.py)
- MT5 connector mock design (fixture structure, which error scenarios)
- Trade manager integration test design (how to wire mocked connectors + real DB)
- Async concurrency test approach (how to simulate concurrent signals, test lock contention)
- Test file organization (tests/ directory structure)
- conftest.py fixture design (DB setup/teardown, mock connectors, test accounts)
- Coverage thresholds (if any)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing tests
- `test_signal_parser.py` — Existing signal parser tests (extend, don't rewrite)
- `test_risk_calculator.py` — Existing risk calculator tests (reference for patterns)
- `test_trade_manager.py` — Existing trade manager tests (extend with integration tests)

### Code to test
- `mt5_connector.py` — DryRunConnector, MT5LinuxConnector, ping(), EOFError handling, reconnect password
- `trade_manager.py` — Zone logic functions (module-level), stale re-check, SL/TP validation, cleanup race fix
- `executor.py` — Heartbeat, reconnect, kill switch, signal gating, is_accepting_signals()
- `signal_parser.py` — parse_signal(), is_signal_like(), _extract_symbol_from_text()
- `db.py` — asyncpg pool, all query functions, archive_old_trades()

### Infrastructure
- `docker-compose.dev.yml` — Local PostgreSQL for test database
- `requirements.txt` — asyncpg already present; needs pytest, pytest-asyncio, pytest-mock added to dev deps

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `test_signal_parser.py` — Existing test patterns and fixtures to extend
- `test_risk_calculator.py` — Reference for test structure conventions
- `mt5_connector.py:DryRunConnector` — Already a mock-like implementation, can be used directly in integration tests

### Established Patterns
- Test files named `test_<module>.py` in project root (not tests/ subdirectory currently)
- Existing tests use basic assert statements (no pytest fixtures yet)
- DryRunConnector simulates MT5 responses — useful as base for test scenarios

### Integration Points
- `db.init_db(database_url)` — Tests need to call this with test DATABASE_URL
- `db.close_db()` — Tests must clean up connection pool
- Module-level pure functions in trade_manager.py (is_price_in_buy_zone, etc.) — easy to unit test directly

</code_context>

<specifics>
## Specific Ideas

- Use DryRunConnector as the base for MT5 mock tests — it already simulates responses
- Module-level zone functions and validation functions in trade_manager.py are pure — test them directly without any mocking
- User will paste real Telegram signals into a test fixture file during execution

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-testing*
*Context gathered: 2026-03-22*
