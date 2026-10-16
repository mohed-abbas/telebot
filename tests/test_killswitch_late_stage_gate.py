"""Kill switch fired while a signal handler is already in flight (D-21/D-22).

The executor checks _trading_paused before dispatching, and the kill switch
drains armed stages before flattening. A handler that was already past that
check (e.g. awaiting get_price) used to insert its stage rows AFTER the drain,
fire the in-zone ones after the flatten, and leave the rest armed to fire after
resume_trading. TradeManager now re-checks the kill switch after inserting
stages and right before submitting, and re-drains.

Known gap: if the operator resumes trading before the in-flight handler reaches
a check, the handler proceeds as if the kill switch never fired.
"""
from __future__ import annotations

import pytest

import db
from models import Direction, SignalAction, SignalType
from trade_manager import KILL_SWITCH_REASON

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(autouse=True)
async def _empty_stage_tables(db_pool):
    # conftest's clean_tables is a no-op until the pool exists, so the first
    # DB test of a run can see rows left by a previous run.
    async with db._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE signals, trades, staged_entries, signal_daily_counted "
            "RESTART IDENTITY CASCADE"
        )


def _in_zone_buy() -> SignalAction:
    # priced_connector quotes 2040.1/2040.2 — every band of 2040-2060 is
    # already crossed at arrival, so without the gate they would all fire.
    return SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone 2040-2060 SL 2030 TP 2080",
        direction=Direction.BUY, entry_zone=(2040.0, 2060.0),
        sl=2030.0, tps=[2080.0], target_tp=2080.0,
    )


async def _stage_statuses() -> list[str]:
    async with db._pool.acquire() as conn:
        rows = await conn.fetch("SELECT status FROM staged_entries ORDER BY stage_number")
    return [r["status"] for r in rows]


async def test_kill_switch_during_price_fetch_blocks_fire_and_drains_stages(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    paused = {"value": False}
    tm_with_store.is_trading_paused = lambda: paused["value"]

    real_get_price = priced_connector.get_price

    async def get_price_then_kill_switch(symbol):
        # The kill switch fires while the handler awaits the price.
        paused["value"] = True
        return await real_get_price(symbol)

    priced_connector.get_price = get_price_then_kill_switch

    results = await tm_with_store.handle_signal(_in_zone_buy())

    assert await priced_connector.get_positions() == []
    assert not [r for r in results if r.get("status") == "executed"]
    statuses = await _stage_statuses()
    assert statuses, "stages should still be recorded"
    assert set(statuses) == {"cancelled_by_kill_switch"}


async def test_choke_point_refuses_submit_while_paused(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    tm_with_store.is_trading_paused = lambda: True

    async def gate_never_reached(*_a, **_kw):
        raise AssertionError("open_order must not be called while paused")

    priced_connector.open_order = gate_never_reached

    results = await tm_with_store.handle_signal(_in_zone_buy())

    skipped = [r for r in results if r.get("status") == "skipped"]
    assert skipped and all("kill switch" in r["reason"].lower() for r in skipped)
    assert set(await _stage_statuses()) <= {"cancelled_by_kill_switch"}


async def test_kill_switch_during_claim_cancels_claimed_row(
    db_pool, seeded_staged_account, priced_connector, tm_with_store, monkeypatch,
):
    """The kill switch fires while the firing claim is in flight: the order must
    not be sent, and the claimed ('firing') row must end cancelled."""
    paused = {"value": False}
    tm_with_store.is_trading_paused = lambda: paused["value"]
    real_claim = db.claim_stage_for_firing

    async def claim_then_kill_switch(stage_id):
        claimed = await real_claim(stage_id)
        paused["value"] = True
        return claimed

    monkeypatch.setattr(db, "claim_stage_for_firing", claim_then_kill_switch)

    async def must_not_submit(*_a, **_kw):
        raise AssertionError("open_order must not be called after the kill switch")

    priced_connector.open_order = must_not_submit

    results = await tm_with_store.handle_signal(_in_zone_buy())

    assert [r for r in results if r.get("reason") == KILL_SWITCH_REASON]
    assert set(await _stage_statuses()) == {"cancelled_by_kill_switch"}


async def test_followup_skips_sequence_whose_stage1_was_kill_switched(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    paused = {"value": True}
    tm_with_store.is_trading_paused = lambda: paused["value"]
    text_only = SignalAction(
        type=SignalType.OPEN_TEXT_ONLY, symbol="XAUUSD",
        raw_text="Gold buy now", direction=Direction.BUY,
        entry_zone=None, sl=None, tps=[], target_tp=None,
    )
    await tm_with_store.handle_signal(text_only)
    assert await _stage_statuses() == ["cancelled_by_kill_switch"]

    # Operator resumes; the provider's follow-up arrives inside the window.
    paused["value"] = False
    results = await tm_with_store.handle_signal(_in_zone_buy())

    assert [r for r in results if r.get("reason") == "Stage 1 cancelled by kill switch"]
    assert await priced_connector.get_positions() == []
    assert await _stage_statuses() == ["cancelled_by_kill_switch"]
