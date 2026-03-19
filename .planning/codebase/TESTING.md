# Testing Patterns

**Analysis Date:** 2026-03-19

## Test Framework

**Runner:**
- pytest (referenced in imports across all test files)
- No configuration file (uses pytest defaults)
- Run with: `pytest` or `pytest test_*.py`

**Assertion Library:**
- Built-in pytest assertions: `assert condition`, `assert value == expected`

**Run Commands:**
```bash
pytest                          # Run all tests in current directory
pytest test_signal_parser.py    # Run specific test file
pytest -v                       # Verbose output with test names
pytest --asyncio-mode=auto      # For async tests (if needed)
```

## Test File Organization

**Location:**
- Co-located in project root with source code
- Test files: `test_signal_parser.py`, `test_risk_calculator.py`, `test_trade_manager.py`
- One test file per major module

**Naming:**
- File pattern: `test_<module_name>.py`
- Class pattern: `Test<FunctionName>` or `Test<Concept>` (e.g., `TestOpenSignalsZone`, `TestCalculateLotSize`)
- Function pattern: `test_<description>` (e.g., `test_sell_zone_with_multiple_tps()`, `test_basic_calculation()`)

**Structure:**
```
test_signal_parser.py
├── Module docstring: """Tests for signal_parser — 30+ signal variations."""
├── Import pytest and test fixtures
├── Class TestOpenSignalsZone:
│   ├── def test_sell_zone_with_multiple_tps(self):
│   ├── def test_buy_zone(self):
│   └── ...
├── Class TestCloseSignals:
│   └── ...
└── Class TestFormatParsedSignal:
    └── ...
```

## Test Structure

**Suite Organization:**

From `test_signal_parser.py`:
```python
class TestOpenSignalsZone:
    def test_sell_zone_with_multiple_tps(self):
        text = (
            "Gold sell now 4978 - 4982\n\n"
            "SL: 4986\n\n"
            "TP. 4975\n"
            "TP: 4973\n"
            "TP: 4971\n"
            "TP: 4969\n"
            "TP: open"
        )
        s = parse_signal(text)
        assert s is not None
        assert s.type == SignalType.OPEN
        assert s.symbol == "XAUUSD"
        assert s.direction == Direction.SELL
        assert s.entry_zone == (4978.0, 4982.0)
        assert s.sl == 4986.0
        assert len(s.tps) == 5
        assert s.tps[0] == 4975.0
        assert s.tps[1] == 4973.0
        assert s.tps[4] == "open"
        assert s.target_tp == 4973.0  # TP2
```

**Patterns:**
- One test method per scenario/condition
- Arrange-Act-Assert (AAA) pattern: Setup data, call function, assert results
- No setup methods per test in classes (no `setUp()` or `@pytest.fixture` per class)
- Descriptive test names that explain what is being tested and the expected behavior

## Mocking

**Framework:** Explicit test doubles via subclasses

From `test_trade_manager.py`:
```python
@pytest.fixture
def connector(account):
    c = DryRunConnector(account.name, account.server, account.login, "pass")
    asyncio.get_event_loop().run_until_complete(c.connect())
    return c
```

**Patterns:**
- Use `DryRunConnector` subclass for testing (simulates MT5 without real trades)
- Pass mock objects through pytest fixtures
- Mock external state through configuration: `trading_dry_run=True` flag

**What to Mock:**
- External services: `DryRunConnector` instead of real MT5 connection
- Database: Temporary database per test via `tmp_path` fixture
- HTTP calls: Could be mocked but currently tests use real calls (or test doubles)

**What NOT to Mock:**
- Pure business logic functions: `calculate_lot_size()`, `parse_signal()` tested directly
- Data structures: Dataclasses tested without mocking
- Simple utility functions: Tested with real implementation

## Fixtures and Factories

**Test Data:**

From `test_trade_manager.py`:
```python
@pytest.fixture(autouse=True)
def setup_db(tmp_path):
    """Initialize a temp database for each test."""
    db.init_db(tmp_path / "test.db")


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
```

**Location:**
- Fixtures defined at module level in test file (not separate factory files)
- Fixtures provide complete test doubles of production dataclasses
- `autouse=True` for database initialization (runs before every test)

## Coverage

**Requirements:** None enforced (no `.coverage` config, no pytest coverage plugin detected)

**View Coverage:**
```bash
pytest --cov=. --cov-report=html    # If pytest-cov installed
```

## Test Types

**Unit Tests:**
- Scope: Individual functions with fixed inputs/outputs
- Examples: `test_calculate_lot_size()`, `test_sell_zone_with_multiple_tps()`
- Approach: Direct function calls with assertions on return values

**Integration Tests:**
- Scope: Multiple components working together
- Examples: `test_close_all_positions()` in `test_trade_manager.py` (opens order, then closes via signal)
- Approach: Use mock connector, verify multi-step workflows

**E2E Tests:**
- Framework: Not used
- Bot behavior tested manually against real Telegram/Discord

## Common Patterns

**Async Testing:**

From `test_trade_manager.py`:
```python
class TestCloseSignal:
    @pytest.mark.asyncio
    async def test_close_all_positions(self, tm, connector):
        # Open a position first
        await connector.open_order("XAUUSD", __import__("mt5_connector").OrderType.MARKET_SELL, 0.10, price=4980.0, sl=4986.0, tp=4973.0)
        positions = await connector.get_positions("XAUUSD")
        assert len(positions) == 1

        signal = SignalAction(type=SignalType.CLOSE, symbol="XAUUSD", raw_text="Close gold")
        results = await tm.handle_signal(signal)

        assert len(results) == 1
        assert results[0]["status"] == "closed"

        positions = await connector.get_positions("XAUUSD")
        assert len(positions) == 0
```

- Use `@pytest.mark.asyncio` decorator for async tests
- Use `await` for all async operations
- Fixtures can return coroutines that are awaited during setup

**Error Testing:**

From `test_signal_parser.py`:
```python
class TestValidation:
    def test_buy_with_sl_above_entry_rejected(self):
        """BUY with SL above entry zone = invalid."""
        text = "Gold buy now 2140 - 2145\nSL: 2150\nTP: 2160\nTP: 2170"
        s = parse_signal(text)
        assert s is None

    def test_sell_with_sl_below_entry_rejected(self):
        """SELL with SL below entry zone = invalid."""
        text = "Gold sell now 4978 - 4982\nSL: 4970\nTP: 4960\nTP: 4950"
        s = parse_signal(text)
        assert s is None
```

- Invalid inputs tested by asserting `None` return
- Validation errors are communicated through return values, not exceptions
- No exception assertions (tests don't use `pytest.raises()`)

**Parametric Testing:**

From `test_risk_calculator.py`:
```python
def test_zone_with_dash_variants(self):
    """Test different dash types: - – —"""
    for dash in ["-", "–", "—"]:
        text = f"Gold sell now 4978 {dash} 4982\nSL: 4986\nTP: 4975\nTP: 4973"
        s = parse_signal(text)
        assert s is not None, f"Failed with dash: {dash!r}"
        assert s.entry_zone == (4978.0, 4982.0)
```

- Variations tested via loop rather than `@pytest.mark.parametrize`
- Inline loops keep related cases together

**Stochastic Testing:**

From `test_risk_calculator.py`:
```python
def test_jitter_varies_output(self):
    """With jitter, repeated calculations should produce different results."""
    results = set()
    for _ in range(50):
        lot = calculate_lot_size(
            account_balance=50000,
            risk_percent=2.0,
            sl_distance=5.0,
            max_lot_size=10.0,
            jitter_percent=5.0,
        )
        results.add(lot)
    # Larger lot size makes jitter visible after rounding
    assert len(results) > 1
```

- Randomized behavior tested by collecting multiple runs
- Assert that variation occurs (not that specific values appear)

## Test Organization by Module

**`test_signal_parser.py` (341 lines):**
- 11 test classes covering 30+ signal variations
- Classes: TestOpenSignalsZone, TestOpenSignalsSingle, TestValidation, TestCloseSignals, TestPartialClose, TestModifySL, TestModifyTP, TestNonSignals, TestFormatParsedSignal
- Coverage: Zone entries, single prices, close signals, partial closes, SL/TP modifications, validation, formatting

**`test_risk_calculator.py` (137 lines):**
- 3 test classes
- Classes: TestCalculateLotSize, TestSLDistance, TestSLJitter, TestTPJitter
- Coverage: Lot sizing with jitter, SL/TP distance calculations, randomization bounds

**`test_trade_manager.py` (187 lines):**
- 3 test classes
- Classes: TestStaleCheck, TestDetermineOrderType, TestCloseSignal, TestModifySL
- Coverage: Zone entry logic, order type selection, position closing, SL modifications
- Uses fixtures for database setup, config, account, connector, trade manager

---

*Testing analysis: 2026-03-19*
