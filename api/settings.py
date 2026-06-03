"""api/settings.py — /api/v2/settings JSON contract (Phase 08 Plan 05, API-02).

Ports the settings surface (dashboard.py:744-946) into /api/v2 as JSON:

  GET  /settings/{account}            -> SettingsView (effective + audit timeline)
  POST /settings/{account}/validate   -> {valid, errors, diff, dry_run_text}
  POST /settings/{account}            -> MutationResult (confirm: persist changes)
  POST /settings/{account}/revert     -> MutationResult (invert the latest change)

The server-side hard-cap validator `validate_settings_form` (dashboard.py:664)
is the authoritative gate and is PORTED VERBATIM (call-only — never re-implemented
here). Only the RESPONSE shape changes (JSON, not the HTML confirm modal / 422
partial) and the request BODY (a JSON Pydantic body, not `dict(await request.form())`).
The SPA's zod mirror (Phase 11) is defense-in-depth ON TOP of this, never a
replacement (T-08-18).

DEFERRED-IMPORT INVARIANT (Plans 01-03 lesson, see api/auth.py / api/deps.py):
`import api.settings` MUST be side-effect-free. A top-level `import dashboard`
(or `from dashboard import ...`) chains through `config._load_settings()` and
raises SystemExit at import time when DATABASE_URL is unset, crashing pytest
collection of the WHOLE suite (api/router.py eagerly imports every resource
module). Therefore every `dashboard` access below is DEFERRED into a handler
body. `db` is side-effect-free and safe at module top; the settings store is
reached via the api.deps accessor `require_settings_store` (also deferred).

CSRF: validate/confirm/revert are state-changing POSTs guarded by
verify_csrf_token via the `_verify_csrf` lazy proxy — 403 without a matching
X-CSRF-Token (T-08-19, the D-16 gate generalises here).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

import db

from api.schemas import (
    MutationResult,
    SettingsConfirmIn,
    SettingsRevertIn,
    SettingsValidateIn,
    SettingsValidateResult,
    SettingsView,
)

router = APIRouter()


def _verify_csrf(request: Request) -> None:
    """Lazy proxy to api.deps.verify_csrf_token (avoids eager dashboard import).

    Mirrors api/auth.py::_verify_csrf — used as the route dependency so the
    decorator does NOT eager-import api.deps (which top-level imports dashboard)
    at api/router.py collection time.
    """
    from api.deps import verify_csrf_token

    verify_csrf_token(request)


def _require_user(request: Request) -> str:
    """Lazy proxy to api.deps.require_user (401 if no session)."""
    from api.deps import require_user

    return require_user(request)


def _require_store():
    """Lazy proxy to api.deps.require_settings_store (503 if uninitialised)."""
    from api.deps import require_settings_store

    return require_settings_store()


# ─── helpers ─────────────────────────────────────────────────────────────────

# The persisted settings fields validate_settings_form parses + caps. Used to
# project the effective AccountSettings dataclass into the JSON `values` dict.
_SETTINGS_FIELDS = (
    "risk_mode",
    "risk_value",
    "max_stages",
    "default_sl_pips",
    "max_daily_trades",
    "max_open_trades",
    "max_lot_size",
)


def _effective_values(current) -> dict:
    """Project the effective AccountSettings dataclass into a plain JSON dict."""
    return {field: getattr(current, field) for field in _SETTINGS_FIELDS}


def _audit_timeline(rows: list[dict]) -> list[dict]:
    """Serialise settings_audit rows for JSON, adding D-06/D-07 timestamp twins.

    Each row carries id/field/old_value/new_value/actor plus a machine
    (`timestamp`, ISO-8601 + UTC offset) and display (`timestamp_display`,
    'YYYY-MM-DD HH:MM:SS UTC') timestamp routed through api/formatting.py — the
    single source of time formatting (never inline a strftime in a route).
    """
    from api.formatting import ts_display, ts_machine

    out: list[dict] = []
    for r in rows:
        ts = r.get("timestamp")
        out.append(
            {
                "id": r.get("id"),
                "account_name": r.get("account_name"),
                "field": r.get("field"),
                "old_value": r.get("old_value"),
                "new_value": r.get("new_value"),
                "actor": r.get("actor"),
                "timestamp": ts_machine(ts) if ts is not None else None,
                "timestamp_display": ts_display(ts) if ts is not None else None,
            }
        )
    return out


def _validate(form: dict, max_lot_size: float):
    """Call the ported-verbatim dashboard validator (deferred import)."""
    from dashboard import validate_settings_form

    return validate_settings_form(form, max_lot_size=max_lot_size)


def _compute_diff(parsed: dict, current) -> list[dict]:
    """Changed-field diff vs the effective settings (dashboard.py:818-822 shape)."""
    diff: list[dict] = []
    for field, new_val in parsed.items():
        old_val = getattr(current, field)
        if str(old_val) != str(new_val):
            diff.append({"field": field, "old": old_val, "new": new_val})
    return diff


# ─── GET effective settings + audit ──────────────────────────────────────────


@router.get("/settings/{account_name}", response_model=SettingsView)
async def get_settings(account_name: str, user: str = Depends(_require_user)):
    """Effective settings + the audit timeline for one account (JSON).

    503 if the settings store is uninitialised; 404 for an unknown account
    (the 503/404 guards are ported verbatim from dashboard.py:749-755).
    """
    store = _require_store()  # 503 if None (dashboard.py:749-750)
    try:
        current = store.effective(account_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown account: {account_name}")

    audit_rows = await db.get_settings_audit(account_name, limit=50)
    return SettingsView(
        account=account_name,
        values=_effective_values(current),
        audit=_audit_timeline(audit_rows),
    )


# ─── POST validate (server hard caps -> JSON, not an HTML modal) ──────────────


@router.post(
    "/settings/{account_name}/validate",
    response_model=SettingsValidateResult,
    dependencies=[Depends(_verify_csrf)],
)
async def validate_settings(
    account_name: str, body: SettingsValidateIn, user: str = Depends(_require_user),
):
    """Validate proposed settings against server hard caps; return JSON.

    Ports the dashboard.py:781-840 validation core verbatim — only the response
    shape changes to `{valid, errors, diff, dry_run_text}` JSON (NEVER the HTML
    confirm modal or the 422 partial). The form-dict input becomes the
    SettingsValidateIn JSON body's `values` dict, the exact shape
    validate_settings_form expects (T-08-18 server-side hard caps stay here).
    """
    store = _require_store()  # 503 if None (dashboard.py:749-750)
    try:
        current = store.effective(account_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown account: {account_name}")

    max_lot_size = float(getattr(current, "max_lot_size", 1.0) or 1.0)

    # OQ2: JSON body in, not form. `values` is the same dict shape the legacy
    # `dict(await request.form())` produced — validate_settings_form is agnostic.
    parsed, errors = _validate(dict(body.values), max_lot_size=max_lot_size)

    if errors:
        # JSON, NOT the HTML 422 partial (the deliberate contrast to dashboard.py:803).
        return SettingsValidateResult(
            valid=False,
            errors={e.field: e.message for e in errors},
        )

    diff = _compute_diff(parsed, current)
    # Dry-run preview (dashboard.py:829 _compute_dry_run, deferred import).
    from dashboard import _compute_dry_run

    dry_run = _compute_dry_run(parsed, current) if diff else "No changes to save."
    return SettingsValidateResult(
        valid=True,
        errors={},
        diff=diff,
        dry_run_text=dry_run,
    )


# ─── POST confirm (persist per changed field) ─────────────────────────────────


@router.post(
    "/settings/{account_name}",
    response_model=MutationResult,
    dependencies=[Depends(_verify_csrf)],
)
async def confirm_settings(
    account_name: str, body: SettingsConfirmIn, user: str = Depends(_require_user),
):
    """Persist validated settings via SettingsStore.update (ports dashboard.py:843-901).

    Re-validates server-side (never trust the client echo, T-08-18) then applies
    each changed field through `store.update` — which writes account_settings +
    a settings_audit row atomically (D-29 / T-08-20). Returns a JSON envelope.
    """
    store = _require_store()  # 503 if None
    try:
        current = store.effective(account_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown account: {account_name}")

    max_lot_size = float(getattr(current, "max_lot_size", 1.0) or 1.0)
    parsed, errors = _validate(dict(body.values), max_lot_size=max_lot_size)
    if errors:
        # Server cap re-breach on confirm -> reject (dashboard.py:861-862).
        raise HTTPException(status_code=422, detail="Re-validation failed")

    # Apply each changed field; store.update writes setting + audit atomically
    # (dashboard.py:866-871 loop ported verbatim).
    changed: list[str] = []
    for field, new_val in parsed.items():
        current = store.effective(account_name)
        if str(getattr(current, field)) != str(new_val):
            changed.append(field)
            await store.update(account_name, field, new_val, actor=user)

    return MutationResult(ok=True, success=True)


# ─── POST revert (invert the latest persisted change) ─────────────────────────


@router.post(
    "/settings/{account_name}/revert",
    response_model=MutationResult,
    dependencies=[Depends(_verify_csrf)],
)
async def revert_settings(
    account_name: str, body: SettingsRevertIn, user: str = Depends(_require_user),
):
    """Invert the latest persisted change for the account (ports dashboard.py:872-914).

    The legacy HTML handler re-opened the confirm modal pre-populated with the
    inverted diff; the JSON contract performs the inverted-diff PERSIST directly:
    restore the most-recent audit row's `old_value` for its field via
    store.update, which records the revert as a NEW audit entry (D-28 / T-08-20).
    Returns a JSON envelope. 404 if there is nothing to revert.
    """
    store = _require_store()  # 503 if None
    try:
        current = store.effective(account_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown account: {account_name}")

    rows = await db.get_settings_audit(account_name, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="Nothing to revert")

    row = rows[0]
    field = row["field"]
    old_value_str = row["old_value"]

    # Coerce the stored string back to the field's runtime type for the cap
    # re-validation + store write (audit stores values as TEXT).
    full = {f: getattr(current, f) for f in _SETTINGS_FIELDS}
    full[field] = old_value_str
    parsed, errors = _validate(
        {k: str(v) for k, v in full.items()},
        max_lot_size=float(getattr(current, "max_lot_size", 1.0) or 1.0),
    )
    if errors:
        # A prior value should always re-validate; guard defensively.
        raise HTTPException(status_code=422, detail="Revert failed re-validation")

    revert_val = parsed[field]
    if str(getattr(current, field)) != str(revert_val):
        await store.update(account_name, field, revert_val, actor=user)

    return MutationResult(ok=True, success=True)
