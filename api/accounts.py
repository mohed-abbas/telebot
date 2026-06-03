"""api/accounts.py — accounts read route (Phase 08 Plan 03).

Wraps dashboard._get_accounts_overview() VERBATIM and adds the D-05 money
`_display` twins through the single-source formatter (api/formatting.py).
Session-gated via require_user (T-08-11).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

import dashboard
from api.deps import require_user
from api.formatting import money_display
from api.schemas import AccountOverview

router = APIRouter()


def _enrich_account(row: dict) -> AccountOverview:
    """Map a _get_accounts_overview() dict to AccountOverview with money twins."""
    return AccountOverview(
        name=row["name"],
        connected=row["connected"],
        enabled=row["enabled"],
        balance=row["balance"],
        balance_display=money_display(row["balance"]),
        equity=row["equity"],
        equity_display=money_display(row["equity"]),
        margin=row["margin"],
        margin_display=money_display(row["margin"]),
        free_margin=row["free_margin"],
        free_margin_display=money_display(row["free_margin"]),
        open_trades=row["open_trades"],
        total_profit=row["total_profit"],
        total_profit_display=money_display(row["total_profit"]),
        daily_trades=row["daily_trades"],
        daily_messages=row["daily_messages"],
        max_daily_trades=row["max_daily_trades"],
        daily_limit_pct=row["daily_limit_pct"],
        risk_percent=row["risk_percent"],
        max_lot=row["max_lot"],
    )


@router.get("/accounts", response_model=list[AccountOverview])
async def list_accounts(_user: str = Depends(require_user)) -> list[AccountOverview]:
    """Per-account overview (wraps dashboard._get_accounts_overview)."""
    rows = await dashboard._get_accounts_overview()
    return [_enrich_account(r) for r in rows]
