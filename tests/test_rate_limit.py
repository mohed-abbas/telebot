"""App-level rate limit (AUTH-05, D-17) — independent of nginx."""
from __future__ import annotations

import importlib
import os
import sys
import asyncio

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app():
    env = {
        "TG_API_ID": "1", "TG_API_HASH": "x", "TG_SESSION": "x", "TG_CHAT_IDS": "-1",
        "DISCORD_WEBHOOK_URL": "https://example", "TIMEZONE": "UTC",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql://telebot:telebot_dev@localhost:5433/telebot",
        ),
        "DASHBOARD_PASS_HASH": PasswordHasher().hash("x" * 16),
        "SESSION_SECRET": "A" * 48,
        "SESSION_COOKIE_SECURE": "false",
    }
    for key in ("DASHBOARD_USER", "DASHBOARD_PASS"):
        os.environ.pop(key, None)
    os.environ.update(env)
    for mod in ("config", "dashboard", "db"):
        sys.modules.pop(mod, None)
    dashboard = importlib.import_module("dashboard")
    import db
    try:
        asyncio.get_event_loop().run_until_complete(db.init_db(env["DATABASE_URL"]))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")
    yield dashboard.app
    try:
        asyncio.get_event_loop().run_until_complete(db.close_db())
    except Exception:
        pass


def _csrf(c: TestClient):
    import re
    r = c.get("/login")
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    return m.group(1) if m else None


def test_five_failures_triggers_lockout(app):
    c = TestClient(app)
    ip = "10.99.77.42"
    for _ in range(5):
        token = _csrf(c)
        r = c.post(
            "/login",
            data={"password": "wrong", "csrf_token": token, "next_path": "/overview"},
            headers={"X-Real-IP": ip},
            follow_redirects=False,
        )
        assert r.status_code == 401
    # 6th attempt hits the lockout
    token = _csrf(c)
    r = c.post(
        "/login",
        data={"password": "wrong", "csrf_token": token, "next_path": "/overview"},
        headers={"X-Real-IP": ip},
        follow_redirects=False,
    )
    assert r.status_code == 429
    assert "15 minutes" in r.text

def test_success_clears_counter(app):
    c = TestClient(app)
    ip = "10.99.88.1"
    # Record 2 failures
    for _ in range(2):
        token = _csrf(c)
        c.post(
            "/login",
            data={"password": "wrong", "csrf_token": token, "next_path": "/overview"},
            headers={"X-Real-IP": ip},
            follow_redirects=False,
        )
    import db
    assert asyncio.get_event_loop().run_until_complete(
        db.get_failed_login_count(ip, minutes=15)
    ) == 2
    # Successful login (password matches the known test hash: "x"*16)
    token = _csrf(c)
    r = c.post(
        "/login",
        data={"password": "x" * 16, "csrf_token": token, "next_path": "/overview"},
        headers={"X-Real-IP": ip},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert asyncio.get_event_loop().run_until_complete(
        db.get_failed_login_count(ip, minutes=15)
    ) == 0, "Successful login must clear the IP's failure counter (D-17)"
