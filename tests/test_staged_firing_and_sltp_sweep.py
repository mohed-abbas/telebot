"""Wave-2 W2-STATE cluster tests — staged firing claim (§4.2) + post-trade
SL/TP verification sweep (§1.3(b)).

These run WITHOUT a live Postgres/broker: the DB compare-and-set semantics are
exercised against a faithful in-memory fake pool (it enforces the exact WHERE
guards the real SQL carries), and the executor sweep is driven with mock
connectors/positions. Named distinctively so it never clashes with the
DB-backed test_staged_* suites.
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
from executor import Executor
from mt5_connector import OrderResult

pytestmark = pytest.mark.asyncio


# ── §4.2 fake pool — models staged_entries.status transitions with the exact
#    WHERE guards the real claim / filled SQL carries. ──────────────────────
class _FakeStagedPool:
    def __init__(self, rows: dict[int, str]):
        self.rows = dict(rows)  # id -> status

    async def fetchval(self, sql: str, *args):
        s = " ".join(sql.split())
        # claim_stage_for_firing: awaiting_zone -> firing compare-and-set
        if "SET status='firing'" in s and "status='awaiting_zone' RETURNING id" in s:
            (sid,) = args
            if self.rows.get(sid) == "awaiting_zone":
                self.rows[sid] = "firing"
                return sid
            return None
        raise AssertionError(f"unexpected fetchval SQL: {s}")

    async def execute(self, sql: str, *args):
        s = " ".join(sql.split())
        # update_stage_status('filled') — guarded transition
        if "filled_at=NOW()" in s:
            assert "status IN ('awaiting_zone','firing')" in s, (
                "the 'filled' transition MUST carry the status precondition"
            )
            status, _ticket, sid = args
            if self.rows.get(sid) in ("awaiting_zone", "firing"):
                self.rows[sid] = status
                return "UPDATE 1"
            return "UPDATE 0"
        # non-filled transitions (cancelled/failed/capped/...) — unconditional
        if "SET status=$1, cancelled_reason=$2" in s:
            status, _reason, sid = args
            self.rows[sid] = status
            return "UPDATE 1"
        raise AssertionError(f"unexpected execute SQL: {s}")


async def test_claim_stage_for_firing_is_exclusive(monkeypatch):
    """(i) The atomic claim wins exactly once; a second claim returns None."""
    pool = _FakeStagedPool({7: "awaiting_zone"})
    monkeypatch.setattr(db, "_pool", pool)

    first = await db.claim_stage_for_firing(7)
    second = await db.claim_stage_for_firing(7)

    assert first == 7, "first claim must win and return the row id"
    assert second is None, "second claim must lose (already firing)"
    assert pool.rows[7] == "firing"


async def test_claim_stage_for_firing_none_on_terminal(monkeypatch):
    """A terminal/cancelled row can never be claimed for firing."""
    pool = _FakeStagedPool({8: "cancelled_stage1_closed"})
    monkeypatch.setattr(db, "_pool", pool)
    assert await db.claim_stage_for_firing(8) is None
    assert pool.rows[8] == "cancelled_stage1_closed"


async def test_filled_transition_no_resurrect_cancelled(monkeypatch):
    """(ii) update_stage_status('filled') is a no-op on a 'cancelled' row."""
    pool = _FakeStagedPool({9: "cancelled_stage1_closed"})
    monkeypatch.setattr(db, "_pool", pool)

    await db.update_stage_status(9, "filled", mt5_ticket=123)
    assert pool.rows[9] == "cancelled_stage1_closed", (
        "a terminal row must NOT be resurrected to 'filled' by a late fill"
    )

    # Sanity: a row still in the firing lifecycle DOES flip.
    pool.rows[10] = "firing"
    await db.update_stage_status(10, "filled", mt5_ticket=5)
    assert pool.rows[10] == "filled"


# ── §1.3(b) sweep — mock connector / positions / db fetch. ──────────────────
class _FakePos:
    def __init__(self, *, ticket, comment, sl, tp, direction="buy", open_price=2000.0):
        self.ticket = ticket
        self.comment = comment
        self.sl = sl
        self.tp = tp
        self.direction = direction
        self.open_price = open_price


class _FakeConnector:
    def __init__(self, positions, *, modify_success=True):
        self._positions = positions
        self._modify_success = modify_success
        self.modify_calls: list[tuple] = []
        self.connected = True

    async def get_positions(self, symbol=None):
        return self._positions

    async def modify_position(self, ticket, sl=None, tp=None):
        self.modify_calls.append((ticket, sl, tp))
        return OrderResult(
            success=self._modify_success, ticket=ticket,
            error=None if self._modify_success else "broker reject",
        )


class _FakeTM:
    def __init__(self, connectors):
        self.connectors = connectors
        self.accounts = {}


class _FakeNotifier:
    def __init__(self):
        self.alerts: list[str] = []

    async def notify_alert(self, message: str) -> None:
        self.alerts.append(message)


def _make_executor(connector, notifier=None, jitter=0.8):
    return Executor(
        trade_manager=_FakeTM({"acct": connector}),
        global_config=SimpleNamespace(sl_tp_jitter_points=jitter),
        notifier=notifier,
    )


def _stage(**overrides):
    row = {
        "id": 1, "signal_id": 1, "stage_number": 1, "account_name": "acct",
        "symbol": "XAUUSD", "direction": "buy",
        "mt5_comment": "telebot-1-s1", "mt5_ticket": 555,
        "signal_sl": 1990.0, "signal_tp": 2020.0,
    }
    row.update(overrides)
    return row


async def test_sweep_remodifies_when_tp_deviates(monkeypatch):
    """(iii) Sweep re-issues modify when the live TP is unset/deviant."""
    pos = _FakePos(ticket=555, comment="telebot-1-s1", sl=1990.0, tp=0.0)
    conn = _FakeConnector([pos])
    ex = _make_executor(conn)

    async def fake_fetch():
        return [_stage()]

    monkeypatch.setattr(db, "get_filled_stages_for_sltp_verification", fake_fetch)
    await ex._run_stage_sltp_verification_sweep()

    assert len(conn.modify_calls) == 1
    ticket, sl_sent, tp_sent = conn.modify_calls[0]
    assert ticket == 555
    assert tp_sent == 2020.0
    assert sl_sent == 1990.0


async def test_sweep_noop_when_in_sync(monkeypatch):
    """(iii) Sweep is a no-op when live SL/TP already match (within jitter)."""
    # 0.3 / 0.2 offsets are inside the jitter tolerance (0.8 + 2*pip).
    pos = _FakePos(ticket=555, comment="telebot-1-s1", sl=1990.2, tp=2020.3)
    conn = _FakeConnector([pos])
    ex = _make_executor(conn)

    async def fake_fetch():
        return [_stage()]

    monkeypatch.setattr(db, "get_filled_stages_for_sltp_verification", fake_fetch)
    await ex._run_stage_sltp_verification_sweep()

    assert conn.modify_calls == []


async def test_sweep_skips_closed_position(monkeypatch):
    """Never re-modify a position the operator/broker already closed."""
    conn = _FakeConnector([])  # no live position with our comment
    ex = _make_executor(conn)

    async def fake_fetch():
        return [_stage()]

    monkeypatch.setattr(db, "get_filled_stages_for_sltp_verification", fake_fetch)
    await ex._run_stage_sltp_verification_sweep()

    assert conn.modify_calls == []


async def test_sweep_bounded_retries_then_notifies_once(monkeypatch):
    """After N failed modifies the sweep escalates once and stops hammering."""
    pos = _FakePos(ticket=555, comment="telebot-1-s1", sl=1990.0, tp=0.0)
    conn = _FakeConnector([pos], modify_success=False)
    notifier = _FakeNotifier()
    ex = _make_executor(conn, notifier=notifier)

    async def fake_fetch():
        return [_stage()]

    monkeypatch.setattr(db, "get_filled_stages_for_sltp_verification", fake_fetch)

    # Tick well past the bound; modify keeps failing.
    for _ in range(ex._SLTP_VERIFY_MAX_ATTEMPTS + 3):
        await ex._run_stage_sltp_verification_sweep()

    assert len(conn.modify_calls) == ex._SLTP_VERIFY_MAX_ATTEMPTS, (
        "must stop re-modifying after the attempt bound"
    )
    assert len(notifier.alerts) == 1, "operator must be alerted exactly once"
    assert "UNVERIFIED" in notifier.alerts[0]
