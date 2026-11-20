"""Per-entry take-profit (stage_tp_map) — TP-01..TP-09.

Each entry of a staged sequence can target its own provider TP: e.g. entries
1–3 on TP2 and the two deepest entries on TP3. The SL is shared. Covers the
selection helper, both band paths (correlated follow-up and direct zone), the
fallback when a signal has fewer TPs, the per-row SL/TP sweep, the target
cascade over mixed TPs and old snapshots. The settings API and /stages tests
live in test_api_settings.py and test_api_contract.py.
"""
from __future__ import annotations

import json
import logging

import pytest

import db
from executor import Executor
from models import AccountSettings, Direction, SignalAction, SignalType
from mt5_connector import Position
from trade_manager import entry_target_tp

MAP = [2, 2, 2, 3, 3]


def _settings(stage_tp_map=()) -> AccountSettings:
    return AccountSettings(
        account_name="x", risk_mode="fixed_lot", risk_value=0.2,
        max_stages=5, default_sl_pips=50, max_daily_trades=30,
        max_open_trades=5, max_lot_size=1.0, stage_tp_map=tuple(stage_tp_map),
    )


def _sell(tps, *, zone=(2050.0, 2060.0), sl=2070.0) -> SignalAction:
    return SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text=f"Gold sell zone {zone[0]}-{zone[1]} SL {sl}",
        direction=Direction.SELL, entry_zone=zone, sl=sl,
        tps=list(tps), target_tp=tps[1] if len(tps) > 1 else tps[-1],
    )


async def _use_map(tm, tp_map, *, cap: int = 10) -> None:
    await db.update_account_setting("test-acct", "stage_tp_map", tp_map, actor="test")
    async with db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE accounts SET max_open_trades = $1 WHERE name = 'test-acct'", cap,
        )
    await tm.settings_store.load_all()


async def _rows() -> list:
    async with db._pool.acquire() as conn:
        return await conn.fetch(
            "SELECT stage_number, status, band_low, band_high, signal_sl, signal_tp "
            "FROM staged_entries ORDER BY stage_number"
        )


# ── Selection helper (pure) ──────────────────────────────────────────────


class TestEntryTargetTp:
    TPS = [2040.0, 2030.0, 2020.0, 2010.0]

    def _sig(self, tps):
        return _sell(tps)

    def test_tp02_mapping_picks_each_entrys_tp(self):
        sig, snap = self._sig(self.TPS), _settings(MAP)
        assert [entry_target_tp(sig, n, snap) for n in range(1, 6)] == [
            2030.0, 2030.0, 2030.0, 2020.0, 2020.0,
        ]

    def test_entry_past_the_map_uses_signal_default(self):
        sig = self._sig(self.TPS)
        assert entry_target_tp(sig, 3, _settings([3])) == sig.target_tp
        assert entry_target_tp(sig, 1, _settings([3])) == 2020.0

    def test_tp04_fewer_tps_falls_back_to_last_numeric(self):
        sig = self._sig([2040.0, 2030.0])
        snap = _settings(MAP)
        assert entry_target_tp(sig, 4, snap) == 2030.0
        assert entry_target_tp(sig, 5, snap) == 2030.0

    def test_open_tp_is_skipped_when_counting(self):
        sig = self._sig([2040.0, 2030.0, "open"])
        assert entry_target_tp(sig, 1, _settings([3])) == 2030.0

    def test_tp08_empty_map_and_no_snapshot_keep_todays_tp(self):
        sig = self._sig(self.TPS)
        for n in range(1, 6):
            assert entry_target_tp(sig, n, _settings()) == sig.target_tp
            assert entry_target_tp(sig, n, None) == sig.target_tp


class TestSnapshotRebuild:
    BASE = {
        "account_name": "x", "risk_mode": "fixed_lot", "risk_value": 0.2,
        "max_stages": 5, "default_sl_pips": 50, "max_daily_trades": 30,
        "max_open_trades": 3, "max_lot_size": 1.0,
    }

    def test_tp07_snapshot_without_the_new_field_rebuilds(self):
        s = AccountSettings.from_snapshot(dict(self.BASE))
        assert s.stage_tp_map == ()
        assert s.tp_index_for_entry(1) is None

    def test_json_list_becomes_tuple(self):
        s = AccountSettings.from_snapshot({**self.BASE, "stage_tp_map": [2, 3]})
        assert s.stage_tp_map == (2, 3)
        assert s.tp_index_for_entry(2) == 3

    def test_missing_required_field_still_fails(self):
        data = dict(self.BASE)
        del data["max_stages"]
        with pytest.raises(KeyError):
            AccountSettings.from_snapshot(data)


# ── Band paths ───────────────────────────────────────────────────────────


async def test_tp02_direct_zone_sell_deep_entries_get_tp3(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    """Direct zone, SELL above price (all armed): entries 1–3 TP2, 4–5 TP3, and
    4–5 are the highest (deepest) bands."""
    await _use_map(tm_with_store, MAP)
    await tm_with_store.handle_signal(_sell([2040.0, 2030.0, 2020.0, 2010.0]))

    rows = await _rows()
    assert [r["stage_number"] for r in rows] == [1, 2, 3, 4, 5]
    assert [r["signal_tp"] for r in rows] == [2030.0, 2030.0, 2030.0, 2020.0, 2020.0]
    assert all(r["signal_sl"] == pytest.approx(2070.0) for r in rows)
    assert rows[4]["band_low"] > rows[0]["band_low"]


async def test_tp03_direct_zone_buy_deep_entries_are_the_lowest(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    await _use_map(tm_with_store, MAP)
    buy = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone 2020-2030 SL 2010",
        direction=Direction.BUY, entry_zone=(2020.0, 2030.0), sl=2010.0,
        tps=[2050.0, 2060.0, 2070.0], target_tp=2060.0,
    )
    await tm_with_store.handle_signal(buy)

    rows = await _rows()
    assert [r["signal_tp"] for r in rows] == [2060.0, 2060.0, 2060.0, 2070.0, 2070.0]
    assert rows[4]["band_high"] < rows[0]["band_high"]
    assert rows[3]["band_high"] < rows[2]["band_high"]


async def test_tp04_direct_zone_signal_with_two_tps(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    await _use_map(tm_with_store, MAP)
    await tm_with_store.handle_signal(_sell([2040.0, 2030.0]))
    assert {r["signal_tp"] for r in await _rows()} == {2030.0}


async def test_tp02_correlated_path_and_stage1_alignment(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    """Text-only fires entry 1 at market; the follow-up aligns it to entry 1's
    TP and arms entries 2–5 with their own TPs."""
    await _use_map(tm_with_store, [3, 2, 2, 3, 3])
    await tm_with_store.handle_signal(SignalAction(
        type=SignalType.OPEN_TEXT_ONLY, symbol="XAUUSD", raw_text="Gold sell now",
        direction=Direction.SELL, entry_zone=None, sl=None, tps=[], target_tp=None,
    ))
    await tm_with_store.handle_signal(_sell([2035.0, 2030.0, 2020.0, 2010.0]))

    rows = await _rows()
    assert [r["stage_number"] for r in rows] == [1, 2, 3, 4, 5]
    assert [r["signal_tp"] for r in rows] == [2020.0, 2030.0, 2030.0, 2020.0, 2020.0]
    stage1 = [p for p in await priced_connector.get_positions() if p.comment.endswith("-s1")]
    assert len(stage1) == 1
    assert stage1[0].tp == pytest.approx(2020.0)


# ── SL/TP sweep keeps each entry on its own TP (TP-05) ───────────────────


async def _insert_row(sid, stage_number, *, status, signal_tp, direction="sell",
                      band=(2050.0, 2052.0), ticket=None, snapshot=None):
    snap = snapshot if snapshot is not None else {
        "account_name": "test-acct", "risk_mode": "fixed_lot", "risk_value": 0.5,
        "max_stages": 5, "default_sl_pips": 100, "max_daily_trades": 30,
        "max_open_trades": 10, "max_lot_size": 1.0, "stage_tp_map": MAP,
    }
    async with db._pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO staged_entries
               (signal_id, stage_number, account_name, symbol, direction,
                zone_low, zone_high, band_low, band_high, target_lot,
                snapshot_settings, mt5_comment, mt5_ticket, status,
                signal_sl, signal_tp)
               VALUES ($1,$2,'test-acct','XAUUSD',$3,2050,2060,$4,$5,0.1,
                       $6::jsonb,$7,$8,$9,2070,$10)""",
            sid, stage_number, direction, band[0], band[1], json.dumps(snap),
            f"telebot-{sid}-s{stage_number}", ticket, status, signal_tp,
        )


def _pos(ticket, sid, stage, tp):
    return Position(
        ticket=ticket, symbol="XAUUSD", direction="sell", volume=0.1,
        open_price=2050.0, sl=2070.0, tp=tp, profit=0.0,
        comment=f"telebot-{sid}-s{stage}",
    )


async def test_tp05_sweep_keeps_each_entry_on_its_own_tp(
    db_pool, seeded_staged_account, seeded_signal, priced_connector,
    tm_with_store, global_config,
):
    sid = seeded_signal
    await _insert_row(sid, 1, status="filled", signal_tp=2030.0, ticket=71001)
    await _insert_row(sid, 4, status="filled", signal_tp=2020.0, ticket=71004)
    await _insert_row(sid, 5, status="filled", signal_tp=2020.0, ticket=71005)
    priced_connector._fake_positions[71001] = _pos(71001, sid, 1, 2030.0)
    priced_connector._fake_positions[71004] = _pos(71004, sid, 4, 2020.0)
    # Entry 5 lost its TP at the broker: it must go back to TP3, not TP2.
    priced_connector._fake_positions[71005] = _pos(71005, sid, 5, 0.0)

    modified: list[tuple[int, float | None]] = []
    original = priced_connector.modify_position

    async def _spy(ticket, sl=None, tp=None, **kw):
        modified.append((ticket, tp))
        return await original(ticket, sl=sl, tp=tp, **kw)

    priced_connector.modify_position = _spy  # type: ignore[assignment]
    ex = Executor(trade_manager=tm_with_store, global_config=global_config, notifier=None)
    await ex._run_stage_sltp_verification_sweep()

    assert modified == [(71005, 2020.0)]
    tps = {t: p.tp for t, p in priced_connector._fake_positions.items()}
    assert tps[71001] == pytest.approx(2030.0)
    assert tps[71004] == pytest.approx(2020.0)
    assert tps[71005] == pytest.approx(2020.0)


# ── Target cascade over mixed TPs (TP-06) ────────────────────────────────


async def _tick(tm, global_config):
    ex = Executor(trade_manager=tm, global_config=global_config, notifier=None)
    await ex._zone_watch_tick()


async def _seed_mixed_sell(sid, priced_connector):
    """Entry 1 filled on TP2 (2030) and live; entries 4–5 armed on TP3 (2020)."""
    await _insert_row(sid, 1, status="filled", signal_tp=2030.0, ticket=72001,
                      band=(2040.0, 2040.1))
    await _insert_row(sid, 4, status="awaiting_zone", signal_tp=2020.0,
                      band=(2055.0, 2057.5))
    await _insert_row(sid, 5, status="awaiting_zone", signal_tp=2020.0,
                      band=(2057.5, 2060.0))
    priced_connector._fake_positions[72001] = _pos(72001, sid, 1, 2030.0)


async def test_tp06_nearest_tp_of_the_sequence_cancels_every_unfilled_entry(
    db_pool, seeded_staged_account, seeded_signal, priced_connector,
    tm_with_store, global_config, caplog,
):
    """Price reaches TP2 (entry 1's TP) but not TP3 (the armed rows' TP): the
    sequence is over, so entries 4–5 are cancelled."""
    sid = seeded_signal
    await _seed_mixed_sell(sid, priced_connector)
    priced_connector._prices = {"XAUUSD": (2029.8, 2029.9)}

    with caplog.at_level(logging.INFO):
        await _tick(tm_with_store, global_config)

    status = {r["stage_number"]: r["status"] for r in await _rows()}
    assert status == {1: "filled", 4: "cancelled_target_reached",
                      5: "cancelled_target_reached"}
    assert any("tp_reached" in r.message for r in caplog.records)


async def test_tp06_before_the_nearest_tp_nothing_is_cancelled(
    db_pool, seeded_staged_account, seeded_signal, priced_connector,
    tm_with_store, global_config,
):
    sid = seeded_signal
    await _seed_mixed_sell(sid, priced_connector)
    priced_connector._prices = {"XAUUSD": (2035.0, 2035.2)}

    await _tick(tm_with_store, global_config)

    status = {r["stage_number"]: r["status"] for r in await _rows()}
    assert status == {1: "filled", 4: "awaiting_zone", 5: "awaiting_zone"}


async def test_sequence_target_tps_ignores_missing_tps(db_pool, seeded_account, seeded_signal):
    sid = seeded_signal
    await _insert_row(sid, 1, status="filled", signal_tp=2030.0)
    await _insert_row(sid, 2, status="awaiting_zone", signal_tp=None)
    await _insert_row(sid, 3, status="awaiting_zone", signal_tp=0.0)
    got = await db.get_sequence_target_tps([sid], "test-acct")
    assert got == {sid: [2030.0]}
    assert await db.get_sequence_target_tps([sid], "other-acct") == {}


# ── Old snapshots still fire (TP-07) ─────────────────────────────────────


async def test_tp07_armed_row_with_old_snapshot_fires_with_its_stored_tp(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
    global_config, caplog,
):
    old_snapshot = {
        "account_name": "test-acct", "risk_mode": "fixed_lot", "risk_value": 0.5,
        "max_stages": 5, "default_sl_pips": 100, "max_daily_trades": 30,
        "max_open_trades": 3, "max_lot_size": 1.0,
    }
    stage = {
        "id": 9101, "signal_id": 7778, "stage_number": 4, "account_name": "test-acct",
        "direction": "sell", "band_low": 2044.0, "band_high": 2046.0,
        "mt5_comment": "telebot-7778-s4", "snapshot_settings": old_snapshot,
        "signal_sl": 2070.0, "signal_tp": 2020.0,
    }
    ex = Executor(trade_manager=tm_with_store, global_config=global_config, notifier=None)
    captured = {}

    async def _spy(synth, signal_id, acct, connector, **kwargs):
        captured["synth"] = synth
        return {"status": "executed", "ticket": 4243}

    tm_with_store._execute_open_on_account = _spy  # type: ignore[assignment]
    with caplog.at_level(logging.ERROR):
        await ex._fire_zone_stage(
            acct_name="test-acct", connector=priced_connector, symbol="XAUUSD",
            stage=stage, bid=2045.0, ask=2045.2, signal_id=7778,
        )
    assert not any("snapshot rebuild failed" in r.message for r in caplog.records)
    assert captured["synth"].target_tp == pytest.approx(2020.0)
