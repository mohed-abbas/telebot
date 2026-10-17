"""Batch 5 — fixes for the 2026-10-17 /code-review findings on batches 1–4.

  #1/#2  limit fills are recorded when the position appears (maintenance tick),
         and an expired order that filled AND closed is reconciled from the
         broker's OUT deal instead of being marked 'cancelled'
  #3/#8  the stale-'closing' fallback waits for the history watermark to pass
         close_time; legacy rows without close_time age from their timestamp
  #4     the D-14 pre-flight get_price is bounded
  #5     bands whose stage 1 ended without filling are cancelled (startup + tick)
  #6     one positions read per account per maintenance tick
  #7/#9  'filled' clears cancelled_reason; drain uses _rows_affected
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

import db
from executor import Executor
from mt5_connector import ConnectorReadError, Deal, Position

pytestmark = pytest.mark.asyncio(loop_scope="session")

ACCT = "test-acct"


# ── helpers ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def executor(tm_with_store, global_config):
    return Executor(trade_manager=tm_with_store, global_config=global_config, notifier=None)


async def _insert_stage(
    *, signal_id: int, stage_number: int, status: str = "awaiting_zone",
    account: str = ACCT, direction: str = "buy",
    band_low: float = 2040.0, band_high: float = 2042.5,
    mt5_ticket: int | None = None, signal_sl: float | None = None,
    signal_tp: float | None = None, firing_minutes_ago: int | None = None,
) -> int:
    snapshot = {
        "account_name": account, "risk_mode": "fixed_lot", "risk_value": 0.5,
        "max_stages": 5, "default_sl_pips": 100, "max_daily_trades": 30,
        "max_open_trades": 5, "max_lot_size": 1.0,
    }
    async with db._pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO staged_entries
               (signal_id, stage_number, account_name, symbol, direction,
                zone_low, zone_high, band_low, band_high, target_lot,
                snapshot_settings, mt5_comment, mt5_ticket, status,
                signal_sl, signal_tp, firing_at)
               VALUES ($1,$2,$3,'XAUUSD',$4,$5,$6,$5,$6,0.1,$7::jsonb,$8,$9,$10,
                       $11,$12,
                       CASE WHEN $13::int IS NULL THEN NULL
                            ELSE NOW() - make_interval(mins => $13) END)
               RETURNING id""",
            signal_id, stage_number, account, direction, band_low, band_high,
            json.dumps(snapshot), f"telebot-{signal_id}-s{stage_number}",
            mt5_ticket, status, signal_sl, signal_tp, firing_minutes_ago,
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


async def _insert_pending_order(ticket: int, *, expires_in_minutes: int) -> int:
    expires = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
    return await db.log_pending_order(
        None, ACCT, ticket, "XAUUSD", "buy_limit", 0.1, 2035.0, 2025.0, 2060.0, expires,
    )


async def _pending_status(order_id: int) -> str:
    async with db._pool.acquire() as conn:
        return await conn.fetchval("SELECT status FROM pending_orders WHERE id=$1", order_id)


def _position(ticket: int, comment: str = "", *, open_price: float = 2040.0) -> Position:
    return Position(
        ticket=ticket, symbol="XAUUSD", direction="buy", volume=0.1,
        open_price=open_price, sl=2030.0, tp=2080.0, profit=0.0, comment=comment,
    )


def _out_deal(position_id: int, *, profit: float, price: float, minutes_ago: int = 15) -> Deal:
    t = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).timestamp()
    return Deal(ticket=position_id + 1, position_id=position_id, time=t, entry=1,
                volume=0.1, price=price, profit=profit)


def _history(connector, deals: list[Deal] | Exception) -> None:
    """Turn the dry-run connector into a 'real bridge' with scripted deal history."""
    connector.supports_history_sync = True

    async def get_history_deals(since, until=None):
        if isinstance(deals, Exception):
            raise deals
        return list(deals)

    connector.get_history_deals = get_history_deals


# ═══════════════════════════════════════════════════════════════════════
# #1/#2  limit-order fills
# ═══════════════════════════════════════════════════════════════════════


async def test_maintenance_tick_records_a_limit_fill_when_the_position_appears(
    db_pool, seeded_account, priced_connector, executor,
):
    ticket = 950001
    await _insert_trade(ticket, status="pending")
    order_id = await _insert_pending_order(ticket, expires_in_minutes=60)
    priced_connector._fake_positions[ticket] = _position(ticket, open_price=2035.0)

    assert await executor._detect_pending_order_fills() == 1
    assert (await _trade(ticket))["status"] == "opened"
    assert await _pending_status(order_id) == "filled"
    # Idempotent on the next tick.
    assert await executor._detect_pending_order_fills() == 0

    # The whole point: a dashboard close before expiry is now recorded.
    assert await db.mark_trade_closing(ticket, ACCT, 2041.0, pnl_estimate=6.0) is True
    assert (await _trade(ticket))["status"] == "closing"


async def test_pending_fill_check_ignores_unrelated_positions(
    db_pool, seeded_account, priced_connector, executor,
):
    ticket = 950002
    await _insert_trade(ticket, status="pending")
    order_id = await _insert_pending_order(ticket, expires_in_minutes=60)
    priced_connector._fake_positions[950099] = _position(950099, "telebot-1-s1")

    assert await executor._detect_pending_order_fills() == 0
    assert (await _trade(ticket))["status"] == "pending"
    assert await _pending_status(order_id) == "active"


async def test_expired_limit_that_filled_and_closed_before_expiry_is_recorded(
    db_pool, seeded_account, tm_with_store, priced_connector,
):
    ticket = 950101
    await _insert_trade(ticket, status="pending")
    order_id = await _insert_pending_order(ticket, expires_in_minutes=-5)
    # No resting order, no position — but the broker has the OUT deal.
    _history(priced_connector, [_out_deal(ticket, profit=12.5, price=2811.0)])

    results = await tm_with_store.cleanup_expired_orders()

    assert [r["status"] for r in results] == ["filled_closed"]
    row = await _trade(ticket)
    assert row["status"] == "closed"
    assert float(row["pnl"]) == pytest.approx(12.5)
    assert float(row["close_price"]) == pytest.approx(2811.0)
    assert await _pending_status(order_id) == "filled"


async def test_expired_limit_history_read_failure_is_retried_next_cycle(
    db_pool, seeded_account, tm_with_store, priced_connector,
):
    ticket = 950102
    await _insert_trade(ticket, status="pending")
    order_id = await _insert_pending_order(ticket, expires_in_minutes=-5)
    _history(priced_connector, ConnectorReadError(f"{ACCT}: history read failed"))

    results = await tm_with_store.cleanup_expired_orders()

    assert [r["status"] for r in results] == ["read_failed"]
    assert (await _trade(ticket))["status"] == "pending"
    assert await _pending_status(order_id) == "active"


async def test_expired_limit_with_no_deal_and_no_position_is_cancelled(
    db_pool, seeded_account, tm_with_store, priced_connector,
):
    ticket = 950103
    await _insert_trade(ticket, status="pending")
    order_id = await _insert_pending_order(ticket, expires_in_minutes=-5)
    _history(priced_connector, [_out_deal(950999, profit=1.0, price=2800.0)])  # someone else's

    results = await tm_with_store.cleanup_expired_orders()

    assert [r["status"] for r in results] == ["cancelled"]
    assert (await _trade(ticket))["status"] == "cancelled"
    assert await _pending_status(order_id) == "cancelled"


# ═══════════════════════════════════════════════════════════════════════
# #3/#8  stale-'closing' fallback vs. the history watermark
# ═══════════════════════════════════════════════════════════════════════


async def _park_closing(ticket: int, *, estimate: float, minutes_ago: int) -> None:
    await _insert_trade(ticket)
    assert await db.mark_trade_closing(ticket, ACCT, 2805.0, pnl_estimate=estimate) is True
    async with db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE trades SET close_time = NOW() - make_interval(mins => $2) WHERE ticket=$1",
            ticket, minutes_ago,
        )


async def test_stale_closing_fallback_waits_for_the_history_watermark(
    db_pool, seeded_account, executor,
):
    ticket = 960001
    await _park_closing(ticket, estimate=12.5, minutes_ago=20)
    now = datetime.now(timezone.utc)

    # No history window read yet for this account -> nothing is finalized.
    assert await executor._finalize_stale_closing_trades(ACCT) == 0
    # Window read only up to before the close -> the deal may still arrive.
    executor._last_history_sync[ACCT] = now - timedelta(minutes=25)
    assert await executor._finalize_stale_closing_trades(ACCT) == 0
    assert (await _trade(ticket))["status"] == "closing"
    # Window read past the close and still no deal -> estimate becomes final.
    executor._last_history_sync[ACCT] = now
    assert await executor._finalize_stale_closing_trades(ACCT) == 1
    row = await _trade(ticket)
    assert row["status"] == "closed"
    assert float(row["pnl"]) == pytest.approx(12.5)


async def test_history_outage_keeps_the_real_deal_ahead_of_the_estimate(
    db_pool, seeded_account, priced_connector, executor,
):
    ticket = 960002
    await _park_closing(ticket, estimate=4.0, minutes_ago=20)

    # 1) the bridge cannot serve deal history: the fallback must NOT fire,
    #    however old the 'closing' row is.
    _history(priced_connector, ConnectorReadError(f"{ACCT}: history read failed"))
    await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)
    assert (await _trade(ticket))["status"] == "closing"
    assert ACCT not in executor._last_history_sync

    # 2) the bridge recovers and the real OUT deal is in the window.
    _history(priced_connector, [_out_deal(ticket, profit=9.0, price=2812.0)])
    await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)
    row = await _trade(ticket)
    assert row["status"] == "closed"
    assert float(row["pnl"]) == pytest.approx(9.0), "broker P&L, not the 4.0 estimate"
    assert float(row["close_price"]) == pytest.approx(2812.0)


async def test_history_sync_still_finalizes_a_genuinely_dealless_close(
    db_pool, seeded_account, priced_connector, executor,
):
    ticket = 960003
    await _park_closing(ticket, estimate=4.0, minutes_ago=20)
    _history(priced_connector, [])  # window read fine, broker has nothing

    await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)
    row = await _trade(ticket)
    assert row["status"] == "closed"
    assert float(row["pnl"]) == pytest.approx(4.0)


async def test_legacy_closing_row_without_close_time_is_finalized(
    db_pool, seeded_account, executor,
):
    ticket = 960004
    await _insert_trade(ticket)
    async with db._pool.acquire() as conn:
        await conn.execute(
            """UPDATE trades SET status='closing', close_time=NULL, pnl=2.0, close_price=2805.0,
                      timestamp = NOW() - make_interval(mins => 20)
               WHERE ticket=$1""",
            ticket,
        )
    executor._last_history_sync[ACCT] = datetime.now(timezone.utc)

    assert await executor._finalize_stale_closing_trades(ACCT) == 1
    row = await _trade(ticket)
    assert row["status"] == "closed"
    assert float(row["pnl"]) == pytest.approx(2.0)


# ═══════════════════════════════════════════════════════════════════════
# #5  stage 1 ended without filling -> its bands go too
# ═══════════════════════════════════════════════════════════════════════


async def test_startup_reconcile_cancels_bands_whose_stage1_failed(
    db_pool, seeded_signal, priced_connector, executor,
):
    sid = seeded_signal
    await _insert_stage(signal_id=sid, stage_number=1, status="failed")
    s2 = await _insert_stage(signal_id=sid, stage_number=2)
    s3 = await _insert_stage(signal_id=sid, stage_number=3, band_low=2030.0, band_high=2032.0)

    await executor._sync_positions(ACCT, priced_connector, startup=True)

    for row_id in (s2, s3):
        row = await _stage(row_id)
        assert row["status"] == "cancelled_stage1_closed"
        assert row["cancelled_reason"] == "stage1_failed_at_startup"


async def test_zone_watch_cancels_bands_whose_stage1_ended_without_filling(
    db_pool, seeded_signal, priced_connector, executor,
):
    sid = seeded_signal
    await _insert_stage(signal_id=sid, stage_number=1, status="capped")
    s2 = await _insert_stage(signal_id=sid, stage_number=2)  # price 2040.1/2040.2 is in band

    await executor._zone_watch_tick()

    row = await _stage(s2)
    assert row["status"] == "cancelled_stage1_closed"
    assert row["cancelled_reason"] == "stage1_capped"
    assert priced_connector._fake_positions == {}, "nothing fired without an anchor"


# ═══════════════════════════════════════════════════════════════════════
# #4/#6  bounded reads, one snapshot per account per tick
# ═══════════════════════════════════════════════════════════════════════


def _count_position_reads(connector) -> dict:
    counter = {"n": 0}
    real = connector.get_positions

    async def counted(*args, **kwargs):
        counter["n"] += 1
        return await real(*args, **kwargs)

    connector.get_positions = counted
    return counter


async def _seed_every_maintenance_candidate(sid: int, connector) -> None:
    """A sweep candidate, a stale 'firing' row and a resting limit order."""
    await _insert_stage(signal_id=sid, stage_number=1, status="filled", mt5_ticket=970001,
                        signal_sl=2030.0, signal_tp=2080.0)
    connector._fake_positions[970001] = _position(970001, f"telebot-{sid}-s1")
    await _insert_stage(signal_id=sid, stage_number=2, status="firing", firing_minutes_ago=10)
    await _insert_trade(970002, status="pending")
    await _insert_pending_order(970002, expires_in_minutes=60)


async def test_maintenance_tick_reads_positions_once_per_account(
    db_pool, seeded_signal, priced_connector, executor,
):
    await _seed_every_maintenance_candidate(seeded_signal, priced_connector)
    counter = _count_position_reads(priced_connector)

    await executor._stage_maintenance_tick()

    assert counter["n"] == 1


async def test_a_failed_positions_read_is_paid_once_per_tick(
    db_pool, seeded_signal, priced_connector, executor,
):
    await _seed_every_maintenance_candidate(seeded_signal, priced_connector)
    counter = {"n": 0}

    async def failing(*args, **kwargs):
        counter["n"] += 1
        raise ConnectorReadError(f"{ACCT}: positions read failed")

    priced_connector.get_positions = failing

    await executor._stage_maintenance_tick()

    assert counter["n"] == 1
    # Nothing was decided from the failed read.
    async with db._pool.acquire() as conn:
        statuses = {r["status"] for r in await conn.fetch("SELECT status FROM staged_entries")}
    assert statuses == {"filled", "firing"}
    assert (await _trade(970002))["status"] == "pending"


async def test_preflight_price_read_is_bounded(
    db_pool, seeded_signal, priced_connector, executor,
):
    sid = seeded_signal
    await _insert_stage(signal_id=sid, stage_number=1, status="filled", mt5_ticket=980001)
    priced_connector._fake_positions[980001] = _position(980001, f"telebot-{sid}-s1")
    s2 = await _insert_stage(signal_id=sid, stage_number=2)

    calls = {"n": 0}
    real_get_price = priced_connector.get_price

    async def get_price(symbol):
        calls["n"] += 1
        if calls["n"] == 1:
            return await real_get_price(symbol)   # in-zone first read
        await asyncio.sleep(30)                    # the bridge hangs on the pre-flight

    priced_connector.get_price = get_price
    executor._READ_TIMEOUT_SECONDS = 0.05

    await asyncio.wait_for(executor._zone_watch_tick(), timeout=2.0)

    assert calls["n"] == 2
    assert (await _stage(s2))["status"] == "awaiting_zone", "skipped this tick, not fired blind"
    assert set(priced_connector._fake_positions) == {980001}


# ═══════════════════════════════════════════════════════════════════════
# #7/#9  small DB fixes
# ═══════════════════════════════════════════════════════════════════════


async def test_filled_clears_the_outcome_unknown_tag(db_pool, seeded_account, seeded_signal):
    row_id = await _insert_stage(signal_id=seeded_signal, stage_number=1, status="firing",
                                 firing_minutes_ago=1)
    await db.mark_stage_outcome_unknown(row_id)
    assert (await _stage(row_id))["cancelled_reason"] == db.STAGE_OUTCOME_UNKNOWN

    assert await db.update_stage_status(row_id, "filled", mt5_ticket=990001) is True
    row = await _stage(row_id)
    assert row["status"] == "filled"
    assert row["cancelled_reason"] is None


async def test_kill_switch_drain_tolerates_a_fake_command_tag(db_pool):
    class _FakePool:
        async def execute(self, *args):
            return None

    real_pool = db._pool
    db._pool = _FakePool()
    try:
        assert await db.drain_staged_entries_for_kill_switch() == 0
    finally:
        db._pool = real_pool
