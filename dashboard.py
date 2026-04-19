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
    return templates.TemplateResponse("overview.html", {
        "request": request,
        "accounts": accounts_data,
        "trading_enabled": _settings.trading_enabled if _settings else False,
        "dry_run": _settings.trading_dry_run if _settings else True,
        "trading_paused": _executor._trading_paused if _executor else False,
        "page": "overview",
    })


@app.get("/positions", response_class=HTMLResponse)
async def positions_page(request: Request, user: str = Depends(_verify_auth)):
    positions = await _get_all_positions()
    return templates.TemplateResponse("positions.html", {
        "request": request,
        "positions": positions,
        "page": "positions",
    })


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, user: str = Depends(_verify_auth)):
    trades = await db.get_recent_trades(100)
    return templates.TemplateResponse("history.html", {
        "request": request,
        "trades": trades,
        "page": "history",
    })


@app.get("/signals", response_class=HTMLResponse)
async def signals_page(request: Request, user: str = Depends(_verify_auth)):
    signals = await db.get_recent_signals(100)
    return templates.TemplateResponse("signals.html", {
        "request": request,
        "signals": signals,
        "page": "signals",
    })


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: str = Depends(_verify_auth)):
    accounts_data = await _get_accounts_overview()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "accounts": accounts_data,
        "trading_enabled": _settings.trading_enabled if _settings else False,
        "dry_run": _settings.trading_dry_run if _settings else True,
        "page": "settings",
    })


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, user: str = Depends(_verify_auth)):
    summary = await db.get_analytics_summary()
    by_symbol = await db.get_analytics_by_symbol()
    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "summary": summary,
        "by_symbol": by_symbol,
        "page": "analytics",
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
    """Server-Sent Events stream for real-time updates."""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                positions = await _get_all_positions()
                accounts = await _get_accounts_overview()
                data = json.dumps({
                    "positions": positions,
                    "accounts": accounts,
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
