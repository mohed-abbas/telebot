"""tests/test_api_contract.py — /api/v2 read-route contract (Phase 08 Plan 03).

Proves the API-01 + API-04 read-surface contract:

  * Every read route is session-gated — 401 without a session (T-08-11).
  * Authed reads return JSON (never HTML) with the expected model shape.
  * Positions carry BOTH a raw `open_price` (float) AND an `open_price_display`
    string; the deterministic XAUUSD row formats to 2dp (API-04 / Pitfall 5).
  * Timestamp-bearing items (history/signals) carry both an ISO-8601-with-offset
    raw field and an absolute-UTC display string (D-06 / D-07).

Backed by the `api_app` fixture (conftest), whose DryRunConnector seeds a
deterministic XAUUSD position (ticket 100001, open_price 2800.123). Skips
cleanly when dev Postgres is absent (the fixture calls pytest.skip).
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

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

KNOWN_PASSWORD = "correct-horse-battery-staple"


def _login(client: TestClient) -> None:
    """Drive the form-login route to seed a real session cookie on `client`."""
    r = client.get("/login")
    assert r.status_code == 200, r.status_code
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    assert m, "csrf_token missing from /login form"
    r = client.post(
        "/login",
        data={"password": KNOWN_PASSWORD, "csrf_token": m.group(1), "next_path": "/overview"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.status_code
    assert "telebot_session" in client.cookies


@pytest.fixture
def session_client(api_app):
    """A TestClient carrying a real logged-in session (form-login round-trip)."""
    client = TestClient(api_app)
    _login(client)
    return client


@pytest.mark.parametrize("path", READ_ROUTES)
def test_read_route_requires_session(api_app, path):
    """Every read route returns 401 (JSON, no redirect) without a session."""
    client = TestClient(api_app)
    r = client.get(path)
    assert r.status_code == 401, f"{path} -> {r.status_code}"
    assert "application/json" in r.headers.get("content-type", ""), path


@pytest.mark.parametrize("path", LIST_ROUTES + OBJECT_ROUTES)
def test_read_routes_return_json_not_html(session_client, path):
    """Authed read routes return 200 JSON (never HTML)."""
    r = session_client.get(path)
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


def test_read_routes_expected_keys(session_client):
    """Spot-check model keys on representative authed routes."""
    accounts = session_client.get("/api/v2/accounts").json()
    assert isinstance(accounts, list)
    if accounts:
        for key in ("name", "balance", "balance_display", "equity", "equity_display"):
            assert key in accounts[0], f"accounts missing {key}"

    overview = session_client.get("/api/v2/overview").json()
    for key in ("trading_paused", "open_positions", "accounts"):
        assert key in overview, f"overview missing {key}"

    status = session_client.get("/api/v2/trading-status").json()
    for key in ("paused", "status"):
        assert key in status, f"trading-status missing {key}"

    preview = session_client.get("/api/v2/emergency/preview").json()
    for key in ("open_positions", "pending_orders", "accounts"):
        assert key in preview, f"emergency preview missing {key}"

    filt = session_client.get("/api/v2/history/filter-options").json()
    for key in ("accounts", "symbols", "directions"):
        assert key in filt, f"filter-options missing {key}"

    stages = session_client.get("/api/v2/stages").json()
    for key in ("active", "resolved"):
        assert key in stages, f"stages missing {key}"


def test_positions_dual_value(session_client):
    """Each position carries raw open_price + open_price_display; XAUUSD -> 2dp."""
    positions = session_client.get("/api/v2/positions").json()
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


def test_timestamp_dual_value(session_client):
    """Signals carry an ISO-8601-with-offset raw + an absolute-UTC display string."""
    signals = session_client.get("/api/v2/signals").json()
    assert isinstance(signals, list)
    for s in signals:
        if s.get("received_at") is not None:
            # ISO-8601 with explicit UTC offset (D-06).
            assert re.search(r"[+-]\d{2}:\d{2}$", s["received_at"]), s["received_at"]
            assert s["received_at_display"].endswith("UTC"), s["received_at_display"]


def test_mutations_return_json(session_client):
    """Placeholder hook (VALIDATION): mutation routes return a JSON envelope, not HTML.

    The actions/settings mutation routes land in Plans 04/05. This test is
    collected now and skips cleanly until those routes exist; when they do it
    asserts the response is JSON (never an HTML fragment).
    """
    probe = session_client.post("/api/v2/positions/Vantage Demo-10k/100001/close")
    if probe.status_code == 404:
        pytest.skip("mutation routes not yet implemented (Plans 04/05)")
    assert "application/json" in probe.headers.get("content-type", ""), probe.headers
    assert "text/html" not in probe.headers.get("content-type", "")
