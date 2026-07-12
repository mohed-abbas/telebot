"""Regression tests for the ReadTimeout double-fill hazard (audit §4.1, cluster E).

A ReadTimeout means the request WAS sent but the response never arrived — the
server may already have processed it. Retrying a non-idempotent call such as
POST /api/v1/order would submit a SECOND identical market order (double fill).

These tests assert:
- POST is attempted EXACTLY ONCE on ReadTimeout (fail fast, no resubmit).
- GET is still retried up to 3 times on ReadTimeout (idempotent, safe).
- ConnectError/ConnectTimeout still retry any method (request never left client).
"""

import httpx
import pytest

from mt5_connector import RestApiConnector


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


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Skip the 1s backoff so GET retries don't slow the suite."""
    async def _fast_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr("mt5_connector.asyncio.sleep", _fast_sleep)


class TestReadTimeoutIdempotency:
    async def test_post_readtimeout_attempted_exactly_once(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ReadTimeout("Response timed out")

        conn = _inject_transport(_make_connector(), handler)
        result = await conn._request("POST", "/api/v1/order", json={"symbol": "EURUSD"})

        assert result is None
        # The order POST must NEVER be auto-resubmitted after a ReadTimeout.
        assert call_count == 1

    async def test_get_readtimeout_retried_three_times(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ReadTimeout("Response timed out")

        conn = _inject_transport(_make_connector(), handler)
        result = await conn._request("GET", "/api/v1/ping")

        assert result is None
        # GET is idempotent — full retry budget is exhausted.
        assert call_count == 3

    async def test_post_connecterror_still_retried(self):
        """ConnectError provably never left the client — safe to retry any method."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("Connection refused")

        conn = _inject_transport(_make_connector(), handler)
        result = await conn._request("POST", "/api/v1/order", json={"symbol": "EURUSD"})

        assert result is None
        assert call_count == 3
