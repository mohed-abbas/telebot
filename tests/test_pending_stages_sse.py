"""Integration tests for Phase 6 Plan 05 STAGE-08 pending-stages panel.

Covers:
  - SSE /stream payload includes `pending_stages` key (D-34)
  - SSE /stream emits a named `event: pending_stages` with pre-rendered HTML partial
  - X-Accel-Buffering: no header preserved (Pitfall 18)
  - /staged page renders empty-state primitive when zero rows (D-35)
  - /staged page renders Recently resolved section + labels (D-36)
  - /partials/pending_stages default=top 5, ?all=1=all rows

Fixture chain duplicated from tests/test_settings_form.py — keeps this test file
self-contained (matches existing per-file fixture idioms used elsewhere in the
suite).
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import sys

import pytest
import pytest_asyncio
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient


KNOWN_PASSWORD = "correct-horse-battery-staple"

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="module")
def known_hash():
    return PasswordHasher().hash(KNOWN_PASSWORD)


@pytest.fixture(scope="module")
def app(known_hash):
    """Import the dashboard app with a known argon2 hash + session secret."""
    env = {
        "TG_API_ID": "1", "TG_API_HASH": "x", "TG_SESSION": "x", "TG_CHAT_IDS": "-1",
        "DISCORD_WEBHOOK_URL": "https://example", "TIMEZONE": "UTC",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql://telebot:telebot_dev@localhost:5433/telebot",
        ),
        "DASHBOARD_PASS_HASH": known_hash,
        "SESSION_SECRET": "B" * 48,
        "SESSION_COOKIE_SECURE": "false",
    }
    for key in ("DASHBOARD_USER", "DASHBOARD_PASS"):
        os.environ.pop(key, None)
    os.environ.update(env)
    for mod in ("config", "dashboard"):
        sys.modules.pop(mod, None)
    dashboard = importlib.import_module("dashboard")
    return dashboard


class _StubConnector:
    connected = False

    async def get_account_info(self):
        return None

    async def get_positions(self):
        return []


class _StubTM:
    def __init__(self, accounts):
        self.connectors = {a: _StubConnector() for a in accounts}
        self.accounts = {}
        self.settings_store = None


class _StubExecutor:
    def __init__(self, tm):
        self.tm = tm
        self._trading_paused = False
        self._reconnecting = set()

        class _CfgStub:
            max_daily_trades_per_account = 30

        self.cfg = _CfgStub()


@pytest_asyncio.fixture
async def seeded_accounts(db_pool):
    import db as db_mod
    for name, login in (("acc-01", 10001),):
        await db_mod.upsert_account_if_missing(
            name=name, server="TestServer", login=login, password_env="",
            risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
            max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
        )
        await db_mod.upsert_account_settings_if_missing(account_name=name)
    return ["acc-01"]


@pytest_asyncio.fixture
async def seeded_account(seeded_accounts):
    return seeded_accounts[0]


@pytest_asyncio.fixture
async def seeded_signal(db_pool):
    import db as db_mod
    async with db_mod._pool.acquire() as conn:
        sid = await conn.fetchval(
            """INSERT INTO signals (raw_text, signal_type, symbol, direction, action_taken)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            "test signal", "open_text_only", "XAUUSD", "buy", "staged",
        )
    return sid


@pytest_asyncio.fixture
async def wired_dashboard(app, seeded_accounts, db_pool):
    dashboard = app
    from settings_store import SettingsStore

    store = SettingsStore(db_pool=db_pool)
    await store.load_all()

    tm = _StubTM(seeded_accounts)
    tm.settings_store = store
    executor = _StubExecutor(tm)

    prior = {
        "_executor": getattr(dashboard, "_executor", None),
        "_settings": getattr(dashboard, "_settings", None),
    }

    class _Settings:
        trading_enabled = True
        trading_dry_run = True

    dashboard._executor = executor
    dashboard._settings = _Settings()

    yield dashboard

    dashboard._executor = prior["_executor"]
    dashboard._settings = prior["_settings"]


@pytest_asyncio.fixture
async def authenticated_client(wired_dashboard):
    transport = ASGITransport(app=wired_dashboard.app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver", follow_redirects=False
    ) as client:
        r = await client.get("/login")
        assert r.status_code == 200
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
        assert m
        token = m.group(1)
        r = await client.post(
            "/login",
            data={"password": KNOWN_PASSWORD, "csrf_token": token, "next_path": "/overview"},
        )
        assert r.status_code == 303
        yield client


def _row(signal_id, account_name, *, stage_number=1, mt5_comment="telebot-x-s1",
         status="awaiting_zone", direction="buy"):
    return {
        "signal_id": signal_id,
        "stage_number": stage_number,
        "account_name": account_name,
        "symbol": "XAUUSD",
        "direction": direction,
        "zone_low": 2040.0,
        "zone_high": 2050.0,
        "band_low": 2041.2,
        "band_high": 2043.8,
        "target_lot": 0.05,
        "snapshot_settings": {
            "risk_mode": "percent", "risk_value": 1.0, "max_stages": 5,
            "default_sl_pips": 50, "max_daily_trades": 10,
        },
        "mt5_comment": mt5_comment,
        "status": status,
    }


async def _drive_sse_once(dashboard_mod, client):
    """Drive one tick of the SSE generator directly.

    httpx.ASGITransport does not stream — it collects the entire response
    before returning, which hangs forever on an infinite SSE generator. We
    invoke `sse_stream` as a coroutine, then pull the first few chunks from
    the returned StreamingResponse's body iterator. This exercises the real
    production generator (including `_get_all_positions`, `db.get_pending_stages`,
    template render, and header wiring) without a live HTTP round-trip.
    """
    # Build a minimal Request-compatible shim so `_verify_auth` + the generator
    # can run. The generator calls `request.is_disconnected()` — we want False
    # for one tick, then True so the loop exits.
    disconnected_calls = {"n": 0}

    class _Req:
        session = {"user": "admin"}
        headers: dict = {}
        url = None

        async def is_disconnected(self):
            disconnected_calls["n"] += 1
            # First probe in the while-loop: allow one iteration; second probe
            # after asyncio.sleep(2) would trigger exit — but we never reach
            # it because we break out after collecting chunks.
            return disconnected_calls["n"] > 1

    resp = await dashboard_mod.sse_stream(_Req(), user="admin")
    # Collect chunks up to ~3 yields (named event + default data + sentinel).
    chunks: list[str] = []
    it = resp.body_iterator
    async for raw in it:
        text = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
        chunks.append(text)
        if len(chunks) >= 3:
            break
    # Make sure the generator is closed so asyncio.sleep is not left pending.
    try:
        await it.aclose()
    except Exception:  # pragma: no cover
        pass
    return resp, chunks


# ─── SSE shape + header ──────────────────────────────────────────────────


async def test_sse_payload_includes_pending_stages_key(wired_dashboard, authenticated_client):
    """D-34: /stream JSON payload carries a `pending_stages` list."""
    resp, chunks = await _drive_sse_once(wired_dashboard, authenticated_client)
    # Find the `data: {...json...}` chunk (the default event).
    body = "".join(chunks)
    lines = body.split("\n")
    data_line = next(
        (ln for ln in lines if ln.startswith("data: ") and ln.lstrip("data: ").startswith("{")),
        None,
    )
    assert data_line is not None, f"no JSON data: line in SSE output: {chunks}"
    payload = json.loads(data_line[len("data: "):])
    assert "pending_stages" in payload
    assert isinstance(payload["pending_stages"], list)


async def test_sse_emits_named_pending_stages_event(wired_dashboard, authenticated_client):
    """Task 2 Step 6: SSE stream emits a named `event: pending_stages` line."""
    resp, chunks = await _drive_sse_once(wired_dashboard, authenticated_client)
    body = "".join(chunks)
    assert "event: pending_stages" in body, f"no named event in SSE body: {body[:400]}"


async def test_sse_accel_buffering_header_set(wired_dashboard, authenticated_client):
    """Pitfall 18: X-Accel-Buffering: no must be preserved on SSE."""
    resp, _ = await _drive_sse_once(wired_dashboard, authenticated_client)
    # Headers on StreamingResponse are a MutableHeaders mapping — case-insensitive.
    assert resp.headers.get("x-accel-buffering") == "no"


async def test_sse_content_type_event_stream(wired_dashboard, authenticated_client):
    resp, _ = await _drive_sse_once(wired_dashboard, authenticated_client)
    assert "text/event-stream" in resp.media_type


# ─── /staged page ────────────────────────────────────────────────────────


async def test_staged_page_renders_empty_state(authenticated_client, db_pool, seeded_account):
    """D-35: /staged with zero rows renders Basecoat empty-state primitive."""
    resp = await authenticated_client.get("/staged")
    assert resp.status_code == 200
    assert "No pending stages" in resp.text
    assert "empty-state" in resp.text


async def test_staged_page_includes_recently_resolved_when_present(
    authenticated_client, db_pool, seeded_account, seeded_signal,
):
    """D-36: cancelled stages appear in the Recently resolved section with the
    D-36 human label ('Kill-switch drain')."""
    import db as db_mod
    # Insert one cancelled_by_kill_switch row directly via create + mutate.
    [sid] = await db_mod.create_staged_entries(
        [_row(seeded_signal, seeded_account, mt5_comment="telebot-killed-s1")]
    )
    await db_mod.update_stage_status(
        sid, "cancelled_by_kill_switch", cancelled_reason="kill_switch",
    )

    resp = await authenticated_client.get("/staged")
    assert resp.status_code == 200
    assert "Recently resolved" in resp.text
    assert "Kill-switch drain" in resp.text


# ─── /partials/pending_stages ────────────────────────────────────────────


async def test_partials_pending_stages_all_param(
    authenticated_client, db_pool, seeded_account, seeded_signal,
):
    """GET /partials/pending_stages?all=1 returns all rows; default returns top 5."""
    import db as db_mod
    # Insert 7 active (awaiting_zone) rows.
    rows = [
        _row(seeded_signal, seeded_account,
             stage_number=i + 1, mt5_comment=f"telebot-many-s{i+1}")
        for i in range(7)
    ]
    await db_mod.create_staged_entries(rows)

    # Default (top 5): 5 rows rendered — count direction badge occurrences.
    resp_top = await authenticated_client.get("/partials/pending_stages")
    assert resp_top.status_code == 200
    top_badges = resp_top.text.count("badge-buy") + resp_top.text.count("badge-sell")
    assert top_badges == 5, f"expected 5 badges in top-5 partial, got {top_badges}"

    # ?all=1: 7 rows rendered.
    resp_all = await authenticated_client.get("/partials/pending_stages?all=1")
    assert resp_all.status_code == 200
    all_badges = resp_all.text.count("badge-buy") + resp_all.text.count("badge-sell")
    assert all_badges == 7, f"expected 7 badges in all partial, got {all_badges}"
