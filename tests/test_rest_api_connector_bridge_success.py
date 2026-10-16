"""RestApiConnector must read the PRODUCTION bridge's response shapes.

mt5-rest-server returns ok=true with NO "success" key for PUT /position,
DELETE /position and DELETE /pending-order (failures come back as ok=false).
The connector used to require a truthy data["success"], so every successful
modify / close / cancel against the real bridge was reported as a failure
("Unknown error"). The dev simulator does send "success": true, which hid it.
"""

import httpx
import pytest

from mt5_connector import RestApiConnector


def _connector(handler) -> RestApiConnector:
    c = RestApiConnector(
        account_name="test-acct", server="TestServer", login=12345,
        password="secret", host="localhost", port=8001, api_key="k",
        use_tls=False,
    )
    c._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=c._base_url,
    )
    return c


def _ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "data": data, "error": None})


def _err(code: str, message: str, status: int = 400) -> httpx.Response:
    return httpx.Response(
        status, json={"detail": {"ok": False, "data": None,
                                 "error": {"code": code, "message": message}}},
    )


async def test_modify_success_with_production_bridge_payload():
    # mt5-rest-server/server.py modify_position return shape.
    c = _connector(lambda r: _ok({"ticket": 101, "sl": 1990.0, "tp": 2020.0}))
    result = await c.modify_position(101, sl=1990.0, tp=2020.0)
    assert result.success is True
    assert result.ticket == 101


async def test_close_success_reads_closed_volume():
    # mt5-rest-server/server.py close_position return shape.
    c = _connector(lambda r: _ok({"ticket": 101, "closed_volume": 0.05, "price": 2001.5}))
    result = await c.close_position(101, volume=0.05)
    assert result.success is True
    assert result.volume == pytest.approx(0.05)
    assert result.price == pytest.approx(2001.5)


async def test_cancel_success_with_production_bridge_payload():
    c = _connector(lambda r: _ok({"ticket": 202, "cancelled": True}))
    result = await c.cancel_pending(202)
    assert result.success is True


async def test_simulator_payload_still_supported():
    # mt5-simulator sends "success": true and "volume" on close.
    c = _connector(lambda r: _ok({"success": True, "ticket": 101, "volume": 0.1, "price": 2000.0}))
    result = await c.close_position(101)
    assert result.success is True
    assert result.volume == pytest.approx(0.1)


async def test_explicit_success_false_is_failure():
    c = _connector(lambda r: _ok({"success": False, "ticket": 101, "error": "rejected"}))
    result = await c.modify_position(101, sl=1990.0)
    assert result.success is False
    assert result.error == "rejected"


async def test_bridge_error_is_failure_with_broker_reason():
    c = _connector(lambda r: _err("MODIFY_FAILED", "retcode=10016 Invalid stops"))
    result = await c.modify_position(101, sl=1990.0)
    assert result.success is False
    assert "10016" in result.error
