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
                "staged_entries, signal_daily_counted "
                "RESTART IDENTITY CASCADE"
            )
    except Exception:
        pass  # DB not available, skip cleanup
    yield


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
