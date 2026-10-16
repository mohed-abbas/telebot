"""A failed request must not leave a healthy account disconnected forever.

A non-GET ReadTimeout (and a few other request failures) set
connector._connected = False. Only connect() set it back, and the heartbeat
only reconnected when ping() failed — which it doesn't while the bridge is up.
The heartbeat now also reconnects + resyncs an account whose bridge answers
the ping but whose session is disconnected (timed-out request, failed login).
"""

import asyncio
import types

import httpx

from executor import (
    RECONNECT_REASON_PING_FAILED, RECONNECT_REASON_SESSION_LOST, Executor,
)
from models import GlobalConfig
from mt5_connector import RestApiConnector


async def test_post_readtimeout_marks_session_disconnected():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    c = RestApiConnector(
        account_name="acct", server="S", login=1, password="",
        host="localhost", port=8001, api_key="k", use_tls=False,
    )
    c._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=c._base_url,
    )
    c._connected = True
    result = await c.modify_position(1, sl=1990.0)

    assert result.success is False
    assert c.connected is False


class _FakeConn:
    def __init__(self, *, alive: bool, connected: bool):
        self.password = ""
        self.password_env = "TEST_HEARTBEAT_PASS"
        self._alive = alive
        self.connected = connected

    async def ping(self):
        return self._alive


def _executor(conn):
    tm = types.SimpleNamespace(connectors={"acct": conn}, accounts={})
    ex = Executor(trade_manager=tm, global_config=GlobalConfig(), notifier=None)
    calls = []

    async def fake_reconnect(acct_name, connector, *, reason):
        calls.append((acct_name, reason))

    ex._reconnect_account = fake_reconnect
    return ex, calls


async def _run_tick(ex):
    await ex._heartbeat_tick()
    # Let the reconnect task the tick scheduled run.
    await asyncio.sleep(0)


async def test_heartbeat_reconnects_alive_bridge_with_lost_session(monkeypatch):
    monkeypatch.setenv("TEST_HEARTBEAT_PASS", "pw")
    ex, calls = _executor(_FakeConn(alive=True, connected=False))
    await _run_tick(ex)
    assert len(calls) == 1
    assert calls[0][1] == RECONNECT_REASON_SESSION_LOST


async def test_heartbeat_leaves_healthy_account_alone(monkeypatch):
    monkeypatch.setenv("TEST_HEARTBEAT_PASS", "pw")
    ex, calls = _executor(_FakeConn(alive=True, connected=True))
    await _run_tick(ex)
    assert calls == []


async def test_heartbeat_still_reconnects_when_ping_fails(monkeypatch):
    monkeypatch.setenv("TEST_HEARTBEAT_PASS", "pw")
    ex, calls = _executor(_FakeConn(alive=False, connected=True))
    await _run_tick(ex)
    assert len(calls) == 1
    assert calls[0][1] == RECONNECT_REASON_PING_FAILED


async def test_heartbeat_skips_accounts_without_credentials(monkeypatch):
    monkeypatch.delenv("TEST_HEARTBEAT_PASS", raising=False)
    ex, calls = _executor(_FakeConn(alive=True, connected=False))
    await _run_tick(ex)
    assert calls == []
