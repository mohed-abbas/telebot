"""Exact signal SL/TP (operator decision 2026-10-22).

Every stage of a signal carries the signal's SL and its TP2 exactly — no
jitter — and, in fixed-lot mode, total lot / max_stages each:

    GOLD BUY 2038-2041 · SL 2029 · TP 2047 · TP 2053 · TP 2060
    fixed lot 0.2, 5 stages  →  5 × 0.04 lots, each SL 2029.0, TP 2053.0

A text-only "GOLD BUY NOW" still opens stage 1 with the temporary default SL;
the follow-up then moves stage 1 to the exact SL/TP2 and the remaining stages
fire with them.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

import db
from executor import Executor
from models import Direction, SignalAction, SignalType

pytestmark = pytest.mark.asyncio(loop_scope="session")

ACCT = "test-acct"
SL, TP1, TP2, TP3 = 2029.0, 2047.0, 2053.0, 2060.0


@pytest_asyncio.fixture
async def fixed_lot_tm(tm_with_store):
    """0.2 total lots over 5 stages, no open-trade cap in the way."""
    await db.update_account_setting(ACCT, "risk_mode", "fixed_lot", actor="test")
    await db.update_account_setting(ACCT, "risk_value", 0.2, actor="test")
    async with db._pool.acquire() as conn:
        await conn.execute("UPDATE accounts SET max_open_trades=10 WHERE name=$1", ACCT)
    await tm_with_store.settings_store.load_all()
    return tm_with_store


def _full_signal() -> SignalAction:
    return SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="GOLD BUY 2038-2041 SL 2029 TP 2047 TP 2053 TP 2060",
        direction=Direction.BUY, entry_zone=(2038.0, 2041.0),
        sl=SL, tps=[TP1, TP2, TP3], target_tp=TP2,
    )


async def _walk_price_down_through_zone(executor, connector) -> None:
    """Move the quote down through the buy zone so every band is entered."""
    for bid in (2040.6, 2040.0, 2039.4, 2038.8, 2038.2, 2037.9):
        connector._prices["XAUUSD"] = (bid, bid + 0.1)
        await executor._zone_watch_tick()


def _assert_exact(positions: dict) -> None:
    assert positions, "no stage was opened"
    for pos in positions.values():
        assert pos.sl == SL, f"{pos.comment}: SL {pos.sl} != {SL}"
        assert pos.tp == TP2, f"{pos.comment}: TP {pos.tp} != {TP2}"
        assert pos.volume == pytest.approx(0.04), f"{pos.comment}: lot {pos.volume}"


async def test_every_stage_carries_the_exact_sl_and_tp2(
    db_pool, fixed_lot_tm, priced_connector, global_config,
):
    executor = Executor(trade_manager=fixed_lot_tm, global_config=global_config, notifier=None)

    await fixed_lot_tm.handle_signal(_full_signal())
    await _walk_price_down_through_zone(executor, priced_connector)

    _assert_exact(priced_connector._fake_positions)
    comments = sorted(p.comment.rsplit("-", 1)[1] for p in priced_connector._fake_positions.values())
    assert comments == ["s1", "s2", "s3", "s4", "s5"], comments


async def test_text_only_then_followup_moves_everything_to_the_exact_levels(
    db_pool, fixed_lot_tm, priced_connector, global_config,
):
    executor = Executor(trade_manager=fixed_lot_tm, global_config=global_config, notifier=None)

    # "GOLD BUY NOW": stage 1 at market with the temporary default SL.
    await fixed_lot_tm.handle_signal(SignalAction(
        type=SignalType.OPEN_TEXT_ONLY, symbol="XAUUSD", raw_text="GOLD BUY NOW",
        direction=Direction.BUY, entry_zone=None, sl=None, tps=[], target_tp=None,
    ))
    (stage1,) = priced_connector._fake_positions.values()
    assert stage1.sl != SL, "before the follow-up: the default SL"

    # Follow-up with the real levels.
    await fixed_lot_tm.handle_signal(_full_signal())
    await _walk_price_down_through_zone(executor, priced_connector)

    _assert_exact(priced_connector._fake_positions)
    assert len(priced_connector._fake_positions) == 5
