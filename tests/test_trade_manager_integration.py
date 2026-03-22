"""Integration tests for trade manager with real DB + PricedDryRunConnector.

Requires PostgreSQL running via docker-compose.dev.yml on port 5433.
"""

import pytest
import pytest_asyncio

import db
from models import AccountConfig, Direction, GlobalConfig, SignalAction, SignalType
from mt5_connector import DryRunConnector, OrderType
from trade_manager import TradeManager


# ── PricedDryRunConnector ────────────────────────────────────────────


class PricedDryRunConnector(DryRunConnector):
    """DryRunConnector that returns configurable fake prices."""

    def __init__(
        self,
        *args,
        prices: dict[str, tuple[float, float]] | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._prices = prices or {"XAUUSD": (4980.0, 4981.0)}

    async def get_price(self, symbol: str) -> tuple[float, float] | None:
        return self._prices.get(symbol)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def priced_connector():
    """Connected PricedDryRunConnector with XAUUSD at (4980.0, 4981.0)."""
    c = PricedDryRunConnector(
        "test-acct", "TestServer", 12345, "pass",
        prices={"XAUUSD": (4980.0, 4981.0)},
    )
    await c.connect()
    yield c
    await c.disconnect()


@pytest.fixture
def tm(priced_connector, account, global_config, db_pool):
    """TradeManager with single priced connector."""
    return TradeManager(
        connectors={account.name: priced_connector},
        accounts=[account],
        global_config=global_config,
    )


@pytest.fixture
def multi_account_tm(db_pool, global_config):
    """TradeManager with 2 accounts and 2 priced connectors (synchronous fixture)."""
    # We create connectors but need to connect them in the test (async)
    acct1 = AccountConfig(
        name="acct-1", server="TestServer", login=11111,
        password_env="TEST_PASS", risk_percent=1.0, max_lot_size=1.0,
        max_daily_loss_percent=3.0, max_open_trades=3, enabled=True,
    )
    acct2 = AccountConfig(
        name="acct-2", server="TestServer", login=22222,
        password_env="TEST_PASS", risk_percent=1.0, max_lot_size=1.0,
        max_daily_loss_percent=3.0, max_open_trades=3, enabled=True,
    )
    c1 = PricedDryRunConnector(
        "acct-1", "TestServer", 11111, "pass",
        prices={"XAUUSD": (4980.0, 4981.0)},
    )
    c2 = PricedDryRunConnector(
        "acct-2", "TestServer", 22222, "pass",
        prices={"XAUUSD": (4980.0, 4981.0)},
    )
    return TradeManager(
        connectors={"acct-1": c1, "acct-2": c2},
        accounts=[acct1, acct2],
        global_config=global_config,
    ), c1, c2


# ── Tests: Full Signal Flow ──────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestFullSignalFlow:
    async def test_open_sell_market_in_zone(self, tm, priced_connector, make_signal):
        """SELL signal with price 4980 in zone 4978-4982 -> market order."""
        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )
        results = await tm.handle_signal(signal)

        assert len(results) == 1
        result = results[0]
        assert result["status"] == "executed"
        assert result["order_type"] == "market"
        assert result["ticket"] > 0

        # Position should exist in connector
        positions = await priced_connector.get_positions("XAUUSD")
        assert len(positions) == 1
        assert positions[0].direction == "sell"

    async def test_open_buy_limit_above_zone(self, tm, priced_connector, make_signal):
        """BUY signal with price above zone -> limit order at zone midpoint."""
        # Set price above the buy zone (2150 > 2145) but below TPs
        priced_connector._prices = {"XAUUSD": (2150.0, 2151.0)}

        signal = make_signal(
            direction=Direction.BUY,
            entry_zone=(2140.0, 2145.0),
            sl=2135.0,
            tps=[2160.0, 2170.0],
            target_tp=2170.0,
            symbol="XAUUSD",
        )
        results = await tm.handle_signal(signal)

        assert len(results) == 1
        result = results[0]
        assert result["status"] == "limit_placed"
        assert result["order_type"] == "limit"
        assert result["price"] == 2142.5  # zone midpoint

    async def test_open_sell_with_db_logging(self, tm, priced_connector, make_signal):
        """After handle_signal for OPEN, trade record exists in DB."""
        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )
        results = await tm.handle_signal(signal)
        assert results[0]["status"] == "executed"

        # Verify DB has a trade record
        trades = await db.get_recent_trades(limit=10)
        assert len(trades) >= 1
        trade = trades[0]
        assert trade["symbol"] == "XAUUSD"
        assert trade["direction"] == "sell"
        assert trade["account_name"] == "test-acct"


# ── Tests: Close and Modify ──────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestCloseAndModify:
    async def test_close_signal_removes_positions(self, tm, priced_connector):
        """Open a position, then send CLOSE signal -> position removed."""
        await priced_connector.open_order(
            "XAUUSD", OrderType.MARKET_SELL, 0.10,
            price=4980.0, sl=4986.0, tp=4973.0,
        )
        positions = await priced_connector.get_positions("XAUUSD")
        assert len(positions) == 1

        close_signal = SignalAction(
            type=SignalType.CLOSE, symbol="XAUUSD", raw_text="Close gold",
        )
        results = await tm.handle_signal(close_signal)
        assert len(results) == 1
        assert results[0]["status"] == "closed"

        positions = await priced_connector.get_positions("XAUUSD")
        assert len(positions) == 0

    async def test_modify_sl_breakeven(self, tm, priced_connector):
        """Open position at 4980, send MODIFY_SL with new_sl=0.0 -> SL becomes 4980.0."""
        await priced_connector.open_order(
            "XAUUSD", OrderType.MARKET_SELL, 0.10,
            price=4980.0, sl=4986.0, tp=4973.0,
        )

        modify_signal = SignalAction(
            type=SignalType.MODIFY_SL, symbol="XAUUSD",
            raw_text="Move SL to BE", new_sl=0.0,
        )
        results = await tm.handle_signal(modify_signal)
        assert len(results) == 1
        assert results[0]["status"] == "sl_modified"
        assert results[0]["new_sl"] == 4980.0

    async def test_close_partial_halves_volume(self, tm, priced_connector):
        """Open position vol=0.10, send CLOSE_PARTIAL 50% -> volume becomes 0.05."""
        await priced_connector.open_order(
            "XAUUSD", OrderType.MARKET_SELL, 0.10,
            price=4980.0, sl=4986.0, tp=4973.0,
        )

        partial_signal = SignalAction(
            type=SignalType.CLOSE_PARTIAL, symbol="XAUUSD",
            raw_text="Close 50%", close_percent=50.0,
        )
        results = await tm.handle_signal(partial_signal)
        assert len(results) == 1
        assert results[0]["status"] == "partial_closed"

        positions = await priced_connector.get_positions("XAUUSD")
        assert len(positions) == 1
        assert positions[0].volume == pytest.approx(0.05, abs=0.001)


# ── Tests: Daily Limit Enforcement ───────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestDailyLimitEnforcement:
    async def test_daily_limit_blocks_trades(self, priced_connector, account, db_pool, make_signal):
        """max_daily_trades=2: after 2 trades, 3rd is rejected."""
        cfg = GlobalConfig(
            default_target_tp=2,
            limit_order_expiry_minutes=30,
            max_daily_trades_per_account=2,
            max_daily_server_messages=500,
            stagger_delay_min=0,
            stagger_delay_max=0,
            lot_jitter_percent=0,
            sl_tp_jitter_points=0,
        )
        tm_limited = TradeManager(
            connectors={account.name: priced_connector},
            accounts=[account],
            global_config=cfg,
        )

        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )

        # Execute 2 trades
        r1 = await tm_limited.handle_signal(signal)
        assert r1[0]["status"] == "executed"

        # Clear positions so duplicate check doesn't block
        priced_connector._fake_positions.clear()

        r2 = await tm_limited.handle_signal(signal)
        assert r2[0]["status"] == "executed"

        # Clear positions again
        priced_connector._fake_positions.clear()

        # 3rd should be blocked by daily limit
        r3 = await tm_limited.handle_signal(signal)
        assert len(r3) == 1
        assert r3[0]["status"] == "skipped"
        assert "Daily trade limit" in r3[0]["reason"]


# ── Tests: Multi-Account Execution ───────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestMultiAccountExecution:
    async def test_signal_executes_on_both_accounts(self, multi_account_tm, make_signal):
        """OPEN signal with 2 accounts -> both execute."""
        tm_multi, c1, c2 = multi_account_tm
        await c1.connect()
        await c2.connect()

        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )
        results = await tm_multi.handle_signal(signal)

        # Both accounts should have results
        account_names = {r["account"] for r in results}
        assert "acct-1" in account_names
        assert "acct-2" in account_names

        executed = [r for r in results if r["status"] == "executed"]
        assert len(executed) == 2


# ── Tests: Zone Logic Integration ────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestZoneLogicIntegration:
    async def test_sell_in_zone_market_order(self, tm, priced_connector, make_signal):
        """Price 4980 in zone 4978-4982 -> market order (not limit)."""
        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )
        results = await tm.handle_signal(signal)
        assert results[0]["order_type"] == "market"

    async def test_buy_above_zone_limit_order(self, tm, priced_connector, make_signal):
        """Price 2150 above zone 2140-2145 -> limit order at 2142.5."""
        priced_connector._prices = {"XAUUSD": (2150.0, 2151.0)}

        signal = make_signal(
            direction=Direction.BUY,
            entry_zone=(2140.0, 2145.0),
            sl=2135.0,
            tps=[2160.0, 2170.0],
            target_tp=2170.0,
        )
        results = await tm.handle_signal(signal)
        assert results[0]["status"] == "limit_placed"
        assert results[0]["price"] == 2142.5


# ── Tests: Stale Signal Rejection ────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestStaleSignalIntegration:
    async def test_sell_price_below_tp1_rejected(self, tm, priced_connector, make_signal):
        """SELL signal with price below TP1 is rejected as stale."""
        # Set price below TP1 (4970 < 4975)
        priced_connector._prices = {"XAUUSD": (4970.0, 4971.0)}

        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )
        results = await tm.handle_signal(signal)
        assert len(results) == 1
        assert results[0]["status"] == "skipped"
        assert "TP1" in results[0]["reason"]
