"""End-to-end login flow against a real FastAPI TestClient with an argon2-known-good hash."""
from __future__ import annotations

import importlib
import os
import sys

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient


KNOWN_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(scope="module")
def known_hash():
    return PasswordHasher().hash(KNOWN_PASSWORD)


@pytest.fixture(scope="module")
def app(known_hash):
    env = {
        "TG_API_ID": "1", "TG_API_HASH": "x", "TG_SESSION": "x", "TG_CHAT_IDS": "-1",
        "DISCORD_WEBHOOK_URL": "https://example", "TIMEZONE": "UTC",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql://telebot:telebot_dev@localhost:5433/telebot",
        ),
        "DASHBOARD_PASS_HASH": known_hash,
        "SESSION_SECRET": "A" * 48,
        "SESSION_COOKIE_SECURE": "false",
    }
    for key in ("DASHBOARD_USER", "DASHBOARD_PASS"):
        os.environ.pop(key, None)
    os.environ.update(env)
    for mod in ("config", "dashboard", "db"):
        sys.modules.pop(mod, None)
    dashboard = importlib.import_module("dashboard")
    # Open DB pool (init_db matches prod boot sequence — needed for failed_login helpers)
    import db
    import asyncio
    try:
        asyncio.get_event_loop().run_until_complete(db.init_db(env["DATABASE_URL"]))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available for login flow tests: {exc}")
    yield dashboard.app
    try:
        asyncio.get_event_loop().run_until_complete(db.close_db())
    except Exception:
        pass


def _get_login_form(client: TestClient):
    r = client.get("/login")
    assert r.status_code == 200
    # Extract csrf_token from the form
    import re
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    assert m, "csrf_token missing from /login form"
    return m.group(1), r.cookies


def test_get_login_sets_csrf_cookie_and_renders_form(app):
    c = TestClient(app)
    r = c.get("/login")
    assert r.status_code == 200
    assert "telebot_login_csrf" in r.cookies
    assert "name=\"password\"" in r.text

def test_post_login_rejects_missing_csrf(app):
    c = TestClient(app)
    r = c.post("/login", data={"password": KNOWN_PASSWORD, "csrf_token": "bogus"}, follow_redirects=False)
    assert r.status_code == 400
    assert "try again" in r.text.lower()

def test_post_login_happy_path_sets_session_and_redirects(app):
    c = TestClient(app)
    token, _ = _get_login_form(c)
    r = c.post(
        "/login",
        data={"password": KNOWN_PASSWORD, "csrf_token": token, "next_path": "/overview"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/overview"
    # Session cookie present after success
    assert "telebot_session" in c.cookies

def test_post_login_wrong_password_returns_401_and_increments_counter(app):
    c = TestClient(app)
    token, _ = _get_login_form(c)
    r = c.post(
        "/login",
        data={"password": "nope", "csrf_token": token, "next_path": "/overview"},
        follow_redirects=False,
        headers={"X-Real-IP": "10.99.0.1"},  # isolate this test's counter
    )
    assert r.status_code == 401
    # Verify DB row was written
    import asyncio, db
    count = asyncio.get_event_loop().run_until_complete(
        db.get_failed_login_count("10.99.0.1", minutes=15)
    )
    assert count >= 1

def test_htmx_login_emits_hx_redirect(app):
    c = TestClient(app)
    token, _ = _get_login_form(c)
    r = c.post(
        "/login",
        data={"password": KNOWN_PASSWORD, "csrf_token": token, "next_path": "/overview"},
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers.get("HX-Redirect") == "/overview"

def test_logout_clears_session_and_redirects(app):
    c = TestClient(app)
    # Log in first
    token, _ = _get_login_form(c)
    c.post(
        "/login",
        data={"password": KNOWN_PASSWORD, "csrf_token": token, "next_path": "/overview"},
        follow_redirects=False,
    )
    assert "telebot_session" in c.cookies
    r = c.get("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
    # Subsequent protected access redirects to /login
    r2 = c.get("/overview", follow_redirects=False)
    assert r2.status_code == 303
    assert r2.headers["location"].startswith("/login?next=")

def test_authenticated_user_skipping_login_form_redirects_to_next(app):
    c = TestClient(app)
    token, _ = _get_login_form(c)
    c.post("/login", data={"password": KNOWN_PASSWORD, "csrf_token": token}, follow_redirects=False)
    r = c.get("/login?next=/positions", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/positions"

def test_csrf_cookie_scoped_to_login_path(app):
    c = TestClient(app)
    c.get("/login")
    csrf_cookie = next(
        (ck for ck in c.cookies.jar if ck.name == "telebot_login_csrf"),
        None,
    )
    assert csrf_cookie is not None
    assert csrf_cookie.path == "/login", "CSRF cookie must be path-scoped (T-5-10 mitigation)"
