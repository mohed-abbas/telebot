"""Tests for the MT5 simulator REST API."""

import os
import sys

import pytest
import httpx

# Ensure the simulator package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mt5-simulator"))

API_KEY = "test-key"
HEADERS = {"X-API-Key": API_KEY}
PREFIX = "/api/v1"


@pytest.fixture(autouse=True)
def _env_setup(monkeypatch):
    """Set environment variables before each test and re-initialise state."""
    monkeypatch.setenv("MT5_API_KEY", API_KEY)
    monkeypatch.setenv("SIMULATOR_PRICE_MODE", "static")
    monkeypatch.setenv("SIMULATOR_BALANCE", "10000.0")
    # Re-initialise the global state so tests are isolated
    from simulator import _init_state
    _init_state()


@pytest.fixture
def client():
    from simulator import app
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ------------------------------------------------------------------
# 1. Ping
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ping_disconnected(client):
    resp = await client.get(f"{PREFIX}/ping", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["alive"] is True
    assert body["data"]["terminal_connected"] is False


@pytest.mark.asyncio
async def test_ping_connected(client):
    await client.post(
        f"{PREFIX}/connect",
        headers=HEADERS,
        json={"login": 123, "password": "pw", "server": "S"},
    )
    resp = await client.get(f"{PREFIX}/ping", headers=HEADERS)
    assert resp.json()["data"]["terminal_connected"] is True


# ------------------------------------------------------------------
# 2. Connect
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_succeeds(client):
    resp = await client.post(
        f"{PREFIX}/connect",
        headers=HEADERS,
        json={"login": 12345678, "password": "secret", "server": "BrokerServer"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["connected"] is True


# ------------------------------------------------------------------
# 3 & 4. Price endpoints
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_price_known_symbol(client):
    resp = await client.get(f"{PREFIX}/price/XAUUSD", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["symbol"] == "XAUUSD"
    assert data["bid"] == 2345.67
    assert data["ask"] == 2345.87


@pytest.mark.asyncio
async def test_get_price_unknown_symbol(client):
    resp = await client.get(f"{PREFIX}/price/UNKNOWN", headers=HEADERS)
    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "SYMBOL_NOT_FOUND"


# ------------------------------------------------------------------
# 5 & 6. Market orders
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_open_market_buy(client):
    resp = await client.post(
        f"{PREFIX}/order",
        headers=HEADERS,
        json={
            "symbol": "XAUUSD",
            "order_type": "market_buy",
            "volume": 0.10,
            "sl": 2335.00,
            "tp": 2350.00,
            "comment": "telebot",
            "magic": 202603,
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["success"] is True
    assert data["price"] == 2345.87  # filled at ask
    assert data["volume"] == 0.10
    assert data["ticket"] > 100000


@pytest.mark.asyncio
async def test_open_market_sell(client):
    resp = await client.post(
        f"{PREFIX}/order",
        headers=HEADERS,
        json={
            "symbol": "XAUUSD",
            "order_type": "market_sell",
            "volume": 0.20,
        },
    )
    data = resp.json()["data"]
    assert data["price"] == 2345.67  # filled at bid


# ------------------------------------------------------------------
# 7. Close position (full) – P&L + balance update
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_position_updates_balance(client):
    # Open a buy at ask = 2345.87
    resp = await client.post(
        f"{PREFIX}/order",
        headers=HEADERS,
        json={"symbol": "XAUUSD", "order_type": "market_buy", "volume": 0.10},
    )
    ticket = resp.json()["data"]["ticket"]

    # Close at bid = 2345.67  =>  P&L = (2345.67 - 2345.87) * 0.10 * 100 = -2.00
    resp = await client.request(
        "DELETE",
        f"{PREFIX}/position/{ticket}",
        headers=HEADERS,
        json={},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["success"] is True
    assert data["price"] == 2345.67

    # Balance should reflect P&L
    resp = await client.get(f"{PREFIX}/account", headers=HEADERS)
    balance = resp.json()["data"]["balance"]
    assert balance == pytest.approx(10000.0 - 2.0, abs=0.01)


# ------------------------------------------------------------------
# 8. Partial close
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_partial_close(client):
    resp = await client.post(
        f"{PREFIX}/order",
        headers=HEADERS,
        json={"symbol": "XAUUSD", "order_type": "market_buy", "volume": 0.10},
    )
    ticket = resp.json()["data"]["ticket"]

    # Partially close 0.05 lots
    resp = await client.request(
        "DELETE",
        f"{PREFIX}/position/{ticket}",
        headers=HEADERS,
        json={"volume": 0.05},
    )
    data = resp.json()["data"]
    assert data["volume"] == 0.05  # closed volume

    # Position should still exist with reduced volume
    resp = await client.get(f"{PREFIX}/positions", headers=HEADERS)
    positions = resp.json()["data"]["positions"]
    assert len(positions) == 1
    assert positions[0]["volume"] == pytest.approx(0.05)


# ------------------------------------------------------------------
# 9. Modify SL/TP
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_modify_sl_tp(client):
    resp = await client.post(
        f"{PREFIX}/order",
        headers=HEADERS,
        json={"symbol": "XAUUSD", "order_type": "market_buy", "volume": 0.10},
    )
    ticket = resp.json()["data"]["ticket"]

    resp = await client.put(
        f"{PREFIX}/position/{ticket}",
        headers=HEADERS,
        json={"sl": 2338.00, "tp": 2355.00},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["success"] is True

    # Verify changes
    resp = await client.get(f"{PREFIX}/positions", headers=HEADERS)
    pos = resp.json()["data"]["positions"][0]
    assert pos["sl"] == 2338.00
    assert pos["tp"] == 2355.00


# ------------------------------------------------------------------
# 10. Cancel pending order
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_pending_order(client):
    # Create a pending order
    resp = await client.post(
        f"{PREFIX}/order",
        headers=HEADERS,
        json={
            "symbol": "XAUUSD",
            "order_type": "buy_limit",
            "volume": 0.10,
            "price": 2330.00,
            "sl": 2325.00,
            "tp": 2345.00,
        },
    )
    ticket = resp.json()["data"]["ticket"]

    # Verify it exists
    resp = await client.get(f"{PREFIX}/pending-orders", headers=HEADERS)
    assert len(resp.json()["data"]["orders"]) == 1

    # Cancel it
    resp = await client.delete(f"{PREFIX}/pending-order/{ticket}", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["data"]["success"] is True

    # Verify it's gone
    resp = await client.get(f"{PREFIX}/pending-orders", headers=HEADERS)
    assert len(resp.json()["data"]["orders"]) == 0


# ------------------------------------------------------------------
# 11. Account info reflects equity with open positions
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_account_equity_with_positions(client):
    # Open a buy at ask = 2345.87
    await client.post(
        f"{PREFIX}/order",
        headers=HEADERS,
        json={"symbol": "XAUUSD", "order_type": "market_buy", "volume": 0.10},
    )
    resp = await client.get(f"{PREFIX}/account", headers=HEADERS)
    data = resp.json()["data"]

    # P&L = (bid - open) * volume * contract_size = (2345.67 - 2345.87) * 0.1 * 100 = -2.0
    assert data["balance"] == 10000.0
    assert data["equity"] == pytest.approx(10000.0 - 2.0, abs=0.01)
    assert data["margin"] > 0
    assert data["free_margin"] == pytest.approx(data["equity"] - data["margin"], abs=0.01)


# ------------------------------------------------------------------
# 12 & 13. Auth
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auth_missing_key(client):
    resp = await client.get(f"{PREFIX}/ping")
    assert resp.status_code == 401
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_auth_wrong_key(client):
    resp = await client.get(f"{PREFIX}/ping", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"


# ------------------------------------------------------------------
# Extra: reject volume > 100
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_order_rejected_volume_too_large(client):
    resp = await client.post(
        f"{PREFIX}/order",
        headers=HEADERS,
        json={"symbol": "XAUUSD", "order_type": "market_buy", "volume": 101},
    )
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "ORDER_REJECTED"


# ------------------------------------------------------------------
# Extra: modify / close non-existent position
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_modify_nonexistent_position(client):
    resp = await client.put(
        f"{PREFIX}/position/999999",
        headers=HEADERS,
        json={"sl": 1.0},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "POSITION_NOT_FOUND"


@pytest.mark.asyncio
async def test_close_nonexistent_position(client):
    resp = await client.request(
        "DELETE",
        f"{PREFIX}/position/999999",
        headers=HEADERS,
        json={},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "POSITION_NOT_FOUND"
