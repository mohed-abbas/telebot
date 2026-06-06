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
from api.formatting import price_display, ts_display, ts_machine
from api.schemas import Signal

router = APIRouter()


def _enrich_signal(row: dict) -> Signal:
    """Map a signals row to a Signal with a dual-value received_at timestamp."""
    ts = row.get("timestamp")
    received_at = ts_machine(ts) if isinstance(ts, datetime) else None
    received_at_display = ts_display(ts) if isinstance(ts, datetime) else None
    symbol = row.get("symbol")
    sym = symbol or ""
    entry_zone_low = row.get("entry_zone_low")
    entry_zone_high = row.get("entry_zone_high")
    sl = row.get("sl")
    tp = row.get("tp")
    return Signal(
        id=row["id"],
        raw_text=row.get("raw_text") or "",
        signal_type=row.get("signal_type") or "",
        symbol=symbol,
        direction=row.get("direction"),
        action_taken=row.get("action_taken"),
        received_at=received_at,
        received_at_display=received_at_display,
        # D-12 widened legacy parity (price fields get _display twins).
        entry_zone_low=entry_zone_low,
        entry_zone_low_display=(
            price_display(sym, entry_zone_low) if entry_zone_low is not None else None
        ),
        entry_zone_high=entry_zone_high,
        entry_zone_high_display=(
            price_display(sym, entry_zone_high) if entry_zone_high is not None else None
        ),
        sl=sl,
        sl_display=price_display(sym, sl) if sl is not None else None,
        tp=tp,
        tp_display=price_display(sym, tp) if tp is not None else None,
        details=row.get("details"),  # bare
        source_name=row.get("source_name"),  # bare
    )


@router.get("/signals", response_model=list[Signal])
async def list_signals(_user: str = Depends(require_user)) -> list[Signal]:
    """Recent signals (wraps db.get_recent_signals(100))."""
    rows = await db.get_recent_signals(100)
    return [_enrich_signal(r) for r in rows]
