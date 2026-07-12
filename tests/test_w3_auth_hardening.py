"""tests/test_w3_auth_hardening.py — W3-AUTH security-hardening regression gate.

Covers the four Wave 3 auth findings. Every test FAILS on the pre-fix code:

  (A) GET /logout is gone (405) and POST /logout requires a matching CSRF token
      and expires both auth cookies server-side.
  (B) A session whose issued-at (`iat`) exceeds the absolute lifetime cap is
      rejected even though the rolling window is fresh; a session with no `iat`
      is treated as over-age.
  (C) The double-submit CSRF cookie gets the `__Host-` prefix ONLY when secure
      (prod/TLS); the server reader prefers that variant.
  (D) `_client_ip` ignores spoofable X-Real-IP / X-Forwarded-For unless the
      TRUST_PROXY flag is on.

The CSRF-cookie and reader unit tests are DB-free. The dashboard-backed tests use
a module-scoped app import (env-injected, no DB — TestClient is not entered as a
context manager so the DB-touching lifespan never runs), mirroring
tests/test_auth_session.py.
"""
from __future__ import annotations

import importlib
import os
import sys
import time
import types

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


# ─── DB-free CSRF-cookie / reader unit tests (finding C) ─────────────────────


def _set_cookie_headers(resp) -> list[str]:
    """All Set-Cookie header values off a Starlette Response (multiple allowed)."""
    return [v.decode() for (k, v) in resp.raw_headers if k == b"set-cookie"]


def test_issue_csrf_no_host_prefix_when_insecure():
    """Dev/http: only the plain telebot_csrf cookie — never a __Host- cookie
    (which the browser would drop over http)."""
    from api.auth import _issue_csrf

    resp = JSONResponse({})
    _issue_csrf(resp, secure=False)

    cookies = _set_cookie_headers(resp)
    assert any(c.startswith("telebot_csrf=") for c in cookies)
    assert not any(c.startswith("__Host-") for c in cookies)


def test_issue_csrf_sets_host_prefix_when_secure():
    """Prod/TLS: emit the __Host- prefixed cookie (Secure, Path=/, no Domain) AND
    keep the plain telebot_csrf mirror so the built SPA still reads it."""
    from api.auth import _issue_csrf

    resp = JSONResponse({})
    _issue_csrf(resp, secure=True)

    cookies = _set_cookie_headers(resp)
    host = [c for c in cookies if c.startswith("__Host-telebot_csrf=")]
    assert host, cookies
    assert "Secure" in host[0]
    assert "Path=/" in host[0]
    assert "Domain=" not in host[0]  # __Host- forbids Domain
    # Plain mirror still present for SPA compatibility.
    assert any(c.startswith("telebot_csrf=") for c in cookies)


def test_read_csrf_cookie_prefers_host_variant():
    from api.deps import read_csrf_cookie

    both = types.SimpleNamespace(
        cookies={"telebot_csrf": "plain", "__Host-telebot_csrf": "hostval"}
    )
    assert read_csrf_cookie(both) == "hostval"

    plain = types.SimpleNamespace(cookies={"telebot_csrf": "plain"})
    assert read_csrf_cookie(plain) == "plain"

    none = types.SimpleNamespace(cookies={})
    assert read_csrf_cookie(none) == ""


def test_verify_csrf_token_matches_host_cookie():
    from api.deps import verify_csrf_token

    ok = types.SimpleNamespace(
        method="POST",
        cookies={"__Host-telebot_csrf": "tok"},
        headers={"x-csrf-token": "tok"},
    )
    verify_csrf_token(ok)  # must not raise

    bad = types.SimpleNamespace(
        method="POST",
        cookies={"__Host-telebot_csrf": "tok"},
        headers={"x-csrf-token": "other"},
    )
    with pytest.raises(HTTPException) as ei:
        verify_csrf_token(bad)
    assert ei.value.status_code == 403


# ─── dashboard-backed tests (findings A, B, D) ───────────────────────────────


@pytest.fixture(scope="module")
def dash():
    """Import dashboard with a valid config env (no DB needed — app just boots)."""
    env = {
        "TG_API_ID": "1", "TG_API_HASH": "x", "TG_SESSION": "x", "TG_CHAT_IDS": "-1",
        "DISCORD_WEBHOOK_URL": "https://example", "TIMEZONE": "UTC",
        "DATABASE_URL": "postgresql://u:p@h:5432/d",
        "DASHBOARD_PASS_HASH": "$argon2id$v=19$m=65536,t=3,p=4$" + "a" * 32 + "$" + "b" * 32,
        "SESSION_SECRET": "A" * 48,
        "SESSION_COOKIE_SECURE": "false",  # TestClient runs over http
    }
    for key in ("DASHBOARD_USER", "DASHBOARD_PASS", "TRUST_PROXY"):
        os.environ.pop(key, None)
    os.environ.update(env)
    for mod in ("config", "dashboard"):
        sys.modules.pop(mod, None)
    return importlib.import_module("dashboard")


# finding B — absolute session lifetime

def test_session_within_absolute_lifetime(dash):
    now = int(time.time())
    cap = dash.SESSION_ABSOLUTE_MAX_AGE
    assert dash._session_within_absolute_lifetime({"iat": now}) is True
    assert dash._session_within_absolute_lifetime({"iat": now - cap - 100}) is False
    assert dash._session_within_absolute_lifetime({}) is False          # no iat -> over-age
    assert dash._session_within_absolute_lifetime({"iat": True}) is False  # bool is not a valid iat


def test_require_user_rejects_over_age_session(dash):
    from api.deps import require_user

    old = int(time.time()) - (dash.SESSION_ABSOLUTE_MAX_AGE + 3600)
    req = types.SimpleNamespace(session={"user": "admin", "iat": old})
    with pytest.raises(HTTPException) as ei:
        require_user(req)
    assert ei.value.status_code == 401
    assert req.session == {}  # over-age session cleared server-side


def test_require_user_accepts_fresh_session(dash):
    from api.deps import require_user

    req = types.SimpleNamespace(session={"user": "admin", "iat": int(time.time())})
    assert require_user(req) == "admin"


# finding D — proxy-header trust gate

def test_client_ip_ignores_spoofed_header_by_default(dash):
    """TRUST_PROXY unset -> spoofed X-Real-IP is ignored; direct peer wins."""
    assert dash._TRUST_PROXY is False
    req = types.SimpleNamespace(
        headers={"x-real-ip": "9.9.9.9"},
        client=types.SimpleNamespace(host="1.2.3.4"),
    )
    assert dash._client_ip(req) == "1.2.3.4"


def test_client_ip_trusts_header_when_flag_on(dash, monkeypatch):
    monkeypatch.setattr(dash, "_TRUST_PROXY", True)
    req = types.SimpleNamespace(
        headers={"x-real-ip": "9.9.9.9"},
        client=types.SimpleNamespace(host="1.2.3.4"),
    )
    assert dash._client_ip(req) == "9.9.9.9"


# finding A — logout hardening

def test_logout_get_not_allowed(dash):
    c = TestClient(dash.app)
    assert c.get("/logout").status_code == 405


def test_logout_requires_csrf(dash):
    c = TestClient(dash.app)
    c.cookies.set("telebot_csrf", "tok")
    r = c.post("/logout")  # no X-CSRF-Token header
    assert r.status_code == 403


def test_logout_clears_cookies(dash):
    c = TestClient(dash.app)
    c.cookies.set("telebot_csrf", "tok")
    r = c.post("/logout", headers={"X-CSRF-Token": "tok"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/app/login"
    raw = [v.decode() for (k, v) in r.headers.raw if k.lower() == b"set-cookie"]
    joined = " ".join(raw)
    assert "telebot_session=" in joined  # session cookie expired server-side
    assert "telebot_csrf=" in joined     # CSRF cookie expired server-side
