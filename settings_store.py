"""In-process cache over account_settings + accounts. DB is source of truth.

Design per D-27 / D-32 (Phase 5 CONTEXT):
  - effective(name) returns a frozen AccountSettings dataclass — cheap copy
    via dataclasses.replace for Phase 6's staged-entry snapshot (SET-05).
  - Cache invalidation: simple reload-on-write (Claude's Discretion).
  - No DB I/O in .effective() — hot path stays in-process.
"""
from __future__ import annotations

import logging
from dataclasses import replace

import asyncpg

import db
from models import AccountSettings

logger = logging.getLogger(__name__)


class SettingsStore:
    def __init__(self, db_pool: asyncpg.Pool):
        self._pool = db_pool
        self._cache: dict[str, AccountSettings] = {}

    async def load_all(self) -> None:
        """Warm the cache from a single JOIN query."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT s.account_name, s.risk_mode,
                          s.risk_value::float AS risk_value,
                          s.max_stages, s.default_sl_pips, s.max_daily_trades,
                          a.max_open_trades, a.max_lot_size
                     FROM account_settings s
                     JOIN accounts a ON a.name = s.account_name"""
            )
        self._cache = {
            r["account_name"]: AccountSettings(
                account_name=r["account_name"],
                risk_mode=r["risk_mode"],
                risk_value=float(r["risk_value"]),
                max_stages=r["max_stages"],
                default_sl_pips=r["default_sl_pips"],
                max_daily_trades=r["max_daily_trades"],
                max_open_trades=r["max_open_trades"],
                max_lot_size=float(r["max_lot_size"]),
            )
            for r in rows
        }
        logger.info("SettingsStore loaded %d account(s)", len(self._cache))

    async def reload(self, account_name: str) -> None:
        """Refresh a single account's cache entry from DB (or evict if missing)."""
        row = await db.get_account_settings(account_name)
        if row is None:
            self._cache.pop(account_name, None)
            return
        self._cache[account_name] = AccountSettings(
            account_name=account_name,
            risk_mode=row["risk_mode"],
            risk_value=float(row["risk_value"]),
            max_stages=row["max_stages"],
            default_sl_pips=row["default_sl_pips"],
            max_daily_trades=row["max_daily_trades"],
            max_open_trades=row["max_open_trades"],
            max_lot_size=float(row["max_lot_size"]),
        )

    def effective(self, account_name: str) -> AccountSettings:
        """Return the cached effective settings; raise if unknown."""
        try:
            return self._cache[account_name]
        except KeyError as exc:
            raise KeyError(
                f"SettingsStore: unknown account {account_name!r}. "
                f"Known: {sorted(self._cache)}"
            ) from exc

    def snapshot(self, account_name: str) -> AccountSettings:
        """Return a cheap copy for Phase 6 stage persistence (SET-05 prep).

        frozen + slots = immutable; dataclasses.replace() with no args is a copy.
        """
        return replace(self.effective(account_name))

    async def update(
        self, account_name: str, field: str, value, actor: str = "admin"
    ) -> None:
        """Write-through: DB update (with audit) then refresh local cache."""
        await db.update_account_setting(account_name, field, value, actor=actor)
        await self.reload(account_name)
