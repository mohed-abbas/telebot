"""api/positions.py — positions read routes (Phase 08 Plan 03).

Wraps the existing in-process helpers VERBATIM — no new query, no recompute:
  * GET /positions                      -> dashboard._get_all_positions()
  * GET /positions/{account}/{ticket}   -> db.get_position_drilldown(ticket, account)

Every price/volume/money field gets a parallel `_display` twin through the
single-source formatter (api/formatting.py) — the route NEVER formats inline
(D-08). Both routes are session-gated via require_user (T-08-11: 401 without a
session, no redirect on /api/v2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import dashboard
import db
from api.deps import require_user
from api.formatting import money_display, price_display, volume_display
from api.schemas import Position

router = APIRouter()


def _enrich_position(row: dict) -> Position:
    """Map a _get_all_positions() dict to a Position with D-05 _display twins."""
    return Position(
        account=row["account"],
        ticket=row["ticket"],
        symbol=row["symbol"],
        direction=row["direction"],
        volume=row["volume"],
        volume_display=volume_display(row["volume"]),
        open_price=row["open_price"],
        open_price_display=price_display(row["symbol"], row["open_price"]),
        sl=row.get("sl"),
        tp=row.get("tp"),
        profit=row["profit"],
        profit_display=money_display(row["profit"]),
    )


@router.get("/positions", response_model=list[Position])
async def list_positions(_user: str = Depends(require_user)) -> list[Position]:
    """All open positions across accounts (wraps dashboard._get_all_positions)."""
    rows = await dashboard._get_all_positions()
    return [_enrich_position(r) for r in rows]


@router.get("/positions/{account}/{ticket}")
async def position_drilldown(
    account: str, ticket: int, _user: str = Depends(require_user)
) -> dict:
    """Drilldown for one position (wraps db.get_position_drilldown). 404 if gone.

    The drilldown payload (position + fill_history + signal) carries the same
    `_display` enrichment on its monetary/price fields as the list route, with
    the raw values preserved untouched.
    """
    detail = await db.get_position_drilldown(ticket, account)
    if detail is None:
        raise HTTPException(status_code=404, detail="Position not found")

    pos = detail.get("position") or {}
    symbol = pos.get("symbol", "")
    # Trades-table position dict uses entry_price / lot_size / pnl column names.
    if "entry_price" in pos and pos["entry_price"] is not None:
        pos["entry_price_display"] = price_display(symbol, pos["entry_price"])
    if "lot_size" in pos and pos["lot_size"] is not None:
        pos["lot_size_display"] = volume_display(pos["lot_size"])
    if "pnl" in pos and pos["pnl"] is not None:
        pos["pnl_display"] = money_display(pos["pnl"])
    return detail
