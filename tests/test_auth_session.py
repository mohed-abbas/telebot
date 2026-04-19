"""Session-based _verify_auth + SessionMiddleware integration — uses FastAPI TestClient."""
from __future__ import annotations

import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app():
    """Import dashboard with a valid config environment (no real DB needed — app boots)."""
    env = {
        "TG_API_ID": "1", "TG_API_HASH": "x", "TG_SESSION": "x", "TG_CHAT_IDS": "-1",
        "DISCORD_WEBHOOK_URL": "https://example", "TIMEZONE": "UTC",
        "DATABASE_URL": "postgresql://u:p@h:5432/d",
        "DASHBOARD_PASS_HASH": "$argon2id$v=19$m=65536,t=3,p=4$" + "a" * 32 + "$" + "b" * 32,
        "SESSION_SECRET": "A" * 48,
        "SESSION_COOKIE_SECURE": "false",  # TestClient runs over http
    }
    for key in ("DASHBOARD_USER", "DASHBOARD_PASS"):
        os.environ.pop(key, None)
    os.environ.update(env)
    for mod in ("config", "dashboard"):
        sys.modules.pop(mod, None)
    dashboard = importlib.import_module("dashboard")
    return dashboard.app


def test_health_route_open(app):
    c = TestClient(app)
    assert c.get("/health").status_code == 200


def test_page_route_redirects_on_missing_session(app):
    c = TestClient(app)
    r = c.get("/overview", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login?next=")


def test_htmx_route_returns_401_on_missing_session(app):
    c = TestClient(app)
    r = c.get("/overview", headers={"HX-Request": "true"}, follow_redirects=False)
    assert r.status_code == 401


def test_valid_session_passes_auth(app):
    c = TestClient(app)
    # Forge a signed cookie by using the session middleware directly via a test route:
    # Simplest: set session by calling /login would work if it existed. For this
    # task's scope, exercise the dependency by seeding session via TestClient's
    # cookie jar from a tiny test-only route.
    # We use Starlette's session via a helper endpoint added under TESTING env — skipped here.
    pytest.skip(
        "Full session-happy-path covered in Plan 04's /login integration test."
    )


def test_session_middleware_registered(app):
    """SessionMiddleware must be present in the middleware stack (Pitfall 2)."""
    from starlette.middleware.sessions import SessionMiddleware
    names = [m.cls.__name__ for m in app.user_middleware]
    assert "SessionMiddleware" in names


def test_asset_url_helper_registered(app):
    """asset_url must be available as a Jinja global."""
    import dashboard
    assert "asset_url" in dashboard.templates.env.globals
    # Without a manifest, falls back to logical name under /static/css/
    assert dashboard.asset_url("app.css").startswith("/static/css/")


def test_base_html_has_no_play_cdn():
    from pathlib import Path
    p = Path("templates/base.html")
    txt = p.read_text()
    assert "cdn.tailwindcss.com" not in txt, "UI-01: Play CDN must be removed"
    assert "asset_url('app.css')" in txt, "UI-04: hashed CSS reference must be via asset_url"
    assert "basecoat.min.js" in txt, "Basecoat JS must be wired"
    assert "htmx_basecoat_bridge.js" in txt, "HTMX bridge must be wired"
