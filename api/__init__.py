"""`/api/v2` JSON API package (v1.2 — React/Vite dashboard rewrite).

This package mounts a single `api_router = APIRouter(prefix="/api/v2")` onto the
existing FastAPI app (see dashboard.py wiring). Every resource module
(auth/accounts/positions/history/signals/stages/analytics/meta/actions/settings)
owns its own `router = APIRouter()`; `api/router.py` includes them ALL exactly
once (single-owner contract — Plans 02-05 add handlers to their own module only,
never edit router.py).

Bot core (executor.py, trade_manager.py, db.py, mt5_connector.py) and
mt5-rest-server/ are called only, never imported-bound or edited.
"""

from __future__ import annotations

from fastapi import APIRouter

# The single router every resource sub-router is mounted under. Importing
# `from api import api_router` gives dashboard.py the mountable surface.
api_router = APIRouter(prefix="/api/v2")

# Populate api_router with every resource sub-router (single-owner assembly).
# Imported AFTER api_router exists so api/router.py can `from api import api_router`.
from api import router as _router  # noqa: E402,F401  (import for side-effect: include_router calls)

__all__ = ["api_router"]
