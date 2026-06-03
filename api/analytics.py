"""api/analytics.py — analytics read route (Phase 08 Plan 03).

Wraps db.get_analytics_with_filters(range_days, source_name) +
db.get_analytics_sources() VERBATIM. The helper returns
{summary, by_source, avg_stages, extremes}; this route projects the `summary`
sub-dict onto the flat schemas.Analytics model and adds money `_display` twins
(via api/formatting.py) on the profit/gross fields. Win-rate and profit-factor
are ratios — kept raw (no _display twin per D-05). Session-gated.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

import db
from api.deps import require_user
from api.formatting import money_display
from api.schemas import Analytics

router = APIRouter()


def _parse_range(range_: str) -> int | None:
    """Coerce the `range` query param to range_days (None = all time)."""
    if not range_:
        return None
    try:
        days = int(range_)
        return days if days > 0 else None
    except (TypeError, ValueError):
        return None


@router.get("/analytics", response_model=Analytics)
async def get_analytics(
    range: str = "",
    source: str = "",
    _user: str = Depends(require_user),
) -> Analytics:
    """Analytics summary (wraps db.get_analytics_with_filters)."""
    data = await db.get_analytics_with_filters(
        range_days=_parse_range(range),
        source_name=source,
    )
    # get_analytics_sources() is wrapped here so the source-filter dropdown shares
    # this route's single round-trip; surfaced for the SPA filter control.
    await db.get_analytics_sources()

    summary = data.get("summary", {}) or {}
    gross_profit = summary.get("gross_profit") or 0.0
    gross_loss = summary.get("gross_loss") or 0.0
    net_pnl = summary.get("net_pnl") or 0.0
    return Analytics(
        total_trades=summary.get("total_trades") or 0,
        wins=summary.get("wins") or 0,
        losses=summary.get("losses") or 0,
        win_rate=summary.get("win_rate") or 0.0,
        profit_factor=summary.get("profit_factor") or 0.0,
        total_profit=net_pnl,
        total_profit_display=money_display(net_pnl),
        gross_profit=gross_profit,
        gross_profit_display=money_display(gross_profit),
        gross_loss=gross_loss,
        gross_loss_display=money_display(gross_loss),
    )
