"""W4-PNL-DISPLAY — position-drilldown unit consistency + *_display twins.

Two findings:

  * sl_at_fill unit mix (db.get_position_drilldown): reported in PIPS for staged
    fills but as an ABSOLUTE PRICE for single-stage fills. Normalized to ONE unit
    (absolute price = the position's SL) in BOTH branches.

  * missing *_display twins (api.positions.position_drilldown): the SPA's
    PositionDrilldown renders *_display fields ONLY, so fill rows and the signal
    time showed em-dashes. The route must add filled_at_display / lot_size_display
    / band_low_display / band_high_display / sl_at_fill_display on each fill row
    and timestamp_display on the signal, mirroring the list route's twins.
"""
from __future__ import annotations

import pytest

import api.positions as positions_route
import db

pytestmark = pytest.mark.asyncio(loop_scope="session")

_TRADE_SL = 2030.0  # absolute price on the trades row


async def _seed_staged_position(ticket: int, account: str, signal_id: int) -> None:
    """Insert a trades row plus one FILLED staged_entries row bound to `ticket`."""
    await db.log_trade(
        signal_id=signal_id,
        account_name=account,
        symbol="XAUUSD",
        direction="buy",
        entry_price=2040.0,
        sl=_TRADE_SL,
        tp=2060.0,
        lot_size=0.05,
        ticket=ticket,
        status="opened",
        raw_signal="test",
    )
    ids = await db.create_staged_entries([
        {
            "signal_id": signal_id,
            "stage_number": 1,
            "account_name": account,
            "symbol": "XAUUSD",
            "direction": "buy",
            "zone_low": 2035.0,
            "zone_high": 2045.0,
            "band_low": 2036.0,
            "band_high": 2038.0,
            "target_lot": 0.05,
            # snapshot carries default_sl_pips (PIPS) — the OLD source of sl_at_fill.
            "snapshot_settings": {"default_sl_pips": 20, "max_stages": 1},
            "mt5_comment": "stage1",
        }
    ])
    # Bind the staged row to the ticket (drilldown matches on se.mt5_ticket).
    await db.update_stage_status(ids[0], "filled", mt5_ticket=ticket)


async def test_sl_at_fill_is_absolute_price_for_staged_fill(
    db_pool, seeded_account, seeded_signal,
):
    """Staged fills must report sl_at_fill as the absolute position SL, NOT the
    snapshot's default_sl_pips (20) — same unit as the single-stage branch."""
    ticket = 880001
    await _seed_staged_position(ticket, "test-acct", seeded_signal)

    detail = await db.get_position_drilldown(ticket, "test-acct")
    assert detail is not None
    assert len(detail["fill_history"]) == 1
    fill = detail["fill_history"][0]
    # Fails before the fix: was 20 (default_sl_pips, a PIPS value).
    assert fill["sl_at_fill"] == pytest.approx(_TRADE_SL)
    assert fill["sl_at_fill"] != 20


async def test_drilldown_route_adds_display_twins(
    db_pool, seeded_account, seeded_signal,
):
    """api.positions.position_drilldown enriches fill rows + signal with the
    *_display twins the SPA renders (otherwise em-dashes everywhere)."""
    ticket = 880101
    await _seed_staged_position(ticket, "test-acct", seeded_signal)

    # Call the handler directly (bypasses the require_user Depends).
    detail = await positions_route.position_drilldown(
        "test-acct", ticket, _user="tester",
    )

    fill = detail["fill_history"][0]
    assert fill["filled_at_display"]  # non-empty formatted timestamp
    assert fill["lot_size_display"] == "0.05"
    assert fill["band_low_display"] == "2036.00"   # XAUUSD 2dp
    assert fill["band_high_display"] == "2038.00"
    assert fill["sl_at_fill_display"] == "2030.00"  # absolute price, 2dp
    # Numeric fields are left untouched alongside the twins.
    assert fill["band_low"] == pytest.approx(2036.0)

    signal = detail["signal"]
    assert signal is not None
    assert signal["timestamp_display"]  # non-empty formatted signal time
    assert "UTC" in signal["timestamp_display"]


async def test_single_stage_drilldown_display_twins(
    db_pool, seeded_account, seeded_signal,
):
    """A single-stage trade (no staged_entries) still gets fill-row twins; band
    fields are None -> the SPA renders 'Market' (no band_*_display)."""
    ticket = 880201
    await db.log_trade(
        signal_id=seeded_signal,
        account_name="test-acct",
        symbol="XAUUSD",
        direction="buy",
        entry_price=2040.0,
        sl=_TRADE_SL,
        tp=2060.0,
        lot_size=0.10,
        ticket=ticket,
        status="opened",
        raw_signal="test",
    )

    detail = await positions_route.position_drilldown(
        "test-acct", ticket, _user="tester",
    )
    fill = detail["fill_history"][0]
    assert fill["lot_size_display"] == "0.10"
    assert fill["sl_at_fill_display"] == "2030.00"
    assert fill.get("band_low") is None
    assert "band_low_display" not in fill  # None fields get no twin (-> "Market")
