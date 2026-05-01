"""Regression tests for executor._history_sync_loop reconciliation.

Verifies the bot picks up broker-side position closes (SL/TP hits, manual
closes in MT5) and updates trades.status / pnl accordingly — the path that
makes /analytics + /history P&L work for non-bot-initiated closes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

import db
from executor import Executor
from models import AccountConfig, GlobalConfig
from mt5_connector import Deal, DryRunConnector, Position
from trade_manager import TradeManager

pytestmark = pytest.mark.asyncio(loop_scope="session")


class _ScriptedConnector(DryRunConnector):
    """Connector that returns a canned history-deals list and stays connected."""

    def __init__(self, *args, scripted_deals=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._scripted_deals: list[Deal] = scripted_deals or []
        self._calls: list[tuple[datetime, datetime | None]] = []

    async def get_history_deals(self, since, until=None):
        self._calls.append((since, until))
        # Filter to scripted deals whose time falls within the window.
        until_ts = (until or datetime.now(timezone.utc)).timestamp()
        return [d for d in self._scripted_deals if since.timestamp() <= d.time <= until_ts]


@pytest_asyncio.fixture
async def scripted_connector():
    c = _ScriptedConnector("test-acct", "TestServer", 99999, "pass")
    await c.connect()
    yield c
    await c.disconnect()


@pytest_asyncio.fixture
async def executor_fixture(db_pool, seeded_account, scripted_connector):
    cfg = GlobalConfig()
    acct = AccountConfig(
        name="test-acct", server="TestServer", login=99999, password_env="",
        risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
        max_open_trades=3, enabled=True,
    )
    tm = TradeManager(
        connectors={"test-acct": scripted_connector},
        accounts=[acct],
        global_config=cfg,
    )
    return Executor(trade_manager=tm, global_config=cfg, notifier=None)


async def _insert_open_trade(account_name: str, ticket: int, symbol: str = "XAUUSD") -> int:
    """Insert one row in trades with status='opened' and ticket set."""
    return await db.log_trade(
        signal_id=None,
        account_name=account_name,
        symbol=symbol,
        direction="buy",
        entry_price=2040.0,
        sl=2030.0, tp=2060.0,
        lot_size=0.01,
        ticket=ticket,
        status="opened",
        raw_signal="test",
    )


async def test_history_sync_closes_trade_when_broker_reports_close(
    db_pool, seeded_account, scripted_connector, executor_fixture,
):
    """Closing deal (entry=1) for a known ticket → trade flips to closed
    with the deal's pnl + price."""
    ticket = 555001
    await _insert_open_trade("test-acct", ticket)
    deal_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()
    scripted_connector._scripted_deals = [
        Deal(
            ticket=999000, position_id=ticket, time=deal_time,
            entry=1,  # DEAL_ENTRY_OUT — closing leg
            volume=0.01, price=2058.0, profit=18.0,
            symbol="XAUUSD",
        ),
    ]

    await executor_fixture._sync_history_for_account(
        "test-acct", scripted_connector, lookback_hours=24,
    )

    rows = await db._pool.fetch(
        "SELECT status, pnl, close_price FROM trades WHERE ticket=$1",
        ticket,
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "closed"
    assert float(rows[0]["pnl"]) == pytest.approx(18.0)
    assert float(rows[0]["close_price"]) == pytest.approx(2058.0)


async def test_history_sync_ignores_opening_deals(
    db_pool, seeded_account, scripted_connector, executor_fixture,
):
    """entry=0 (DEAL_ENTRY_IN, opening leg) must NOT close the trade."""
    ticket = 555101
    await _insert_open_trade("test-acct", ticket)
    deal_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()
    scripted_connector._scripted_deals = [
        Deal(
            ticket=999100, position_id=ticket, time=deal_time,
            entry=0,  # OPENING leg — should be skipped
            volume=0.01, price=2040.0, profit=0.0,
            symbol="XAUUSD",
        ),
    ]

    await executor_fixture._sync_history_for_account(
        "test-acct", scripted_connector, lookback_hours=24,
    )

    row = await db._pool.fetchrow(
        "SELECT status FROM trades WHERE ticket=$1", ticket,
    )
    assert row["status"] == "opened"


async def test_history_sync_ignores_unknown_position_ids(
    db_pool, seeded_account, scripted_connector, executor_fixture,
):
    """A deal whose position_id we don't know about (manual broker trade)
    must not affect any of our trades."""
    our_ticket = 555201
    await _insert_open_trade("test-acct", our_ticket)
    deal_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()
    scripted_connector._scripted_deals = [
        Deal(
            ticket=999200, position_id=12345678, time=deal_time,  # not ours
            entry=1, volume=0.01, price=2058.0, profit=18.0,
            symbol="XAUUSD",
        ),
    ]

    await executor_fixture._sync_history_for_account(
        "test-acct", scripted_connector, lookback_hours=24,
    )

    row = await db._pool.fetchrow(
        "SELECT status FROM trades WHERE ticket=$1", our_ticket,
    )
    assert row["status"] == "opened"


async def test_history_sync_advances_watermark_past_processed_deal(
    db_pool, seeded_account, scripted_connector, executor_fixture,
):
    """After processing a deal, the per-account watermark advances past
    that deal's time so the next iteration doesn't re-process it."""
    ticket = 555301
    await _insert_open_trade("test-acct", ticket)
    deal_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()
    scripted_connector._scripted_deals = [
        Deal(
            ticket=999300, position_id=ticket, time=deal_time,
            entry=1, volume=0.01, price=2058.0, profit=18.0,
            symbol="XAUUSD",
        ),
    ]

    await executor_fixture._sync_history_for_account(
        "test-acct", scripted_connector, lookback_hours=24,
    )

    watermark = executor_fixture._last_history_sync["test-acct"]
    assert watermark.timestamp() > deal_time
