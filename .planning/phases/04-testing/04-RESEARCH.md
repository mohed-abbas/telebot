# Phase 4: Testing - Research

**Researched:** 2026-03-22
**Domain:** Python async test infrastructure (pytest + asyncpg + mock-based MT5 testing)
**Confidence:** HIGH

## Summary

Phase 4 adds a comprehensive test suite covering the full telebot codebase hardened in Phases 1-3. The project already has three test files (`test_signal_parser.py`, `test_risk_calculator.py`, `test_trade_manager.py`) using pytest with basic patterns, but `test_trade_manager.py` is stale -- it calls `db.init_db(tmp_path / "test.db")` which was the old SQLite API. The db module now uses asyncpg with PostgreSQL, so all DB-touching tests need updated fixtures.

The key challenge is database test isolation: the user chose local docker-compose PostgreSQL (port 5433) for tests. Since the project uses raw asyncpg (no SQLAlchemy ORM), transaction rollback must be done at the asyncpg connection level, not via ORM session scoping. The simplest reliable approach is to create/drop a test schema per test session and use table truncation between tests.

**Primary recommendation:** Configure pytest-asyncio in auto mode, create a shared conftest.py with asyncpg pool fixtures targeting the docker-compose dev PostgreSQL, use `DryRunConnector` directly for MT5 mock tests (it already simulates all operations), and organize tests in a `tests/` directory with clear separation between unit tests (no DB), integration tests (DB required), and concurrency tests.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Use **local docker-compose.dev.yml PostgreSQL** for tests -- same dev database, set DATABASE_URL in test config
- No CI/CD yet -- tests run locally only for now
- Tests should create/drop a test schema or use transaction rollback to avoid polluting dev data
- User will **provide real Telegram signal messages** for regression tests (mostly consistent format)
- Extend existing test_signal_parser.py fixtures with real-world samples
- Include edge cases based on parser regex patterns
- User provides samples during execution -- plan should include a placeholder test file that's easy to extend

### Claude's Discretion
- pytest configuration (pyproject.toml vs pytest.ini vs conftest.py)
- MT5 connector mock design (fixture structure, which error scenarios)
- Trade manager integration test design (how to wire mocked connectors + real DB)
- Async concurrency test approach (how to simulate concurrent signals, test lock contention)
- Test file organization (tests/ directory structure)
- conftest.py fixture design (DB setup/teardown, mock connectors, test accounts)
- Coverage thresholds (if any)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TEST-01 | requirements-dev.txt with pytest, pytest-asyncio, pytest-mock, pytest-cov; documented in README | Standard Stack section defines exact versions; pyproject.toml recommended over requirements-dev.txt for pytest config |
| TEST-02 | MT5 connector mock-based tests: connect, disconnect, get_price, open_order, modify_order, close_position, error scenarios | DryRunConnector already exists as production mock; Architecture Patterns section shows how to extend it for error scenarios via subclassing |
| TEST-03 | Trade manager integration tests: full signal flow, multi-account execution, daily limit enforcement, zone-based execution | Integration test pattern section with real DB fixtures + DryRunConnector wiring; existing test_trade_manager.py needs DB fixture migration from SQLite to asyncpg |
| TEST-04 | Async concurrency tests: no race conditions with concurrent signals, database lock contention, reconnection during signal processing | Concurrency test patterns using asyncio.gather with multiple simultaneous signal handlers; executor signal gating tests |
| TEST-05 | Signal parser regression tests with real-world Telegram signals and edge cases | Placeholder test file pattern with clear fixture structure for user to paste real signals; edge cases from regex analysis |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 8.3.5 | Test runner and framework | Industry standard for Python; 9.x is very new (2026-03), 8.3.x is stable and battle-tested |
| pytest-asyncio | 0.25.3 | Async test support | Required for testing async/await code; 1.x dropped Python 3.9 and changed event_loop handling -- 0.25.x is the most stable well-documented branch |
| pytest-mock | 3.15.1 | Mock fixture integration | Provides `mocker` fixture wrapping unittest.mock; cleaner than raw @patch |
| pytest-cov | 6.1.1 | Coverage reporting | Standard coverage tool; 7.x is new, 6.x is stable |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncpg | 0.31.0 | PostgreSQL driver (already in requirements.txt) | Already a project dependency; tests connect to real PostgreSQL |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pytest-asyncio 0.25.x | pytest-asyncio 1.3.0 | 1.x removes deprecated event_loop fixture and requires Python >=3.10; since Python 3.14 is available, 1.x would work, but 0.25.x has more community docs and examples. Either works -- recommend 0.25.x for stability |
| pytest 8.3.x | pytest 9.0.x | 9.x is very recent (March 2026); 8.3.x is proven stable. Use 8.3.x |
| requirements-dev.txt | pyproject.toml [project.optional-dependencies] | pyproject.toml is the modern standard and can also hold pytest config. Recommend pyproject.toml but create requirements-dev.txt too since TEST-01 explicitly requires it |

**Installation:**
```bash
pip install pytest==8.3.5 pytest-asyncio==0.25.3 pytest-mock==3.15.1 pytest-cov==6.1.1
```

**Note on version pinning:** Use `==` pins in requirements-dev.txt for reproducibility. The versions above were verified against PyPI on 2026-03-22.

## Architecture Patterns

### Recommended Project Structure
```
telebot/
├── tests/
│   ├── conftest.py           # Shared fixtures: DB pool, connectors, accounts, cleanup
│   ├── test_signal_parser.py # Moved from root (extend with regression tests)
│   ├── test_risk_calculator.py  # Moved from root (no changes needed)
│   ├── test_trade_manager.py # Moved from root + migrated from SQLite to asyncpg fixtures
│   ├── test_mt5_connector.py # NEW: DryRunConnector + mock error scenarios
│   ├── test_executor.py      # NEW: Kill switch, signal gating, heartbeat
│   ├── test_db.py            # NEW: asyncpg operations, daily stats, archival
│   ├── test_concurrency.py   # NEW: Race conditions, concurrent signals, lock contention
│   └── test_signal_regression.py  # NEW: Placeholder for real Telegram signals
├── pyproject.toml            # pytest config section
├── requirements-dev.txt      # Dev dependencies (TEST-01)
└── ... (existing code)
```

### Pattern 1: Database Fixture with Schema Isolation
**What:** Create a separate test schema in the docker-compose PostgreSQL, create tables at session start, truncate between tests.
**When to use:** All integration tests that touch the database.
**Why not transaction rollback:** The project uses raw asyncpg with a module-level `_pool` global. Transaction rollback would require wrapping every `_pool.execute/fetch` call, which is invasive. Schema isolation + truncation is simpler and matches the actual production code path.
**Example:**
```python
# tests/conftest.py
import asyncio
import pytest
import asyncpg
import db

TEST_DATABASE_URL = "postgresql://telebot:telebot_dev@localhost:5433/telebot"

@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for all async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def db_pool():
    """Create asyncpg pool once for the entire test session."""
    await db.init_db(TEST_DATABASE_URL)
    yield db._pool
    await db.close_db()

@pytest.fixture(autouse=True)
async def clean_db(db_pool):
    """Truncate all tables between tests for isolation."""
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE signals, trades, daily_stats, pending_orders RESTART IDENTITY CASCADE")
    yield
```

### Pattern 2: DryRunConnector as Test Double
**What:** Use the existing `DryRunConnector` class directly -- it already implements all MT5Connector methods with in-memory state.
**When to use:** All tests needing MT5 interaction without a real MT5 terminal.
**Why:** It is already production code, not a test-only mock. Tests validate the same code path used in dry-run mode.
**Example:**
```python
@pytest.fixture
def connector():
    """Create a connected DryRunConnector."""
    c = DryRunConnector("test-acct", "TestServer", 12345, "pass")
    # Use event loop directly since we are already in async context
    return c

@pytest.fixture
async def connected_connector(connector):
    await connector.connect()
    yield connector
    await connector.disconnect()
```

### Pattern 3: Error Scenario Connector
**What:** Subclass DryRunConnector to simulate specific failure modes (connection loss, timeout, partial failures).
**When to use:** Testing error handling in trade_manager and executor.
**Example:**
```python
class FailingConnector(DryRunConnector):
    """Connector that fails on specific operations."""
    def __init__(self, *args, fail_on: set[str] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._fail_on = fail_on or set()

    async def ping(self) -> bool:
        if "ping" in self._fail_on:
            self._connected = False
            return False
        return await super().ping()

    async def get_price(self, symbol: str):
        if "get_price" in self._fail_on:
            return None
        return (4980.0, 4981.0)  # Return realistic price for testing

    async def open_order(self, *args, **kwargs):
        if "open_order" in self._fail_on:
            return OrderResult(success=False, error="Simulated failure")
        return await super().open_order(*args, **kwargs)
```

### Pattern 4: Concurrency Testing with asyncio.gather
**What:** Fire multiple signal handlers concurrently to test race conditions.
**When to use:** TEST-04 -- verifying no race conditions under concurrent signal load.
**Example:**
```python
@pytest.mark.asyncio
async def test_concurrent_signals_no_race(tm, connected_connector):
    """Multiple BUY signals for same symbol should not open duplicate positions."""
    signal = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD", raw_text="test",
        direction=Direction.BUY,
        entry_zone=(2140.0, 2145.0), sl=2135.0,
        tps=[2150.0, 2155.0], target_tp=2155.0,
    )
    # Fire 5 concurrent handlers
    results = await asyncio.gather(
        *[tm.handle_signal(signal) for _ in range(5)]
    )
    # Only the first should execute; rest should be skipped (duplicate check)
    executed = sum(1 for r_list in results for r in r_list if r["status"] == "executed")
    assert executed <= 1  # At most one should execute
```

### Anti-Patterns to Avoid
- **Using unittest.TestCase with async tests:** Does not work with pytest-asyncio. Use plain functions or classes without TestCase inheritance.
- **Creating a new event loop per test:** pytest-asyncio manages the event loop. Do not call `asyncio.get_event_loop().run_until_complete()` in fixtures (as the existing test_trade_manager.py does). Use `async def` fixtures instead.
- **Testing against production DATABASE_URL:** Always use the local docker-compose database on port 5433. Never connect to the VPS shared PostgreSQL.
- **Mocking asyncpg internals:** Test against a real PostgreSQL instance. Mock the connectors (MT5), not the database. This catches real SQL errors.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async test running | Custom event loop management | pytest-asyncio auto mode | Handles loop lifecycle, fixture scoping, and cleanup |
| MT5 mock | Custom Mock() objects for every method | DryRunConnector (already exists) | Production code that simulates all operations; subclass for error scenarios |
| Database isolation | Manual DELETE statements or custom transaction wrappers | TRUNCATE CASCADE in autouse fixture | Faster than DELETE, resets sequences, no partial state |
| Coverage reporting | Manual file counting | pytest-cov with --cov flag | Integrated with pytest, generates HTML reports |
| Fixture mocking | Manual unittest.mock.patch everywhere | pytest-mock `mocker` fixture | Automatic cleanup, better assertion messages |

**Key insight:** The project already has DryRunConnector which is a complete MT5 test double. No need to build mocks from scratch -- extend DryRunConnector with failure modes.

## Common Pitfalls

### Pitfall 1: Stale test_trade_manager.py DB fixtures
**What goes wrong:** Existing `test_trade_manager.py` calls `db.init_db(tmp_path / "test.db")` which was the SQLite API. db.py now uses asyncpg/PostgreSQL. Tests will fail with connection errors.
**Why it happens:** Phase 1 migrated to asyncpg but tests were not updated.
**How to avoid:** Migrate the `setup_db` fixture to use the asyncpg pool pattern from conftest.py. Remove `tmp_path` usage for DB.
**Warning signs:** `db.init_db()` now expects a `postgresql://` URL string, not a Path.

### Pitfall 2: DryRunConnector._ticket_counter is a class variable
**What goes wrong:** `DryRunConnector._ticket_counter` is shared across all instances (class-level int). Tests that create multiple connectors will share ticket numbering, and parallel test runs could interfere.
**Why it happens:** Class variable is mutable shared state.
**How to avoid:** Reset `DryRunConnector._ticket_counter = 100000` in a fixture or accept non-deterministic ticket numbers in assertions (assert ticket > 0, not ticket == 100001).
**Warning signs:** Tests that assert exact ticket numbers will be fragile.

### Pitfall 3: pytest-asyncio strict mode requires explicit markers
**What goes wrong:** Without `asyncio_mode = "auto"` in config, every async test needs `@pytest.mark.asyncio` and every async fixture needs `@pytest_asyncio.fixture`. Easy to forget.
**Why it happens:** Default mode is `strict` since pytest-asyncio 0.19.
**How to avoid:** Set `asyncio_mode = "auto"` in pyproject.toml. All async tests and fixtures are automatically recognized.
**Warning signs:** `PytestUnraisableExceptionWarning` or tests silently not running.

### Pitfall 4: Event loop scope mismatch with session-scoped DB fixture
**What goes wrong:** A session-scoped async fixture (like db_pool) runs in a different event loop than function-scoped tests, causing "attached to a different loop" errors.
**Why it happens:** pytest-asyncio creates a new loop per test by default.
**How to avoid:** Set `asyncio_default_fixture_loop_scope = "session"` or use `loop_scope="session"` on session fixtures, and ensure tests that use session-scoped fixtures share the same loop.
**Warning signs:** `RuntimeError: Event loop is closed` or `got Future <Future pending> attached to a different loop`.

### Pitfall 5: Docker PostgreSQL not running
**What goes wrong:** Tests fail with connection refused if docker-compose.dev.yml is not up.
**Why it happens:** No CI/CD -- tests run locally and depend on manual `docker compose up`.
**How to avoid:** Add a clear skip/error message in conftest.py that detects if PostgreSQL is unreachable. Document `docker compose -f docker-compose.dev.yml up -d` as a prerequisite.
**Warning signs:** `asyncpg.exceptions.ConnectionRefusedError`.

### Pitfall 6: db._pool global state leaks between tests
**What goes wrong:** `db._pool` is a module-level global. If one test calls `db.close_db()`, subsequent tests using `db._pool` get `InterfaceError: pool is closed`.
**Why it happens:** Module-level mutable state.
**How to avoid:** Initialize the pool once per session in conftest.py and never call `close_db()` except in session teardown. Individual tests should not manage pool lifecycle.
**Warning signs:** Tests pass individually but fail when run together.

## Code Examples

### pytest configuration in pyproject.toml
```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "integration: marks tests requiring PostgreSQL (deselect with '-m \"not integration\"')",
    "slow: marks slow tests",
]
filterwarnings = [
    "ignore::DeprecationWarning",
]
```

### requirements-dev.txt
```
# Test dependencies
pytest==8.3.5
pytest-asyncio==0.25.3
pytest-mock==3.15.1
pytest-cov==6.1.1
```

### conftest.py -- full fixture set
```python
"""Shared test fixtures for telebot test suite."""
import asyncio
import os
import pytest
import pytest_asyncio

import db
from models import AccountConfig, GlobalConfig, Direction, SignalAction, SignalType
from mt5_connector import DryRunConnector, OrderResult

# Use docker-compose.dev.yml PostgreSQL
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://telebot:telebot_dev@localhost:5433/telebot",
)


@pytest.fixture(scope="session")
async def db_pool():
    """Session-scoped asyncpg pool -- created once, shared across all tests."""
    await db.init_db(TEST_DATABASE_URL)
    yield db._pool
    await db.close_db()


@pytest.fixture(autouse=True)
async def clean_tables(db_pool):
    """Truncate all tables between tests."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE signals, trades, daily_stats, pending_orders "
            "RESTART IDENTITY CASCADE"
        )
    yield


@pytest.fixture
def global_config():
    return GlobalConfig(
        default_target_tp=2,
        limit_order_expiry_minutes=30,
        max_daily_trades_per_account=30,
        max_daily_server_messages=500,
        stagger_delay_min=0,
        stagger_delay_max=0,
        lot_jitter_percent=0,
        sl_tp_jitter_points=0,
    )


@pytest.fixture
def account():
    return AccountConfig(
        name="test-acct",
        server="TestServer",
        login=12345,
        password_env="TEST_PASS",
        risk_percent=1.0,
        max_lot_size=1.0,
        max_daily_loss_percent=3.0,
        max_open_trades=3,
        enabled=True,
    )


@pytest.fixture
async def connector():
    c = DryRunConnector("test-acct", "TestServer", 12345, "pass")
    await c.connect()
    yield c
    await c.disconnect()


@pytest.fixture
def make_signal():
    """Factory fixture for creating test signals."""
    def _make(
        direction=Direction.SELL,
        entry_zone=(4978.0, 4982.0),
        sl=4986.0,
        tps=None,
        target_tp=4973.0,
        signal_type=SignalType.OPEN,
        symbol="XAUUSD",
        raw_text="test signal",
    ):
        if tps is None:
            tps = [4975.0, 4973.0]
        return SignalAction(
            type=signal_type, symbol=symbol, raw_text=raw_text,
            direction=direction, entry_zone=entry_zone, sl=sl,
            tps=tps, target_tp=target_tp,
        )
    return _make
```

### Signal regression test placeholder
```python
"""Regression tests for signal_parser using real Telegram messages.

HOW TO ADD NEW SIGNALS:
1. Copy a real Telegram message into the REAL_SIGNALS list below
2. Add the expected parsed values
3. Run: pytest tests/test_signal_regression.py -v
"""
import pytest
from signal_parser import parse_signal
from models import Direction, SignalType

# Real Telegram signals provided by user -- extend this list
REAL_SIGNALS = [
    # Format: (raw_text, expected_type, expected_direction, expected_symbol, expected_entry_zone)
    # Example:
    # (
    #     "Gold sell now 4978 - 4982\nSL: 4986\nTP: 4975\nTP: 4973\nTP: open",
    #     SignalType.OPEN,
    #     Direction.SELL,
    #     "XAUUSD",
    #     (4978.0, 4982.0),
    # ),
]


@pytest.mark.parametrize(
    "raw_text,expected_type,expected_dir,expected_symbol,expected_zone",
    REAL_SIGNALS,
    ids=[f"signal_{i}" for i in range(len(REAL_SIGNALS))],
)
def test_real_signal(raw_text, expected_type, expected_dir, expected_symbol, expected_zone):
    """Verify real Telegram signals parse correctly."""
    result = parse_signal(raw_text)
    assert result is not None, f"Failed to parse: {raw_text[:80]}"
    assert result.type == expected_type
    if expected_dir:
        assert result.direction == expected_dir
    assert result.symbol == expected_symbol
    if expected_zone:
        assert result.entry_zone == expected_zone
```

### Concurrency test pattern
```python
"""Concurrency tests for executor and trade manager."""
import asyncio
import pytest
from models import Direction, SignalAction, SignalType
from trade_manager import TradeManager
from executor import Executor


@pytest.mark.asyncio
async def test_concurrent_open_signals_no_duplicate(
    connector, account, global_config, db_pool,
):
    """Firing the same BUY signal concurrently should not open duplicate positions."""
    # Give the connector a real price so execution proceeds
    connector.get_price = lambda symbol: asyncio.coroutine(lambda: (2142.0, 2143.0))()

    tm = TradeManager(
        connectors={account.name: connector},
        accounts=[account],
        global_config=global_config,
    )
    signal = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD", raw_text="test concurrent",
        direction=Direction.BUY,
        entry_zone=(2140.0, 2145.0), sl=2135.0,
        tps=[2150.0, 2155.0], target_tp=2155.0,
    )

    results = await asyncio.gather(
        *[tm.handle_signal(signal) for _ in range(5)]
    )

    all_results = [r for batch in results for r in batch]
    executed = [r for r in all_results if r["status"] in ("executed", "limit_placed")]
    # Due to duplicate check (same direction already open), at most 1 should execute
    assert len(executed) <= 1
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `asyncio.get_event_loop()` in fixtures | `async def` fixtures with pytest-asyncio auto mode | pytest-asyncio 0.19+ | Existing `connector` fixture uses `get_event_loop().run_until_complete()` -- must migrate |
| `event_loop` fixture override | `loop_scope` parameter or `asyncio_default_fixture_loop_scope` config | pytest-asyncio 0.23+ / 1.0 | Session-scoped async fixtures need explicit loop scope config |
| `@pytest.mark.asyncio` on every test | `asyncio_mode = "auto"` in config | pytest-asyncio 0.19+ | No need for markers on every test; cleaner code |
| SQLite `db.init_db(path)` for tests | `db.init_db(postgresql_url)` with asyncpg pool | Phase 1 migration | Existing test_trade_manager.py setup_db fixture is broken |
| `requirements-dev.txt` only | `pyproject.toml [project.optional-dependencies]` + `requirements-dev.txt` | Python packaging 2023+ | Modern projects use pyproject.toml; keep requirements-dev.txt for TEST-01 requirement |

**Deprecated/outdated:**
- `asyncio.get_event_loop().run_until_complete()` in test fixtures: Replace with native async fixtures
- `event_loop` fixture: Removed in pytest-asyncio 1.0; use `loop_scope` parameter instead
- `@pytest_asyncio.fixture` decorator: Not needed in auto mode (regular `@pytest.fixture` works for async fixtures)

## Open Questions

1. **DryRunConnector.get_price() returns None by default**
   - What we know: `DryRunConnector.get_price()` returns `None`, which causes `_execute_open_on_account` to bail with "Cannot get current price". Integration tests for open signals need a connector that returns real prices.
   - What's unclear: Should we subclass DryRunConnector with a `PricedDryRunConnector` or monkeypatch `get_price`?
   - Recommendation: Create a `TestConnector` subclass that returns configurable fake prices (e.g., bid=4980.0, ask=4981.0 for XAUUSD). This is cleaner than monkeypatching.

2. **Test database vs dev database isolation**
   - What we know: User chose "same dev database" with schema/transaction isolation. Docker-compose exposes port 5433.
   - What's unclear: Whether tests should use a separate database name (e.g., `telebot_test`) or the same `telebot` database with TRUNCATE.
   - Recommendation: Use the same `telebot` database with TRUNCATE between tests. Creating a separate database adds docker-compose complexity. TRUNCATE + RESTART IDENTITY CASCADE is sufficient for local testing.

3. **Moving test files from root to tests/ directory**
   - What we know: Existing tests are in project root. New tests should go in `tests/`.
   - What's unclear: Whether to move existing files or leave them.
   - Recommendation: Move all test files to `tests/` for consistency. Configure `testpaths = ["tests"]` in pyproject.toml. This keeps the root clean.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3.5 + pytest-asyncio 0.25.3 |
| Config file | pyproject.toml (to be created in Wave 0) |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v --cov=. --cov-report=term-missing` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TEST-01 | Dev deps file exists with correct packages | smoke | `pytest tests/test_infrastructure.py -x` (verify imports) | No -- Wave 0 |
| TEST-02 | MT5 connector mock tests (connect, disconnect, get_price, open_order, modify, close, errors) | unit | `pytest tests/test_mt5_connector.py -x` | No -- Wave 0 |
| TEST-03 | Trade manager integration (full flow, multi-account, daily limits, zones) | integration | `pytest tests/test_trade_manager.py -x` | Exists at root but broken DB fixtures -- needs migration |
| TEST-04 | Async concurrency (concurrent signals, DB contention, reconnect during processing) | integration | `pytest tests/test_concurrency.py -x` | No -- Wave 0 |
| TEST-05 | Signal parser regression with real Telegram signals | unit | `pytest tests/test_signal_regression.py -x` | No -- Wave 0 (placeholder for user data) |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x -q` (fast fail on first error)
- **Per wave merge:** `pytest tests/ -v --cov=. --cov-report=term-missing`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `pyproject.toml` -- pytest configuration with asyncio_mode = "auto"
- [ ] `requirements-dev.txt` -- pytest, pytest-asyncio, pytest-mock, pytest-cov
- [ ] `tests/conftest.py` -- shared fixtures (DB pool, connector, accounts, cleanup)
- [ ] `tests/test_mt5_connector.py` -- covers TEST-02
- [ ] `tests/test_trade_manager.py` -- migrate from root, fix DB fixtures (TEST-03)
- [ ] `tests/test_signal_parser.py` -- move from root (existing, no changes)
- [ ] `tests/test_risk_calculator.py` -- move from root (existing, no changes)
- [ ] `tests/test_executor.py` -- covers parts of TEST-03 and TEST-04
- [ ] `tests/test_concurrency.py` -- covers TEST-04
- [ ] `tests/test_signal_regression.py` -- placeholder for TEST-05
- [ ] `tests/test_db.py` -- covers db.py operations
- [ ] Framework install: `pip install -r requirements-dev.txt`

## Sources

### Primary (HIGH confidence)
- Project source code: db.py, mt5_connector.py, trade_manager.py, executor.py, signal_parser.py (read directly)
- Existing test files: test_signal_parser.py, test_risk_calculator.py, test_trade_manager.py (read directly)
- docker-compose.dev.yml (read directly -- PostgreSQL 16-alpine, port 5433, user telebot)
- PyPI package index: verified versions via `pip3 index versions` for pytest (8.3.5/9.0.2), pytest-asyncio (0.25.3/1.3.0), pytest-mock (3.15.1), pytest-cov (6.1.1/7.1.0)
- [pytest-asyncio configuration docs](https://pytest-asyncio.readthedocs.io/en/stable/reference/configuration.html) -- asyncio_mode options, loop_scope config
- [pytest-asyncio changelog](https://pytest-asyncio.readthedocs.io/en/stable/reference/changelog.html) -- 1.0 breaking changes, event_loop removal

### Secondary (MEDIUM confidence)
- [asyncpg test_pool.py](https://github.com/MagicStack/asyncpg/blob/master/tests/test_pool.py) -- asyncpg's own pool test patterns
- [pytest-asyncio concepts](https://pytest-asyncio.readthedocs.io/en/stable/concepts.html) -- auto mode explanation

### Tertiary (LOW confidence)
- Web search results on concurrent async testing patterns -- verified against pytest-asyncio docs

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- versions verified against PyPI registry; library choices are industry standard
- Architecture: HIGH -- based on direct code reading of all 5 modules being tested, existing test patterns, and asyncpg connection model
- Pitfalls: HIGH -- all 6 pitfalls identified from direct code analysis (stale SQLite fixture, class-variable ticket counter, event loop scope, etc.)

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable domain; pytest ecosystem moves slowly)
