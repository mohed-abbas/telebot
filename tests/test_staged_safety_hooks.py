"""Safety-hook tests for Phase 6 Plan 02 (D-08, D-23) + Plan 04 (D-11/D-14/D-16/D-21/D-22/D-24/D-25).

Covers:
  - D-08 hard-reject of sl <= 0.0 in _execute_open_on_account
  - D-23 duplicate-direction guard bypass for sibling stages (matching signal_id)
  - D-23 negative case — unrelated same-direction still rejected
  - D-11/D-14 _zone_watch_loop fires armed stages when price enters band (Plan 04)
  - D-21 _trading_paused gates zone-watch + kill-switch drain runs BEFORE close (Plan 04)
  - D-22 resume_trading does not un-cancel drained stages (Plan 04)
  - D-16 stage-1-exit cascade cancels unfilled stages (Plan 04)
  - D-24/D-25 reconnect reconciliation + idempotency probe (Plan 04, Task 2)
"""
from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio

import db
from executor import Executor
from models import AccountConfig, Direction, GlobalConfig, SignalAction, SignalType
from mt5_connector import DryRunConnector, OrderResult, OrderType, Position
from settings_store import SettingsStore
from trade_manager import TradeManager

pytestmark = pytest.mark.asyncio(loop_scope="session")


class _PricedDry(DryRunConnector):
    """DryRunConnector returning configurable fake prices."""

    def __init__(self, *args, prices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._prices = prices or {"XAUUSD": (2040.0, 2040.2)}

    async def get_price(self, symbol):
        return self._prices.get(symbol)


@pytest_asyncio.fixture
async def priced_connector():
    c = _PricedDry("test-acct", "TestServer", 99999, "pass")
    await c.connect()
    yield c
    await c.disconnect()


@pytest_asyncio.fixture
async def tm_with_store(db_pool, seeded_account, priced_connector, global_config):
    """TradeManager with SettingsStore attached — Phase 6-ready."""
    store = SettingsStore(db._pool)
    await store.load_all()
    acct = AccountConfig(
        name="test-acct", server="TestServer", login=99999, password_env="",
        risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
        max_open_trades=3, enabled=True,
    )
    t = TradeManager(
        connectors={"test-acct": priced_connector},
        accounts=[acct],
        global_config=global_config,
    )
    t.settings_store = store
    return t


# ── D-08 hard reject ─────────────────────────────────────────────────


async def test_default_sl_zero_hard_rejects_text_only(
    db_pool, seeded_account, priced_connector, tm_with_store, seeded_signal,
):
    """D-08: _execute_open_on_account with sl=0.0 returns status='failed'.

    The text-only path is the most likely source of this footgun (default_sl_pips
    mis-set to 0). Regardless of entry path, sl <= 0 must never reach open_order.
    """
    acct = tm_with_store.accounts["test-acct"]
    # Synthetic signal with sl=0.0 — simulates a broken default_sl_pips computation.
    bad_signal = SignalAction(
        type=SignalType.OPEN_TEXT_ONLY,
        symbol="XAUUSD",
        raw_text="Gold buy now",
        direction=Direction.BUY,
        entry_zone=None,
        sl=0.0,
        tps=[],
        target_tp=None,
    )
    result = await tm_with_store._execute_open_on_account(
        bad_signal, seeded_signal, acct, priced_connector,
        staged=True, stage_number=1,
    )
    assert result["status"] == "failed"
    assert "sl=0.0" in result["reason"]


# ── D-23 dup-guard bypass for sibling stages ─────────────────────────


async def test_dup_guard_bypass_same_signal_id_different_stage(
    db_pool, seeded_account, priced_connector, tm_with_store, seeded_signal,
):
    """D-23: sibling stages of the same signal_id bypass the duplicate-direction guard.

    Scenario: stage 1 of signal_id=N fills as a BUY on XAUUSD. Stage 2 of the same
    signal_id arrives — even though the dup-guard would normally reject (same
    direction already open), the telebot-{signal_id}-s* comment match lets it through.
    """
    # Pre-load a fake stage-1 position with the canonical comment.
    priced_connector._fake_positions[999001] = Position(
        ticket=999001, symbol="XAUUSD", direction="buy",
        volume=0.10, open_price=2040.1, sl=2039.0, tp=0.0,
        profit=0.0, comment=f"telebot-{seeded_signal}-s1",
    )

    acct = tm_with_store.accounts["test-acct"]
    sibling_signal = SignalAction(
        type=SignalType.OPEN,
        symbol="XAUUSD",
        raw_text="Gold buy zone 2040-2050 SL 2035 TP 2060",
        direction=Direction.BUY,
        entry_zone=(2040.0, 2050.0),
        sl=2035.0,
        tps=[2060.0],
        target_tp=2060.0,
    )
    result = await tm_with_store._execute_open_on_account(
        sibling_signal, seeded_signal, acct, priced_connector,
        staged=True, stage_number=2,
    )
    # Stage 2 must NOT be skipped by the dup-guard — either executed or a later
    # stage-specific outcome, but NOT the "Already have a buy position" message.
    assert result["status"] != "skipped" or "Already have a buy" not in result.get("reason", "")
    assert result["status"] in ("executed", "limit_placed")


async def test_dup_guard_still_rejects_unrelated_same_direction(
    db_pool, seeded_account, priced_connector, tm_with_store, seeded_signal,
):
    """D-23 negative: an unrelated signal (different signal_id OR no signal_id) with
    same direction still hits the guard.
    """
    # Pre-load a position with a DIFFERENT signal_id prefix.
    priced_connector._fake_positions[999002] = Position(
        ticket=999002, symbol="XAUUSD", direction="buy",
        volume=0.10, open_price=2040.1, sl=2039.0, tp=0.0,
        profit=0.0, comment="telebot-99999-s1",  # different signal_id
    )

    acct = tm_with_store.accounts["test-acct"]
    unrelated_signal = SignalAction(
        type=SignalType.OPEN,
        symbol="XAUUSD",
        raw_text="Gold buy zone 2040-2050 SL 2035 TP 2060",
        direction=Direction.BUY,
        entry_zone=(2040.0, 2050.0),
        sl=2035.0,
        tps=[2060.0],
        target_tp=2060.0,
    )
    result = await tm_with_store._execute_open_on_account(
        unrelated_signal, seeded_signal, acct, priced_connector,
        staged=True, stage_number=1,
    )
    assert result["status"] == "skipped"
    assert "Already have a buy" in result["reason"]


# ── Plan 04 ── executor safety hooks ─────────────────────────────────
# Covers:
#   Task 1 — _zone_watch_loop + kill-switch drain + D-16 cascade + lifecycle
#   Task 2 — _sync_positions reconcile (D-24) + abandoned_reconnect age rule


@pytest_asyncio.fixture
async def executor_fixture(tm_with_store, global_config):
    """Executor wrapping tm_with_store. Not started — tests drive hooks directly."""
    ex = Executor(
        trade_manager=tm_with_store,
        global_config=global_config,
        notifier=None,
    )
    return ex


async def _insert_staged_row(
    *, signal_id: int, stage_number: int, account_name: str,
    symbol: str = "XAUUSD", direction: str = "buy",
    band_low: float = 2040.0, band_high: float = 2042.5,
    mt5_comment: str | None = None, status: str = "awaiting_zone",
    target_lot: float = 0.1,
    snapshot_settings: dict | None = None,
    mt5_ticket: int | None = None,
) -> int:
    """Insert one staged_entries row; return its id."""
    if mt5_comment is None:
        mt5_comment = f"telebot-{signal_id}-s{stage_number}"
    if snapshot_settings is None:
        snapshot_settings = {
            "account_name": account_name,
            "risk_mode": "fixed_lot",
            "risk_value": 0.5,
            "max_stages": 5,
            "default_sl_pips": 100,
            "max_daily_trades": 30,
            "max_open_trades": 3,
            "max_lot_size": 1.0,
        }
    async with db._pool.acquire() as conn:
        row_id = await conn.fetchval(
            """INSERT INTO staged_entries
               (signal_id, stage_number, account_name, symbol, direction,
                zone_low, zone_high, band_low, band_high, target_lot,
                snapshot_settings, mt5_comment, mt5_ticket, status)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13,$14)
               RETURNING id""",
            signal_id, stage_number, account_name, symbol, direction,
            band_low, band_high, band_low, band_high, target_lot,
            json.dumps(snapshot_settings), mt5_comment, mt5_ticket, status,
        )
    return row_id


async def _run_one_zone_watch_tick(executor_fixture) -> None:
    """Run exactly one body iteration of _zone_watch_loop (skip the sleep)."""
    import asyncio as _a
    ticks = {"n": 0}
    real_sleep = _a.sleep

    async def fake_sleep(delay):
        ticks["n"] += 1
        if ticks["n"] >= 2:
            raise _a.CancelledError()
        await real_sleep(0)

    _a.sleep = fake_sleep  # type: ignore[assignment]
    try:
        try:
            await executor_fixture._zone_watch_loop()
        except _a.CancelledError:
            pass
    finally:
        _a.sleep = real_sleep  # type: ignore[assignment]


async def test_zone_watch_fires_stage_when_price_enters_band(
    db_pool, seeded_staged_account, seeded_signal, priced_connector, executor_fixture,
):
    """D-11/D-14: an awaiting_zone stage fires when price enters its band.

    Setup:
      - stage 1 marked 'filled' with comment telebot-{sid}-s1 to satisfy D-16.
      - a Position matching that comment lives on the connector so D-16 sees it live.
      - stage 2 (awaiting_zone) whose band contains current price.
    """
    sid = seeded_signal
    # Price falls inside stage 2 band — BUY, ask <= band.high triggers.
    priced_connector._prices = {"XAUUSD": (2041.0, 2041.2)}
    # Stage 1 is filled on MT5 (so D-16 does NOT cascade).
    priced_connector._fake_positions[888001] = Position(
        ticket=888001, symbol="XAUUSD", direction="buy",
        volume=0.10, open_price=2040.1, sl=2038.0, tp=0.0,
        profit=0.0, comment=f"telebot-{sid}-s1",
    )
    await _insert_staged_row(
        signal_id=sid, stage_number=1, account_name=seeded_staged_account,
        band_low=2040.0, band_high=2040.1,
        mt5_comment=f"telebot-{sid}-s1", status="filled", mt5_ticket=888001,
    )
    await _insert_staged_row(
        signal_id=sid, stage_number=2, account_name=seeded_staged_account,
        band_low=2040.5, band_high=2042.0,
        mt5_comment=f"telebot-{sid}-s2", status="awaiting_zone",
    )

    await _run_one_zone_watch_tick(executor_fixture)

    row = await db.get_stage_by_comment(f"telebot-{sid}-s2")
    assert row is not None
    assert row["status"] == "filled", f"expected filled, got {row['status']}"
    assert row["mt5_ticket"] is not None


async def test_zone_watch_skips_when_trading_paused(
    db_pool, seeded_staged_account, seeded_signal, priced_connector, executor_fixture,
):
    """D-21: _trading_paused=True — loop body skips without any MT5 submit."""
    sid = seeded_signal
    priced_connector._prices = {"XAUUSD": (2041.0, 2041.2)}
    await _insert_staged_row(
        signal_id=sid, stage_number=2, account_name=seeded_staged_account,
        band_low=2040.5, band_high=2042.0,
        mt5_comment=f"telebot-{sid}-s2", status="awaiting_zone",
    )
    executor_fixture._trading_paused = True

    await _run_one_zone_watch_tick(executor_fixture)

    row = await db.get_stage_by_comment(f"telebot-{sid}-s2")
    assert row["status"] == "awaiting_zone"  # unchanged


async def test_zone_watch_idempotency_probe_marks_filled_without_submit(
    db_pool, seeded_staged_account, seeded_signal, priced_connector, executor_fixture,
):
    """D-25: MT5 already has a position with the stage's target comment.

    The loop must mark the stage filled and skip open_order.
    """
    sid = seeded_signal
    priced_connector._prices = {"XAUUSD": (2041.0, 2041.2)}
    comment = f"telebot-{sid}-s2"
    # Stage 1 is filled + on MT5 (so D-16 doesn't cascade).
    priced_connector._fake_positions[777001] = Position(
        ticket=777001, symbol="XAUUSD", direction="buy",
        volume=0.10, open_price=2040.1, sl=2038.0, tp=0.0,
        profit=0.0, comment=f"telebot-{sid}-s1",
    )
    await _insert_staged_row(
        signal_id=sid, stage_number=1, account_name=seeded_staged_account,
        band_low=2040.0, band_high=2040.1,
        mt5_comment=f"telebot-{sid}-s1", status="filled", mt5_ticket=777001,
    )
    # Stage 2 — already on MT5 via `comment` match.
    priced_connector._fake_positions[777002] = Position(
        ticket=777002, symbol="XAUUSD", direction="buy",
        volume=0.10, open_price=2041.1, sl=2038.0, tp=0.0,
        profit=0.0, comment=comment,
    )
    await _insert_staged_row(
        signal_id=sid, stage_number=2, account_name=seeded_staged_account,
        band_low=2040.5, band_high=2042.0,
        mt5_comment=comment, status="awaiting_zone",
    )

    before = len(priced_connector._fake_positions)
    await _run_one_zone_watch_tick(executor_fixture)
    after = len(priced_connector._fake_positions)

    row = await db.get_stage_by_comment(comment)
    assert row["status"] == "filled"
    assert row["mt5_ticket"] == 777002
    assert after == before, "no new positions should have been opened (idempotency probe)"


async def test_zone_watch_cancels_remaining_stages_when_stage1_closed(
    db_pool, seeded_staged_account, seeded_signal, priced_connector, executor_fixture, caplog,
):
    """D-16 cascade: stage 1 is filled in DB but its position is absent on MT5.

    Remaining unfilled stages transition to 'cancelled_stage1_closed' and no
    open_order fires.
    """
    sid = seeded_signal
    priced_connector._prices = {"XAUUSD": (2041.0, 2041.2)}
    # NO position with comment telebot-{sid}-s1 — stage 1 closed externally.
    await _insert_staged_row(
        signal_id=sid, stage_number=1, account_name=seeded_staged_account,
        band_low=2040.0, band_high=2040.1,
        mt5_comment=f"telebot-{sid}-s1", status="filled", mt5_ticket=555001,
    )
    await _insert_staged_row(
        signal_id=sid, stage_number=2, account_name=seeded_staged_account,
        band_low=2040.5, band_high=2042.0,
        mt5_comment=f"telebot-{sid}-s2", status="awaiting_zone",
    )
    before_positions = len(priced_connector._fake_positions)

    import logging as _lg
    with caplog.at_level(_lg.INFO):
        await _run_one_zone_watch_tick(executor_fixture)

    row = await db.get_stage_by_comment(f"telebot-{sid}-s2")
    assert row["status"] == "cancelled_stage1_closed"
    assert len(priced_connector._fake_positions) == before_positions, "no new fill"
    assert any("D-16 cascade" in rec.message for rec in caplog.records)


async def test_zone_watch_does_not_cascade_when_stage1_still_awaiting(
    db_pool, seeded_staged_account, seeded_signal, priced_connector, executor_fixture,
):
    """D-16 edge: stage 1 row exists but status='awaiting_followup' (not yet filled).

    No cascade; remaining stages stay awaiting_zone.
    """
    sid = seeded_signal
    # Price is OUTSIDE stage 2 band so the in-zone check won't fire either way;
    # this test specifically verifies "when stage 1 isn't filled, don't touch stage 2".
    priced_connector._prices = {"XAUUSD": (2100.0, 2100.2)}
    await _insert_staged_row(
        signal_id=sid, stage_number=1, account_name=seeded_staged_account,
        band_low=2040.0, band_high=2040.1,
        mt5_comment=f"telebot-{sid}-s1", status="awaiting_followup",
    )
    await _insert_staged_row(
        signal_id=sid, stage_number=2, account_name=seeded_staged_account,
        band_low=2040.5, band_high=2042.0,
        mt5_comment=f"telebot-{sid}-s2", status="awaiting_zone",
    )

    await _run_one_zone_watch_tick(executor_fixture)

    row = await db.get_stage_by_comment(f"telebot-{sid}-s2")
    assert row["status"] == "awaiting_zone"


async def test_emergency_close_drains_staged_before_positions(
    db_pool, seeded_staged_account, seeded_signal, priced_connector, executor_fixture,
):
    """D-21: emergency_close drains staged_entries BEFORE closing positions."""
    sid = seeded_signal
    for n in (1, 2, 3):
        await _insert_staged_row(
            signal_id=sid, stage_number=n, account_name=seeded_staged_account,
            band_low=2040.0 + n, band_high=2041.0 + n,
            mt5_comment=f"telebot-{sid}-s{n}", status="awaiting_zone",
        )

    result = await executor_fixture.emergency_close()

    assert result.get("drained_stages") == 3
    # All rows are now terminal cancelled
    for n in (1, 2, 3):
        row = await db.get_stage_by_comment(f"telebot-{sid}-s{n}")
        assert row["status"] == "cancelled_by_kill_switch", (
            f"stage {n}: {row['status']}"
        )
    # v1.0 keys preserved
    assert "closed_positions" in result
    assert "cancelled_orders" in result


async def test_resume_trading_does_not_uncancel_drained_stages(
    db_pool, seeded_staged_account, seeded_signal, executor_fixture,
):
    """D-22: drained stages stay cancelled after resume_trading()."""
    sid = seeded_signal
    await _insert_staged_row(
        signal_id=sid, stage_number=1, account_name=seeded_staged_account,
        mt5_comment=f"telebot-{sid}-s1", status="awaiting_zone",
    )

    await executor_fixture.emergency_close()
    executor_fixture.resume_trading()

    row = await db.get_stage_by_comment(f"telebot-{sid}-s1")
    assert row["status"] == "cancelled_by_kill_switch"
    assert executor_fixture._trading_paused is False


async def test_zone_watch_starts_and_stops_cleanly(executor_fixture):
    """Lifecycle: start() spawns _zone_watch_task; stop() cancels it cleanly."""
    await executor_fixture.start()
    try:
        assert executor_fixture._zone_watch_task is not None
        assert not executor_fixture._zone_watch_task.done()
    finally:
        await executor_fixture.stop()
    assert executor_fixture._zone_watch_task.done()


# ── Task 2 — reconnect reconciliation tests ──────────────────────────


async def test_reconnect_marks_filled_when_comment_exists_on_mt5(
    db_pool, seeded_staged_account, seeded_signal, priced_connector, executor_fixture,
):
    """D-24 (a/c): staged row matches MT5 position by comment → status='filled'."""
    sid = seeded_signal
    comment = f"telebot-{sid}-s2"
    await _insert_staged_row(
        signal_id=sid, stage_number=2, account_name=seeded_staged_account,
        mt5_comment=comment, status="awaiting_zone",
    )
    priced_connector._fake_positions[9001] = Position(
        ticket=9001, symbol="XAUUSD", direction="buy",
        volume=0.1, open_price=2041.0, sl=2038.0, tp=0.0,
        profit=0.0, comment=comment,
    )

    await executor_fixture._sync_positions(seeded_staged_account, priced_connector)

    row = await db.get_stage_by_comment(comment)
    assert row["status"] == "filled"
    assert row["mt5_ticket"] == 9001


async def test_reconnect_marks_abandoned_when_signal_aged_and_no_mt5_position(
    db_pool, seeded_staged_account, seeded_signal, priced_connector, executor_fixture,
):
    """D-24 (d): aged stage with no MT5 match → 'abandoned_reconnect'."""
    sid = seeded_signal
    comment = f"telebot-{sid}-s2"
    row_id = await _insert_staged_row(
        signal_id=sid, stage_number=2, account_name=seeded_staged_account,
        mt5_comment=comment, status="awaiting_zone",
    )
    # Backdate created_at to force age > signal_max_age_minutes (30 default).
    async with db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE staged_entries SET created_at=NOW() - INTERVAL '120 minutes' WHERE id=$1",
            row_id,
        )

    await executor_fixture._sync_positions(seeded_staged_account, priced_connector)

    row = await db.get_stage_by_comment(comment)
    assert row["status"] == "abandoned_reconnect"


async def test_reconnect_leaves_young_unfilled_stages_alone(
    db_pool, seeded_staged_account, seeded_signal, priced_connector, executor_fixture,
):
    """Young stages (< signal_max_age_minutes) with no MT5 match stay awaiting_zone."""
    sid = seeded_signal
    comment = f"telebot-{sid}-s2"
    await _insert_staged_row(
        signal_id=sid, stage_number=2, account_name=seeded_staged_account,
        mt5_comment=comment, status="awaiting_zone",
    )

    await executor_fixture._sync_positions(seeded_staged_account, priced_connector)

    row = await db.get_stage_by_comment(comment)
    assert row["status"] == "awaiting_zone"


async def test_reconnect_reconciliation_dry_on_empty_staged(
    db_pool, seeded_staged_account, priced_connector, executor_fixture,
):
    """No pending staged_entries → _sync_positions unchanged v1.0 behavior (no crash)."""
    await executor_fixture._sync_positions(seeded_staged_account, priced_connector)
