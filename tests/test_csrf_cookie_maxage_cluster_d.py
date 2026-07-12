"""tests/test_csrf_cookie_maxage_cluster_d.py — §2.1 (HIGH) regression gate.

The telebot_csrf double-submit cookie was previously set WITHOUT max_age, making
it a browser-session cookie that dies on browser restart — while the auth
telebot_session cookie persists 30 days (dashboard.py:183). A device that then
auto-authenticates off the surviving session cookie had no CSRF cookie, so every
mutation sent an empty X-CSRF-Token and 403'd forever.

The fix adds max_age=30d to BOTH set_cookie calls for telebot_csrf (the login
`_issue_csrf` path and the GET /auth/csrf path). These tests assert the emitted
Set-Cookie header now carries Max-Age matching the session-cookie lifetime.

The unit test (_issue_csrf) needs no DB. The integration test drives the real
GET /api/v2/auth/csrf route via TestClient and skips cleanly when dev Postgres is
absent (the api_app fixture skips on init_db failure).
"""

from __future__ import annotations

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

# The CSRF cookie must outlive a browser restart exactly as long as the session
# cookie does (dashboard.py:183 — 30 days). Kept in sync via this literal.
EXPECTED_MAX_AGE = 30 * 24 * 60 * 60  # 2592000


def test_issue_csrf_sets_max_age_on_cookie():
    """_issue_csrf (the login response path) emits Max-Age on telebot_csrf.

    DB-free: builds a bare JSONResponse and inspects the Set-Cookie header the
    handler appends. FAILS on the pre-fix code (no max_age -> session cookie).
    """
    from api.auth import CSRF_COOKIE_MAX_AGE, _issue_csrf

    assert CSRF_COOKIE_MAX_AGE == EXPECTED_MAX_AGE

    resp = JSONResponse({"user": "admin"})
    _issue_csrf(resp, secure=False)

    set_cookie = resp.headers.get("set-cookie")
    assert set_cookie is not None
    assert "telebot_csrf=" in set_cookie
    # Starlette renders max_age as `Max-Age=<seconds>`.
    assert f"Max-Age={EXPECTED_MAX_AGE}" in set_cookie


def test_csrf_endpoint_sets_max_age_on_cookie(api_app):
    """GET /api/v2/auth/csrf sets telebot_csrf with a persistent Max-Age.

    FAILS on the pre-fix code (browser-session cookie, no Max-Age). Requires the
    api_app fixture (skips without dev Postgres)."""
    c = TestClient(api_app)
    r = c.get("/api/v2/auth/csrf")
    assert r.status_code == 200, r.text

    set_cookie = r.headers.get("set-cookie")
    assert set_cookie is not None
    assert "telebot_csrf=" in set_cookie
    assert f"Max-Age={EXPECTED_MAX_AGE}" in set_cookie
