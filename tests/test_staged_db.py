"""Tests for Phase 6 staged_entries + signal_daily_counted DB helpers.

RED baseline: all 6 tests fail until Task 1 adds the helpers.
Task 1 fills in real assertions for the currently-skipped stubs.
"""
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture
async def seeded_signal(db_pool):
    """Insert one signals row (FK target for staged_entries); returns the id."""
    import db
    async with db._pool.acquire() as conn:
        sid = await conn.fetchval(
            """INSERT INTO signals (raw_text, signal_type, symbol, direction, action_taken)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            "test signal", "open_text_only", "XAUUSD", "buy", "staged",
        )
    return sid


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


async def test_update_stage_status_sets_filled_at(db_pool, seeded_account, seeded_signal):
    """RED — stub for Task 1."""
    pytest.skip("Stub — wired in Task 1")


async def test_drain_for_kill_switch_terminal(db_pool, seeded_account, seeded_signal):
    pytest.skip("Stub — wired in Task 1")


async def test_get_pending_stages_filters_by_status(db_pool, seeded_account, seeded_signal):
    pytest.skip("Stub — wired in Task 1")


async def test_mark_signal_counted_today_idempotent(db_pool, seeded_account, seeded_signal):
    pytest.skip("Stub — wired in Task 1")


async def test_reconcile_after_reconnect_matches_by_comment(db_pool, seeded_account, seeded_signal):
    pytest.skip("Stub — wired in Task 1")
