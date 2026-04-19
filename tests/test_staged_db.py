"""Tests for Phase 6 staged_entries + signal_daily_counted DB helpers.

RED baseline: all 6 tests fail until Task 1 adds the helpers.
Task 1 fills in real assertions for the currently-skipped stubs.
"""
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")


# seeded_signal is now provided by tests/conftest.py so multiple Phase 6 test files can share it.


async def test_create_staged_entries_returns_ids(db_pool, seeded_account, seeded_signal):
    """RED: db.create_staged_entries does not yet exist."""
    import db
    ids = await db.create_staged_entries([{
        "signal_id": seeded_signal,
        "stage_number": 1,
        "account_name": seeded_account,
        "symbol": "XAUUSD",
        "direction": "buy",
        "zone_low": 2040.0,
        "zone_high": 2050.0,
        "band_low": 2040.0,
        "band_high": 2050.0,
        "target_lot": 0.05,
        "snapshot_settings": {
            "risk_mode": "percent", "risk_value": 1.0, "max_stages": 5,
            "default_sl_pips": 50, "max_daily_trades": 10,
        },
        "mt5_comment": "telebot-1-s1",
        "status": "awaiting_zone",
    }])
    assert len(ids) == 1 and ids[0] > 0


def _row(signal_id, account_name, *, stage_number=1, mt5_comment="telebot-x-s1",
         status="awaiting_zone", direction="buy"):
    return {
        "signal_id": signal_id,
        "stage_number": stage_number,
        "account_name": account_name,
        "symbol": "XAUUSD",
        "direction": direction,
        "zone_low": 2040.0,
        "zone_high": 2050.0,
        "band_low": 2040.0,
        "band_high": 2050.0,
        "target_lot": 0.05,
        "snapshot_settings": {
            "risk_mode": "percent", "risk_value": 1.0, "max_stages": 5,
            "default_sl_pips": 50, "max_daily_trades": 10,
        },
        "mt5_comment": mt5_comment,
        "status": status,
    }


async def test_update_stage_status_sets_filled_at(db_pool, seeded_account, seeded_signal):
    import db
    [sid] = await db.create_staged_entries(
        [_row(seeded_signal, seeded_account, mt5_comment="telebot-upd-s1")]
    )
    await db.update_stage_status(sid, "filled", mt5_ticket=999)
    async with db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, mt5_ticket, filled_at FROM staged_entries WHERE id=$1", sid,
        )
    assert row["status"] == "filled"
    assert row["mt5_ticket"] == 999
    assert row["filled_at"] is not None


async def test_drain_for_kill_switch_terminal(db_pool, seeded_account, seeded_signal):
    import db
    await db.create_staged_entries([
        _row(seeded_signal, seeded_account, stage_number=1, mt5_comment="telebot-k-s1"),
        _row(seeded_signal, seeded_account, stage_number=2, mt5_comment="telebot-k-s2"),
    ])
    drained = await db.drain_staged_entries_for_kill_switch()
    assert drained == 2
    async with db._pool.acquire() as conn:
        rows = await conn.fetch("SELECT status FROM staged_entries ORDER BY id")
    assert all(r["status"] == "cancelled_by_kill_switch" for r in rows)


async def test_get_pending_stages_filters_by_status(db_pool, seeded_account, seeded_signal):
    import db
    ids = await db.create_staged_entries([
        _row(seeded_signal, seeded_account, stage_number=1, mt5_comment="telebot-p-s1"),
        _row(seeded_signal, seeded_account, stage_number=2, mt5_comment="telebot-p-s2"),
    ])
    # Mark the second one filled so it no longer shows as pending
    await db.update_stage_status(ids[1], "filled", mt5_ticket=42)
    pending = await db.get_pending_stages()
    assert len(pending) == 1
    assert pending[0]["status"] == "awaiting_zone"
    assert pending[0]["id"] == ids[0]


async def test_mark_signal_counted_today_idempotent(db_pool, seeded_account, seeded_signal):
    import db
    first = await db.mark_signal_counted_today(seeded_signal, seeded_account)
    second = await db.mark_signal_counted_today(seeded_signal, seeded_account)
    assert first is True
    assert second is False


async def test_reconcile_after_reconnect_matches_by_comment(db_pool, seeded_account, seeded_signal):
    import db
    await db.create_staged_entries(
        [_row(seeded_signal, seeded_account, stage_number=2, mt5_comment="telebot-42-s2")]
    )
    row = await db.get_stage_by_comment("telebot-42-s2")
    assert row is not None
    assert row["signal_id"] == seeded_signal
    assert row["stage_number"] == 2
    # miss case
    assert await db.get_stage_by_comment("does-not-exist") is None
