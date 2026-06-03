"""api/deps.py — shared FastAPI dependencies for /api/v2 (Phase 08 Plan 01).

Exports the four guards every resource route in Plans 02-05 depends on:

  require_user(request)         -> str          # 401 if no session (no redirect on /api/v2)
  verify_csrf_token(request)    -> None         # 403 on state-changing methods w/o matching token
  require_executor()            -> Executor     # 503 if trading not initialised
  require_settings_store()      -> SettingsStore # 503 if settings store not initialised

Design notes (mirrors the house style in dashboard.py / 08-PATTERNS.md):
  * `require_user` replicates the session-read + 401 branch of `_verify_auth`
    (dashboard.py:108-116) WITHOUT the redirect branch — `/api/v2` never redirects.
  * `verify_csrf_token` is the NEW double-submit dep (D-13/D-15): cookie
    `telebot_csrf` (NOT `telebot_login_csrf`) compared to the `X-CSRF-Token`
    header with `secrets.compare_digest`. Guards only state-changing methods.
  * Executor / settings-store are reached via the dashboard ACCESSOR functions
    (get_executor / get_settings_store), never `from dashboard import _executor`
    — init_dashboard() rebinds those globals, so a direct import captures a
    stale `None` (08-PATTERNS Pitfall 6).
"""

from __future__ import annotations

import secrets as _secrets

from fastapi import HTTPException, Request

# Accessor imports (NOT the rebindable globals — Pattern 1 / Pitfall 6).
from dashboard import get_executor, get_settings_store

# Double-submit CSRF cookie name. MUST be telebot_csrf — must NOT collide with
# the legacy login-form cookie telebot_login_csrf (dashboard.py:142) — D-13.
CSRF_COOKIE = "telebot_csrf"
CSRF_HEADER = "x-csrf-token"
_STATE_CHANGING_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def require_user(request: Request) -> str:
    """Session-based auth for /api/v2 (V4 access control).

    Reads the session `user`; raises 401 if absent. Unlike `_verify_auth`
    (dashboard.py:99) there is NO redirect branch — JSON API routes never 303.
    """
    user = request.session.get("user")
    if user:
        return user
    raise HTTPException(status_code=401, detail="Session expired")


def verify_csrf_token(request: Request) -> None:
    """Double-submit CSRF guard for /api/v2 mutations (T-08-01, D-15).

    Only guards state-changing methods. Compares the `telebot_csrf` cookie to
    the `X-CSRF-Token` header in constant time (secrets.compare_digest). GET and
    other safe methods pass through untouched.
    """
    if request.method in _STATE_CHANGING_METHODS:
        cookie = request.cookies.get(CSRF_COOKIE, "")
        header = request.headers.get(CSRF_HEADER, "")
        if not cookie or not header or not _secrets.compare_digest(cookie, header):
            raise HTTPException(status_code=403, detail="CSRF token invalid")


def require_executor():
    """Return the live executor or 503 (mirrors dashboard.py:1052-1053).

    Uses the dashboard accessor so init_dashboard()'s late global rebind is seen.
    """
    executor = get_executor()
    if executor is None:
        raise HTTPException(status_code=503, detail="Trading not initialized")
    return executor


def require_settings_store():
    """Return the live SettingsStore or 503 (mirrors dashboard.py:749-751)."""
    store = get_settings_store()
    if store is None:
        raise HTTPException(status_code=503, detail="SettingsStore not initialised")
    return store
