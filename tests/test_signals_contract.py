"""tests/test_signals_contract.py — /api/v2/signals widened-column contract (Phase 10 Plan 03).

Proves PAGE-02 legacy parity (D-12): the widened `Signal` surfaces
`entry_zone_low/high`, `sl`, `tp`, `details`, `source_name`, with server-formatted
price `_display` twins on the price fields and BARE strings for `details`/`source_name`.

Reuses the api_app fixture (conftest) + the form-login round-trip from
test_api_contract.py. Tolerates an empty signals table (TRUNCATE'd by the db
fixtures): the shape assertions run only when rows exist; the route-level checks
(200, JSON list) hold regardless.

XSS note (V5 / T-10-06): the JSON contract returns `details`/`raw_text` as plain
strings with NO server-side HTML escaping — the SPA renders them as React text
children (never dangerouslySetInnerHTML). This test confirms they arrive as bare
strings.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from api.formatting import price_display

KNOWN_PASSWORD = "correct-horse-battery-staple"

# Price fields carry a server-formatted `_display` twin.
PRICE_FIELDS = ("entry_zone_low", "entry_zone_high", "sl", "tp")
# Bare strings — MUST NOT carry a `_display` twin (D-05 twin discipline).
BARE_STRING_FIELDS = ("details", "source_name")


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


def test_signals_widened_columns(session_client):
    """GET /api/v2/signals exposes the D-12 widened columns with correct twin discipline."""
    r = session_client.get("/api/v2/signals")
    assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
    body = r.json()
    assert isinstance(body, list), "signals must be a JSON list"

    if not body:
        pytest.skip("signals table empty — route shape verified, no rows to inspect")

    for row in body:
        # Widened parity columns present on every row.
        for key in (*PRICE_FIELDS, *BARE_STRING_FIELDS):
            assert key in row, f"signals row missing {key}"
        # Price `_display` twins declared on every row.
        for key in PRICE_FIELDS:
            assert f"{key}_display" in row, f"signals row missing {key}_display"
        # Bare strings carry NO `_display` twin (D-05).
        for key in BARE_STRING_FIELDS:
            assert f"{key}_display" not in row, f"{key} must not have a _display twin"
        # details/raw_text arrive as plain strings (XSS note V5/T-10-06): no
        # server-side HTML escaping — bare str (or None for details).
        assert isinstance(row["raw_text"], str), "raw_text must be a plain string"
        assert row["details"] is None or isinstance(row["details"], str)
        assert row["source_name"] is None or isinstance(row["source_name"], str)


def test_signals_price_display_matches_formatter(session_client):
    """A sampled non-null sl row formats its `sl_display` via price_display(symbol, sl)."""
    body = session_client.get("/api/v2/signals").json()
    assert isinstance(body, list)

    sampled = False
    for row in body:
        sym = row.get("symbol") or ""
        if row.get("sl") is not None:
            assert row["sl_display"] == price_display(sym, row["sl"]), row
            sampled = True
            break
    if not sampled:
        pytest.skip("no non-null sl row to sample (empty/None-sl signals table)")
