"""tests/test_api_csrf.py — the D-16 CSRF go-live gate (Phase 08 Plan 02).

THIS FILE IS THE HARD GATE referenced in 08-VALIDATION.md (API-03). No /api/v2
mutation ships unless this suite is green. It proves the three CSRF invariants:

  1. A /api/v2 mutation WITHOUT a valid X-CSRF-Token returns 403 (the double-submit
     guard, never an HTML/traceback leak).
  2. A valid X-CSRF-Token matching the telebot_csrf cookie lets the mutation proceed.
  3. The new cookie is named `telebot_csrf` and does NOT collide with the legacy
     `telebot_login_csrf` name.

The representative guarded mutation is `POST /api/v2/auth/logout` (decorated with
`Depends(verify_csrf_token)` in api/auth.py). The money-mutation routes inherit the
identical guard, so this gate generalises.

Harness: the conftest `api_client` (httpx on the session loop, sharing the one
asyncpg pool) and `api_login` (the real JSON login round-trip). Skips cleanly
when Postgres is absent (the `db_pool` fixture skips).
"""

from __future__ import annotations

from tests.conftest import api_login


# ─── /auth/me + /auth/csrf basics ────────────────────────────────────────────


async def test_me_requires_session(api_client):
    """GET /auth/me with no session -> 401 (enveloped JSON, no HTML)."""
    r = await api_client.get("/api/v2/auth/me")
    assert r.status_code == 401
    assert "<html" not in r.text.lower()
    assert "traceback" not in r.text.lower()


async def test_csrf_endpoint_issues_readable_token(api_client):
    """GET /auth/csrf returns a token AND sets a matching readable telebot_csrf
    cookie (httponly=False so the SPA can read it), without an existing session."""
    r = await api_client.get("/api/v2/auth/csrf")
    assert r.status_code == 200
    token = r.json()["csrf_token"]
    assert token
    assert api_client.cookies.get("telebot_csrf") == token


async def test_login_then_me_returns_admin(api_client):
    """End-to-end: login establishes a session, /auth/me then returns the user."""
    await api_login(api_client)
    r = await api_client.get("/api/v2/auth/me")
    assert r.status_code == 200
    assert r.json() == {"user": "admin"}


# ─── The D-16 hard gate: missing token -> 403 / valid token -> pass ──────────


async def test_mutation_without_csrf_token_returns_403(api_client):
    """A /api/v2 mutation WITHOUT X-CSRF-Token -> 403 (no HTML, no traceback).

    Authenticate first (so the 403 is unambiguously the CSRF guard, not auth),
    then POST the guarded mutation with NO X-CSRF-Token header.
    """
    await api_login(api_client)
    # Strip the cookie so neither the cookie nor the header is present — the
    # purest no-token case; the double-submit guard must reject it.
    api_client.cookies.delete("telebot_csrf")
    r = await api_client.post("/api/v2/auth/logout")  # no X-CSRF-Token header
    assert r.status_code == 403, r.text
    assert "<html" not in r.text.lower()
    assert "traceback" not in r.text.lower()


async def test_valid_token_passes(api_client):
    """A valid X-CSRF-Token matching the telebot_csrf cookie lets the mutation
    proceed (NOT 403)."""
    token = await api_login(api_client)
    r = await api_client.post("/api/v2/auth/logout", headers={"X-CSRF-Token": token})
    assert r.status_code != 403, r.text
    assert r.status_code == 200
    assert r.json() == {"ok": True}


async def test_csrf_cookie_name_no_collision(api_client):
    """The new cookie is `telebot_csrf`, distinct from the legacy
    `telebot_login_csrf` name (the legacy HTML /login flow was deleted in CUT-03)."""
    r = await api_client.get("/api/v2/auth/csrf")
    assert "telebot_csrf" in r.cookies
    assert "telebot_login_csrf" not in r.cookies
