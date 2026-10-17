"""CUT-03 post-teardown guard.

Asserts that the deleted legacy HTMX routes 404 (a REAL 404, not the SPA
catch-all shell swallowing the path) while the surviving routes still serve,
and that `import api` still resolves (the MUST-SURVIVE dashboard.py helpers the
/api/v2 layer imports are not deleted).

Harness: conftest `api_app` + `make_api_client` (httpx on the session loop) and
`spa_index` (a stub static/app/index.html when no Vite build is present).
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from tests.conftest import api_login, make_api_client


@pytest_asyncio.fixture
async def client(api_app, spa_index):  # noqa: ARG001 — spa_index ensures the shell exists
    """Unauthenticated client over the shared dashboard.app."""
    async with make_api_client(api_app) as c:
        yield c


# Deleted legacy routes must return a REAL 404, not the SPA shell catch-all. The
# 'id="root"' guard proves the /app static mount did not swallow the path and
# serve index.html with a 200/HTML body.
@pytest.mark.parametrize("deleted", ["/overview", "/stream", "/partials/positions"])
async def test_deleted_legacy_route_returns_real_404(client, deleted):
    """A torn-down legacy route 404s and is NOT the SPA shell (CUT-03)."""
    r = await client.get(deleted)
    assert r.status_code == 404, r.text
    assert 'id="root"' not in r.text


async def test_health_survives(client):
    """GET /health -> 200 (open route survives teardown)."""
    assert (await client.get("/health")).status_code == 200


async def test_app_root_survives(client):
    """GET /app/ -> 200 (SPA shell survives teardown)."""
    assert (await client.get("/app/")).status_code == 200


async def test_api_not_shadowed_survives(client):
    """GET /api/v2/trading-status -> JSON, status in (200, 401) (precedence intact)."""
    r = await client.get("/api/v2/trading-status")
    assert "application/json" in r.headers["content-type"]
    assert 'id="root"' not in r.text
    assert r.status_code in (200, 401)


async def test_root_redirects_to_app(client):
    """GET / -> 303 to the SPA (D-02 root flip).

    Unauthenticated hits bounce to the SPA login first; a logged-in session is
    sent straight to /app/.
    """
    r = await client.get("/")
    assert r.status_code == 303, r.text
    assert r.headers["location"].startswith("/app/login?next=")

    await api_login(client)
    r = await client.get("/")
    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/app/"


def test_api_imports_resolve():
    """`import api` resolves -> the MUST-SURVIVE dashboard.py helpers are intact.

    Cheap in-suite dangling-import guard: the /api/v2 layer imports
    validate_settings_form, _compute_dry_run, _enrich_stage_for_ui, _client_ip,
    _password_hasher and app_settings from dashboard.py — if teardown deletes any
    of them, `import api` raises ImportError and this fails.
    """
    import api  # noqa: F401
