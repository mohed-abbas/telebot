"""PostgreSQL database for trade logging, signal tracking, and daily stats.

Uses asyncpg connection pool for async operations.
"""

from __future__ import annotations

import logging
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Optional, Union

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None

# ── Field whitelist for dynamic SQL (SEC-01) ─────────────────────────

_DAILY_STAT_FIELDS: frozenset[str] = frozenset({
    "trades_count",
    "server_messages",
    "daily_pnl",
    "starting_balance",
})


def _validate_field(field: str) -> str:
    """Validate a field name against the whitelist. Raises ValueError if invalid."""
    if field not in _DAILY_STAT_FIELDS:
        raise ValueError(f"Invalid daily_stat field: {field!r}")
    return field


_ACCOUNT_SETTINGS_FIELDS: frozenset[str] = frozenset({
    "risk_mode", "risk_value", "max_stages", "default_sl_pips", "max_daily_trades",
})


def _validate_account_settings_field(field: str) -> str:
    """Validate a field name against the account_settings whitelist. Raises ValueError if invalid."""
    if field not in _ACCOUNT_SETTINGS_FIELDS:
        raise ValueError(f"Invalid account_settings field: {field!r}")
    return field


def _utc_today() -> date:
    """Get today's date in UTC (not local timezone)."""
    return datetime.now(timezone.utc).date()


# ── Lifecycle ────────────────────────────────────────────────────────


async def init_db(database_url: str) -> None:
    """Initialize the connection pool and create tables."""
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=2,
        max_size=5,
        command_timeout=30,
    )
    await _create_tables()
    logger.info("Database initialized (PostgreSQL pool: min=2, max=5)")


async def close_db() -> None:
    """Close the connection pool (call on shutdown)."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def _create_tables() -> None:
    """Create tables if they don't exist. Each DDL is a separate execute."""
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                raw_text TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                symbol TEXT,
                direction TEXT,
                entry_zone_low DOUBLE PRECISION,
                entry_zone_high DOUBLE PRECISION,
                sl DOUBLE PRECISION,
                tp DOUBLE PRECISION,
                action_taken TEXT NOT NULL,
                details TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                signal_id INTEGER REFERENCES signals(id),
                timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                account_name TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price DOUBLE PRECISION,
                sl DOUBLE PRECISION,
                tp DOUBLE PRECISION,
                lot_size DOUBLE PRECISION,
                ticket BIGINT,
                status TEXT NOT NULL,
                pnl DOUBLE PRECISION DEFAULT 0.0,
                close_price DOUBLE PRECISION,
                close_time TIMESTAMPTZ,
                raw_signal TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL,
                account_name TEXT NOT NULL,
                trades_count INTEGER DEFAULT 0,
                server_messages INTEGER DEFAULT 0,
                daily_pnl DOUBLE PRECISION DEFAULT 0.0,
                starting_balance DOUBLE PRECISION DEFAULT 0.0,
                UNIQUE(date, account_name)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_orders (
                id SERIAL PRIMARY KEY,
                signal_id INTEGER REFERENCES signals(id),
                account_name TEXT NOT NULL,
                ticket BIGINT NOT NULL,
                symbol TEXT NOT NULL,
                order_type TEXT NOT NULL,
                volume DOUBLE PRECISION,
                price DOUBLE PRECISION,
                sl DOUBLE PRECISION,
                tp DOUBLE PRECISION,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMPTZ NOT NULL,
                status TEXT DEFAULT 'active'
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_orders_status
            ON pending_orders(status)
        """)
        # ── accounts (D-23) ──
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                name                    TEXT        PRIMARY KEY,
                server                  TEXT        NOT NULL,
                login                   BIGINT      NOT NULL,
                password_env            TEXT        NOT NULL DEFAULT '',
                risk_percent            DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                max_lot_size            DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                max_daily_loss_percent  DOUBLE PRECISION NOT NULL DEFAULT 3.0,
                max_open_trades         INTEGER     NOT NULL DEFAULT 3,
                enabled                 BOOLEAN     NOT NULL DEFAULT TRUE,
                mt5_host                TEXT        NOT NULL DEFAULT '',
                mt5_port                INTEGER     NOT NULL DEFAULT 0,
                created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS account_settings (
                account_name        TEXT        PRIMARY KEY REFERENCES accounts(name) ON DELETE CASCADE,
                risk_mode           TEXT        NOT NULL DEFAULT 'percent'
                                                CHECK (risk_mode IN ('percent', 'fixed_lot')),
                risk_value          NUMERIC(10,4) NOT NULL DEFAULT 1.0
                                                CHECK (risk_value > 0 AND risk_value <= 100),
                max_stages          INTEGER     NOT NULL DEFAULT 1
                                                CHECK (max_stages >= 1 AND max_stages <= 10),
                default_sl_pips     INTEGER     NOT NULL DEFAULT 100
                                                CHECK (default_sl_pips > 0 AND default_sl_pips <= 10000),
                max_daily_trades    INTEGER     NOT NULL DEFAULT 30
                                                CHECK (max_daily_trades >= 1 AND max_daily_trades <= 1000),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings_audit (
                id              SERIAL      PRIMARY KEY,
                timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                account_name    TEXT        NOT NULL,
                field           TEXT        NOT NULL,
                old_value       TEXT,
                new_value       TEXT        NOT NULL,
                actor           TEXT        NOT NULL DEFAULT 'admin'
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_settings_audit_account_ts
                ON settings_audit(account_name, timestamp DESC)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS failed_login_attempts (
                id              SERIAL      PRIMARY KEY,
                ip_addr         TEXT        NOT NULL,
                attempted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                user_agent      TEXT        NOT NULL DEFAULT ''
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_failed_login_ip_ts
                ON failed_login_attempts(ip_addr, attempted_at)
        """)


# ── Signal logging ───────────────────────────────────────────────────


async def log_signal(
    raw_text: str,
    signal_type: str,
    action_taken: str,
    symbol: str = "",
    direction: str = "",
    entry_zone_low: float = 0.0,
    entry_zone_high: float = 0.0,
    sl: float = 0.0,
    tp: float = 0.0,
    details: str = "",
) -> int:
    """Log a parsed signal. Returns the signal ID."""
    return await _pool.fetchval(
        """INSERT INTO signals
           (timestamp, raw_text, signal_type, symbol, direction,
            entry_zone_low, entry_zone_high, sl, tp, action_taken, details)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
           RETURNING id""",
        datetime.now(timezone.utc),
        raw_text,
        signal_type,
        symbol,
        direction,
        entry_zone_low,
        entry_zone_high,
        sl,
        tp,
        action_taken,
        details,
    )


# ── Trade logging ────────────────────────────────────────────────────


async def log_trade(
    signal_id: int | None,
    account_name: str,
    symbol: str,
    direction: str,
    entry_price: float,
    sl: float,
    tp: float,
    lot_size: float,
    ticket: int,
    status: str,
    raw_signal: str = "",
) -> int:
    """Log a trade execution. Returns the trade ID."""
    return await _pool.fetchval(
        """INSERT INTO trades
           (signal_id, timestamp, account_name, symbol, direction,
            entry_price, sl, tp, lot_size, ticket, status, raw_signal)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
           RETURNING id""",
        signal_id,
        datetime.now(timezone.utc),
        account_name,
        symbol,
        direction,
        entry_price,
        sl,
        tp,
        lot_size,
        ticket,
        status,
        raw_signal,
    )


# ── Trade updates ────────────────────────────────────────────────────


async def update_trade_close(ticket: int, account_name: str, pnl: float, close_price: float) -> None:
    """Update a trade record when the position is closed."""
    await _pool.execute(
        """UPDATE trades SET status='closed', pnl=$1, close_price=$2, close_time=$3
           WHERE ticket=$4 AND account_name=$5""",
        pnl,
        close_price,
        datetime.now(timezone.utc),
        ticket,
        account_name,
    )


# ── Daily stats ──────────────────────────────────────────────────────


async def increment_daily_stat(account_name: str, field: str, amount: int = 1) -> None:
    """Increment a daily stat counter (trades_count or server_messages)."""
    safe_field = _validate_field(field)
    today = _utc_today()
    await _pool.execute(
        f"""INSERT INTO daily_stats (date, account_name, {safe_field})
            VALUES ($1, $2, $3)
            ON CONFLICT(date, account_name)
            DO UPDATE SET {safe_field} = daily_stats.{safe_field} + $3""",
        today,
        account_name,
        amount,
    )


async def get_daily_stats_batch(account_name: str) -> dict[str, int]:
    """Get all daily stats for an account in a single query."""
    today = _utc_today()
    row = await _pool.fetchrow(
        "SELECT trades_count, server_messages FROM daily_stats WHERE date=$1 AND account_name=$2",
        today,
        account_name,
    )
    if row:
        return {"trades_count": row["trades_count"], "server_messages": row["server_messages"]}
    return {"trades_count": 0, "server_messages": 0}


async def get_daily_stat(account_name: str, field: str) -> int:
    """Get current daily stat value."""
    safe_field = _validate_field(field)
    today = _utc_today()
    result = await _pool.fetchval(
        f"SELECT {safe_field} FROM daily_stats WHERE date=$1 AND account_name=$2",
        today,
        account_name,
    )
    return result if result is not None else 0


# ── Pending orders ───────────────────────────────────────────────────


async def log_pending_order(
    signal_id: int | None,
    account_name: str,
    ticket: int,
    symbol: str,
    order_type: str,
    volume: float,
    price: float,
    sl: float,
    tp: float,
    expires_at: Union[str, datetime],
) -> int:
    """Log a pending order. Returns the order ID."""
    # Accept both str and datetime for backward compatibility
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    return await _pool.fetchval(
        """INSERT INTO pending_orders
           (signal_id, account_name, ticket, symbol, order_type,
            volume, price, sl, tp, expires_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
           RETURNING id""",
        signal_id,
        account_name,
        ticket,
        symbol,
        order_type,
        volume,
        price,
        sl,
        tp,
        expires_at,
    )


async def get_expired_pending_orders() -> list[dict]:
    """Get pending orders that have passed their expiry time."""
    now = datetime.now(timezone.utc)
    rows = await _pool.fetch(
        "SELECT * FROM pending_orders WHERE status='active' AND expires_at < $1",
        now,
    )
    return [dict(r) for r in rows]


async def mark_pending_cancelled(order_id: int) -> None:
    """Mark a pending order as cancelled."""
    await _pool.execute(
        "UPDATE pending_orders SET status='cancelled' WHERE id=$1",
        order_id,
    )


async def mark_pending_filled(ticket: int, account_name: str) -> None:
    """Mark a pending order as filled."""
    await _pool.execute(
        "UPDATE pending_orders SET status='filled' WHERE ticket=$1 AND account_name=$2",
        ticket,
        account_name,
    )


# ── Query helpers (dashboard) ────────────────────────────────────────


async def get_recent_trades(limit: int = 50) -> list[dict]:
    """Get recent trades for dashboard display."""
    rows = await _pool.fetch(
        "SELECT * FROM trades ORDER BY id DESC LIMIT $1",
        limit,
    )
    return [dict(r) for r in rows]


async def get_recent_signals(limit: int = 50) -> list[dict]:
    """Get recent signals for dashboard display."""
    rows = await _pool.fetch(
        "SELECT * FROM signals ORDER BY id DESC LIMIT $1",
        limit,
    )
    return [dict(r) for r in rows]


# ── Analytics (OBS-03 / ANLYT-01) ──────────────────────────────────


async def get_analytics_by_symbol() -> list[dict]:
    """Get win rate, profit factor, and trade stats grouped by symbol."""
    rows = await _pool.fetch("""
        SELECT
            symbol,
            COUNT(*) AS total_trades,
            COUNT(*) FILTER (WHERE pnl > 0) AS wins,
            COUNT(*) FILTER (WHERE pnl <= 0) AS losses,
            ROUND(
                COUNT(*) FILTER (WHERE pnl > 0)::numeric
                / NULLIF(COUNT(*), 0) * 100, 1
            ) AS win_rate,
            COALESCE(SUM(pnl) FILTER (WHERE pnl > 0), 0) AS gross_profit,
            COALESCE(ABS(SUM(pnl) FILTER (WHERE pnl <= 0)), 0) AS gross_loss,
            CASE
                WHEN COALESCE(ABS(SUM(pnl) FILTER (WHERE pnl <= 0)), 0) = 0
                THEN NULL
                ELSE ROUND(
                    COALESCE(SUM(pnl) FILTER (WHERE pnl > 0), 0)::numeric
                    / ABS(SUM(pnl) FILTER (WHERE pnl <= 0))::numeric, 2
                )
            END AS profit_factor,
            COALESCE(SUM(pnl), 0) AS net_pnl
        FROM trades
        WHERE status = 'closed'
        GROUP BY symbol
        ORDER BY total_trades DESC
    """)
    return [dict(r) for r in rows]


async def get_analytics_summary() -> dict:
    """Get overall analytics summary across all symbols."""
    row = await _pool.fetchrow("""
        SELECT
            COUNT(*) AS total_trades,
            COUNT(*) FILTER (WHERE pnl > 0) AS wins,
            COUNT(*) FILTER (WHERE pnl <= 0) AS losses,
            ROUND(
                COUNT(*) FILTER (WHERE pnl > 0)::numeric
                / NULLIF(COUNT(*), 0) * 100, 1
            ) AS win_rate,
            COALESCE(SUM(pnl) FILTER (WHERE pnl > 0), 0) AS gross_profit,
            COALESCE(ABS(SUM(pnl) FILTER (WHERE pnl <= 0)), 0) AS gross_loss,
            CASE
                WHEN COALESCE(ABS(SUM(pnl) FILTER (WHERE pnl <= 0)), 0) = 0
                THEN NULL
                ELSE ROUND(
                    COALESCE(SUM(pnl) FILTER (WHERE pnl > 0), 0)::numeric
                    / ABS(SUM(pnl) FILTER (WHERE pnl <= 0))::numeric, 2
                )
            END AS profit_factor,
            COALESCE(SUM(pnl), 0) AS net_pnl
        FROM trades
        WHERE status = 'closed'
    """)
    return dict(row) if row else {
        "total_trades": 0, "wins": 0, "losses": 0,
        "win_rate": None, "gross_profit": 0, "gross_loss": 0,
        "profit_factor": None, "net_pnl": 0,
    }


# ── Archival (DB-03) ────────────────────────────────────────────────


async def archive_old_trades(archive_dir: str, months: int = 3) -> dict:
    """Archive closed trades older than N months to CSV files.

    Only archives trades with status='closed' AND close_time older than cutoff.
    Never archives 'opened' or 'pending' trades regardless of age.

    Returns: {"archived_count": int, "file_path": str}
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
    archive_path = Path(archive_dir)
    archive_path.mkdir(parents=True, exist_ok=True)

    filename = f"trades_archive_{cutoff.strftime('%Y%m%d')}.csv"
    filepath = archive_path / filename

    async with _pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM trades WHERE status='closed' AND close_time < $1",
            cutoff,
        )

        if count == 0:
            return {"archived_count": 0, "file_path": ""}

        # Export to CSV using asyncpg COPY protocol
        await conn.copy_from_query(
            "SELECT * FROM trades WHERE status='closed' AND close_time < $1 ORDER BY id",
            cutoff,
            output=str(filepath),
            format="csv",
            header=True,
        )

        # Delete archived rows
        await conn.execute(
            "DELETE FROM trades WHERE status='closed' AND close_time < $1",
            cutoff,
        )

    logger.info("Archived %d trades to %s", count, filepath)
    return {"archived_count": count, "file_path": str(filepath)}


# ── accounts + settings (Phase 5) ────────────────────────────────────


async def upsert_account_if_missing(
    name: str, server: str, login: int, password_env: str,
    risk_percent: float, max_lot_size: float, max_daily_loss_percent: float,
    max_open_trades: int, enabled: bool, mt5_host: str, mt5_port: int,
) -> bool:
    """Idempotent INSERT ... ON CONFLICT DO NOTHING. Returns True iff a new row was inserted (D-24)."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO accounts (name, server, login, password_env,
                   risk_percent, max_lot_size, max_daily_loss_percent,
                   max_open_trades, enabled, mt5_host, mt5_port)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
               ON CONFLICT (name) DO NOTHING
               RETURNING name""",
            name, server, login, password_env,
            risk_percent, max_lot_size, max_daily_loss_percent,
            max_open_trades, enabled, mt5_host, mt5_port,
        )
        return row is not None


async def upsert_account_settings_if_missing(
    account_name: str, risk_mode: str = "percent", risk_value: float = 1.0,
    max_stages: int = 1, default_sl_pips: int = 100, max_daily_trades: int = 30,
) -> bool:
    """Idempotent INSERT of account_settings row (D-26). Returns True on new insert."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO account_settings (account_name, risk_mode, risk_value,
                   max_stages, default_sl_pips, max_daily_trades)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (account_name) DO NOTHING
               RETURNING account_name""",
            account_name, risk_mode, risk_value, max_stages, default_sl_pips, max_daily_trades,
        )
        return row is not None


async def get_account_settings(account_name: str) -> dict | None:
    """Return effective settings (account_settings ⋈ accounts) for one account, or None."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT s.account_name,
                      s.risk_mode, s.risk_value::float AS risk_value,
                      s.max_stages, s.default_sl_pips, s.max_daily_trades,
                      a.max_open_trades, a.max_lot_size
                 FROM account_settings s
                 JOIN accounts a ON a.name = s.account_name
                WHERE s.account_name = $1""",
            account_name,
        )
        return dict(row) if row else None


async def get_all_accounts() -> list[dict]:
    """Return all account names (alphabetical)."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch("SELECT name FROM accounts ORDER BY name")
        return [dict(r) for r in rows]


async def update_account_setting(
    account_name: str, field: str, new_value, actor: str = "admin",
) -> None:
    """Write-through with audit row, same transaction (D-29).

    Whitelists `field` BEFORE any SQL interpolation to block SQL injection.
    Audit row is inserted BEFORE the UPDATE so `old_value` is the value prior
    to the mutation.
    """
    field = _validate_account_settings_field(field)  # whitelist before SQL
    async with _pool.acquire() as conn:
        async with conn.transaction():
            old_value = await conn.fetchval(
                f"SELECT {field}::TEXT FROM account_settings WHERE account_name=$1",
                account_name,
            )
            await conn.execute(
                """INSERT INTO settings_audit
                   (account_name, field, old_value, new_value, actor)
                   VALUES ($1, $2, $3, $4, $5)""",
                account_name, field, old_value, str(new_value), actor,
            )
            await conn.execute(
                f"UPDATE account_settings SET {field}=$1, updated_at=NOW() "
                f"WHERE account_name=$2",
                new_value, account_name,
            )


async def get_orphan_accounts(seeded_names: list[str]) -> list[str]:
    """Return accounts in DB not present in accounts.json (D-25 warning list)."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT name FROM accounts WHERE name <> ALL($1::text[])",
            seeded_names,
        )
        return [r["name"] for r in rows]


# ── failed_login_attempts (consumed by Plan 04) ──────────────────────


async def get_failed_login_count(ip_addr: str, minutes: int = 15) -> int:
    """Count failed login attempts from an IP within the last N minutes."""
    async with _pool.acquire() as conn:
        return await conn.fetchval(
            """SELECT COUNT(*)::int FROM failed_login_attempts
                WHERE ip_addr = $1
                  AND attempted_at > NOW() - make_interval(mins => $2)""",
            ip_addr, minutes,
        )


async def log_failed_login(ip_addr: str, user_agent: str = "") -> None:
    """Insert a failed login attempt row (D-17)."""
    async with _pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO failed_login_attempts (ip_addr, user_agent) VALUES ($1, $2)",
            ip_addr, user_agent,
        )


async def clear_failed_logins(ip_addr: str) -> None:
    """Clear failed login attempts for an IP (called on successful login)."""
    async with _pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM failed_login_attempts WHERE ip_addr = $1",
            ip_addr,
        )
