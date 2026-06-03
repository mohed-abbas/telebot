"""api/actions.py — /api/v2 live-money mutation routes (Phase 08 Plan 04).

Ports every dashboard mutation into a structured JSON envelope (API-02) and
rebuilds partial-close as an idempotent, absolute-volume operation (API-05):

  POST /positions/{account}/{ticket}/close          (dashboard.py:1081-1100)
  POST /positions/{account}/{ticket}/levels         (dashboard.py:1173-1247)
  POST /positions/{account}/{ticket}/close-partial  (dashboard.py:1250-1298 — REWRITTEN)
  POST /emergency/close                             (dashboard.py:1333-1342)
  POST /emergency/resume                            (dashboard.py:1345-1354)

GET /trading-status is owned by api/meta.py (Plan 03) — NOT redefined here, to
avoid a duplicate route registration.

The broker/DB CALLS are ported VERBATIM from dashboard.py; only the response
shape changes (JSON envelope, never `_render_toast_oob` HTML). The DEPRECATED
modify-sl / modify-tp endpoints (dashboard.py:1103-1160) are NOT ported.

Money-safety core (API-05): partial-close switches percent→absolute close_volume
(eliminating the percent-of-current double-fire / 75% trap) and gains the
Postgres `request_id` idempotency guard — a legitimate retry replays the cached
200 and never re-hits the broker (D-09/D-10/D-11).

Every POST carries `Depends(verify_csrf_token)` + `Depends(require_user)` so it
inherits the D-16 CSRF gate (403 without a valid X-CSRF-Token).

DEFERRED-IMPORT INVARIANT (08-PATTERNS Pitfall 6 / Plans 01-03): `dashboard` is
imported INSIDE handler bodies only — a top-level `import dashboard` chains
through `config._load_settings()` and raises SystemExit at import time when
DATABASE_URL is unset, crashing pytest collection of the whole suite. `db`,
`api.deps`, `api.idempotency`, `api.formatting`, and `api.schemas` are all
side-effect-free at module top and safe to import eagerly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import db

from api import idempotency
from api.deps import require_executor, require_user, verify_csrf_token
from api.formatting import volume_display
from api.schemas import CloseLevelsIn, EmergencyResult, MutationResult, PartialCloseIn

router = APIRouter()


def _connector_or_404(account: str):
    """Resolve the live connector for `account` or raise 404.

    Mirrors dashboard.py:1055-1057 (503 if executor absent via require_executor,
    404 if the account has no connector). require_executor() defers its dashboard
    import, keeping this module's top level side-effect-free.
    """
    executor = require_executor()
    connector = executor.tm.connectors.get(account)
    if connector is None:
        raise HTTPException(status_code=404, detail=f"Account {account} not found")
    return connector


# ─── Full close (ports dashboard.py:1081-1100) ───────────────────────────────


@router.post("/positions/{account}/{ticket}/close", response_model=MutationResult)
async def close(
    account: str,
    ticket: int,
    _csrf: None = Depends(verify_csrf_token),
    _user: str = Depends(require_user),
) -> MutationResult:
    """Close a position fully.

    Ports the connector lookup + `close_position(ticket)` + `db.update_trade_close`
    verbatim (dashboard.py:1087-1093). Returns a JSON envelope instead of the
    green/red HTML span; the toast notification side-effect is dropped (the SPA
    renders its own toast from the JSON result).
    """
    connector = _connector_or_404(account)
    result = await connector.close_position(ticket)
    if result.success:
        # Verbatim DB write (dashboard.py:1093): pnl 0.0 placeholder, close price.
        await db.update_trade_close(ticket, account, 0.0, result.price)
    return MutationResult(
        ok=result.success,
        success=result.success,
        error=None if result.success else (result.error or "close failed"),
    )


# ─── Modify levels (ports dashboard.py:1173-1247) ────────────────────────────


@router.post("/positions/{account}/{ticket}/levels")
async def levels(
    account: str,
    ticket: int,
    body: CloseLevelsIn,
    _csrf: None = Depends(verify_csrf_token),
    _user: str = Depends(require_user),
) -> dict:
    """Modify SL and/or TP atomically (the edit-levels modal action).

    Ports the position lookup + `_changed` diff + atomic
    `modify_position(ticket, sl=, tp=)` from dashboard.py:1191-1235 unchanged;
    the modal/toast HTML at :1198,1233,1247 becomes a structured JSON envelope.
    `changed` reports which fields were actually sent to the broker (data, not
    HTML). A no-op (nothing changed) returns ok with an empty `changed`.
    """
    connector = _connector_or_404(account)
    positions = await connector.get_positions()
    pos = next((p for p in positions if p.ticket == ticket), None)
    if pos is None:
        raise HTTPException(status_code=404, detail="Position no longer open")

    new_sl = body.sl
    new_tp = body.tp
    if new_sl is not None and new_sl <= 0:
        raise HTTPException(status_code=422, detail="SL must be > 0")
    if new_tp is not None and new_tp <= 0:
        raise HTTPException(status_code=422, detail="TP must be > 0")

    # Only send values that actually changed; treat tiny float noise as unchanged
    # (verbatim _changed diff, dashboard.py:1221-1226).
    def _changed(new: float | None, current: float | None) -> bool:
        if new is None:
            return False
        if current is None:
            return True
        return abs(new - current) > 1e-9

    sl_to_send = new_sl if _changed(new_sl, pos.sl) else None
    tp_to_send = new_tp if _changed(new_tp, pos.tp) else None

    if sl_to_send is None and tp_to_send is None:
        # Nothing changed — success envelope, empty change set (was an info toast).
        return {"ok": True, "success": True, "changed": {}, "error": None}

    result = await connector.modify_position(ticket, sl=sl_to_send, tp=tp_to_send)
    if not result.success:
        return {
            "ok": False,
            "success": False,
            "changed": {},
            "error": result.error or "Broker rejected modify",
        }

    changed: dict[str, float] = {}
    if sl_to_send is not None:
        changed["sl"] = sl_to_send
    if tp_to_send is not None:
        changed["tp"] = tp_to_send
    return {"ok": True, "success": True, "changed": changed, "error": None}


# ─── Idempotent partial close (REWRITES dashboard.py:1250-1298 — API-05) ──────


@router.post("/positions/{account}/{ticket}/close-partial")
async def close_partial(
    account: str,
    ticket: int,
    body: PartialCloseIn,
    _csrf: None = Depends(verify_csrf_token),
    _user: str = Depends(require_user),
) -> dict:
    """Partial-close an absolute lot volume, idempotent per request_id.

    Replaces the percent-of-current math (dashboard.py:1283, the 75% double-fire
    trap) with an absolute `close_volume` (D-09) and a Postgres `request_id`
    guard (D-10/D-11):

      * `cv = round(close_volume, 2)` (symbol lot step); `0 < cv < pos.volume`
        else 422 (out of range, D-10).
      * idempotency.check(request_id, account, ticket, cv):
          new      -> execute `close_position(ticket, volume=cv)` (absolute, D-09),
                      store the payload, return it.
          replay   -> return the cached 200; the broker is NOT called again.
          conflict -> 409 (request_id reused with different params, D-11).

    The connector already accepts an absolute volume (mt5_connector.py:742) — no
    connector edit. CSRF-guarded like every mutation.
    """
    connector = _connector_or_404(account)

    positions = await connector.get_positions()
    pos = next((p for p in positions if p.ticket == ticket), None)
    if pos is None:
        raise HTTPException(status_code=404, detail="Position no longer open")

    cv = round(body.close_volume, 2)  # symbol lot step (2dp)
    if not (0 < cv < pos.volume):
        raise HTTPException(status_code=422, detail="close_volume out of range")

    # Idempotency gate (insert-first; closes the check-then-act race).
    state, cached = await idempotency.check(body.request_id, account, ticket, cv)
    if state == "replay":
        return cached  # cached 200 — broker untouched (D-11)
    if state == "conflict":
        raise HTTPException(
            status_code=409, detail="request_id reused with different params"
        )

    # state == "new": execute the absolute-volume close exactly once.
    result = await connector.close_position(ticket, volume=cv)
    payload = {
        "ok": result.success,
        "success": result.success,
        "closed_volume": cv,
        "closed_volume_display": volume_display(cv),
        "error": None if result.success else (result.error or "partial close failed"),
    }
    await idempotency.store(body.request_id, account, ticket, cv, payload)
    return payload


# ─── Kill switch (ports dashboard.py:1333-1354) ──────────────────────────────


@router.post("/emergency/close", response_model=EmergencyResult)
async def emergency_close(
    _csrf: None = Depends(verify_csrf_token),
    _user: str = Depends(require_user),
) -> EmergencyResult:
    """Execute the kill switch: close all positions, cancel all orders, pause.

    Ports `await executor.emergency_close()` (dashboard.py:1339) verbatim and the
    kill-switch notification (dashboard.py:1340-1341); models the returned
    `results` dict as a JSON envelope instead of returning the bare dict.
    """
    import dashboard  # deferred — keep `import api.actions` side-effect-free

    executor = require_executor()
    results = await executor.emergency_close()

    notifier = dashboard.get_notifier()
    if notifier is not None:
        await notifier.notify_kill_switch(activated=True)

    return EmergencyResult(results=results, ok=True)


@router.post("/emergency/resume")
async def emergency_resume(
    _csrf: None = Depends(verify_csrf_token),
    _user: str = Depends(require_user),
) -> dict:
    """Re-enable trading after the kill switch.

    Ports `executor.resume_trading()` (sync, dashboard.py:1351) + the resume
    notification verbatim; returns the same `{"status": "resumed"}` shape.
    """
    import dashboard  # deferred — keep `import api.actions` side-effect-free

    executor = require_executor()
    executor.resume_trading()

    notifier = dashboard.get_notifier()
    if notifier is not None:
        await notifier.notify_kill_switch(activated=False)

    return {"status": "resumed"}
