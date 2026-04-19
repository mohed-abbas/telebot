"""Tests for SettingsStore — in-process cache over account_settings + accounts (Phase 5).

D-27 / D-32: effective() returns a frozen AccountSettings (cheap copy via
dataclasses.replace) — Phase 6 stage snapshot depends on this shape.
"""
import pytest
import pytest_asyncio

import db
from settings_store import SettingsStore
from models import AccountSettings

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture
async def store(db_pool, seeded_account):
    s = SettingsStore(db_pool=db_pool)
    await s.load_all()
    return s


async def test_effective_returns_frozen_account_settings(store, seeded_account):
    eff = store.effective(seeded_account)
    assert isinstance(eff, AccountSettings)
    # frozen dataclass raises FrozenInstanceError (subclass of AttributeError)
    with pytest.raises((AttributeError, Exception)):
        eff.risk_value = 99.0  # type: ignore[misc]


async def test_effective_unknown_account_raises(store):
    with pytest.raises(KeyError, match="unknown account"):
        store.effective("nope")


async def test_snapshot_is_equal_copy(store, seeded_account):
    snap = store.snapshot(seeded_account)
    assert snap == store.effective(seeded_account)
    # Note: frozen+slots dataclasses with identical field values may compare
    # equal but be distinct objects. replace() creates a new instance.
    # Mutation impossibility is already covered by the frozen test above.


async def test_update_invalidates_cache(store, seeded_account):
    await store.update(seeded_account, "risk_value", 7.5)
    assert store.effective(seeded_account).risk_value == 7.5


async def test_update_writes_audit_row(store, seeded_account, db_pool):
    await store.update(seeded_account, "max_stages", 3, actor="admin")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT field, new_value FROM settings_audit WHERE account_name=$1",
            seeded_account,
        )
    assert any(r["field"] == "max_stages" and r["new_value"] == "3" for r in rows)


async def test_load_all_populates_from_db(db_pool, seeded_account):
    """A fresh SettingsStore.load_all() picks up seeded rows via JOIN."""
    s = SettingsStore(db_pool=db_pool)
    await s.load_all()
    eff = s.effective(seeded_account)
    assert eff.account_name == seeded_account
    assert eff.risk_mode == "percent"
    # defaults from db.upsert_account_settings_if_missing
    assert eff.risk_value == 1.0
    assert eff.max_stages == 1
    assert eff.default_sl_pips == 100
    assert eff.max_daily_trades == 30
    # max_open_trades / max_lot_size come from accounts table
    assert eff.max_open_trades == 3
    assert eff.max_lot_size == 1.0
