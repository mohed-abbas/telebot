"""A signalled SL move far from the entry is a typo and is refused.

The provider has sent levels like "SL: 51108" for a 5108 trade. On the right
side of the entry such a level passes the direction check, so the distance
check keeps it off the position.
"""

import pytest

import db
from models import AccountConfig, GlobalConfig, SignalAction, SignalType
from mt5_connector import DryRunConnector, Position
from trade_manager import TradeManager


def _tm_with_sell_at(open_price: float) -> tuple[TradeManager, DryRunConnector]:
    conn = DryRunConnector("test-acct", "TestServer", 12345, "pass")
    conn._connected = True
    conn._fake_positions = {
        111: Position(ticket=111, symbol="XAUUSD", direction="sell", volume=0.1,
                      open_price=open_price, sl=open_price + 4, tp=open_price - 10,
                      profit=0.0, comment="telebot-5-s1"),
    }
    cfg = GlobalConfig(
        default_target_tp=2, limit_order_expiry_minutes=30,
        max_daily_trades_per_account=30, max_daily_server_messages=500,
        stagger_delay_min=0, stagger_delay_max=0, lot_jitter_percent=0,
    )
    acct = AccountConfig(
        name="test-acct", server="TestServer", login=12345, password_env="TEST_PASS",
        risk_percent=1.0, max_lot_size=1.0,
    )
    return TradeManager({"test-acct": conn}, [acct], cfg), conn


@pytest.fixture(autouse=True)
def _stub_db(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    for fn in ("log_signal", "increment_daily_stat", "update_stage_targets_for_position"):
        monkeypatch.setattr(db, fn, _noop)


@pytest.mark.asyncio
async def test_typo_level_is_refused():
    tm, conn = _tm_with_sell_at(5108.0)
    signal = SignalAction(type=SignalType.MODIFY_SL, symbol="XAUUSD",
                          raw_text="SL: 51108", new_sl=51108.0)

    [result] = await tm._handle_modify_sl(signal)

    assert result["status"] == "skipped"
    assert "typo" in result["reason"]
    assert conn._fake_positions[111].sl == 5112.0


@pytest.mark.asyncio
async def test_widened_level_is_applied():
    tm, conn = _tm_with_sell_at(4117.5)
    signal = SignalAction(type=SignalType.MODIFY_SL, symbol="XAUUSD",
                          raw_text="Update SL to 4129.3 ok", new_sl=4129.3)

    [result] = await tm._handle_modify_sl(signal)

    assert result["status"] == "sl_modified"
    assert result["new_sl"] == 4129.3
