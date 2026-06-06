"""tests/test_analytics_contract.py — /api/v2/analytics widened contract (Phase 10 Plan 01).

Gates PAGE-01 (D-01 legacy parity widening). The analytics route now surfaces the
full payload — `by_source[]`, `extremes`, `avg_stages`, `sources` — alongside the
flat summary. This Wave-0 contract test proves:

  * GET /api/v2/analytics 200 returns the four new keys.
  * `by_source` is a list; each row carries a `net_pnl_display` str and BARE
    `win_rate`/`profit_factor` (NO `win_rate_display`/`profit_factor_display`, D-14).
  * each present `net_pnl_display` == `money_display(net_pnl)` (server-formatted, Pitfall 5).
  * `extremes` carries the best/worst + `_display` twin shape.
  * the all-source default load yields `avg_stages is None` (mirrors legacy
    `{% if avg_stages %}` — Pitfall 3); a source-filtered call MAY return non-null.

Harness mirrors tests/test_pending_stages_sse.py (the proven single-loop pattern for
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

from api.formatting import money_display
from tests.conftest import _make_dryrun_executor

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="module")
def analytics_app():
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
async def client(analytics_app, db_pool):
    """An httpx AsyncClient with require_user overridden, sharing the session loop.

    `db_pool` (session-scoped) guarantees the asyncpg pool is live on this loop before
    the analytics route touches it. `require_user` is overridden so the read-only
    contract test never drives the DB-writing form-login path.
    """
    from api.deps import require_user

    dashboard = analytics_app
    # Wire the DryRunConnector-backed executor stub so the app boots cleanly.
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


async def test_analytics_has_widened_keys(client):
    """GET /api/v2/analytics returns the four D-01 parity keys."""
    r = await client.get("/api/v2/analytics")
    assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
    body = r.json()
    for key in ("by_source", "extremes", "avg_stages", "sources"):
        assert key in body, f"analytics missing {key}"
    assert isinstance(body["by_source"], list), "by_source not a list"
    assert isinstance(body["sources"], list), "sources not a list"
    assert isinstance(body["extremes"], dict), "extremes not an object"


async def test_by_source_ratios_stay_raw_money_has_display(client):
    """Each by_source row: money `_display` twins present; ratios bare (D-14)."""
    body = (await client.get("/api/v2/analytics")).json()
    for row in body["by_source"]:
        # Money field carries a server-formatted display twin.
        assert isinstance(row["net_pnl_display"], str), "net_pnl_display not str"
        # Display twin equals the formatter output (no client re-rounding, Pitfall 5).
        assert row["net_pnl_display"] == money_display(row["net_pnl"]), (
            f"net_pnl_display {row['net_pnl_display']!r} != money_display({row['net_pnl']})"
        )
        # Ratios stay raw — NO _display twin (D-14).
        assert "win_rate_display" not in row, "win_rate must stay raw (D-14)"
        assert "profit_factor_display" not in row, "profit_factor must stay raw (D-14)"
        # best/worst money fields are None-guarded but, when present, format correctly.
        for fld in ("best_trade", "worst_trade"):
            disp = f"{fld}_display"
            assert disp in row, f"by_source row missing {disp}"
            if row[fld] is not None:
                assert row[disp] == money_display(row[fld]), f"{disp} mismatch"
            else:
                assert row[disp] is None, f"{disp} should be None when {fld} is None"


async def test_extremes_dual_value_shape(client):
    """`extremes` carries best/worst + None-guarded money `_display` twins."""
    extremes = (await client.get("/api/v2/analytics")).json()["extremes"]
    for fld in ("best_trade", "worst_trade"):
        disp = f"{fld}_display"
        assert fld in extremes, f"extremes missing {fld}"
        assert disp in extremes, f"extremes missing {disp}"
        if extremes[fld] is not None:
            assert extremes[disp] == money_display(extremes[fld]), f"extremes {disp} mismatch"
        else:
            assert extremes[disp] is None, f"extremes {disp} should be None"


async def test_avg_stages_none_on_all_source_default(client):
    """All-source default load → avg_stages is None (legacy `{% if avg_stages %}`, Pitfall 3)."""
    body = (await client.get("/api/v2/analytics")).json()
    assert body["avg_stages"] is None, (
        f"avg_stages must be None without a source filter, got {body['avg_stages']!r}"
    )


async def test_source_filtered_call_is_well_formed(client):
    """A source-filtered call stays a valid, contract-shaped 200 payload.

    avg_stages MAY become non-null when a source filter is active (it is only
    populated from staged_entries for the filtered source); this asserts the
    filtered request remains contract-shaped rather than pinning a value that
    depends on seeded staged data.
    """
    body = (await client.get("/api/v2/analytics")).json()
    sources = body["sources"]
    if not sources:
        pytest.skip("no analytics sources seeded; source-filter path not exercisable")
    filtered = await client.get("/api/v2/analytics", params={"source": sources[0]})
    assert filtered.status_code == 200, filtered.status_code
    fb = filtered.json()
    for key in ("by_source", "extremes", "avg_stages", "sources"):
        assert key in fb, f"filtered analytics missing {key}"
    # avg_stages is either None or a non-negative number — never an int-default 0 stub.
    if fb["avg_stages"] is not None:
        assert isinstance(fb["avg_stages"], (int, float)) and fb["avg_stages"] >= 0
