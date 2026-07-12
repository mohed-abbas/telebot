"""Tests for trade_manager.py -- zone logic, stale checks, execution flow."""

import pytest

from models import Direction, SignalAction, SignalType
from mt5_connector import OrderType
from trade_manager import TradeManager


@pytest.fixture
def tm(connector, account, global_config):
    return TradeManager(
        connectors={account.name: connector},
        accounts=[account],
        global_config=global_config,
    )


class TestStaleCheck:
    def test_sell_price_below_tp1_is_stale(self, tm):
        signal = SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="test",
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0), sl=4986.0,
            tps=[4975.0, 4973.0], target_tp=4973.0,
        )
        result = tm._check_stale(signal, current_price=4970.0)
        assert result is not None
        assert "below TP1" in result

    def test_sell_price_above_tp1_not_stale(self, tm):
        signal = SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="test",
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0), sl=4986.0,
            tps=[4975.0, 4973.0], target_tp=4973.0,
        )
        result = tm._check_stale(signal, current_price=4980.0)
        assert result is None

    def test_buy_price_above_tp1_is_stale(self, tm):
        signal = SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="test",
            direction=Direction.BUY,
            entry_zone=(2140.0, 2145.0), sl=2135.0,
            tps=[2150.0, 2155.0], target_tp=2155.0,
        )
        result = tm._check_stale(signal, current_price=2155.0)
        assert result is not None

    def test_buy_price_below_tp1_not_stale(self, tm):
        signal = SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="test",
            direction=Direction.BUY,
            entry_zone=(2140.0, 2145.0), sl=2135.0,
            tps=[2150.0, 2155.0], target_tp=2155.0,
        )
        result = tm._check_stale(signal, current_price=2142.0)
        assert result is None

    def test_no_tps_not_stale(self, tm):
        signal = SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="test",
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0), sl=4986.0,
            tps=[], target_tp=None,
        )
        result = tm._check_stale(signal, current_price=4970.0)
        assert result is None


class TestDetermineOrderType:
    def test_sell_price_in_zone_market(self, tm):
        use_market, limit_price = tm._determine_order_type(
            Direction.SELL, current_price=4980.0, zone_low=4978.0, zone_high=4982.0,
        )
        assert use_market is True

    def test_sell_price_above_zone_market(self, tm):
        use_market, limit_price = tm._determine_order_type(
            Direction.SELL, current_price=4985.0, zone_low=4978.0, zone_high=4982.0,
        )
        assert use_market is True

    def test_sell_price_below_zone_limit(self, tm):
        use_market, limit_price = tm._determine_order_type(
            Direction.SELL, current_price=4975.0, zone_low=4978.0, zone_high=4982.0,
        )
        assert use_market is False
        assert limit_price == 4980.0  # zone midpoint

    def test_buy_price_in_zone_market(self, tm):
        use_market, limit_price = tm._determine_order_type(
            Direction.BUY, current_price=2142.0, zone_low=2140.0, zone_high=2145.0,
        )
        assert use_market is True

    def test_buy_price_below_zone_market(self, tm):
        use_market, limit_price = tm._determine_order_type(
            Direction.BUY, current_price=2138.0, zone_low=2140.0, zone_high=2145.0,
        )
        assert use_market is True

    def test_buy_price_above_zone_limit(self, tm):
        use_market, limit_price = tm._determine_order_type(
            Direction.BUY, current_price=2150.0, zone_low=2140.0, zone_high=2145.0,
        )
        assert use_market is False
        assert limit_price == 2142.5  # zone midpoint


@pytest.mark.asyncio(loop_scope="session")
class TestCloseSignal:
    async def test_close_all_positions(self, db_pool, tm, connector):
        # Open a position first
        await connector.open_order("XAUUSD", OrderType.MARKET_SELL, 0.10, price=4980.0, sl=4986.0, tp=4973.0)
        positions = await connector.get_positions("XAUUSD")
        assert len(positions) == 1

        signal = SignalAction(type=SignalType.CLOSE, symbol="XAUUSD", raw_text="Close gold")
        results = await tm.handle_signal(signal)

        assert len(results) == 1
        assert results[0]["status"] == "closed"

        positions = await connector.get_positions("XAUUSD")
        assert len(positions) == 0


@pytest.mark.asyncio(loop_scope="session")
class TestModifySL:
    async def test_move_sl_to_breakeven(self, db_pool, tm, connector):
        await connector.open_order("XAUUSD", OrderType.MARKET_SELL, 0.10, price=4980.0, sl=4986.0, tp=4973.0)

        signal = SignalAction(
            type=SignalType.MODIFY_SL, symbol="XAUUSD", raw_text="Move SL to BE",
            new_sl=0.0,  # sentinel for breakeven
        )
        results = await tm.handle_signal(signal)
        assert len(results) == 1
        assert results[0]["status"] == "sl_modified"
        assert results[0]["new_sl"] == 4980.0  # entry price


# ── Phase 5 (D-24, D-27): SettingsStore replaces AccountConfig for risk reads ──


@pytest.mark.asyncio(loop_scope="session")
async def test_lot_sized_against_settings_store_value_not_accountconfig(
    db_pool, seeded_account, global_config, connector,
):
    """When SettingsStore has risk_value=5.0, it overrides
    AccountConfig.risk_percent=1.0 in trade_manager's hot path (D-24 + D-27).
    """
    import db
    from settings_store import SettingsStore
    from trade_manager import TradeManager, _effective
    from models import AccountConfig

    await db.update_account_setting(seeded_account, "risk_value", 5.0)

    store = SettingsStore(db_pool=db_pool)
    await store.load_all()

    acct = AccountConfig(
        name=seeded_account, server="T", login=1, password_env="",
        risk_percent=1.0,  # deliberately different from DB's 5.0
        max_lot_size=1.0, max_daily_loss_percent=3.0, max_open_trades=3, enabled=True,
    )
    tm = TradeManager({seeded_account: connector}, [acct], global_config)
    tm.settings_store = store

    risk_pct, max_lot, max_open = _effective(tm, acct)
    assert risk_pct == 5.0, "DB risk_value must override AccountConfig.risk_percent"
    assert max_lot == 1.0
    assert max_open == 3


@pytest.mark.asyncio(loop_scope="session")
async def test_fallback_when_no_settings_store(global_config, connector):
    """v1.0 harness compatibility: TradeManager without SettingsStore still reads
    from AccountConfig (unit tests, dry-run demos must keep working)."""
    from trade_manager import TradeManager, _effective
    from models import AccountConfig
    acct = AccountConfig(
        name="legacy", server="T", login=1, password_env="",
        risk_percent=2.0, max_lot_size=0.5, max_daily_loss_percent=3.0,
        max_open_trades=2, enabled=True,
    )
    tm = TradeManager({"legacy": connector}, [acct], global_config)
    # settings_store stays None (the default)
    risk_pct, max_lot, max_open = _effective(tm, acct)
    assert (risk_pct, max_lot, max_open) == (2.0, 0.5, 2)


@pytest.mark.asyncio(loop_scope="session")
async def test_fixed_lot_mode_uses_accountconfig_risk_percent(
    db_pool, seeded_account, global_config, connector,
):
    """When risk_mode == 'fixed_lot', risk_value carries the lot size, not a
    percent — fall back to AccountConfig.risk_percent for the risk-percent
    signal so downstream calculate_lot_size keeps its existing semantics.
    """
    import db
    from settings_store import SettingsStore
    from trade_manager import TradeManager, _effective
    from models import AccountConfig

    await db.update_account_setting(seeded_account, "risk_mode", "fixed_lot")
    await db.update_account_setting(seeded_account, "risk_value", 0.5)

    store = SettingsStore(db_pool=db_pool)
    await store.load_all()

    acct = AccountConfig(
        name=seeded_account, server="T", login=1, password_env="",
        risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
        max_open_trades=3, enabled=True,
    )
    tm = TradeManager({seeded_account: connector}, [acct], global_config)
    tm.settings_store = store

    risk_pct, _, _ = _effective(tm, acct)
    assert risk_pct == 1.0, "fixed_lot mode falls back to AccountConfig.risk_percent"


# ── Bug #2 regression: fixed_lot must reach MT5 ─────────────────────────────

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock


@dataclass
class _StubSnapshot:
    """Minimal AccountSettings stand-in for fixed_lot branch tests."""
    risk_mode: str
    risk_value: float
    max_stages: int
    max_lot_size: float
    default_sl_pips: int = 100


class TestFixedLotBranch:
    """Bug #2 regression: snapshot.risk_mode='fixed_lot' must route the
    operator-configured volume to connector.open_order — _execute_open_on_account
    previously ignored snapshot.risk_mode and always called calculate_lot_size().
    """

    @pytest.fixture
    def signal(self):
        return SignalAction(
            type=SignalType.OPEN_TEXT_ONLY, symbol="XAUUSD", raw_text="t",
            direction=Direction.BUY, entry_zone=None,
            sl=2790.0, tps=[], target_tp=None,
        )

    @pytest.fixture(autouse=True)
    def _patch_db(self, monkeypatch):
        """Patch all db.* calls _execute_open_on_account touches so the path
        runs to open_order without a real Postgres connection.

        Kept minimal: only the symbols actually called along the success path
        for a text-only BUY (entry_zone=None, no TPs, no limit order)."""
        import trade_manager as tm_mod

        # Read paths — return non-blocking values
        monkeypatch.setattr(tm_mod.db, "get_daily_stat", AsyncMock(return_value=0))
        monkeypatch.setattr(tm_mod.db, "get_stage_by_comment", AsyncMock(return_value=None))
        # Write paths — no-op
        monkeypatch.setattr(tm_mod.db, "increment_daily_stat", AsyncMock(return_value=None))
        monkeypatch.setattr(tm_mod.db, "mark_signal_counted_today", AsyncMock(return_value=False))
        monkeypatch.setattr(tm_mod.db, "update_stage_status", AsyncMock(return_value=None))
        monkeypatch.setattr(tm_mod.db, "log_trade", AsyncMock(return_value=None))

    async def _run(self, tm, signal, snapshot):
        """Drive _execute_open_on_account once and return the open_order spy."""
        connector = next(iter(tm.connectors.values()))
        acct = next(iter(tm.accounts.values()))
        # Text-only path: entry_zone is None → no auto-feed of simulated price.
        # Seed one explicitly so connector.get_price() returns (bid, ask).
        connector.set_simulated_price(signal.symbol, 2799.5, 2800.0)
        spy = AsyncMock(return_value=MagicMock(
            success=True, ticket=12345, price=2800.0, retcode=10009, comment="ok",
        ))
        connector.open_order = spy
        await tm._execute_open_on_account(
            signal, signal_id=1, acct=acct, connector=connector,
            staged=True, stage_number=1, stage_row_id=None, snapshot=snapshot,
        )
        return spy

    async def test_fixed_lot_mode_sends_configured_volume(self, tm, signal):
        snapshot = _StubSnapshot(
            risk_mode="fixed_lot", risk_value=0.04,
            max_stages=1, max_lot_size=1.0,
        )
        spy = await self._run(tm, signal, snapshot)
        assert spy.await_count == 1
        assert spy.call_args.kwargs["volume"] == 0.04

    async def test_fixed_lot_mode_caps_at_max_lot_size(self, tm, signal):
        snapshot = _StubSnapshot(
            risk_mode="fixed_lot", risk_value=2.0,
            max_stages=1, max_lot_size=0.5,
        )
        spy = await self._run(tm, signal, snapshot)
        assert spy.call_args.kwargs["volume"] == 0.5

    async def test_fixed_lot_mode_floors_at_001(self, tm, signal):
        snapshot = _StubSnapshot(
            risk_mode="fixed_lot", risk_value=0.001,
            max_stages=1, max_lot_size=1.0,
        )
        spy = await self._run(tm, signal, snapshot)
        assert spy.call_args.kwargs["volume"] == 0.01


# ── Quick 260501-mrw: stage-1 SL/TP alignment with correlated follow-up ──


from risk_calculator import calculate_sl_with_jitter, calculate_tp_with_jitter
from mt5_connector import OrderResult


@dataclass
class _StubBandSnapshot:
    """Minimal AccountSettings stand-in for follow-up band-creation tests.

    max_stages=2 → compute_bands returns one band (stage 2), exercising the
    band-creation path so tests can assert it ran alongside stage-1 alignment.
    """
    account_name: str = "test-acct"
    risk_mode: str = "fixed_lot"
    risk_value: float = 0.01
    max_stages: int = 2
    default_sl_pips: int = 100
    max_daily_trades: int = 30
    max_open_trades: int = 3
    max_lot_size: float = 1.0


class _StubStore:
    """Minimal SettingsStore stand-in: returns a fixed snapshot per account."""
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self, account_name: str):
        return self._snapshot


@pytest.mark.asyncio(loop_scope="session")
class TestCorrelatedFollowupStage1Align:
    """Quick task 260501-mrw: when a correlated follow-up arrives and stage 1
    is already filled, the existing stage-1 MT5 position must be modified so
    its SL/TP match the follow-up's jittered plan. Failure isolated (D-17):
    a modify failure must not abort band creation/firing.
    """

    @pytest.fixture
    def followup(self):
        return SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="follow-up",
            direction=Direction.BUY,
            entry_zone=(4570.0, 4572.0),
            sl=4565.0, tps=[4580.0], target_tp=4580.0,
        )

    @pytest.fixture(autouse=True)
    def _patch_db(self, monkeypatch):
        """Patch every db.* call _handle_correlated_followup touches so the
        path runs without a real Postgres connection. Each test overrides
        get_stage_by_signal_account explicitly to control the lookup."""
        import trade_manager as tm_mod

        # Default stage-1 lookup → None; tests override per-case.
        monkeypatch.setattr(
            tm_mod.db, "get_stage_by_signal_account",
            AsyncMock(return_value=None),
        )
        # Band-creation writes — return ids mirroring inserted rows.
        monkeypatch.setattr(
            tm_mod.db, "create_staged_entries",
            AsyncMock(return_value=[101]),
        )
        monkeypatch.setattr(
            tm_mod.db, "update_stage_status", AsyncMock(return_value=None),
        )
        # Stage-1 audit row — capture for assertion.
        monkeypatch.setattr(
            tm_mod.db, "log_signal", AsyncMock(return_value=1),
        )
        # If a band fires _execute_open_on_account also touches these.
        monkeypatch.setattr(tm_mod.db, "get_daily_stat", AsyncMock(return_value=0))
        monkeypatch.setattr(tm_mod.db, "get_stage_by_comment", AsyncMock(return_value=None))
        monkeypatch.setattr(tm_mod.db, "increment_daily_stat", AsyncMock(return_value=None))
        monkeypatch.setattr(tm_mod.db, "mark_signal_counted_today", AsyncMock(return_value=False))
        monkeypatch.setattr(tm_mod.db, "log_trade", AsyncMock(return_value=None))

    def _wire_tm(self, tm, monkeypatch):
        """Attach a stub settings_store so bands actually get created (max_stages=2)
        and replace the connector spy methods we need to inspect."""
        snapshot = _StubBandSnapshot()
        tm.settings_store = _StubStore(snapshot)
        connector = next(iter(tm.connectors.values()))
        # Provide a price so the in-zone-at-arrival check has something to read,
        # but place price OUTSIDE the band so nothing fires (keeps test focused
        # on the alignment block + the "staged" summary entry).
        connector.get_price = AsyncMock(return_value=(4575.0, 4575.5))
        return connector

    async def test_followup_aligns_stage1_sl_and_tp_when_filled(
        self, tm, followup, monkeypatch,
    ):
        import trade_manager as tm_mod

        connector = self._wire_tm(tm, monkeypatch)
        monkeypatch.setattr(
            tm_mod.db, "get_stage_by_signal_account",
            AsyncMock(return_value={
                "id": 50, "signal_id": 99, "stage_number": 1,
                "account_name": "test-acct", "symbol": "XAUUSD",
                "direction": "buy", "status": "filled", "mt5_ticket": 12345,
            }),
        )
        modify_spy = AsyncMock(return_value=OrderResult(
            success=True, ticket=12345,
        ))
        connector.modify_position = modify_spy

        results = await tm._handle_correlated_followup(
            followup, paired_signal_id=99,
        )

        jitter = tm.cfg.sl_tp_jitter_points
        expected_sl = calculate_sl_with_jitter(4565.0, jitter, Direction.BUY)
        expected_tp = calculate_tp_with_jitter(4580.0, jitter, Direction.BUY)

        assert modify_spy.await_count == 1
        kwargs = modify_spy.call_args.kwargs
        args = modify_spy.call_args.args
        # ticket may be passed positionally
        assert (args and args[0] == 12345) or kwargs.get("ticket") == 12345
        assert kwargs["sl"] == expected_sl
        assert kwargs["tp"] == expected_tp

        aligned = [r for r in results if r.get("status") == "stage1_aligned"]
        assert len(aligned) == 1
        assert aligned[0]["ticket"] == 12345
        assert aligned[0]["sl"] == expected_sl
        assert aligned[0]["tp"] == expected_tp

        # Audit row was written for the alignment.
        log_signal_mock = tm_mod.db.log_signal
        assert log_signal_mock.await_count == 1
        log_kwargs = log_signal_mock.call_args.kwargs
        assert log_kwargs["signal_type"] == "modify_sl_tp"
        assert "stage1_aligned" in log_kwargs["action_taken"]
        assert "12345" in log_kwargs["action_taken"]

    async def test_followup_skips_stage1_align_when_not_filled(
        self, tm, followup, monkeypatch,
    ):
        import trade_manager as tm_mod

        connector = self._wire_tm(tm, monkeypatch)
        monkeypatch.setattr(
            tm_mod.db, "get_stage_by_signal_account",
            AsyncMock(return_value={
                "id": 50, "signal_id": 99, "stage_number": 1,
                "account_name": "test-acct", "symbol": "XAUUSD",
                "direction": "buy", "status": "awaiting_zone",
                "mt5_ticket": None,
            }),
        )
        modify_spy = AsyncMock(return_value=OrderResult(success=True, ticket=0))
        connector.modify_position = modify_spy

        results = await tm._handle_correlated_followup(
            followup, paired_signal_id=99,
        )

        assert modify_spy.await_count == 0
        statuses = {r.get("status") for r in results}
        assert "stage1_aligned" not in statuses
        assert "stage1_align_failed" not in statuses
        # Band creation still ran → "staged" summary present.
        assert "staged" in statuses

    async def test_followup_continues_band_fill_when_stage1_align_fails(
        self, tm, followup, monkeypatch,
    ):
        import trade_manager as tm_mod

        connector = self._wire_tm(tm, monkeypatch)
        monkeypatch.setattr(
            tm_mod.db, "get_stage_by_signal_account",
            AsyncMock(return_value={
                "id": 50, "signal_id": 99, "stage_number": 1,
                "account_name": "test-acct", "symbol": "XAUUSD",
                "direction": "buy", "status": "filled", "mt5_ticket": 12345,
            }),
        )
        modify_spy = AsyncMock(return_value=OrderResult(
            success=False, ticket=12345, error="broker reject",
        ))
        connector.modify_position = modify_spy

        results = await tm._handle_correlated_followup(
            followup, paired_signal_id=99,
        )

        failed = [r for r in results if r.get("status") == "stage1_align_failed"]
        assert len(failed) == 1
        assert failed[0]["ticket"] == 12345
        assert failed[0]["reason"] == "broker reject"

        # D-17 failure isolation: bands path still ran.
        statuses = {r.get("status") for r in results}
        assert "staged" in statuses

    async def test_followup_with_no_tp_still_aligns_stage1_sl(
        self, tm, followup, monkeypatch,
    ):
        import trade_manager as tm_mod

        connector = self._wire_tm(tm, monkeypatch)
        monkeypatch.setattr(
            tm_mod.db, "get_stage_by_signal_account",
            AsyncMock(return_value={
                "id": 50, "signal_id": 99, "stage_number": 1,
                "account_name": "test-acct", "symbol": "XAUUSD",
                "direction": "buy", "status": "filled", "mt5_ticket": 12345,
            }),
        )
        modify_spy = AsyncMock(return_value=OrderResult(
            success=True, ticket=12345,
        ))
        connector.modify_position = modify_spy

        # Replace target_tp with None (rare follow-up shape).
        followup_no_tp = SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="follow-up no tp",
            direction=Direction.BUY,
            entry_zone=(4570.0, 4572.0),
            sl=4565.0, tps=[], target_tp=None,
        )

        # Must not raise.
        results = await tm._handle_correlated_followup(
            followup_no_tp, paired_signal_id=99,
        )

        jitter = tm.cfg.sl_tp_jitter_points
        expected_sl = calculate_sl_with_jitter(4565.0, jitter, Direction.BUY)

        assert modify_spy.await_count == 1
        kwargs = modify_spy.call_args.kwargs
        assert kwargs["sl"] == expected_sl
        # §1.2: no numeric TP → tp must be None (not 0.0) so the REST bridge's
        # is-not-None guard preserves the position's existing TP; 0.0 would be
        # treated as an explicit "remove the TP".
        assert kwargs["tp"] is None

        aligned = [r for r in results if r.get("status") == "stage1_aligned"]
        assert len(aligned) == 1
        assert aligned[0]["tp"] is None


# ── Phase 13 Wave-0 RED stubs (trade_manager) ────────────────────────
# Intentionally RED (pytest.fail) so each downstream task has a concrete
# `pytest -k <name>` gate to turn green.


@pytest.mark.asyncio(loop_scope="session")
async def test_sl_less_open_skips_cleanly(tm, monkeypatch):
    """EXEC2-04 / D2-13 — a standalone OPEN whose signal.sl is None is routed to a
    clean skip-result BEFORE any sizing (no TypeError from
    calculate_sl_distance(entry, None), no EXECUTION ERROR alert). The D-08
    sl<=0 guard remains the second backstop.
    """
    import trade_manager as tm_mod

    # log_signal is the only db.* call the skip path touches — stub it (DB-free).
    log_spy = AsyncMock(return_value=42)
    monkeypatch.setattr(tm_mod.db, "log_signal", log_spy)
    # Spy on calculate_sl_distance: it MUST NOT be called on the SL-less path.
    sl_dist_spy = MagicMock(side_effect=tm_mod.calculate_sl_distance)
    monkeypatch.setattr(tm_mod, "calculate_sl_distance", sl_dist_spy)

    sl_less = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone 2040-2050 (no SL)",
        direction=Direction.BUY, entry_zone=(2040.0, 2050.0),
        sl=None, tps=[2060.0], target_tp=2060.0,
    )

    # Must not raise; returns a single skip-result.
    results = await tm._handle_open(sl_less)

    assert len(results) == 1
    assert results[0]["status"] == "skipped"
    assert "no SL" in results[0]["reason"]
    # The crash site is never reached.
    assert sl_dist_spy.call_count == 0
    # The signal was logged as skipped (audit trail), not silently dropped.
    assert log_spy.await_count == 1
    assert log_spy.call_args.kwargs.get("action_taken") == "skipped"


@pytest.mark.asyncio(loop_scope="session")
async def test_open_with_real_sl_unchanged(tm, monkeypatch):
    """EXEC2-04 guard — an OPEN WITH a real SL must NOT take the skip path; it
    proceeds to the normal account loop (calculate_sl_distance reached). Asserts
    the early skip is gated strictly on signal.sl is None.

    Post-EXEC2-06: _handle_open is now a multi-stage scale-in, so a standalone
    OPEN routes through create_staged_entries → _execute_open_on_account (staged).
    With no settings_store on the bare `tm` fixture, snapshot is None → max_stages=1
    → ONE synthesized whole-zone band. The seeded price (2045.0 ask) is inside the
    zone (2040-2050) and below TP1 (2060), so the band is not stale and fires →
    calculate_sl_distance is reached. (Updated from the v1.0 single-fill flow.)
    """
    import trade_manager as tm_mod

    monkeypatch.setattr(tm_mod.db, "log_signal", AsyncMock(return_value=7))
    sl_dist_spy = MagicMock(side_effect=tm_mod.calculate_sl_distance)
    monkeypatch.setattr(tm_mod, "calculate_sl_distance", sl_dist_spy)

    # No connected accounts on the bare `tm` fixture's connector → the loop runs
    # but the connector is connected (DryRunConnector). Seed a price so sizing runs.
    connector = next(iter(tm.connectors.values()))
    connector.set_simulated_price("XAUUSD", 2044.5, 2045.0)
    # Stub the db.* calls the staged success path touches so it runs DB-free.
    # create_staged_entries returns one stage id (max_stages=1 → 1 whole-zone band).
    monkeypatch.setattr(tm_mod.db, "create_staged_entries", AsyncMock(return_value=[101]))
    # §4.2: the fire path now atomically claims the row before submitting; echo the
    # stage_id so the claim succeeds and firing proceeds (return 0/None = "claim lost").
    monkeypatch.setattr(tm_mod.db, "claim_stage_for_firing",
                        AsyncMock(side_effect=lambda stage_id: stage_id))
    for name in ("get_daily_stat", "increment_daily_stat", "mark_signal_counted_today",
                 "update_stage_status", "log_trade", "log_pending_order",
                 "get_stage_by_comment"):
        monkeypatch.setattr(tm_mod.db, name, AsyncMock(return_value=0))

    with_sl = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone 2040-2050 SL 2035 TP 2060",
        direction=Direction.BUY, entry_zone=(2040.0, 2050.0),
        sl=2035.0, tps=[2060.0], target_tp=2060.0,
    )
    results = await tm._handle_open(with_sl)
    # Reached sizing → calculate_sl_distance called at least once; no skip-for-no-SL.
    assert sl_dist_spy.call_count >= 1
    assert not any(
        r.get("reason", "").startswith("Skipped: signal has no SL") for r in results
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_direct_zone_past_market_stale(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    """EXEC2-06 / D2-14 — when price has already run PAST the zone at arrival, the
    direct-zone OPEN is rejected as stale (_check_stale runs FIRST) before any
    band fires at market AND before any staged row is created — never chase a
    moved market.

    BUY signal, TP above the zone. _check_stale flags BUY stale when
    current_price >= TP1. Set price (2085.1/2085.2) ABOVE TP1=2080 → the market
    already ran past the target → stale → clean skip, NO staged_entries rows.
    """
    open_signal = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone 2040-2060 SL 2030 TP 2080",
        direction=Direction.BUY, entry_zone=(2040.0, 2060.0),
        sl=2030.0, tps=[2080.0], target_tp=2080.0,
    )
    import db

    # Price has run PAST the zone and past TP1 — moved market.
    priced_connector._prices = {"XAUUSD": (2085.1, 2085.2)}

    results = await tm_with_store.handle_signal(open_signal)

    # Stale skip — no band fired.
    assert any(
        r.get("status") == "skipped" and "stale" in r.get("reason", "").lower()
        for r in results
    ), results
    assert not any(r.get("status") == "executed" for r in results)

    # D2-14: the stale check precedes the band lifecycle → NO staged rows created.
    async with db._pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM staged_entries")
    assert len(rows) == 0


@pytest.mark.asyncio(loop_scope="session")
async def test_direct_zone_in_zone_not_stale_proceeds(
    db_pool, seeded_staged_account, priced_connector, tm_with_store,
):
    """D2-14 guard — an in-zone (non-stale) arrival is NOT rejected by the
    pre-band stale check; it proceeds to the band lifecycle and creates rows."""
    open_signal = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD",
        raw_text="Gold buy zone 2040-2060 SL 2030 TP 2080",
        direction=Direction.BUY, entry_zone=(2040.0, 2060.0),
        sl=2030.0, tps=[2080.0], target_tp=2080.0,
    )
    import db

    # Price inside/below the zone, well under TP1 → not stale.
    priced_connector._prices = {"XAUUSD": (2050.1, 2050.2)}

    await tm_with_store.handle_signal(open_signal)

    async with db._pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM staged_entries")
    # Bands were created (not stale-skipped before the lifecycle).
    assert len(rows) > 0
