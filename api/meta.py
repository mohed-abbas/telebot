"""api/meta.py — overview / trading-status / emergency-preview read routes
(Phase 08 Plan 03).

Composes the same aggregates the HTML overview/status routes already build,
re-shaped as Pydantic JSON:
  * GET /overview          -> dashboard composition (dashboard.py:343-364)
  * GET /trading-status    -> executor paused/reconnecting (dashboard.py:1357-1363)
  * GET /emergency/preview -> _get_all_positions() + get_pending_orders()
                              (dashboard.py:1306-1330)

Executor state is reached ONLY through the require_executor() accessor — never
`from dashboard import _executor` (init_dashboard rebinds that global late;
a direct import captures a stale None — 08-PATTERNS Pitfall 6). The accounts
list reuses the same money `_display` enrichment as api/accounts.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.accounts import _enrich_account
from api.deps import require_executor, require_user
from api.schemas import EmergencyPreview, OverviewMeta, TradingStatus

router = APIRouter()


@router.get("/overview", response_model=OverviewMeta)
async def overview(_user: str = Depends(require_user)) -> OverviewMeta:
    """Top-of-overview composite (accounts + open count + paused flag)."""
    import dashboard  # deferred: keep `import api.meta` side-effect-free

    executor = require_executor()
    accounts = await dashboard._get_accounts_overview()
    positions = await dashboard._get_all_positions()
    return OverviewMeta(
        trading_paused=getattr(executor, "_trading_paused", False),
        open_positions=len(positions),
        accounts=[_enrich_account(a) for a in accounts],
    )


@router.get("/trading-status", response_model=TradingStatus)
async def trading_status(_user: str = Depends(require_user)) -> TradingStatus:
    """Current trading status (paused flag + derived status label)."""
    executor = require_executor()
    paused = getattr(executor, "_trading_paused", False)
    return TradingStatus(paused=paused, status="paused" if paused else "running")


@router.get("/emergency/preview", response_model=EmergencyPreview)
async def emergency_preview(_user: str = Depends(require_user)) -> EmergencyPreview:
    """What a kill-switch would close (wraps _get_all_positions + pending orders)."""
    import dashboard  # deferred: keep `import api.meta` side-effect-free

    executor = require_executor()
    positions = await dashboard._get_all_positions()

    pending_count = 0
    for connector in executor.tm.connectors.values():
        if getattr(connector, "connected", False):
            try:
                orders = await connector.get_pending_orders()
                pending_count += len(orders)
            except Exception:
                pass

    accounts = sorted({p["account"] for p in positions})
    return EmergencyPreview(
        open_positions=len(positions),
        pending_orders=pending_count,
        accounts=accounts,
    )
