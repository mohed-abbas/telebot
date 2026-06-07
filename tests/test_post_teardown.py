"""CUT-03 post-teardown guard (Wave-0 standing test).

This file is the CUT-03 *teardown acceptance guard*: once Plan 12-03 deletes the
legacy HTMX routes/SSE stream/partials and flips the root, it asserts that the
deleted routes 404 (a REAL 404, not the SPA catch-all shell swallowing the path)
while the surviving routes still serve, and that `import api` still resolves (the
6 MUST-SURVIVE dashboard.py helpers the /api/v2 layer imports are not deleted).

These assertions are INTENTIONALLY RED right now and go GREEN only after 12-03
teardown lands — that staged-red behavior is the intended CUT-03 guard. The
acceptance bar for the Wave-0 plan that creates this file is "collects clean",
not "all green".

Fixture/assertion forms copied verbatim from the in-repo analogs:
  - client(api_app) fixture: tests/test_spa_serving.py:64-67
  - deleted-404 + 'id="root"' not in body: tests/test_spa_serving.py:109-119
  - surviving-200 / JSON precedence:        tests/test_spa_serving.py:94-106
  - /health 200:                            tests/test_auth_session.py:32-34
The api_app conftest fixture (conftest.py:112) pytest.skips if PostgreSQL is
absent — these tests inherit that skip, matching the rest of the suite.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(api_app):
    """TestClient over the shared dashboard.app (unauthenticated by default)."""
    return TestClient(api_app)


# Deleted legacy routes must return a REAL 404, not the SPA shell catch-all. The
# 'id="root"' guard proves the /app static mount did not swallow the path and
# serve index.html with a 200/HTML body. RED until 12-03 deletes these routes.
@pytest.mark.parametrize("deleted", ["/overview", "/stream", "/partials/positions"])
def test_deleted_legacy_route_returns_real_404(client, deleted):
    """A torn-down legacy route 404s and is NOT the SPA shell (CUT-03)."""
    r = client.get(deleted, follow_redirects=False)
    assert r.status_code == 404, r.text
    assert 'id="root"' not in r.text


def test_health_survives(client):
    """GET /health -> 200 (open route survives teardown)."""
    assert client.get("/health").status_code == 200


def test_app_root_survives(client):
    """GET /app/ -> 200 (SPA shell survives teardown)."""
    assert client.get("/app/").status_code == 200


def test_api_not_shadowed_survives(client):
    """GET /api/v2/trading-status -> JSON, status in (200, 401) (precedence intact)."""
    r = client.get("/api/v2/trading-status")
    assert "application/json" in r.headers["content-type"]
    assert 'id="root"' not in r.text
    assert r.status_code in (200, 401)


def test_root_redirects_to_app(client):
    """GET / -> 303 Location /app/ (D-02 final root flip; RED until 12-03)."""
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/app/"


def test_api_imports_resolve():
    """`import api` resolves -> the 6 MUST-SURVIVE dashboard.py helpers are intact.

    Cheap in-suite dangling-import guard (RESEARCH §Test Map): the /api/v2 layer
    imports validate_settings_form, _compute_dry_run, _enrich_stage_for_ui,
    _client_ip, _password_hasher and app_settings from dashboard.py — if teardown
    deletes any of them, `import api` raises ImportError and this fails.
    """
    import api  # noqa: F401
