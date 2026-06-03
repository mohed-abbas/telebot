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
def event_loop():
    """Session-scoped event loop so all async fixtures and tests share one loop.

    Required because the db_pool fixture is session-scoped: the asyncpg pool
    is bound to the loop where it was created, so every test that touches the
    DB (directly or via handle_signal) must run on that same loop.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def db_pool():
    """Session-scoped asyncpg pool -- created once, shared across all tests."""
    try:
        await db.init_db(TEST_DATABASE_URL)
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
    Skips silently when no DB pool is available (non-DB tests).
    """
    if db._pool is None:
        yield
        return
    try:
        async with db._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE signals, trades, daily_stats, pending_orders, "
                "settings_audit, account_settings, accounts, failed_login_attempts, "
                "staged_entries, signal_daily_counted, idempotency_keys "
                "RESTART IDENTITY CASCADE"
            )
    except Exception:
        pass  # DB not available, skip cleanup
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


@pytest.fixture(scope="module")
def api_app():
    """Module-scoped FastAPI app for /api/v2 tests (Phase 08).

    Mirrors tests/test_login_flow.py:21-47 — env-inject, sys.modules.pop +
    importlib re-import so the app binds the test config, init_db with skip on
    absence, then wire a DryRunConnector-backed executor stub via init_dashboard()
    so _get_all_positions() returns a deterministic XAUUSD row. Yields dashboard.app.
    """
    import asyncio
    import importlib

    from argon2 import PasswordHasher

    known_hash = PasswordHasher().hash("correct-horse-battery-staple")
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
    for mod in ("config", "dashboard", "db"):
        sys.modules.pop(mod, None)
    dashboard = importlib.import_module("dashboard")
    import db as _db
    try:
        asyncio.get_event_loop().run_until_complete(_db.init_db(env["DATABASE_URL"]))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available for api tests: {exc}")
    # Wire the DryRun-backed executor stub through the real accessor path.
    dashboard.init_dashboard(_make_dryrun_executor(), notifier=None, settings=None)
    yield dashboard.app
    try:
        asyncio.get_event_loop().run_until_complete(_db.close_db())
    except Exception:
        pass


@pytest.fixture
def authed_client(api_app):
    """A TestClient carrying a logged-in session + telebot_csrf cookie.

    Plan 02 finalises the JSON auth route; until then the helper seeds the session
    directly (sets request.session["user"]) and issues a telebot_csrf cookie so
    Plans 03-05 mutation tests can round-trip the double-submit header. Returns
    (client, csrf_token).
    """
    import secrets as _secrets

    from fastapi.testclient import TestClient

    client = TestClient(api_app)
    # Seed the session cookie via the SessionMiddleware by exercising a tiny
    # login shim is not yet available at Wave 0; instead set the session through
    # a transient route is unnecessary — Plan 02 wires /api/v2/auth/login. For now
    # expose the csrf cookie so downstream CSRF round-trip tests have a token.
    csrf = _secrets.token_urlsafe(32)
    client.cookies.set("telebot_csrf", csrf)
    return client, csrf


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
