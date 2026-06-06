---
phase: 09-spa-scaffold-auth-design-system
plan: 02
subsystem: infra
tags: [fastapi, starlette, staticfiles, spa, vite, docker, serving]

# Dependency graph
requires:
  - phase: 08-json-api-foundation
    provides: /api/v2 JSON router (the surface the /app mount must NOT shadow) + bot-core diff guard
  - phase: 09-spa-scaffold-auth-design-system (Plan 01)
    provides: frontend/ Vite+React scaffold with base:/app/ that this serving substrate ships
provides:
  - uvicorn StaticFiles /app mount serving the built SPA same-origin (no nginx, no prod Node)
  - SpaStaticFiles deep-link fallback (404 -> index.html) so /app/<route> hard reloads resolve the shell
  - Dockerfile node:22-slim spa-build stage + single dist COPY into the Node-free runtime
  - Wave-0 serving test encoding root + deep-link + API-not-shadowed contracts
affects: [10-read-only-page-migration, 11-live-money-pages, 12-parallel-run-cutover]

# Tech tracking
tech-stack:
  added: [node:22-slim Docker build stage]
  patterns:
    - "SpaStaticFiles: StaticFiles subclass overriding get_response to fall back to index.html on 404"
    - "SPA mount registered AFTER api_router so /api/v2/* always wins route precedence"
    - "Node confined to a build stage only; runtime image stays python:3.12-slim (minimize-deps)"

key-files:
  created:
    - tests/test_spa_serving.py
  modified:
    - dashboard.py
    - Dockerfile
    - .dockerignore

key-decisions:
  - "D-01: SPA served under /app/ subpath with deep-link/index.html fallback for client routes"
  - "D-02: uvicorn StaticFiles serves the bundle (not nginx); /api/v2 unshadowed by registering mount last"
  - "D-03: Dockerfile gains node:22-slim AS spa-build; runtime stays python:3.12-slim (no prod Node); css-build coexists"

patterns-established:
  - "SpaStaticFiles subclass: self-contained SPA catch-all scoped to the mount — structurally cannot shadow sibling routers"
  - "check_dir=False on the /app mount keeps the app importable before a Vite build exists (tests/dev)"

requirements-completed: [SPA-01]

# Metrics
duration: 8min
completed: 2026-06-06
---

# Phase 9 Plan 02: SPA Serving Substrate Summary

**uvicorn StaticFiles `/app` mount with a SpaStaticFiles 404→index.html deep-link fallback, plus a node:22-slim Dockerfile build stage that ships the Vite bundle into a Node-free python:3.12-slim runtime — /api/v2 left unshadowed.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-06T10:23:06+02:00 (first task commit)
- **Completed:** 2026-06-06T10:24:49+02:00 (last task commit)
- **Tasks:** 3
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments
- Same-origin SPA serving at `/app/` via a `SpaStaticFiles` subclass that falls back to `index.html` on a 404 — fixing RESEARCH Pitfall 1 (deep-link hard reloads that would otherwise 404 and silently ship a broken dashboard).
- Mount registered AFTER `app.include_router(api_router)` and the `/static` mount, so `/api/v2/*` keeps route precedence and is never swallowed by the `/app` catch-all (verified: unauthenticated `/api/v2/trading-status` returns a 401 JSON envelope, not the SPA shell).
- Dockerfile `node:22-slim AS spa-build` stage (`npm ci` + `npm run build` → `/spa/dist`) with a single `COPY --from=spa-build /spa/dist/ ./static/app/`; the runtime stays `python:3.12-slim` with no Node (SPA-01 minimize-deps). The existing `css-build` stage is untouched and coexists until Phase 12.
- `.dockerignore` now excludes `frontend/node_modules` + `frontend/dist` (regenerated in the build stage) while keeping `frontend/` source in the build context.
- Wave-0 serving test (`tests/test_spa_serving.py`) encodes the three contracts and ships a stub `static/app/index.html` fixture so the mount has a shell pre-build.

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave-0 serving test** - `b7cc9b0` (test)
2. **Task 2: dashboard.py /app mount + deep-link fallback** - `2fc4159` (feat)
3. **Task 3: Dockerfile spa-build stage + .dockerignore** - `10f1f0e` (feat)

## Files Created/Modified
- `tests/test_spa_serving.py` (created) - Wave-0 contracts: `/app/` shell, `/app/login` deep-link fallback, `/api/v2/trading-status` stays JSON; module-scoped stub-index fixture.
- `dashboard.py` (modified) - `SpaStaticFiles(StaticFiles)` subclass + `/app` mount (`html=True, check_dir=False`) registered after the API router and `/static` mount; added `starlette.exceptions.HTTPException` + `starlette.responses.Response` imports.
- `Dockerfile` (modified) - new `FROM node:22-slim AS spa-build` stage; one `COPY --from=spa-build /spa/dist/ ./static/app/` overlay in the runtime stage.
- `.dockerignore` (modified) - excludes `frontend/node_modules` and `frontend/dist`; keeps `frontend/`.

## Decisions Made
None beyond the plan — followed D-01/D-02/D-03 as specified. Chose `check_dir=False` on the `/app` mount (allowed by the plan's "guard against a missing static/app/ directory at import time" instruction) so the app imports cleanly before any Vite build exists.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- **Full backend suite shows 71 pre-existing failures when PostgreSQL is unavailable.** Confirmed pre-existing by running the suite at the pre-plan-02 baseline (commit 9bbe2b0): identical 71 failed / 19 error count. Files like `tests/test_settings_form.py` pass fully (12/12) in isolation — the failures are cross-file DB-pool fixture-ordering contamination once a session-scoped pool is absent, not logic regressions. Plan 02 added 3 passing tests (260 → 263) and introduced zero new failures. The new serving tests skip cleanly without a DB (the `api_app` fixture `pytest.skip`s on DB absence). Logged to `deferred-items.md`; out of scope for this presentation-layer plan. The `/app` mount + fallback + API-not-shadowed contracts were verified directly via a TestClient smoke check (root 200 HTML, deep-link 200 byte-identical shell, `/api/v2/trading-status` 401 JSON).
- **Bot-core diff guard:** PASSED. `git diff` shows zero changes to `executor.py`, `trade_manager.py`, `db.py`, `mt5_connector.py`, and the `api/` package — only `dashboard.py` changed in app code.

## User Setup Required
None - no external service configuration required. (Note: the nginx `/api/v2/auth/login` rate-limit block — Phase 8 D-14 — remains a deploy/UAT artifact flagged in the threat model, not gated by this plan.)

## Next Phase Readiness
- Serving substrate is ready: once `cd frontend && npm run build` produces `static/app/`, the dashboard serves the SPA at `/app/` with working deep-links and an unshadowed API.
- Phase 10 (read-only page migration) can build pages against this mount with confidence that hard reloads resolve the shell.
- No blockers. The 71 pre-existing DB-absent test failures should be resolved by running the suite against a live PostgreSQL (`docker compose -f docker-compose.dev.yml up -d`) — independent of this plan.

## Self-Check: PASSED

All created/modified files exist on disk; all three task commits (b7cc9b0, 2fc4159, 10f1f0e) are present in git history.

---
*Phase: 09-spa-scaffold-auth-design-system*
*Completed: 2026-06-06*
