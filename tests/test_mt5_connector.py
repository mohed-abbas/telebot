"""Tests for MT5 connector — DryRunConnector state management, error scenarios, and factory function.

Covers:
- connect/disconnect/ping state transitions
- Password clearing after connect
- get_price (always None for DryRunConnector)
- get_account_info defaults
- open_order (MARKET_BUY, MARKET_SELL), ticket assignment, position tracking
- modify_position (SL, TP, nonexistent ticket)
- close_position (full, partial, nonexistent ticket)
- cancel_pending and get_pending_orders
- get_positions filtering by symbol
- create_connector factory function
- FailingConnector error simulation
"""

import pytest

from mt5_connector import (
    AccountInfo,
    DryRunConnector,
    MT5LinuxConnector,
    OrderResult,
    OrderType,
    Position,
    create_connector,
)


class FailingConnector(DryRunConnector):
    """DryRunConnector subclass that simulates failures for specified operations."""

    def __init__(self, *args, fail_on: set[str] | None = None, **kwargs):
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
        return (4980.0, 4981.0)  # Override None default for tests needing prices

    async def open_order(self, *args, **kwargs):
        if "open_order" in self._fail_on:
            return OrderResult(success=False, error="Simulated failure")
        return await super().open_order(*args, **kwargs)


@pytest.fixture(autouse=True)
def reset_ticket_counter():
    """Reset class-level ticket counter to avoid cross-test interference."""
    DryRunConnector._ticket_counter = 100000
    yield


@pytest.fixture
def connector():
    """Fresh DryRunConnector (not connected)."""
    return DryRunConnector("test-acct", "TestServer", 12345, "secret_pass")


# ═══════════════════════════════════════════════════════════════════════
# CONNECT / DISCONNECT / PING
# ═══════════════════════════════════════════════════════════════════════


class TestDryRunConnectDisconnect:
    async def test_initially_disconnected(self, connector):
        assert connector.connected is False

    async def test_connect_returns_true(self, connector):
        result = await connector.connect()
        assert result is True

    async def test_connect_sets_connected_true(self, connector):
        await connector.connect()
        assert connector.connected is True

    async def test_connect_clears_password(self, connector):
        assert connector.password == "secret_pass"
        await connector.connect()
        assert connector.password == ""

    async def test_disconnect_sets_connected_false(self, connector):
        await connector.connect()
        assert connector.connected is True
        await connector.disconnect()
        assert connector.connected is False

    async def test_ping_when_connected(self, connector):
        await connector.connect()
        assert await connector.ping() is True

    async def test_ping_when_disconnected(self, connector):
        assert await connector.ping() is False

    async def test_ping_after_disconnect(self, connector):
        await connector.connect()
        await connector.disconnect()
        assert await connector.ping() is False


# ═══════════════════════════════════════════════════════════════════════
# GET PRICE
# ═══════════════════════════════════════════════════════════════════════


class TestDryRunGetPrice:
    async def test_get_price_returns_none(self, connector):
        """DryRunConnector.get_price always returns None — callers must handle this."""
        await connector.connect()
        result = await connector.get_price("XAUUSD")
        assert result is None

    async def test_get_price_returns_none_any_symbol(self, connector):
        await connector.connect()
        assert await connector.get_price("EURUSD") is None
        assert await connector.get_price("BTCUSD") is None


# ═══════════════════════════════════════════════════════════════════════
# GET ACCOUNT INFO
# ═══════════════════════════════════════════════════════════════════════


class TestDryRunAccountInfo:
    async def test_account_info_defaults(self, connector):
        await connector.connect()
        info = await connector.get_account_info()
        assert isinstance(info, AccountInfo)
        assert info.balance == 10000.0
        assert info.equity == 10000.0
        assert info.margin == 0.0
        assert info.free_margin == 10000.0
        assert info.currency == "USD"


# ═══════════════════════════════════════════════════════════════════════
# OPEN ORDER
# ═══════════════════════════════════════════════════════════════════════


class TestDryRunOpenOrder:
    async def test_market_sell_creates_position(self, connector):
        await connector.connect()
        result = await connector.open_order(
            "XAUUSD", OrderType.MARKET_SELL, 0.10, price=4980.0, sl=4986.0, tp=4973.0
        )
        assert result.success is True
        assert result.ticket > 0
        assert result.volume == 0.10

    async def test_market_sell_direction(self, connector):
        await connector.connect()
        result = await connector.open_order("XAUUSD", OrderType.MARKET_SELL, 0.10)
        pos = connector._fake_positions[result.ticket]
        assert pos.direction == "sell"

    async def test_market_buy_creates_position(self, connector):
        await connector.connect()
        result = await connector.open_order(
            "XAUUSD", OrderType.MARKET_BUY, 0.20, price=2140.0, sl=2135.0, tp=2155.0
        )
        assert result.success is True
        assert result.ticket > 0
        pos = connector._fake_positions[result.ticket]
        assert pos.direction == "buy"
        assert pos.symbol == "XAUUSD"
        assert pos.volume == 0.20

    async def test_ticket_increments(self, connector):
        await connector.connect()
        r1 = await connector.open_order("XAUUSD", OrderType.MARKET_BUY, 0.10)
        r2 = await connector.open_order("XAUUSD", OrderType.MARKET_BUY, 0.10)
        assert r2.ticket > r1.ticket

    async def test_position_appears_in_get_positions(self, connector):
        await connector.connect()
        result = await connector.open_order("XAUUSD", OrderType.MARKET_BUY, 0.10)
        positions = await connector.get_positions()
        assert len(positions) == 1
        assert positions[0].ticket == result.ticket

    async def test_open_order_with_comment(self, connector):
        await connector.connect()
        result = await connector.open_order(
            "XAUUSD", OrderType.MARKET_BUY, 0.10, comment="test_order"
        )
        pos = connector._fake_positions[result.ticket]
        assert pos.comment == "test_order"


# ═══════════════════════════════════════════════════════════════════════
# MODIFY POSITION
# ═══════════════════════════════════════════════════════════════════════


class TestDryRunModifyPosition:
    async def test_modify_sl(self, connector):
        await connector.connect()
        result = await connector.open_order(
            "XAUUSD", OrderType.MARKET_SELL, 0.10, sl=4986.0, tp=4973.0
        )
        mod = await connector.modify_position(result.ticket, sl=4984.0)
        assert mod.success is True
        pos = connector._fake_positions[result.ticket]
        assert pos.sl == 4984.0

    async def test_modify_tp(self, connector):
        await connector.connect()
        result = await connector.open_order(
            "XAUUSD", OrderType.MARKET_SELL, 0.10, sl=4986.0, tp=4973.0
        )
        mod = await connector.modify_position(result.ticket, sl=4986.0, tp=4970.0)
        assert mod.success is True
        pos = connector._fake_positions[result.ticket]
        assert pos.tp == 4970.0

    async def test_modify_nonexistent_ticket(self, connector):
        await connector.connect()
        mod = await connector.modify_position(999999, sl=4984.0)
        assert mod.success is False
        assert "not found" in mod.error.lower()


# ═══════════════════════════════════════════════════════════════════════
# CLOSE POSITION
# ═══════════════════════════════════════════════════════════════════════


class TestDryRunClosePosition:
    async def test_full_close_removes_position(self, connector):
        await connector.connect()
        result = await connector.open_order("XAUUSD", OrderType.MARKET_SELL, 0.10)
        close = await connector.close_position(result.ticket)
        assert close.success is True
        assert result.ticket not in connector._fake_positions

    async def test_partial_close_reduces_volume(self, connector):
        await connector.connect()
        result = await connector.open_order("XAUUSD", OrderType.MARKET_SELL, 1.0)
        close = await connector.close_position(result.ticket, volume=0.3)
        assert close.success is True
        pos = connector._fake_positions[result.ticket]
        assert abs(pos.volume - 0.7) < 1e-9  # float comparison

    async def test_close_nonexistent_ticket(self, connector):
        await connector.connect()
        close = await connector.close_position(999999)
        assert close.success is False
        assert "not found" in close.error.lower()

    async def test_close_full_volume_removes(self, connector):
        """Closing with volume >= position volume removes the position entirely."""
        await connector.connect()
        result = await connector.open_order("XAUUSD", OrderType.MARKET_SELL, 0.50)
        close = await connector.close_position(result.ticket, volume=0.50)
        assert close.success is True
        assert result.ticket not in connector._fake_positions


# ═══════════════════════════════════════════════════════════════════════
# PENDING ORDERS
# ═══════════════════════════════════════════════════════════════════════


class TestDryRunPendingOrders:
    async def test_cancel_pending_returns_success(self, connector):
        await connector.connect()
        result = await connector.cancel_pending(12345)
        assert result.success is True

    async def test_get_pending_orders_empty(self, connector):
        await connector.connect()
        orders = await connector.get_pending_orders()
        assert orders == []

    async def test_get_pending_orders_with_symbol(self, connector):
        await connector.connect()
        orders = await connector.get_pending_orders(symbol="XAUUSD")
        assert orders == []


# ═══════════════════════════════════════════════════════════════════════
# GET POSITIONS (filter)
# ═══════════════════════════════════════════════════════════════════════


class TestDryRunGetPositions:
    async def test_get_all_positions(self, connector):
        await connector.connect()
        await connector.open_order("XAUUSD", OrderType.MARKET_BUY, 0.10)
        await connector.open_order("EURUSD", OrderType.MARKET_SELL, 0.20)
        positions = await connector.get_positions()
        assert len(positions) == 2

    async def test_filter_by_symbol(self, connector):
        await connector.connect()
        await connector.open_order("XAUUSD", OrderType.MARKET_BUY, 0.10)
        await connector.open_order("EURUSD", OrderType.MARKET_SELL, 0.20)
        xau_positions = await connector.get_positions(symbol="XAUUSD")
        assert len(xau_positions) == 1
        assert xau_positions[0].symbol == "XAUUSD"

    async def test_filter_returns_empty_when_no_match(self, connector):
        await connector.connect()
        await connector.open_order("XAUUSD", OrderType.MARKET_BUY, 0.10)
        positions = await connector.get_positions(symbol="GBPUSD")
        assert len(positions) == 0


# ═══════════════════════════════════════════════════════════════════════
# CREATE CONNECTOR FACTORY
# ═══════════════════════════════════════════════════════════════════════


class TestCreateConnector:
    def test_dry_run_backend(self):
        c = create_connector("dry_run", "acct", "Server", 111, "pwd")
        assert isinstance(c, DryRunConnector)

    def test_mt5linux_backend(self):
        c = create_connector("mt5linux", "acct", "Server", 111, "pwd")
        assert isinstance(c, MT5LinuxConnector)

    def test_invalid_backend_raises(self):
        with pytest.raises(ValueError, match="Unknown MT5 backend"):
            create_connector("bad_backend", "acct", "Server", 111, "pwd")


# ═══════════════════════════════════════════════════════════════════════
# FAILING CONNECTOR — ERROR SIMULATION
# ═══════════════════════════════════════════════════════════════════════


class TestFailingConnector:
    async def test_ping_failure_sets_disconnected(self):
        c = FailingConnector("test", "Server", 111, "pwd", fail_on={"ping"})
        await c.connect()
        assert c.connected is True
        result = await c.ping()
        assert result is False
        assert c.connected is False

    async def test_get_price_failure_returns_none(self):
        c = FailingConnector("test", "Server", 111, "pwd", fail_on={"get_price"})
        await c.connect()
        result = await c.get_price("XAUUSD")
        assert result is None

    async def test_get_price_success_returns_tuple(self):
        c = FailingConnector("test", "Server", 111, "pwd", fail_on=set())
        await c.connect()
        result = await c.get_price("XAUUSD")
        assert result == (4980.0, 4981.0)

    async def test_open_order_failure(self):
        c = FailingConnector("test", "Server", 111, "pwd", fail_on={"open_order"})
        await c.connect()
        result = await c.open_order("XAUUSD", OrderType.MARKET_BUY, 0.10)
        assert result.success is False
        assert "Simulated failure" in result.error

    async def test_non_failing_operations_work(self):
        """Operations NOT in fail_on should work normally."""
        c = FailingConnector("test", "Server", 111, "pwd", fail_on={"ping"})
        await c.connect()
        result = await c.open_order("XAUUSD", OrderType.MARKET_BUY, 0.10)
        assert result.success is True
