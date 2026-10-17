"""Shared test fixtures for telebot test suite."""
import asyncio
import os
import sys
import pytest
import pytest_asyncio

# Add project root to path so tests can import project modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
from models import AccountConfig, Direction, GlobalConfig, SignalAction, SignalType
from mt5_connector import DryRunConnector, OrderResult, OrderType

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://telebot:telebot_dev@localhost:5433/telebot",
)


@pytest.fixture(scope="session")
async def db_pool():
    """Session-scoped asyncpg pool -- created once, shared across all tests."""
    try:
        await db.init_db(TEST_DATABASE_URL)
        # idempotency_keys is created by the dashboard lifespan, not
        # db.init_db. clean_tables truncates it, so without it that TRUNCATE
        # fails (silently) and no table is ever cleaned between tests.
        from api.idempotency import ensure_table
        await ensure_table()
    except Exception as exc:
        pytest.skip(
            f"PostgreSQL not available at {TEST_DATABASE_URL}: {exc}\n"
            "Start it with: docker compose -f docker-compose.dev.yml up -d"
        )
    yield db._pool
    await db.close_db()


@pytest.fixture(autouse=True)
async def clean_tables():
    """Truncate all tables between tests for isolation.

    No-op when no pool exists (DB-free tests). Any other failure is raised:
    a silent TRUNCATE failure once hid the fact that no table was ever cleaned.
    """
    if db._pool is None:
        yield
        return
    async with db._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE signals, trades, daily_stats, pending_orders, "
            "settings_audit, account_settings, accounts, failed_login_attempts, "
            "staged_entries, signal_daily_counted, idempotency_keys "
            "RESTART IDENTITY CASCADE"
        )
    yield


# ─── Phase 08 (JSON API) shared fixtures ─────────────────────────────────────


def _make_dryrun_executor():
    """Build a lightweight executor stub backed by a DryRunConnector.

    Mirrors only the surface dashboard._get_all_positions / _get_accounts_overview
    reach: `executor.tm.connectors` (name->connector), `executor.tm.accounts`
    (name->AccountConfig), and `executor.cfg.max_daily_trades_per_account`. A real
    Executor is not needed at Wave 0 — Plans 02-05 add route handlers that read
    these via api/deps.get_executor(). Injects one deterministic XAUUSD position so
    the positions/formatting routes have a stable row without a live MT5 bridge.
    """
    import types

    from mt5_connector import Position as MT5Position

    conn = DryRunConnector("Vantage Demo-10k", "TestServer", 12345, "pass")
    conn._connected = True  # connected without awaiting connect() (no MT5 bridge)
    # Deterministic XAUUSD position (drives the formatting assertions).
    conn._fake_positions = {
        100001: MT5Position(
            ticket=100001, symbol="XAUUSD", direction="buy", volume=0.30,
            open_price=2800.123, sl=2790.0, tp=2820.0, profit=12.5,
        )
    }
    # Static price so get_positions' P&L recompute stays deterministic.
    conn.set_simulated_price("XAUUSD", 2805.0, 2805.2)

    acct = AccountConfig(
        name="Vantage Demo-10k", server="TestServer", login=12345,
        password_env="TEST_PASS", risk_percent=1.0, max_lot_size=1.0,
        max_daily_loss_percent=3.0, max_open_trades=3, enabled=True,
    )

    tm = types.SimpleNamespace(
        connectors={"Vantage Demo-10k": conn},
        accounts={"Vantage Demo-10k": acct},
    )
    cfg = types.SimpleNamespace(max_daily_trades_per_account=30)
    return types.SimpleNamespace(tm=tm, cfg=cfg)


API_PASSWORD = "correct-horse-battery-staple"
"""Dashboard password the `api_app` fixture is configured with."""


@pytest.fixture(scope="module")
def api_app(db_pool):
    """Module-scoped FastAPI app for /api/v2 tests.

    Env-inject then re-import `config` + `dashboard` so the app binds the test
    config, and wire a DryRunConnector-backed executor stub via init_dashboard()
    so _get_all_positions() returns a deterministic XAUUSD row.

    The app uses the SESSION-scoped `db_pool` (one asyncpg pool on the session
    loop). `db` is deliberately NOT re-imported: a second `db` module with its
    own pool is what used to split the pool across event loops. Drive the app
    with the `api_client` fixture (httpx on the session loop), not TestClient —
    TestClient runs handlers on a separate thread/loop, which asyncpg rejects.
    """
    import importlib

    from argon2 import PasswordHasher

    env = {
        "TG_API_ID": "1", "TG_API_HASH": "x", "TG_SESSION": "x", "TG_CHAT_IDS": "-1",
        "DISCORD_WEBHOOK_URL": "https://example", "TIMEZONE": "UTC",
        "DATABASE_URL": TEST_DATABASE_URL,
        "DASHBOARD_PASS_HASH": PasswordHasher().hash(API_PASSWORD),
        "SESSION_SECRET": "A" * 48,
        "SESSION_COOKIE_SECURE": "false",
    }
    for key in ("DASHBOARD_USER", "DASHBOARD_PASS"):
        os.environ.pop(key, None)
    os.environ.update(env)
    for mod in ("config", "dashboard"):
        sys.modules.pop(mod, None)
    dashboard = importlib.import_module("dashboard")
    dashboard.init_dashboard(_make_dryrun_executor(), notifier=None, settings=None)
    return dashboard.app


def make_api_client(app, client_ip: str = "127.0.0.1"):
    """An httpx AsyncClient driving `app` in-process on the CURRENT event loop.

    `client_ip` is what `request.client.host` (and so `_client_ip` without
    TRUST_PROXY) sees — use distinct values to exercise per-IP logic.
    """
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app, client=(client_ip, 12345))
    return AsyncClient(
        transport=transport, base_url="http://testserver", follow_redirects=False,
    )


@pytest_asyncio.fixture
async def api_client(api_app):
    """Unauthenticated httpx client over `api_app`, sharing the session loop."""
    async with make_api_client(api_app) as c:
        yield c


async def api_login(client, password: str = API_PASSWORD) -> str:
    """Drive the real JSON login (GET /auth/csrf, POST /auth/login) on `client`.

    Returns the post-login telebot_csrf token to echo as X-CSRF-Token.
    """
    r = await client.get("/api/v2/auth/csrf")
    assert r.status_code == 200, r.text
    token = r.json()["csrf_token"]
    r = await client.post(
        "/api/v2/auth/login", json={"password": password, "csrf_token": token},
    )
    assert r.status_code == 200, r.text
    assert "telebot_session" in client.cookies
    return client.cookies.get("telebot_csrf")


@pytest_asyncio.fixture
async def session_client(api_app):
    """httpx client carrying a real logged-in session; yields (client, csrf)."""
    async with make_api_client(api_app) as c:
        token = await api_login(c)
        yield c, token


# Minimal SPA shell — the `id="root"` div is the React mount point asserted on.
_STUB_INDEX_HTML = (
    "<!doctype html><html><head><title>spa</title></head>"
    '<body><div id="root"></div></body></html>'
)


@pytest.fixture(scope="module")
def spa_index():
    """Ensure static/app/index.html exists so the /app mount has a shell to serve.

    Writes a stub into the repo's static/app/ if absent (the real one comes from
    `cd frontend && npm run build`). Leaves a pre-existing real bundle untouched
    and only removes a stub it created itself.
    """
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent / "static" / "app"
    index = app_dir / "index.html"
    created_dir = not app_dir.exists()
    created_file = not index.exists()
    if created_file:
        app_dir.mkdir(parents=True, exist_ok=True)
        index.write_text(_STUB_INDEX_HTML, encoding="utf-8")

    yield index

    if created_file and index.exists():
        index.unlink()
    if created_dir and app_dir.exists():
        try:
            app_dir.rmdir()
        except OSError:
            pass  # non-empty (a real build landed) — leave it alone


@pytest_asyncio.fixture
async def seeded_account(db_pool):
    """Seeds one test account + default settings; rolled back by clean_tables."""
    await db.upsert_account_if_missing(
        name="test-acct", server="Test", login=99999, password_env="",
        risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
        max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
    )
    await db.upsert_account_settings_if_missing(account_name="test-acct")
    return "test-acct"


@pytest_asyncio.fixture
async def seeded_signal(db_pool):
    """Insert one signals row (FK target for staged_entries); returns the id.

    Promoted from tests/test_staged_db.py (Plan 01 local fixture) to conftest
    so Phase 6 Plan 02 test files (test_staged_executor, test_staged_safety_hooks,
    test_staged_attribution) can share it — Rule 3 deviation, blocking otherwise.
    """
    async with db._pool.acquire() as conn:
        sid = await conn.fetchval(
            """INSERT INTO signals (raw_text, signal_type, symbol, direction, action_taken)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            "test signal", "open_text_only", "XAUUSD", "buy", "staged",
        )
    return sid


@pytest_asyncio.fixture
async def seeded_staged_account(db_pool, seeded_account):
    """seeded_account with max_stages=5 + default_sl_pips=100 suitable for band tests."""
    await db.update_account_setting("test-acct", "max_stages", 5, actor="test")
    await db.update_account_setting("test-acct", "default_sl_pips", 100, actor="test")
    return seeded_account


@pytest.fixture
def global_config():
    """Trading config with zero jitter/delay for deterministic tests."""
    return GlobalConfig(
        default_target_tp=2,
        limit_order_expiry_minutes=30,
        max_daily_trades_per_account=30,
        max_daily_server_messages=500,
        stagger_delay_min=0,
        stagger_delay_max=0,
        lot_jitter_percent=0,
        sl_tp_jitter_points=0,
    )


@pytest.fixture
def account():
    return AccountConfig(
        name="test-acct",
        server="TestServer",
        login=12345,
        password_env="TEST_PASS",
        risk_percent=1.0,
        max_lot_size=1.0,
        max_daily_loss_percent=3.0,
        max_open_trades=3,
        enabled=True,
    )


# ── Phase 6/13 staged-entry integration fixtures (promoted from
# test_staged_executor.py so test_trade_manager.py can share them — mirrors the
# Plan 01 seeded_signal promotion; Rule 3 deviation, blocking otherwise) ──────


class _PricedDry(DryRunConnector):
    """DryRunConnector with a settable price book for at-arrival band tests."""

    def __init__(self, *args, prices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._prices = prices or {"XAUUSD": (2040.1, 2040.2)}

    async def get_price(self, symbol):
        return self._prices.get(symbol)


@pytest_asyncio.fixture
async def priced_connector():
    c = _PricedDry("test-acct", "TestServer", 99999, "pass")
    await c.connect()
    yield c
    await c.disconnect()


@pytest_asyncio.fixture
async def tm_with_store(db_pool, seeded_staged_account, priced_connector, global_config):
    """TradeManager with SettingsStore + SignalCorrelator attached — Phase 6-ready."""
    from settings_store import SettingsStore
    from signal_correlator import SignalCorrelator
    from trade_manager import TradeManager

    store = SettingsStore(db._pool)
    await store.load_all()
    acct = AccountConfig(
        name="test-acct", server="TestServer", login=99999, password_env="",
        risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
        max_open_trades=5, enabled=True,
    )
    t = TradeManager(
        connectors={"test-acct": priced_connector},
        accounts=[acct],
        global_config=global_config,
    )
    t.settings_store = store
    t.correlator = SignalCorrelator(window_seconds=600)
    return t


@pytest.fixture
async def connector():
    """A connected DryRunConnector for testing."""
    c = DryRunConnector("test-acct", "TestServer", 12345, "pass")
    await c.connect()
    yield c
    await c.disconnect()


@pytest.fixture
def make_signal():
    """Factory fixture for creating test signals."""
    def _make(
        direction=Direction.SELL,
        entry_zone=(4978.0, 4982.0),
        sl=4986.0,
        tps=None,
        target_tp=4973.0,
        signal_type=SignalType.OPEN,
        symbol="XAUUSD",
        raw_text="test signal",
    ):
        if tps is None:
            tps = [4975.0, 4973.0]
        return SignalAction(
            type=signal_type, symbol=symbol, raw_text=raw_text,
            direction=direction, entry_zone=entry_zone, sl=sl,
            tps=tps, target_tp=target_tp,
        )
    return _make
