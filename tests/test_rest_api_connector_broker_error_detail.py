"""Regression tests for structured broker-error propagation (audit W3-CONNECTOR).

When the REST server returns a structured error body ({"ok": false,
"error": {"code": ..., "message": ...}}), the connector must surface that
broker reason (e.g. 10016 invalid stops, 10030 unsupported filling) in
OrderResult.error — not swallow it behind a generic "REST API request failed".
Without the real code + message an operator cannot diagnose the failure from
logs or the trade-manager notifier payload.
"""

import httpx

from mt5_connector import OrderType, RestApiConnector


def _make_connector(**overrides) -> RestApiConnector:
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


def _inject_transport(connector: RestApiConnector, handler) -> RestApiConnector:
    transport = httpx.MockTransport(handler)
    connector._http = httpx.AsyncClient(
        transport=transport,
        base_url=connector._base_url,
        timeout=15.0,
        headers={"X-API-Key": connector.api_key},
    )
    return connector


def _error_body_handler(code, message):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": {"code": code, "message": message}})

    return handler


class TestBrokerErrorDetailSurfaced:
    async def test_open_order_surfaces_broker_code_and_message(self):
        conn = _inject_transport(
            _make_connector(),
            _error_body_handler(10016, "Invalid stops"),
        )
        result = await conn.open_order("EURUSD", OrderType.MARKET_BUY, 0.1)

        assert result.success is False
        # The broker code AND message must both be in the error string.
        assert "10016" in result.error
        assert "Invalid stops" in result.error
        assert result.error != "REST API request failed"

    async def test_modify_position_surfaces_broker_detail(self):
        conn = _inject_transport(
            _make_connector(),
            _error_body_handler(10030, "Unsupported filling mode"),
        )
        result = await conn.modify_position(555, sl=1.2345)

        assert result.success is False
        assert result.ticket == 555
        assert "10030" in result.error
        assert "Unsupported filling mode" in result.error

    async def test_close_position_surfaces_broker_detail(self):
        conn = _inject_transport(
            _make_connector(),
            _error_body_handler(10018, "Market closed"),
        )
        result = await conn.close_position(777)

        assert result.success is False
        assert result.ticket == 777
        assert "10018" in result.error
        assert "Market closed" in result.error

    async def test_cancel_pending_surfaces_broker_detail(self):
        conn = _inject_transport(
            _make_connector(),
            _error_body_handler(10013, "Invalid request"),
        )
        result = await conn.cancel_pending(888)

        assert result.success is False
        assert result.ticket == 888
        assert "10013" in result.error
        assert "Invalid request" in result.error

    async def test_generic_fallback_when_no_structured_body(self):
        """A transport-level failure (no REST error body) keeps the generic string."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        conn = _inject_transport(_make_connector(), handler)
        result = await conn.modify_position(123, sl=1.0)

        assert result.success is False
        assert result.error == "REST API request failed"
