"""CUT-02 per-page cutover redirect guard (Wave-0 standing test).

This file is the CUT-02 *progress guard*: it asserts that each legacy HTMX page
route 303-redirects to its `/app/<page>` SPA target, and that an unauthenticated
hit bounces to `/app/login`.

The per-page assertions are INTENTIONALLY RED right now and go GREEN one row at a
time as Plan 12-02 swaps each page's route body to
`RedirectResponse(url="/app/<page>", status_code=303)` (D-01). The
`test_unauth_redirects_to_app_login` case stays RED until 12-03 Commit 1 repoints
`_verify_auth`'s `Location` header to `/app/login` (RESEARCH Pitfall 4). That
staged-red behavior is the intended CUT-02 guard — the acceptance bar for the
Wave-0 plan that creates this file is "collects clean", not "all green".

CUT-01 note: parallel-run is already satisfied by Phase-9 routing with ZERO code
change (RESEARCH §CUT-01). The evidence is
`tests/test_spa_serving.py::test_api_not_shadowed_by_spa_mount` — the /api/v2
router is registered BEFORE the /app static mount, so the API is never shadowed.
That test is the CUT-01 confirmation; it lives in test_spa_serving.py, not here.

Fixture/assertion forms copied verbatim from the in-repo analogs:
  - client(api_app) fixture: tests/test_spa_serving.py:64-67
  - follow_redirects=False + 303 + Location: tests/test_auth_session.py:37-42
The api_app conftest fixture (conftest.py:112) env-injects + re-imports dashboard
and pytest.skips if PostgreSQL is absent — these redirect tests inherit that skip
(they do not touch the DB) which matches the rest of the suite.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(api_app):
    """TestClient over the shared dashboard.app (unauthenticated by default)."""
    return TestClient(api_app)


# D-05 cutover order (the 7 legacy GET pages that swap to a /app/<page> redirect).
# Each row goes GREEN as Plan 12-02 cuts that page over; RED until then.
@pytest.mark.parametrize(
    "legacy, target",
    [
        ("/analytics", "/app/analytics"),
        ("/signals", "/app/signals"),
        ("/history", "/app/history"),
        ("/staged", "/app/staged"),
        ("/overview", "/app/overview"),
        ("/settings", "/app/settings"),
        ("/positions", "/app/positions"),
    ],
)
def test_legacy_page_redirects_to_spa(client, legacy, target):
    """Each legacy page 303-redirects to its /app/<page> SPA target (CUT-02).

    follow_redirects=False is load-bearing: without it TestClient follows the 303
    and we would assert against the destination response, not the redirect itself
    (so a typo like /app/analytic would slip through silently).
    """
    r = client.get(legacy, follow_redirects=False)
    assert r.status_code == 303, r.text
    assert r.headers["location"] == target


def test_unauth_redirects_to_app_login(client):
    """An unauth GET to a surviving route bounces 303 to /app/login (CUT-02).

    RED until 12-03 Commit 1 repoints _verify_auth's Location header from the
    legacy /login to /app/login (RESEARCH Pitfall 4) — otherwise every unauth
    bounce 404s once legacy /login is deleted.
    """
    r = client.get("/positions", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/app/login")
