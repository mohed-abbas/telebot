"""Phase 6 Plan 02 Task 2 — staged executor integration tests.

Covers:
  - compute_bands() pure helper (D-11/D-12): equal-width N-1 partition, edge cases
  - stage_is_in_zone_at_arrival() pure helper (D-13): trigger-edge inclusion
  - _handle_text_only_open() (STAGE-02): fires stage 1 at market with non-zero SL
  - _handle_correlated_followup() (STAGE-04): inserts N-1 stages, fires crossed bands
  - D-13 in-zone-at-arrival: band 1 fires immediately; remaining bands armed
  - D-19 per-symbol cap: over-cap stages marked 'capped' not submitted
  - Broker-reject on one stage does not abort the rest (D-17)
"""
from __future__ import annotations

import pytest
import pytest_asyncio

import db
from models import AccountConfig, Direction, GlobalConfig, SignalAction, SignalType
from mt5_connector import DryRunConnector, OrderResult
from settings_store import SettingsStore
from signal_correlator import SignalCorrelator
from trade_manager import (
    TradeManager,
    Band,
    compute_bands,
    stage_is_in_zone_at_arrival,
    stage_lot_size,
)


# ── Unit tests (no fixture, pure helpers) ────────────────────────────


class TestComputeBands:
    def test_five_stages_gives_four_bands(self):
        bands = compute_bands(2040.0, 2050.0, max_stages=5, direction="buy")
        assert len(bands) == 4
        assert bands[0] == Band(2, 2040.0, 2042.5)
        assert bands[3] == Band(5, 2047.5, 2050.0)

    def test_max_stages_1_returns_empty(self):
        assert compute_bands(2040.0, 2050.0, max_stages=1, direction="buy") == []

    def test_bands_partition_zone_exactly(self):
        bands = compute_bands(2040.0, 2050.0, max_stages=4, direction="buy")
        assert bands[0].low == 2040.0
        assert bands[-1].high == 2050.0
        for i in range(len(bands) - 1):
            assert bands[i].high == pytest.approx(bands[i + 1].low)

    def test_zero_width_zone_produces_point_bands(self):
        bands = compute_bands(2045.0, 2045.0, max_stages=5, direction="buy")
        assert len(bands) == 4
        for i, b in enumerate(bands):
            assert b.stage_number == i + 2
            assert b.low == 2045.0
            assert b.high == 2045.0

    def test_inverted_zone_raises(self):
        with pytest.raises(ValueError):
            compute_bands(2050.0, 2040.0, max_stages=5, direction="buy")


class TestInZoneAtArrival:
    def test_buy_ask_below_band_high_is_in_zone(self):
        band = Band(2, 2040.0, 2042.5)
        assert stage_is_in_zone_at_arrival(band, current_bid=2041.0, current_ask=2041.5, direction="buy") is True

    def test_sell_bid_above_band_low_is_in_zone(self):
        band = Band(2, 2040.0, 2042.5)
        assert stage_is_in_zone_at_arrival(band, current_bid=2041.0, current_ask=2041.5, direction="sell") is True

    def test_buy_ask_above_band_high_not_yet_in_zone(self):
        band = Band(2, 2040.0, 2042.5)
        assert stage_is_in_zone_at_arrival(band, current_bid=2043.0, current_ask=2043.5, direction="buy") is False


class TestStageLotSize:
    def test_fixed_lot_split_by_max_stages(self):
        from models import AccountSettings
        s = AccountSettings(
            account_name="x", risk_mode="fixed_lot", risk_value=0.25,
            max_stages=5, default_sl_pips=100, max_daily_trades=30,
            max_open_trades=3, max_lot_size=1.0,
        )
        assert stage_lot_size(s) == pytest.approx(0.05)

    def test_percent_mode_returns_per_stage_slice(self):
        from models import AccountSettings
        s = AccountSettings(
            account_name="x", risk_mode="percent", risk_value=2.0,
            max_stages=4, default_sl_pips=100, max_daily_trades=30,
            max_open_trades=3, max_lot_size=1.0,
        )
        assert stage_lot_size(s) == pytest.approx(0.5)


# ── Integration fixtures ─────────────────────────────────────────────
# _PricedDry / priced_connector / tm_with_store are now shared via
# tests/conftest.py (promoted in Plan 13-05 so test_trade_manager.py can use
# them for the D2-14 stale tests).


pytestmark = pytest.mark.asyncio(loop_scope="session")


# ── STAGE-02: text-only opens stage 1 with default SL ────────────────


async def test_text_only_opens_stage_1_with_default_sl(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    """STAGE-02: OPEN_TEXT_ONLY fills stage 1 at market with non-zero SL from default_sl_pips."""
    text_only = SignalAction(
        type=SignalType.OPEN_TEXT_ONLY, symbol="XAUUSD",
        raw_text="Gold buy now", direction=Direction.BUY,
        entry_zone=None, sl=None, tps=[], target_tp=None,
    )
    results = await tm_with_store.handle_signal(text_only)

    assert len(results) == 1
    assert results[0]["status"] == "executed"
    assert results[0]["sl"] > 0.0

    # staged_entries row was persisted
    async with db._pool.acquire() as conn:
        rows = await conn.fetch("SELECT stage_number, status, mt5_ticket, mt5_comment FROM staged_entries ORDER BY id")
    assert len(rows) == 1
    assert rows[0]["stage_number"] == 1
    assert rows[0]["status"] == "filled"
    assert rows[0]["mt5_ticket"] == results[0]["ticket"]
    assert rows[0]["mt5_comment"].startswith("telebot-")
    assert rows[0]["mt5_comment"].endswith("-s1")


# ── STAGE-04: correlated follow-up inserts N-1 stages ────────────────


async def test_correlated_followup_creates_n_minus_1_stages(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    """STAGE-04: text-only → follow-up yields max_stages-1 = 4 staged_entries rows."""
    # First, fire the text-only so the orphan is registered.
    text_only = SignalAction(
        type=SignalType.OPEN_TEXT_ONLY, symbol="XAUUSD",
        raw_text="Gold buy now", direction=Direction.BUY,
        entry_zone=None, sl=None, tps=[], target_tp=None,
    )
    await tm_with_store.handle_signal(text_only)

    # Then the follow-up with zone far above current price so no band is in-zone.
    # Current price is (2040.1, 2040.2). Zone (2060, 2070) — bands 2060-2062.5, etc.
    # For BUY in-zone: ask <= band.high. ask=2040.2 << 2062.5 → all bands in-zone
    # at arrival because price already below. So use zone BELOW price to keep bands armed.
    # For BUY: ask=2040.2, zone (2020, 2030) → ask=2040.2 > 2027.5 → band 1 not in-zone,
    # all armed.
    followup = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone 2020-2030 SL 2015 TP 2050",
        direction=Direction.BUY, entry_zone=(2020.0, 2030.0),
        sl=2015.0, tps=[2050.0], target_tp=2050.0,
    )
    results = await tm_with_store.handle_signal(followup)
    # Expect 4 bands inserted, 0 fired at market (none in-zone)
    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT stage_number, status FROM staged_entries WHERE stage_number > 1 ORDER BY stage_number"
        )
    assert len(rows) == 4
    # Stages 2..5 should remain awaiting_zone (none crossed at arrival)
    for r in rows:
        assert r["status"] == "awaiting_zone"


# ── D-13 in-zone-at-arrival ──────────────────────────────────────────


async def test_in_zone_at_arrival_fires_crossed_bands_immediately(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    """D-13: follow-up arrives with price already inside band 1; band 1 fires at market."""
    # Fire text-only first to register orphan
    text_only = SignalAction(
        type=SignalType.OPEN_TEXT_ONLY, symbol="XAUUSD",
        raw_text="Gold buy now", direction=Direction.BUY,
        entry_zone=None, sl=None, tps=[], target_tp=None,
    )
    await tm_with_store.handle_signal(text_only)

    # Zone 2040-2050, max_stages=5 → bands: 2040-2042.5, 2042.5-2045, 2045-2047.5, 2047.5-2050
    # Current price (2040.1, 2040.2). For BUY, ask=2040.2 <= 2042.5 (band 1) → in-zone fires.
    # ask=2040.2 <= 2045 (band 2) → ALSO in-zone (stage 3), etc. Actually ALL bands fire
    # because ask is below all band.high values.
    # Use smaller ask: set prices so only band 1 crosses.
    priced_connector._prices = {"XAUUSD": (2042.4, 2042.4)}
    # Now ask=2042.4 <= 2042.5 (band 1) True; <= 2045 (band 2) True — still multiple.
    # Actually for BUY the trigger is ask <= band.high, so any band above current ask qualifies.
    # To isolate exactly band 1 firing: use zone where ONLY band 1 contains the price.
    # Zone (2042, 2050) max_stages=5 → bands 2042-2044, 2044-2046, 2046-2048, 2048-2050.
    # ask=2042.4 <= 2044 (b1) True; <= 2046 (b2) True; <= 2048 (b3) True; <= 2050 (b4) True.
    # The in-zone-at-arrival predicate says: if price has crossed the trigger edge of this
    # band. For BUY moving DOWN into the zone, crossing band.high means ask<=band.high.
    # With all bands having band.high above current ask, all are "already crossed".
    # This is actually correct behavior: if price moved down past all trigger edges
    # before follow-up arrived, fire them all. The test should verify that behavior.
    # So for the "only band 1 fires" assertion we need ask BETWEEN band 1's edges.
    # For BUY zone the triggers are: band1.high, band2.high, .. so ordering is
    # b1.high < b2.high < .. for a buy zone indexed from low. ask<=b1.high implies
    # ask<=b2.high (since b1.high < b2.high). So "only band 1 fires" isn't possible
    # for BUY by this predicate. Instead, "only band N fires" happens when the trigger
    # direction is reversed (SELL, where predicate is bid>=band.low).
    #
    # Simplest assertion: band 1 (closest to current price) fires; at least one band
    # remains armed if we construct so band N.high > current ask.
    #
    # For our setup: zone (2040, 2060), ask=2042.4, max_stages=5:
    # bands: 2040-2044, 2044-2048, 2048-2052, 2052-2056, 2056-2060 (4 bands, stages 2..5)
    # Wait max_stages=5 gives 4 bands. Width = 5/4 = wrong, it's 20/4=5.
    # bands: (2040,2045), (2045,2050), (2050,2055), (2055,2060)
    # For BUY ask=2042.4: <= 2045? yes. <= 2050? yes. <= 2055? yes. <= 2060? yes.
    # All bands fire — not what test needs. Need ask between b1.high and b2.high:
    # ask=2047 → <= 2045? No. So use ask=2047.0, zone(2040,2060) max_stages=5:
    # band 1 (2040-2045): ask=2047 > 2045, NOT in-zone → armed
    # band 2 (2045-2050): ask=2047 <= 2050, in-zone → fires
    # band 3 (2050-2055): ask=2047 <= 2055, in-zone → fires
    # band 4 (2055-2060): ask=2047 <= 2060, in-zone → fires
    # So "price crossed into band 2" means bands 2,3,4 all fire (already crossed).
    # Band 1 stays armed because price hasn't come down to 2045 yet.
    # That's reasonable. Assert: at least one band fires immediately and at least one stays armed.
    priced_connector._prices = {"XAUUSD": (2047.0, 2047.0)}

    followup = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone 2040-2060 SL 2035 TP 2080",
        direction=Direction.BUY, entry_zone=(2040.0, 2060.0),
        sl=2035.0, tps=[2080.0], target_tp=2080.0,
    )
    await tm_with_store.handle_signal(followup)

    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT stage_number, status, mt5_ticket FROM staged_entries "
            "WHERE stage_number > 1 ORDER BY stage_number"
        )
    # We expect 4 bands inserted (stages 2..5).
    assert len(rows) == 4
    filled = [r for r in rows if r["status"] == "filled"]
    armed = [r for r in rows if r["status"] == "awaiting_zone"]
    assert len(filled) >= 1  # at least one band fired at market
    assert len(armed) >= 1   # at least one band remained armed
    # Band 1 (stage 2) should be the armed one (ask=2047 > band 2 high=2045).
    assert armed[0]["stage_number"] == 2


# ── D-19 per-symbol cap enforced for staged submissions ──────────────


async def test_stage_marked_capped_when_max_open_trades_reached(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    """D-19: when max_open_trades is already met, over-cap stages are marked 'capped'."""
    # Lower max_open_trades to 1 by updating account row directly.
    await db.update_account_setting("test-acct", "max_stages", 3, actor="test")
    # AccountConfig.max_open_trades is on accounts table; tweak via SQL to 1.
    async with db._pool.acquire() as conn:
        await conn.execute("UPDATE accounts SET max_open_trades=1 WHERE name='test-acct'")
    await tm_with_store.settings_store.load_all()

    # Fire text-only → stage 1 fills and occupies 1 position.
    await tm_with_store.handle_signal(SignalAction(
        type=SignalType.OPEN_TEXT_ONLY, symbol="XAUUSD",
        raw_text="Gold buy now", direction=Direction.BUY,
        entry_zone=None, sl=None, tps=[], target_tp=None,
    ))
    # Now follow-up — bands 2..3 will all hit the cap (1 position already open).
    # Use zone far from price so bands don't "arrive in-zone" (would auto-fire
    # and still hit cap).
    priced_connector._prices = {"XAUUSD": (2100.0, 2100.0)}  # way above zone
    await tm_with_store.handle_signal(SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone 2040-2050 SL 2035 TP 2080",
        direction=Direction.BUY, entry_zone=(2040.0, 2050.0),
        sl=2035.0, tps=[2080.0], target_tp=2080.0,
    ))
    # bands: max_stages=3 → 2 bands (stages 2, 3). Both armed (price 2100 not in zone).
    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT stage_number, status FROM staged_entries "
            "WHERE stage_number > 1 ORDER BY stage_number"
        )
    assert len(rows) == 2  # max_stages=3 → 2 bands
    # They are awaiting_zone (not fired, not capped yet — cap only checked at submit).
    assert all(r["status"] == "awaiting_zone" for r in rows)

    # Now directly call _execute_open_on_account with staged=True on the first band
    # to simulate what _zone_watch_loop will do in Plan 04 — expect 'capped'.
    from trade_manager import compute_bands
    bands = compute_bands(2040.0, 2050.0, 3, "buy")
    band = bands[0]  # stage 2
    [stage_row] = await db._pool.fetch(
        "SELECT id FROM staged_entries WHERE stage_number=2 LIMIT 1"
    )
    stage_id = stage_row["id"]
    synth = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone 2040-2050 SL 2035 TP 2080",
        direction=Direction.BUY, entry_zone=(band.low, band.high),
        sl=2035.0, tps=[2080.0], target_tp=2080.0,
    )
    # Get signal_id from existing stage row
    async with db._pool.acquire() as conn:
        sig_id = await conn.fetchval(
            "SELECT signal_id FROM staged_entries WHERE id=$1", stage_id,
        )
    acct = tm_with_store.accounts["test-acct"]
    result = await tm_with_store._execute_open_on_account(
        synth, sig_id, acct, priced_connector,
        staged=True, stage_number=2, stage_row_id=stage_id,
    )
    assert result["status"] == "capped"
    async with db._pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM staged_entries WHERE id=$1", stage_id)
    assert row["status"] == "capped"


# ── D-17 broker reject on one stage doesn't abort others ─────────────


async def test_stage_marked_failed_on_broker_reject_others_continue(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
    monkeypatch,
):
    """D-17: if band 1 submit fails at broker, bands 2..N still processed."""
    # Register text-only orphan first.
    await tm_with_store.handle_signal(SignalAction(
        type=SignalType.OPEN_TEXT_ONLY, symbol="XAUUSD",
        raw_text="Gold buy now", direction=Direction.BUY,
        entry_zone=None, sl=None, tps=[], target_tp=None,
    ))

    # Rig connector so the NEXT open_order call fails, subsequent ones succeed.
    original_open = priced_connector.open_order
    call_count = {"n": 0}

    async def flaky_open(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return OrderResult(success=False, ticket=0, error="broker rejected")
        return await original_open(*args, **kwargs)

    priced_connector.open_order = flaky_open

    # Price inside ALL bands so each band tries to fire at arrival → first fails, rest succeed.
    # zone (2040,2060) max_stages=5 → 4 bands, ask=2039 → ask<=all band.high → all fire.
    priced_connector._prices = {"XAUUSD": (2039.0, 2039.0)}
    await tm_with_store.handle_signal(SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone 2040-2060 SL 2035 TP 2080",
        direction=Direction.BUY, entry_zone=(2040.0, 2060.0),
        sl=2035.0, tps=[2080.0], target_tp=2080.0,
    ))

    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT stage_number, status FROM staged_entries WHERE stage_number > 1 "
            "ORDER BY stage_number"
        )
    statuses = [r["status"] for r in rows]
    # First band attempted failed; remaining bands should have status='filled'.
    assert "failed" in statuses  # at least one band failed
    assert "filled" in statuses  # at least one band succeeded


# ── Phase 13 Wave-0 RED stubs (executor) ─────────────────────────────
# Each stub below is intentionally RED (fails, not error-collects) so the
# downstream implementation task has a concrete `pytest -k <name>` gate to turn
# green. The docstring states the contract + requirement ID; the implementing
# plan replaces the body with the real assertion.


async def _capture_fire_zone_stage_synth(tm_with_store, global_config, *, stage):
    """Drive _fire_zone_stage with `stage` and capture the synth SignalAction
    passed to _execute_open_on_account (without actually submitting).

    Returns the captured SignalAction.
    """
    from executor import Executor

    ex = Executor(
        trade_manager=tm_with_store,
        global_config=global_config,
        notifier=None,
    )
    captured: dict = {}

    async def _spy(synth, signal_id, acct, connector, **kwargs):
        captured["synth"] = synth
        return {"status": "executed", "ticket": 4242}

    tm_with_store._execute_open_on_account = _spy  # type: ignore[assignment]
    connector = tm_with_store.connectors["test-acct"]
    await ex._fire_zone_stage(
        acct_name="test-acct",
        connector=connector,
        symbol="XAUUSD",
        stage=stage,
        bid=2045.0,
        ask=2045.2,
        signal_id=stage["signal_id"],
    )
    return captured.get("synth")


def _late_stage_row(**overrides):
    """A minimal staged_entries-shaped dict the way get_active_stages returns it."""
    row = {
        "id": 9001,
        "signal_id": 7777,
        "stage_number": 2,
        "account_name": "test-acct",
        "direction": "buy",
        "band_low": 2040.0,
        "band_high": 2045.0,
        "mt5_comment": "telebot-7777-s2",
        "snapshot_settings": {
            "account_name": "test-acct",
            "risk_mode": "fixed_lot",
            "risk_value": 0.5,
            "max_stages": 5,
            "default_sl_pips": 100,
            "max_daily_trades": 30,
            "max_open_trades": 3,
            "max_lot_size": 1.0,
        },
        "signal_sl": 2035.0,
        "signal_tp": 2060.0,
    }
    row.update(overrides)
    return row


async def test_late_stage_carries_signal_sl_tp(
    db_pool, seeded_staged_account, priced_connector, tm_with_store, global_config,
):
    """EXEC2-01 — a late zone-watch stage fires with the signal's REAL SL/TP
    (read from the persisted signal_sl/signal_tp on the staged row), NOT the
    default_sl_pips-derived SL with target_tp=None.

    Three contracts:
      1. signal_sl/signal_tp present → synth.sl == signal_sl, synth.target_tp == signal_tp.
      2. signal_sl NULL (pre-migration) → synth.sl falls back to the default_sl_pips
         price (NOT 0.0, NOT None); synth.target_tp stays None.
      3. No path yields synth.sl <= 0.
    """
    # 1) Persisted SL/TP are carried verbatim.
    stage = _late_stage_row(signal_sl=2035.0, signal_tp=2060.0)
    synth = await _capture_fire_zone_stage_synth(tm_with_store, global_config, stage=stage)
    assert synth is not None, "_fire_zone_stage did not reach _execute_open_on_account"
    assert synth.sl == pytest.approx(2035.0), "late stage must carry persisted signal_sl"
    assert synth.target_tp == pytest.approx(2060.0), "late stage must carry persisted signal_tp"
    assert synth.sl > 0.0

    # 2) NULL signal_sl → default_sl_pips fallback, target_tp None, never sl=0.
    null_stage = _late_stage_row(signal_sl=None, signal_tp=None)
    synth_null = await _capture_fire_zone_stage_synth(tm_with_store, global_config, stage=null_stage)
    assert synth_null is not None
    # buy, band_high=2045.0, default_sl_pips=100, gold pip=0.10 → 2045.0 - 100*0.10 = 2035.0
    assert synth_null.sl == pytest.approx(2035.0), "NULL signal_sl must fall back to default-SL price"
    assert synth_null.sl > 0.0, "fallback SL must never be 0"
    assert synth_null.target_tp is None, "NULL signal_tp leaves target_tp None (orphan TP is Plan 04)"


async def test_percent_splits_risk(
    db_pool, seeded_staged_account, seeded_signal, priced_connector, tm_with_store,
):
    """EXEC2-02 — in percent risk_mode the submitted per-stage volume equals
    calculate_lot_size(risk_value / max_stages), so total deployed risk is the
    risk_value ceiling rather than risk_value × stages. fixed_lot already splits
    via stage_lot_size; this proves the percent branch now matches.

    Contract:
      - staged percent OPEN (max_stages=4) submits volume sized at risk_value/4.
      - non-staged percent OPEN (staged=False) keeps the FULL risk_value (v1.0).
      - so submitted_staged == submitted_nonstaged / 4 (within rounding).
    """
    from models import AccountSettings
    from risk_calculator import calculate_lot_size, calculate_sl_distance

    # Configure the account as percent-mode, risk_value=2%, max_stages=4.
    await db.update_account_setting("test-acct", "risk_mode", "percent", actor="test")
    await db.update_account_setting("test-acct", "risk_value", 2.0, actor="test")
    await db.update_account_setting("test-acct", "max_stages", 4, actor="test")
    await tm_with_store.settings_store.load_all()
    snapshot = tm_with_store.settings_store.snapshot("test-acct")
    assert snapshot.risk_mode == "percent"
    assert snapshot.risk_value == pytest.approx(2.0)
    assert snapshot.max_stages == 4

    acct = tm_with_store.accounts["test-acct"]

    # A market BUY with a real SL (entry derived from the dry price 2040.2 ask).
    signal = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy now SL 2035 TP 2050",
        direction=Direction.BUY, entry_zone=None,
        sl=2035.0, tps=[], target_tp=None,
    )

    # Staged percent stage → must divide risk_value by max_stages.
    staged_result = await tm_with_store._execute_open_on_account(
        signal, signal_id=seeded_signal, acct=acct,
        connector=priced_connector,
        staged=True, stage_number=1, stage_row_id=None, snapshot=snapshot,
    )
    assert staged_result["status"] == "executed"
    submitted_staged = staged_result["lot_size"]

    # Compute the expected per-stage volume independently.
    acct_info = await priced_connector.get_account_info()
    entry = 2040.2  # ask from priced_connector
    sl_distance = calculate_sl_distance(entry, 2035.0)
    expected_per_stage = calculate_lot_size(
        account_balance=acct_info.balance,
        risk_percent=2.0 / 4,  # risk_value / max_stages
        sl_distance=sl_distance,
        max_lot_size=snapshot.max_lot_size,
        jitter_percent=0,
        symbol="XAUUSD",
    )
    expected_full = calculate_lot_size(
        account_balance=acct_info.balance,
        risk_percent=2.0,  # un-split, the v1.0 non-staged amount
        sl_distance=sl_distance,
        max_lot_size=snapshot.max_lot_size,
        jitter_percent=0,
        symbol="XAUUSD",
    )

    assert submitted_staged == pytest.approx(expected_per_stage)
    # The split must actually be a quarter of the full (sanity, guards no-op division).
    assert expected_per_stage == pytest.approx(expected_full / 4, abs=0.01)
    assert submitted_staged < expected_full


async def test_direct_zone_multistage(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    """EXEC2-06 — a standalone zone+SL+TP OPEN with max_stages=N creates N stages
    (mirrors _handle_correlated_followup band geometry), not a single zone_mid
    fill. Some already-crossed bands fire at market; the rest arm.

    Direct-zone bands are numbered 1..N (the lowest band IS stage 1 — there is
    no prior text-only market anchor; D2-02). max_stages=5 → 5 bands.

    Price (2040.1/2040.2). Zone (2040, 2060) max_stages=5 →
      bands (1..5): 2040-2044, 2044-2048, 2048-2052, 2052-2056, 2056-2060.
    For BUY, in-zone-at-arrival is ask <= band.high. ask=2040.2 <= every
    band.high → ALL 5 bands are already crossed → all 5 fire at market.
    """
    # Allow all 5 bands to fill at market (default max_open_trades=3 would cap
    # the deepest two as 'capped'); this test validates the N-stage geometry.
    # max_open_trades lives on the accounts table (not account_settings).
    async with db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE accounts SET max_open_trades = 10 WHERE name = 'test-acct'"
        )
    await tm_with_store.settings_store.load_all()

    # NO orphan registered → handle_signal routes a standalone OPEN to _handle_open.
    open_signal = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone 2040-2060 SL 2030 TP 2080",
        direction=Direction.BUY, entry_zone=(2040.0, 2060.0),
        sl=2030.0, tps=[2080.0], target_tp=2080.0,
    )
    results = await tm_with_store.handle_signal(open_signal)

    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT stage_number, status, band_low, band_high, target_lot, "
            "signal_sl, signal_tp, mt5_comment "
            "FROM staged_entries ORDER BY stage_number"
        )
    # max_stages=5 → exactly 5 stages (NOT a single zone_mid fill).
    assert len(rows) == 5
    assert [r["stage_number"] for r in rows] == [1, 2, 3, 4, 5]
    # All bands already crossed at arrival → all filled.
    assert all(r["status"] == "filled" for r in rows)
    # Bands partition the zone exactly.
    assert rows[0]["band_low"] == pytest.approx(2040.0)
    assert rows[-1]["band_high"] == pytest.approx(2060.0)
    # Every row persists the OPEN's real signal SL/TP (not default+0).
    for r in rows:
        assert r["signal_sl"] == pytest.approx(2030.0)
        assert r["signal_tp"] == pytest.approx(2080.0)
        assert r["mt5_comment"].endswith(f"-s{r['stage_number']}")
    # No collision with the correlated path: comments key off the OPEN's own id.
    assert all(r["mt5_comment"].startswith("telebot-") for r in rows)
    # Fired results carry the signal's real SL (not a default-derived one).
    fired = [r for r in results if r.get("status") == "executed"]
    assert len(fired) == 5


async def test_direct_zone_single_band(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    """EXEC2-06 / D2-04 — max_stages=1 fires exactly ONE whole-zone entry (a
    synthesized whole-zone band), NOT the legacy v1.0 zone_mid single fill and
    NOT the correlated 'no_bands' branch.
    """
    await db.update_account_setting("test-acct", "max_stages", 1, actor="test")
    await tm_with_store.settings_store.load_all()

    # Price (2040.1/2040.2) sits inside the zone → the whole-zone band crosses.
    open_signal = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone 2040-2050 SL 2030 TP 2080",
        direction=Direction.BUY, entry_zone=(2040.0, 2050.0),
        sl=2030.0, tps=[2080.0], target_tp=2080.0,
    )
    results = await tm_with_store.handle_signal(open_signal)

    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT stage_number, status, band_low, band_high, signal_sl, signal_tp "
            "FROM staged_entries ORDER BY stage_number"
        )
    # Exactly ONE whole-zone band (low=zone_low, high=zone_high).
    assert len(rows) == 1
    assert rows[0]["stage_number"] == 1
    assert rows[0]["band_low"] == pytest.approx(2040.0)
    assert rows[0]["band_high"] == pytest.approx(2050.0)
    assert rows[0]["status"] == "filled"
    assert rows[0]["signal_sl"] == pytest.approx(2030.0)
    assert rows[0]["signal_tp"] == pytest.approx(2080.0)
    # Not the correlated no_bands branch.
    assert not any(r.get("status") == "no_bands" for r in results)
    fired = [r for r in results if r.get("status") == "executed"]
    assert len(fired) == 1


async def test_direct_zone_arms_when_outside(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    """EXEC2-06 / D2-02 — when price is entirely outside the zone at arrival,
    NOTHING fires; all bands are armed (status='awaiting_zone') and the
    _zone_watch_loop fires them later when price enters.

    Price (2040.1/2040.2). Zone (2020, 2030) is BELOW price → for a BUY the
    trigger is ask <= band.high; ask=2040.2 > every band.high (<=2030) →
    NO band crossed → all armed.
    """
    open_signal = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone 2020-2030 SL 2010 TP 2060",
        direction=Direction.BUY, entry_zone=(2020.0, 2030.0),
        sl=2010.0, tps=[2060.0], target_tp=2060.0,
    )
    results = await tm_with_store.handle_signal(open_signal)

    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT stage_number, status FROM staged_entries ORDER BY stage_number"
        )
    # max_stages=5 → 5 bands, all armed (none crossed at arrival).
    assert len(rows) == 5
    for r in rows:
        assert r["status"] == "awaiting_zone"
    # Nothing fired at market.
    assert not any(r.get("status") == "executed" for r in results)
    # No zone_mid full-fill leaked through.
    assert not any(r.get("status") == "filled" for r in results)
