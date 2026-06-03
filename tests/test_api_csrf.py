"""tests/test_api_csrf.py — the D-16 CSRF go-live gate (Phase 08 Plan 02).

THIS FILE IS THE HARD GATE referenced in 08-VALIDATION.md (API-03). No /api/v2
mutation ships unless this suite is green. It proves the three CSRF invariants:

  1. A /api/v2 mutation WITHOUT a valid X-CSRF-Token returns 403 (the double-submit
     guard, never an HTML/traceback leak).
  2. A valid X-CSRF-Token matching the telebot_csrf cookie lets the mutation proceed.
  3. The new cookie is named `telebot_csrf` and does NOT collide with the legacy
     `telebot_login_csrf`; the legacy HTML /login flow still sets its own cookie
     (D-13: the two flows run in parallel, untouched).

The representative guarded mutation is `POST /api/v2/auth/logout` (decorated with
`Depends(verify_csrf_token)` in api/auth.py). Once the money-mutation routes land
(Plan 04) they inherit the identical guard, so this gate generalises.

Skips cleanly when dev Postgres is absent (the api_app fixture skips on init_db
failure, per the conftest skip pattern) — the login route exercises the failed-
login DB helpers, so a DB is required for an end-to-end session.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

KNOWN_PASSWORD = "correct-horse-battery-staple"


def _login(client: TestClient) -> str:
    """Drive the real JSON login route end-to-end and return the live csrf token.

    GET /auth/csrf first to obtain a telebot_csrf cookie + token, then POST
    /auth/login echoing that token in the body. On success the server sets the
    session cookie and refreshes telebot_csrf; the TestClient cookie jar carries
    both forward. Returns the post-login telebot_csrf token.
    """
    r = client.get("/api/v2/auth/csrf")
    assert r.status_code == 200, r.text
    token = r.json()["csrf_token"]
    assert client.cookies.get("telebot_csrf") == token

    r = client.post(
        "/api/v2/auth/login",
        json={"password": KNOWN_PASSWORD, "csrf_token": token},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"user": "admin"}
    # Session established; telebot_csrf refreshed by the login response.
    assert "telebot_session" in client.cookies
    return client.cookies.get("telebot_csrf")


# ─── /auth/me + /auth/csrf basics ────────────────────────────────────────────


def test_me_requires_session(api_app):
    """GET /auth/me with no session -> 401 (enveloped JSON, no HTML)."""
    c = TestClient(api_app)
    r = c.get("/api/v2/auth/me")
    assert r.status_code == 401
    assert "<html" not in r.text.lower()
    assert "traceback" not in r.text.lower()


def test_csrf_endpoint_issues_readable_token(api_app):
    """GET /auth/csrf returns a token AND sets a matching readable telebot_csrf
    cookie (httponly=False so the SPA can read it), without an existing session."""
    c = TestClient(api_app)
    r = c.get("/api/v2/auth/csrf")
    assert r.status_code == 200
    token = r.json()["csrf_token"]
    assert token
    assert c.cookies.get("telebot_csrf") == token


def test_login_then_me_returns_admin(api_app):
    """End-to-end: login establishes a session, /auth/me then returns the user."""
    c = TestClient(api_app)
    _login(c)
    r = c.get("/api/v2/auth/me")
    assert r.status_code == 200
    assert r.json() == {"user": "admin"}


# ─── The D-16 hard gate: missing token -> 403 / valid token -> pass ──────────


def test_mutation_without_csrf_token_returns_403(api_app):
    """A /api/v2 mutation WITHOUT X-CSRF-Token -> 403 (no HTML, no traceback).

    Authenticate first (so the 403 is unambiguously the CSRF guard, not auth),
    then POST the guarded mutation with NO X-CSRF-Token header.
    """
    c = TestClient(api_app)
    _login(c)
    # Strip the cookie so neither the cookie nor the header is present — the
    # purest no-token case; the double-submit guard must reject it.
    c.cookies.delete("telebot_csrf")
    r = c.post("/api/v2/auth/logout")  # no X-CSRF-Token header
    assert r.status_code == 403, r.text
    assert "<html" not in r.text.lower()
    assert "traceback" not in r.text.lower()


def test_valid_token_passes(api_app):
    """A valid X-CSRF-Token matching the telebot_csrf cookie lets the mutation
    proceed (NOT 403)."""
    c = TestClient(api_app)
    token = _login(c)
    r = c.post("/api/v2/auth/logout", headers={"X-CSRF-Token": token})
    assert r.status_code != 403, r.text
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_csrf_cookie_name_no_collision(api_app):
    """The new cookie is `telebot_csrf`, distinct from the legacy
    `telebot_login_csrf`, and the legacy /login GET still sets its own cookie
    (D-13: both flows run in parallel, legacy untouched)."""
    c = TestClient(api_app)

    # New flow issues telebot_csrf.
    r = c.get("/api/v2/auth/csrf")
    assert "telebot_csrf" in r.cookies
    assert "telebot_login_csrf" not in r.cookies
    assert "telebot_csrf" != "telebot_login_csrf"

    # Legacy HTML /login flow is untouched — still sets telebot_login_csrf.
    c2 = TestClient(api_app)
    r2 = c2.get("/login")
    assert r2.status_code == 200
    assert "telebot_login_csrf" in r2.cookies
    assert "telebot_csrf" not in r2.cookies
