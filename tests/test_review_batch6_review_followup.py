"""Batch 6 — fixes for the 2026-10-17 /code-review of batch 5.

  A  startup/reconnect reconcile judges stage-1 rows before their bands
  B  an unverifiable stage-1 state never allows a fire
  C  close-by deals (entry 3) are reconciled like plain closes
     (batch 7: entry 2 / reversal is no longer a close — tests updated)
  D  'closing' rows waiting on an unreadable history are reported once per outage
  E  maintenance pass order (asserted in the batch-3 test)
  F  one history read per account per cleanup; one pending-orders query per tick
     (batch 7: close_time is the reconcile time again, not the broker-clock
     deal time — tests updated)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

import db
from executor import Executor
from mt5_connector import ConnectorReadError, Deal, Position

pytestmark = pytest.mark.asyncio(loop_scope="session")

ACCT = "test-acct"


@pytest_asyncio.fixture
async def executor(tm_with_store, global_config):
    return Executor(trade_manager=tm_with_store, global_config=global_config, notifier=None)


async def _insert_stage(
    *, signal_id: int, stage_number: int, status: str = "awaiting_zone",
    band_low: float = 2040.0, band_high: float = 2042.5,
    mt5_ticket: int | None = None, firing_minutes_ago: int | None = None,
    created_minutes_ago: int = 0,
) -> int:
    snapshot = {
        "account_name": ACCT, "risk_mode": "fixed_lot", "risk_value": 0.5,
        "max_stages": 5, "default_sl_pips": 100, "max_daily_trades": 30,
        "max_open_trades": 5, "max_lot_size": 1.0,
    }
    async with db._pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO staged_entries
               (signal_id, stage_number, account_name, symbol, direction,
                zone_low, zone_high, band_low, band_high, target_lot,
                snapshot_settings, mt5_comment, mt5_ticket, status, firing_at, created_at)
               VALUES ($1,$2,$3,'XAUUSD','buy',$4,$5,$4,$5,0.1,$6::jsonb,$7,$8,$9,
                       CASE WHEN $10::int IS NULL THEN NULL
                            ELSE NOW() - make_interval(mins => $10) END,
                       NOW() - make_interval(mins => $11))
               RETURNING id""",
            signal_id, stage_number, ACCT, band_low, band_high, json.dumps(snapshot),
            f"telebot-{signal_id}-s{stage_number}", mt5_ticket, status,
            firing_minutes_ago, created_minutes_ago,
        )


async def _stage(row_id: int) -> dict:
    async with db._pool.acquire() as conn:
        return dict(await conn.fetchrow("SELECT * FROM staged_entries WHERE id=$1", row_id))


async def _insert_trade(ticket: int, status: str = "opened") -> int:
    return await db.log_trade(
        signal_id=None, account_name=ACCT, symbol="XAUUSD", direction="buy",
        entry_price=2040.0, sl=2030.0, tp=2060.0, lot_size=0.1,
        ticket=ticket, status=status, raw_signal="test",
    )


async def _trade(ticket: int) -> dict:
    async with db._pool.acquire() as conn:
        return dict(await conn.fetchrow(
            "SELECT * FROM trades WHERE ticket=$1 AND account_name=$2", ticket, ACCT,
        ))


async def _insert_expired_order(ticket: int) -> int:
    expires = datetime.now(timezone.utc) - timedelta(minutes=5)
    return await db.log_pending_order(
        None, ACCT, ticket, "XAUUSD", "buy_limit", 0.1, 2035.0, 2025.0, 2060.0, expires,
    )


def _deal(position_id: int, *, entry: int, profit: float, price: float, minutes_ago: int) -> Deal:
    t = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).timestamp()
    return Deal(ticket=position_id + 1, position_id=position_id, time=t, entry=entry,
                volume=0.1, price=price, profit=profit)


def _history(connector, deals, counter: dict | None = None) -> None:
    connector.supports_history_sync = True

    async def get_history_deals(since, until=None):
        if counter is not None:
            counter["n"] += 1
        if isinstance(deals, Exception):
            raise deals
        return list(deals)

    connector.get_history_deals = get_history_deals


async def _park_closing(ticket: int, *, estimate: float, minutes_ago: int) -> None:
    await _insert_trade(ticket)
    assert await db.mark_trade_closing(ticket, ACCT, 2805.0, pnl_estimate=estimate) is True
    async with db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE trades SET close_time = NOW() - make_interval(mins => $2) WHERE ticket=$1",
            ticket, minutes_ago,
        )


# ── A ──────────────────────────────────────────────────────────────────


async def test_startup_reconcile_judges_stage1_before_its_bands(
    db_pool, seeded_signal, priced_connector, executor,
):
    sid = seeded_signal
    # Stage 1 is the OLDEST row (newest-first fetch puts it last); it died mid-fire.
    s1 = await _insert_stage(signal_id=sid, stage_number=1, status="firing",
                             firing_minutes_ago=3, created_minutes_ago=3)
    s2 = await _insert_stage(signal_id=sid, stage_number=2, created_minutes_ago=2)
    s3 = await _insert_stage(signal_id=sid, stage_number=3, created_minutes_ago=1,
                             band_low=2030.0, band_high=2032.0)

    await executor._sync_positions(ACCT, priced_connector, startup=True)

    assert (await _stage(s1))["status"] == "failed"
    for row_id in (s2, s3):
        row = await _stage(row_id)
        assert row["status"] == "cancelled_stage1_closed"
        assert row["cancelled_reason"] == "stage1_failed_at_startup"


# ── B ──────────────────────────────────────────────────────────────────


async def test_unverifiable_stage1_never_allows_a_fire(
    db_pool, seeded_signal, priced_connector, executor, monkeypatch,
):
    sid = seeded_signal
    # Stage 1 filled in the DB, no longer on MT5: the fire MUST be refused —
    # but the lookup that would reveal this fails.
    await _insert_stage(signal_id=sid, stage_number=1, status="filled", mt5_ticket=701)
    s2 = await _insert_stage(signal_id=sid, stage_number=2)  # in zone at 2040.1/2040.2

    async def boom(*args, **kwargs):
        raise RuntimeError("pool exhausted")

    monkeypatch.setattr(db, "get_stage_by_signal_account", boom)

    await executor._zone_watch_tick()

    assert (await _stage(s2))["status"] == "awaiting_zone", "kept for the next tick, not cancelled"
    assert priced_connector._fake_positions == {}, "and definitely not fired"

    # The reconnect reconcile keeps the band too (no age-abandon on a DB hiccup).
    async with db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE staged_entries SET created_at = NOW() - make_interval(mins => 120) WHERE id=$1", s2,
        )
    await executor._sync_positions(ACCT, priced_connector)
    assert (await _stage(s2))["status"] == "awaiting_zone"


# ── C ──────────────────────────────────────────────────────────────────


async def test_history_sync_reconciles_close_by_deals(
    db_pool, seeded_account, priced_connector, executor,
):
    ticket = 610003
    await _park_closing(ticket, estimate=4.0, minutes_ago=20)
    _history(priced_connector, [_deal(ticket, entry=3, profit=9.0, price=2812.0, minutes_ago=15)])

    await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)

    row = await _trade(ticket)
    assert row["status"] == "closed"
    assert float(row["pnl"]) == pytest.approx(9.0), "broker P&L, not the estimate"
    # Batch 7: the deal's time is broker-clock time — close_time is set on our clock.
    age = datetime.now(timezone.utc) - row["close_time"]
    assert age < timedelta(minutes=1)


async def test_expiry_probe_accepts_a_close_by_deal(
    db_pool, seeded_account, tm_with_store, priced_connector,
):
    ticket = 620001
    await _insert_trade(ticket, status="pending")
    await _insert_expired_order(ticket)
    _history(priced_connector, [_deal(ticket, entry=3, profit=-3.0, price=2799.0, minutes_ago=30)])

    results = await tm_with_store.cleanup_expired_orders()

    assert [r["status"] for r in results] == ["filled_closed"]
    row = await _trade(ticket)
    assert row["status"] == "closed"
    assert float(row["pnl"]) == pytest.approx(-3.0)


# ── D ──────────────────────────────────────────────────────────────────


async def test_closing_rows_blocked_by_dead_history_are_reported_once(
    db_pool, seeded_account, priced_connector, executor, caplog,
):
    ticket = 630001
    await _park_closing(ticket, estimate=4.0, minutes_ago=20)
    _history(priced_connector, ConnectorReadError(f"{ACCT}: history read failed"))

    with caplog.at_level(logging.ERROR, logger="executor"):
        await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)
        await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)
    stuck = [r for r in caplog.records if "stuck in 'closing'" in r.getMessage()]
    assert len(stuck) == 1
    assert str(ticket) in stuck[0].getMessage()
    assert (await _trade(ticket))["status"] == "closing"

    # Bridge recovers: the warning re-arms for a future outage and the row finalizes.
    _history(priced_connector, [])
    await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)
    assert ACCT not in executor._history_blocked_warned
    assert (await _trade(ticket))["status"] == "closed"


async def test_no_report_when_no_closing_rows_are_waiting(
    db_pool, seeded_account, priced_connector, executor, caplog,
):
    await _insert_trade(630002)  # plain open trade, nothing 'closing'
    _history(priced_connector, ConnectorReadError(f"{ACCT}: history read failed"))
    with caplog.at_level(logging.ERROR, logger="executor"):
        await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)
    assert not [r for r in caplog.records if "stuck in 'closing'" in r.getMessage()]


# ── F ──────────────────────────────────────────────────────────────────


async def test_cleanup_reads_history_once_per_account(
    db_pool, seeded_account, tm_with_store, priced_connector,
):
    tickets = [640001, 640002, 640003]
    for t in tickets:
        await _insert_trade(t, status="pending")
        await _insert_expired_order(t)
    counter = {"n": 0}
    _history(priced_connector, [_deal(640002, entry=1, profit=5.0, price=2810.0, minutes_ago=10)], counter)

    results = await tm_with_store.cleanup_expired_orders()

    assert counter["n"] == 1
    by_ticket = {r["ticket"]: r["status"] for r in results}
    assert by_ticket == {640001: "cancelled", 640002: "filled_closed", 640003: "cancelled"}


async def test_cleanup_history_failure_is_paid_once_per_account(
    db_pool, seeded_account, tm_with_store, priced_connector,
):
    for t in (641001, 641002):
        await _insert_trade(t, status="pending")
        await _insert_expired_order(t)
    counter = {"n": 0}
    _history(priced_connector, ConnectorReadError(f"{ACCT}: history read failed"), counter)

    results = await tm_with_store.cleanup_expired_orders()

    assert counter["n"] == 1
    assert [r["status"] for r in results] == ["read_failed", "read_failed"]


async def test_pending_fill_check_is_one_query_per_tick(
    db_pool, seeded_account, priced_connector, executor, monkeypatch,
):
    await _insert_trade(650001, status="pending")
    await db.log_pending_order(None, ACCT, 650001, "XAUUSD", "buy_limit", 0.1, 2035.0, 2025.0,
                               2060.0, datetime.now(timezone.utc) + timedelta(hours=1))
    priced_connector._fake_positions[650001] = Position(
        ticket=650001, symbol="XAUUSD", direction="buy", volume=0.1, open_price=2035.0,
        sl=2025.0, tp=2060.0, profit=0.0, comment="",
    )
    calls: list = []
    real = db.get_active_pending_orders

    async def counted(*args, **kwargs):
        calls.append((args, kwargs))
        return await real(*args, **kwargs)

    monkeypatch.setattr(db, "get_active_pending_orders", counted)

    assert await executor._detect_pending_order_fills() == 1
    assert len(calls) == 1
    assert calls[0] == ((), {}), "all accounts in one query"
    assert (await _trade(650001))["status"] == "opened"
