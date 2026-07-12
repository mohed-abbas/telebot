"""Web dashboard app host for trade monitoring and management.

FastAPI app host for the React SPA (served at /app) + the /api/v2 JSON layer.

Phase 12 (CUT-03) decommissioned the legacy HTMX/Jinja presentation stack: the
HTML page/partial routes, the SSE /stream endpoint, the Jinja2Templates setup,
the asset-manifest machinery, the legacy /login form, and the dead legacy HTML
trade-action routes were deleted. What survives is the app wiring (factory,
middleware, mounts, auth, /health, / -> /app/) plus the helpers the /api/v2
layer imports from this module (validate_settings_form, _compute_dry_run,
_enrich_stage_for_ui, _client_ip, _password_hasher, app_settings) and the data
helpers those depend on. bot.py's `from dashboard import app, init_dashboard`
is unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from argon2 import PasswordHasher
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

import db
from config import settings as app_settings

logger = logging.getLogger(__name__)

# These get set by init_dashboard() from bot.py
_executor = None
_notifier = None
_settings = None
_daily_limit_warned: set[str] = set()  # Account names that already received 80% warning today

# Last-good positions per account — used by _get_all_positions() to mask
# transient REST failures that would otherwise blink the open-positions table
# to "no positions" between 3-second polls. Cleared explicitly when an
# account fetch returns an empty list AFTER a successful response (real
# zero-position state vs. fetch failure).
_last_positions_by_account: dict[str, list[dict]] = {}

BASE_DIR = Path(__file__).parent


def init_dashboard(executor, notifier, settings):
    """Called from bot.py to inject dependencies."""
    global _executor, _notifier, _settings
    _executor = executor
    _notifier = notifier
    _settings = settings


# ─── Phase 08 (JSON API) read-only accessors ─────────────────────────────────
# api/ depends on these instead of importing the rebindable module globals
# directly: init_dashboard() rebinds _executor/_notifier/_settings AFTER import,
# so `from dashboard import _executor` would capture a stale None (Pattern 1).
def get_executor():
    return _executor


def get_notifier():
    return _notifier


def get_settings():
    return _settings


def get_settings_store():
    return _get_settings_store()


# W3-AUTH(B): absolute session-lifetime cap. The SessionMiddleware cookie is a
# rolling 30-day signed cookie with no server-side revocation; a stolen cookie
# would otherwise live forever as long as it keeps being used. login stamps an
# issued-at (`iat`) into the session and every auth check rejects a session once
# `iat` is older than this cap — even while the rolling window is still fresh.
# Configurable (seconds); default 7 days. Read at import (config-safe, no TLS req).
SESSION_ABSOLUTE_MAX_AGE = int(
    os.environ.get("SESSION_ABSOLUTE_MAX_AGE", str(7 * 24 * 60 * 60))
)


def _session_within_absolute_lifetime(session) -> bool:
    """W3-AUTH(B): True while the session's issued-at is within the absolute cap.

    A session with no numeric `iat` (minted before this hardening, or forged) is
    treated as over-age → the operator re-authenticates once. Shared by
    dashboard._verify_auth, api.deps.require_user and api.auth.me so the cap is
    enforced uniformly on both the page and JSON auth surfaces.
    """
    iat = session.get("iat")
    if not isinstance(iat, (int, float)) or isinstance(iat, bool):
        return False
    return (time.time() - iat) <= SESSION_ABSOLUTE_MAX_AGE


def _verify_auth(request: Request) -> str:
    """Session-based auth (AUTH-01 consumer contract).

    Page routes: HTTPException(303, Location=/app/login?next=…) to redirect.
    API routes: HTTPException(401) so the SPA shows an inline error.

    Signature preserved: still returns the username string so the existing
    `user: str = Depends(_verify_auth)` call sites compile unchanged.
    """
    user = request.session.get("user")
    if user:
        if _session_within_absolute_lifetime(request.session):
            return user
        # W3-AUTH(B): session exceeded the absolute cap — clear it so the still-
        # fresh rolling cookie can't keep re-authenticating a stale login.
        request.session.clear()

    if request.url.path.startswith("/api/"):
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
        headers={"Location": f"/app/login?next={next_path}"},
    )


# ─── Auth helpers imported by the /api/v2 layer (MUST SURVIVE) ───────────────
# api/auth.py:100 does `from dashboard import _client_ip, _password_hasher, app_settings`.
_password_hasher = PasswordHasher()  # RFC 9106 defaults

# W3-AUTH(D): X-Real-IP / X-Forwarded-For are attacker-controlled on any request
# that does NOT traverse the trusted nginx front, so keying the login lockout on
# them unconditionally let an attacker rotate the lockout key by spoofing headers.
# Only honour those headers when TRUST_PROXY is set (the nginx-fronted prod deploy
# MUST set it — see concerns); otherwise fall back to the direct connection peer.
_TRUST_PROXY = os.environ.get("TRUST_PROXY", "false").lower() in ("true", "1", "yes")


def _client_ip(request: Request) -> str:
    """Client IP used as the per-IP login-lockout key.

    W3-AUTH(D): trust the nginx-supplied X-Real-IP / X-Forwarded-For headers ONLY
    when TRUST_PROXY is enabled; otherwise use the direct peer so the lockout can't
    be evaded by header spoofing on a non-nginx path.
    """
    if _TRUST_PROXY:
        xri = request.headers.get("x-real-ip", "").strip()
        if xri:
            return xri
        xff = request.headers.get("x-forwarded-for", "").strip()
        if xff:
            # First hop is the original client (nginx appends downstream peers).
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """ASGI lifespan: manages startup/shutdown lifecycle."""
    logger.info("Dashboard ASGI lifespan: startup")
    # Phase 08 (JSON API): create the idempotency_keys table at startup.
    # DDL lives in api/idempotency.py (NOT db.py — bot core stays untouched).
    from api.idempotency import ensure_table
    await ensure_table()
    yield
    logger.info("Dashboard ASGI lifespan: shutdown")


# ─── Phase 09 (SPA serving, SPA-01 / D-01) ───────────────────────────────────
# StaticFiles(html=True) serves index.html ONLY at the mount root (`/app/`). A
# hard reload of a client route (`/app/login`, `/app/positions`) has no matching
# file on disk → 404, NOT index.html (RESEARCH Pitfall 1 — the single
# highest-risk item: it silently ships a dashboard that 404s on refresh).
# SpaStaticFiles overrides get_response to fall back to index.html on a 404 so
# client-side routing resolves. The fallback is self-contained inside the /app
# mount and is registered AFTER app.include_router(api_router), so it can never
# shadow /api/v2/* (router-precedence rule; Pitfall 1/4).
class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                # CR-01: a missing built ASSET must stay a 404 — never mask it as the
                # HTML shell. A request for /app/assets/index-OLDHASH.js (stale HTML,
                # cache skew, typo'd import) that returned 200 text/html would make the
                # browser try to execute index.html as a module → silent white screen.
                # Only NON-asset, NON-file paths (client deep-link ROUTES like
                # /app/positions) fall back to the shell so the router boots
                # (RESEARCH Pitfall 1). Predicate: under the Vite assetsDir
                # ("assets/") OR any path carrying a file extension ⇒ keep the 404.
                if path.startswith("assets/") or Path(path).suffix:
                    raise
                # Deep-link / client route: serve the SPA shell so the router boots.
                return await super().get_response("index.html", scope)
            raise


app = FastAPI(title="Telebot Dashboard", docs_url=None, redoc_url=None, lifespan=lifespan)

# Phase 08 (JSON API): mount the /api/v2 router and install enveloped-error
# handlers. The SPA fetches only /api/v2/* + /app/*.
from api import api_router  # noqa: E402
from api.errors import register_error_handlers  # noqa: E402

app.include_router(api_router)
register_error_handlers(app)

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

# Phase 09 (SPA-01 / D-01, D-02): serve the built Vite bundle same-origin at
# /app/ via uvicorn StaticFiles (no nginx, no prod Node). check_dir=False so the
# app still imports before a build exists (tests / dev before `npm run build`);
# the directory is provided by the Dockerfile spa-build COPY in production and by
# the serving-test fixture in CI. Registered AFTER app.include_router(api_router)
# and the /static mount, so /api/v2/* always wins route precedence (Pitfall 1/4).
app.mount(
    "/app",
    SpaStaticFiles(directory=str(BASE_DIR / "static" / "app"), html=True, check_dir=False),
    name="spa",
)


@app.get("/health")
async def health():
    """Health check for container orchestration — no auth required."""
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════
# AUTH: /logout (login is served by /api/v2/auth/login — Phase 8)
# ═══════════════════════════════════════════════════════════════════════


def _expire_auth_cookies(resp: Response) -> None:
    """W3-AUTH(A): explicitly delete both auth cookies so logout is effective
    server-side rather than trusting the client to drop them. Attributes match the
    set sites (path=/, secure gated on config) so the browser actually expires
    them; the __Host- CSRF variant is only emitted (and thus only cleared) under TLS.
    """
    secure = app_settings.session_cookie_secure
    resp.delete_cookie("telebot_session", path="/", samesite="lax", secure=secure)
    resp.delete_cookie("telebot_csrf", path="/", samesite="lax", secure=secure)
    if secure:
        resp.delete_cookie("__Host-telebot_csrf", path="/", samesite="lax", secure=True)


@app.post("/logout")
async def logout(request: Request):
    """AUTH-06 / W3-AUTH(A): CSRF-protected POST logout.

    Previously also reachable via GET, which made it a state-changing endpoint that
    a cross-site link could trigger to force-logout the operator. It is now
    POST-only and guarded by the same double-submit CSRF check as every /api/v2
    mutation, and it expires the session + CSRF cookies server-side. The SPA logs
    out via POST /api/v2/auth/logout; this route is the plain-form fallback.
    """
    from api.deps import verify_csrf_token  # deferred (mirrors deps import discipline)

    verify_csrf_token(request)
    request.session.clear()
    resp = RedirectResponse(url="/app/login", status_code=303)
    _expire_auth_cookies(resp)
    return resp


@app.get("/")
async def root(request: Request, user: str = Depends(_verify_auth)):
    """Root redirects to the SPA (CUT-02 D-02). Depends(_verify_auth) retained so
    an unauthenticated hit bounces to /app/login first."""
    return RedirectResponse(url="/app/", status_code=303)


# ═══════════════════════════════════════════════════════════════════════
# Helpers imported by the /api/v2 layer (MUST SURVIVE — see module docstring)
# ═══════════════════════════════════════════════════════════════════════


def _enrich_stage_for_ui(stage: dict, positions: list[dict]) -> dict:
    """D-34: transform a staged_entries row into the UI display shape.

    Imported by api/stages.py:73 (`dashboard._enrich_stage_for_ui(...)`).

    `positions` is the list produced by `_get_all_positions()` (keys:
    `account`, `symbol`, `direction`, `open_price`, `profit`). No live-price
    field is carried today — `current_price` stays None and the caller renders
    an em-dash.
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


# ─── SET-03: per-account settings validation (imported by /api/v2 layer) ─────

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

    Imported by api/settings.py:125 (`from dashboard import validate_settings_form`).

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
    """D-27: concise dry-run string rendered inside the confirmation modal.

    Imported by api/settings.py:204 (`from dashboard import _compute_dry_run`).
    """
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


# ═══════════════════════════════════════════════════════════════════════
# DATA HELPERS (consumed by the /api/v2 accounts/stages layer)
# ═══════════════════════════════════════════════════════════════════════


async def _get_all_positions() -> list[dict]:
    """Get all open positions across all accounts (batched with asyncio.gather).

    Per-account stale-while-revalidate: a transient REST failure (timeout,
    momentary disconnect) for one account returns the last-good list for
    THAT account instead of dropping it from the response. Only a successful
    fetch that returns zero positions counts as "really empty" and clears the
    cache. This prevents the 3-second poll on /overview from blinking to
    "no open positions" during a single failed tick.
    """
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

    positions: list[dict] = []
    for acct_name, result in zip(connected.keys(), results):
        if isinstance(result, Exception):
            logger.warning(
                "Failed to get positions for %s: %s — using last-good cache",
                acct_name, result,
            )
            cached = _last_positions_by_account.get(acct_name)
            if cached:
                positions.extend(cached)
            continue
        acct_positions = [
            {
                "account": acct_name,
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "direction": pos.direction,
                "volume": pos.volume,
                "open_price": pos.open_price,
                "sl": pos.sl,
                "tp": pos.tp,
                "profit": pos.profit,
            }
            for pos in result
        ]
        _last_positions_by_account[acct_name] = acct_positions
        positions.extend(acct_positions)
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
