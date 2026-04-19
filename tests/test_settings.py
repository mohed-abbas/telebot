"""Tests for account_settings / settings_audit write helpers + field whitelist + failed_login helpers."""
import pytest
import db

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_audit_per_field_write(db_pool, seeded_account):
    await db.update_account_setting(seeded_account, "risk_value", 2.5)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT field, old_value, new_value, actor FROM settings_audit "
            "WHERE account_name=$1 ORDER BY id",
            seeded_account,
        )
    assert len(rows) == 1
    assert rows[0]["field"] == "risk_value"
    assert rows[0]["new_value"] == "2.5"
    assert rows[0]["actor"] == "admin"


async def test_field_whitelist_blocks_injection(db_pool, seeded_account):
    with pytest.raises(ValueError, match="Invalid account_settings field"):
        await db.update_account_setting(
            seeded_account, "risk_value; DROP TABLE accounts;--", 1.0
        )


async def test_settings_audit_captures_old_value(db_pool, seeded_account):
    await db.update_account_setting(seeded_account, "max_stages", 2)
    await db.update_account_setting(seeded_account, "max_stages", 5)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT old_value, new_value FROM settings_audit "
            "WHERE account_name=$1 AND field='max_stages' ORDER BY id",
            seeded_account,
        )
    assert rows[0]["old_value"] == "1" and rows[0]["new_value"] == "2"
    assert rows[1]["old_value"] == "2" and rows[1]["new_value"] == "5"


async def test_get_orphan_accounts(db_pool, seeded_account):
    orphans = await db.get_orphan_accounts(["some-other-name"])
    assert seeded_account in orphans


async def test_failed_login_helpers(db_pool):
    await db.log_failed_login("10.0.0.1")
    await db.log_failed_login("10.0.0.1")
    assert await db.get_failed_login_count("10.0.0.1", minutes=15) == 2
    await db.clear_failed_logins("10.0.0.1")
    assert await db.get_failed_login_count("10.0.0.1", minutes=15) == 0
