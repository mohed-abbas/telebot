"""api/analytics.py — analytics read route (Phase 08 Plan 03).

Wraps db.get_analytics_with_filters(range_days, source_name) +
db.get_analytics_sources() VERBATIM. The helper returns
{summary, by_source, avg_stages, extremes}; this route projects the full payload
onto schemas.Analytics (D-01 legacy parity): the flat `summary` fields, the
per-source `by_source[]` deep-dive, overall `extremes`, conditional `avg_stages`,
and the `sources` list. Money fields gain `_display` twins (via api/formatting.py);
win-rate and profit-factor are ratios — kept raw (no _display twin per D-05/D-14).
Session-gated.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import db
from api.deps import require_user
from api.formatting import money_display
from api.schemas import Analytics, AnalyticsBySource, AnalyticsExtremes

router = APIRouter()


def _parse_range(range_: str) -> int | None:
    """Coerce the `range` query param to range_days (None = all time).

    Empty → all time. A non-empty value MUST be a positive integer day count
    (the SPA sends 7/30/90 or empty); anything else (typo, negative, zero) is a
    client error surfaced as HTTP 422 rather than silently coerced to all-time
    (IN-04) — a malformed range no longer masquerades as a valid all-time result.
    """
    if not range_:
        return None
    try:
        days = int(range_)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422, detail=f"Invalid range '{range_}': expected a positive integer day count."
        )
    if days <= 0:
        raise HTTPException(
            status_code=422, detail=f"Invalid range '{range_}': expected a positive integer day count."
        )
    return days


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
    # this route's single round-trip; surfaced (no longer discarded) for the SPA
    # filter control (D-01).
    sources = await db.get_analytics_sources()

    summary = data.get("summary", {}) or {}
    gross_profit = summary.get("gross_profit") or 0.0
    gross_loss = summary.get("gross_loss") or 0.0
    net_pnl = summary.get("net_pnl") or 0.0

    # Per-source deep-dive (D-01). Money fields carry _display twins; win_rate /
    # profit_factor are ratios kept raw (D-14). best/worst may be None → None-guard.
    by_source = []
    for row in data.get("by_source", []) or []:
        row_net = row.get("net_pnl") or 0.0
        best = row.get("best_trade")
        worst = row.get("worst_trade")
        by_source.append(
            AnalyticsBySource(
                source_name=row.get("source_name") or "Unknown",
                total_trades=row.get("total_trades") or 0,
                wins=row.get("wins") or 0,
                losses=row.get("losses") or 0,
                win_rate=row.get("win_rate"),
                profit_factor=row.get("profit_factor"),
                net_pnl=row_net,
                net_pnl_display=money_display(row_net),
                best_trade=best,
                best_trade_display=money_display(best) if best is not None else None,
                worst_trade=worst,
                worst_trade_display=money_display(worst) if worst is not None else None,
            )
        )

    # Overall best/worst extremes (D-01) — None-guarded money _display twins.
    ext = data.get("extremes", {}) or {}
    ext_best = ext.get("best_trade")
    ext_worst = ext.get("worst_trade")
    extremes = AnalyticsExtremes(
        best_trade=ext_best,
        best_trade_display=money_display(ext_best) if ext_best is not None else None,
        worst_trade=ext_worst,
        worst_trade_display=money_display(ext_worst) if ext_worst is not None else None,
    )

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
        by_source=by_source,
        extremes=extremes,
        # avg_stages is None on the all-source view (Pitfall 3) — pass through, never default to 0.
        avg_stages=data.get("avg_stages"),
        sources=sources,
    )
