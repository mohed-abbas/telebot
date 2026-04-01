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
