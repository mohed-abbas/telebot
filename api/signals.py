"""api/signals.py — signals read route (Phase 08 Plan 03).

Wraps db.get_recent_signals(100) VERBATIM and adds the D-05 timestamp twin
(ts_machine ISO-8601-with-offset raw + ts_display absolute UTC) via
api/formatting.py. Session-gated via require_user.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

import db
from api.deps import require_user
from api.formatting import ts_display, ts_machine
from api.schemas import Signal

router = APIRouter()


def _enrich_signal(row: dict) -> Signal:
    """Map a signals row to a Signal with a dual-value received_at timestamp."""
    ts = row.get("timestamp")
    received_at = ts_machine(ts) if isinstance(ts, datetime) else None
    received_at_display = ts_display(ts) if isinstance(ts, datetime) else None
    return Signal(
        id=row["id"],
        raw_text=row.get("raw_text") or "",
        signal_type=row.get("signal_type") or "",
        symbol=row.get("symbol"),
        direction=row.get("direction"),
        action_taken=row.get("action_taken"),
        received_at=received_at,
        received_at_display=received_at_display,
    )


@router.get("/signals", response_model=list[Signal])
async def list_signals(_user: str = Depends(require_user)) -> list[Signal]:
    """Recent signals (wraps db.get_recent_signals(100))."""
    rows = await db.get_recent_signals(100)
    return [_enrich_signal(r) for r in rows]
