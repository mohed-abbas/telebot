"""Review 2026-10-16 — batch 4 (minor items) regression tests.

One test per item in docs/audit/review-2026-10-16-fix-plan.md "Batch 4":

  connector errors are per call, not per connector
  "10025" no-change check matches the retcode, not ticket digits
  SL/TP sweep candidates exclude closed trades and are capped
  idempotency results are stored once (jsonb object, not a JSON string)
  SPA logout expires the session + CSRF cookies
  SESSION_ABSOLUTE_MAX_AGE garbage falls back to the default
  drilldown: lots are the trade's lots; a market stage 1 has no band
  sweep / orphan modifies count against server_messages
  one MT5Connector.has_credentials(); one pip_size_for_symbol()
  cascade cancels share one SQL (account-scoped and signal-wide)
  backlog: limit-order trades leave 'pending'; CLOSE goes through 'closing'
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

import db
from executor import Executor
from models import AccountConfig, Direction, SignalAction, SignalType
from mt5_connector import DryRunConnector, MT5Connector, OrderResult, OrderType, Position, RestApiConnector
from risk_calculator import GOLD_PIP_SIZE, pip_size_for_symbol
from trade_manager import TradeManager, _pip_size_for_symbol, is_no_change_result

pytestmark = pytest.mark.asyncio(loop_scope="session")

ACCT = "test-acct"


@pytest_asyncio.fixture
async def executor(tm_with_store, global_config):
    return Executor(trade_manager=tm_with_store, global_config=global_config, notifier=None)


async def _insert_stage(*, signal_id: int, stage_number: int, status="filled",
                        mt5_ticket=None, band=(2040.0, 2042.5), target_lot=0.1,
                        signal_sl=2030.0, signal_tp=2080.0, filled=True) -> int:
    snapshot = {"account_name": ACCT, "risk_mode": "percent", "risk_value": 1.0, "max_stages": 5,
                "default_sl_pips": 100, "max_daily_trades": 30, "max_open_trades": 5,
                "max_lot_size": 1.0}
    async with db._pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO staged_entries
               (signal_id, stage_number, account_name, symbol, direction, zone_low, zone_high,
                band_low, band_high, target_lot, snapshot_settings, mt5_comment, mt5_ticket,
                status, signal_sl, signal_tp, filled_at)
               VALUES ($1,$2,$3,'XAUUSD','buy',$4,$5,$4,$5,$6,$7::jsonb,$8,$9,$10,$11,$12,
                       CASE WHEN $13 THEN NOW() ELSE NULL END)
               RETURNING id""",
            signal_id, stage_number, ACCT, band[0], band[1], target_lot, json.dumps(snapshot),
            f"telebot-{signal_id}-s{stage_number}", mt5_ticket, status, signal_sl, signal_tp,
            filled,
        )


async def _trade(ticket: int, status: str = "opened", lot_size: float = 0.37) -> int:
    return await db.log_trade(
        signal_id=None, account_name=ACCT, symbol="XAUUSD", direction="buy",
        entry_price=2040.0, sl=2030.0, tp=2080.0, lot_size=lot_size, ticket=ticket,
        status=status, raw_signal="t",
    )


async def _trade_row(ticket: int) -> dict:
    async with db._pool.acquire() as conn:
        return dict(await conn.fetchrow("SELECT * FROM trades WHERE ticket=$1", ticket))


# ── connector: errors belong to the call ──────────────────────────────────


def _rest(handler) -> RestApiConnector:
    conn = RestApiConnector(account_name=ACCT, server="S", login=1, password="p",
                            host="localhost", port=8001, api_key="k", use_tls=False)
    conn._http = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                   base_url=conn._base_url, timeout=15.0)
    return conn


async def test_concurrent_calls_do_not_swap_each_others_errors():
    """Two coroutines on ONE connector: the rejected order must carry ITS broker
    reason; the modify that succeeded must not inherit it (and vice versa)."""
    gate = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            # Fail first, then let the PUT run while this result is "in flight".
            resp = httpx.Response(400, json={"ok": False, "data": None,
                                             "error": {"code": "10016", "message": "invalid stops"}})
            gate.set()
            return resp
        await gate.wait()
        return httpx.Response(200, json={"ok": True, "data": {"success": True}, "error": None})

    conn = _rest(handler)
    opened, modified = await asyncio.gather(
        conn.open_order("XAUUSD", OrderType.MARKET_BUY, 0.1, sl=2030.0),
        conn.modify_position(5, sl=2031.0),
    )
    assert opened.success is False and "10016" in opened.error
    assert modified.success is True and modified.error == ""


# ── 10025 whole-number match ──────────────────────────────────────────────


async def test_no_change_check_does_not_match_ticket_digits():
    assert is_no_change_result(OrderResult(success=False, error="retcode=10025 No changes")) is True
    assert is_no_change_result(OrderResult(success=False, error="broker error 10025: no changes")) is True
    assert is_no_change_result(OrderResult(success=False, error="position 41002537 not found")) is False
    assert is_no_change_result(OrderResult(success=False, error="retcode=100250")) is False


# ── one pip-size helper, one credentials check ────────────────────────────


async def test_single_pip_size_helper():
    assert pip_size_for_symbol("XAUUSD") == GOLD_PIP_SIZE
    assert pip_size_for_symbol("xauusd") == GOLD_PIP_SIZE
    assert pip_size_for_symbol("EURUSD") == 0.0001
    assert _pip_size_for_symbol("XAUUSD") == pip_size_for_symbol("XAUUSD")


async def test_has_credentials(monkeypatch):
    monkeypatch.delenv("TB_TEST_PW", raising=False)
    inline = MT5Connector("a", "s", 1, "secret")
    none = MT5Connector("a", "s", 1, "", password_env="TB_TEST_PW")
    assert inline.has_credentials() is True
    assert none.has_credentials() is False
    monkeypatch.setenv("TB_TEST_PW", "x")
    assert none.has_credentials() is True


# ── sweep candidates are bounded ──────────────────────────────────────────


async def test_sweep_candidates_skip_closed_trades(db_pool, seeded_account, seeded_signal):
    sid = seeded_signal
    await _trade(7001, status="closed")
    await _trade(7002, status="opened")
    closed_stage = await _insert_stage(signal_id=sid, stage_number=1, mt5_ticket=7001)
    live_stage = await _insert_stage(signal_id=sid, stage_number=2, mt5_ticket=7002)

    ids = {r["id"] for r in await db.get_filled_stages_for_sltp_verification()}
    assert live_stage in ids
    assert closed_stage not in ids, "a closed trade has no live position to verify"


async def test_sweep_candidates_are_capped(db_pool, seeded_account, seeded_signal, monkeypatch):
    monkeypatch.setattr(db, "SLTP_SWEEP_MAX_ROWS", 2)
    for n in range(1, 5):
        await _insert_stage(signal_id=seeded_signal, stage_number=n, mt5_ticket=7100 + n)
    rows = await db.get_filled_stages_for_sltp_verification()
    assert len(rows) == 2


# ── idempotency: stored once ──────────────────────────────────────────────


async def test_idempotency_result_is_a_jsonb_object(db_pool):
    from api import idempotency

    state, _ = await idempotency.check("req-b4-1", ACCT, 1, 0.1)
    assert state == "new"
    await idempotency.store("req-b4-1", ACCT, 1, 0.1, {"ok": True, "closed_volume": 0.1})

    async with db._pool.acquire() as conn:
        kind = await conn.fetchval(
            "SELECT jsonb_typeof(result) FROM idempotency_keys WHERE request_id=$1", "req-b4-1",
        )
    assert kind == "object", "was 'string' (JSON encoded twice)"
    state, cached = await idempotency.check("req-b4-1", ACCT, 1, 0.1)
    assert state == "replay" and cached == {"ok": True, "closed_volume": 0.1}


async def test_idempotency_still_reads_legacy_double_encoded_rows(db_pool):
    from api import idempotency

    async with db._pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO idempotency_keys (request_id, account, ticket, close_volume, result)
               VALUES ($1, $2, $3, $4, to_jsonb($5::text))""",
            "req-b4-legacy", ACCT, 2, 0.2, json.dumps({"ok": True}),
        )
    state, cached = await idempotency.check("req-b4-legacy", ACCT, 2, 0.2)
    assert state == "replay" and cached == {"ok": True}


# ── SPA logout expires the cookies ────────────────────────────────────────


async def test_api_logout_expires_session_and_csrf_cookies(session_client):
    client, csrf = session_client
    r = await client.post("/api/v2/auth/logout", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    set_cookies = [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie"]
    expired = {c.split("=", 1)[0] for c in set_cookies if "Max-Age=0" in c or "max-age=0" in c.lower()}
    assert {"telebot_session", "telebot_csrf"} <= expired, set_cookies


# ── SESSION_ABSOLUTE_MAX_AGE parsing ──────────────────────────────────────


async def test_env_int_falls_back_on_garbage(monkeypatch, api_app):
    import dashboard

    monkeypatch.setenv("TB_B4_INT", "seven days")
    assert dashboard._env_int("TB_B4_INT", 42) == 42
    monkeypatch.setenv("TB_B4_INT", "0")
    assert dashboard._env_int("TB_B4_INT", 42) == 42
    monkeypatch.setenv("TB_B4_INT", " 3600 ")
    assert dashboard._env_int("TB_B4_INT", 42) == 3600
    monkeypatch.delenv("TB_B4_INT")
    assert dashboard._env_int("TB_B4_INT", 42) == 42


# ── drilldown lots + band ─────────────────────────────────────────────────


async def test_drilldown_uses_trade_lots_and_market_for_stage1(db_pool, seeded_account, seeded_signal):
    sid = seeded_signal
    await _trade(7201, lot_size=0.37)
    # percent mode: target_lot holds 1.0 % / 5 stages = 0.2 "percent", not lots.
    await _insert_stage(signal_id=sid, stage_number=1, mt5_ticket=7201, band=(0.0, 0.0), target_lot=0.2)

    detail = await db.get_position_drilldown(7201, ACCT)
    fill = detail["fill_history"][0]
    assert fill["lot_size"] == pytest.approx(0.37), "lots actually sent, not the risk slice"
    assert fill["band_low"] is None and fill["band_high"] is None, "market stage 1 has no band"

    from api import positions as positions_route
    detail = await positions_route.position_drilldown(ACCT, 7201, _user="tester")
    fill = detail["fill_history"][0]
    assert fill["lot_size_display"] == "0.37"
    assert "band_low_display" not in fill  # -> the SPA renders "Market"


# ── sweep modifies count against the daily message budget ─────────────────


async def test_sweep_modify_counts_a_server_message(db_pool, seeded_signal, priced_connector, executor):
    sid = seeded_signal
    await _trade(7301)
    await _insert_stage(signal_id=sid, stage_number=1, mt5_ticket=7301)
    priced_connector._fake_positions[7301] = Position(
        ticket=7301, symbol="XAUUSD", direction="buy", volume=0.1, open_price=2040.0,
        sl=0.0, tp=0.0, profit=0.0, comment=f"telebot-{sid}-s1",
    )
    before = await db.get_daily_stat(ACCT, "server_messages")
    await executor._run_stage_sltp_verification_sweep()
    assert priced_connector._fake_positions[7301].sl == 2030.0
    assert await db.get_daily_stat(ACCT, "server_messages") == before + 1


# ── cascade cancels share one SQL ─────────────────────────────────────────


async def test_cascade_cancels_scope_by_account_or_signal(db_pool, seeded_account, seeded_signal):
    sid = seeded_signal
    await db.upsert_account_if_missing(
        name="other-acct", server="Test", login=2, password_env="", risk_percent=1.0,
        max_lot_size=1.0, max_daily_loss_percent=3.0, max_open_trades=3, enabled=True,
        mt5_host="", mt5_port=0,
    )
    mine = await _insert_stage(signal_id=sid, stage_number=2, status="awaiting_zone", filled=False)
    async with db._pool.acquire() as conn:
        theirs = await conn.fetchval(
            """INSERT INTO staged_entries
               (signal_id, stage_number, account_name, symbol, direction, zone_low, zone_high,
                band_low, band_high, target_lot, snapshot_settings, mt5_comment, status)
               VALUES ($1, 3, 'other-acct', 'XAUUSD', 'buy', 1, 2, 1, 2, 0.1, '{}'::jsonb,
                       $2, 'awaiting_zone') RETURNING id""",
            sid, f"telebot-{sid}-s3",
        )

    assert await db.cancel_unfilled_stages_for_signal(sid, reason="stage1_closed", account_name=ACCT) == 1
    async with db._pool.acquire() as conn:
        statuses = dict(await conn.fetch(
            "SELECT id, status FROM staged_entries WHERE id = ANY($1::int[])", [mine, theirs],
        ))
    assert statuses[mine] == "cancelled_stage1_closed"
    assert statuses[theirs] == "awaiting_zone", "another account's band is untouched"

    assert await db.cancel_unfilled_stages_target_reached(sid, reason="tp_reached") == 1
    async with db._pool.acquire() as conn:
        assert await conn.fetchval("SELECT status FROM staged_entries WHERE id=$1", theirs) \
            == "cancelled_target_reached"


# ── backlog: limit-order trades and CLOSE P&L ─────────────────────────────


async def test_limit_order_trade_leaves_pending_on_fill_and_cancel(db_pool, seeded_account):
    expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    await _trade(7401, status="pending")
    await _trade(7402, status="pending")
    await db.log_pending_order(None, ACCT, 7401, "XAUUSD", "buy_limit", 0.1, 2035.0, 2025.0, 2060.0, expires)
    cancelled_id = await db.log_pending_order(
        None, ACCT, 7402, "XAUUSD", "buy_limit", 0.1, 2035.0, 2025.0, 2060.0, expires,
    )

    await db.mark_pending_filled(7401, ACCT)
    await db.mark_pending_cancelled(cancelled_id)

    assert (await _trade_row(7401))["status"] == "opened"
    assert (await _trade_row(7402))["status"] == "cancelled"
    assert 7401 in await db.get_open_trade_tickets_for_account(ACCT), "now reconciled by history sync"


class _HistoryCapableDry(DryRunConnector):
    """A dry-run connector pretending to be a real bridge with deal history."""
    supports_history_sync = True


async def test_close_signal_parks_trade_in_closing_on_a_real_bridge(db_pool, seeded_account, global_config):
    conn = _HistoryCapableDry(ACCT, "S", 1, "p")
    await conn.connect()
    conn.set_simulated_price("XAUUSD", 2045.0, 2045.2)
    conn._fake_positions[7501] = Position(
        ticket=7501, symbol="XAUUSD", direction="buy", volume=0.1, open_price=2040.0,
        sl=2030.0, tp=2080.0, profit=0.0, comment="telebot-9-s1",
    )
    await _trade(7501)
    acct = AccountConfig(name=ACCT, server="S", login=1, password_env="", risk_percent=1.0,
                         max_lot_size=1.0, max_daily_loss_percent=3.0, max_open_trades=5, enabled=True)
    tm = TradeManager(connectors={ACCT: conn}, accounts=[acct], global_config=global_config)

    results = await tm.handle_signal(SignalAction(type=SignalType.CLOSE, symbol="XAUUSD", raw_text="close"))
    assert [r["status"] for r in results] == ["closed"]

    row = await _trade_row(7501)
    assert row["status"] == "closing", "floating P&L is an estimate; the deal decides"
    assert float(row["pnl"]) == pytest.approx((2045.0 - 2040.0) * 0.1 * 100)  # estimate kept


async def test_close_signal_finalizes_on_dry_run(db_pool, seeded_account, tm_with_store, priced_connector):
    priced_connector._fake_positions[7601] = Position(
        ticket=7601, symbol="XAUUSD", direction="buy", volume=0.1, open_price=2040.0,
        sl=2030.0, tp=2080.0, profit=0.0, comment="telebot-9-s1",
    )
    await _trade(7601)
    await tm_with_store.handle_signal(SignalAction(type=SignalType.CLOSE, symbol="XAUUSD", raw_text="close"))
    assert (await _trade_row(7601))["status"] == "closed"
