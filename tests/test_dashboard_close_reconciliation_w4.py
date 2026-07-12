"""W4-PNL-DISPLAY §4.6 — dashboard/API full-close P&L reconciliation.

The dashboard/API full-close route (api/actions.py) must NOT finalize a trade
with a placeholder pnl=0.0. Doing so flips status straight to 'closed', which the
history-sync reconciler never rescans (it only considers still-open tickets), so
the authoritative deal.profit is never backfilled — every dashboard-closed trade
shows $0 in /history and corrupts win_rate/profit_factor/net_pnl.

The fix parks the trade in a 'closing' state: still scanned by history-sync,
still excluded from closed analytics/archive aggregates, until the reconciler
overwrites it with the real deal.profit and flips it to 'closed'.

These tests exercise the DB helpers directly plus one end-to-end pass through
executor._sync_history_for_account, proving a mark_trade_closing trade is
reconciled with the broker's real deal profit.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

import db
from executor import Executor
from models import AccountConfig, GlobalConfig
from mt5_connector import Deal, DryRunConnector
from trade_manager import TradeManager

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _insert_open_trade(account_name: str, ticket: int) -> int:
    return await db.log_trade(
        signal_id=None,
        account_name=account_name,
        symbol="XAUUSD",
        direction="buy",
        entry_price=2040.0,
        sl=2030.0,
        tp=2060.0,
        lot_size=0.01,
        ticket=ticket,
        status="opened",
        raw_signal="test",
    )


async def test_mark_trade_closing_parks_status_without_finalizing_pnl(
    db_pool, seeded_account,
):
    """mark_trade_closing sets status='closing' + close_price but leaves pnl
    unfinalized (default 0.0) — it must NOT masquerade as a closed $0 trade."""
    ticket = 770001
    await _insert_open_trade("test-acct", ticket)

    await db.mark_trade_closing(ticket, "test-acct", 2058.0)

    row = await db._pool.fetchrow(
        "SELECT status, pnl, close_price FROM trades WHERE ticket=$1", ticket,
    )
    assert row["status"] == "closing"
    assert float(row["close_price"]) == pytest.approx(2058.0)
    # pnl is NOT finalized here — the reconciler owns the authoritative value.
    assert row["status"] != "closed"


async def test_open_tickets_includes_closing_trades(db_pool, seeded_account):
    """THE §4.6 fix: a 'closing' ticket must still be returned to the
    history-sync loop so its real deal profit can be backfilled. Before the fix
    the query matched only status='opened' and dropped it forever."""
    open_ticket = 770101
    closing_ticket = 770102
    await _insert_open_trade("test-acct", open_ticket)
    await _insert_open_trade("test-acct", closing_ticket)
    await db.mark_trade_closing(closing_ticket, "test-acct", 2058.0)

    tickets = await db.get_open_trade_tickets_for_account("test-acct")
    assert open_ticket in tickets
    assert closing_ticket in tickets  # fails before the fix


async def test_closing_trade_excluded_from_closed_analytics(db_pool, seeded_account):
    """A 'closing' (unreconciled) trade must NOT pollute closed aggregates — it
    is excluded until the reconciler flips it to 'closed' with a real pnl."""
    ticket = 770201
    await _insert_open_trade("test-acct", ticket)
    await db.mark_trade_closing(ticket, "test-acct", 2058.0)

    rows = await db.get_analytics_by_symbol()
    # No closed XAUUSD row yet — the only trade is still 'closing'.
    assert all(r["symbol"] != "XAUUSD" for r in rows)


# ── End-to-end: history-sync reconciles a dashboard-closed trade ─────────────


class _ScriptedConnector(DryRunConnector):
    """Connector returning canned closing deals, staying connected."""

    def __init__(self, *args, scripted_deals=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._scripted_deals: list[Deal] = scripted_deals or []

    async def get_history_deals(self, since, until=None):
        until_ts = (until or datetime.now(timezone.utc)).timestamp()
        return [
            d for d in self._scripted_deals
            if since.timestamp() <= d.time <= until_ts
        ]


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


async def test_dashboard_closed_trade_is_reconciled_by_history_sync(
    db_pool, seeded_account, scripted_connector, executor_fixture,
):
    """A trade marked 'closing' by the dashboard close route is picked up by
    history-sync and finalized with the broker's real deal.profit — NOT $0."""
    ticket = 770301
    await _insert_open_trade("test-acct", ticket)
    # Dashboard/API full close parks it as 'closing' (placeholder close price).
    await db.mark_trade_closing(ticket, "test-acct", 2050.0)

    deal_time = (datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp()
    scripted_connector._scripted_deals = [
        Deal(
            ticket=999301, position_id=ticket, time=deal_time,
            entry=1,  # DEAL_ENTRY_OUT — closing leg
            volume=0.01, price=2058.5, profit=18.5,
            symbol="XAUUSD",
        ),
    ]

    await executor_fixture._sync_history_for_account(
        "test-acct", scripted_connector, lookback_hours=24,
    )

    row = await db._pool.fetchrow(
        "SELECT status, pnl, close_price FROM trades WHERE ticket=$1", ticket,
    )
    assert row["status"] == "closed"
    assert float(row["pnl"]) == pytest.approx(18.5)  # real profit, not 0.0
    assert float(row["close_price"]) == pytest.approx(2058.5)  # authoritative price
