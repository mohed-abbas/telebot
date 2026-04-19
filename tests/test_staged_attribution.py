"""Attribution tests for Phase 6 Plan 02 (D-18, D-24, STAGE-09).

Covers:
  - Every stage persists signal_id
  - staged_entries.mt5_ticket populated on fill (join-to-trades by ticket)
  - 1 signal = 1 daily slot — stage 2..N skip trades_count increment
"""
from __future__ import annotations

import pytest
import pytest_asyncio

import db
from models import AccountConfig, Direction, GlobalConfig, SignalAction, SignalType
from mt5_connector import DryRunConnector
from settings_store import SettingsStore
from trade_manager import TradeManager

pytestmark = pytest.mark.asyncio(loop_scope="session")


class _PricedDry(DryRunConnector):
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


def _stage_row(signal_id, account, *, stage_number, comment):
    return {
        "signal_id": signal_id,
        "stage_number": stage_number,
        "account_name": account,
        "symbol": "XAUUSD",
        "direction": "buy",
        "zone_low": 2040.0,
        "zone_high": 2050.0,
        "band_low": 2040.0,
        "band_high": 2050.0,
        "target_lot": 0.05,
        "snapshot_settings": {
            "risk_mode": "percent", "risk_value": 1.0, "max_stages": 5,
            "default_sl_pips": 100, "max_daily_trades": 30,
        },
        "mt5_comment": comment,
        "status": "awaiting_zone",
    }


async def test_every_stage_persists_signal_id(
    db_pool, seeded_account, seeded_signal, priced_connector, tm_with_store,
):
    """Every staged_entries row carries the originating signal_id (D-07, STAGE-09)."""
    ids = await db.create_staged_entries([
        _stage_row(seeded_signal, seeded_account, stage_number=1, comment=f"telebot-{seeded_signal}-s1"),
        _stage_row(seeded_signal, seeded_account, stage_number=2, comment=f"telebot-{seeded_signal}-s2"),
        _stage_row(seeded_signal, seeded_account, stage_number=3, comment=f"telebot-{seeded_signal}-s3"),
    ])
    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT signal_id, stage_number, mt5_comment FROM staged_entries WHERE id = ANY($1::int[]) ORDER BY stage_number",
            ids,
        )
    assert len(rows) == 3
    for r in rows:
        assert r["signal_id"] == seeded_signal
        assert r["mt5_comment"].startswith(f"telebot-{seeded_signal}-s")


async def test_staged_entries_joins_trades_by_ticket(
    db_pool, seeded_account, seeded_signal, priced_connector, tm_with_store,
):
    """staged_entries.mt5_ticket = trades.ticket — analytics join works (D-38, STAGE-09).

    Fire a text-only open path equivalent: synthetic signal with a pre-computed SL,
    call _execute_open_on_account with signal_id + stage_number + stage_row_id.
    The stage row gets populated with mt5_ticket matching the trades row.
    """
    [stage_id] = await db.create_staged_entries(
        [_stage_row(seeded_signal, seeded_account, stage_number=1, comment=f"telebot-{seeded_signal}-s1")]
    )

    acct = tm_with_store.accounts["test-acct"]
    synth = SignalAction(
        type=SignalType.OPEN_TEXT_ONLY,
        symbol="XAUUSD",
        raw_text="Gold buy now",
        direction=Direction.BUY,
        entry_zone=None,
        sl=2039.0,  # non-zero SL (computed upstream from default_sl_pips)
        tps=[],
        target_tp=None,
    )
    result = await tm_with_store._execute_open_on_account(
        synth, seeded_signal, acct, priced_connector,
        stage_number=1, stage_row_id=stage_id,
    )
    assert result["status"] == "executed"
    ticket = result["ticket"]

    # Stage row should now carry the matching ticket
    async with db._pool.acquire() as conn:
        stage_row = await conn.fetchrow(
            "SELECT mt5_ticket, status FROM staged_entries WHERE id=$1", stage_id,
        )
    assert stage_row["mt5_ticket"] == ticket
    assert stage_row["status"] == "filled"

    # And trades has a row with matching ticket + signal_id
    async with db._pool.acquire() as conn:
        trade_row = await conn.fetchrow(
            "SELECT signal_id FROM trades WHERE ticket=$1 AND account_name=$2",
            ticket, seeded_account,
        )
    assert trade_row is not None
    assert trade_row["signal_id"] == seeded_signal


async def test_one_signal_id_one_daily_slot(
    db_pool, seeded_account, seeded_signal, priced_connector, tm_with_store,
):
    """Stage 1 increments trades_count; stage 2 of same signal_id does NOT (D-18)."""
    acct = tm_with_store.accounts["test-acct"]

    assert await db.get_daily_stat(seeded_account, "trades_count") == 0

    # Stage 1 — a correlated sibling, say stage_number=1 with distinct comment.
    [stage1_id] = await db.create_staged_entries(
        [_stage_row(seeded_signal, seeded_account, stage_number=1, comment=f"telebot-{seeded_signal}-s1")]
    )
    synth1 = SignalAction(
        type=SignalType.OPEN_TEXT_ONLY, symbol="XAUUSD", raw_text="Gold buy now",
        direction=Direction.BUY, entry_zone=None, sl=2039.0, tps=[], target_tp=None,
    )
    r1 = await tm_with_store._execute_open_on_account(
        synth1, seeded_signal, acct, priced_connector,
        stage_number=1, stage_row_id=stage1_id,
    )
    assert r1["status"] == "executed"
    assert await db.get_daily_stat(seeded_account, "trades_count") == 1

    # Stage 2 — same signal_id, different stage, same direction (dup-guard bypassed).
    [stage2_id] = await db.create_staged_entries(
        [_stage_row(seeded_signal, seeded_account, stage_number=2, comment=f"telebot-{seeded_signal}-s2")]
    )
    synth2 = SignalAction(
        type=SignalType.OPEN,  # follow-up path — full zone/SL/TP
        symbol="XAUUSD", raw_text="Gold buy zone 2040-2050 SL 2035 TP 2060",
        direction=Direction.BUY, entry_zone=(2040.0, 2050.0),
        sl=2035.0, tps=[2060.0], target_tp=2060.0,
    )
    r2 = await tm_with_store._execute_open_on_account(
        synth2, seeded_signal, acct, priced_connector,
        stage_number=2, stage_row_id=stage2_id,
    )
    assert r2["status"] in ("executed", "limit_placed")
    # Critical: trades_count did NOT increment a second time.
    assert await db.get_daily_stat(seeded_account, "trades_count") == 1
