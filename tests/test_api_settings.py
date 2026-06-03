"""tests/test_api_settings.py — the API-02 settings JSON contract (Phase 08 Plan 05).

Proves the settings surface ships as JSON, not HTML modals/partials:

  * GET /settings/{known}   -> 200 JSON with effective fields + an `audit` list.
  * GET /settings/{unknown} -> 404.
  * POST validate (valid change)        -> {valid:true, diff non-empty, dry_run_text}.
  * POST validate (server cap breach)   -> {valid:false, errors non-empty}, HTTP-200
                                           JSON (NOT an HTML 422 modal).
  * POST confirm  -> JSON envelope; persisted (reflected on a later GET) + audit row.
  * POST revert   -> JSON envelope inverting the prior change.
  * validate/confirm without X-CSRF-Token -> 403 (the D-16 double-submit gate, T-08-19).

The server-side hard caps live in `validate_settings_form` (dashboard.py:664) and
are enforced verbatim by the route — `test_validate_breaches_cap` is the T-08-18
evidence that an over-cap value is rejected server-side regardless of any client
echo.

Harness: the shared conftest `api_app` fixture wires a DryRunConnector-backed
executor stub that has NO settings_store, so this file builds its OWN module app
(`settings_app`) that additionally attaches a real SettingsStore loaded from a
seeded dev-Postgres account. Skips cleanly when dev Postgres is absent (init_db
failure -> pytest.skip), matching the conftest skip contract. A live session is
established through the real JSON `/api/v2/auth/login` route (Plan 02).
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://telebot:telebot_dev@localhost:5433/telebot",
)
KNOWN_PASSWORD = "correct-horse-battery-staple"
ACCOUNT = "settings-acct"


def _build_executor_with_store(settings_store):
    """A DryRunConnector-backed executor stub carrying a real settings_store.

    Mirrors conftest._make_dryrun_executor but additionally attaches the live
    SettingsStore on `tm.settings_store` so dashboard._get_settings_store()
    (which reads getattr(_executor.tm, "settings_store", None)) returns it.
    """
    import types

    from models import AccountConfig
    from mt5_connector import DryRunConnector

    conn = DryRunConnector(ACCOUNT, "TestServer", 12345, "pass")
    conn._connected = True
    acct = AccountConfig(
        name=ACCOUNT, server="TestServer", login=12345,
        password_env="TEST_PASS", risk_percent=1.0, max_lot_size=1.0,
        max_daily_loss_percent=3.0, max_open_trades=3, enabled=True,
    )
    tm = types.SimpleNamespace(
        connectors={ACCOUNT: conn},
        accounts={ACCOUNT: acct},
        settings_store=settings_store,
    )
    cfg = types.SimpleNamespace(max_daily_trades_per_account=30)
    return types.SimpleNamespace(tm=tm, cfg=cfg)


@pytest.fixture(scope="module")
def settings_app():
    """Module app with a seeded account + a live SettingsStore wired on the executor.

    Env-inject + sys.modules.pop + importlib re-import (like conftest.api_app),
    init_db (skip on absence), seed one account + default settings, load a real
    SettingsStore, then init_dashboard with an executor stub carrying that store.
    Yields dashboard.app.
    """
    # Portability guard. The DB-backed /api/v2 tests require the asyncpg pool and
    # the Starlette TestClient to share ONE event loop. That single-loop guarantee
    # holds on the project's target interpreter (Python 3.12, the Dockerfile +
    # CI runtime) via conftest's session `event_loop` fixture, but NOT on newer
    # local interpreters (3.13/3.14) where asyncio.get_event_loop()/TestClient
    # loop semantics changed — the pool then binds to a different loop than the
    # request, raising "another operation is in progress". This is the identical
    # pre-existing environment mismatch tests/test_login_flow.py + test_api_csrf.py
    # hit locally (documented in 08-02-SUMMARY). Skip cleanly off-target so the
    # suite stays green on CI without adding local-only noise.
    if sys.version_info[:2] != (3, 12):
        pytest.skip(
            f"settings /api/v2 DB tests target Python 3.12 (CI); "
            f"running {sys.version_info.major}.{sys.version_info.minor} — "
            "pool/TestClient single-loop guarantee does not hold (see 08-02-SUMMARY)."
        )

    known_hash = PasswordHasher().hash(KNOWN_PASSWORD)
    env = {
        "TG_API_ID": "1", "TG_API_HASH": "x", "TG_SESSION": "x", "TG_CHAT_IDS": "-1",
        "DISCORD_WEBHOOK_URL": "https://example", "TIMEZONE": "UTC",
        "DATABASE_URL": TEST_DATABASE_URL,
        "DASHBOARD_PASS_HASH": known_hash,
        "SESSION_SECRET": "A" * 48,
        "SESSION_COOKIE_SECURE": "false",
    }
    for key in ("DASHBOARD_USER", "DASHBOARD_PASS"):
        os.environ.pop(key, None)
    os.environ.update(env)
    for mod in ("config", "dashboard", "db", "settings_store"):
        sys.modules.pop(mod, None)
    dashboard = importlib.import_module("dashboard")
    import db as _db
    from settings_store import SettingsStore

    # The asyncpg pool binds to the loop it is created on, and the Starlette
    # TestClient drives request handlers on that same current loop. So setup MUST
    # run on the loop the TestClient will later use. On CI (Python 3.12)
    # asyncio.get_event_loop() returns the conftest session `event_loop`, which
    # the TestClient also adopts — pool + requests share one loop (this is how
    # tests/test_api_csrf.py runs green). On the local Python 3.14 interpreter
    # get_event_loop() raises when no loop is current, so we skip cleanly (the
    # documented conftest skip contract, matching api_app).
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError as exc:
        pytest.skip(f"No current event loop (Python 3.14 local env): {exc}")

    async def _setup():
        await _db.init_db(env["DATABASE_URL"])
        # Clean slate for this module's account + audit.
        async with _db._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE settings_audit, account_settings, accounts "
                "RESTART IDENTITY CASCADE"
            )
        await _db.upsert_account_if_missing(
            name=ACCOUNT, server="Test", login=99999, password_env="",
            risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
            max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
        )
        await _db.upsert_account_settings_if_missing(
            account_name=ACCOUNT, risk_mode="percent", risk_value=1.0,
            max_stages=1, default_sl_pips=100, max_daily_trades=30,
        )
        store = SettingsStore(_db._pool)
        await store.load_all()
        return store

    try:
        store = loop.run_until_complete(_setup())
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available for settings api tests: {exc}")

    dashboard.init_dashboard(
        _build_executor_with_store(store), notifier=None, settings=None
    )
    yield dashboard.app
    try:
        loop.run_until_complete(_db.close_db())
    except Exception:
        pass


def _login(client: TestClient) -> str:
    """Drive the real JSON login and return the live telebot_csrf token."""
    r = client.get("/api/v2/auth/csrf")
    assert r.status_code == 200, r.text
    token = r.json()["csrf_token"]
    r = client.post(
        "/api/v2/auth/login",
        json={"password": KNOWN_PASSWORD, "csrf_token": token},
    )
    assert r.status_code == 200, r.text
    return client.cookies.get("telebot_csrf")


@pytest.fixture
def client(settings_app):
    """An authenticated TestClient + the live csrf token (tuple)."""
    c = TestClient(settings_app)
    token = _login(c)
    return c, token


# ─── GET effective + audit ───────────────────────────────────────────────────


def test_get_settings_known_account(client):
    """GET a known account -> 200 JSON with effective fields + an audit list."""
    c, _ = client
    r = c.get(f"/api/v2/settings/{ACCOUNT}")
    assert r.status_code == 200, r.text
    assert "application/json" in r.headers["content-type"]
    body = r.json()
    assert body["account"] == ACCOUNT
    values = body["values"]
    # Effective fields present.
    for field in ("risk_mode", "risk_value", "max_stages", "default_sl_pips",
                  "max_daily_trades", "max_open_trades", "max_lot_size"):
        assert field in values, f"missing effective field {field}"
    assert isinstance(body["audit"], list)


def test_get_settings_unknown_account(client):
    """GET an unknown account -> 404."""
    c, _ = client
    r = c.get("/api/v2/settings/does-not-exist")
    assert r.status_code == 404, r.text


# ─── POST validate ───────────────────────────────────────────────────────────


def test_validate_valid_change(client):
    """An in-range change -> {valid:true, non-empty diff, dry_run_text present}."""
    c, token = client
    r = c.post(
        f"/api/v2/settings/{ACCOUNT}/validate",
        headers={"X-CSRF-Token": token},
        json={
            "account": ACCOUNT,
            "values": {
                "risk_mode": "percent", "risk_value": "2.0",
                "max_stages": "3", "default_sl_pips": "100",
                "max_daily_trades": "30",
            },
        },
    )
    assert r.status_code == 200, r.text
    assert "application/json" in r.headers["content-type"]
    body = r.json()
    assert body["valid"] is True
    assert body["diff"], "expected a non-empty diff for a real change"
    assert body["dry_run_text"]


def test_validate_breaches_cap(client):
    """A value above the server hard cap -> {valid:false, errors non-empty} as JSON.

    risk_mode=percent caps risk_value at 5.0 (dashboard.py:692). 9.0 must be
    rejected server-side (T-08-18) and returned as JSON, never an HTML 422 modal.
    """
    c, token = client
    r = c.post(
        f"/api/v2/settings/{ACCOUNT}/validate",
        headers={"X-CSRF-Token": token},
        json={
            "account": ACCOUNT,
            "values": {
                "risk_mode": "percent", "risk_value": "9.0",
                "max_stages": "3", "default_sl_pips": "100",
                "max_daily_trades": "30",
            },
        },
    )
    assert r.status_code == 200, r.text
    assert "application/json" in r.headers["content-type"]
    assert "<html" not in r.text.lower()
    body = r.json()
    assert body["valid"] is False
    assert body["errors"], "expected per-field errors for a cap breach"
    assert "risk_value" in body["errors"]


# ─── POST confirm (persist + audit) ──────────────────────────────────────────


def test_confirm_persists_and_audits(client):
    """Confirm -> JSON envelope; the change is reflected on a later GET + audited."""
    c, token = client
    r = c.post(
        f"/api/v2/settings/{ACCOUNT}",
        headers={"X-CSRF-Token": token},
        json={
            "account": ACCOUNT,
            "values": {
                "risk_mode": "percent", "risk_value": "1.0",
                "max_stages": "4", "default_sl_pips": "100",
                "max_daily_trades": "30",
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True

    # Reflected on a subsequent GET.
    g = c.get(f"/api/v2/settings/{ACCOUNT}")
    assert g.status_code == 200, g.text
    gbody = g.json()
    assert int(gbody["values"]["max_stages"]) == 4
    # An audit row was added for the change.
    fields = [row["field"] for row in gbody["audit"]]
    assert "max_stages" in fields


# ─── POST revert ─────────────────────────────────────────────────────────────


def test_revert_inverts_prior_change(client):
    """Revert -> JSON envelope inverting the most-recent change."""
    c, token = client
    # Make a change first (max_stages 1 -> 5).
    r = c.post(
        f"/api/v2/settings/{ACCOUNT}",
        headers={"X-CSRF-Token": token},
        json={
            "account": ACCOUNT,
            "values": {
                "risk_mode": "percent", "risk_value": "1.0",
                "max_stages": "5", "default_sl_pips": "100",
                "max_daily_trades": "30",
            },
        },
    )
    assert r.status_code == 200, r.text
    before = c.get(f"/api/v2/settings/{ACCOUNT}").json()
    assert int(before["values"]["max_stages"]) == 5

    # Revert inverts it back to the prior value.
    rv = c.post(
        f"/api/v2/settings/{ACCOUNT}/revert",
        headers={"X-CSRF-Token": token},
        json={"account": ACCOUNT},
    )
    assert rv.status_code == 200, rv.text
    assert rv.json().get("ok") is True

    after = c.get(f"/api/v2/settings/{ACCOUNT}").json()
    assert int(after["values"]["max_stages"]) != 5


# ─── CSRF gate (T-08-19) ─────────────────────────────────────────────────────


def test_validate_requires_csrf(client):
    """POST validate WITHOUT X-CSRF-Token -> 403 (no HTML)."""
    c, _ = client
    c.cookies.delete("telebot_csrf")
    r = c.post(
        f"/api/v2/settings/{ACCOUNT}/validate",
        json={"account": ACCOUNT, "values": {"risk_mode": "percent",
              "risk_value": "2.0", "max_stages": "3", "default_sl_pips": "100",
              "max_daily_trades": "30"}},
    )
    assert r.status_code == 403, r.text
    assert "<html" not in r.text.lower()


def test_confirm_requires_csrf(client):
    """POST confirm WITHOUT X-CSRF-Token -> 403."""
    c, _ = client
    c.cookies.delete("telebot_csrf")
    r = c.post(
        f"/api/v2/settings/{ACCOUNT}",
        json={"account": ACCOUNT, "values": {"risk_mode": "percent",
              "risk_value": "1.0", "max_stages": "2", "default_sl_pips": "100",
              "max_daily_trades": "30"}},
    )
    assert r.status_code == 403, r.text
