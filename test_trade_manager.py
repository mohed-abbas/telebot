"""Tests for trade_manager.py — zone logic, stale checks, execution flow."""

import asyncio
import pytest

import db
from models import AccountConfig, Direction, GlobalConfig, SignalAction, SignalType
from mt5_connector import DryRunConnector
from trade_manager import TradeManager


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


@pytest.fixture
def connector(account):
    c = DryRunConnector(account.name, account.server, account.login, "pass")
    asyncio.get_event_loop().run_until_complete(c.connect())
    return c


@pytest.fixture
def tm(connector, account, global_config):
    return TradeManager(
        connectors={account.name: connector},
        accounts=[account],
        global_config=global_config,
    )


class TestStaleCheck:
    def test_sell_price_below_tp1_is_stale(self, tm):
        signal = SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="test",
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0), sl=4986.0,
            tps=[4975.0, 4973.0], target_tp=4973.0,
        )
        result = tm._check_stale(signal, current_price=4970.0)
        assert result is not None
        assert "below TP1" in result

    def test_sell_price_above_tp1_not_stale(self, tm):
        signal = SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="test",
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0), sl=4986.0,
            tps=[4975.0, 4973.0], target_tp=4973.0,
        )
        result = tm._check_stale(signal, current_price=4980.0)
        assert result is None

    def test_buy_price_above_tp1_is_stale(self, tm):
        signal = SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="test",
            direction=Direction.BUY,
            entry_zone=(2140.0, 2145.0), sl=2135.0,
            tps=[2150.0, 2155.0], target_tp=2155.0,
        )
        result = tm._check_stale(signal, current_price=2155.0)
        assert result is not None

    def test_buy_price_below_tp1_not_stale(self, tm):
        signal = SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="test",
            direction=Direction.BUY,
            entry_zone=(2140.0, 2145.0), sl=2135.0,
            tps=[2150.0, 2155.0], target_tp=2155.0,
        )
        result = tm._check_stale(signal, current_price=2142.0)
        assert result is None

    def test_no_tps_not_stale(self, tm):
        signal = SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="test",
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0), sl=4986.0,
            tps=[], target_tp=None,
        )
        result = tm._check_stale(signal, current_price=4970.0)
        assert result is None


class TestDetermineOrderType:
    def test_sell_price_in_zone_market(self, tm):
        use_market, limit_price = tm._determine_order_type(
            Direction.SELL, current_price=4980.0, zone_low=4978.0, zone_high=4982.0,
        )
        assert use_market is True

    def test_sell_price_above_zone_market(self, tm):
        use_market, limit_price = tm._determine_order_type(
            Direction.SELL, current_price=4985.0, zone_low=4978.0, zone_high=4982.0,
        )
        assert use_market is True

    def test_sell_price_below_zone_limit(self, tm):
        use_market, limit_price = tm._determine_order_type(
            Direction.SELL, current_price=4975.0, zone_low=4978.0, zone_high=4982.0,
        )
        assert use_market is False
        assert limit_price == 4980.0  # zone midpoint

    def test_buy_price_in_zone_market(self, tm):
        use_market, limit_price = tm._determine_order_type(
            Direction.BUY, current_price=2142.0, zone_low=2140.0, zone_high=2145.0,
        )
        assert use_market is True

    def test_buy_price_below_zone_market(self, tm):
        use_market, limit_price = tm._determine_order_type(
            Direction.BUY, current_price=2138.0, zone_low=2140.0, zone_high=2145.0,
        )
        assert use_market is True

    def test_buy_price_above_zone_limit(self, tm):
        use_market, limit_price = tm._determine_order_type(
            Direction.BUY, current_price=2150.0, zone_low=2140.0, zone_high=2145.0,
        )
        assert use_market is False
        assert limit_price == 2142.5  # zone midpoint


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


class TestModifySL:
    @pytest.mark.asyncio
    async def test_move_sl_to_breakeven(self, tm, connector):
        await connector.open_order("XAUUSD", __import__("mt5_connector").OrderType.MARKET_SELL, 0.10, price=4980.0, sl=4986.0, tp=4973.0)

        signal = SignalAction(
            type=SignalType.MODIFY_SL, symbol="XAUUSD", raw_text="Move SL to BE",
            new_sl=0.0,  # sentinel for breakeven
        )
        results = await tm.handle_signal(signal)
        assert len(results) == 1
        assert results[0]["status"] == "sl_modified"
        assert results[0]["new_sl"] == 4980.0  # entry price
