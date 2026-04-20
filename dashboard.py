"""Web dashboard for trade monitoring and management.

FastAPI + Jinja2 + HTMX + SSE.
Provides real-time positions, P&L, trade management, and audit logs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets as _secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import db
from config import settings as app_settings

logger = logging.getLogger(__name__)

# These get set by init_dashboard() from bot.py
_executor = None
_notifier = None
_settings = None
_daily_limit_warned: set[str] = set()  # Account names that already received 80% warning today

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ─── Asset manifest (Phase 5 UI-04) ──────────────────────────────────────────
# Resolves logical CSS names (e.g. "app.css") to content-hashed filenames built
# by scripts/build_css.sh. Loaded once at module import; falls back to the
# logical name when the manifest is absent (dev workflow before first build).
_asset_manifest: dict[str, str] = {}


def _load_manifest() -> None:
    global _asset_manifest
    path = BASE_DIR / "static" / "css" / "manifest.json"
    if path.exists():
        try:
            _asset_manifest = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            logger.warning("manifest.json unreadable: %s", exc)
            _asset_manifest = {}


_load_manifest()


def asset_url(logical_name: str) -> str:
    """Jinja global: resolves logical css name to hashed filename via manifest.
    Falls back to the logical name if manifest missing (dev workflow)."""
    hashed = _asset_manifest.get(logical_name, logical_name)
    return f"/static/css/{hashed}"


templates.env.globals["asset_url"] = asset_url


def init_dashboard(executor, notifier, settings):
    """Called from bot.py to inject dependencies."""
    global _executor, _notifier, _settings
    _executor = executor
    _notifier = notifier
    _settings = settings


def _verify_auth(request: Request) -> str:
    """Session-based auth (AUTH-01 consumer contract).

    Page routes: HTTPException(303, Location=/login?next=…) to redirect.
    HTMX / API routes: HTTPException(401) so HTMX shows an inline error.

    Signature preserved: still returns the username string so the existing
    18+ `user: str = Depends(_verify_auth)` call sites compile unchanged.
    """
    user = request.session.get("user")
    if user:
        return user

    if request.headers.get("hx-request") or request.url.path.startswith("/api/"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        )

    next_path = quote(
        request.url.path
        + ("?" + request.url.query if request.url.query else "")
    )
    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": f"/login?next={next_path}"},
    )


async def _verify_csrf(request: Request):
    """CSRF protection: reject state-changing requests without a custom header.

    HTMX sends HX-Request automatically. Cross-origin forms cannot set custom headers.
    """
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        if not request.headers.get("hx-request"):
            raise HTTPException(status_code=403, detail="Forbidden")


# ═══════════════════════════════════════════════════════════════════════
# AUTHENTICATION: /login, /logout (Phase 5 Plan 04)
# ═══════════════════════════════════════════════════════════════════════

CSRF_COOKIE = "telebot_login_csrf"
CSRF_COOKIE_MAX_AGE = 15 * 60  # 15 minutes (form validity window)
_password_hasher = PasswordHasher()  # RFC 9106 defaults


def _client_ip(request: Request) -> str:
    """Prefer X-Real-IP (set by nginx line 36 of telebot.conf); fallback to conn peer."""
    xri = request.headers.get("x-real-ip", "").strip()
    if xri:
        return xri
    return request.client.host if request.client else "unknown"


def _render_login(
    request: Request,
    csrf_token: str,
    next_path: str = "/overview",
    error: str | None = None,
    status_code: int = 200,
):
    """Render login.html with a fresh CSRF cookie (path=/login — T-5-10)."""
    resp = templates.TemplateResponse("login.html", {
        "request": request,
        "csrf_token": csrf_token,
        "next_path": next_path,
        "error": error,
    }, status_code=status_code)
    resp.set_cookie(
        CSRF_COOKIE, csrf_token,
        max_age=CSRF_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=app_settings.session_cookie_secure,
        path="/login",
    )
    return resp


@asynccontextmanager
async def lifespan(app: FastAPI):
    """ASGI lifespan: manages startup/shutdown lifecycle."""
    logger.info("Dashboard ASGI lifespan: startup")
    yield
    logger.info("Dashboard ASGI lifespan: shutdown")


app = FastAPI(title="Telebot Dashboard", docs_url=None, redoc_url=None, lifespan=lifespan)

# Phase 5 AUTH-03: SessionMiddleware — must be added before first request.
# D-11: 30-day cookie. Pitfall 3: https_only config-driven for dev/tests.
app.add_middleware(
    SessionMiddleware,
    secret_key=app_settings.session_secret,
    session_cookie="telebot_session",
    max_age=30 * 24 * 60 * 60,        # 30 days (D-11)
    same_site="lax",
    https_only=app_settings.session_cookie_secure,
    path="/",
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/health")
async def health():
    """Health check for container orchestration — no auth required."""
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════
# AUTH ROUTES (/login + /logout)
# ═══════════════════════════════════════════════════════════════════════


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    """Render the login form with a fresh CSRF token. Skip the form if already authenticated."""
    if request.session.get("user"):
        return RedirectResponse(
            url=request.query_params.get("next", "/overview"),
            status_code=303,
        )
    csrf_token = _secrets.token_urlsafe(32)
    next_path = request.query_params.get("next", "/overview")
    return _render_login(request, csrf_token, next_path=next_path)


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    password: str = Form(...),
    csrf_token: str = Form(...),
    next_path: str = Form("/overview"),
):
    """Validate CSRF → check rate-limit → argon2 verify → set session."""
    # 1. Double-submit cookie CSRF (AUTH-04, D-14)
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    if not cookie_token or not _secrets.compare_digest(cookie_token, csrf_token):
        fresh = _secrets.token_urlsafe(32)
        return _render_login(
            request, fresh, next_path=next_path,
            error="Session expired — please try again.",
            status_code=400,
        )

    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")

    # 2. App-level rate limit (AUTH-05, D-17) — before argon2 CPU cost
    fail_count = await db.get_failed_login_count(ip, minutes=15)
    if fail_count >= 5:
        fresh = _secrets.token_urlsafe(32)
        return _render_login(
            request, fresh, next_path=next_path,
            error="Too many failed attempts. Try again in 15 minutes.",
            status_code=429,
        )

    # 3. argon2 verify (constant-time, D-13)
    ok = False
    try:
        _password_hasher.verify(app_settings.dashboard_pass_hash, password)
        ok = True
    except VerifyMismatchError:
        ok = False
    except (InvalidHashError, VerificationError):
        logger.error(
            "Stored DASHBOARD_PASS_HASH is malformed — regenerate via scripts/hash_password.py"
        )
        ok = False

    if not ok:
        await db.log_failed_login(ip, user_agent=ua)
        fresh = _secrets.token_urlsafe(32)
        return _render_login(
            request, fresh, next_path=next_path,
            error="Invalid credentials.",
            status_code=401,
        )

    # 4. Success: set session, clear counter, redirect
    request.session["user"] = "admin"  # D-30 actor default
    await db.clear_failed_logins(ip)

    response = RedirectResponse(url=next_path, status_code=303)
    response.delete_cookie(CSRF_COOKIE, path="/login")
    if request.headers.get("hx-request"):
        response.headers["HX-Redirect"] = next_path
    return response


@app.post("/logout")
@app.get("/logout")
async def logout(request: Request):
    """AUTH-06: clear session, redirect to /login. Accepts GET for plain-link logout."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# ═══════════════════════════════════════════════════════════════════════
# PAGES
# ═══════════════════════════════════════════════════════════════════════


@app.get("/", response_class=HTMLResponse)
async def root(request: Request, user: str = Depends(_verify_auth)):
    return RedirectResponse(url="/overview")


@app.get("/overview", response_class=HTMLResponse)
async def overview(request: Request, user: str = Depends(_verify_auth)):
    accounts_data = await _get_accounts_overview()
    # D-32: initial server-render of the pending-stages top-5 card (SSE then
    # takes over). If positions lookup fails, fall back to empty list — the
    # partial's empty-state renders correctly and SSE populates on first tick.
    try:
        positions = await _get_all_positions()
        raw_stages = await db.get_pending_stages(limit=5)
        stages = [_enrich_stage_for_ui(s, positions) for s in raw_stages]
    except Exception:  # pragma: no cover — defensive for overview render
        stages = []
    return templates.TemplateResponse("overview.html", {
        "request": request,
        "accounts": accounts_data,
        "trading_enabled": _settings.trading_enabled if _settings else False,
        "dry_run": _settings.trading_dry_run if _settings else True,
        "trading_paused": _executor._trading_paused if _executor else False,
        "stages": stages,
        "page": "overview",
        "page_title": "Overview",
    })


@app.get("/positions", response_class=HTMLResponse)
async def positions_page(request: Request, user: str = Depends(_verify_auth)):
    positions = await _get_all_positions()
    return templates.TemplateResponse("positions.html", {
        "request": request,
        "positions": positions,
        "page": "positions",
        "page_title": "Open Positions",
    })


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, user: str = Depends(_verify_auth)):
    trades = await db.get_recent_trades(100)
    return templates.TemplateResponse("history.html", {
        "request": request,
        "trades": trades,
        "page": "history",
        "page_title": "Trade History",
    })


@app.get("/signals", response_class=HTMLResponse)
async def signals_page(request: Request, user: str = Depends(_verify_auth)):
    signals = await db.get_recent_signals(100)
    return templates.TemplateResponse("signals.html", {
        "request": request,
        "signals": signals,
        "page": "signals",
        "page_title": "Signal Log",
    })


# ─── STAGE-08: pending-stages observability (D-32..D-36) ──────────────────


_RESOLVED_STATUS_LABELS: dict[str, str] = {
    "cancelled_by_kill_switch": "Kill-switch drain",
    "cancelled_stage1_closed": "Stage 1 exited",
    "abandoned_reconnect": "Abandoned (reconnect)",
    "failed": "Failed",
    "capped": "Capped",
    "filled": "Filled",
}


def _enrich_stage_for_ui(stage: dict, positions: list[dict]) -> dict:
    """D-34: transform a staged_entries row into the UI display shape.

    `positions` is the list produced by `_get_all_positions()` (keys:
    `account`, `symbol`, `direction`, `open_price`, `profit`). No live-price
    field is carried today — `current_price` stays None and the template
    renders an em-dash. Live-price wiring is deferred (UI-SPEC TODO phase 7).
    """
    snapshot = stage.get("snapshot_settings") or {}
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except (TypeError, ValueError):
            snapshot = {}
    total = snapshot.get("max_stages", stage["stage_number"])

    # Live-price lookup against the open-positions list (same broker).
    # _get_all_positions returns keys `account` + `symbol` (no `account_name`
    # and no `price_current`/`current_price`). Match on both, accept future
    # price keys if a later plan adds them.
    current_price = None
    for p in positions:
        if (
            p.get("symbol") == stage["symbol"]
            and p.get("account") == stage["account_name"]
        ):
            current_price = (
                p.get("price_current")
                or p.get("current_price")
                or None
            )
            break

    # Distance-to-next-band sub-line.
    if current_price is not None:
        band_low = stage["band_low"]
        band_high = stage["band_high"]
        direction = stage["direction"]
        if direction == "buy":
            # trigger edge is band_high; positive = still above the band
            distance_pips = (current_price - band_high) * 100
        else:
            distance_pips = (band_low - current_price) * 100
        if current_price >= stage["band_low"] and current_price <= stage["band_high"]:
            distance_str = "inside band"
        elif distance_pips >= 0:
            sign = "+" if direction == "buy" else "−"
            distance_str = f"{sign}{distance_pips:.1f} pips to next band"
        else:
            # Already past the band (crossed but not yet filled this tick).
            sign = "−" if direction == "buy" else "+"
            distance_str = f"{sign}{abs(distance_pips):.1f} pips to next band"
    else:
        distance_str = "—"

    # Elapsed mm:ss or hh:mm:ss.
    created_at = stage["created_at"]
    now = datetime.now(timezone.utc)
    elapsed_seconds = max(0, int((now - created_at).total_seconds()))
    if elapsed_seconds < 3600:
        elapsed_str = f"{elapsed_seconds // 60:02d}:{elapsed_seconds % 60:02d}"
    else:
        h = elapsed_seconds // 3600
        m = (elapsed_seconds % 3600) // 60
        s = elapsed_seconds % 60
        elapsed_str = f"{h:02d}:{m:02d}:{s:02d}"

    return {
        "account_name": stage["account_name"],
        "symbol": stage["symbol"],
        "direction": stage["direction"],
        # v1.1 approximation: show this stage's number as `filled` (= next-to-fire).
        # Precise "3 / 5" requires a grouped COUNT per signal_id; deferred to Phase 7.
        "filled": stage["stage_number"],
        "total": total,
        "band_low": stage["band_low"],
        "band_high": stage["band_high"],
        "current_price": current_price,
        "distance_str": distance_str,
        "elapsed": elapsed_str,
        "status": stage["status"],
    }


def _label_resolved_stage(r: dict) -> dict:
    """D-36: add a human-facing `status_label` to a resolved-stage row."""
    return {**r, "status_label": _RESOLVED_STATUS_LABELS.get(r["status"], r["status"])}


@app.get("/staged", response_class=HTMLResponse)
async def staged_page(request: Request, user: str = Depends(_verify_auth)):
    """D-32: full-page view of all active sequences + collapsed 'Recently resolved'."""
    positions = await _get_all_positions()
    raw_active = await db.get_pending_stages()  # no limit — all rows
    active = [_enrich_stage_for_ui(s, positions) for s in raw_active]
    resolved = await db.get_recently_resolved_stages(limit=50)
    resolved_labeled = [_label_resolved_stage(r) for r in resolved]
    return templates.TemplateResponse("staged.html", {
        "request": request,
        "active": active,
        "resolved": resolved_labeled,
        "trading_enabled": _settings.trading_enabled if _settings else False,
        "dry_run": _settings.trading_dry_run if _settings else True,
        "page": "staged",
        "page_title": "Pending Stages",
    })


@app.get("/partials/pending_stages", response_class=HTMLResponse)
async def pending_stages_partial(
    request: Request,
    all: int = 0,
    user: str = Depends(_verify_auth),
):
    """HTMX polling fallback when SSE drops (5s cadence on /staged)."""
    positions = await _get_all_positions()
    raw = await db.get_pending_stages(limit=None if all else 5)
    stages = [_enrich_stage_for_ui(s, positions) for s in raw]
    return templates.TemplateResponse("partials/pending_stages.html", {
        "request": request,
        "stages": stages,
    })


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: str = Depends(_verify_auth)):
    """SET-03: per-account tabbed settings form with audit timeline."""
    accounts_data = await _get_accounts_overview()
    store = _get_settings_store()
    settings_by_account: dict[str, object] = {}
    audit_by_account: dict[str, list[dict]] = {}
    for a in accounts_data:
        name = a["name"]
        settings_by_account[name] = store.effective(name) if store else None
        audit_by_account[name] = await db.get_settings_audit(name, limit=50)
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "accounts": accounts_data,
        "settings_by_account": settings_by_account,
        "audit_by_account": audit_by_account,
        "trading_enabled": _settings.trading_enabled if _settings else False,
        "dry_run": _settings.trading_dry_run if _settings else True,
        "page": "settings",
        "page_title": "Settings",
    })


# ─── SET-03: per-account settings form (POST handlers) ──────────────────

from dataclasses import dataclass


@dataclass
class _SettingsValidationError:
    field: str
    message: str


_SETTINGS_HARD_CAPS_INT: dict[str, tuple[int, int]] = {
    "max_stages": (1, 10),
    "default_sl_pips": (1, 500),
    "max_daily_trades": (1, 100),
}


def validate_settings_form(
    form: dict, max_lot_size: float,
) -> tuple[dict, list[_SettingsValidationError]]:
    """D-29: server-side hard-cap validator for the per-account settings form.

    Returns (parsed_values, errors). parsed_values is empty when errors is non-empty.
    Client-echo via HTML min/max attributes is cosmetic — this is authoritative.
    """
    errors: list[_SettingsValidationError] = []
    parsed: dict = {}

    risk_mode = str(form.get("risk_mode", "")).strip()
    if risk_mode not in ("percent", "fixed_lot"):
        errors.append(_SettingsValidationError(
            "risk_mode", 'Risk mode must be "percent" or "fixed_lot".'))
    else:
        parsed["risk_mode"] = risk_mode

    # risk_value — cap depends on risk_mode
    risk_value = None
    try:
        risk_value = float(form.get("risk_value", ""))
    except (ValueError, TypeError):
        errors.append(_SettingsValidationError("risk_value", "Risk value must be a number."))
    if risk_value is not None:
        if risk_value <= 0:
            errors.append(_SettingsValidationError(
                "risk_value", "Risk value must be greater than 0."))
        elif risk_mode == "percent" and risk_value > 5.0:
            errors.append(_SettingsValidationError(
                "risk_value", "risk_value must be between 0 and 5.0."))
        elif risk_mode == "fixed_lot" and risk_value > max_lot_size:
            errors.append(_SettingsValidationError(
                "risk_value", "Risk value exceeds max_lot_size for this account."))
        elif risk_mode in ("percent", "fixed_lot"):
            parsed["risk_value"] = risk_value

    # Integer hard caps
    for field, (min_v, max_v) in _SETTINGS_HARD_CAPS_INT.items():
        raw = form.get(field, "")
        try:
            v = int(raw)
        except (ValueError, TypeError):
            errors.append(_SettingsValidationError(field, f"{field} must be an integer."))
            continue
        if v < min_v or v > max_v:
            errors.append(_SettingsValidationError(
                field, f"{field} must be between {min_v} and {max_v}."))
        else:
            parsed[field] = v

    return (parsed if not errors else {}), errors


def _get_settings_store():
    """Return the live SettingsStore (attached to TradeManager in bot.py)."""
    if _executor is None:
        return None
    return getattr(_executor.tm, "settings_store", None)


def _accounts_by_name() -> dict[str, object]:
    """Return AccountConfig-by-name for lookup (max_lot_size etc.)."""
    if _executor is None:
        return {}
    return dict(getattr(_executor.tm, "accounts", {}) or {})


def _compute_dry_run(parsed: dict, current) -> str:
    """D-27: concise dry-run string rendered inside the confirmation modal."""
    risk_mode = parsed.get("risk_mode", current.risk_mode)
    risk_value = float(parsed.get("risk_value", current.risk_value))
    max_stages = int(parsed.get("max_stages", current.max_stages))
    per_stage = risk_value / max_stages if max_stages else 0.0
    if risk_mode == "percent":
        return (
            f"A typical signal would size {max_stages} stages at "
            f"{per_stage:.3f}% risk per stage."
        )
    return (
        f"A typical signal would size {max_stages} stages at "
        f"{per_stage:.3f} lots per stage (fixed_lot)."
    )


def _render_tab_partial(
    request: Request, account_name: str, errors: dict | None = None, status_code: int = 200,
):
    """Re-render the per-account settings tab partial (form + audit timeline)."""
    store = _get_settings_store()
    if store is None:
        raise HTTPException(status_code=503, detail="SettingsStore not initialised")
    try:
        s = store.effective(account_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    # Shim the overview row shape expected by the tab partial (it only reads .name)
    account_row = {"name": account_name}
    return templates.TemplateResponse(
        "partials/account_settings_tab.html",
        {
            "request": request,
            "a": account_row,
            "s": s,
            "errors": errors or {},
            "audit": None,  # filled below by caller that awaits DB
        },
        status_code=status_code,
    )


@app.post("/settings/{account_name}", response_class=HTMLResponse)
async def settings_validate(
    account_name: str, request: Request,
    user: str = Depends(_verify_auth), _csrf=Depends(_verify_csrf),
):
    """D-27/D-29: validate hard caps. On success render modal; on failure 422 partial."""
    store = _get_settings_store()
    if store is None:
        raise HTTPException(status_code=503, detail="SettingsStore not initialised")
    try:
        current = store.effective(account_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown account: {account_name}")

    max_lot_size = float(getattr(current, "max_lot_size", 1.0) or 1.0)

    form = dict(await request.form())
    parsed, errors = validate_settings_form(form, max_lot_size=max_lot_size)

    if errors:
        # Re-render the form partial with per-field red-400 messages
        audit = await db.get_settings_audit(account_name, limit=50)
        return templates.TemplateResponse(
            "partials/account_settings_tab.html",
            {
                "request": request,
                "a": {"name": account_name},
                "s": current,
                "errors": {e.field: e.message for e in errors},
                "audit": audit,
            },
            status_code=422,
        )

    # Compute diff vs current effective settings
    diff: list[dict] = []
    for field, new_val in parsed.items():
        old_val = getattr(current, field)
        if str(old_val) != str(new_val):
            diff.append({"field": field, "old": old_val, "new": new_val})

    if not diff:
        return HTMLResponse(
            '<div class="text-xs text-slate-500">No changes to save.</div>'
        )

    dry_run = _compute_dry_run(parsed, current)
    return templates.TemplateResponse(
        "partials/settings_confirm_modal.html",
        {
            "request": request,
            "account_name": account_name,
            "diff": diff,
            "dry_run": dry_run,
            "pending_values": parsed,
            "is_revert": False,
        },
    )


@app.post("/settings/{account_name}/confirm", response_class=HTMLResponse)
async def settings_confirm(
    account_name: str, request: Request,
    user: str = Depends(_verify_auth), _csrf=Depends(_verify_csrf),
):
    """D-27: persist validated settings + audit row via SettingsStore.update (atomic)."""
    store = _get_settings_store()
    if store is None:
        raise HTTPException(status_code=503, detail="SettingsStore not initialised")
    try:
        current = store.effective(account_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown account: {account_name}")

    max_lot_size = float(getattr(current, "max_lot_size", 1.0) or 1.0)
    form = dict(await request.form())
    parsed, errors = validate_settings_form(form, max_lot_size=max_lot_size)
    if errors:
        raise HTTPException(status_code=422, detail="Re-validation failed")

    # Apply each changed field; SettingsStore.update writes settings + audit atomically.
    for field, new_val in parsed.items():
        current = store.effective(account_name)
        if str(getattr(current, field)) != str(new_val):
            await store.update(account_name, field, new_val, actor=user)

    fresh = store.effective(account_name)
    audit = await db.get_settings_audit(account_name, limit=50)
    return templates.TemplateResponse(
        "partials/account_settings_tab.html",
        {
            "request": request,
            "a": {"name": account_name},
            "s": fresh,
            "errors": {},
            "audit": audit,
        },
    )


@app.post("/settings/{account_name}/revert", response_class=HTMLResponse)
async def settings_revert(
    account_name: str, audit_id: int, request: Request,
    user: str = Depends(_verify_auth), _csrf=Depends(_verify_csrf),
):
    """D-28: re-open the two-step modal pre-populated with the inverted diff."""
    row = await db.get_settings_audit_row(audit_id)
    if row is None or row["account_name"] != account_name:
        raise HTTPException(status_code=404, detail="Audit row not found")

    store = _get_settings_store()
    if store is None:
        raise HTTPException(status_code=503, detail="SettingsStore not initialised")
    try:
        current = store.effective(account_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown account: {account_name}")

    field = row["field"]
    old_value_str = row["old_value"]
    current_val = getattr(current, field)

    diff = [{
        "field": field,
        "old": current_val,
        "new": old_value_str,
    }]
    pending_values = {field: old_value_str}
    dry_run = (
        f"Reverting {field} from {current_val} back to {old_value_str}. "
        "The revert itself is recorded as a new audit entry."
    )
    return templates.TemplateResponse(
        "partials/settings_confirm_modal.html",
        {
            "request": request,
            "account_name": account_name,
            "diff": diff,
            "dry_run": dry_run,
            "pending_values": pending_values,
            "is_revert": True,
        },
    )


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, user: str = Depends(_verify_auth)):
    summary = await db.get_analytics_summary()
    by_symbol = await db.get_analytics_by_symbol()
    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "summary": summary,
        "by_symbol": by_symbol,
        "page": "analytics",
        "page_title": "Analytics",
    })


# ═══════════════════════════════════════════════════════════════════════
# HTMX PARTIALS (for live updates)
# ═══════════════════════════════════════════════════════════════════════


@app.get("/partials/positions", response_class=HTMLResponse)
async def positions_partial(request: Request, user: str = Depends(_verify_auth)):
    positions = await _get_all_positions()
    return templates.TemplateResponse("partials/positions_table.html", {
        "request": request,
        "positions": positions,
    })


@app.get("/partials/overview", response_class=HTMLResponse)
async def overview_partial(request: Request, user: str = Depends(_verify_auth)):
    accounts_data = await _get_accounts_overview()
    return templates.TemplateResponse("partials/overview_cards.html", {
        "request": request,
        "accounts": accounts_data,
        "trading_paused": _executor._trading_paused if _executor else False,
        "max_daily_trades": _executor.cfg.max_daily_trades_per_account if _executor else 30,
    })


# ═══════════════════════════════════════════════════════════════════════
# TRADE MANAGEMENT ACTIONS
# ═══════════════════════════════════════════════════════════════════════


@app.post("/api/close/{account_name}/{ticket}", response_class=HTMLResponse)
async def close_position(account_name: str, ticket: int, user: str = Depends(_verify_auth), _csrf=Depends(_verify_csrf)):
    """Close a position fully."""
    if not _executor:
        raise HTTPException(status_code=503, detail="Trading not initialized")

    connector = _executor.tm.connectors.get(account_name)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Account {account_name} not found")

    result = await connector.close_position(ticket)
    if result.success:
        await db.update_trade_close(ticket, account_name, 0.0, result.price)
        if _notifier:
            await _notifier.notify_alert(
                f"MANUAL CLOSE: {account_name} #{ticket} via dashboard"
            )
        return HTMLResponse(f'<span class="text-green-400">Closed #{ticket}</span>')
    else:
        return HTMLResponse(f'<span class="text-red-400">Failed: {result.error}</span>')


@app.post("/api/modify-sl/{account_name}/{ticket}", response_class=HTMLResponse)
async def modify_sl(
    account_name: str, ticket: int, request: Request,
    user: str = Depends(_verify_auth), _csrf=Depends(_verify_csrf),
):
    """Modify SL on a position."""
    if not _executor:
        raise HTTPException(status_code=503, detail="Trading not initialized")

    form = await request.form()
    new_sl = float(form.get("sl", 0))
    if new_sl <= 0:
        return HTMLResponse('<span class="text-red-400">Invalid SL</span>')

    connector = _executor.tm.connectors.get(account_name)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Account {account_name} not found")

    result = await connector.modify_position(ticket, sl=new_sl)
    if result.success:
        return HTMLResponse(f'<span class="text-green-400">SL updated to {new_sl:.2f}</span>')
    return HTMLResponse(f'<span class="text-red-400">Failed: {result.error}</span>')


@app.post("/api/modify-tp/{account_name}/{ticket}", response_class=HTMLResponse)
async def modify_tp(
    account_name: str, ticket: int, request: Request,
    user: str = Depends(_verify_auth), _csrf=Depends(_verify_csrf),
):
    """Modify TP on a position."""
    if not _executor:
        raise HTTPException(status_code=503, detail="Trading not initialized")

    form = await request.form()
    new_tp = float(form.get("tp", 0))
    if new_tp <= 0:
        return HTMLResponse('<span class="text-red-400">Invalid TP</span>')

    connector = _executor.tm.connectors.get(account_name)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Account {account_name} not found")

    result = await connector.modify_position(ticket, tp=new_tp)
    if result.success:
        return HTMLResponse(f'<span class="text-green-400">TP updated to {new_tp:.2f}</span>')
    return HTMLResponse(f'<span class="text-red-400">Failed: {result.error}</span>')


@app.post("/api/close-partial/{account_name}/{ticket}", response_class=HTMLResponse)
async def close_partial(
    account_name: str, ticket: int, request: Request,
    user: str = Depends(_verify_auth), _csrf=Depends(_verify_csrf),
):
    """Partial close a position."""
    if not _executor:
        raise HTTPException(status_code=503, detail="Trading not initialized")

    form = await request.form()
    percent = float(form.get("percent", 50))

    connector = _executor.tm.connectors.get(account_name)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Account {account_name} not found")

    positions = await connector.get_positions()
    pos = next((p for p in positions if p.ticket == ticket), None)
    if not pos:
        return HTMLResponse(f'<span class="text-red-400">Position #{ticket} not found</span>')

    close_vol = round(pos.volume * (percent / 100), 2)
    close_vol = max(close_vol, 0.01)

    result = await connector.close_position(ticket, volume=close_vol)
    if result.success:
        return HTMLResponse(f'<span class="text-green-400">Closed {close_vol:.2f} lots</span>')
    return HTMLResponse(f'<span class="text-red-400">Failed: {result.error}</span>')


# ═══════════════════════════════════════════════════════════════════════
# KILL SWITCH (REL-03)
# ═══════════════════════════════════════════════════════════════════════


@app.get("/api/emergency-preview", response_class=HTMLResponse)
async def emergency_preview(request: Request, user: str = Depends(_verify_auth)):
    """Show what kill switch will do before executing."""
    if not _executor:
        raise HTTPException(status_code=503, detail="Trading not initialized")

    positions = await _get_all_positions()
    pending_orders = []
    for acct_name, connector in _executor.tm.connectors.items():
        if connector.connected:
            try:
                orders = await connector.get_pending_orders()
                for o in orders:
                    o["account"] = acct_name
                    pending_orders.append(o)
            except Exception:
                pass

    return templates.TemplateResponse("partials/kill_switch_preview.html", {
        "request": request,
        "positions": positions,
        "pending_orders": pending_orders,
        "position_count": len(positions),
        "order_count": len(pending_orders),
    })


@app.post("/api/emergency-close")
async def emergency_close_endpoint(user: str = Depends(_verify_auth), _csrf=Depends(_verify_csrf)):
    """Execute emergency close: close all positions, cancel all orders, pause executor."""
    if not _executor:
        raise HTTPException(status_code=503, detail="Trading not initialized")

    results = await _executor.emergency_close()
    if _notifier:
        await _notifier.notify_kill_switch(activated=True)
    return results


@app.post("/api/resume-trading")
async def resume_trading(user: str = Depends(_verify_auth), _csrf=Depends(_verify_csrf)):
    """Re-enable trading after kill switch."""
    if not _executor:
        raise HTTPException(status_code=503, detail="Trading not initialized")

    _executor.resume_trading()
    if _notifier:
        await _notifier.notify_kill_switch(activated=False)
    return {"status": "resumed"}


@app.get("/api/trading-status")
async def trading_status(user: str = Depends(_verify_auth)):
    """Return current trading status for HTMX polling."""
    return {
        "trading_paused": _executor._trading_paused if _executor else False,
        "reconnecting": list(_executor._reconnecting) if _executor else [],
    }


# ═══════════════════════════════════════════════════════════════════════
# SSE STREAM (real-time updates)
# ═══════════════════════════════════════════════════════════════════════


@app.get("/stream")
async def sse_stream(request: Request, user: str = Depends(_verify_auth)):
    """Server-Sent Events stream for real-time updates.

    Emits two events per tick at 2s cadence:
      • a named `event: pending_stages` carrying the rendered partial HTML so
        HTMX (`sse-swap="pending_stages"`) can swap it directly (D-34)
      • the default `data:` event with the full JSON payload (existing
        consumers keep working; adds `pending_stages` key for clients that
        prefer raw data)
    """
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                positions = await _get_all_positions()
                accounts = await _get_accounts_overview()
                # D-34: include pending-stages payload. Top 5 most-recent
                # active sequences for the overview-panel partial.
                raw_stages = await db.get_pending_stages(limit=5)
                pending_stages = [
                    _enrich_stage_for_ui(s, positions) for s in raw_stages
                ]

                # Named SSE event — pre-rendered HTML partial for sse-swap.
                stages_html = templates.get_template(
                    "partials/pending_stages.html"
                ).render(stages=pending_stages)
                # SSE `data:` lines cannot contain raw newlines — collapse to
                # a single line before emit.
                stages_html_oneline = stages_html.replace("\n", "")
                yield (
                    "event: pending_stages\n"
                    f"data: {stages_html_oneline}\n\n"
                )

                # Default payload (JSON) — preserves backwards compat and
                # adds the pending_stages array for any raw-data consumer.
                data = json.dumps({
                    "positions": positions,
                    "accounts": accounts,
                    "pending_stages": pending_stages,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                yield f"data: {data}\n\n"
            except Exception as exc:
                logger.error("SSE error: %s", exc)
            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


async def _get_all_positions() -> list[dict]:
    """Get all open positions across all accounts (batched with asyncio.gather)."""
    if not _executor:
        return []

    connected = {
        name: conn for name, conn in _executor.tm.connectors.items()
        if conn.connected
    }
    if not connected:
        return []

    # Fetch all accounts in parallel instead of sequential N+1
    results = await asyncio.gather(
        *(conn.get_positions() for conn in connected.values()),
        return_exceptions=True,
    )

    positions = []
    for acct_name, result in zip(connected.keys(), results):
        if isinstance(result, Exception):
            logger.error("Failed to get positions for %s: %s", acct_name, result)
            continue
        for pos in result:
            positions.append({
                "account": acct_name,
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "direction": pos.direction,
                "volume": pos.volume,
                "open_price": pos.open_price,
                "sl": pos.sl,
                "tp": pos.tp,
                "profit": pos.profit,
            })
    return positions


async def _get_accounts_overview() -> list[dict]:
    """Get account summaries for all accounts."""
    if not _executor:
        return []
    accounts = []
    max_trades = _executor.cfg.max_daily_trades_per_account if _executor else 30
    for acct_name, connector in _executor.tm.connectors.items():
        acct_config = _executor.tm.accounts.get(acct_name)
        info = None
        if connector.connected:
            try:
                info = await connector.get_account_info()
            except Exception:
                pass

        positions = []
        if connector.connected:
            try:
                positions = await connector.get_positions()
            except Exception:
                pass

        stats = await db.get_daily_stats_batch(acct_name)
        trade_count = stats["trades_count"]
        msg_count = stats["server_messages"]

        # EXEC-04: Calculate daily limit percentage
        daily_limit_pct = (trade_count / max_trades * 100) if max_trades > 0 else 0

        # EXEC-04: Discord warning at 80% threshold (first crossing only)
        if daily_limit_pct >= 80 and acct_name not in _daily_limit_warned and _notifier:
            _daily_limit_warned.add(acct_name)
            asyncio.create_task(
                _notifier.notify_daily_limit(acct_name, f"trades {trade_count}/{max_trades}")
            )

        accounts.append({
            "name": acct_name,
            "connected": connector.connected,
            "enabled": acct_config.enabled if acct_config else False,
            "balance": info.balance if info else 0,
            "equity": info.equity if info else 0,
            "margin": info.margin if info else 0,
            "free_margin": info.free_margin if info else 0,
            "open_trades": len(positions),
            "total_profit": sum(p.profit for p in positions),
            "daily_trades": trade_count,
            "daily_messages": msg_count,
            "max_daily_trades": max_trades,
            "daily_limit_pct": daily_limit_pct,
            "risk_percent": acct_config.risk_percent if acct_config else 0,
            "max_lot": acct_config.max_lot_size if acct_config else 0,
        })
    return accounts
