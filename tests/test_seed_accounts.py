"""Tests for the seed-at-boot idempotency + orphan detection (Phase 5, D-24/D-25/D-26).

Seed = INSERT ... ON CONFLICT DO NOTHING (no UPDATE → no audit row).
Orphan = DB row whose name is absent from accounts.json → kept alive, warned once.
"""
import pytest
import db

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_seed_idempotent_no_duplicate_rows(db_pool):
    for _ in range(3):
        await db.upsert_account_if_missing(
            name="repeat", server="S", login=1, password_env="",
            risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
            max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
        )
        await db.upsert_account_settings_if_missing(account_name="repeat")
    async with db_pool.acquire() as conn:
        n_accts = await conn.fetchval("SELECT COUNT(*) FROM accounts WHERE name='repeat'")
        n_settings = await conn.fetchval(
            "SELECT COUNT(*) FROM account_settings WHERE account_name='repeat'"
        )
        n_audit = await conn.fetchval(
            "SELECT COUNT(*) FROM settings_audit WHERE account_name='repeat'"
        )
    assert n_accts == 1 and n_settings == 1
    assert n_audit == 0, "Seed must not produce audit entries"


async def test_db_wins_over_json_default(db_pool):
    """After seed, editing DB settings must stick; re-running seed must not revert."""
    await db.upsert_account_if_missing(
        name="winner", server="S", login=1, password_env="",
        risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
        max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
    )
    await db.upsert_account_settings_if_missing(account_name="winner")
    await db.update_account_setting("winner", "risk_value", 4.2)
    # Re-run seed (idempotent — must NOT overwrite)
    await db.upsert_account_if_missing(
        name="winner", server="S", login=1, password_env="",
        risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
        max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
    )
    await db.upsert_account_settings_if_missing(account_name="winner")
    row = await db.get_account_settings("winner")
    assert float(row["risk_value"]) == 4.2, "D-24: DB must win over JSON seed"


async def test_orphan_reported_when_json_lacks_account(db_pool):
    await db.upsert_account_if_missing(
        name="orphan-x", server="S", login=1, password_env="",
        risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
        max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
    )
    orphans = await db.get_orphan_accounts(["some-different-name"])
    assert "orphan-x" in orphans


async def test_multi_account_seed_per_account_risk_mapping(db_pool):
    """REGRESSION GUARD: when accounts.json has >1 account with different
    risk_percent values, each account_settings row must carry the originating
    account's risk_value — no cross-contamination, no default fallback.
    Real-money safety: v1.1 risk config drift would mis-size lots.
    """
    await db.upsert_account_if_missing(
        name="acct-conservative", server="S", login=10, password_env="",
        risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
        max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
    )
    await db.upsert_account_settings_if_missing(
        account_name="acct-conservative", risk_value=1.0,
    )
    await db.upsert_account_if_missing(
        name="acct-aggressive", server="S", login=20, password_env="",
        risk_percent=2.5, max_lot_size=2.0, max_daily_loss_percent=5.0,
        max_open_trades=5, enabled=True, mt5_host="", mt5_port=0,
    )
    await db.upsert_account_settings_if_missing(
        account_name="acct-aggressive", risk_value=2.5,
    )
    cons = await db.get_account_settings("acct-conservative")
    agg = await db.get_account_settings("acct-aggressive")
    assert float(cons["risk_value"]) == 1.0
    assert float(agg["risk_value"]) == 2.5
    assert cons["account_name"] == "acct-conservative"
    assert agg["account_name"] == "acct-aggressive"
