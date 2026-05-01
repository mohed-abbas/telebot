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
