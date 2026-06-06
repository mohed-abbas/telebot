"""api/history.py — trade history read routes (Phase 08 Plan 03).

Wraps the existing helpers VERBATIM:
  * GET /history                 -> db.get_filtered_trades(account, source, symbol,
                                    from_date, to_date)
  * GET /history/filter-options  -> db.get_trade_filter_options()

Money/price/timestamp fields get D-05 `_display` twins through api/formatting.py
(timestamps -> ts_machine ISO-8601-with-offset raw + ts_display absolute UTC).
Session-gated via require_user.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends

import db
from api.deps import require_user
from api.formatting import money_display, price_display, ts_display, ts_machine
from api.schemas import FilterOptions, HistoryTrade

router = APIRouter()


def _ts_pair(value):
    """Return (ts_machine, ts_display) for a datetime, or (None, None)."""
    if isinstance(value, datetime):
        return ts_machine(value), ts_display(value)
    return None, None


def _enrich_trade(row: dict) -> HistoryTrade:
    """Map a get_filtered_trades() row (trades-table cols) to HistoryTrade.

    trades columns: account_name, entry_price, lot_size, pnl, timestamp.
    There is no stored close_price/closed_at — those stay None.
    """
    symbol = row.get("symbol") or ""
    open_price = row.get("entry_price") or 0.0
    volume = row.get("lot_size") or 0.0
    profit = row.get("pnl") or 0.0
    opened_at, opened_at_display = _ts_pair(row.get("timestamp"))
    sl = row.get("sl")
    tp = row.get("tp")
    return HistoryTrade(
        account=row.get("account_name") or "",
        ticket=row.get("ticket") or 0,
        symbol=symbol,
        direction=row.get("direction") or "",
        volume=volume,
        volume_display=f"{volume:.2f}",
        open_price=open_price,
        open_price_display=price_display(symbol, open_price),
        close_price=None,
        close_price_display=None,
        profit=profit,
        profit_display=money_display(profit),
        opened_at=opened_at,
        opened_at_display=opened_at_display,
        closed_at=None,
        closed_at_display=None,
        # D-12 widened legacy parity (price fields get _display twins).
        sl=sl,
        sl_display=price_display(symbol, sl) if sl is not None else None,
        tp=tp,
        tp_display=price_display(symbol, tp) if tp is not None else None,
        status=row.get("status"),  # bare
        source_name=row.get("source_name") or "Unknown",  # bare
    )


@router.get("/history", response_model=list[HistoryTrade])
async def list_history(
    account: str = "",
    source: str = "",
    symbol: str = "",
    from_date: date | None = None,
    to_date: date | None = None,
    _user: str = Depends(require_user),
) -> list[HistoryTrade]:
    """Filtered trade history (wraps db.get_filtered_trades).

    `from_date`/`to_date` are typed as `date` so FastAPI parses the ISO query
    strings into real `datetime.date` objects — `db.get_filtered_trades` binds
    them to a `::date` param, which asyncpg rejects for bare strings
    (`'str' object has no attribute 'toordinal'`). Falsy (`None`) values skip
    the filter, preserving the unfiltered default. `db.py` stays untouched.
    """
    rows = await db.get_filtered_trades(
        account=account,
        source=source,
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
    )
    return [_enrich_trade(r) for r in rows]


@router.get("/history/filter-options", response_model=FilterOptions)
async def history_filter_options(_user: str = Depends(require_user)) -> FilterOptions:
    """Distinct filter values (wraps db.get_trade_filter_options).

    The helper returns accounts/symbols/sources; `directions` is not stored as a
    distinct-filter list, so it stays empty (schema-declared, additive).
    """
    opts = await db.get_trade_filter_options()
    return FilterOptions(
        accounts=opts.get("accounts", []),
        symbols=opts.get("symbols", []),
        directions=[],
    )
