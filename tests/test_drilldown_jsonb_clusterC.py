"""Cluster C regression tests — §3.1 JSONB decode + catch-all error envelope.

Covers two HIGH findings:
  1. db._init_connection must register a JSONB codec so JSONB columns decode to
     Python objects (dict/list), not raw JSON strings. Without it,
     get_position_drilldown does `settings.get(...)` on a str -> AttributeError
     -> unhandled 500 on every staged-trade drilldown.
  2. api.errors must install a catch-all Exception handler so an unexpected error
     returns the standard enveloped 500 on /api/v2, not a bare un-enveloped 500,
     while the specific HTTPException/validation handlers still win.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import db
from api.errors import register_error_handlers


# ── Finding §3.1: JSONB codec registration ──────────────────────────────


class _FakeConn:
    """Records set_type_codec calls made by db._init_connection."""

    def __init__(self) -> None:
        self.codecs: list[dict] = []

    async def set_type_codec(self, name, *, encoder, decoder, schema):
        self.codecs.append(
            {"name": name, "encoder": encoder, "decoder": decoder, "schema": schema}
        )


@pytest.mark.asyncio
async def test_init_connection_registers_jsonb_codec():
    conn = _FakeConn()
    await db._init_connection(conn)

    jsonb = [c for c in conn.codecs if c["name"] == "jsonb"]
    assert jsonb, "expected a 'jsonb' type codec to be registered on each connection"
    codec = jsonb[0]
    assert codec["schema"] == "pg_catalog"
    # The decoder must turn JSON text into a Python object (the whole point of §3.1):
    # a raw string would break `snapshot_settings.get(...)` in get_position_drilldown.
    decoded = codec["decoder"]('{"default_sl_pips": 20}')
    assert decoded == {"default_sl_pips": 20}
    assert codec["encoder"]({"a": 1}) == json.dumps({"a": 1})


# ── Related HIGH: catch-all error envelope ───────────────────────────────


@pytest.fixture()
def _client() -> TestClient:
    app = FastAPI()

    @app.get("/api/v2/boom")
    async def boom():
        raise RuntimeError("simulated drilldown crash")

    @app.get("/api/v2/known")
    async def known():
        raise HTTPException(status_code=404, detail="nope")

    @app.get("/legacy/boom")
    async def legacy_boom():
        raise RuntimeError("html-route crash")

    register_error_handlers(app)
    # raise_server_exceptions=False so the handler runs instead of TestClient re-raising.
    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_exception_returns_enveloped_500(_client: TestClient):
    resp = _client.get("/api/v2/boom")
    assert resp.status_code == 500
    body = resp.json()
    # Standard envelope shape {"error": {"code": ..., "message": ...}}.
    assert "error" in body, f"expected enveloped error, got {body!r}"
    assert body["error"]["code"] == "error"
    assert isinstance(body["error"]["message"], str)
    # Never leak the raw exception text.
    assert "simulated drilldown crash" not in json.dumps(body)


def test_specific_http_handler_still_wins_over_catch_all(_client: TestClient):
    resp = _client.get("/api/v2/known")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == "nope"


def test_legacy_route_not_enveloped(_client: TestClient):
    resp = _client.get("/legacy/boom")
    assert resp.status_code == 500
    # Non-/api/v2 paths keep the bare-detail default shape.
    assert "error" not in resp.json()
