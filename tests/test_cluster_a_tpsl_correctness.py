"""Cluster A (Phase 13 TP/SL correctness) regression tests.

Covers audit findings:
  §1.1 — a correlated follow-up's band rows must carry signal_sl/signal_tp so a
         band that arms and later fires via the zone watcher opens with the real
         SL/TP instead of NULL → tp=0.0 and a wrong default SL.
  §1.2 — a follow-up with no numeric TP must align stage 1 with tp=None (not
         0.0) so the REST bridge's is-not-None guard preserves the existing TP.
  §1.3 — the notifier must surface a 'stage1_align_failed' result as a visible
         warning line in the #executions message instead of silently dropping it.
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from models import Direction, SignalAction, SignalType
from mt5_connector import OrderResult
from trade_manager import TradeManager


# Local `tm` fixture (kept out of conftest to avoid cross-cluster collision).
# The conftest `account` fixture is named 'test-acct', matching the stub store.
@pytest.fixture
def tm(connector, account, global_config):
    return TradeManager(
        connectors={account.name: connector},
        accounts=[account],
        global_config=global_config,
    )


@dataclass
class _StubBandSnapshot:
    """Minimal AccountSettings stand-in; max_stages=2 makes compute_bands emit
    real bands so create_staged_entries is exercised."""
    account_name: str = "test-acct"
    risk_mode: str = "fixed_lot"
    risk_value: float = 0.01
    max_stages: int = 2
    default_sl_pips: int = 100
    max_daily_trades: int = 30
    max_open_trades: int = 3
    max_lot_size: float = 1.0


class _StubStore:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self, account_name: str):
        return self._snapshot


@pytest.mark.asyncio(loop_scope="session")
class TestCorrelatedRowsCarrySlTp:
    """§1.1 / §1.2 — the correlated follow-up path."""

    @pytest.fixture(autouse=True)
    def _patch_db(self, monkeypatch):
        import trade_manager as tm_mod

        # Default: no stage-1 row → the alignment block is skipped and the test
        # focuses purely on the band rows written by create_staged_entries.
        monkeypatch.setattr(
            tm_mod.db, "get_stage_by_signal_account",
            AsyncMock(return_value=None),
        )
        self.create_spy = AsyncMock(return_value=[101])
        monkeypatch.setattr(tm_mod.db, "create_staged_entries", self.create_spy)
        monkeypatch.setattr(tm_mod.db, "update_stage_status", AsyncMock(return_value=None))
        monkeypatch.setattr(tm_mod.db, "log_signal", AsyncMock(return_value=1))
        monkeypatch.setattr(tm_mod.db, "get_daily_stat", AsyncMock(return_value=0))
        monkeypatch.setattr(tm_mod.db, "get_stage_by_comment", AsyncMock(return_value=None))
        monkeypatch.setattr(tm_mod.db, "increment_daily_stat", AsyncMock(return_value=None))
        monkeypatch.setattr(tm_mod.db, "mark_signal_counted_today", AsyncMock(return_value=False))
        monkeypatch.setattr(tm_mod.db, "log_trade", AsyncMock(return_value=None))

    def _wire(self, tm):
        tm.settings_store = _StubStore(_StubBandSnapshot())
        connector = next(iter(tm.connectors.values()))
        # Price above the zone → nothing fires; bands arm and wait, exercising
        # the persisted-row path the zone watcher later reads.
        connector.get_price = AsyncMock(return_value=(4575.0, 4575.5))
        return connector

    async def test_band_rows_include_signal_sl_and_tp(self, tm):
        self._wire(tm)
        followup = SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="follow-up",
            direction=Direction.BUY, entry_zone=(4570.0, 4572.0),
            sl=4565.0, tps=[4580.0], target_tp=4580.0,
        )

        await tm._handle_correlated_followup(followup, paired_signal_id=99)

        assert self.create_spy.await_count == 1
        rows = self.create_spy.call_args.args[0]
        assert rows, "expected at least one band row to be written"
        for row in rows:
            # Pre-fix these keys were omitted → DB inserted NULL for both.
            assert row["signal_sl"] == 4565.0
            assert row["signal_tp"] == 4580.0

    async def test_no_tp_followup_aligns_stage1_with_tp_none(self, tm, monkeypatch):
        import trade_manager as tm_mod

        connector = self._wire(tm)
        monkeypatch.setattr(
            tm_mod.db, "get_stage_by_signal_account",
            AsyncMock(return_value={
                "id": 50, "signal_id": 99, "stage_number": 1,
                "account_name": "test-acct", "symbol": "XAUUSD",
                "direction": "buy", "status": "filled", "mt5_ticket": 12345,
            }),
        )
        modify_spy = AsyncMock(return_value=OrderResult(success=True, ticket=12345))
        connector.modify_position = modify_spy

        followup_no_tp = SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="follow-up no tp",
            direction=Direction.BUY, entry_zone=(4570.0, 4572.0),
            sl=4565.0, tps=[], target_tp=None,
        )

        results = await tm._handle_correlated_followup(
            followup_no_tp, paired_signal_id=99,
        )

        assert modify_spy.await_count == 1
        # Pre-fix this was 0.0, which the REST bridge treats as "remove the TP".
        assert modify_spy.call_args.kwargs["tp"] is None

        aligned = [r for r in results if r.get("status") == "stage1_aligned"]
        assert len(aligned) == 1
        assert aligned[0]["tp"] is None


@pytest.mark.asyncio(loop_scope="session")
class TestNotifierStage1AlignFailed:
    """§1.3 — a stage1_align_failed result must be surfaced, not swallowed."""

    async def test_stage1_align_failed_is_surfaced(self, monkeypatch):
        import notifier as notifier_mod

        sent = {}

        async def fake_send(http, url, msg):
            sent["msg"] = msg

        monkeypatch.setattr(notifier_mod, "send_message", fake_send)

        n = notifier_mod.Notifier(
            http=None, executions_webhook="http://x", alerts_webhook=None,
        )
        signal = SignalAction(
            type=SignalType.OPEN, symbol="XAUUSD", raw_text="t",
            direction=Direction.BUY, entry_zone=(4570.0, 4572.0),
            sl=4565.0, tps=[4580.0], target_tp=4580.0,
        )
        results = [{
            "account": "test-acct", "status": "stage1_align_failed",
            "ticket": 12345, "reason": "broker reject",
        }]

        await n.notify_execution(signal, results)

        assert "msg" in sent, "notify_execution should have sent a message"
        # Pre-fix: no branch for this status → the warning line was omitted.
        assert "Stage-1 TP/SL alignment FAILED" in sent["msg"]
        assert "12345" in sent["msg"]
        assert "broker reject" in sent["msg"]
