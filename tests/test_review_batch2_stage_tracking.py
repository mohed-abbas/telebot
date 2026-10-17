"""Review 2026-10-16 — batch 2 (stage tracking) regression tests.

One test group per finding in docs/audit/review-2026-10-16-fix-plan.md:

  #1   SL/TP sweep undid breakeven / TP edits
  #5   fire-path races overwrote 'filled' / 'firing'
  #10  stages stuck in 'firing'
  #6   restart cancelled armed scale-ins
  #11  early follow-up skipped the stage-1 alignment
  (+)  kill switch then quick resume (batch-1 leftover: epoch counter)

DB-backed: every test drives the real TradeManager / Executor against the
throwaway Postgres (conftest `db_pool`) and a DryRunConnector.
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio

import db
from executor import Executor
from models import Direction, SignalAction, SignalType
from mt5_connector import Position
from trade_manager import KILL_SWITCH_REASON

pytestmark = pytest.mark.asyncio(loop_scope="session")

ACCT = "test-acct"


# ── helpers ────────────────────────────────────────────────────────────


async def _insert_stage(
    *, signal_id: int, stage_number: int, status: str = "awaiting_zone",
    direction: str = "buy", band_low: float = 2040.0, band_high: float = 2042.5,
    mt5_ticket: int | None = None, signal_sl: float | None = None,
    signal_tp: float | None = None, created_minutes_ago: int = 0,
    firing_minutes_ago: int | None = None,
) -> int:
    snapshot = {
        "account_name": ACCT, "risk_mode": "fixed_lot", "risk_value": 0.5,
        "max_stages": 5, "default_sl_pips": 100, "max_daily_trades": 30,
        "max_open_trades": 5, "max_lot_size": 1.0,
    }
    async with db._pool.acquire() as conn:
        row_id = await conn.fetchval(
            """INSERT INTO staged_entries
               (signal_id, stage_number, account_name, symbol, direction,
                zone_low, zone_high, band_low, band_high, target_lot,
                snapshot_settings, mt5_comment, mt5_ticket, status,
                signal_sl, signal_tp, created_at, firing_at)
               VALUES ($1,$2,$3,'XAUUSD',$4,$5,$6,$5,$6,0.1,$7::jsonb,$8,$9,$10,
                       $11,$12, NOW() - make_interval(mins => $13),
                       CASE WHEN $14::int IS NULL THEN NULL
                            ELSE NOW() - make_interval(mins => $14) END)
               RETURNING id""",
            signal_id, stage_number, ACCT, direction, band_low, band_high,
            json.dumps(snapshot), f"telebot-{signal_id}-s{stage_number}",
            mt5_ticket, status, signal_sl, signal_tp,
            created_minutes_ago, firing_minutes_ago,
        )
    return row_id


async def _stage(row_id: int) -> dict:
    async with db._pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM staged_entries WHERE id=$1", row_id)
    return dict(row)


def _position(ticket: int, comment: str, *, direction="buy", open_price=2040.0,
              sl=2030.0, tp=2080.0) -> Position:
    return Position(
        ticket=ticket, symbol="XAUUSD", direction=direction, volume=0.1,
        open_price=open_price, sl=sl, tp=tp, profit=0.0, comment=comment,
    )


def _open_buy(zone=(2040.0, 2060.0), sl=2030.0, tp=2080.0) -> SignalAction:
    return SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone SL TP", direction=Direction.BUY,
        entry_zone=zone, sl=sl, tps=[tp], target_tp=tp,
    )


@pytest_asyncio.fixture
async def executor(tm_with_store, global_config):
    """Executor wrapping the DB-backed TradeManager; loops are not started."""
    return Executor(trade_manager=tm_with_store, global_config=global_config, notifier=None)


# ── #1  SL/TP sweep must keep a live SL/TP edit ──────────────────────────


async def test_modify_sl_to_breakeven_survives_the_sweep(
    db_pool, seeded_signal, priced_connector, tm_with_store, executor,
):
    sid = seeded_signal
    comment = f"telebot-{sid}-s1"
    row_id = await _insert_stage(
        signal_id=sid, stage_number=1, status="filled", mt5_ticket=501,
        signal_sl=2030.0, signal_tp=2080.0,
    )
    priced_connector._fake_positions[501] = _position(501, comment, open_price=2040.0)

    # Provider: "SL to breakeven" (new_sl=0.0 means entry price).
    results = await tm_with_store.handle_signal(SignalAction(
        type=SignalType.MODIFY_SL, symbol="XAUUSD", raw_text="SL to BE", new_sl=0.0,
    ))
    assert [r for r in results if r.get("status") == "sl_modified"]
    assert priced_connector._fake_positions[501].sl == 2040.0

    row = await _stage(row_id)
    assert row["signal_sl"] == 2040.0, "the stage row must now target breakeven"
    assert row["signal_tp"] == 2080.0, "TP target untouched"

    # The sweep must treat breakeven as the target: no revert to 2030.
    modify_calls: list[tuple] = []
    real_modify = priced_connector.modify_position

    async def spy_modify(ticket, sl=None, tp=None):
        modify_calls.append((ticket, sl, tp))
        return await real_modify(ticket, sl=sl, tp=tp)

    priced_connector.modify_position = spy_modify
    await executor._run_stage_sltp_verification_sweep()

    assert modify_calls == [], f"sweep must not touch an in-sync position: {modify_calls}"
    assert priced_connector._fake_positions[501].sl == 2040.0


async def test_modify_tp_persists_target(
    db_pool, seeded_signal, priced_connector, tm_with_store,
):
    sid = seeded_signal
    row_id = await _insert_stage(
        signal_id=sid, stage_number=2, status="filled", mt5_ticket=502,
        signal_sl=2030.0, signal_tp=2080.0,
    )
    priced_connector._fake_positions[502] = _position(502, f"telebot-{sid}-s2")

    await tm_with_store.handle_signal(SignalAction(
        type=SignalType.MODIFY_TP, symbol="XAUUSD", raw_text="TP 2100", new_tp=2100.0,
    ))

    row = await _stage(row_id)
    assert row["signal_tp"] == 2100.0
    assert row["signal_sl"] == 2030.0


async def test_update_stage_targets_for_position_is_coalesce_and_stage_only(
    db_pool, seeded_account, seeded_signal,
):
    sid = seeded_signal
    row_id = await _insert_stage(
        signal_id=sid, stage_number=1, status="filled", mt5_ticket=503,
        signal_sl=2030.0, signal_tp=None,
    )
    assert await db.update_stage_targets_for_position(ACCT, "telebot", sl=1.0) is False
    assert await db.update_stage_targets_for_position(ACCT, "manual", tp=1.0) is False
    assert await db.update_stage_targets_for_position(ACCT, f"telebot-{sid}-s1") is False

    assert await db.update_stage_targets_for_position(ACCT, f"telebot-{sid}-s1", tp=2090.0)
    row = await _stage(row_id)
    assert (row["signal_sl"], row["signal_tp"]) == (2030.0, 2090.0)

    # Wrong account → no row touched.
    assert await db.update_stage_targets_for_position("other", f"telebot-{sid}-s1", sl=1.0) is False


async def test_dashboard_levels_edit_records_stage_target(
    db_pool, api_app, session_client, monkeypatch,
):
    """POST /positions/{account}/{ticket}/levels must hand the edit to the stage
    row (the sweep reverted dashboard edits within one tick)."""
    import dashboard

    c, token = session_client
    conn = dashboard._executor.tm.connectors["Vantage Demo-10k"]
    pos = conn._fake_positions[100001]
    original = pos
    conn._fake_positions[100001] = Position(
        ticket=pos.ticket, symbol=pos.symbol, direction=pos.direction,
        volume=pos.volume, open_price=pos.open_price, sl=pos.sl, tp=pos.tp,
        profit=pos.profit, comment="telebot-7-s1",
    )
    recorded: list[tuple] = []

    async def fake_update(account_name, mt5_comment, *, sl=None, tp=None):
        recorded.append((account_name, mt5_comment, sl, tp))
        return True

    monkeypatch.setattr(db, "update_stage_targets_for_position", fake_update)
    try:
        resp = await c.post(
            "/api/v2/positions/Vantage%20Demo-10k/100001/levels",
            json={"sl": 2795.0, "tp": 2820.0},  # tp unchanged → only sl is sent
            headers={"X-CSRF-Token": token},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["changed"] == {"sl": 2795.0}
        assert recorded == [("Vantage Demo-10k", "telebot-7-s1", 2795.0, None)]
    finally:
        conn._fake_positions[100001] = original


# ── #5  status writes are compare-and-set ───────────────────────────────


async def test_failed_and_capped_never_overwrite_a_filled_row(db_pool, seeded_account, seeded_signal):
    row_id = await _insert_stage(signal_id=seeded_signal, stage_number=2)
    assert await db.update_stage_status(row_id, "filled", mt5_ticket=600)

    assert await db.update_stage_status(row_id, "failed", cancelled_reason="late") is False
    assert await db.update_stage_status(row_id, "capped", cancelled_reason="cap") is False
    assert await db.update_stage_status(row_id, "abandoned_reconnect", cancelled_reason="x") is False
    assert await db.update_stage_status(row_id, "cancelled_by_kill_switch") is False

    row = await _stage(row_id)
    assert (row["status"], row["mt5_ticket"]) == ("filled", 600)
    assert row["cancelled_reason"] is None


async def test_only_the_claim_owner_may_fail_a_firing_row(db_pool, seeded_account, seeded_signal):
    row_id = await _insert_stage(signal_id=seeded_signal, stage_number=2)
    assert await db.claim_stage_for_firing(row_id) == row_id
    assert (await _stage(row_id))["firing_at"] is not None

    # A non-owner (default rule) is refused; the owner passes the expected state.
    assert await db.update_stage_status(row_id, "failed", cancelled_reason="other path") is False
    assert (await _stage(row_id))["status"] == "firing"
    assert await db.update_stage_status(
        row_id, "failed", cancelled_reason="broker reject", expected_status=("firing",),
    )
    assert (await _stage(row_id))["status"] == "failed"


async def test_unknown_status_has_no_transition_rule(db_pool):
    with pytest.raises(ValueError):
        await db.update_stage_status(1, "bogus")


async def test_zone_watch_already_filled_result_keeps_the_filled_row(
    db_pool, seeded_signal, priced_connector, tm_with_store, executor,
):
    """Zone watch snapshotted s2 as awaiting; the at-arrival path filled it in
    between. The zone-watch fire must then leave the row 'filled' + ticket."""
    sid = seeded_signal
    row_id = await _insert_stage(signal_id=sid, stage_number=2, signal_sl=2030.0, signal_tp=2080.0)
    snapshot = await _stage(row_id)                     # status='awaiting_zone' here
    assert await db.update_stage_status(row_id, "filled", mt5_ticket=610)  # other path wins

    await executor._fire_zone_stage(
        acct_name=ACCT, connector=priced_connector, symbol="XAUUSD",
        stage=snapshot, bid=2040.1, ask=2040.2, signal_id=sid,
    )

    row = await _stage(row_id)
    assert (row["status"], row["mt5_ticket"]) == ("filled", 610)
    assert priced_connector._fake_positions == {}, "no second order was sent"


async def test_capped_check_does_not_overwrite_a_filled_row(
    db_pool, seeded_signal, priced_connector, tm_with_store,
):
    sid = seeded_signal
    row_id = await _insert_stage(signal_id=sid, stage_number=2)
    assert await db.update_stage_status(row_id, "filled", mt5_ticket=620)
    for t in range(10):  # over any max_open_trades cap
        priced_connector._fake_positions[700 + t] = _position(700 + t, f"telebot-{sid}-s{t + 3}")

    acct = tm_with_store.accounts[ACCT]
    result = await tm_with_store._execute_open_on_account(
        _open_buy(), sid, acct, priced_connector,
        staged=True, stage_number=2, stage_row_id=row_id,
    )
    assert result["status"] == "capped"
    assert (await _stage(row_id))["status"] == "filled"


# ── #10  no row may stay 'firing' ───────────────────────────────────────


async def test_fill_is_recorded_before_bookkeeping_that_raises(
    db_pool, seeded_staged_account, priced_connector, tm_with_store, monkeypatch,
):
    async def boom(**_kw):
        raise RuntimeError("trades table unavailable")

    monkeypatch.setattr(db, "log_trade", boom)

    results = await tm_with_store.handle_signal(SignalAction(
        type=SignalType.OPEN_TEXT_ONLY, symbol="XAUUSD", raw_text="Gold buy now",
        direction=Direction.BUY, entry_zone=None, sl=None, tps=[], target_tp=None,
    ))

    executed = [r for r in results if r.get("status") == "executed"]
    assert executed, results
    rows = await db.get_pending_stages(account_name=ACCT)
    assert rows == [], "nothing may be left in 'firing'"
    ticket = executed[0]["ticket"]
    row = await db.get_stage_by_comment(priced_connector._fake_positions[ticket].comment)
    assert row["status"] == "filled"
    assert row["mt5_ticket"] == ticket


async def test_broker_reject_finalizes_the_claimed_row_as_failed(
    db_pool, seeded_signal, priced_connector, tm_with_store,
):
    from mt5_connector import OrderResult

    async def reject(**_kw):
        return OrderResult(success=False, error="10019 no money")

    priced_connector.open_order = reject
    sid = seeded_signal
    row_id = await _insert_stage(signal_id=sid, stage_number=2, signal_sl=2030.0, signal_tp=2080.0)
    acct = tm_with_store.accounts[ACCT]

    result = await tm_with_store._execute_open_on_account(
        _open_buy(), sid, acct, priced_connector,
        staged=True, stage_number=2, stage_row_id=row_id,
    )
    assert result["status"] == "failed"
    row = await _stage(row_id)
    assert (row["status"], row["cancelled_reason"]) == ("failed", "10019 no money")


async def test_open_order_exception_finalizes_the_claimed_row_as_failed(
    db_pool, seeded_signal, priced_connector, tm_with_store,
):
    async def explode(**_kw):
        raise ConnectionError("bridge gone")

    priced_connector.open_order = explode
    sid = seeded_signal
    row_id = await _insert_stage(signal_id=sid, stage_number=2, signal_sl=2030.0, signal_tp=2080.0)
    acct = tm_with_store.accounts[ACCT]

    with pytest.raises(ConnectionError):
        await tm_with_store._execute_open_on_account(
            _open_buy(), sid, acct, priced_connector,
            staged=True, stage_number=2, stage_row_id=row_id,
        )
    row = await _stage(row_id)
    assert row["status"] == "failed"
    assert row["cancelled_reason"].startswith("open_order raised")


async def test_stale_firing_rows_are_reconciled_from_live_positions(
    db_pool, seeded_signal, priced_connector, executor,
):
    sid = seeded_signal
    with_pos = await _insert_stage(signal_id=sid, stage_number=2, status="firing", firing_minutes_ago=10)
    without_pos = await _insert_stage(signal_id=sid, stage_number=3, status="firing", firing_minutes_ago=10)
    fresh = await _insert_stage(signal_id=sid, stage_number=4, status="firing", firing_minutes_ago=0)
    priced_connector._fake_positions[801] = _position(801, f"telebot-{sid}-s2")

    await executor._reconcile_stale_firing_stages()

    assert ((await _stage(with_pos))["status"], (await _stage(with_pos))["mt5_ticket"]) == ("filled", 801)
    assert (await _stage(without_pos))["status"] == "failed"
    assert (await _stage(without_pos))["cancelled_reason"] == "firing_stale_no_position"
    assert (await _stage(fresh))["status"] == "firing", "a fresh claim belongs to its owner"


async def test_startup_reconcile_fails_firing_rows_left_by_the_old_process(
    db_pool, seeded_signal, priced_connector, executor,
):
    sid = seeded_signal
    row_id = await _insert_stage(signal_id=sid, stage_number=2, status="firing", firing_minutes_ago=0)

    await executor._sync_positions(ACCT, priced_connector, startup=True)

    row = await _stage(row_id)
    assert (row["status"], row["cancelled_reason"]) == ("failed", "firing_interrupted_by_restart")


# ── #6  restart keeps the armed bands of a live sequence ────────────────


async def test_startup_reconcile_keeps_bands_while_stage1_is_live(
    db_pool, seeded_signal, priced_connector, executor,
):
    sid = seeded_signal
    await _insert_stage(signal_id=sid, stage_number=1, status="filled", mt5_ticket=901, created_minutes_ago=45)
    s2 = await _insert_stage(signal_id=sid, stage_number=2, created_minutes_ago=45)
    s3 = await _insert_stage(signal_id=sid, stage_number=3, created_minutes_ago=45)
    priced_connector._fake_positions[901] = _position(901, f"telebot-{sid}-s1")

    await executor._sync_positions(ACCT, priced_connector, startup=True)

    assert (await _stage(s2))["status"] == "awaiting_zone"
    assert (await _stage(s3))["status"] == "awaiting_zone"


async def test_reconnect_reconcile_also_keeps_bands_while_stage1_is_live(
    db_pool, seeded_signal, priced_connector, executor,
):
    """The same sequence on a disconnect/reconnect 2 h later: still armed."""
    sid = seeded_signal
    await _insert_stage(signal_id=sid, stage_number=1, status="filled", mt5_ticket=902, created_minutes_ago=120)
    s2 = await _insert_stage(signal_id=sid, stage_number=2, created_minutes_ago=120)
    priced_connector._fake_positions[902] = _position(902, f"telebot-{sid}-s1")

    await executor._sync_positions(ACCT, priced_connector)

    assert (await _stage(s2))["status"] == "awaiting_zone"


async def test_startup_reconcile_cancels_bands_when_stage1_is_gone(
    db_pool, seeded_signal, priced_connector, executor,
):
    sid = seeded_signal
    await _insert_stage(signal_id=sid, stage_number=1, status="filled", mt5_ticket=903, created_minutes_ago=5)
    s2 = await _insert_stage(signal_id=sid, stage_number=2, created_minutes_ago=5)

    await executor._sync_positions(ACCT, priced_connector, startup=True)

    row = await _stage(s2)
    assert row["status"] == "cancelled_stage1_closed"
    assert row["cancelled_reason"] == "stage1_closed_at_startup"


async def test_startup_reconcile_keeps_unfilled_direct_zone_bands(
    db_pool, seeded_signal, priced_connector, executor,
):
    """Direct-zone sequence, nothing filled yet, 2 h old: a restart must not
    abandon it (without the restart it would still be waiting for price)."""
    sid = seeded_signal
    s1 = await _insert_stage(signal_id=sid, stage_number=1, created_minutes_ago=120)
    s2 = await _insert_stage(signal_id=sid, stage_number=2, created_minutes_ago=120)

    await executor._sync_positions(ACCT, priced_connector, startup=True)

    assert (await _stage(s1))["status"] == "awaiting_zone"
    assert (await _stage(s2))["status"] == "awaiting_zone"


# ── #11  early follow-up still aligns stage 1 ───────────────────────────


async def test_followup_while_stage1_is_firing_persists_targets_and_sweep_aligns(
    db_pool, seeded_signal, priced_connector, tm_with_store, executor,
):
    sid = seeded_signal
    # Stage 1 (text-only SELL) is mid-fire: claimed, no ticket yet, default SL.
    s1 = await _insert_stage(
        signal_id=sid, stage_number=1, status="firing", direction="sell",
        signal_sl=2050.0, signal_tp=None, firing_minutes_ago=0,
    )
    await tm_with_store.correlator.register_orphan(
        signal_id=sid, symbol="XAUUSD", direction="sell", account_name=ACCT,
    )
    modify_calls: list[tuple] = []
    real_modify = priced_connector.modify_position

    async def spy_modify(ticket, sl=None, tp=None):
        modify_calls.append((ticket, sl, tp))
        return await real_modify(ticket, sl=sl, tp=tp)

    priced_connector.modify_position = spy_modify

    # Follow-up: zone above the current price (2040) so no band fires at arrival.
    results = await tm_with_store.handle_signal(SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD", raw_text="Gold sell 2050-2060 SL 2070 TP 2020",
        direction=Direction.SELL, entry_zone=(2050.0, 2060.0),
        sl=2070.0, tps=[2020.0], target_tp=2020.0,
    ))
    assert [r for r in results if r.get("status") == "staged"], results
    assert modify_calls == [], "no ticket yet → nothing to modify"

    row = await _stage(s1)
    assert (row["signal_sl"], row["signal_tp"]) == (2070.0, 2020.0)
    assert row["status"] == "firing"

    # Stage 1 now fills with the default SL and no TP (what the fire path sent).
    priced_connector._fake_positions[950] = _position(
        950, f"telebot-{sid}-s1", direction="sell", open_price=2040.0, sl=2050.0, tp=0.0,
    )
    assert await db.update_stage_status(s1, "filled", mt5_ticket=950)

    await executor._run_stage_sltp_verification_sweep()

    pos = priced_connector._fake_positions[950]
    assert (pos.sl, pos.tp) == (2070.0, 2020.0)
    assert modify_calls == [(950, 2070.0, 2020.0)]


async def test_followup_does_not_touch_a_terminal_stage1(
    db_pool, seeded_signal, priced_connector, tm_with_store,
):
    sid = seeded_signal
    s1 = await _insert_stage(
        signal_id=sid, stage_number=1, status="failed", direction="sell", signal_sl=2050.0,
    )
    await tm_with_store.correlator.register_orphan(
        signal_id=sid, symbol="XAUUSD", direction="sell", account_name=ACCT,
    )
    await tm_with_store.handle_signal(SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD", raw_text="Gold sell 2050-2060 SL 2070 TP 2020",
        direction=Direction.SELL, entry_zone=(2050.0, 2060.0),
        sl=2070.0, tps=[2020.0], target_tp=2020.0,
    ))
    row = await _stage(s1)
    assert (row["signal_sl"], row["signal_tp"]) == (2050.0, None)


# ── kill switch, then a quick resume, while a handler is in flight ──────


async def test_kill_switch_then_resume_during_handler_refuses_submit(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    epoch = {"v": 0}
    tm_with_store.is_trading_paused = lambda: False      # operator already resumed
    tm_with_store.kill_switch_epoch = lambda: epoch["v"]
    real_get_price = priced_connector.get_price

    async def get_price_then_kill_switch_and_resume(symbol):
        epoch["v"] += 1  # emergency_close ran (and resume_trading right after)
        return await real_get_price(symbol)

    priced_connector.get_price = get_price_then_kill_switch_and_resume

    results = await tm_with_store.handle_signal(_open_buy())

    assert priced_connector._fake_positions == {}
    assert [r for r in results if r.get("reason") == KILL_SWITCH_REASON]
    async with db._pool.acquire() as conn:
        statuses = {r["status"] for r in await conn.fetch("SELECT status FROM staged_entries")}
    assert statuses == {"cancelled_by_kill_switch"}


async def test_emergency_close_bumps_the_epoch_the_trade_manager_sees(
    db_pool, priced_connector, tm_with_store, executor,
):
    assert tm_with_store.kill_switch_epoch() == 0
    await executor.emergency_close()
    assert tm_with_store.kill_switch_epoch() == 1
    executor.resume_trading()
    assert tm_with_store.kill_switch_epoch() == 1, "resume must not reset the epoch"
