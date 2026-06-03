"""api/router.py — single-owner router assembly (Phase 08 Plan 01).

ROUTER OWNERSHIP CONTRACT: this file is created ONCE by Plan 01 and wires the
WHOLE `/api/v2` surface. Each resource module (auth/accounts/positions/history/
signals/stages/analytics/meta/actions/settings) defines its own
`router = APIRouter()`; this file imports every one and `include_router`s it into
`api_router`. Plans 02-05 ONLY add `@router` handlers inside their own resource
module — they NEVER edit this file. That keeps router.py single-owned by Plan 01.
"""

from __future__ import annotations

from api import api_router
from api import (
    accounts,
    actions,
    analytics,
    auth,
    history,
    meta,
    positions,
    settings,
    signals,
    stages,
)

# Include every resource sub-router exactly once (single-owner assembly).
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
api_router.include_router(positions.router)
api_router.include_router(history.router)
api_router.include_router(signals.router)
api_router.include_router(stages.router)
api_router.include_router(analytics.router)
api_router.include_router(meta.router)
api_router.include_router(actions.router)
api_router.include_router(settings.router)
