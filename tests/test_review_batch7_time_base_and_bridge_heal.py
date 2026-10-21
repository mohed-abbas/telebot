"""Batch 7 — fixes for the 2026-10-17 /code-review of batch 6, plus the bridge
outage seen on the VPS on 2026-10-21 (MT5 auto-updated and restarted; the
bridge kept a dead IPC pipe until restarted by hand).

  A  deal times are broker-server time: reads are widened by DEAL_TIME_MARGIN,
     the watermark stays on our clock, close_time is not taken from a deal
  B  entry 2 (inout / netting reversal) is not a close
  C  the stale-'closing' fallback keeps the submit-time close_time
  D  zone watch: one log line per unverifiable stage 1
  E  expiry cleanup reads history from its oldest order (window widened)
  G  bridge re-attaches to a replaced terminal; reads retried, sends never
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

import db
from executor import Executor
from mt5_connector import DEAL_TIME_MARGIN, Deal

pytestmark = pytest.mark.asyncio(loop_scope="session")

ACCT = "test-acct"
BROKER_OFFSET = timedelta(hours=3)  # e.g. Vantage server time, UTC+3


@pytest_asyncio.fixture
async def executor(tm_with_store, global_config):
    return Executor(trade_manager=tm_with_store, global_config=global_config, notifier=None)


async def _insert_trade(ticket: int, status: str = "opened") -> int:
    return await db.log_trade(
        signal_id=None, account_name=ACCT, symbol="XAUUSD", direction="buy",
        entry_price=2040.0, sl=2030.0, tp=2060.0, lot_size=0.1,
        ticket=ticket, status=status, raw_signal="test",
    )


async def _trade(ticket: int) -> dict:
    async with db._pool.acquire() as conn:
        return dict(await conn.fetchrow(
            "SELECT * FROM trades WHERE ticket=$1 AND account_name=$2", ticket, ACCT,
        ))


async def _insert_expired_order(ticket: int, *, created_hours_ago: float = 0.0) -> int:
    expires = datetime.now(timezone.utc) - timedelta(minutes=5)
    row_id = await db.log_pending_order(
        None, ACCT, ticket, "XAUUSD", "buy_limit", 0.1, 2035.0, 2025.0, 2060.0, expires,
    )
    if created_hours_ago:
        async with db._pool.acquire() as conn:
            await conn.execute(
                "UPDATE pending_orders SET created_at = NOW() - make_interval(secs => $2) WHERE id=$1",
                row_id, created_hours_ago * 3600,
            )
    return row_id


def _broker_deal(position_id: int, *, entry: int, profit: float, price: float,
                 real_minutes_ago: float = 0.0) -> Deal:
    """A deal stamped the way MT5 stamps it: broker-server clock, not UTC."""
    real = datetime.now(timezone.utc) - timedelta(minutes=real_minutes_ago)
    return Deal(ticket=position_id + 1, position_id=position_id,
                time=(real + BROKER_OFFSET).timestamp(), entry=entry,
                volume=0.1, price=price, profit=profit)


def _broker_history(connector, deals, calls: list | None = None) -> None:
    """Behaves like the bridge: returns only deals whose (broker) time lies in
    the requested window."""
    connector.supports_history_sync = True

    async def get_history_deals(since, until=None):
        until = until or datetime.now(timezone.utc)
        if calls is not None:
            calls.append((since, until))
        return [d for d in deals if since.timestamp() <= d.time <= until.timestamp()]

    connector.get_history_deals = get_history_deals


# ── A ──────────────────────────────────────────────────────────────────


async def test_history_sync_sees_a_broker_clock_deal_immediately(
    db_pool, seeded_account, priced_connector, executor,
):
    ticket = 710001
    await _insert_trade(ticket)
    # Closed a minute ago in real time; its broker stamp is 3h ahead of UTC.
    _broker_history(priced_connector, [_broker_deal(ticket, entry=1, profit=12.0, price=2052.0,
                                                    real_minutes_ago=1)])

    await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)

    row = await _trade(ticket)
    assert row["status"] == "closed", "reconciled now, not three hours from now"
    assert float(row["pnl"]) == pytest.approx(12.0)
    age = datetime.now(timezone.utc) - row["close_time"]
    assert timedelta(0) <= age < timedelta(minutes=1), "close_time on our clock, not the broker's"


async def test_watermark_stays_on_our_clock_and_the_window_never_inverts(
    db_pool, seeded_account, priced_connector, executor,
):
    t1, t2 = 710011, 710012
    await _insert_trade(t1)
    await _insert_trade(t2)
    deals = [_broker_deal(t1, entry=1, profit=1.0, price=2041.0, real_minutes_ago=2)]
    calls: list = []
    _broker_history(priced_connector, deals, calls)

    before = datetime.now(timezone.utc)
    await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)
    after = datetime.now(timezone.utc)

    watermark = executor._last_history_sync[ACCT]
    assert before <= watermark <= after, "the deal's broker time (now+3h) must not become the watermark"

    # The next close lands in the next read.
    deals.append(_broker_deal(t2, entry=1, profit=2.0, price=2042.0))
    await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)
    assert (await _trade(t2))["status"] == "closed"

    since, until = calls[-1]
    assert since < until
    assert since <= watermark - DEAL_TIME_MARGIN
    assert until >= datetime.now(timezone.utc) + DEAL_TIME_MARGIN - timedelta(seconds=5)


# ── B ──────────────────────────────────────────────────────────────────


async def test_reversal_deal_does_not_close_the_trade(
    db_pool, seeded_account, priced_connector, executor,
):
    ticket = 720001
    await _insert_trade(ticket)
    _broker_history(priced_connector, [_broker_deal(ticket, entry=2, profit=5.0, price=2045.0)])

    await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)

    assert (await _trade(ticket))["status"] == "opened", "a netting reversal keeps the position open"


async def test_expiry_probe_ignores_a_reversal_deal(
    db_pool, seeded_account, tm_with_store, priced_connector,
):
    ticket = 720002
    await _insert_trade(ticket, status="pending")
    await _insert_expired_order(ticket)
    _broker_history(priced_connector, [_broker_deal(ticket, entry=2, profit=5.0, price=2045.0)])

    results = await tm_with_store.cleanup_expired_orders()

    assert [r["status"] for r in results] == ["cancelled"]


# ── C ──────────────────────────────────────────────────────────────────


async def test_stale_closing_fallback_keeps_the_submit_time(
    db_pool, seeded_account, priced_connector, executor,
):
    ticket = 730001
    await _insert_trade(ticket)
    assert await db.mark_trade_closing(ticket, ACCT, 2805.0, pnl_estimate=4.0) is True
    async with db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE trades SET close_time = NOW() - make_interval(mins => 20) WHERE ticket=$1",
            ticket,
        )
    _broker_history(priced_connector, [])

    await executor._sync_history_for_account(ACCT, priced_connector, lookback_hours=24)

    row = await _trade(ticket)
    assert row["status"] == "closed"
    age = datetime.now(timezone.utc) - row["close_time"]
    assert timedelta(minutes=19) < age < timedelta(minutes=21), "not overwritten with 'now'"


# ── D ──────────────────────────────────────────────────────────────────


async def test_unknown_stage1_logs_one_line_per_signal(
    db_pool, seeded_signal, priced_connector, executor, monkeypatch, caplog,
):
    sid = seeded_signal
    snapshot = {
        "account_name": ACCT, "risk_mode": "fixed_lot", "risk_value": 0.5,
        "max_stages": 5, "default_sl_pips": 100, "max_daily_trades": 30,
        "max_open_trades": 5, "max_lot_size": 1.0,
    }
    async with db._pool.acquire() as conn:
        for n, status, ticket in ((1, "filled", 701), (2, "awaiting_zone", None)):
            await conn.execute(
                """INSERT INTO staged_entries
                   (signal_id, stage_number, account_name, symbol, direction,
                    zone_low, zone_high, band_low, band_high, target_lot,
                    snapshot_settings, mt5_comment, mt5_ticket, status)
                   VALUES ($1,$2,$3,'XAUUSD','buy',2040.0,2042.5,2040.0,2042.5,0.1,
                           $4::jsonb,$5,$6,$7)""",
                sid, n, ACCT, json.dumps(snapshot), f"telebot-{sid}-s{n}", ticket, status,
            )

    async def boom(*args, **kwargs):
        raise RuntimeError("pool exhausted")

    monkeypatch.setattr(db, "get_stage_by_signal_account", boom)

    with caplog.at_level(logging.WARNING, logger="executor"):
        await executor._zone_watch_tick()

    lines = [r for r in caplog.records if f"signal_id={sid}" in r.getMessage()]
    assert len(lines) == 1, [r.getMessage() for r in lines]
    assert priced_connector._fake_positions == {}


# ── E ──────────────────────────────────────────────────────────────────


async def test_cleanup_reads_from_the_oldest_order_with_margin(
    db_pool, seeded_account, tm_with_store, priced_connector,
):
    for ticket, hours in ((740001, 0.0), (740002, 3.0)):
        await _insert_trade(ticket, status="pending")
        await _insert_expired_order(ticket, created_hours_ago=hours)
    # 740002 filled and closed 2h ago (real time) — broker stamp is +3h.
    calls: list = []
    _broker_history(priced_connector,
                    [_broker_deal(740002, entry=1, profit=6.0, price=2048.0, real_minutes_ago=120)],
                    calls)

    results = await tm_with_store.cleanup_expired_orders()

    assert len(calls) == 1
    since, until = calls[0]
    oldest = datetime.now(timezone.utc) - timedelta(hours=3)
    assert since <= oldest - DEAL_TIME_MARGIN + timedelta(seconds=5)
    assert until >= datetime.now(timezone.utc) + DEAL_TIME_MARGIN - timedelta(seconds=5)
    assert {r["ticket"]: r["status"] for r in results} == {
        740001: "cancelled", 740002: "filled_closed",
    }


# ═══════════════════════════════════════════════════════════════════════
# G  bridge: re-attach to a replaced terminal
# ═══════════════════════════════════════════════════════════════════════


class _FakeMT5Module(types.ModuleType):
    def __getattr__(self, name):
        if name.isupper():
            return abs(hash(name)) % 100000 + 1000
        raise AttributeError(name)


def _fake_terminal(*, terminal_up: bool = True, attached: bool = True):
    """A terminal whose IPC pipe can die. `terminal_up` is whether a terminal
    process is running and logged in; `pipe` is whether initialize() attached."""
    state = {"terminal_up": terminal_up, "pipe": attached, "err": (1, "Success"),
             "init_calls": [], "sends": 0, "reads": 0}
    mt5 = _FakeMT5Module("MetaTrader5")

    def _dead():
        state["err"] = (-10004, "No IPC connection")
        return None

    def _live(value):
        state["err"] = (1, "Success")
        return value

    def initialize(*args, **kwargs):
        state["init_calls"].append((args, kwargs))
        if state["terminal_up"]:
            state["pipe"] = True
            return _live(True)
        state["pipe"] = False
        state["err"] = (-6, "Terminal: Authorization failed")
        return False

    def shutdown():
        state["pipe"] = False
        return True

    def positions_get(**kwargs):
        state["reads"] += 1
        return _live(()) if state["pipe"] else _dead()

    def account_info():
        return _live(types.SimpleNamespace(login=26298599, balance=10000.0, equity=10000.0)) \
            if state["pipe"] else _dead()

    def terminal_info():
        return _live(types.SimpleNamespace(connected=True)) if state["pipe"] else _dead()

    def order_send(request):
        state["sends"] += 1
        return _live(types.SimpleNamespace(retcode=10009)) if state["pipe"] else _dead()

    def last_error():
        return state["err"]

    for fn in (initialize, shutdown, positions_get, account_info, terminal_info,
               order_send, last_error):
        setattr(mt5, fn.__name__, fn)
    return mt5, state


def _load_bridge(fake_mt5):
    cfg = types.ModuleType("config")
    cfg.API_KEY = "k"
    cfg.MT5_LOGIN = 26298599
    cfg.MT5_PASSWORD = "pw"
    cfg.MT5_SERVER = "VantageMarkets-Demo"
    cfg.MT5_TERMINAL_PATH = r"C:\MT5\Vantage\MetaTrader 5\terminal64.exe"
    cfg.MT5_MAGIC_NUMBER = 202603
    cfg.PORT = 8001
    saved = {name: sys.modules.get(name) for name in ("MetaTrader5", "config")}
    sys.modules["MetaTrader5"] = fake_mt5
    sys.modules["config"] = cfg
    try:
        path = Path(__file__).resolve().parents[1] / "mt5-rest-server" / "server.py"
        spec = importlib.util.spec_from_file_location("mt5_bridge_server_batch7", path)
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


async def test_read_reattaches_after_terminal_restart():
    fake, state = _fake_terminal()
    server = _load_bridge(fake)
    try:
        state["pipe"] = False  # MT5 auto-updated and restarted under the bridge

        result, error = await server._run_err(fake.positions_get, symbol="XAUUSD")

        assert result == () and error == (1, "Success"), "healed and retried"
        assert len(state["init_calls"]) == 1
        args, kwargs = state["init_calls"][0]
        assert args == (r"C:\MT5\Vantage\MetaTrader 5\terminal64.exe",)
        assert kwargs == {"login": 26298599, "password": "pw", "server": "VantageMarkets-Demo"}
    finally:
        server._mt5_executor.shutdown(wait=True)


async def test_order_send_is_never_repeated():
    fake, state = _fake_terminal()
    server = _load_bridge(fake)
    try:
        state["pipe"] = False

        result, error = await server._run_err(fake.order_send, {"action": 1})

        assert result is None and error[0] == -10004, "the caller sees the failure"
        assert state["sends"] == 1, "a send that may have reached the broker is not repeated"
        assert state["pipe"] is True, "but the pipe is fresh for the next request"
    finally:
        server._mt5_executor.shutdown(wait=True)


async def test_concurrent_failures_attach_once():
    fake, state = _fake_terminal()
    server = _load_bridge(fake)
    try:
        state["pipe"] = False

        results = await asyncio.gather(*(
            server._run_err(fake.positions_get, symbol="XAUUSD") for _ in range(5)
        ))

        assert all(r == () for r, _ in results)
        assert len(state["init_calls"]) == 1
    finally:
        server._mt5_executor.shutdown(wait=True)


async def test_a_dead_terminal_is_not_hammered():
    fake, state = _fake_terminal(terminal_up=False, attached=False)
    server = _load_bridge(fake)
    try:
        r1, _ = await server._run_err(fake.positions_get, symbol="XAUUSD")
        r2, _ = await server._run_err(fake.positions_get, symbol="XAUUSD")

        assert r1 is None and r2 is None
        assert len(state["init_calls"]) == 1, "second attempt inside the 5s back-off"
    finally:
        server._mt5_executor.shutdown(wait=True)


async def test_startup_failure_is_retried_until_the_terminal_is_ready():
    fake, state = _fake_terminal(terminal_up=False, attached=False)
    server = _load_bridge(fake)
    server._STARTUP_RETRY_SECONDS = 0.01
    server._REATTACH_MIN_INTERVAL = 0.0

    async with server.lifespan(server.app):
        assert server._terminal_generation == 0, "-6 at startup: terminal still logging in"
        state["terminal_up"] = True
        for _ in range(100):
            if server._terminal_generation:
                break
            await asyncio.sleep(0.01)
        assert server._terminal_generation == 1
        result, _ = await server._run_err(fake.positions_get, symbol="XAUUSD")
        assert result == ()


async def test_shutdown_does_not_trigger_a_reattach():
    fake, state = _fake_terminal()
    server = _load_bridge(fake)
    try:
        state["err"] = (-10004, "No IPC connection")  # stale error before shutdown()
        original = fake.shutdown

        def shutdown():
            original()
            return None  # the real MT5 shutdown() returns None

        fake.shutdown = shutdown
        await server._run_err(fake.shutdown)

        assert state["init_calls"] == []
    finally:
        server._mt5_executor.shutdown(wait=True)
