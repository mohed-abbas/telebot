"""tests/test_api_contract.py — /api/v2 read-route contract (Phase 08 Plan 03).

Proves the API-01 + API-04 read-surface contract:

  * Every read route is session-gated — 401 without a session (T-08-11).
  * Authed reads return JSON (never HTML) with the expected model shape.
  * Positions carry BOTH a raw `open_price` (float) AND an `open_price_display`
    string; the deterministic XAUUSD row formats to 2dp (API-04 / Pitfall 5).
  * Timestamp-bearing items (history/signals) carry both an ISO-8601-with-offset
    raw field and an absolute-UTC display string (D-06 / D-07).

Backed by the conftest `api_app` / `api_client` / `session_client` fixtures
(httpx on the session loop; the DryRunConnector seeds a deterministic XAUUSD
position, ticket 100001, open_price 2800.123). Skips cleanly when Postgres is
absent (the `db_pool` fixture skips).
"""

from __future__ import annotations

import re

import pytest

# Read routes that MUST 401 without a session.
READ_ROUTES = [
    "/api/v2/accounts",
    "/api/v2/positions",
    "/api/v2/history",
    "/api/v2/history/filter-options",
    "/api/v2/signals",
    "/api/v2/stages",
    "/api/v2/analytics",
    "/api/v2/overview",
    "/api/v2/trading-status",
    "/api/v2/emergency/preview",
]

# Routes asserted to return a JSON list of models.
LIST_ROUTES = [
    "/api/v2/accounts",
    "/api/v2/positions",
    "/api/v2/history",
    "/api/v2/signals",
]

# Routes asserted to return a JSON object (dict) of model fields.
OBJECT_ROUTES = [
    "/api/v2/history/filter-options",
    "/api/v2/stages",
    "/api/v2/analytics",
    "/api/v2/overview",
    "/api/v2/trading-status",
    "/api/v2/emergency/preview",
]

@pytest.mark.parametrize("path", READ_ROUTES)
async def test_read_route_requires_session(api_client, path):
    """Every read route returns 401 (JSON, no redirect) without a session."""
    r = await api_client.get(path)
    assert r.status_code == 401, f"{path} -> {r.status_code}"
    assert "application/json" in r.headers.get("content-type", ""), path


@pytest.mark.parametrize("path", LIST_ROUTES + OBJECT_ROUTES)
async def test_read_routes_return_json_not_html(session_client, path):
    """Authed read routes return 200 JSON (never HTML)."""
    c, _ = session_client
    r = await c.get(path)
    assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"
    ctype = r.headers.get("content-type", "")
    assert "application/json" in ctype, f"{path} -> {ctype}"
    assert "text/html" not in ctype, f"{path} returned HTML"
    # Body must be parseable JSON of the declared container shape.
    body = r.json()
    if path in LIST_ROUTES:
        assert isinstance(body, list), f"{path} not a list"
    else:
        assert isinstance(body, dict), f"{path} not an object"


async def test_read_routes_expected_keys(session_client):
    """Spot-check model keys on representative authed routes."""
    c, _ = session_client
    accounts = (await c.get("/api/v2/accounts")).json()
    assert isinstance(accounts, list)
    if accounts:
        for key in ("name", "balance", "balance_display", "equity", "equity_display"):
            assert key in accounts[0], f"accounts missing {key}"

    overview = (await c.get("/api/v2/overview")).json()
    for key in ("trading_paused", "open_positions", "accounts"):
        assert key in overview, f"overview missing {key}"

    status = (await c.get("/api/v2/trading-status")).json()
    for key in ("paused", "status"):
        assert key in status, f"trading-status missing {key}"

    preview = (await c.get("/api/v2/emergency/preview")).json()
    for key in ("open_positions", "pending_orders", "accounts"):
        assert key in preview, f"emergency preview missing {key}"

    filt = (await c.get("/api/v2/history/filter-options")).json()
    for key in ("accounts", "symbols", "directions"):
        assert key in filt, f"filter-options missing {key}"

    stages = (await c.get("/api/v2/stages")).json()
    for key in ("active", "resolved"):
        assert key in stages, f"stages missing {key}"


async def test_positions_dual_value(session_client):
    """Each position carries raw open_price + open_price_display; XAUUSD -> 2dp."""
    c, _ = session_client
    positions = (await c.get("/api/v2/positions")).json()
    assert isinstance(positions, list)
    assert positions, "DryRunConnector should seed at least one XAUUSD position"
    for item in positions:
        assert isinstance(item["open_price"], (int, float)), "open_price not numeric"
        assert isinstance(item["open_price_display"], str), "open_price_display not str"
        assert isinstance(item["volume_display"], str)
        assert isinstance(item["profit_display"], str)

    xau = [p for p in positions if p["symbol"] == "XAUUSD"]
    assert xau, "deterministic XAUUSD row missing"
    disp = xau[0]["open_price_display"]
    # 2dp display for the gold pip-size class (Pitfall 5 / quick task 260501-i7u).
    assert re.fullmatch(r"-?\d+\.\d{2}", disp), f"XAUUSD open_price_display not 2dp: {disp}"
    # The seeded row opens at 2800.123 -> 2800.12 at 2dp.
    assert disp == "2800.12", disp


async def test_timestamp_dual_value(session_client):
    """Signals carry an ISO-8601-with-offset raw + an absolute-UTC display string."""
    c, _ = session_client
    signals = (await c.get("/api/v2/signals")).json()
    assert isinstance(signals, list)
    for s in signals:
        if s.get("received_at") is not None:
            # ISO-8601 with explicit UTC offset (D-06).
            assert re.search(r"[+-]\d{2}:\d{2}$", s["received_at"]), s["received_at"]
            assert s["received_at_display"].endswith("UTC"), s["received_at_display"]


async def test_mutations_return_json(session_client):
    """Mutation routes return a JSON envelope, not HTML."""
    c, _ = session_client
    probe = await c.post("/api/v2/positions/Vantage Demo-10k/100001/close")
    if probe.status_code == 404:
        pytest.skip("mutation routes not yet implemented (Plans 04/05)")
    assert "application/json" in probe.headers.get("content-type", ""), probe.headers
    assert "text/html" not in probe.headers.get("content-type", "")
