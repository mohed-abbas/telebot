"""What a parsed instruction leaves behind (2026-10-28 review).

* A close-all signal cancels this account's armed bands, so one waiting for
  the zone cannot open a new trade after the provider said to get out.
* SL/TP changes are written to the trade row, so the dashboard shows the
  levels the position really has (the 28 Oct stage 1 showed SL 4031.09 /
  TP 0.00 although it closed at the follow-up's SL 4027).
* Discord shows the stage-1 alignment and the cancelled bands.
"""

import pytest

import db
from models import AccountConfig, Direction, GlobalConfig, SignalAction, SignalType
from mt5_connector import DryRunConnector, Position
from trade_manager import TradeManager


def _stage_row(signal_id, account_name, *, stage_number, status, symbol="XAUUSD"):
    return {
        "signal_id": signal_id,
        "stage_number": stage_number,
        "account_name": account_name,
        "symbol": symbol,
        "direction": "buy",
        "zone_low": 4031.0,
        "zone_high": 4035.5,
        "band_low": 4031.0,
        "band_high": 4033.0,
        "target_lot": 0.04,
        "snapshot_settings": {},
        "mt5_comment": f"telebot-{signal_id}-s{stage_number}-{symbol}",
        "status": status,
    }


# ── DB helpers (live Postgres) ────────────────────────────────────────────


@pytest.mark.asyncio(loop_scope="session")
async def test_close_cancels_only_unfilled_stages_of_account_and_symbol(
    db_pool, seeded_account, seeded_signal,
):
    ids = await db.create_staged_entries([
        _stage_row(seeded_signal, seeded_account, stage_number=1, status="filled"),
        _stage_row(seeded_signal, seeded_account, stage_number=2, status="awaiting_zone"),
        _stage_row(seeded_signal, seeded_account, stage_number=3, status="firing"),
        _stage_row(seeded_signal, seeded_account, stage_number=4, status="awaiting_zone",
                   symbol="EURUSD"),
    ])

    assert await db.cancel_unfilled_stages_for_close(seeded_account, "XAUUSD") == 1

    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, status, cancelled_reason FROM staged_entries WHERE id = ANY($1::int[]) ORDER BY id",
            ids,
        )
    statuses = [(r["status"], r["cancelled_reason"]) for r in rows]
    assert statuses == [
        ("filled", None),
        ("cancelled_stage1_closed", "close_signal"),
        ("firing", None),            # in flight: the stage-1 exit cascade covers it
        ("awaiting_zone", None),     # other symbol untouched
    ]


@pytest.mark.asyncio(loop_scope="session")
async def test_trade_levels_follow_live_changes(db_pool, seeded_account):
    await db.log_trade(
        signal_id=None, account_name=seeded_account, symbol="XAUUSD", direction="buy",
        entry_price=4036.17, sl=4031.09, tp=0.0, lot_size=0.04, ticket=2257227474,
        status="opened",
    )

    assert await db.update_trade_levels(2257227474, seeded_account, sl=4027.0, tp=4040.0)
    # None keeps the stored level.
    assert await db.update_trade_levels(2257227474, seeded_account, sl=4025.0)
    assert not await db.update_trade_levels(2257227474, seeded_account)

    async with db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT sl, tp FROM trades WHERE ticket=$1 AND account_name=$2",
            2257227474, seeded_account,
        )
    assert (row["sl"], row["tp"]) == (4025.0, 4040.0)


@pytest.mark.asyncio(loop_scope="session")
async def test_closed_trade_levels_are_not_rewritten(db_pool, seeded_account):
    await db.log_trade(
        signal_id=None, account_name=seeded_account, symbol="XAUUSD", direction="buy",
        entry_price=4033.38, sl=4027.0, tp=4040.0, lot_size=0.04, ticket=2257244024,
        status="closed",
    )
    assert not await db.update_trade_levels(2257244024, seeded_account, sl=4033.38)


# ── TradeManager wiring (DB stubbed) ──────────────────────────────────────


def _tm(positions: dict) -> tuple[TradeManager, DryRunConnector]:
    conn = DryRunConnector("test-acct", "TestServer", 12345, "pass")
    conn._connected = True
    conn._fake_positions = positions
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


def _buy(ticket, open_price, sl):
    return Position(ticket=ticket, symbol="XAUUSD", direction="buy", volume=0.04,
                    open_price=open_price, sl=sl, tp=4040.0, profit=0.0,
                    comment=f"telebot-199-s{ticket % 10}")


@pytest.fixture
def db_calls(monkeypatch):
    calls = []

    def record(name, result=None):
        async def _fn(*args, **kwargs):
            calls.append((name, args, kwargs))
            return result
        return _fn

    monkeypatch.setattr(db, "log_signal", record("log_signal"))
    monkeypatch.setattr(db, "increment_daily_stat", record("increment_daily_stat"))
    monkeypatch.setattr(db, "mark_trade_closing", record("mark_trade_closing"))
    monkeypatch.setattr(db, "update_trade_close", record("update_trade_close"))
    monkeypatch.setattr(db, "update_stage_targets_for_position", record("update_stage_targets"))
    monkeypatch.setattr(db, "update_trade_levels", record("update_trade_levels", True))
    monkeypatch.setattr(db, "cancel_unfilled_stages_for_close", record("cancel_for_close", 2))
    return calls


@pytest.mark.asyncio
async def test_close_signal_cancels_bands_before_closing(db_calls):
    tm, conn = _tm({1: _buy(1, 4036.17, 4027.0), 2: _buy(2, 4033.38, 4027.0)})
    signal = SignalAction(type=SignalType.CLOSE, symbol="XAUUSD",
                          raw_text="OUT OF ALL ENTRIES NOW!!!")

    results = await tm._handle_close(signal)

    names = [c[0] for c in db_calls]
    first_close = min(
        i for i, n in enumerate(names) if n in ("mark_trade_closing", "update_trade_close")
    )
    assert names.index("cancel_for_close") < first_close
    assert ("cancel_for_close", ("test-acct", "XAUUSD"), {}) in db_calls
    assert {"account": "test-acct", "status": "stages_cancelled", "count": 2} in results
    assert conn._fake_positions == {}


@pytest.mark.asyncio
async def test_breakeven_writes_each_entry_to_its_trade_row(db_calls):
    tm, _ = _tm({1: _buy(1, 4036.17, 4027.0), 2: _buy(2, 4033.38, 4027.0)})
    signal = SignalAction(type=SignalType.MODIFY_SL, symbol="XAUUSD",
                          raw_text="Make sure u set breakeven too!", new_sl=0.0)

    await tm._handle_modify_sl(signal)

    levels = sorted(
        (args[0], kwargs["sl"]) for name, args, kwargs in db_calls if name == "update_trade_levels"
    )
    assert levels == [(1, 4036.17), (2, 4033.38)]


# ── Discord ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discord_shows_stage1_alignment_and_cancelled_bands(monkeypatch):
    import notifier as notifier_mod

    sent = {}

    async def fake_send(http, url, msg):
        sent["msg"] = msg

    monkeypatch.setattr(notifier_mod, "send_message", fake_send)
    n = notifier_mod.Notifier(http=None, executions_webhook="http://x", alerts_webhook=None)
    signal = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD", raw_text="t", direction=Direction.BUY,
        entry_zone=(4031.0, 4035.5), sl=4027.0, tps=[4038.0, 4040.0], target_tp=4040.0,
    )

    await n.notify_execution(signal, [
        {"account": "Vantage Demo-10k", "status": "stage1_aligned",
         "ticket": 2257227474, "sl": 4027.0, "tp": 4040.0},
        {"account": "Vantage Demo-10k", "status": "stage1_aligned",
         "ticket": 2257227475, "sl": 4027.0, "tp": None},
        {"account": "Vantage Demo-10k", "status": "stages_cancelled", "count": 3},
    ])

    msg = sent["msg"]
    assert "Stage 1 aligned #2257227474 | SL → 4027.00 | TP → 4040.00" in msg
    assert "TP → unchanged" in msg
    assert "3 unfilled stage(s) cancelled" in msg
