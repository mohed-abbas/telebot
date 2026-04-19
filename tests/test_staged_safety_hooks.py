"""Safety-hook tests for Phase 6 Plan 02 (D-08, D-23).

Covers:
  - D-08 hard-reject of sl <= 0.0 in _execute_open_on_account
  - D-23 duplicate-direction guard bypass for sibling stages (matching signal_id)
  - D-23 negative case — unrelated same-direction still rejected

Kill-switch drain + reconnect idempotency are Plan 04's concern.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

import db
from models import AccountConfig, Direction, GlobalConfig, SignalAction, SignalType
from mt5_connector import DryRunConnector, OrderType, Position
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
