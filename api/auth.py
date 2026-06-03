"""api/auth.py — /api/v2/auth JSON contract (Phase 08 Plan 02).

The complete `/auth/{login,logout,me,csrf}` JSON port of the legacy HTML login
flow (dashboard.py:261-330). The four-step login pipeline order is load-bearing
and ported verbatim from `login_submit` (dashboard.py:269-316):

  1. double-submit CSRF        (secrets.compare_digest on telebot_csrf vs body)
  2. per-IP rate-limit         (db.get_failed_login_count >= 5 -> 429, D-14)
                               — BEFORE the argon2 CPU cost.
  3. argon2 verify             (_password_hasher.verify, VerifyMismatchError -> 401)
  4. session + clear counter   (request.session["user"] = "admin")

Only the RESPONSE shape changes (JSON, not HTML/redirect). The reused machinery
(_password_hasher, app_settings, _client_ip) is imported from dashboard.py — we
do NOT re-instantiate PasswordHasher() (08-PATTERNS api/auth.py section).

The `telebot_csrf` cookie is the NEW double-submit cookie (D-13/D-15):
`httponly=False` (the SPA must read it) and `path="/"` (covers all of /api/v2).
This is the deliberate contrast to the legacy login cookie `telebot_login_csrf`
(dashboard.py:189-196: httponly=True, path="/login") — the two MUST NOT collide,
and the legacy HTMX /login flow stays untouched and operational in parallel.

tests/test_api_csrf.py is the D-16 go-live gate proving any /api/v2 mutation
rejects a request with no valid X-CSRF-Token (403).
"""

from __future__ import annotations

import secrets as _secrets

from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

import db

from api.schemas import LoginIn

# NOTE — reused machinery (_password_hasher / app_settings / _client_ip) and the
# verify_csrf_token dependency are imported LAZILY inside the handlers, NOT at
# module top level. Importing them eagerly would pull in `dashboard` -> `config`
# at api/router.py collection time; when a test fixture has popped `config` from
# sys.modules without the env set, `config._load_settings()` raises SystemExit
# and crashes pytest collection for the whole suite. Deferring the import to
# request time keeps `import api.auth` side-effect-free (it only needs `db` +
# `LoginIn` at import time). app_settings / _password_hasher / _client_ip are
# stable module-level objects in dashboard.py (not rebound by init_dashboard),
# so a lazy direct import is correct (08-PATTERNS Pitfall 6 / api/auth.py).


def _verify_csrf(request: Request) -> None:
    """Lazy proxy to api.deps.verify_csrf_token.

    Used as the route dependency so the decorator does NOT eager-import api.deps
    (which top-level imports dashboard) at collection time — see the module note.
    """
    from api.deps import verify_csrf_token

    verify_csrf_token(request)


router = APIRouter()

# The NEW double-submit cookie name (D-13). MUST differ from the legacy
# telebot_login_csrf (dashboard.py:162) — non-collision is asserted by
# tests/test_api_csrf.py::test_csrf_cookie_name_no_collision.
CSRF_COOKIE = "telebot_csrf"


def _issue_csrf(resp: JSONResponse, secure: bool) -> str:
    """Set a fresh telebot_csrf cookie on `resp` and return the token.

    Pitfall 4: httponly=False so the SPA can read the token and echo it as the
    X-CSRF-Token header; path="/" so the cookie covers every /api/v2 route. This
    is the deliberate inverse of the legacy login cookie (httponly=True,
    path="/login") — NEVER use those values here. `secure` is passed in by the
    caller from the lazily-imported app_settings.session_cookie_secure.
    """
    token = _secrets.token_urlsafe(32)
    resp.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=False,
        samesite="lax",
        secure=secure,
        path="/",
    )
    return token


@router.post("/auth/login")
async def login(request: Request, body: LoginIn) -> JSONResponse:
    """JSON login — ports dashboard.py:269-316 four-step pipeline verbatim.

    Order is load-bearing: CSRF -> rate-limit (before argon2 CPU) -> verify ->
    session. Only the response shape changes to JSON.
    """
    # Lazy import of the reused dashboard machinery (see module note) — keeps
    # `import api.auth` free of the dashboard -> config import chain.
    from dashboard import _client_ip, _password_hasher, app_settings

    # 1. Double-submit CSRF (AUTH-04, D-15) — compare the telebot_csrf cookie to
    #    the token in the request body in constant time.
    cookie = request.cookies.get(CSRF_COOKIE, "")
    if not cookie or not _secrets.compare_digest(cookie, body.csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token invalid")

    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")

    # 2. App-level rate limit (D-14) — BEFORE the argon2 CPU cost. Reuses the
    #    legacy per-IP 5/15min lockout verbatim (db.py unmodified).
    if await db.get_failed_login_count(ip, minutes=15) >= 5:
        raise HTTPException(status_code=429, detail="rate_limited")

    # 3. argon2 verify (constant-time). Generic failure -> 401 invalid_credentials
    #    (no user-enumeration, T-08-08).
    ok = False
    try:
        _password_hasher.verify(app_settings.dashboard_pass_hash, body.password)
        ok = True
    except VerifyMismatchError:
        ok = False
    except (InvalidHashError, VerificationError):
        ok = False

    if not ok:
        await db.log_failed_login(ip, user_agent=ua)
        raise HTTPException(status_code=401, detail="invalid_credentials")

    # 4. Success: set session, clear the failed-login counter.
    request.session["user"] = "admin"  # D-30 actor default
    await db.clear_failed_logins(ip)

    resp = JSONResponse({"user": "admin"})
    _issue_csrf(resp, secure=app_settings.session_cookie_secure)
    return resp


@router.post("/auth/logout", dependencies=[Depends(_verify_csrf)])
async def logout(request: Request) -> JSONResponse:
    """Clear the session. Guarded by verify_csrf_token so it doubles as the
    representative /api/v2 mutation in the D-16 CSRF regression gate."""
    request.session.clear()
    return JSONResponse({"ok": True})


@router.get("/auth/me")
async def me(request: Request) -> JSONResponse:
    """Return the authenticated user or 401 (no session)."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Session expired")
    return JSONResponse({"user": user})


@router.get("/auth/csrf")
async def csrf(request: Request) -> JSONResponse:
    """Issue/refresh the telebot_csrf cookie and return the token in the body so
    the SPA can read it on first load. Does NOT require an existing session.

    Mint the token first, then build the response body with it; set_cookie only
    appends a Set-Cookie header (it never touches the already-rendered body), so
    the body token and the cookie value are guaranteed identical."""
    from dashboard import app_settings  # lazy (see module note)

    token = _secrets.token_urlsafe(32)
    resp = JSONResponse({"csrf_token": token})
    resp.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=False,
        samesite="lax",
        secure=app_settings.session_cookie_secure,
        path="/",
    )
    return resp
