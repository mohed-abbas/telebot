"""Wave-0 SPA serving contract tests (SPA-01 + RESEARCH Pitfall 1).

Encodes three same-origin serving contracts for the `/app` mount added in
dashboard.py (Plan 09-02 Task 2):

  1. `/app/`            -> 200 text/html index.html shell (StaticFiles html=True).
  2. `/app/<route>`     -> 200 text/html SAME index.html (deep-link fallback).
     A hard reload of a client route has NO matching file on disk; without the
     SpaStaticFiles 404->index.html fallback this returns 404 and silently ships
     a broken dashboard. THIS is the Pitfall-1 guard.
  3. `/api/v2/*`        -> JSON (never the SPA shell). Proves the /app mount,
     registered AFTER app.include_router(api_router), does not shadow the API.

Runs BEFORE a real Vite build exists, so a stub `static/app/index.html` is
written into the repo's `static/app/` directory (module-scoped fixture) to give
the mount something to serve. Reuses the existing `api_app` fixture from
conftest.py (env-injected dashboard.app with a DryRun executor wired) — no
bespoke app construction. Does NOT touch bot core / api/ modules.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Minimal SPA shell — the `id="root"` div is the React mount point asserted on.
_STUB_INDEX_HTML = (
    "<!doctype html><html><head><title>spa</title></head>"
    '<body><div id="root"></div></body></html>'
)


@pytest.fixture(scope="module")
def spa_index(api_app):  # noqa: ARG001 — depends on api_app so app import order matches
    """Ensure static/app/index.html exists so the /app mount has a shell to serve.

    Writes a stub index.html into the repo's static/app/ directory if absent (the
    real one is produced by `cd frontend && npm run build` in CI/Docker). Leaves a
    pre-existing real bundle untouched and only removes a stub it created itself.
    """
    base_dir = Path(__file__).resolve().parent.parent
    app_dir = base_dir / "static" / "app"
    index = app_dir / "index.html"

    created_dir = not app_dir.exists()
    created_file = not index.exists()
    if created_file:
        app_dir.mkdir(parents=True, exist_ok=True)
        index.write_text(_STUB_INDEX_HTML, encoding="utf-8")

    yield index

    # Clean up only artifacts this fixture created (never a real build output).
    if created_file and index.exists():
        index.unlink()
    if created_dir and app_dir.exists():
        try:
            app_dir.rmdir()
        except OSError:
            pass  # non-empty (a real build landed) — leave it alone


@pytest.fixture
def client(api_app, spa_index):  # noqa: ARG001 — spa_index ensures the shell exists
    """TestClient over the shared dashboard.app (unauthenticated by default)."""
    return TestClient(api_app)


def test_app_root_returns_index(client):
    """GET /app/ -> 200 HTML shell with the React mount point."""
    r = client.get("/app/")
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers["content-type"]
    assert 'id="root"' in r.text


def test_app_deeplink_returns_index(client):
    """GET /app/login (no matching file) -> 200 SAME index.html, NOT 404.

    Pitfall-1 guard: html=True only serves index.html at the mount ROOT. A hard
    reload of a client route must fall back to the shell via SpaStaticFiles.
    RED until Task 2 adds the fallback.
    """
    root = client.get("/app/")
    deeplink = client.get("/app/login")
    assert deeplink.status_code == 200, deeplink.text
    assert "text/html" in deeplink.headers["content-type"]
    assert 'id="root"' in deeplink.text
    # Deep-link must serve the byte-identical shell, not a different/empty body.
    assert deeplink.text == root.text


def test_api_not_shadowed_by_spa_mount(client):
    """GET /api/v2/trading-status -> JSON, never the SPA index.html.

    Unauthenticated, the API returns a 401 JSON envelope (require_user). The
    point is the /app catch-all did NOT swallow the route into serving HTML —
    so assert on JSON content-type and that the body is not the SPA shell.
    """
    r = client.get("/api/v2/trading-status")
    assert "application/json" in r.headers["content-type"]
    assert 'id="root"' not in r.text
    # Either authenticated 200 with the status contract, or 401 JSON envelope —
    # both are JSON, both prove the API route won precedence over the /app mount.
    assert r.status_code in (200, 401)
