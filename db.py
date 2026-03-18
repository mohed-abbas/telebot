"""SQLite database for trade logging, signal tracking, and daily stats."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, date, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH: Path | None = None
_db: sqlite3.Connection | None = None
_lock = asyncio.Lock()


def init_db(db_path: str | Path) -> None:
    """Initialize the database and create tables if needed."""
    global _DB_PATH, _db
    _DB_PATH = Path(db_path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _db = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    _db.row_factory = sqlite3.Row
    _db.execute("PRAGMA journal_mode=WAL")
    _create_tables()
    logger.info("Database initialized: %s", _DB_PATH)


def _create_tables() -> None:
    _db.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            symbol TEXT,
            direction TEXT,
            entry_zone_low REAL,
            entry_zone_high REAL,
            sl REAL,
            tp REAL,
            action_taken TEXT NOT NULL,
            details TEXT
        );

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER,
            timestamp TEXT NOT NULL,
            account_name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL,
            sl REAL,
            tp REAL,
            lot_size REAL,
            ticket INTEGER,
            status TEXT NOT NULL,
            pnl REAL DEFAULT 0.0,
            close_price REAL,
            close_time TEXT,
            raw_signal TEXT,
            FOREIGN KEY (signal_id) REFERENCES signals(id)
        );

        CREATE TABLE IF NOT EXISTS daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            account_name TEXT NOT NULL,
            trades_count INTEGER DEFAULT 0,
            server_messages INTEGER DEFAULT 0,
            daily_pnl REAL DEFAULT 0.0,
            starting_balance REAL DEFAULT 0.0,
            UNIQUE(date, account_name)
        );

        CREATE TABLE IF NOT EXISTS pending_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER,
            account_name TEXT NOT NULL,
            ticket INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            order_type TEXT NOT NULL,
            volume REAL,
            price REAL,
            sl REAL,
            tp REAL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (signal_id) REFERENCES signals(id)
        );
    """)
    _db.commit()


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
    async with _lock:
        cursor = _db.execute(
            """INSERT INTO signals
               (timestamp, raw_text, signal_type, symbol, direction,
                entry_zone_low, entry_zone_high, sl, tp, action_taken, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
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
            ),
        )
        _db.commit()
        return cursor.lastrowid


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
    async with _lock:
        cursor = _db.execute(
            """INSERT INTO trades
               (signal_id, timestamp, account_name, symbol, direction,
                entry_price, sl, tp, lot_size, ticket, status, raw_signal)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal_id,
                datetime.now(timezone.utc).isoformat(),
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
            ),
        )
        _db.commit()
        return cursor.lastrowid


async def update_trade_close(ticket: int, account_name: str, pnl: float, close_price: float) -> None:
    """Update a trade record when the position is closed."""
    async with _lock:
        _db.execute(
            """UPDATE trades SET status='closed', pnl=?, close_price=?, close_time=?
               WHERE ticket=? AND account_name=?""",
            (pnl, close_price, datetime.now(timezone.utc).isoformat(), ticket, account_name),
        )
        _db.commit()


async def increment_daily_stat(account_name: str, field: str, amount: int = 1) -> None:
    """Increment a daily stat counter (trades_count or server_messages)."""
    today = date.today().isoformat()
    async with _lock:
        _db.execute(
            f"""INSERT INTO daily_stats (date, account_name, {field})
                VALUES (?, ?, ?)
                ON CONFLICT(date, account_name)
                DO UPDATE SET {field} = {field} + ?""",
            (today, account_name, amount, amount),
        )
        _db.commit()


async def get_daily_stat(account_name: str, field: str) -> int:
    """Get current daily stat value."""
    today = date.today().isoformat()
    async with _lock:
        row = _db.execute(
            f"SELECT {field} FROM daily_stats WHERE date=? AND account_name=?",
            (today, account_name),
        ).fetchone()
        return row[0] if row else 0


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
    expires_at: str,
) -> int:
    async with _lock:
        cursor = _db.execute(
            """INSERT INTO pending_orders
               (signal_id, account_name, ticket, symbol, order_type,
                volume, price, sl, tp, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal_id, account_name, ticket, symbol, order_type,
                volume, price, sl, tp,
                datetime.now(timezone.utc).isoformat(), expires_at,
            ),
        )
        _db.commit()
        return cursor.lastrowid


async def get_expired_pending_orders() -> list[dict]:
    """Get pending orders that have passed their expiry time."""
    now = datetime.now(timezone.utc).isoformat()
    async with _lock:
        rows = _db.execute(
            "SELECT * FROM pending_orders WHERE status='active' AND expires_at < ?",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]


async def mark_pending_cancelled(order_id: int) -> None:
    async with _lock:
        _db.execute(
            "UPDATE pending_orders SET status='cancelled' WHERE id=?", (order_id,),
        )
        _db.commit()


async def mark_pending_filled(ticket: int, account_name: str) -> None:
    async with _lock:
        _db.execute(
            "UPDATE pending_orders SET status='filled' WHERE ticket=? AND account_name=?",
            (ticket, account_name),
        )
        _db.commit()


async def get_recent_trades(limit: int = 50) -> list[dict]:
    """Get recent trades for dashboard display."""
    async with _lock:
        rows = _db.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


async def get_recent_signals(limit: int = 50) -> list[dict]:
    """Get recent signals for dashboard display."""
    async with _lock:
        rows = _db.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
