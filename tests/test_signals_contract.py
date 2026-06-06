"""tests/test_signals_contract.py — /api/v2/signals widened-column contract (Phase 10 Plan 03).

Proves PAGE-02 legacy parity (D-12): the widened `Signal` surfaces
`entry_zone_low/high`, `sl`, `tp`, `details`, `source_name`, with server-formatted
price `_display` twins on the price fields and BARE strings for `details`/`source_name`.

Tolerates an empty signals table (TRUNCATE'd by the db fixtures): the shape
assertions run only when rows exist; the route-level checks (200, JSON list) hold
regardless.

XSS note (V5 / T-10-06): the JSON contract returns `details`/`raw_text` as plain
strings with NO server-side HTML escaping — the SPA renders them as React text
children (never dangerouslySetInnerHTML). This test confirms they arrive as bare
strings.

Harness mirrors tests/test_analytics_contract.py (the proven single-loop pattern for
DB-backed /api/v2): `pytest.mark.asyncio(loop_scope="session")` + httpx ASGITransport
AsyncClient + the session-scoped `db_pool` fixture, so the asyncpg pool and the request
handler share ONE event loop (the conftest session loop). This avoids the TestClient
blocking-portal loop split that raises "another operation is in progress" /
"attached to a different loop" for pool-touching routes. Auth is seeded by overriding
the `require_user` dependency (the route is read-only; the 401-without-session contract
is covered in tests/test_api_contract.py). Skips cleanly when dev Postgres is absent
(the db_pool fixture calls pytest.skip).
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest
import pytest_asyncio
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient

from api.formatting import price_display
from tests.conftest import _make_dryrun_executor

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Price fields carry a server-formatted `_display` twin.
PRICE_FIELDS = ("entry_zone_low", "entry_zone_high", "sl", "tp")
# Bare strings — MUST NOT carry a `_display` twin (D-05 twin discipline).
BARE_STRING_FIELDS = ("details", "source_name")


@pytest.fixture(scope="module")
def signals_app():
    """Import the dashboard app with a known argon2 hash + a DryRun executor wired."""
    env = {
        "TG_API_ID": "1", "TG_API_HASH": "x", "TG_SESSION": "x", "TG_CHAT_IDS": "-1",
        "DISCORD_WEBHOOK_URL": "https://example", "TIMEZONE": "UTC",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql://telebot:telebot_dev@localhost:5433/telebot",
        ),
        "DASHBOARD_PASS_HASH": PasswordHasher().hash("contract-test-pass"),
        "SESSION_SECRET": "C" * 48,
        "SESSION_COOKIE_SECURE": "false",
    }
    for key in ("DASHBOARD_USER", "DASHBOARD_PASS"):
        os.environ.pop(key, None)
    os.environ.update(env)
    for mod in ("config", "dashboard"):
        sys.modules.pop(mod, None)
    dashboard = importlib.import_module("dashboard")
    return dashboard


@pytest_asyncio.fixture
async def client(signals_app, db_pool):
    """An httpx AsyncClient with require_user overridden, sharing the session loop.

    `db_pool` (session-scoped) guarantees the asyncpg pool is live on this loop before
    the signals route touches it. `require_user` is overridden so the read-only
    contract test never drives the DB-writing form-login path.
    """
    from api.deps import require_user

    dashboard = signals_app
    dashboard.init_dashboard(_make_dryrun_executor(), notifier=None, settings=None)
    dashboard.app.dependency_overrides[require_user] = lambda: "test-operator"
    transport = ASGITransport(app=dashboard.app)
    try:
        async with AsyncClient(
            transport=transport, base_url="http://testserver", follow_redirects=False
        ) as c:
            yield c
    finally:
        dashboard.app.dependency_overrides.pop(require_user, None)


async def test_signals_widened_columns(client):
    """GET /api/v2/signals exposes the D-12 widened columns with correct twin discipline."""
    r = await client.get("/api/v2/signals")
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


async def test_signals_price_display_matches_formatter(client):
    """A sampled non-null sl row formats its `sl_display` via price_display(symbol, sl)."""
    body = (await client.get("/api/v2/signals")).json()
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
