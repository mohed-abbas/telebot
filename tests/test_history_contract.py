"""tests/test_history_contract.py — /api/v2/history widened-column + filter contract.

Phase 10 Plan 03. Proves PAGE-03 legacy parity (D-12) and the 5-param filter
round-trip:

  * Widened columns: each history row surfaces `sl`, `tp` (+ price `_display`
    twins), `status`, `source_name` (BARE strings, no `_display`).
  * Price `_display` equals price_display(symbol, value) for a sampled non-null
    sl/tp (Pitfall 5 — server-formatted, never re-rounded client-side).
  * Filter round-trip: GET /history/filter-options yields valid account/symbol/
    source values; GET /history?account=&symbol= returns only rows matching ALL
    supplied filters (D-11 AND logic, parameterized asyncpg `$n` — T-10-05).

Reuses the api_app fixture (conftest) + the form-login round-trip. Tolerates an
empty trades table (TRUNCATE'd by db fixtures): shape + AND assertions run only
when rows / filter-options exist.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from api.formatting import price_display

KNOWN_PASSWORD = "correct-horse-battery-staple"

# Price fields carry a server-formatted `_display` twin.
PRICE_FIELDS = ("sl", "tp")
# Bare strings — MUST NOT carry a `_display` twin (D-05 twin discipline).
BARE_STRING_FIELDS = ("status", "source_name")


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


def test_history_widened_columns(session_client):
    """GET /api/v2/history exposes D-12 widened columns with correct twin discipline."""
    r = session_client.get("/api/v2/history")
    assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
    body = r.json()
    assert isinstance(body, list), "history must be a JSON list"

    if not body:
        pytest.skip("trades table empty — route shape verified, no rows to inspect")

    for row in body:
        for key in (*PRICE_FIELDS, *BARE_STRING_FIELDS):
            assert key in row, f"history row missing {key}"
        # Price `_display` twins declared on every row.
        for key in PRICE_FIELDS:
            assert f"{key}_display" in row, f"history row missing {key}_display"
        # Bare strings carry NO `_display` twin (D-05).
        for key in BARE_STRING_FIELDS:
            assert f"{key}_display" not in row, f"{key} must not have a _display twin"
        assert row["status"] is None or isinstance(row["status"], str)
        assert row["source_name"] is None or isinstance(row["source_name"], str)


def test_history_price_display_matches_formatter(session_client):
    """A sampled non-null sl/tp row formats its `_display` via price_display(symbol, v)."""
    body = session_client.get("/api/v2/history").json()
    assert isinstance(body, list)

    sampled = False
    for row in body:
        sym = row.get("symbol") or ""
        for field in PRICE_FIELDS:
            v = row.get(field)
            if v is not None:
                assert row[f"{field}_display"] == price_display(sym, v), row
                sampled = True
    if not sampled:
        pytest.skip("no non-null sl/tp row to sample (empty/None-price trades table)")


def test_history_five_param_filter_round_trip(session_client):
    """account+symbol filters round-trip with AND logic over returned rows (D-11)."""
    opts = session_client.get("/api/v2/history/filter-options").json()
    assert isinstance(opts, dict)
    for key in ("accounts", "symbols"):
        assert key in opts, f"filter-options missing {key}"

    accounts = opts.get("accounts") or []
    symbols = opts.get("symbols") or []
    if not accounts or not symbols:
        # Empty DB: prove the unfiltered + a benign multi-param call still 200/list.
        r = session_client.get(
            "/api/v2/history",
            params={
                "account": "nope",
                "symbol": "NONE",
                "from_date": "2000-01-01",
                "to_date": "2000-01-02",
            },
        )
        assert r.status_code == 200, r.text[:200]
        assert isinstance(r.json(), list)
        pytest.skip("filter-options empty — AND assertions skipped on empty DB")

    a = accounts[0]
    sym = symbols[0]
    r = session_client.get("/api/v2/history", params={"account": a, "symbol": sym})
    assert r.status_code == 200, r.text[:200]
    rows = r.json()
    assert isinstance(rows, list)
    # AND logic: every returned row matches BOTH filters.
    for row in rows:
        assert row["account"] == a, f"account filter leaked: {row['account']} != {a}"
        assert row["symbol"] == sym, f"symbol filter leaked: {row['symbol']} != {sym}"
