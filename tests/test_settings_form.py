"""Integration tests for Phase 6 SET-03 settings form routes.

Covers:
  - GET /settings renders Basecoat tabs per account
  - POST /settings/{account} CSRF enforcement + hard-cap validation (D-29/D-31)
  - POST /settings/{account} renders two-step modal on valid diff (D-27)
  - POST /settings/{account}/confirm writes audit row via SettingsStore.update
  - POST /settings/{account}/revert renders inverted-diff modal (D-28)
  - Revert confirm writes a NEW audit row (revert is itself audited)

Uses httpx.AsyncClient over ASGITransport so the app runs on the same event loop
as the shared asyncpg pool (conftest.py session-scoped `event_loop` fixture).
This avoids the cross-loop asyncpg errors that fastapi.testclient.TestClient
triggers under Python 3.12+.
"""
from __future__ import annotations

import importlib
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
    """Import the dashboard app with a known argon2 password hash + session secret.

    The shared asyncpg pool is opened by tests/conftest.py's session-scoped
    `db_pool` fixture, so this fixture only reloads the app module.
    """
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
    """Seed two accounts + default settings. Relies on conftest.clean_tables autouse."""
    import db as db_mod
    for name, login in (("acc-01", 10001), ("acc-02", 10002)):
        await db_mod.upsert_account_if_missing(
            name=name, server="TestServer", login=login, password_env="",
            risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
            max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
        )
        await db_mod.upsert_account_settings_if_missing(account_name=name)
    return ["acc-01", "acc-02"]


@pytest_asyncio.fixture
async def seeded_account(seeded_accounts):
    return seeded_accounts[0]


@pytest_asyncio.fixture
async def wired_dashboard(app, seeded_accounts, db_pool):
    """Wire a stub executor + live SettingsStore into dashboard module-globals."""
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
    """AsyncClient with a valid session cookie (logs in via /login)."""
    transport = ASGITransport(app=wired_dashboard.app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver", follow_redirects=False
    ) as client:
        r = await client.get("/login")
        assert r.status_code == 200, f"/login GET failed: {r.status_code}"
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
        assert m, "csrf_token missing from /login"
        token = m.group(1)
        r = await client.post(
            "/login",
            data={"password": KNOWN_PASSWORD, "csrf_token": token, "next_path": "/overview"},
        )
        assert r.status_code == 303, f"login failed: {r.status_code} {r.text[:200]}"
        yield client


# ─── Tests ───────────────────────────────────────────────────────────────


async def test_settings_get_renders_tabs_per_account(authenticated_client, seeded_accounts):
    """GET /settings returns HTML with one Basecoat tab per account."""
    r = await authenticated_client.get("/settings")
    assert r.status_code == 200
    assert 'role="tablist"' in r.text
    for name in seeded_accounts:
        assert name in r.text


async def test_post_rejects_without_htmx_header(authenticated_client, seeded_account):
    """D-31: non-HTMX POST returns 403 (CSRF failure)."""
    r = await authenticated_client.post(
        f"/settings/{seeded_account}",
        data={"risk_mode": "percent", "risk_value": "1.0",
              "max_stages": "1", "default_sl_pips": "100", "max_daily_trades": "30"},
    )
    assert r.status_code == 403


async def test_post_hard_cap_risk_value_percent_over_5(authenticated_client, seeded_account):
    """D-29: percent risk_value > 5.0 rejected 422 with field error."""
    r = await authenticated_client.post(
        f"/settings/{seeded_account}",
        data={"risk_mode": "percent", "risk_value": "6.5",
              "max_stages": "5", "default_sl_pips": "50", "max_daily_trades": "10"},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 422
    assert "between 0 and 5.0" in r.text


async def test_post_hard_cap_max_stages_over_10(authenticated_client, seeded_account):
    """D-29: max_stages > 10 rejected."""
    r = await authenticated_client.post(
        f"/settings/{seeded_account}",
        data={"risk_mode": "percent", "risk_value": "1.0",
              "max_stages": "15", "default_sl_pips": "50", "max_daily_trades": "10"},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 422
    assert "max_stages" in r.text
    assert "between 1 and 10" in r.text


async def test_post_hard_cap_default_sl_pips_over_500(authenticated_client, seeded_account):
    """D-29: default_sl_pips > 500 rejected."""
    r = await authenticated_client.post(
        f"/settings/{seeded_account}",
        data={"risk_mode": "percent", "risk_value": "1.0",
              "max_stages": "5", "default_sl_pips": "999", "max_daily_trades": "10"},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 422
    assert "default_sl_pips" in r.text


async def test_post_valid_renders_modal(authenticated_client, seeded_account):
    """D-27: valid change returns modal HTML with diff + dry-run + Confirm button."""
    r = await authenticated_client.post(
        f"/settings/{seeded_account}",
        data={"risk_mode": "percent", "risk_value": "2.5",
              "max_stages": "3", "default_sl_pips": "75", "max_daily_trades": "15"},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200, r.text[:400]
    assert 'role="dialog"' in r.text
    assert "Confirm change" in r.text
    assert "Discard changes" in r.text
    assert "Effect on a typical signal" in r.text
    assert "applies to signals received AFTER you confirm" in r.text
    # Regression: the Basecoat .dialog component class applies opacity-0 unless the
    # element has [open] / :popover-open. Using it on a plain <div> made the modal
    # invisible while still trapping pointer events — every click was swallowed by
    # the transparent backdrop, freezing the page. The overlay must use plain
    # Tailwind utilities so it actually renders.
    modal_open_tag = re.search(r'<div[^>]*role="dialog"[^>]*>', r.text)
    assert modal_open_tag is not None, "modal opening tag not found"
    classes = re.search(r'class="([^"]*)"', modal_open_tag.group(0))
    assert classes is not None, "modal has no class attribute"
    class_list = classes.group(1).split()
    assert "dialog" not in class_list, (
        "modal must not use the Basecoat .dialog class — it applies opacity-0 "
        "without an [open] attribute, making the modal invisible while the "
        "backdrop still traps clicks"
    )


async def test_post_no_change_bounces_quietly(authenticated_client, seeded_account):
    """No diff vs current effective settings → light message, no modal."""
    # Defaults from upsert_account_settings_if_missing: percent/1.0/1/100/30
    r = await authenticated_client.post(
        f"/settings/{seeded_account}",
        data={"risk_mode": "percent", "risk_value": "1.0",
              "max_stages": "1", "default_sl_pips": "100", "max_daily_trades": "30"},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200
    assert "No changes to save" in r.text
    assert 'role="dialog"' not in r.text


async def test_confirm_writes_audit_row(authenticated_client, seeded_account):
    """D-27: /confirm path writes settings + audit row via SettingsStore.update."""
    import db as db_mod
    rows_before = await db_mod.get_settings_audit(seeded_account)
    assert rows_before == []

    r = await authenticated_client.post(
        f"/settings/{seeded_account}/confirm",
        data={"risk_mode": "percent", "risk_value": "2.5",
              "max_stages": "3", "default_sl_pips": "75", "max_daily_trades": "15"},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200, r.text[:400]

    rows_after = await db_mod.get_settings_audit(seeded_account)
    changed_fields = {row["field"] for row in rows_after}
    # Four fields changed vs defaults (risk_mode matched)
    assert changed_fields == {"risk_value", "max_stages", "default_sl_pips", "max_daily_trades"}


async def test_confirm_fixed_lot_mode_persists(authenticated_client, seeded_account):
    """Verify switching to fixed_lot mode and setting a small lot size persists correctly."""
    import db as db_mod

    r = await authenticated_client.post(
        f"/settings/{seeded_account}/confirm",
        data={"risk_mode": "fixed_lot", "risk_value": "0.05",
              "max_stages": "1", "default_sl_pips": "100", "max_daily_trades": "30"},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200, r.text[:400]
    assert 'id="modal-root"' in r.text, "Modal should be cleared via OOB swap"

    settings = await db_mod.get_account_settings(seeded_account)
    assert settings["risk_mode"] == "fixed_lot", "risk_mode should persist as fixed_lot"
    assert float(settings["risk_value"]) == 0.05, "risk_value should persist as 0.05"

    audit = await db_mod.get_settings_audit(seeded_account)
    audit_fields = {row["field"] for row in audit}
    assert "risk_mode" in audit_fields, "risk_mode change should be audited"
    assert "risk_value" in audit_fields, "risk_value change should be audited"


async def test_settings_renders_with_space_in_account_name(
    authenticated_client, wired_dashboard, db_pool,
):
    """Regression: account names with spaces (e.g. "Vantage Demo-10k") must produce
    CSS-selector-safe ids. Verifies the tab id, data-tab-target, and the confirm
    modal's hx-target all use a slugified id — not the raw name.
    """
    import db as db_mod
    import importlib

    name = "Vantage Demo-10k"
    await db_mod.upsert_account_if_missing(
        name=name, server="S", login=20001, password_env="",
        risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
        max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
    )
    await db_mod.upsert_account_settings_if_missing(account_name=name)

    # Rebuild the SettingsStore cache + add a connector stub so /settings sees the new account
    store_mod = importlib.import_module("settings_store")
    store = store_mod.SettingsStore(db_pool=db_pool)
    await store.load_all()
    wired_dashboard._executor.tm.settings_store = store
    wired_dashboard._executor.tm.connectors[name] = _StubConnector()

    r = await authenticated_client.get("/settings")
    assert r.status_code == 200
    # Slug of "Vantage Demo-10k" → "Vantage-Demo-10k"
    assert 'id="tab-Vantage-Demo-10k"' in r.text
    assert 'data-tab-target="tab-Vantage-Demo-10k"' in r.text
    # Raw id with space must NOT be present — that would break CSS selectors
    assert 'id="tab-Vantage Demo-10k"' not in r.text

    # Drive the validate step (needs URL-encoded space in path)
    r = await authenticated_client.post(
        "/settings/Vantage%20Demo-10k",
        data={"risk_mode": "fixed_lot", "risk_value": "0.05",
              "max_stages": "1", "default_sl_pips": "100", "max_daily_trades": "30"},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200, r.text[:400]
    # Modal's hx-target must use the slugified id, not the raw name
    assert 'hx-target="#tab-Vantage-Demo-10k .card"' in r.text
    assert 'hx-target="#tab-Vantage Demo-10k .card"' not in r.text


async def test_revert_post_renders_modal_with_inverted_diff(authenticated_client, seeded_account):
    """D-28: /revert produces modal with old/new swapped."""
    import db as db_mod

    # First produce an audit entry by editing risk_value 1.0 → 2.5
    r = await authenticated_client.post(
        f"/settings/{seeded_account}/confirm",
        data={"risk_mode": "percent", "risk_value": "2.5",
              "max_stages": "1", "default_sl_pips": "100", "max_daily_trades": "30"},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200

    audit = await db_mod.get_settings_audit(seeded_account)
    rv = next(a for a in audit if a["field"] == "risk_value")

    r = await authenticated_client.post(
        f"/settings/{seeded_account}/revert?audit_id={rv['id']}",
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200
    assert 'role="dialog"' in r.text
    assert "2.5" in r.text
    assert "1.0" in r.text
    assert "Revert" in r.text


async def test_revert_confirm_writes_new_audit_row(authenticated_client, seeded_account):
    """D-28: the revert itself is audited — a new audit row appears after revert."""
    import db as db_mod

    await authenticated_client.post(
        f"/settings/{seeded_account}/confirm",
        data={"risk_mode": "percent", "risk_value": "2.5",
              "max_stages": "1", "default_sl_pips": "100", "max_daily_trades": "30"},
        headers={"hx-request": "true"},
    )
    rows_after_forward = await db_mod.get_settings_audit(seeded_account)
    forward_count = len(rows_after_forward)

    r = await authenticated_client.post(
        f"/settings/{seeded_account}/confirm",
        data={"risk_mode": "percent", "risk_value": "1.0",
              "max_stages": "1", "default_sl_pips": "100", "max_daily_trades": "30"},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200

    rows_after_revert = await db_mod.get_settings_audit(seeded_account)
    assert len(rows_after_revert) == forward_count + 1
    # Newest row (ORDER BY id DESC) reverts risk_value 2.5 → 1.0
    latest = rows_after_revert[0]
    assert latest["field"] == "risk_value"
    # risk_value is NUMERIC(10,4) → stored-as-TEXT keeps 4 decimals
    assert float(latest["old_value"]) == 2.5
    assert float(latest["new_value"]) == 1.0
