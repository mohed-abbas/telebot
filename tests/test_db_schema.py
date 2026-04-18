"""Schema tests for Phase 5 additive tables: accounts, account_settings, settings_audit, failed_login_attempts.

Verifies SET-02 columns exist and CHECK constraints reject out-of-range values.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_accounts_table_columns(db_pool):
    async with db_pool.acquire() as conn:
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='accounts' ORDER BY ordinal_position"
        )
    names = [c["column_name"] for c in cols]
    assert "name" in names and "login" in names and "enabled" in names


async def test_account_settings_columns(db_pool):
    async with db_pool.acquire() as conn:
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='account_settings' ORDER BY ordinal_position"
        )
    names = [c["column_name"] for c in cols]
    for required in ("risk_mode", "risk_value", "max_stages",
                     "default_sl_pips", "max_daily_trades"):
        assert required in names, f"SET-02 missing column: {required}"


async def test_account_settings_check_constraints(db_pool, seeded_account):
    """CHECK constraints reject out-of-range values."""
    with pytest.raises(Exception):  # asyncpg.CheckViolationError
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE account_settings SET risk_mode='wild' WHERE account_name=$1",
                seeded_account,
            )


async def test_settings_audit_table_exists(db_pool):
    async with db_pool.acquire() as conn:
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='settings_audit' ORDER BY ordinal_position"
        )
    names = [c["column_name"] for c in cols]
    for required in ("timestamp", "account_name", "field", "old_value", "new_value", "actor"):
        assert required in names, f"settings_audit missing column: {required}"


async def test_failed_login_attempts_table_exists(db_pool):
    async with db_pool.acquire() as conn:
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='failed_login_attempts' ORDER BY ordinal_position"
        )
    names = [c["column_name"] for c in cols]
    for required in ("ip_addr", "attempted_at", "user_agent"):
        assert required in names, f"failed_login_attempts missing column: {required}"
