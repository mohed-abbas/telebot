"""api/stages.py — staged-entries read route (Phase 08 Plan 03).

Composes the SAME helpers the HTML /staged page uses, VERBATIM:
  * active   = [_enrich_stage_for_ui(s, positions) for s in get_pending_stages()]
  * resolved = get_recently_resolved_stages(50)

`_enrich_stage_for_ui` (dashboard.py:456) produces the UI display shape; this
route reaches it through the dashboard module (accessor-safe) and adds D-05
`_display` twins on price/timestamp fields. The enriched stage shape differs
from the flat schemas.Stage model, so the route returns an active+resolved
JSON payload (each list a dict-of-fields) rather than coercing to Stage.
Session-gated via require_user.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

import db
from api.deps import require_user
from api.formatting import price_display, ts_display, ts_machine

router = APIRouter()


def _enrich_active(stage: dict, raw: dict) -> dict:
    """Add price `_display` twins + a machine `started_at` to an _enrich_stage_for_ui() dict.

    `_enrich_stage_for_ui` DROPS the raw `created_at` after building its `elapsed`
    string (dashboard.py:567-581), so the timestamp lives ONLY in `raw` — the raw
    get_pending_stages() row. Source `started_at` from there (Pitfall 4 / D-09),
    mirroring the ts_machine/ts_display twin shape of `_enrich_resolved`.
    """
    symbol = stage.get("symbol") or ""
    out = dict(stage)
    for key in ("band_low", "band_high", "current_price"):
        val = stage.get(key)
        if val is not None:
            out[f"{key}_display"] = price_display(symbol, val)
    created_at = raw.get("created_at")
    if isinstance(created_at, datetime):
        out["started_at"] = ts_machine(created_at)
        out["started_at_display"] = ts_display(created_at)
    return out


def _enrich_resolved(row: dict) -> dict:
    """Add timestamp `_display` twins to a recently-resolved stage row."""
    out = dict(row)
    for key in ("created_at", "filled_at"):
        val = row.get(key)
        if isinstance(val, datetime):
            out[key] = ts_machine(val)
            out[f"{key}_display"] = ts_display(val)
    return out


@router.get("/stages")
async def list_stages(_user: str = Depends(require_user)) -> dict:
    """Active + recently-resolved staged entries (wraps the /staged helpers)."""
    import dashboard  # deferred: keep `import api.stages` side-effect-free

    positions = await dashboard._get_all_positions()
    raw_active = await db.get_pending_stages()
    active = [dashboard._enrich_stage_for_ui(s, positions) for s in raw_active]
    resolved = await db.get_recently_resolved_stages(50)
    return {
        "active": [
            _enrich_active(enriched, raw)
            for enriched, raw in zip(active, raw_active)
        ],
        "resolved": [_enrich_resolved(r) for r in resolved],
    }
