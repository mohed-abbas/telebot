"""W3-IDENTITY (§1.4) — multi-account correlation + query-scoping regressions.

These fail BEFORE the cluster fix and pass AFTER it:

  1. SignalCorrelator is account-scoped: under interleaved registration from two
     accounts on the same (symbol, direction), each account's follow-up pairs to
     its OWN orphan signal_id (never the sibling account's).
  2. db.get_orphan_candidate_stage1s scopes its sibling NOT EXISTS by account, so
     one account's stage-2 row does not mask another account's genuine orphan
     stage-1 (defense-in-depth for a shared signal_id).
  3. Comment identity: two accounts handling one Telegram message get DISTINCT
     per-account signal_ids (the design choice that keeps mt5_comment unique
     without a schema change), and the UNIQUE(mt5_comment) constraint still bites
     on a genuine duplicate.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

import db
from signal_correlator import SignalCorrelator

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ── (1) account-scoped correlator ────────────────────────────────────

async def test_correlator_pairs_each_account_to_its_own_orphan():
    """Interleaved multi-account registration must not cross-pair (§1.4)."""
    corr = SignalCorrelator(window_seconds=600)

    # Two accounts register orphans on the SAME (symbol, direction), interleaved.
    await corr.register_orphan(100, "XAUUSD", "buy", account_name="acct-A")
    await corr.register_orphan(200, "XAUUSD", "buy", account_name="acct-B")

    # Each follow-up must pair to its own account's orphan — NOT the most-recent
    # global orphan (which the old single-bucket LIFO would have returned: 200).
    assert await corr.pair_followup("XAUUSD", "buy", account_name="acct-A") == 100
    assert await corr.pair_followup("XAUUSD", "buy", account_name="acct-B") == 200


async def test_correlator_account_isolation_one_to_one():
    """One account pairing its orphan must not consume the other account's."""
    corr = SignalCorrelator(window_seconds=600)
    await corr.register_orphan(11, "XAUUSD", "sell", account_name="acct-A")
    await corr.register_orphan(22, "XAUUSD", "sell", account_name="acct-B")

    # acct-A pairs (and evicts) ONLY its own orphan.
    assert await corr.pair_followup("XAUUSD", "sell", account_name="acct-A") == 11
    assert await corr.pair_followup("XAUUSD", "sell", account_name="acct-A") is None
    # acct-B's orphan is untouched.
    assert await corr.pair_followup("XAUUSD", "sell", account_name="acct-B") == 22


# ── DB helpers ───────────────────────────────────────────────────────

async def _seed_second_account(name: str) -> str:
    await db.upsert_account_if_missing(
        name=name, server="Test", login=88888, password_env="",
        risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
        max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
    )
    await db.upsert_account_settings_if_missing(account_name=name)
    return name


async def _insert_signal() -> int:
    async with db._pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO signals (raw_text, signal_type, symbol, direction, action_taken)
               VALUES ($1,$2,$3,$4,$5) RETURNING id""",
            "w3 signal", "open_text_only", "XAUUSD", "buy", "staged",
        )


def _stage_row(signal_id, account, *, stage_number, comment, status="awaiting_zone"):
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
        "status": status,
    }


# ── (2) account-scoped sibling NOT EXISTS ────────────────────────────

async def test_orphan_candidates_not_masked_by_other_accounts_sibling(
    db_pool, seeded_account, seeded_signal,
):
    """Account A's orphan stage-1 must be returned even though account B has a
    stage-2 sibling under the SAME signal_id (§1.4 defense-in-depth).

    Before the fix the sibling NOT EXISTS matched on signal_id only, so B's
    stage-2 excluded A's genuine orphan from the protective-TP watchdog.
    """
    acct_a = seeded_account
    acct_b = await _seed_second_account("test-acct-b")
    sid = seeded_signal  # shared signal_id across accounts (worst case)

    # Account A: a lone stage-1 (true orphan — no siblings on A).
    [a_s1] = await db.create_staged_entries(
        [_stage_row(sid, acct_a, stage_number=1, comment=f"telebot-{sid}-A-s1")]
    )
    # Account B: stage-1 AND a stage-2 sibling (B has a genuine follow-up).
    [b_s1, b_s2] = await db.create_staged_entries([
        _stage_row(sid, acct_b, stage_number=1, comment=f"telebot-{sid}-B-s1"),
        _stage_row(sid, acct_b, stage_number=2, comment=f"telebot-{sid}-B-s2"),
    ])

    # Both stage-1 rows are filled with live tickets.
    await db.update_stage_status(a_s1, "filled", mt5_ticket=5001)
    await db.update_stage_status(b_s1, "filled", mt5_ticket=5002)

    # Negative window → created_at < NOW()+5s is always true (window expired).
    candidates = await db.get_orphan_candidate_stage1s(-5)
    cand_ids = {c["id"] for c in candidates}

    # A's stage-1 IS an orphan candidate; B's stage-1 is NOT (it has a sibling).
    assert a_s1 in cand_ids
    assert b_s1 not in cand_ids


async def test_orphan_candidate_excluded_by_own_sibling(
    db_pool, seeded_account, seeded_signal,
):
    """A stage-1 with its OWN account's stage-2 sibling is still excluded."""
    acct_a = seeded_account
    sid = seeded_signal
    [a_s1, a_s2] = await db.create_staged_entries([
        _stage_row(sid, acct_a, stage_number=1, comment=f"telebot-{sid}-s1"),
        _stage_row(sid, acct_a, stage_number=2, comment=f"telebot-{sid}-s2"),
    ])
    await db.update_stage_status(a_s1, "filled", mt5_ticket=6001)

    candidates = await db.get_orphan_candidate_stage1s(-5)
    assert a_s1 not in {c["id"] for c in candidates}


# ── (3) comment identity across accounts ─────────────────────────────

async def test_distinct_signal_ids_keep_comments_unique_across_accounts(
    db_pool, seeded_account,
):
    """One Telegram message → per-account signal_ids → naturally-unique comments.

    The cluster keeps signal_ids per-account (each account's temp TradeManager
    logs its own signals row), so both accounts' stage-1 comments differ and the
    UNIQUE(mt5_comment) constraint never fires for a legitimate multi-account
    open. A genuine duplicate comment still raises.
    """
    acct_a = seeded_account
    acct_b = await _seed_second_account("test-acct-b")

    sid_a = await _insert_signal()  # account A's own signal row
    sid_b = await _insert_signal()  # account B's own signal row
    assert sid_a != sid_b

    # Distinct per-account signal_ids → distinct s1 comments → both insert.
    [a_s1] = await db.create_staged_entries(
        [_stage_row(sid_a, acct_a, stage_number=1, comment=f"telebot-{sid_a}-s1")]
    )
    [b_s1] = await db.create_staged_entries(
        [_stage_row(sid_b, acct_b, stage_number=1, comment=f"telebot-{sid_b}-s1")]
    )
    assert a_s1 > 0 and b_s1 > 0 and a_s1 != b_s1

    # UNIQUE(mt5_comment) still enforced on a real collision.
    with pytest.raises(Exception):
        await db.create_staged_entries(
            [_stage_row(sid_b, acct_b, stage_number=1, comment=f"telebot-{sid_a}-s1")]
        )
