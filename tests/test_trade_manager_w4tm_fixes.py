"""W4-TM regression tests — three trade_manager.py fixes.

Covers:
  1. SL-less correlated follow-up degrades to a clean skip (no TypeError).
  2. MODIFY/CLOSE only touch bot-owned positions; retcode 10025 (no-change)
     on a modify is treated as success, not failure.
  3. cleanup_expired_orders detects a filled limit by position/order ticket
     identity (not a substring-in-comment probe that is always false).

DB-free: the handful of db.* calls these paths make are monkeypatched to
no-ops so the tests run without a live PostgreSQL.
"""

import pytest

import db
from models import AccountConfig, Direction, GlobalConfig, SignalAction, SignalType
from mt5_connector import DryRunConnector, OrderResult, Position
from trade_manager import TradeManager, is_bot_position, is_no_change_result


# ── Shared builders ──────────────────────────────────────────────────────────

def _cfg():
    return GlobalConfig(
        default_target_tp=2,
        limit_order_expiry_minutes=30,
        max_daily_trades_per_account=30,
        max_daily_server_messages=500,
        stagger_delay_min=0,
        stagger_delay_max=0,
        lot_jitter_percent=0,
        sl_tp_jitter_points=0,
    )


def _acct(name="test-acct"):
    return AccountConfig(
        name=name, server="TestServer", login=12345, password_env="TEST_PASS",
        risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
        max_open_trades=3, enabled=True,
    )


def _connected_dry(name="test-acct"):
    c = DryRunConnector(name, "TestServer", 12345, "pass")
    c._connected = True
    return c


@pytest.fixture(autouse=True)
def _stub_db(monkeypatch):
    """No-op the db writes these paths perform so no live DB is required."""
    async def _noop(*args, **kwargs):
        return None

    for fn in (
        "log_signal", "increment_daily_stat", "update_trade_close",
        "mark_pending_filled", "mark_pending_cancelled",
    ):
        monkeypatch.setattr(db, fn, _noop)
    yield


# ── Finding 2 (helpers) ──────────────────────────────────────────────────────

class TestIsBotPosition:
    def test_bot_comment_prefix_is_owned(self):
        pos = Position(ticket=1, symbol="XAUUSD", direction="buy", volume=0.1,
                       open_price=2800.0, sl=2790.0, tp=2820.0, profit=0.0,
                       comment="telebot-5-s1")
        assert is_bot_position(pos) is True

    def test_bare_telebot_comment_is_owned(self):
        pos = Position(ticket=1, symbol="XAUUSD", direction="buy", volume=0.1,
                       open_price=2800.0, sl=2790.0, tp=2820.0, profit=0.0,
                       comment="telebot")
        assert is_bot_position(pos) is True

    def test_empty_comment_is_foreign(self):
        pos = Position(ticket=1, symbol="XAUUSD", direction="buy", volume=0.1,
                       open_price=2800.0, sl=2790.0, tp=2820.0, profit=0.0,
                       comment="")
        assert is_bot_position(pos) is False

    def test_manual_comment_is_foreign(self):
        pos = Position(ticket=1, symbol="XAUUSD", direction="buy", volume=0.1,
                       open_price=2800.0, sl=2790.0, tp=2820.0, profit=0.0,
                       comment="manual entry")
        assert is_bot_position(pos) is False


class TestIsNoChangeResult:
    def test_retcode_10025_is_no_change(self):
        r = OrderResult(success=False, ticket=1, error="retcode 10025")
        assert is_no_change_result(r) is True

    def test_no_changes_message_is_no_change(self):
        r = OrderResult(success=False, ticket=1, error="Error: No changes")
        assert is_no_change_result(r) is True

    def test_generic_error_is_not_no_change(self):
        r = OrderResult(success=False, ticket=1, error="Invalid stops (10016)")
        assert is_no_change_result(r) is False

    def test_success_is_not_no_change(self):
        r = OrderResult(success=True, ticket=1)
        assert is_no_change_result(r) is False


# ── Finding 2 (handler behaviour) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_modify_sl_skips_foreign_positions():
    conn = _connected_dry()
    # One bot-owned position and one manual/foreign position on same symbol.
    conn._fake_positions = {
        111: Position(ticket=111, symbol="XAUUSD", direction="buy", volume=0.1,
                      open_price=2800.0, sl=2790.0, tp=2820.0, profit=0.0,
                      comment="telebot-5-s1"),
        222: Position(ticket=222, symbol="XAUUSD", direction="buy", volume=0.1,
                      open_price=2800.0, sl=2790.0, tp=2820.0, profit=0.0,
                      comment=""),  # foreign
    }
    tm = TradeManager({"test-acct": conn}, [_acct()], _cfg())

    signal = SignalAction(type=SignalType.MODIFY_SL, symbol="XAUUSD",
                          raw_text="modify", new_sl=2795.0)
    results = await tm._handle_modify_sl(signal)

    tickets = {r["ticket"] for r in results}
    assert 111 in tickets            # bot position modified
    assert 222 not in tickets        # foreign position untouched


@pytest.mark.asyncio
async def test_close_skips_foreign_positions():
    conn = _connected_dry()
    conn._fake_positions = {
        111: Position(ticket=111, symbol="XAUUSD", direction="buy", volume=0.1,
                      open_price=2800.0, sl=2790.0, tp=2820.0, profit=0.0,
                      comment="telebot"),
        222: Position(ticket=222, symbol="XAUUSD", direction="buy", volume=0.1,
                      open_price=2800.0, sl=2790.0, tp=2820.0, profit=0.0,
                      comment="hand-placed"),
    }
    tm = TradeManager({"test-acct": conn}, [_acct()], _cfg())

    signal = SignalAction(type=SignalType.CLOSE, symbol="XAUUSD", raw_text="close")
    results = await tm._handle_close(signal)

    tickets = {r["ticket"] for r in results}
    assert 111 in tickets
    assert 222 not in tickets
    # Foreign position must remain open on the broker.
    assert 222 in conn._fake_positions


class _NoChangeConnector(DryRunConnector):
    """modify_position always reports MT5 retcode 10025 (no changes)."""

    async def modify_position(self, ticket, sl=None, tp=None):
        return OrderResult(success=False, ticket=ticket, error="retcode 10025 no changes")


@pytest.mark.asyncio
async def test_modify_sl_no_change_reported_as_success():
    conn = _NoChangeConnector("test-acct", "TestServer", 12345, "pass")
    conn._connected = True
    conn._fake_positions = {
        111: Position(ticket=111, symbol="XAUUSD", direction="buy", volume=0.1,
                      open_price=2800.0, sl=2795.0, tp=2820.0, profit=0.0,
                      comment="telebot-5-s1"),
    }
    tm = TradeManager({"test-acct": conn}, [_acct()], _cfg())

    signal = SignalAction(type=SignalType.MODIFY_SL, symbol="XAUUSD",
                          raw_text="modify", new_sl=2795.0)
    results = await tm._handle_modify_sl(signal)

    assert len(results) == 1
    assert results[0]["status"] == "sl_modified"   # not "failed"


# ── Finding 3 (filled-limit detection) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_expired_limit_with_resulting_position_is_filled(monkeypatch):
    conn = _connected_dry()
    # Pending order 500 is gone from the pending list but its position exists.
    # Position ticket == triggering order ticket (MT5 identity). Comment does
    # NOT contain "500" — the old substring probe would misclassify as cancelled.
    conn._pending_orders = {}
    conn._fake_positions = {
        500: Position(ticket=500, symbol="XAUUSD", direction="buy", volume=0.1,
                      open_price=2800.0, sl=2790.0, tp=2820.0, profit=0.0,
                      comment="telebot-9-s2"),
    }

    async def _expired():
        return [{"id": 1, "account_name": "test-acct", "ticket": 500, "symbol": "XAUUSD"}]

    monkeypatch.setattr(db, "get_expired_pending_orders", _expired)

    marked_filled = []

    async def _mark_filled(ticket, acct):
        marked_filled.append((ticket, acct))

    monkeypatch.setattr(db, "mark_pending_filled", _mark_filled)

    tm = TradeManager({"test-acct": conn}, [_acct()], _cfg())
    results = await tm.cleanup_expired_orders()

    assert len(results) == 1
    assert results[0]["status"] == "filled"
    assert marked_filled == [(500, "test-acct")]


@pytest.mark.asyncio
async def test_expired_limit_without_position_is_cancelled(monkeypatch):
    conn = _connected_dry()
    conn._pending_orders = {}
    conn._fake_positions = {}  # no resulting position

    async def _expired():
        return [{"id": 1, "account_name": "test-acct", "ticket": 500, "symbol": "XAUUSD"}]

    marked_cancelled = []

    async def _mark_cancelled(order_id):
        marked_cancelled.append(order_id)

    monkeypatch.setattr(db, "get_expired_pending_orders", _expired)
    monkeypatch.setattr(db, "mark_pending_cancelled", _mark_cancelled)

    tm = TradeManager({"test-acct": conn}, [_acct()], _cfg())
    results = await tm.cleanup_expired_orders()

    assert len(results) == 1
    assert results[0]["status"] == "cancelled"
    assert marked_cancelled == [1]


# ── Finding 1 (SL-less correlated follow-up) ─────────────────────────────────

@pytest.mark.asyncio
async def test_slless_correlated_followup_skips_without_crash():
    conn = _connected_dry()
    tm = TradeManager({"test-acct": conn}, [_acct()], _cfg())

    signal = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD", raw_text="followup",
        direction=Direction.BUY, entry_zone=(2795.0, 2805.0),
        sl=None, tps=[2820.0], target_tp=2820.0,
    )
    # Must not raise TypeError; must return a clean skip result.
    results = await tm._handle_correlated_followup(signal, paired_signal_id=1)

    assert len(results) == 1
    assert results[0]["status"] == "skipped"
    assert "no SL" in results[0]["reason"]
