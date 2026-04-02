"""Unit tests for RestApiConnector — mock HTTP responses via httpx.MockTransport.

Covers:
- connect() sends correct JSON and sets connected on success
- connect() returns False on server error
- ping() returns True when alive
- get_price() returns bid/ask tuple
- get_price() returns None on 404 (unknown symbol)
- get_account_info() returns AccountInfo
- get_positions() returns list of Position objects
- get_positions() with symbol filter passes query param
- open_order() sends order and returns OrderResult
- modify_position() sends SL/TP update
- close_position() full close
- close_position() partial close sends volume
- cancel_pending() cancels order
- get_pending_orders() returns list of dicts
- Retry on connection error (first request fails, second succeeds)
- Sets _connected = False on 503 response
"""

import json

import httpx
import pytest

from mt5_connector import (
    AccountInfo,
    OrderResult,
    OrderType,
    Position,
    RestApiConnector,
)


def _make_connector(**overrides) -> RestApiConnector:
    """Create a RestApiConnector with sensible test defaults."""
    defaults = dict(
        account_name="test-acct",
        server="TestServer",
        login=12345,
        password="secret",
        host="localhost",
        port=8001,
        api_key="test-key",
        use_tls=False,
    )
    defaults.update(overrides)
    return RestApiConnector(**defaults)


def _ok_response(data: dict, status: int = 200) -> httpx.Response:
    """Build a successful JSON response."""
    return httpx.Response(
        status,
        json={"ok": True, "data": data, "error": None},
    )


def _error_response(code: str, message: str, status: int = 400) -> httpx.Response:
    return httpx.Response(
        status,
        json={"ok": False, "data": None, "error": {"code": code, "message": message}},
    )


def _inject_transport(connector: RestApiConnector, handler) -> RestApiConnector:
    """Replace the connector's HTTP client with a mock transport."""
    transport = httpx.MockTransport(handler)
    connector._http = httpx.AsyncClient(
        transport=transport,
        base_url=connector._base_url,
        timeout=15.0,
        headers={"X-API-Key": connector.api_key},
    )
    return connector


# ═══════════════════════════════════════════════════════════════════════
# 1. CONNECT — success
# ═══════════════════════════════════════════════════════════════════════


class TestConnect:
    async def test_connect_sends_correct_json_and_sets_connected(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            captured["path"] = request.url.path
            return _ok_response({"connected": True})

        conn = _inject_transport(_make_connector(), handler)
        result = await conn.connect()

        assert result is True
        assert conn.connected is True
        assert captured["path"] == "/api/v1/connect"
        assert captured["body"]["login"] == 12345
        assert captured["body"]["password"] == "secret"
        assert captured["body"]["server"] == "TestServer"

    async def test_connect_clears_password_on_success(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_response({"connected": True})

        conn = _inject_transport(_make_connector(), handler)
        assert conn.password == "secret"
        await conn.connect()
        assert conn.password == ""

    # ───────────────────────────────────────────────────────────────
    # 2. CONNECT — server error
    # ───────────────────────────────────────────────────────────────

    async def test_connect_returns_false_on_server_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _error_response("INTERNAL", "boom", status=500)

        conn = _inject_transport(_make_connector(), handler)
        result = await conn.connect()

        assert result is False
        assert conn.connected is False


# ═══════════════════════════════════════════════════════════════════════
# 3. PING
# ═══════════════════════════════════════════════════════════════════════


class TestPing:
    async def test_ping_returns_true_when_alive(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_response({"alive": True, "terminal_connected": True})

        conn = _inject_transport(_make_connector(), handler)
        assert await conn.ping() is True

    async def test_ping_returns_false_when_not_alive(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_response({"alive": False})

        conn = _inject_transport(_make_connector(), handler)
        assert await conn.ping() is False


# ═══════════════════════════════════════════════════════════════════════
# 4 & 5. GET PRICE
# ═══════════════════════════════════════════════════════════════════════


class TestGetPrice:
    async def test_get_price_returns_bid_ask_tuple(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_response({"symbol": "XAUUSD", "bid": 2345.67, "ask": 2345.87})

        conn = _inject_transport(_make_connector(), handler)
        result = await conn.get_price("XAUUSD")
        assert result == (2345.67, 2345.87)

    async def test_get_price_returns_none_on_404(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _error_response("SYMBOL_NOT_FOUND", "Not found", status=404)

        conn = _inject_transport(_make_connector(), handler)
        result = await conn.get_price("UNKNOWN")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════
# 6. GET ACCOUNT INFO
# ═══════════════════════════════════════════════════════════════════════


class TestGetAccountInfo:
    async def test_returns_account_info(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_response({
                "balance": 10000.0,
                "equity": 9998.0,
                "margin": 50.0,
                "free_margin": 9948.0,
                "currency": "USD",
            })

        conn = _inject_transport(_make_connector(), handler)
        info = await conn.get_account_info()

        assert isinstance(info, AccountInfo)
        assert info.balance == 10000.0
        assert info.equity == 9998.0
        assert info.margin == 50.0
        assert info.free_margin == 9948.0
        assert info.currency == "USD"


# ═══════════════════════════════════════════════════════════════════════
# 7 & 8. GET POSITIONS
# ═══════════════════════════════════════════════════════════════════════


class TestGetPositions:
    async def test_returns_list_of_positions(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_response({"positions": [
                {
                    "ticket": 100001,
                    "symbol": "XAUUSD",
                    "direction": "buy",
                    "volume": 0.10,
                    "open_price": 2345.87,
                    "sl": 2335.0,
                    "tp": 2355.0,
                    "profit": -2.0,
                    "comment": "telebot",
                },
            ]})

        conn = _inject_transport(_make_connector(), handler)
        positions = await conn.get_positions()

        assert len(positions) == 1
        pos = positions[0]
        assert isinstance(pos, Position)
        assert pos.ticket == 100001
        assert pos.symbol == "XAUUSD"
        assert pos.direction == "buy"
        assert pos.volume == 0.10
        assert pos.profit == -2.0
        assert pos.comment == "telebot"

    async def test_symbol_filter_passes_query_param(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return _ok_response({"positions": []})

        conn = _inject_transport(_make_connector(), handler)
        await conn.get_positions(symbol="EURUSD")

        assert captured["params"]["symbol"] == "EURUSD"

    async def test_returns_empty_list_on_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _error_response("INTERNAL", "boom", status=500)

        conn = _inject_transport(_make_connector(), handler)
        positions = await conn.get_positions()
        assert positions == []


# ═══════════════════════════════════════════════════════════════════════
# 9. OPEN ORDER
# ═══════════════════════════════════════════════════════════════════════


class TestOpenOrder:
    async def test_sends_order_and_returns_result(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return _ok_response({
                "success": True,
                "ticket": 100001,
                "price": 2345.87,
                "volume": 0.10,
                "error": "",
            })

        conn = _inject_transport(_make_connector(), handler)
        result = await conn.open_order(
            "XAUUSD", OrderType.MARKET_BUY, 0.10,
            price=0.0, sl=2335.0, tp=2355.0, comment="telebot",
        )

        assert isinstance(result, OrderResult)
        assert result.success is True
        assert result.ticket == 100001
        assert result.price == 2345.87
        assert result.volume == 0.10

        assert captured["body"]["symbol"] == "XAUUSD"
        assert captured["body"]["order_type"] == "market_buy"
        assert captured["body"]["volume"] == 0.10
        assert captured["body"]["sl"] == 2335.0
        assert captured["body"]["tp"] == 2355.0
        assert captured["body"]["comment"] == "telebot"

    async def test_open_order_failure_returns_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _error_response("ORDER_REJECTED", "Volume too large")

        conn = _inject_transport(_make_connector(), handler)
        result = await conn.open_order("XAUUSD", OrderType.MARKET_BUY, 999.0)

        assert result.success is False
        assert "REST API request failed" in result.error


# ═══════════════════════════════════════════════════════════════════════
# 10. MODIFY POSITION
# ═══════════════════════════════════════════════════════════════════════


class TestModifyPosition:
    async def test_sends_sl_tp_update(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            captured["path"] = request.url.path
            return _ok_response({"success": True, "ticket": 100001, "error": ""})

        conn = _inject_transport(_make_connector(), handler)
        result = await conn.modify_position(100001, sl=2338.0, tp=2355.0)

        assert result.success is True
        assert result.ticket == 100001
        assert captured["path"] == "/api/v1/position/100001"
        assert captured["body"]["sl"] == 2338.0
        assert captured["body"]["tp"] == 2355.0


# ═══════════════════════════════════════════════════════════════════════
# 11 & 12. CLOSE POSITION
# ═══════════════════════════════════════════════════════════════════════


class TestClosePosition:
    async def test_full_close(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_response({
                "success": True,
                "ticket": 100001,
                "price": 2345.67,
                "volume": 0.10,
                "error": "",
            })

        conn = _inject_transport(_make_connector(), handler)
        result = await conn.close_position(100001)

        assert result.success is True
        assert result.ticket == 100001
        assert result.price == 2345.67
        assert result.volume == 0.10

    async def test_partial_close_sends_volume(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return _ok_response({
                "success": True,
                "ticket": 100001,
                "price": 2345.67,
                "volume": 0.05,
                "error": "",
            })

        conn = _inject_transport(_make_connector(), handler)
        result = await conn.close_position(100001, volume=0.05)

        assert result.success is True
        assert result.volume == 0.05
        assert captured["body"]["volume"] == 0.05


# ═══════════════════════════════════════════════════════════════════════
# 13. CANCEL PENDING
# ═══════════════════════════════════════════════════════════════════════


class TestCancelPending:
    async def test_cancel_pending_order(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/pending-order/200001"
            return _ok_response({"success": True, "ticket": 200001, "error": ""})

        conn = _inject_transport(_make_connector(), handler)
        result = await conn.cancel_pending(200001)

        assert result.success is True
        assert result.ticket == 200001


# ═══════════════════════════════════════════════════════════════════════
# 14. GET PENDING ORDERS
# ═══════════════════════════════════════════════════════════════════════


class TestGetPendingOrders:
    async def test_returns_list_of_dicts(self):
        orders = [
            {"ticket": 200001, "symbol": "XAUUSD", "type": "buy_limit",
             "volume": 0.10, "price": 2330.0, "sl": 2325.0, "tp": 2345.0},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_response({"orders": orders})

        conn = _inject_transport(_make_connector(), handler)
        result = await conn.get_pending_orders()

        assert len(result) == 1
        assert result[0]["ticket"] == 200001
        assert result[0]["type"] == "buy_limit"

    async def test_symbol_filter_passes_query_param(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return _ok_response({"orders": []})

        conn = _inject_transport(_make_connector(), handler)
        await conn.get_pending_orders(symbol="XAUUSD")

        assert captured["params"]["symbol"] == "XAUUSD"


# ═══════════════════════════════════════════════════════════════════════
# 15. RETRY ON CONNECTION ERROR
# ═══════════════════════════════════════════════════════════════════════


class TestRetry:
    async def test_retries_on_connect_error_then_succeeds(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("Connection refused")
            return _ok_response({"alive": True})

        conn = _inject_transport(_make_connector(), handler)
        result = await conn.ping()

        assert result is True
        assert call_count == 2  # first attempt failed, second succeeded

    async def test_gives_up_after_three_attempts(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("Connection refused")

        conn = _inject_transport(_make_connector(), handler)
        conn._connected = True  # start connected to verify it gets set to False
        result = await conn.ping()

        assert result is False
        assert call_count == 3
        assert conn.connected is False


# ═══════════════════════════════════════════════════════════════════════
# 16. 503 RESPONSE SETS DISCONNECTED
# ═══════════════════════════════════════════════════════════════════════


class TestServiceUnavailable:
    async def test_503_sets_connected_false(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                503,
                json={"ok": False, "data": None, "error": {"code": "NOT_CONNECTED", "message": "MT5 not connected"}},
            )

        conn = _inject_transport(_make_connector(), handler)
        conn._connected = True

        result = await conn.ping()

        assert result is False
        assert conn.connected is False
