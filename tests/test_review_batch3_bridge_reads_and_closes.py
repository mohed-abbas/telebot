"""Review 2026-10-16 — batch 3 regression tests.

One test group per finding in docs/audit/review-2026-10-16-fix-plan.md:

  #3   a timed-out order was treated as rejected
  #13  a failed read looked like "no positions" / "no orders"
  #12  one dead bridge delayed fires on every account
  #7   dashboard close stuck in 'closing'
  #9   concurrent modifies on the bridge lost a change

DB-backed where the finding is about persisted state (throwaway Postgres via
conftest `db_pool`); the connector and bridge tests are pure unit tests.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

import db
from executor import Executor
from models import Direction, SignalAction, SignalType
from mt5_connector import ConnectorReadError, OrderResult, Position, RestApiConnector
from trade_manager import OUTCOME_UNKNOWN_REASON, READ_FAILED_REASON

pytestmark = pytest.mark.asyncio(loop_scope="session")

ACCT = "test-acct"


# ── helpers ────────────────────────────────────────────────────────────


async def _insert_stage(
    *, signal_id: int, stage_number: int, status: str = "awaiting_zone",
    account: str = ACCT, direction: str = "buy",
    band_low: float = 2040.0, band_high: float = 2042.5,
    mt5_ticket: int | None = None, signal_sl: float | None = None,
    signal_tp: float | None = None, firing_minutes_ago: int | None = None,
    cancelled_reason: str | None = None,
) -> int:
    snapshot = {
        "account_name": account, "risk_mode": "fixed_lot", "risk_value": 0.5,
        "max_stages": 5, "default_sl_pips": 100, "max_daily_trades": 30,
        "max_open_trades": 5, "max_lot_size": 1.0,
    }
    async with db._pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO staged_entries
               (signal_id, stage_number, account_name, symbol, direction,
                zone_low, zone_high, band_low, band_high, target_lot,
                snapshot_settings, mt5_comment, mt5_ticket, status,
                signal_sl, signal_tp, firing_at, cancelled_reason)
               VALUES ($1,$2,$3,'XAUUSD',$4,$5,$6,$5,$6,0.1,$7::jsonb,$8,$9,$10,
                       $11,$12,
                       CASE WHEN $13::int IS NULL THEN NULL
                            ELSE NOW() - make_interval(mins => $13) END,
                       $14)
               RETURNING id""",
            signal_id, stage_number, account, direction, band_low, band_high,
            json.dumps(snapshot), f"telebot-{signal_id}-s{stage_number}",
            mt5_ticket, status, signal_sl, signal_tp, firing_minutes_ago,
            cancelled_reason,
        )


async def _stage(row_id: int) -> dict:
    async with db._pool.acquire() as conn:
        return dict(await conn.fetchrow("SELECT * FROM staged_entries WHERE id=$1", row_id))


async def _trades(account: str = ACCT) -> list[dict]:
    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM trades WHERE account_name=$1 ORDER BY id", account,
        )
    return [dict(r) for r in rows]


def _position(ticket: int, comment: str, *, direction="buy", open_price=2040.0,
              sl=2030.0, tp=2080.0, volume=0.1) -> Position:
    return Position(
        ticket=ticket, symbol="XAUUSD", direction=direction, volume=volume,
        open_price=open_price, sl=sl, tp=tp, profit=0.0, comment=comment,
    )


async def _fire(executor: Executor, connector, row_id: int) -> None:
    row = await _stage(row_id)
    await executor._fire_zone_stage(
        acct_name=row["account_name"], connector=connector, symbol="XAUUSD",
        stage=row, bid=2040.1, ask=2040.2, signal_id=row["signal_id"],
    )


@pytest_asyncio.fixture
async def executor(tm_with_store, global_config):
    """Executor wrapping the DB-backed TradeManager; loops are not started."""
    return Executor(trade_manager=tm_with_store, global_config=global_config, notifier=None)


# REST connector with a canned transport ─────────────────────────────────


def _rest_connector(handler) -> RestApiConnector:
    conn = RestApiConnector(
        account_name=ACCT, server="TestServer", login=12345, password="secret",
        host="localhost", port=8001, api_key="k", use_tls=False,
    )
    conn._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=conn._base_url,
        timeout=15.0, headers={"X-API-Key": "k"},
    )
    return conn


def _error_body(code: str, message: str) -> httpx.Response:
    return httpx.Response(
        500, json={"ok": False, "data": None, "error": {"code": code, "message": message}},
    )


@pytest.fixture
def no_retry_sleep(monkeypatch):
    """Skip the connector's 1 s retry backoff (GET reads retry 3x).

    NOT autouse: it replaces asyncio.sleep globally for the test, which would
    turn the executor loops into busy spins in the tests that start them.
    """
    async def _fast(*_a, **_k):
        return None
    monkeypatch.setattr("mt5_connector.asyncio.sleep", _fast)


# ═══════════════════════════════════════════════════════════════════════
# #3  timed-out order is NOT a rejection
# ═══════════════════════════════════════════════════════════════════════


async def test_post_readtimeout_open_order_reports_outcome_unknown():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer")

    conn = _rest_connector(handler)
    from mt5_connector import OrderType
    result = await conn.open_order("XAUUSD", OrderType.MARKET_BUY, 0.1, sl=2030.0)
    assert result.success is False
    assert result.outcome_unknown is True, "a sent-but-unanswered order is not a reject"
    assert "outcome unknown" in result.error


async def test_broker_reject_is_not_outcome_unknown():
    def handler(request: httpx.Request) -> httpx.Response:
        return _error_body("10016", "invalid stops")

    conn = _rest_connector(handler)
    from mt5_connector import OrderType
    result = await conn.open_order("XAUUSD", OrderType.MARKET_BUY, 0.1, sl=2030.0)
    assert result.success is False
    assert result.outcome_unknown is False
    assert "10016" in result.error


async def test_unknown_outcome_keeps_stage_firing_then_adopts_the_position(
    db_pool, seeded_signal, priced_connector, tm_with_store, executor,
):
    sid = seeded_signal
    s1 = f"telebot-{sid}-s1"
    priced_connector._fake_positions[501] = _position(501, s1)
    await _insert_stage(signal_id=sid, stage_number=1, status="filled", mt5_ticket=501)
    row_id = await _insert_stage(signal_id=sid, stage_number=2)

    async def timed_out_open(**_kwargs):
        return OrderResult(success=False, error="POST /api/v1/order timed out (outcome unknown)",
                           outcome_unknown=True)
    priced_connector.open_order = timed_out_open

    await _fire(executor, priced_connector, row_id)

    row = await _stage(row_id)
    assert row["status"] == "firing", "the claim is kept: the order may be live"
    assert row["cancelled_reason"] == db.STAGE_OUTCOME_UNKNOWN
    assert not [t for t in await _trades() if t["status"] == "failed"], \
        "no 'failed' trade row for an order whose outcome is unknown"

    # The order DID fill on the broker; the position carries our unique comment.
    priced_connector._fake_positions[777] = _position(
        777, f"telebot-{sid}-s2", open_price=2040.2, sl=2032.5, tp=0.0,
    )
    await executor._reconcile_stale_firing_stages()

    row = await _stage(row_id)
    assert row["status"] == "filled"
    assert row["mt5_ticket"] == 777
    adopted = [t for t in await _trades() if t["ticket"] == 777]
    assert len(adopted) == 1 and adopted[0]["status"] == "opened"
    assert adopted[0]["entry_price"] == pytest.approx(2040.2)
    assert adopted[0]["signal_id"] == sid


async def test_unknown_outcome_row_is_checked_at_once_but_failed_only_after_grace(
    db_pool, seeded_signal, priced_connector, executor,
):
    sid = seeded_signal
    row_id = await _insert_stage(
        signal_id=sid, stage_number=2, status="firing", firing_minutes_ago=0,
        cancelled_reason=db.STAGE_OUTCOME_UNKNOWN,
    )
    # No position yet → inside the grace period the row is left alone.
    await executor._reconcile_stale_firing_stages()
    assert (await _stage(row_id))["status"] == "firing"

    async with db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE staged_entries SET firing_at = NOW() - make_interval(mins => 10) WHERE id=$1",
            row_id,
        )
    await executor._reconcile_stale_firing_stages()
    row = await _stage(row_id)
    assert row["status"] == "failed"
    assert row["cancelled_reason"] == "firing_stale_no_position_after_unknown_outcome"


async def test_unstaged_unknown_outcome_records_an_unknown_trade_row(
    db_pool, seeded_account, tm_with_store, priced_connector,
):
    """Legacy (non-staged) path: nothing reconciles it, so the operator at least
    sees an 'unknown' trade instead of a bogus 'failed' one."""
    async def timed_out_open(**_kwargs):
        return OrderResult(success=False, error="timed out (outcome unknown)", outcome_unknown=True)
    priced_connector.open_order = timed_out_open

    acct = tm_with_store.accounts[ACCT]
    signal = SignalAction(
        type=SignalType.OPEN, symbol="XAUUSD", raw_text="buy", direction=Direction.BUY,
        entry_zone=(2040.0, 2041.0), sl=2030.0, tps=[2080.0], target_tp=2080.0,
    )
    result = await tm_with_store._execute_open_on_account(signal, None, acct, priced_connector)
    assert result["status"] == "unknown"
    assert result["reason"] == OUTCOME_UNKNOWN_REASON
    statuses = [t["status"] for t in await _trades()]
    assert statuses == ["unknown"]


# ═══════════════════════════════════════════════════════════════════════
# #13  a failed read is not an empty broker
# ═══════════════════════════════════════════════════════════════════════


async def test_rest_reads_raise_instead_of_returning_empty(no_retry_sleep):
    def handler(request: httpx.Request) -> httpx.Response:
        return _error_body("INTERNAL", "boom")

    conn = _rest_connector(handler)
    with pytest.raises(ConnectorReadError):
        await conn.get_positions()
    with pytest.raises(ConnectorReadError):
        await conn.get_pending_orders()
    with pytest.raises(ConnectorReadError):
        await conn.get_history_deals(datetime.now(timezone.utc) - timedelta(hours=1))


async def test_expired_limit_order_survives_a_failed_pending_orders_read(
    db_pool, seeded_account, tm_with_store, priced_connector,
):
    order_id = await db.log_pending_order(
        signal_id=None, account_name=ACCT, ticket=9001, symbol="XAUUSD",
        order_type="buy_limit", volume=0.1, price=2035.0, sl=2025.0, tp=2060.0,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )

    async def failing_read(symbol=None):
        raise ConnectorReadError("bridge down")
    cancelled: list[int] = []

    async def spy_cancel(ticket):
        cancelled.append(ticket)
        return OrderResult(success=True, ticket=ticket)
    priced_connector.get_pending_orders = failing_read
    priced_connector.cancel_pending = spy_cancel

    results = await tm_with_store.cleanup_expired_orders()

    assert results == [{"account": ACCT, "status": "read_failed", "ticket": 9001, "symbol": "XAUUSD"}]
    assert cancelled == []
    async with db._pool.acquire() as conn:
        status = await conn.fetchval("SELECT status FROM pending_orders WHERE id=$1", order_id)
    assert status == "active", "the order was NOT marked cancelled behind the broker's back"


async def test_positions_read_failure_keeps_the_stage_armed(
    db_pool, seeded_signal, priced_connector, executor,
):
    row_id = await _insert_stage(signal_id=seeded_signal, stage_number=2)

    async def failing_read(symbol=None):
        raise ConnectorReadError("bridge down")
    priced_connector.get_positions = failing_read

    await _fire(executor, priced_connector, row_id)

    row = await _stage(row_id)
    assert row["status"] == "awaiting_zone", "no write at all on a failed read"
    assert row["cancelled_reason"] is None


async def test_close_signal_with_failed_read_closes_nothing(
    db_pool, seeded_account, tm_with_store, priced_connector,
):
    closed: list[int] = []

    async def failing_read(symbol=None):
        raise ConnectorReadError("bridge down")

    async def spy_close(ticket, volume=None):
        closed.append(ticket)
        return OrderResult(success=True, ticket=ticket)
    priced_connector.get_positions = failing_read
    priced_connector.close_position = spy_close

    results = await tm_with_store.handle_signal(
        SignalAction(type=SignalType.CLOSE, symbol="XAUUSD", raw_text="close all"),
    )
    assert results == [{"account": ACCT, "status": "failed", "reason": READ_FAILED_REASON}]
    assert closed == []


async def test_history_sync_read_failure_does_not_advance_the_watermark(
    db_pool, seeded_account, priced_connector, executor,
):
    await db.log_trade(
        signal_id=None, account_name=ACCT, symbol="XAUUSD", direction="buy",
        entry_price=2040.0, sl=2030.0, tp=2060.0, lot_size=0.1, ticket=4242,
        status="opened", raw_signal="t",
    )

    async def failing_history(since, until=None):
        raise ConnectorReadError("bridge down")
    priced_connector.get_history_deals = failing_history

    await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)
    assert ACCT not in executor._last_history_sync, \
        "a failed read must not skip the window the deals would have been in"


# ═══════════════════════════════════════════════════════════════════════
# #12  one dead bridge must not delay the others
# ═══════════════════════════════════════════════════════════════════════


class _HangingConnector:
    """Accepts calls and never answers (a bridge that is up but wedged)."""
    connected = True

    def __init__(self):
        self.calls = 0

    async def get_price(self, symbol):
        self.calls += 1
        await asyncio.sleep(60)

    async def get_positions(self, symbol=None):
        self.calls += 1
        await asyncio.sleep(60)


async def test_hanging_bridge_does_not_delay_other_accounts_fires(
    db_pool, seeded_signal, priced_connector, tm_with_store, executor,
):
    sid = seeded_signal
    # A second account whose bridge hangs; its stage is listed FIRST.
    await db.upsert_account_if_missing(
        name="dead-acct", server="Test", login=1, password_env="",
        risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
        max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
    )
    hanging = _HangingConnector()
    tm_with_store.connectors["dead-acct"] = hanging
    async with db._pool.acquire() as conn:
        dead_sid = await conn.fetchval(
            """INSERT INTO signals (raw_text, signal_type, symbol, direction, action_taken)
               VALUES ('dead', 'open', 'XAUUSD', 'buy', 'staged') RETURNING id""",
        )
    dead_row = await _insert_stage(signal_id=dead_sid, stage_number=2, account="dead-acct")

    # The healthy account: stage 1 live, stage 2 in band at 2040.1/2040.2.
    priced_connector._fake_positions[501] = _position(501, f"telebot-{sid}-s1")
    await _insert_stage(signal_id=sid, stage_number=1, status="filled", mt5_ticket=501)
    live_row = await _insert_stage(signal_id=sid, stage_number=2)

    executor._READ_TIMEOUT_SECONDS = 0.2
    started = time.monotonic()
    await asyncio.wait_for(executor._zone_watch_tick(), timeout=5.0)
    elapsed = time.monotonic() - started

    assert (await _stage(live_row))["status"] == "filled", "the healthy account fired"
    assert (await _stage(dead_row))["status"] == "awaiting_zone", "the dead one just waits"
    assert hanging.calls >= 1
    assert elapsed < 3.0, f"tick took {elapsed:.1f}s with a hanging bridge"


async def test_sweep_skips_a_disconnected_account(
    db_pool, seeded_signal, priced_connector, executor,
):
    sid = seeded_signal
    await _insert_stage(
        signal_id=sid, stage_number=1, status="filled", mt5_ticket=501,
        signal_sl=2030.0, signal_tp=2080.0,
    )
    reads = {"n": 0}
    real_get_positions = priced_connector.get_positions

    async def counting(symbol=None):
        reads["n"] += 1
        return await real_get_positions(symbol)
    priced_connector.get_positions = counting

    priced_connector._connected = False
    try:
        await executor._run_stage_sltp_verification_sweep()
        await executor._run_orphan_protective_tp_watchdog()
        await executor._reconcile_stale_firing_stages()
    finally:
        priced_connector._connected = True
    assert reads["n"] == 0, "a disconnected bridge is the heartbeat's problem, not the sweep's"


async def test_maintenance_passes_run_outside_the_fire_tick(
    db_pool, seeded_signal, executor, monkeypatch,
):
    called: list[str] = []

    # Batch 5: the passes take the shared per-tick positions cache (#6).
    async def record_sweep(positions_cache=None):
        called.append("sweep")

    async def record_orphan(positions_cache=None):
        called.append("orphan")

    async def record_stale(positions_cache=None):
        called.append("stale")

    async def record_fills(positions_cache=None):
        called.append("fills")
    monkeypatch.setattr(executor, "_run_stage_sltp_verification_sweep", record_sweep)
    monkeypatch.setattr(executor, "_run_orphan_protective_tp_watchdog", record_orphan)
    monkeypatch.setattr(executor, "_reconcile_stale_firing_stages", record_stale)
    monkeypatch.setattr(executor, "_detect_pending_order_fills", record_fills)

    await _insert_stage(signal_id=seeded_signal, stage_number=2)
    await executor._zone_watch_tick()
    assert called == [], "the fire tick no longer waits on the maintenance passes"

    # One iteration of the maintenance loop runs all four.
    real_sleep = asyncio.sleep
    ticks = {"n": 0}

    async def one_tick(delay):
        ticks["n"] += 1
        if ticks["n"] >= 2:
            raise asyncio.CancelledError()
        await real_sleep(0)
    monkeypatch.setattr("executor.asyncio.sleep", one_tick)
    try:
        await executor._stage_maintenance_loop()
    except asyncio.CancelledError:
        pass
    # Batch 6: the irreversible stale-firing decision runs on the fresh snapshot.
    assert called == ["stale", "fills", "orphan", "sweep"]


async def test_start_runs_the_maintenance_loop_as_its_own_task(executor):
    await executor.start()
    try:
        assert executor._stage_maintenance_task is not None
        assert executor._stage_maintenance_task is not executor._zone_watch_task
    finally:
        await executor.stop()
    assert executor._stage_maintenance_task.cancelled() or executor._stage_maintenance_task.done()


# ═══════════════════════════════════════════════════════════════════════
# #7  dashboard close must reach 'closed'
# ═══════════════════════════════════════════════════════════════════════


async def _insert_open_trade(account: str, ticket: int) -> int:
    return await db.log_trade(
        signal_id=None, account_name=account, symbol="XAUUSD", direction="buy",
        entry_price=2800.123, sl=2790.0, tp=2820.0, lot_size=0.30, ticket=ticket,
        status="opened", raw_signal="t",
    )


async def test_dashboard_close_on_dry_run_finalizes_the_trade(db_pool, session_client):
    """The api_app stub is a DryRunConnector (no deal history): the close route
    finalizes the trade itself instead of parking it in 'closing' forever."""
    client, csrf = session_client
    account, ticket = "Vantage Demo-10k", 100001
    await _insert_open_trade(account, ticket)

    r = await client.post(
        f"/api/v2/positions/{account}/{ticket}/close", headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True

    async with db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, pnl, close_price FROM trades WHERE ticket=$1 AND account_name=$2",
            ticket, account,
        )
    assert row["status"] == "closed"
    # buy 0.30 lots opened at 2800.123, simulated bid 2805.0 → (bid-open)*vol*100
    assert float(row["pnl"]) == pytest.approx((2805.0 - 2800.123) * 0.30 * 100, abs=0.01)
    assert float(row["close_price"]) == pytest.approx(2805.0)


async def test_mark_trade_closing_never_reopens_a_closed_trade(db_pool, seeded_account):
    ticket = 880001
    await _insert_open_trade(ACCT, ticket)
    await db.update_trade_close(ticket, ACCT, pnl=7.5, close_price=2810.0)

    moved = await db.mark_trade_closing(ticket, ACCT, 2805.0, pnl_estimate=1.0)
    assert moved is False

    async with db._pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status, pnl FROM trades WHERE ticket=$1", ticket)
    assert row["status"] == "closed"
    assert float(row["pnl"]) == pytest.approx(7.5), "the reconciled P&L is untouched"


async def test_stale_closing_trade_is_finalized_from_the_estimate(
    db_pool, seeded_account, executor,
):
    stale, fresh = 880101, 880102
    await _insert_open_trade(ACCT, stale)
    await _insert_open_trade(ACCT, fresh)
    assert await db.mark_trade_closing(stale, ACCT, 2805.0, pnl_estimate=12.5) is True
    assert await db.mark_trade_closing(fresh, ACCT, 2806.0, pnl_estimate=3.0) is True
    async with db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE trades SET close_time = NOW() - make_interval(mins => 20) WHERE ticket=$1",
            stale,
        )

    # Batch 5: the fallback only acts once the history window up to the
    # watermark has been read; stand in for one completed sync.
    executor._last_history_sync[ACCT] = datetime.now(timezone.utc)
    finalized = await executor._finalize_stale_closing_trades(ACCT)
    assert finalized == 1

    async with db._pool.acquire() as conn:
        rows = {
            r["ticket"]: dict(r) for r in await conn.fetch(
                "SELECT ticket, status, pnl, close_price FROM trades WHERE ticket = ANY($1::bigint[])",
                [stale, fresh],
            )
        }
    assert rows[stale]["status"] == "closed"
    assert float(rows[stale]["pnl"]) == pytest.approx(12.5)
    assert float(rows[stale]["close_price"]) == pytest.approx(2805.0)
    assert rows[fresh]["status"] == "closing", "a fresh close still waits for the broker deal"


async def test_history_sync_runs_the_stale_closing_fallback(
    db_pool, seeded_account, priced_connector, executor,
):
    ticket = 880201
    await _insert_open_trade(ACCT, ticket)
    await db.mark_trade_closing(ticket, ACCT, 2805.0, pnl_estimate=4.0)
    async with db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE trades SET close_time = NOW() - make_interval(mins => 20) WHERE ticket=$1",
            ticket,
        )
    # DryRunConnector.get_history_deals is always empty — exactly the stuck case.
    await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)
    async with db._pool.acquire() as conn:
        status = await conn.fetchval("SELECT status FROM trades WHERE ticket=$1", ticket)
    assert status == "closed"


# ═══════════════════════════════════════════════════════════════════════
# #9  bridge: concurrent modifies on one ticket
# ═══════════════════════════════════════════════════════════════════════


def _load_bridge_server(fake_mt5: types.ModuleType):
    """Import mt5-rest-server/server.py against a fake MetaTrader5 + config."""
    fake_config = types.ModuleType("config")
    fake_config.API_KEY = "k"
    fake_config.MT5_LOGIN = 0
    fake_config.MT5_PASSWORD = ""
    fake_config.MT5_SERVER = ""
    fake_config.MT5_TERMINAL_PATH = ""
    fake_config.MT5_MAGIC_NUMBER = 202603
    fake_config.PORT = 8001

    saved = {name: sys.modules.get(name) for name in ("MetaTrader5", "config")}
    sys.modules["MetaTrader5"] = fake_mt5
    sys.modules["config"] = fake_config
    try:
        path = Path(__file__).resolve().parents[1] / "mt5-rest-server" / "server.py"
        spec = importlib.util.spec_from_file_location("mt5_bridge_server_under_test", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


class _FakeMT5Module(types.ModuleType):
    """Any UPPER_CASE attribute is a constant; the ones with semantics are set
    explicitly below. The server builds its order-type map at import time."""

    def __getattr__(self, name):
        if name.isupper():
            return abs(hash(name)) % 100000 + 1000
        raise AttributeError(name)


def _fake_mt5_with_one_position(ticket: int, *, sl: float, tp: float) -> tuple[types.ModuleType, dict]:
    state = {"sl": sl, "tp": tp, "sends": 0}
    mt5 = _FakeMT5Module("MetaTrader5")
    mt5.TRADE_ACTION_SLTP = 6
    mt5.TRADE_ACTION_DEAL = 1
    mt5.TRADE_RETCODE_DONE = 10009
    mt5.TRADE_RETCODE_INVALID_FILL = 10030
    mt5.ORDER_TYPE_BUY = 0
    mt5.ORDER_TYPE_SELL = 1
    mt5.ORDER_FILLING_RETURN = 2

    def positions_get(**kwargs):
        if kwargs.get("ticket") != ticket:
            return ()
        return (types.SimpleNamespace(
            ticket=ticket, symbol="XAUUSD", type=0, volume=0.1,
            sl=state["sl"], tp=state["tp"],
        ),)

    def symbol_select(symbol, enable):
        return True

    def order_send(request):
        # The real call blocks for a while; long enough for the other
        # coroutine's read to be queued behind it on the single MT5 thread.
        time.sleep(0.02)
        state["sl"] = request["sl"]
        state["tp"] = request["tp"]
        state["sends"] += 1
        return types.SimpleNamespace(retcode=10009, comment="done", price=0.0, volume=0.1, order=ticket)

    def last_error():
        return (1, "Success")

    mt5.positions_get = positions_get
    mt5.symbol_select = symbol_select
    mt5.order_send = order_send
    mt5.last_error = last_error
    return mt5, state


async def test_concurrent_modifies_on_one_ticket_keep_both_changes():
    fake_mt5, state = _fake_mt5_with_one_position(42, sl=1.0, tp=1.0)
    server = _load_bridge_server(fake_mt5)
    try:
        await asyncio.gather(
            server.modify_position(42, server.ModifyRequest(sl=2.0)),
            server.modify_position(42, server.ModifyRequest(tp=3.0)),
        )
    finally:
        server._mt5_executor.shutdown(wait=True)

    assert state["sends"] == 2
    assert (state["sl"], state["tp"]) == (2.0, 3.0), \
        "the second modify must read the first one's result, not the stale levels"


async def test_ticket_locks_are_per_ticket():
    fake_mt5, _ = _fake_mt5_with_one_position(7, sl=1.0, tp=1.0)
    server = _load_bridge_server(fake_mt5)
    try:
        assert server._ticket_lock(7) is server._ticket_lock(7)
        assert server._ticket_lock(7) is not server._ticket_lock(8)
    finally:
        server._mt5_executor.shutdown(wait=True)
