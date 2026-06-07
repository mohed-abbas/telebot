---
phase: 12-parallel-run-cutover-htmx-decommission
plan: 03
subsystem: htmx-decommission
tags: [teardown, htmx-decommission, cutover, dashboard, dockerfile, nginx, deploy-at-end]
requires:
  - dashboard.py legacy redirect-only page routes (12-02)
  - dashboard.py _verify_auth /login bounce (Pitfall 4 repoint target)
  - tests/test_post_teardown.py (12-01 CUT-03 guard)
  - templates/, static/vendor/, static/js/htmx_basecoat_bridge.js (legacy HTMX assets)
  - Dockerfile Stage-1 css-build + Stage-3 COPY lines
  - nginx/telebot.conf SSE block
provides:
  - dashboard.py reduced to surviving wiring (app host + 6 api/-imported helpers + auth + mounts)
  - _verify_auth + /logout repointed to /app/login (Pitfall 4 resolved)
  - templates/ + Basecoat vendor + HTMX bridge deleted
  - Dockerfile css-build stage removed + Stage-3 COPY corrected; docker build green
  - nginx SSE block removed; /login rate-limit block preserved
  - HTMX-era tests pruned; test_post_teardown.py green-or-skip
affects:
  - Phase 12 complete (CUT-01/02/03 all landed); HTMX/Jinja stack fully decommissioned
  - VPS deploy: operator must copy nginx/telebot.conf + reload nginx (see Operator Deploy Step)
tech-stack:
  added: []
  patterns:
    - "4 grouped, independently-revertable teardown commits (D-10): routes/SSE/Jinja | templates/vendor/bridge | Dockerfile/CSS-CLI/nginx | tests"
    - "Delete-and-keep surgery: 6 api/-imported helpers preserved while the HTMX presentation surface is removed (D-09)"
    - "import dashboard + import api as the 6-helper dangling-import guard (Pitfall 3)"
key-files:
  created:
    - .planning/phases/12-parallel-run-cutover-htmx-decommission/12-03-SUMMARY.md
    - .planning/phases/12-parallel-run-cutover-htmx-decommission/deferred-items.md
  modified:
    - dashboard.py
    - Dockerfile
    - nginx/telebot.conf
    - tests/test_auth_session.py
    - tests/test_api_csrf.py
  deleted:
    - templates/ (21 Jinja files)
    - static/vendor/basecoat/ (basecoat.css, basecoat.min.js)
    - static/js/htmx_basecoat_bridge.js
    - tailwind.config.js
    - static/css/input.css
    - static/css/_compat.css
    - scripts/build_css.sh
    - tests/test_ui_substrate.py
    - tests/test_pending_stages_sse.py
    - tests/test_settings_form.py
    - tests/test_login_flow.py
decisions:
  - "Deploy-at-end: the post-cutover 7-day live bake + operator GO checkpoint (D-07/D-08) was WAIVED for this run (operator pre-authorized). Teardown code written + verified locally now; the single live bake + GO happens once end-to-end on the VPS at final deploy. No operator sign-offs fabricated."
  - "dashboard.py reduced to wiring (D-09): 985 deletions, 43 net wiring lines; the 6 api/-imported helpers + transitive deps + data helpers + app factory/mounts/auth/health all preserved"
  - "_verify_auth + /logout repointed to /app/login (Pitfall 4) so the unauth bounce does not 404 after legacy /login deletion"
  - "3 pre-existing MT5 REST-connector test failures are out of scope (fail identically at the 12-02 baseline; zero dashboard/HTMX surface) — logged to deferred-items.md, not fixed"
metrics:
  duration: ~30min
  completed: 2026-06-08
  tasks: 4
  files: 21
---

# Phase 12 Plan 03: HTMX/Jinja Stack Decommission (CUT-03) Summary

Tore down the now-dead HTMX/Jinja presentation stack in 4 grouped,
independently-revertable commits (D-10), reducing `dashboard.py` from a 1486-line
HTML+SSE app to a ~470-line FastAPI app host that keeps only the surviving wiring
(app factory, `/api/v2` router, `/app` + `/static` mounts, auth, `/health`,
`/ → /app/`) plus the six helpers the `/api/v2` layer imports from it (D-09). The
live-money control surface (now served entirely by the React SPA over `/api/v2`)
never regressed: `import dashboard` and `import api` both resolve, the 6
MUST-SURVIVE symbols are intact, and `docker build` succeeds.

## What Was Built (the 4 teardown commits, D-10)

| # | Commit | Type | Scope |
|---|--------|------|-------|
| 1 | `143b7f0` | refactor | dashboard.py surgery: delete HTML page/partial/SSE routes + Jinja setup + asset-manifest machinery + legacy /login + dead legacy money routes; keep the 6 api/-imported helpers; repoint _verify_auth + /logout → /app/login (1 file, +43/-985) |
| 2 | `e14e11f` | chore | delete templates/ (21 files), static/vendor/basecoat/, static/js/htmx_basecoat_bridge.js (24 files, -2851) |
| 3 | `35b4d4f` | chore | Dockerfile: remove Stage-1 css-build + dangling Stage-3 COPY (Pitfall 1); delete tailwind.config.js, input.css, _compat.css, build_css.sh; nginx: remove SSE block, keep /login rate-limit (6 files, +8/-223) |
| 4 | `7cf93d0` | test | prune HTMX-era tests (4 whole-file deletes) + surgically prune test_auth_session.py & test_api_csrf.py (6 files, +11/-1072) |

Each commit touches a single category and leaves a buildable, importable tree —
`git revert` of any one is safe (D-10 independent revertability).

### Commit 1 — dashboard.py reduced to wiring (D-09)

Deleted: `Jinja2Templates` setup; the asset-manifest machinery (`_asset_manifest`,
`_load_manifest`, `asset_url`, `_slug`); `HTMLResponse`/`StreamingResponse` imports
(kept `RedirectResponse`); `_render_login` + legacy `GET`/`POST /login`; the legacy
HTMX CSRF dep `_verify_csrf`; all HTML page routes (`/overview`, `/positions`,
`/history`, `/signals`, `/staged`, `/settings`, `/analytics` — they were redirect
stubs after 12-02); all `/partials/*` routes; the HTML settings POST handlers
(`/settings/{a}[/confirm|/revert]`) and their HTML-only helpers
(`_append_to_response_body`, `_render_toast_oob`, `_render_tab_partial`); the
legacy HTML trade-action routes (`/api/close`, `/api/modify-sl|tp`,
`/api/modify-levels`, `/api/close-partial`, `/api/emergency-preview`,
`/api/emergency-close`, `/api/resume-trading`, `/api/trading-status`) +
`_render_edit_modal_with_error`; the SSE `/stream` route; and the HTML-only
stage-label helpers `_RESOLVED_STATUS_LABELS` + `_label_resolved_stage` (verified
`api/stages.py` has its own `_enrich_resolved` and does not import them — RESEARCH
A7).

Kept (MUST SURVIVE — `grep -rn 'from dashboard import' api/` confirmed):
`validate_settings_form`, `_compute_dry_run` (api/settings.py), `_enrich_stage_for_ui`
(api/stages.py), `_client_ip`, `_password_hasher`, `app_settings` (api/auth.py),
plus transitive deps (`_SETTINGS_HARD_CAPS_INT`, `_SettingsValidationError`,
`_get_settings_store`, `_accounts_by_name`) and the data helpers
`_get_all_positions`/`_get_accounts_overview`. App factory, lifespan,
`include_router(api_router)`, `register_error_handlers`, `SessionMiddleware`,
`/static` + `/app` mounts, `/health`, accessors, and `bot.py`'s import are
untouched.

`_verify_auth`'s `Location` header (and `/logout`'s redirect) was repointed from
the deleted `/login?next=…` to `/app/login?next=…` (Pitfall 4) so an
unauthenticated hit bounces to the SPA login instead of a 404.

### Commit 3 — the Pitfall-1 Dockerfile correction

Beyond deleting Stage-1 `css-build` (as CONTEXT's D-10 specified), this commit
also removed the dangling Stage-3 COPY lines CONTEXT omitted: `COPY templates/`
(templates deleted in Commit 2) and the two `COPY --from=css-build` lines (no
css-build stage remains). Without these, `docker build` would have failed. The
runtime now keeps `COPY *.py/*.json`, `COPY api/`, `COPY static/`, `COPY scripts/`
(scripts/ still has `hash_password.py`), and the SPA overlay
`COPY --from=spa-build /spa/dist/ ./static/app/`. Stages were renumbered (spa-build
→ Stage 1, runtime → Stage 2).

## Verification

All test/build runs in a `python:3.12-slim` container (host has no pytest;
Postgres absent locally — the `api_app` fixture `pytest.skip`s, which is the
sanctioned green-or-skip bar).

- `python -c "import dashboard"` → OK (with config env); `python -c "import api"` →
  OK. The 6 MUST-SURVIVE symbols all resolve via a direct
  `from dashboard import validate_settings_form, _compute_dry_run, _enrich_stage_for_ui, _client_ip, _password_hasher, app_settings`
  → `ALL_6_RESOLVE` (Pitfall-3 guard green).
- `pytest tests/test_post_teardown.py tests/test_cutover_redirects.py tests/test_auth_session.py tests/test_api_csrf.py` →
  **4 passed, 22 skipped** (Postgres-skip), no FAIL. `test_post_teardown.py`
  deleted-404 / surviving-200 / `import api` cases and
  `test_cutover_redirects.py::test_unauth_redirects_to_app_login` pass-or-skip.
- `pytest tests/` (full suite) → **227 passed, 157 skipped, 3 failed**. The 3
  failures are pre-existing MT5 REST-connector tests
  (`test_rest_api_connector.py::TestConnect::*`,
  `test_rest_api_integration.py::test_full_market_buy_flow`) — they fail
  identically at the 12-02 baseline (498114a), contain zero dashboard/template/HTMX
  references, and are out of scope (logged in `deferred-items.md`, not fixed).
- `docker build -t telebot:teardown-check .` → **succeeds** (Pitfall-1
  half-removal trap avoided).
- `cd frontend && npm run build` → **built in 3.65s** (no shared CSS/asset broke;
  the >500 kB chunk note is an advisory, not an error).
- `grep -q 'location = /login' nginx/telebot.conf` → present (rate-limit preserved);
  `! grep -q 'proxy_read_timeout 86400s' nginx/telebot.conf` → SSE block removed.
- Each of the 4 commits is single-category and independently revertable (D-10).

## Operator Deploy Step (VPS — nginx, deploy-time-verified)

The `nginx/telebot.conf` edit is git-only and cannot be exercised locally. At VPS
deploy, copy the updated file and reload nginx (copy-paste on the VPS):

```bash
cp nginx/telebot.conf /home/murx/shared/nginx/conf.d/telebot.conf
docker exec shared-nginx nginx -t
docker exec shared-nginx nginx -s reload
```

The SSE block was removed only after Commit 1 deleted `/stream` (Pitfall 2
ordering). The `location = /login` rate-limit block and the base
`proxy_pass`/`proxy_set_header` lines are preserved.

## Deviations from Plan

### [Gating override — operator pre-authorized] Post-cutover 7-day bake + GO checkpoint WAIVED (deploy-at-end)

- **Found during:** plan start (explicit operator override in the execution brief,
  consistent with the same deploy-at-end decision recorded in 12-02).
- **Plan said:** a `checkpoint:human-verify gate="blocking"` at the head of the
  plan requiring 7 clean live-bake days + an explicit operator "GO" before any
  deletion (D-06/D-07/D-08).
- **What changed:** the operator chose a deploy-at-end workflow — ALL teardown code
  written and verified LOCALLY now; the single live bake + operator GO happens once,
  end-to-end, on the VPS at final deploy. The blocking checkpoint was treated as
  waived/acknowledged (not stopped at); all 4 teardown tasks executed in the planned
  grouped/revertable structure (D-10).
- **Honesty guard:** NO operator sign-offs were fabricated. Teardown code is
  complete and guards are green locally as of 2026-06-08; the **live bake + GO is
  DEFERRED to the VPS end-to-end acceptance**. The kill-switch parity sign-off
  (12-02 row 8) that gates the `/api/emergency-preview` deletion is likewise part of
  that single VPS acceptance — `/api/emergency-preview` was deleted here as planned,
  with its live verification deferred to VPS acceptance.
- **Risk note:** the per-commit revertability (D-10) and live-money-last safety
  ordering are intact; only the *timing* of the live bake moved (7-day-now →
  once-at-VPS-deploy). The SPA already serves the live-money surface over `/api/v2`
  (shipped Phases 8/11); the legacy money routes deleted here were dead duplicates
  with no SPA caller (RESEARCH Safety §1).

### [Rule 3 — Blocking] test_api_csrf.py legacy /login assertion pruned

- **Found during:** Task 4 (and during Task 1 read-ahead).
- **Issue:** `test_api_csrf.py::test_csrf_cookie_name_no_collision` (a KEEP file)
  read the legacy `GET /login` and asserted it sets `telebot_login_csrf`. Commit 1
  deleted `GET /login`, so that half would fail with Postgres present.
- **Fix:** surgically removed only the legacy-`/login` half (lines 128-133); kept
  the `telebot_csrf` distinct-name assertions. The plan named only
  `test_auth_session.py` for surgical pruning; this file needed the same treatment
  because its legacy assertion's target was deleted in Commit 1.
- **Files modified:** tests/test_api_csrf.py — **Commit:** `7cf93d0`.

## Authentication Gates

None. (The deploy-at-end waiver above is a gating-policy deviation, not an auth
gate.)

## Known Stubs

None. dashboard.py is reduced to its intended final wiring; the surviving helpers
are live (imported by `/api/v2`). No placeholder data, no unwired components.

## Threat Flags

None. This plan only *removes* surface — no new endpoint, auth path, file-access
pattern, or schema change. The threat-register mitigations are satisfied: T-12-08
(6-helper ImportError) guarded by `import dashboard`/`import api`; T-12-09 (auth
bounce) by the `/app/login` repoint; T-12-10 (settings caps) by surviving
`validate_settings_form` + green `test_api_settings.py`; T-12-11 (nginx /login
rate-limit) preserved; T-12-12 (SSE-before-/stream order) honored (Commit 1 before
Commit 3); T-12-13 (dead money endpoints) deleted + asserted 404 by
test_post_teardown; T-12-14 (Dockerfile half-removal) gated by `docker build`.

## Self-Check: PASSED

- FOUND: dashboard.py (reduced; 6 symbols + /app/login repoint verified)
- FOUND: Dockerfile (no css-build, spa-build + SPA overlay present, docker build green)
- FOUND: nginx/telebot.conf (location = /login present; SSE block gone)
- FOUND: .planning/phases/12-parallel-run-cutover-htmx-decommission/12-03-SUMMARY.md
- FOUND: .planning/phases/12-parallel-run-cutover-htmx-decommission/deferred-items.md
- GONE: templates/, static/vendor/, static/js/htmx_basecoat_bridge.js, tailwind.config.js,
  static/css/input.css, static/css/_compat.css, scripts/build_css.sh,
  tests/test_ui_substrate.py, tests/test_pending_stages_sse.py,
  tests/test_settings_form.py, tests/test_login_flow.py
- FOUND commit 143b7f0 (refactor 12-03 dashboard.py surgery)
- FOUND commit e14e11f (chore 12-03 templates/vendor/bridge delete)
- FOUND commit 35b4d4f (chore 12-03 Dockerfile/CSS-CLI/nginx)
- FOUND commit 7cf93d0 (test 12-03 HTMX test prune)
