# Phase 12: Parallel-run Cutover + HTMX Decommission - Pattern Map

**Mapped:** 2026-06-07
**Files analyzed:** 6 (3 NEW, 3 MODIFIED)
**Analogs found:** 6 / 6 (every file maps to an in-repo precedent — this is a cutover/decommission phase, not a build)

> Cutover/decommission phase. Most "work" is editing existing files (`dashboard.py` redirect swaps + deletions, `nginx/telebot.conf`, `Dockerfile`) and deleting files — the analog for every MODIFIED file is **its own existing pattern**. Only 3 genuinely NEW files are created; all are test/doc-shaped with exact in-repo analogs.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `tests/test_cutover_redirects.py` (NEW) | test (integration) | request-response (assert 303/Location) | `tests/test_spa_serving.py` + `tests/test_auth_session.py` | exact (same family) |
| `tests/test_post_teardown.py` (NEW) | test (integration) | request-response (assert 404 / 200) | `tests/test_spa_serving.py` + `tests/test_auth_session.py` | exact (same family) |
| `.planning/phases/12-.../12-CUTOVER-CHECKLIST.md` (NEW) | doc (operator sign-off) | n/a | `.planning/phases/06-staged-entry-execution/06-HUMAN-UAT.md` | exact (named precedent, D-04) |
| `dashboard.py` (MODIFIED — D-01 redirects, D-09/D-10 deletions) | route/app-host | request-response (redirect swap + route deletion) | own existing `RedirectResponse(...)` call site (`:384`) + `@app.get` page route shape (`:387`) | self-analog (exact) |
| `nginx/telebot.conf` (MODIFIED — D-10 commit 3, SSE block removal) | config | request-response proxy | own existing `location /` block (`:47-60`) | self-analog (exact) |
| `Dockerfile` (MODIFIED — D-10 commit 3, Stage-1 + Stage-3 COPY removal) | config (build) | batch (multi-stage build) | own existing Stage-1/Stage-3 COPY lines | self-analog (exact) |

## Pattern Assignments

### `tests/test_cutover_redirects.py` (NEW — test, request-response)

**Analog:** `tests/test_spa_serving.py` (client/fixture setup) + `tests/test_auth_session.py` (redirect/Location assertion). Both drive `dashboard.app` and live in the same suite. The codebase uses **`fastapi.testclient.TestClient`** (a sync wrapper over Starlette's ASGITransport) — NOT raw `httpx.AsyncClient`. New tests MUST follow `TestClient`, not introduce a new async client style.

**Client/fixture pattern** — reuse the shared `api_app` conftest fixture, wrap in a `TestClient`, do NOT re-import dashboard yourself (`tests/test_spa_serving.py:64-67`):
```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(api_app):  # api_app is the conftest module-scoped dashboard.app (conftest.py:112-148)
    """TestClient over the shared dashboard.app (unauthenticated by default)."""
    return TestClient(api_app)
```

**Redirect / status + Location assertion pattern** — copy `follow_redirects=False` + `status_code == 303` + `headers["location"]` assertion from `tests/test_auth_session.py:37-42`:
```python
def test_page_route_redirects_on_missing_session(app):
    c = TestClient(app)
    r = c.get("/overview", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login?next=")
```

**How to specialize for CUT-02** (assert each cut-over page 303s to its `/app/<page>` target, per RESEARCH per-page map): parameterize over the D-05 page list and assert `r.status_code == 303` and `r.headers["location"] == "/app/<page>"`. Example skeleton the planner can specify against the real pattern above:
```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(api_app):
    return TestClient(api_app)


@pytest.mark.parametrize("legacy, target", [
    ("/analytics", "/app/analytics"),
    ("/signals", "/app/signals"),
    ("/history", "/app/history"),
    ("/staged", "/app/staged"),
    ("/overview", "/app/overview"),
    ("/settings", "/app/settings"),
    ("/positions", "/app/positions"),
])
def test_legacy_page_redirects_to_spa(client, legacy, target):
    r = client.get(legacy, follow_redirects=False)
    assert r.status_code == 303, r.text
    assert r.headers["location"] == target


def test_unauth_redirects_to_app_login(client):
    # After Pitfall-4 repoint of _verify_auth (dashboard.py:146) the unauth bounce
    # goes to /app/login instead of the deleted legacy /login.
    r = client.get("/positions", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/app/login")
```
Notes: the `api_app` fixture `pytest.skip`s if PostgreSQL is absent (`conftest.py:144-145`) — redirect tests do not touch the DB but inherit the skip; that matches the rest of the suite and is fine. `follow_redirects=False` is mandatory or `TestClient` follows the 303 and you assert against the wrong response.

---

### `tests/test_post_teardown.py` (NEW — test, request-response)

**Analog:** same family — `tests/test_spa_serving.py:94-119` already asserts both a route that must serve (`/app/`, `/api/v2/*`) and a path that must 404 (`/app/assets/missing-abc.js` → 404). That is exactly the "surviving 200 / deleted 404" shape this file needs.

**Surviving-route 200 + JSON-precedence pattern** (`tests/test_spa_serving.py:94-106`):
```python
def test_api_not_shadowed_by_spa_mount(client):
    r = client.get("/api/v2/trading-status")
    assert "application/json" in r.headers["content-type"]
    assert 'id="root"' not in r.text
    assert r.status_code in (200, 401)
```

**Deleted-route 404 pattern** (`tests/test_spa_serving.py:109-119`):
```python
def test_missing_asset_returns_404_not_shell(client):
    r = client.get("/app/assets/missing-abc.js")
    assert r.status_code == 404, r.text
    assert 'id="root"' not in r.text
```

**Health 200 pattern** (`tests/test_auth_session.py:32-34`):
```python
def test_health_route_open(app):
    c = TestClient(app)
    assert c.get("/health").status_code == 200
```

**How to specialize for CUT-03** (RESEARCH §Phase Requirements → Test Map, line 431): assert deleted legacy routes 404, surviving routes 200/JSON, `/` post-final-cutover 303→`/app/`, and that `import api` resolves (the 6-helper guard). Reuse the same `client(api_app)` fixture from the cutover test. Targets to assert: `GET /overview` → 404, `GET /stream` → 404, `GET /partials/positions` → 404, `GET /health` → 200, `GET /app/` → 200, `GET /api/v2/trading-status` → JSON, `GET /` → 303 `/app/`. The `import dashboard` / `import api` dangling-import guard (RESEARCH line 432) is a `python -c` smoke command, not a pytest assertion — keep it in the plan's gate, not necessarily in this file (though a `def test_api_imports_resolve(): import api` is a cheap in-suite guard for the MUST-SURVIVE list).

---

### `.planning/phases/12-.../12-CUTOVER-CHECKLIST.md` (NEW — operator sign-off doc)

**Analog:** `.planning/phases/06-staged-entry-execution/06-HUMAN-UAT.md` (named precedent in D-04 / CONTEXT line 184). Mirror its structure exactly: YAML frontmatter (`status / phase / source / started / updated`), a `## Tests` section with numbered rows each having an `expected:` line + a `result: [pending]` line, then a `## Summary` tally block.

**Frontmatter + row + summary structure to copy** (`06-HUMAN-UAT.md:1-46`):
```markdown
---
status: partial
phase: 12-parallel-run-cutover-htmx-decommission
source: [12-RESEARCH.md, 12-CONTEXT.md]
started: 2026-06-07T00:00:00Z
updated: 2026-06-07T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. <page> SPA matches legacy on live data
expected: <parity items — SPA data matches legacy on live data; live-money actions behave correctly; no console errors; poll-safe modals/drilldowns>
result: [pending]

## Summary

total: <n>
passed: 0
issues: 0
pending: <n>
skipped: 0
blocked: 0

## Gaps
```

**Specialization for D-04/D-05:** one numbered row PER PAGE in D-05 cutover order (`analytics → signals → history → staged → overview → settings → positions → kill-switch`). Per-page parity items per D-04: (a) SPA data matches legacy on live data, (b) live-money actions behave correctly, (c) no console errors, (d) poll-safe modals/drilldowns. Each row carries an operator-dated sign-off (extend the `result:` line to a dated `[signed: YYYY-MM-DD operator]` per D-04). Each D-01 redirect commit references its row number. The `06-HUMAN-UAT.md` rows already model "expected behavior → pending result" per scenario — same shape, one per page instead of one per scenario.

---

### `dashboard.py` (MODIFIED — self-analog)

**Analog:** the file's OWN existing patterns. Two shapes the planner anchors to:

**D-01 per-page redirect swap — anchor to the existing `RedirectResponse` import + call style already in the file.** `RedirectResponse` is already imported (`dashboard.py:22`) and already used for the root redirect (`dashboard.py:382-384`):
```python
# dashboard.py:22 — already imported (D-10 Commit 1 will split this import to keep ONLY RedirectResponse)
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse

# dashboard.py:382-384 — the EXISTING root redirect call style D-01/D-02 mirror:
@app.get("/", response_class=HTMLResponse)
async def root(request: Request, user: str = Depends(_verify_auth)):
    return RedirectResponse(url="/overview")
```
D-01 swaps each cut-over page's body to this exact call style **with `status_code=303`** (the page routes are GET→GET; 303 forces GET). Keep `Depends(_verify_auth)` so an unauth hit still bounces to login, not into the SPA. The existing 303 call style is already in the file at `:362` (`RedirectResponse(url=next_path, status_code=303)`) — use that import + keyword form, not a bare string:
```python
# Per-page swap shape (D-01), anchored to the dashboard.py:362 status_code=303 call form:
@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, user: str = Depends(_verify_auth)):
    return RedirectResponse(url="/app/analytics", status_code=303)
```

**D-02 final root flip** — change `dashboard.py:384` body from `RedirectResponse(url="/overview")` to `RedirectResponse(url="/app/", status_code=303)` LAST, after every page is cut over.

**D-09/D-10 deletion-target shape** — the deletion unit is a whole `@app.get("/<page>", response_class=HTMLResponse)` route returning `templates.TemplateResponse(...)` (analog: `overview` route `dashboard.py:387-408`). The planner deletes these route blocks wholesale in Commit 1. **MUST-SURVIVE** the 6 `api/`-imported helpers (RESEARCH lines 262-269) — do NOT delete `validate_settings_form`, `_compute_dry_run`, `_enrich_stage_for_ui`, `_client_ip`, `_password_hasher`, `app_settings`.

**Pitfall-4 repoint** — `_verify_auth`'s `headers={"Location": f"/login?next={next_path}"}` (`dashboard.py:146`) must be repointed to `/app/login` in Commit 1, or every unauth bounce 404s after legacy `/login` is deleted.

---

### `nginx/telebot.conf` (MODIFIED — self-analog)

**Analog:** the file's own `location /` block (`nginx/telebot.conf:47-60`). D-10 Commit 3 deletes ONLY the SSE sub-block (`:54-59` — `proxy_buffering off` / `proxy_cache off` / `proxy_http_version 1.1` / `proxy_set_header Connection ''` / `proxy_read_timeout 86400s`). KEEP the base `proxy_pass` + `proxy_set_header` lines (`:47-53`) and the `location = /login` rate-limit block (`:36-45`). Ordering constraint: Commit 1 (delete `/stream`) must deploy before this nginx edit (Pitfall 2). VPS deploy is an operator copy-paste step (`docker exec shared-nginx nginx -s reload`).

---

### `Dockerfile` (MODIFIED — self-analog)

**Analog:** the file's own multi-stage COPY pattern. D-10 Commit 3 deletes Stage 1 `css-build` entirely (`Dockerfile:1-40`) AND the Stage-3 lines that reference now-deleted dirs/stages — `COPY templates/ ./templates/` (`:63`), `COPY --from=css-build /build/static/css/app.*.css` (`:68`), `COPY --from=css-build .../manifest.json` (`:69`). KEEP Stage 2 `spa-build` (`:42-52`) and the SPA overlay `COPY --from=spa-build /spa/dist/ ./static/app/` (`:72`). **RESEARCH Pitfall 1:** CONTEXT's D-10 list omits `:63,68,69`; the planner MUST add them or `docker build` fails. Gate this commit with `docker build .`.

## Shared Patterns

### Test client construction (applies to BOTH new test files)
**Source:** `tests/test_spa_serving.py:64-67` (the `client(api_app)` fixture) + `tests/conftest.py:112-148` (the `api_app` module-scoped fixture).
**Apply to:** `test_cutover_redirects.py`, `test_post_teardown.py`.
```python
@pytest.fixture
def client(api_app):
    return TestClient(api_app)
```
Do NOT re-implement env-injection/`importlib.import_module("dashboard")` in the new files — `conftest.py::api_app` already does it (env-inject → `sys.modules.pop` → re-import → `init_dashboard` with DryRun executor → `pytest.skip` if no Postgres). `test_auth_session.py:12-29` shows the in-file env-inject form ONLY because it predates the conftest fixture; new files should depend on `api_app` instead.

### Redirect assertion (applies to cutover test)
**Source:** `tests/test_auth_session.py:37-42`.
**Apply to:** `test_cutover_redirects.py`.
```python
r = c.get("/overview", follow_redirects=False)
assert r.status_code == 303
assert r.headers["location"].startswith("/login?next=")  # → "/app/<page>" for cutover
```
`follow_redirects=False` is load-bearing — without it `TestClient` follows the 303 and you assert against the destination, not the redirect.

### 404 / surviving-200 assertion (applies to teardown test)
**Source:** `tests/test_spa_serving.py:94-119`.
**Apply to:** `test_post_teardown.py`.
Surviving routes assert `status_code in (200, 401)` + JSON content-type (precedence proof); deleted routes assert `status_code == 404` and `'id="root"' not in r.text` (proves it's a real 404, not the SPA shell catch-all swallowing it).

### Operator sign-off doc structure
**Source:** `.planning/phases/06-staged-entry-execution/06-HUMAN-UAT.md:1-46`.
**Apply to:** `12-CUTOVER-CHECKLIST.md`.
Frontmatter (`status/phase/source/started/updated`) → numbered `### N. <title>` rows each with `expected:` + `result:` → `## Summary` tally.

## No Analog Found

None. Every NEW file maps to a named in-repo precedent and every MODIFIED file's analog is its own existing call-site pattern. The phase introduces no new role/data-flow that the codebase has not already exercised.

## Metadata

**Analog search scope:** `tests/` (40 files — focused on the `TestClient`-over-`dashboard.app` family: `test_spa_serving.py`, `test_auth_session.py`, `test_api_csrf.py`, `conftest.py`), `dashboard.py` (RedirectResponse import + call sites + page-route shape), `nginx/telebot.conf`, `Dockerfile`, `.planning/phases/06-.../06-HUMAN-UAT.md`.
**Files scanned:** 7 source/test/doc files read; `tests/` directory enumerated.
**Pattern extraction date:** 2026-06-07
**Line-number caveat (from RESEARCH):** `dashboard.py` line numbers drift on any edit — re-verify before each commit if the file was edited earlier in the plan.
