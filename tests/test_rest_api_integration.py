"""Integration tests: RestApiConnector wired to the in-process MT5 simulator.

Uses httpx.ASGITransport to connect RestApiConnector directly to the
simulator's ASGI app — no network, no Docker, fast and deterministic.

Covers:
1. Full flow: connect -> open market buy -> get positions -> close -> verify P&L
2. Limit order flow: open limit -> get pending orders -> cancel
3. Modify SL/TP: open position -> modify -> verify changed
4. Account info reflects open position equity
5. Partial close: open 0.10 lots -> close 0.05 -> verify remaining
"""

import os
import sys

import httpx
import pytest

# Ensure the simulator package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mt5-simulator"))

from mt5_connector import OrderType, RestApiConnector

API_KEY = "integration-test-key"


@pytest.fixture(autouse=True)
def _env_setup(monkeypatch):
    """Set environment variables before each test and re-initialise simulator state."""
    monkeypatch.setenv("MT5_API_KEY", API_KEY)
    monkeypatch.setenv("SIMULATOR_PRICE_MODE", "static")
    monkeypatch.setenv("SIMULATOR_BALANCE", "10000.0")
    from simulator import _init_state
    _init_state()


@pytest.fixture
def connector():
    from simulator import app as simulator_app

    conn = RestApiConnector(
        account_name="test",
        server="TestServer",
        login=12345,
        password="testpass",
        host="localhost",
        port=8001,
        api_key=API_KEY,
        use_tls=False,
    )
    # Replace the HTTP client with one that talks directly to the simulator ASGI app
    transport = httpx.ASGITransport(app=simulator_app)
    conn._http = httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": API_KEY},
        timeout=15.0,
    )
    return conn


# ═══════════════════════════════════════════════════════════════════════
# 1. Full flow: connect -> buy -> positions -> close -> P&L
# ═══════════════════════════════════════════════════════════════════════


async def test_full_market_buy_flow(connector):
    # Connect
    connected = await connector.connect()
    assert connected is True
    assert connector.connected is True

    # Open a market buy — simulator fills at ask = 2345.87
    result = await connector.open_order(
        "XAUUSD", OrderType.MARKET_BUY, 0.10,
        sl=2335.0, tp=2355.0, comment="integration-test",
    )
    assert result.success is True
    assert result.ticket > 0
    assert result.price == 2345.87
    assert result.volume == 0.10

    # Get positions — should have exactly one
    positions = await connector.get_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.ticket == result.ticket
    assert pos.symbol == "XAUUSD"
    assert pos.direction == "buy"
    assert pos.volume == 0.10
    assert pos.open_price == 2345.87
    assert pos.sl == 2335.0
    assert pos.tp == 2355.0

    # Close position — simulator closes at bid = 2345.67
    # P&L = (2345.67 - 2345.87) * 0.10 * 100 = -2.0
    close_result = await connector.close_position(result.ticket)
    assert close_result.success is True
    assert close_result.price == 2345.67

    # Verify no positions remaining
    positions = await connector.get_positions()
    assert len(positions) == 0

    # Verify balance reflects P&L
    info = await connector.get_account_info()
    assert info is not None
    assert info.balance == pytest.approx(10000.0 - 2.0, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════
# 2. Limit order flow: open limit -> pending orders -> cancel
# ═══════════════════════════════════════════════════════════════════════


async def test_limit_order_flow(connector):
    await connector.connect()

    # Place a buy limit order
    result = await connector.open_order(
        "XAUUSD", OrderType.BUY_LIMIT, 0.10,
        price=2330.0, sl=2325.0, tp=2345.0,
    )
    assert result.success is True
    ticket = result.ticket

    # Verify pending orders list
    pending = await connector.get_pending_orders()
    assert len(pending) == 1
    assert pending[0]["ticket"] == ticket
    assert pending[0]["type"] == "buy_limit"
    assert pending[0]["price"] == 2330.0

    # No active positions (limit not filled)
    positions = await connector.get_positions()
    assert len(positions) == 0

    # Cancel the pending order
    cancel_result = await connector.cancel_pending(ticket)
    assert cancel_result.success is True

    # Verify pending orders list is now empty
    pending = await connector.get_pending_orders()
    assert len(pending) == 0


# ═══════════════════════════════════════════════════════════════════════
# 3. Modify SL/TP: open -> modify -> verify
# ═══════════════════════════════════════════════════════════════════════


async def test_modify_sl_tp(connector):
    await connector.connect()

    result = await connector.open_order(
        "XAUUSD", OrderType.MARKET_BUY, 0.10,
        sl=2335.0, tp=2355.0,
    )
    assert result.success is True
    ticket = result.ticket

    # Modify SL and TP
    mod = await connector.modify_position(ticket, sl=2338.0, tp=2360.0)
    assert mod.success is True

    # Verify changes
    positions = await connector.get_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.sl == 2338.0
    assert pos.tp == 2360.0


# ═══════════════════════════════════════════════════════════════════════
# 4. Account info reflects open position equity
# ═══════════════════════════════════════════════════════════════════════


async def test_account_info_with_open_position(connector):
    await connector.connect()

    # Check initial state
    info = await connector.get_account_info()
    assert info is not None
    assert info.balance == 10000.0
    assert info.equity == 10000.0

    # Open a buy at ask = 2345.87
    await connector.open_order("XAUUSD", OrderType.MARKET_BUY, 0.10)

    # Equity should reflect unrealised P&L
    # P&L = (bid - ask) * volume * contract_size = (2345.67 - 2345.87) * 0.1 * 100 = -2.0
    info = await connector.get_account_info()
    assert info is not None
    assert info.balance == 10000.0  # unchanged — position still open
    assert info.equity == pytest.approx(10000.0 - 2.0, abs=0.01)
    assert info.margin > 0
    assert info.free_margin == pytest.approx(info.equity - info.margin, abs=0.01)
    assert info.currency == "USD"


# ═══════════════════════════════════════════════════════════════════════
# 5. Partial close: open 0.10 -> close 0.05 -> verify remaining
# ═══════════════════════════════════════════════════════════════════════


async def test_partial_close(connector):
    await connector.connect()

    result = await connector.open_order(
        "XAUUSD", OrderType.MARKET_BUY, 0.10,
        sl=2335.0, tp=2355.0,
    )
    assert result.success is True
    ticket = result.ticket

    # Partial close — close 0.05 of 0.10
    close_result = await connector.close_position(ticket, volume=0.05)
    assert close_result.success is True
    assert close_result.volume == 0.05

    # Remaining position should have 0.05 lots
    positions = await connector.get_positions()
    assert len(positions) == 1
    assert positions[0].volume == pytest.approx(0.05)
    assert positions[0].ticket == ticket
