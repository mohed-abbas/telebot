# Phase 12: Parallel-run Cutover + HTMX Decommission - Research

**Researched:** 2026-06-07
**Domain:** Reversible UI cutover + dead-code decommission (FastAPI/Jinja/HTMX → React SPA already shipped)
**Confidence:** HIGH (this is a codebase-inventory phase — every claim is grepped against live source at a verified line number, not training data)

## Summary

This is a **cutover + decommission** phase, not a build phase. The SPA pages (Phases 10/11) and the `/api/v2` JSON contract (Phase 8) already exist and are wired. The parallel-run substrate (CUT-01) is already live from Phase 9: the SPA is mounted at `/app/` via `SpaStaticFiles` (registered **after** `app.include_router(api_router)` so `/api/v2` always wins precedence — `dashboard.py:274-278`), and the legacy HTMX stack serves `/`, `/overview`, `/positions`, `/history`, `/signals`, `/staged`, `/settings`, `/analytics`, `/login` in parallel behind the single nginx `location /` proxy (`nginx/telebot.conf:47-60`). **CUT-01 requires ZERO code change** — it is satisfied as-is by Phase 9 routing; the planner's CUT-01 task is a documented confirmation, not a build.

The highest-value research output here is the **exhaustive, file:line-backed teardown inventory** so nothing is half-removed. I read all 1586 lines of `dashboard.py`, the full `templates/` + `static/` trees, the `Dockerfile`, `nginx/telebot.conf`, every test file, and grepped both the SPA's actual fetch targets AND `api/`'s imports from `dashboard.py`. The load-bearing safety facts: (1) **the SPA calls only `/api/v2/*` and `/app/*` — never any legacy HTML endpoint, partial, or SSE stream** (verified by exhaustive grep of `frontend/src`), so every legacy HTML route is safe to delete once cut over; (2) **the `/api/v2` layer imports SIX symbols from `dashboard.py` that look "HTMX-era" but MUST survive** — `_client_ip`, `_password_hasher`, `app_settings` (`api/auth.py`), `validate_settings_form` + `_compute_dry_run` (`api/settings.py`), and `_enrich_stage_for_ui` (`api/stages.py`); deleting any of these breaks the surviving JSON API. (3) `bot.py` imports `from dashboard import app, init_dashboard` (`bot.py:409`) — both survive untouched, so D-09's "no bot.py churn" holds.

**Primary recommendation:** CUT-01 = confirm-only (no code). CUT-02 = per-page one-line `RedirectResponse('/app/<page>', 303)` swaps, one commit each, gated by `12-CUTOVER-CHECKLIST.md` rows in D-05 order (analytics→…→kill-switch); `/` flips last. CUT-03 = the 4 grouped teardown commits in D-10, **gated behind a 7-day live bake + explicit operator go-ahead** — the planner must represent CUT-03 as a separate, non-autonomous, checkpoint-gated plan, NOT scheduled inside the cutover run. The single biggest teardown trap: D-10's deletion list is **incomplete** — it omits the Dockerfile Stage-3 COPY lines (`:63,68,69`) and six `api/`-imported helpers; both are corrected below.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CUT-01 | SPA + legacy HTMX run in parallel behind nginx so cutover is incremental/reversible | **Already satisfied by Phase 9** — `SpaStaticFiles` mount `dashboard.py:274-278` (after `include_router` `:251`), legacy routes `dashboard.py:382-1041`, single nginx `location /` `nginx/telebot.conf:47-60`. No code change; CUT-01 task = formalize/document the parallel-run state + assert router precedence (existing test `tests/test_spa_serving.py::test_api_not_shadowed_by_spa_mount`). |
| CUT-02 | Each page cut over individually; legacy route decommissioned only after React replacement verified at parity vs MT5 demo | Per-page redirect swap (one line, `RedirectResponse` already imported `dashboard.py:22`), one commit each, gated by a `12-CUTOVER-CHECKLIST.md` row (mirrors `06-HUMAN-UAT.md`). D-05 order + per-page SPA target map below. **Phase 12 OWNS the MT5-demo UAT** (D-03) — the parity check IS the gate. |
| CUT-03 | After full cutover, remove HTMX/Jinja templates, Tailwind standalone-CLI build stage, Basecoat vendor assets | Exhaustive 4-commit teardown inventory below (D-10), with two completeness corrections to D-10. Gated on 7-day bake + operator go-ahead (D-07/D-08). |
</phase_requirements>

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Per-page backend redirect. When a page passes its MT5-demo parity gate, change that page's legacy route to `RedirectResponse('/app/<page>', status_code=303)`, committed **one page per commit**. Rollback = `git revert` that single commit; nginx untouched (no per-page nginx rewrites/reloads). The switch lives in Python next to the route it replaces.
- **D-02:** Root `/` flips last. Keep `/` → `/overview` (legacy) until *every* page has individually cut over and verified, then flip `/` → `RedirectResponse('/app/')` as the final cutover step.
- **D-03:** Phase 12 OWNS the MT5-demo UAT. Phase 10/11 pages have NOT yet passed live MT5-demo UAT. Each page's MT5-demo parity check is a **task within this phase**, and passing it is what unblocks that page's D-01 redirect commit.
- **D-04:** Per-page checklist + dated sign-off. Maintain `12-CUTOVER-CHECKLIST.md`: one row per page (SPA data matches legacy on live data, live-money actions behave correctly, no console errors, poll-safe modals/drilldowns) + operator-dated sign-off line. Each D-01 commit references its checklist row. Mirrors `06-HUMAN-UAT.md`.
- **D-05:** Cutover order — read-only first, live-money last: `analytics (pilot) → signals → history → staged → overview → settings → positions → kill-switch`.
- **D-06:** Live bake period, then teardown. After all pages cut over, legacy HTMX keeps shipping (dormant, still reachable by direct legacy URL — only a redirect was added, not a deletion) for a bake window. During bake, rollback = revert one redirect commit.
- **D-07/D-08:** Bake gate = **7 days clean + explicit operator go-ahead**. The planner should NOT schedule CUT-03 execution inside the same uninterrupted run; it waits for the bake + go-ahead.
- **D-09:** `dashboard.py` survives as the FastAPI app host. KEEP: app factory + middleware, `app.include_router(api_router)`, `app.mount('/app', SpaStaticFiles)`, `/static` mount, auth (login POST + session + `/logout`), `/health`, and `/` → `RedirectResponse('/app/')`. DELETE: the `TemplateResponse`/`HTMLResponse` page + partial routes, the SSE `/stream` endpoint, the `Jinja2Templates` setup, and the `asset_url`/CSS-manifest helper machinery. `bot.py`'s import stays unchanged.
- **D-10:** Teardown in ~4 grouped, independently-revertable commits: (1) remove HTML page/partial routes + `/stream` SSE + Jinja setup from `dashboard.py`; (2) delete `templates/` + `static/vendor/` (Basecoat); (3) remove Dockerfile **Stage 1 (`css-build`)** + `tailwind.config.js` + `static/css/input.css` + `scripts/build_css.sh` + the nginx SSE block; (4) prune HTMX-era tests.

### Claude's Discretion
- Whether CUT-01 needs any code change at all, or is satisfied as-is by Phase-9 routing (verify + document rather than assume new work). **→ Researched: NO code change. See CUT-01 finding.**
- Exact contents/columns of the per-page `12-CUTOVER-CHECKLIST.md` parity rows per page.
- The precise CUT-03 inventory sweep (enumerate every Jinja template, every HTML/partial route line, every Basecoat/vendor asset, asset_url/manifest call sites, HTMX-specific tests). **→ Researched: full inventory below.**
- Whether the SPA login fully replaces legacy `/login` (legacy `/login` template route is in scope for D-09 deletion; the login POST/auth/session endpoints stay — confirm the SPA already posts to the surviving auth endpoint). **→ Researched: SPA posts to `/api/v2/auth/login`; see Safety finding.**
- Whether `/api/emergency-preview`, `/partials/*`, `/api/trading-status` HTML endpoints are all under D-09 deletion (verify nothing in `/app` still calls them). **→ Researched: all HTMX-era, no SPA caller; deletable.**
- Exact 303-vs-307/308 redirect status nuance per page (overview/positions/etc. are GET — 303 is fine). **→ Researched: all legacy page routes are `@app.get`; 303 correct everywhere.**

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope. The `dashboard.py` rename/split was considered and rejected (D-09). No new pages, endpoints, or features. The 7-day bake before CUT-03 is an intentional in-phase wait, not a deferral.
</user_constraints>

## Project Constraints (from CLAUDE.md)

`./CLAUDE.md` (the global file at `/Users/murx/CLAUDE.md`) is **Figma-MCP + Vue/Nuxt-oriented** and does **not** apply to this Python/FastAPI/React-Vite backend cutover phase — it governs Figma-design-to-code translation only. No directive in it constrains Phase 12. The binding project constraints come from `PROJECT.md §Constraints` + `§Key Decisions`:

- **Safety — real money at stake:** every change tested before deployment. The live-money control surface (close, modify SL/TP, partial-close, kill switch) must NEVER regress. This is the non-negotiable constraint shaping the cutover order (D-05: live-money last) and the bake gate (D-07/D-08).
- **Backwards compatibility:** no breaking changes to `.env` / `accounts.json` format. (Phase 12 touches neither.)
- **Deployment:** Docker with shared VPS services (proxy-net, data-net). nginx config lives on the VPS at `/home/murx/shared/nginx/conf.d/` — a teardown edit to `nginx/telebot.conf` requires a VPS copy + `docker exec shared-nginx nginx -s reload` (operator step, give as copy-paste text per MEMORY `feedback_vps_commands`).
- **Minimize dependencies / no Node runtime in prod:** Phase 12 *removes* deps (Tailwind standalone CLI, Basecoat) — aligned. Stage 2 `spa-build` node stage stays (build-time only; runtime is `python:3.12-slim`).
- **Commit hygiene (MEMORY `feedback_no_coauthor`):** NO `Co-Authored-By` lines in commit messages.
- **Commit timing (MEMORY `feedback_commit_timing`):** do not commit prematurely; wait for operator to test/confirm — directly reinforces the D-07/D-08 bake gate before CUT-03.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Per-page cutover switch (CUT-02) | API/Backend (`dashboard.py` route body) | — | D-01 keeps the switch in Python next to the route; rollback = `git revert`. No browser/nginx logic. |
| Parallel-run routing (CUT-01) | API/Backend (FastAPI mount order) + nginx | — | Precedence is enforced by FastAPI registration order (`/api/v2` before `/app`), not nginx; nginx is a dumb single `location /` proxy. |
| SPA serving | Frontend Server (uvicorn `StaticFiles`) | CDN/Static (none — no nginx alias) | Phase 9 D-02 chose uvicorn `StaticFiles` deep-link fallback, not nginx `alias`. Teardown does not touch this. |
| HTML page rendering (legacy) | API/Backend (Jinja `TemplateResponse`) | — | The entire tier being decommissioned in CUT-03. |
| SSE live push (legacy `/stream`) | API/Backend (StreamingResponse) | nginx (`proxy_buffering off`) | Both halves removed in Commit 1 (endpoint) + Commit 3 (nginx block). v1.2 replaced push with 3s TanStack-Query polling. |
| Live-money mutations (post-cutover) | API/Backend (`/api/v2` actions) | Browser (server-confirmed UI) | Already shipped (Phase 8/11). Legacy `/api/close|modify|close-partial|emergency-close|resume-trading` HTML routes are dead duplicates removed in Commit 1. |
| CSS build (legacy Tailwind CLI) | CDN/Static build (Dockerfile Stage 1) | — | Removed in Commit 3; SPA CSS comes from Vite (Stage 2). |

## Standard Stack

**No new libraries.** This phase removes stack, it does not add any. The only "tools" are existing ones already in the repo:

| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| `RedirectResponse` (FastAPI) | n/a (`fastapi.responses`) | Per-page 303 cutover redirect | Already imported `dashboard.py:22`; FastAPI native |
| `git revert` | system git | Single-commit rollback of any page cutover or teardown commit | D-01/D-10 reversibility is commit-granular |
| `pytest` + `pytest-asyncio` | repo-pinned | Post-teardown regression gate | Existing suite (40 test files under `tests/`) |
| `npm run build` (Vite) | repo-pinned | Confirms SPA still builds after teardown | Existing `frontend/` |

**Installation:** None. No package added or removed at the language-dependency level (Tailwind standalone CLI is a Docker-stage binary download, not a Python/npm dep — removed by deleting Dockerfile Stage 1).

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Per-page Python redirect (D-01) | Per-page nginx `rewrite`/`return 303` | REJECTED in CONTEXT — splits cutover state onto VPS config, needs an nginx reload per page, harder rollback. |
| 4 grouped teardown commits (D-10) | One big-bang teardown sweep | REJECTED — a single sweep is not partially revertable; a regression after teardown can't be bisected to a category. |

## Package Legitimacy Audit

**Not applicable — this phase installs ZERO external packages.** It only deletes existing code/assets. No npm/PyPI install occurs. slopcheck gate skipped (nothing to verify). The only "package-shaped" removal is the Tailwind standalone CLI binary (downloaded inside Dockerfile Stage 1 from `github.com/tailwindlabs/tailwindcss/releases` — an official first-party source, `Dockerfile:28`); removing it reduces attack surface.

## Architecture Patterns

### System Architecture Diagram

```
                         BEFORE (parallel run — current state, CUT-01 satisfied)
                         ─────────────────────────────────────────────────────
  Operator browser
        │
        ▼
  nginx  location = /login  (rate-limit, telebot.conf:36-45)  ─┐
  nginx  location /         (single proxy, telebot.conf:47-60) ─┤  proxy_pass telebot:8080
        │  (SSE block :54-59 — proxy_buffering off, read_timeout 86400s)        │
        ▼                                                                       ▼
  ┌─────────────────────────── FastAPI app (dashboard.py) ──────────────────────────┐
  │  app.include_router(api_router)      → /api/v2/*   (JSON, Phase 8)  ◀── SPA fetches
  │  app.mount('/static', StaticFiles)   → /static/*                                  │
  │  app.mount('/app', SpaStaticFiles)   → /app/*      (React SPA, deep-link 404→shell)
  │  @app.get('/')        → RedirectResponse('/overview')   ◀─ legacy default landing │
  │  @app.get('/overview'|'/positions'|'/history'|'/signals'|'/staged'               │
  │           |'/settings'|'/analytics') → TemplateResponse  ◀─ LEGACY HTMX pages     │
  │  @app.get('/partials/*'), @app.get('/stream') (SSE)      ◀─ LEGACY HTMX live      │
  │  @app.post('/api/close|modify-*|close-partial|emergency-close|resume')           │
  │  @app.get/post('/login'), @app.*('/logout'), @app.get('/health')                 │
  └─────────────────────────────────────────────────────────────────────────────────┘

                         DURING CUTOVER (CUT-02 — per page, one commit each)
                         ─────────────────────────────────────────────────────
  @app.get('/analytics') → RedirectResponse('/app/analytics', 303)   ◀─ swapped after parity gate
  @app.get('/signals')   → RedirectResponse('/app/signals',   303)   ◀─ next, …
  ...                                                                     (D-05 order)
  @app.get('/')          → RedirectResponse('/app/',          303)   ◀─ LAST (D-02)

                         AFTER TEARDOWN (CUT-03 — 4 commits, post-bake)
                         ─────────────────────────────────────────────────────
  ┌─────────────────── FastAPI app (dashboard.py, reduced to wiring) ───────────────┐
  │  app.include_router(api_router)  → /api/v2/*   (JSON)            ◀── SPA fetches  │
  │  app.mount('/static'), app.mount('/app', SpaStaticFiles)                          │
  │  @app.get('/')  → RedirectResponse('/app/')   ◀─ now default landing             │
  │  login POST + session + /logout + /health   (SURVIVE)                             │
  │  + the 6 api/-imported helpers (validate_settings_form, _compute_dry_run,        │
  │    _enrich_stage_for_ui, _client_ip, _password_hasher, app_settings) SURVIVE     │
  │  [all TemplateResponse routes, /partials/*, /stream, Jinja2Templates,            │
  │   asset_url/manifest, legacy /api/* HTML mutation routes — DELETED]               │
  └──────────────────────────────────────────────────────────────────────────────────┘
  nginx location / : SSE block removed; rate-limit /login block SURVIVES
  Dockerfile: Stage 1 css-build removed; Stage 2 spa-build + Stage 3 SPA overlay SURVIVE
```

### Pattern 1: One-line per-page redirect swap (D-01 / CUT-02)
**What:** Replace a legacy page route's *body* (not its decorator/signature) with a redirect.
**When to use:** After that page's `12-CUTOVER-CHECKLIST.md` row is operator-signed.
**Example:**
```python
# Source: dashboard.py:993-1041 (analytics) — current body returns TemplateResponse.
# After parity gate, the ENTIRE body collapses to one line (keep the @app.get + auth dep):
@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, user: str = Depends(_verify_auth)):
    return RedirectResponse("/app/analytics", status_code=303)
```
Notes: keep `Depends(_verify_auth)` so an unauthenticated hit still bounces to `/login` (not to `/app/` which would itself bounce). `RedirectResponse` already imported (`dashboard.py:22`). 303 is correct because all legacy page routes are `@app.get` (GET → GET redirect; no body to preserve). The `response_class=HTMLResponse` decorator arg is now cosmetically wrong but harmless; it can be dropped or left until Commit 1 deletes the route entirely.

### Pattern 2: Per-page SPA redirect-target map (the planner needs the exact target per page)

| Legacy route (line) | Method | Cutover target | SPA route exists? | D-05 order |
|---------------------|--------|----------------|-------------------|------------|
| `/analytics` (`dashboard.py:993`) | GET | `/app/analytics` | yes (Phase 10) | 1 (pilot) |
| `/signals` (`:475`) | GET | `/app/signals` | yes (Phase 10) | 2 |
| `/history` (`:422`) | GET | `/app/history` | yes (Phase 10) | 3 |
| `/staged` (`:589`) | GET | `/app/staged` | yes (Phase 10) | 4 |
| `/overview` (`:387`) | GET | `/app/overview` | yes (Phase 11, also `/app` index) | 5 |
| `/settings` (`:624`) | GET | `/app/settings` | yes (Phase 11) | 6 |
| `/positions` (`:411`) | GET | `/app/positions` | yes (Phase 11) | 7 |
| kill-switch (no standalone legacy GET page — reached via overview button + `/api/emergency-preview`) | GET preview | `/app/emergency` (`KillSwitchView`) | yes (Phase 11) | 8 (last) |
| `/` root (`:382`) | GET | `/app/` (flip `/overview`→`/app/`) | n/a | FINAL (D-02) |

**Kill-switch nuance:** there is no `@app.get("/kill-switch")` page route — the legacy kill switch is the `/api/emergency-preview` HTML partial (`:1350`) embedded in overview, plus the `/api/emergency-close` action (`:1377`). The SPA equivalent is the `/app/emergency` route (`frontend/src/routes/KillSwitchView.tsx`, queryKey `["emergency-preview"]` → `/api/v2/emergency/preview`). So the kill-switch "cutover" is not a redirect swap — it is **verified-then-decommissioned**: its parity row gates Commit 1's deletion of `/api/emergency-preview`, not a redirect. The planner should model kill-switch as the last *verification* gate, with its actual removal happening in CUT-03 Commit 1 (it has no GET page to redirect).

**303-vs-307/308:** every legacy *page* route is `@app.get` (verified — see inventory). 303 (See Other, forces GET) is correct for all. No 307/308 needed. The `POST /login` and `POST /api/*` routes are NOT cutover targets (they survive or are deleted in Commit 1, never redirected).

### Anti-Patterns to Avoid
- **Deleting before bake (violates D-06/D-07):** adding the redirect is the cutover; deletion is a *separate, later* CUT-03 step gated on 7 days + go-ahead. Do not collapse cutover and teardown into one plan.
- **Removing the nginx SSE block while any HTMX live page is still reachable (Pitfall 4, STATE.md):** `proxy_buffering off` / `proxy_read_timeout 86400s` must stay until `/stream` is deleted in Commit 1. The nginx SSE block is removed in Commit 3 — AFTER Commit 1 removed `/stream`. Order matters: Commit 1 (remove `/stream`) before Commit 3 (remove its nginx directives).
- **Deleting any of the 6 `api/`-imported `dashboard.py` symbols in Commit 1:** see the explicit MUST-SURVIVE list in Commit 1. Three look like auth helpers (`_client_ip`, `_password_hasher`, `app_settings`), THREE look like HTMX-era settings/stage helpers (`validate_settings_form`, `_compute_dry_run`, `_enrich_stage_for_ui`) but are imported by the live `/api/v2` layer. Deleting any → `ImportError` at boot → dashboard down → `bot.py` dashboard launch fails.
- **Deleting `dashboard.app` or renaming the module:** `bot.py:409` does `from dashboard import app as dashboard_app, init_dashboard`. Module name + `app` object + `init_dashboard` survive (D-09) → zero bot.py churn.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-page rollback | A feature-flag system / config toggle | `git revert <commit>` (D-01) | Each cutover is one commit; revert is instant + auditable; no new runtime state. |
| Routing precedence (API vs SPA) | A custom dispatcher / middleware | FastAPI registration order (already done: `include_router` before `app.mount('/app')`) | Phase 9 already proved this with `tests/test_spa_serving.py::test_api_not_shadowed_by_spa_mount`. |
| "Is the SPA caller-clean of legacy endpoints?" | Manual code reading | The grep already run (see Safety section) | Exhaustive `frontend/src` grep is authoritative; SPA uses only `/api/v2/*` + `/app/*`. |
| Cutover checklist format | A new doc schema | Mirror `06-HUMAN-UAT.md` (D-04) | Operator already knows that format; one row per page, dated sign-off. |

**Key insight:** Everything reversible in this phase is reversible *because it is a single git commit*, not because of any runtime machinery. Do not invent toggles, flags, or env switches.

## Runtime State Inventory

> This is a decommission phase touching presentation only. Runtime-state audit across all 5 categories:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | **None.** No template name, route path, or HTMX string is stored as a DB key, collection name, or ID. `db.py` write paths are explicitly out of scope (CONTEXT hard boundary). The `idempotency_keys`, `staged_entries`, `settings_audit`, etc. tables contain no presentation-layer strings. | None — verified by reviewing CONTEXT boundary + that all deleted code is pure presentation. |
| **Live service config** | **nginx config lives on the VPS** at `/home/murx/shared/nginx/conf.d/telebot.conf` (MEMORY `project_vps_infra`), NOT only in git. The Commit-3 SSE-block removal edits the git copy; the operator must re-copy + reload on the VPS (`docker exec shared-nginx nginx -s reload`). The git file `nginx/telebot.conf` is the source of truth but the *running* config is the deployed copy. | **Manual VPS step** after Commit 3: copy updated `telebot.conf` to VPS + reload nginx. Give as copy-paste text (MEMORY `feedback_vps_commands`). |
| **OS-registered state** | **None.** No systemd/cron/Task-Scheduler entry references templates or HTMX. The bot runs as a single Docker container (`CMD ["python","-u","bot.py"]`, `Dockerfile:76`). | None. |
| **Secrets/env vars** | **None renamed or removed.** `SESSION_SECRET`, `DASHBOARD_PASS_HASH`, `dashboard_port`, `dashboard_enabled`, `session_cookie_secure` all survive (consumed by surviving auth + app factory). No `.env` change. | None. |
| **Build artifacts** | **Hashed CSS + manifest:** `static/css/app.*.css` + `static/css/manifest.json` are build outputs of `scripts/build_css.sh` (Dockerfile Stage 1). After Commit 3 removes Stage 1, the **Dockerfile Stage-3 `COPY --from=css-build` lines (`Dockerfile:68-69`) and `COPY templates/` (`:63`) must ALSO be removed in Commit 3**, or the build fails (no `css-build` stage to copy from, no `templates/` dir to copy). The `_load_manifest()` call (`dashboard.py:68`) is deleted in Commit 1, so a missing `manifest.json` at runtime is harmless after teardown. No local stale egg-info/compiled artifacts (pure-Python app, no packaging). | **Commit 3 must edit Dockerfile lines 63 + 68-69** in addition to deleting Stage 1 (lines 1-40) — CONTEXT's D-10 list omits these COPY lines; the planner MUST add them or the image won't build. |

**Critical addition the planner must not miss:** D-10 Commit 3 as written ("remove Dockerfile Stage 1 + tailwind.config.js + input.css + build_css.sh + nginx SSE block") is **incomplete** — it must ALSO remove the Stage-3 `COPY templates/ ./templates/` (`Dockerfile:63`) and `COPY --from=css-build /build/static/css/app.*.css` + `manifest.json` (`Dockerfile:68-69`), because those reference deleted dirs/stages. Likewise the Stage-1 `COPY templates/`, `COPY static/vendor/`, `COPY static/css/input.css` (`Dockerfile:34-37`) vanish with the stage. This is one of two "half-removed" traps in the phase (the other is the 6 api/-imported helpers in Commit 1).

## CUT-03 Teardown Inventory (exhaustive, file:line-backed, grouped by D-10's 4 commits)

### Commit 1 — `dashboard.py` surgery (remove HTML page/partial routes + `/stream` SSE + Jinja setup)

> **⚠ Commit 1 is NOT a "delete everything that touches templates" sweep.** Six symbols that render Jinja or look HTMX-era are imported by the live `/api/v2` layer and MUST survive (see MUST-SURVIVE block). Treat the delete and keep lists as authoritative line-by-line.

**DELETE (Jinja/manifest setup, module-level):**
- `from fastapi.responses import HTMLResponse, StreamingResponse` — keep `RedirectResponse` (`dashboard.py:22`; split the import).
- `from fastapi.templating import Jinja2Templates` (`:24`).
- `templates = Jinja2Templates(...)` (`:48`).
- Asset-manifest machinery: `_asset_manifest` (`:54`), `_load_manifest()` def (`:57-65`), `_load_manifest()` call (`:68`), `asset_url()` def (`:71-75`), `templates.env.globals["asset_url"] = asset_url` (`:78`), `_slug()` def (`:81-87`), `templates.env.filters["slug"] = _slug` (`:90`).
- `_render_login()` helper (`:177-199`) — returns `templates.TemplateResponse("login.html", …)`. Tied to legacy `/login` (see login decision below).
- Legacy CSRF dep `_verify_csrf` (`:150-157`) — HTMX-coupled (`hx-request` heuristic). Used ONLY by legacy HTML mutation routes (`:822,890,951,1126,1150,1180,1220,1297,1378,1390`) — all deleted in this commit → dep is dead → delete. (`api/` has its own `verify_csrf_token` in `api/deps.py` and a separate `_verify_csrf` in `api/auth.py` — independent, survive.)

**DELETE (HTML page routes):**
- `overview` `@app.get("/overview")` (`:387-408`)
- `positions_page` `@app.get("/positions")` (`:411-419`)
- `history_page` `@app.get("/history")` (`:422-472`) — incl. its `partials/history_table.html` HTMX branch (`:455-460`)
- `signals_page` `@app.get("/signals")` (`:475-483`)
- `staged_page` `@app.get("/staged")` (`:589-605`)
- `settings_page` `@app.get("/settings")` (`:624-644`)
- `analytics_page` `@app.get("/analytics")` (`:993-1041`) — incl. its `partials/analytics_table.html` HTMX branch (`:1015-1025`)

**DELETE (HTML partial routes):**
- `pending_stages_partial` `@app.get("/partials/pending_stages")` (`:608-621`)
- `positions_partial` `@app.get("/partials/positions")` (`:1049-1055`)
- `position_drilldown_partial` `@app.get("/partials/position_drilldown/{account}/{ticket}")` (`:1058-1075`)
- `edit_levels_modal` `@app.get("/partials/edit-levels/{account_name}/{ticket}")` (`:1078-1106`)
- `overview_partial` `@app.get("/partials/overview")` (`:1109-1117`)

**DELETE (HTML settings POST handlers + their HTML-ONLY helpers):**
- `settings_validate` `@app.post("/settings/{account_name}")` (`:819-884`)
- `settings_confirm` `@app.post("/settings/{account_name}/confirm")` (`:887-945`)
- `settings_revert` `@app.post("/settings/{account_name}/revert")` (`:948-990`)
- HTML-only render helpers used ONLY by the above: `_append_to_response_body` (`:665-674`), `_render_toast_oob` (`:677-705`), `_render_tab_partial` (`:793-816`).
- **NOTE — do NOT delete `_compute_dry_run` or `validate_settings_form` here** (they are in the MUST-SURVIVE list — `api/settings.py` imports them).

**DELETE (legacy HTML trade-action routes — dead duplicates of `/api/v2/*`):**
- `close_position` `@app.post("/api/close/{account_name}/{ticket}")` (`:1125-1144`)
- `modify_sl` `@app.post("/api/modify-sl/...")` (`:1147-1174`) — already DEPRECATED in its docstring.
- `modify_tp` `@app.post("/api/modify-tp/...")` (`:1177-1204`) — already DEPRECATED.
- `_render_edit_modal_with_error` helper (`:1207-1214`)
- `modify_levels` `@app.post("/api/modify-levels/...")` (`:1217-1291`)
- `close_partial` `@app.post("/api/close-partial/...")` (`:1294-1342`)
- `emergency_preview` `@app.get("/api/emergency-preview")` (`:1350-1374`) — returns `kill_switch_preview.html`.
- `trading_status` `@app.get("/api/trading-status")` (`:1401-1407`) — JSON but the HTMX-poll endpoint; SPA uses `/api/v2/trading-status` (distinct path). Deletable (confirm A3).
- `emergency_close_endpoint` `@app.post("/api/emergency-close")` (`:1377-1386`) and `resume_trading` `@app.post("/api/resume-trading")` (`:1389-1398`) — JSON legacy kill-switch actions; SPA uses `/api/v2/emergency/close` + `/api/v2/emergency/resume`. Dead duplicates → delete (confirm A3: no external script depends on the bare paths).

**DELETE (SSE):**
- `sse_stream` `@app.get("/stream")` (`:1415-1469`) — the only `/stream` endpoint; the only consumer of `templates.get_template("partials/pending_stages.html").render(...)` (`:1441-1443`). v1.2 replaced push with 3s polling (REQUIREMENTS "Real-time push rejected for v1.2").

**DELETE (HTML-only stage-label helper):**
- `_RESOLVED_STATUS_LABELS` (`:489-497`) + `_label_resolved_stage` (`:584-586`) — used only by the deleted `/staged` route's "recently resolved" list. **VERIFY** `api/stages.py` does its own resolved-label mapping (it has `_enrich_resolved`, `api/stages.py:55`) — if so these two are HTML-only → delete. (`_enrich_stage_for_ui` is NOT in this group — it SURVIVES; see below.)

**KEEP — MUST SURVIVE (the `/api/v2` layer imports these from `dashboard.py`; VERIFIED by grep):**
- `validate_settings_form` (`:708-759`) — **`api/settings.py:125` does `from dashboard import validate_settings_form`**. `/api/v2` settings hard-cap validation depends on it. [VERIFIED: grep]
- `_compute_dry_run` (`:776-790`) — **`api/settings.py:204` does `from dashboard import _compute_dry_run`**. [VERIFIED: grep] *(My first-pass draft wrongly listed this for deletion — corrected.)*
- `_enrich_stage_for_ui` (`:500-581`) — **`api/stages.py:73` does `dashboard._enrich_stage_for_ui(...)`** (the API adds `_display` twins on top of it, `api/stages.py:28-34`). [VERIFIED: grep] *(First-pass draft wrongly listed this for deletion — corrected.)*
- Their dependencies therefore also survive: `_SETTINGS_HARD_CAPS_INT` (`:658-662`), `_SettingsValidationError` (`:652-654`), `_get_settings_store` (`:762-766`), `_accounts_by_name` (`:769-773`).
- `_client_ip` (`:169-174`), `_password_hasher` (`:166`), `app_settings` (`:30`) — **`api/auth.py:100` does `from dashboard import _client_ip, _password_hasher, app_settings`**. [VERIFIED: grep]

**Full `api/`→`dashboard` import surface (all must survive; VERIFIED by `grep -rn 'from dashboard import' api/`):** `get_executor`, `get_settings_store` (`api/deps.py`); `_client_ip`, `_password_hasher`, `app_settings` (`api/auth.py`); `validate_settings_form`, `_compute_dry_run` (`api/settings.py`); `dashboard._enrich_stage_for_ui` (`api/stages.py`). Plus the read-only accessors `get_executor/get_notifier/get_settings/get_settings_store` (`:105-118`) and the data helpers `_get_all_positions` (`:1477-1530`), `_get_accounts_overview` (`:1533-1586`) that those accessors and `_enrich_stage_for_ui`'s callers rely on.

**KEEP / SURVIVES (D-09 — explicitly verify these stay intact):**
- App factory: `app = FastAPI(...)` (`:244`), lifespan (`:202-211`), `from api import api_router` + `app.include_router(api_router)` (`:248,251`), `register_error_handlers(app)` (`:252`).
- Middleware: `SessionMiddleware` (`:256-264`). Mounts: `/static` (`:266`), `SpaStaticFiles` class (`:223-241`) + `/app` mount (`:274-278`).
- Accessors: `init_dashboard` (`:93-98`), `get_executor` (`:105`), `get_notifier` (`:109`), `get_settings` (`:113`), `get_settings_store` (`:117`), `_get_settings_store` (`:762`).
- Auth: `_verify_auth` (`:121-147`) — used by surviving `/` route + login. `/health` (`:281-284`). Data helpers `_get_all_positions`/`_get_accounts_overview`.
- **Login routes:** `login_form` GET (`:292-302`), `login_submit` POST (`:305-366`), `logout` (`:369-374`). **TENSION with D-09:** D-09 says "DELETE the legacy `/login` template route" yet "KEEP login POST + session". The GET `/login` renders `login.html` (Jinja); the SPA logs in at `/app/login` → `/api/v2/auth/login` (which sets the session itself, `api/auth.py:131`). RESOLUTION (Open Question 1): the **surviving** login is `/api/v2/auth/*`; the legacy GET+POST `/login` + `_render_login` + `login.html` are Jinja-coupled and deletable — **BUT `_verify_auth`'s `/login?next=…` redirect (`:146`) must be repointed to `/app/login` in Commit 1**, or every unauth bounce 404s after the legacy `/login` is gone. (Keep `/logout` or repoint it to `/app/login` too.)

### Commit 2 — delete `templates/` + `static/vendor/` (Basecoat) + HTMX JS bridge

**`templates/` (all 21 files — entire directory):**
```
templates/base.html, login.html, overview.html, positions.html, history.html,
signals.html, staged.html, settings.html, analytics.html,
templates/partials/account_settings_tab.html, analytics_table.html,
edit_levels_modal.html, history_table.html, kill_switch_preview.html,
overview_cards.html, pending_stages.html, position_drilldown.html,
positions_table.html, settings_audit_timeline.html, settings_confirm_modal.html,
toaster.html
```
(`settings_audit_timeline.html` + `toaster.html` are include-only partials — never a direct route return — but die with the directory.)

**`static/vendor/` (Basecoat):**
- `static/vendor/basecoat/basecoat.css`
- `static/vendor/basecoat/basecoat.min.js`

**`static/js/` (HTMX-era bridge — ADD to D-10 Commit 2; CONTEXT omits it):**
- `static/js/htmx_basecoat_bridge.js` — re-inits Basecoat after HTMX swaps; pure HTMX-era, no SPA caller. **Planner MUST add this to Commit 2** (D-10 lists only `templates/` + `static/vendor/`). After deletion, `static/js/` is empty → remove the dir too.

**KEEP:** `static/app/` (the built SPA — served at `/app`). `static/css/` handled in Commit 3.

### Commit 3 — Dockerfile Stage 1 + Tailwind config/input + build script + nginx SSE block

**Dockerfile (`Dockerfile`):**
- **DELETE Stage 1 `css-build` entirely** — lines `1-40` (`FROM debian:bookworm-slim AS css-build` through `RUN bash scripts/build_css.sh`). Drop the WR-06 comment block (`:7-12`) with it.
- **DELETE Stage-3 lines that reference deleted dirs/stages (CONTEXT omits these — REQUIRED, Pitfall 1):**
  - `COPY templates/ ./templates/` (`:63`) — `templates/` deleted in Commit 2.
  - `COPY --from=css-build /build/static/css/app.*.css ./static/css/` (`:68`) — no `css-build` stage.
  - `COPY --from=css-build /build/static/css/manifest.json ./static/css/` (`:69`).
  - `COPY static/ ./static/` (`:64`) STAYS (still needs `static/app`, `static/css`) — just copies less after Commit 2.
- **KEEP:** Stage 2 `spa-build` (`:42-52`), Stage-3 SPA overlay `COPY --from=spa-build /spa/dist/ ./static/app/` (`:72`), `COPY *.py *.json` (`:61`), `COPY api/` (`:62`), `COPY scripts/` (`:65` — `scripts/build_css.sh` deleted; verify `scripts/` still has other files, e.g. `hash_password.py`, or the COPY of an empty dir is fine).

**Repo files:**
- `tailwind.config.js` (DELETE — legacy v4 standalone-CLI config; SPA uses `@tailwindcss/vite`, no config file).
- `static/css/input.css` (DELETE — Tailwind CLI entrypoint that `@import`s Basecoat).
- `scripts/build_css.sh` (DELETE).
- `static/css/_compat.css` (DELETE — Phase 5 v1.0 class compat shim; **VERIFIED no reference** in `static/app`, `frontend/`, or `input.css` after Commit 2 removes input.css — A4 confirmed clean).
- Hashed artifacts `static/css/app.*.css` + `static/css/manifest.json` — build-time outputs (produced in the image, not committed source — A5); if any committed copies exist, delete them.

**nginx (`nginx/telebot.conf`):**
- **DELETE the SSE block inside `location /`** — lines `54-59`:
  ```
  # SSE support (critical for /stream endpoint)
  proxy_buffering off;
  proxy_cache off;
  proxy_http_version 1.1;
  proxy_set_header Connection '';
  proxy_read_timeout 86400s;
  ```
- **KEEP:** `location = /login` rate-limit block (`:36-45`) — login POST survives. The base `location /` proxy_pass + proxy_set_header lines (`:47-53`) STAY.
- **Ordering constraint:** Commit 1 (delete `/stream`) must land + deploy before Commit 3 removes the nginx SSE directives (Pitfall 2).
- **VPS deploy step:** copy updated `telebot.conf` to `/home/murx/shared/nginx/conf.d/` + `docker exec shared-nginx nginx -s reload` (operator copy-paste, MEMORY).

### Commit 4 — prune HTMX-era tests

| Test file | Disposition | Reason |
|-----------|-------------|--------|
| `tests/test_ui_substrate.py` | **DELETE** | Asserts Basecoat vendored, `tailwind.config.js` content glob, `input.css` `@import`, `htmx_basecoat_bridge.js` (`htmx:afterSwap`) — all deleted artifacts. |
| `tests/test_pending_stages_sse.py` | **DELETE** | Tests `/stream` SSE payload, `event: pending_stages`, `/staged` Jinja render, `/partials/pending_stages` — all deleted in Commit 1. (Stage *data* is covered by `tests/test_stages_contract.py` which survives.) |
| `tests/test_settings_form.py` | **DELETE** | Tests `GET /settings` Jinja tabs, `POST /settings/{a}` HTML modal/CSRF — deleted routes. (Settings *JSON* covered by surviving `tests/test_api_settings.py`. Note: `validate_settings_form` itself survives + is covered by `tests/test_settings_form` unit-level assertions? — confirm those validator unit tests, if any, move to a surviving file rather than being lost.) |
| `tests/test_login_flow.py` | **DELETE (after confirming A6)** | Tests legacy `GET /login` CSRF cookie + `POST /login` argon2 flow + `HX-Redirect` (`:107-117`). Surviving auth is covered by `tests/test_api_csrf.py` + the `/api/v2/auth/login` contract. **Confirm a `/api/v2/auth/*` login regression test exists before deleting** (`api/auth.py` references "the mandatory CSRF regression test (D-16 hard gate)"). |
| `tests/test_auth_session.py` | **SURGICAL PRUNE (do NOT delete whole file)** | KEEP `test_health_route_open`, `test_session_middleware_registered`. REMOVE `test_page_route_redirects_on_missing_session` (`:37` — hits `/overview`), `test_htmx_route_returns_401_on_missing_session` (`:44` — `hx-request` on `/overview`), `test_asset_url_helper_registered` (`:69`), `test_base_html_has_no_play_cdn` (`:77` — reads `templates/base.html`). Optionally replace the first two with an `/app/login`-bounce test (Pitfall 4). |
| `tests/test_simulator.py` | **KEEP** | Uses `PREFIX = "/api/v1"` (the MT5 bridge sim, `X-API-Key`) — unrelated to HTMX. Not a dashboard test. |
| `tests/test_spa_serving.py` | **KEEP** | Tests the surviving `/app` mount + `/api/v2` precedence. |
| `tests/test_api_*.py`, `test_*_contract.py`, `test_rate_limit.py`, `test_settings_store.py`, `test_settings.py` | **KEEP** | `/api/v2` JSON contract + rate-limit + settings-store unit — survive. |

**Note:** `tests/_bot_core_diff_guard.py` (the byte-for-byte bot-core guard) and `tests/conftest.py` survive untouched.

## Safety / Verification of the Teardown (avoid breaking the surviving app)

**1. SPA never calls a legacy HTML endpoint — VERIFIED.** Exhaustive grep of `frontend/src` shows the SPA fetches ONLY:
```
/api/v2/auth/{csrf,login,logout,me}   /api/v2/overview   /api/v2/positions
/api/v2/signals   /api/v2/stages   /api/v2/trading-status   /api/v2/history/filter-options
/api/v2/emergency/{preview,close,resume}   and the /app, /app/, /app/login shell paths.
```
No reference to `/partials/*`, `/stream`, `/api/emergency-preview`, `/api/close|modify-*|close-partial`, or any legacy page route. The `Sidebar.tsx` `to: "/positions"` / `"/settings"` entries are **react-router client paths under the `/app/` basename** (not backend fetches). → Every legacy HTML route is safe to delete once its page is cut over + baked. [VERIFIED: grep of frontend/src, 2026-06-07]

**2. SPA login uses the surviving auth — VERIFIED.** SPA posts to `/api/v2/auth/login` (`api/auth.py:91`), which sets the session itself (`request.session["user"]`, `api/auth.py:131-133`). The legacy `POST /login` (`dashboard.py:305`) is a Jinja-coupled duplicate. `api/auth.py` imports `_client_ip`, `_password_hasher`, `app_settings` from `dashboard.py` (`:100`) — those survive. → Legacy `/login` GET+POST + `login.html` + `_render_login` are deletable, **but** `_verify_auth`'s `/login?next=…` redirect (`dashboard.py:146`) must be repointed to `/app/login` in Commit 1. [VERIFIED: api/auth.py + dashboard.py read]

**3. `bot.py` import stays valid — VERIFIED.** `bot.py:409` = `from dashboard import app as dashboard_app, init_dashboard`. Both survive (D-09). `uvicorn.Config(dashboard_app, ...)` (`bot.py:413-419`) unaffected. → Zero bot.py churn. [VERIFIED: bot.py read]

**4. `api/` imports 6 helpers from `dashboard.py` — VERIFIED, and they ALL survive.** `grep -rn 'from dashboard import' api/` + `grep 'dashboard\.' api/stages.py` returns: `get_executor`/`get_settings_store` (`api/deps.py`), `_client_ip`/`_password_hasher`/`app_settings` (`api/auth.py`), `validate_settings_form`/`_compute_dry_run` (`api/settings.py`), `dashboard._enrich_stage_for_ui` (`api/stages.py`). **None may be deleted in Commit 1.** This corrects an earlier-draft assumption that `validate_settings_form` and `_enrich_stage_for_ui` were HTMX-only — they are NOT. [VERIFIED: grep, 2026-06-07]

**5. Test/build commands that MUST stay green after the teardown plan's final gate:**
```bash
pytest tests/ -x                                  # backend regression
cd frontend && npm run build                      # SPA still builds (no shared asset broke)
cd frontend && npx vitest run                     # SPA unit tests (Phase 11)
python -c "import dashboard"                       # no dangling import (the 6-helper trap)
docker build -t telebot:teardown-check .          # the Dockerfile half-removal trap (Pitfall 1)
# Surviving-route smoke:
#   GET /health -> 200 {"status":"ok"};  GET /app/ -> 200 shell
#   GET /api/v2/trading-status -> JSON (precedence intact)
#   GET / (post-final-cutover) -> 303 /app/;  GET /overview (post-teardown) -> 404
```
Sequencing note: Commits 1-3 make several tests fail until Commit 4 prunes them, so the suite is briefly red mid-plan. The planner must sequence so the **plan's final gate is green** — either land the Commit-4 prune last with one green checkpoint, or prune the now-dead tests in the same commit that deletes their target. The 4 commits stay independently revertable regardless.

## Common Pitfalls

### Pitfall 1: Half-removed Dockerfile (CONTEXT's D-10 Commit 3 is incomplete)
**What goes wrong:** Deleting Stage 1 `css-build` but leaving Stage-3 `COPY --from=css-build ...` (`Dockerfile:68-69`) and `COPY templates/` (`:63`) → `docker build` fails ("invalid from: css-build" / "templates: not found").
**How to avoid:** Commit 3 edits `Dockerfile:63, 68, 69` in addition to deleting `:1-40`. Run `docker build` as the commit's gate.

### Pitfall 2: nginx SSE directives removed while `/stream` still live (STATE.md Pitfall 4)
**What goes wrong:** Removing `proxy_buffering off` / `proxy_read_timeout 86400s` while an HTMX page still holds an SSE connection → buffered/timed-out stream, operator sees a frozen legacy page during bake.
**How to avoid:** Commit 1 (delete `/stream`) deploys before Commit 3 (remove nginx SSE block). Never reverse this order.

### Pitfall 3: Deleting one of the 6 `dashboard.py` symbols `api/` imports
**What goes wrong:** Deleting `validate_settings_form`, `_compute_dry_run`, `_enrich_stage_for_ui`, `_client_ip`, `_password_hasher`, or `app_settings` → `ImportError` at boot → whole dashboard down → `bot.py` dashboard launch fails. The three settings/stage helpers are the trap because they *look* HTMX-era.
**How to avoid:** Treat the MUST-SURVIVE list as load-bearing. Gate Commit 1 with `python -c "import dashboard"` AND `python -c "import api"` (forces the lazy `from dashboard import ...` lines to resolve) + `pytest tests/test_api_settings.py tests/test_stages_contract.py -x`.

### Pitfall 4: `_verify_auth` redirects to a deleted `/login`
**What goes wrong:** After deleting legacy `/login`, an unauthenticated hit to any surviving route 303s to `/login?next=…` → 404.
**How to avoid:** Commit 1 repoints `_verify_auth`'s `Location` (`dashboard.py:146`) to `/app/login`. Add a test asserting an unauth GET to a surviving route bounces to `/app/login`.

### Pitfall 5: Collapsing cutover and teardown into one run (violates D-06/D-07/D-08)
**What goes wrong:** Teardown runs before the 7-day bake → no instant-rollback safety net if a live-money regression surfaces on day 3.
**How to avoid:** The planner produces CUT-03 as a SEPARATE plan with a `checkpoint:human-verify` (or non-autonomous) gate at its head: "7 days clean + operator types GO". Do not autochain CUT-02 → CUT-03.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SSE `/stream` push (2s) | TanStack Query 3s polling | Phase 9 (v1.2) | `/stream` + nginx SSE block become dead; removed in CUT-03. |
| HTMX `HX-Request` CSRF heuristic | double-submit cookie `telebot_csrf` / `X-CSRF-Token` | Phase 8 | Legacy `_verify_csrf` (`dashboard.py:150`) dead; `api/deps.verify_csrf_token` is the live one. |
| Jinja `TemplateResponse` HTML | React SPA + `/api/v2` JSON | Phases 8-11 | Entire `templates/` tree + HTML routes decommissioned. |
| Tailwind standalone CLI (Dockerfile Stage 1) | `@tailwindcss/vite` (Stage 2) | Phase 9 | Stage 1 + `tailwind.config.js` + `input.css` removed. |

**Deprecated/outdated:** `modify_sl` (`:1147`) + `modify_tp` (`:1177`) self-document as DEPRECATED ("UI no longer calls this") — already-dead even pre-cutover; delete in Commit 1.

## Validation Architecture

> `workflow.nyquist_validation: true` in config — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework (backend) | pytest + pytest-asyncio (httpx `ASGITransport` over `app`) |
| Framework (frontend) | vitest (node env) |
| Config file | `tests/conftest.py` (session-scoped event loop + asyncpg pool); `frontend/` vitest via package.json |
| Quick run command | `pytest tests/test_spa_serving.py tests/test_api_csrf.py -x` |
| Full suite command | `pytest tests/ -x && cd frontend && npm run build && npx vitest run` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CUT-01 | `/api/v2` not shadowed by `/app` mount (precedence) | integration | `pytest tests/test_spa_serving.py::test_api_not_shadowed_by_spa_mount -x` | ✅ |
| CUT-02 | Legacy page returns 303 → `/app/<page>` after cutover | integration | `pytest tests/test_cutover_redirects.py -x` (assert `GET /analytics` → 303 `/app/analytics`, etc.) | ❌ Wave 0 |
| CUT-02 | Unauth hit to a cut-over/surviving route bounces to `/app/login` (after Pitfall-4 repoint) | integration | same file: `test_unauth_redirects_to_app_login` | ❌ Wave 0 |
| CUT-02 | Per-page parity vs MT5 demo (SPA data == legacy, live-money actions correct, no console errors, poll-safe) | manual (operator) | `12-CUTOVER-CHECKLIST.md` dated sign-off | ❌ Wave 0 (the checklist doc) |
| CUT-03 | After teardown, deleted routes 404 / app still boots / `/health` 200 / `/app/` 200 | integration | `pytest tests/test_post_teardown.py -x` (assert `GET /overview` → 404, `GET /stream` → 404, `/health` 200, `/app/` 200) | ❌ Wave 0 (built in CUT-03 plan) |
| CUT-03 | No dangling import of deleted symbols; `api/` still imports its 6 helpers; image builds | smoke | `python -c "import dashboard" && python -c "import api"` + `docker build .` | ✅ (commands exist) |
| CUT-03 | SPA still builds (no shared CSS/asset broke) | smoke | `cd frontend && npm run build` | ✅ |

### Sampling Rate
- **Per cutover commit (CUT-02):** `pytest tests/test_cutover_redirects.py -x` + the page's checklist row signed.
- **Per teardown commit (CUT-03):** `pytest tests/ -x` (suite green at plan gate) + `python -c "import dashboard" && python -c "import api"` + (Commit 3) `docker build .`.
- **Phase gate:** full suite + `npm run build` + `vitest run` green; 7-day bake clean; operator GO before CUT-03.

### Wave 0 Gaps
- [ ] `tests/test_cutover_redirects.py` — assert each legacy page route returns 303 to its `/app/<page>` target (CUT-02), parameterized over the D-05 page list; assert unauth → `/app/login`.
- [ ] `tests/test_post_teardown.py` — assert deleted routes 404 + surviving routes (`/health`, `/app/`, `/api/v2/trading-status`, `/` → 303 `/app/`) + `import api` resolves (the 6-helper guard).
- [ ] `.planning/phases/12-.../12-CUTOVER-CHECKLIST.md` — one row per page (D-04/D-05 order) mirroring `06-HUMAN-UAT.md`, with parity items + dated operator sign-off.
- [ ] No new test framework install needed — pytest + vitest already present.

## Security Domain

> `security_enforcement` not set to `false` → section included.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | argon2 (`_password_hasher`) + httpOnly session cookie — SURVIVES; `/api/v2/auth/login` is the live path. Verify no auth gap when legacy `/login` is removed (Pitfall 4). |
| V3 Session Management | yes | `SessionMiddleware` (`dashboard.py:256`) — SURVIVES; 30-day signed cookie, `same_site=lax`, `https_only` config-driven. Untouched by teardown. |
| V4 Access Control | yes | `_verify_auth` (page) + `api/deps.require_user` (401 on `/api/v2`) — both survive. Confirm every surviving route still carries an auth dep after Commit 1 edits. |
| V5 Input Validation | yes | Settings hard caps = `validate_settings_form` (`dashboard.py:708`) — **survives + is the ONLY copy** (`api/settings.py` imports it). Deleting it would silently drop server-side caps → must NOT delete. |
| V6 Cryptography | yes | `secrets.compare_digest` CSRF compare + argon2 — all in surviving code (`api/deps.py`, `api/auth.py`). No hand-rolled crypto introduced. |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| CSRF on surviving money mutations | Tampering | Double-submit `telebot_csrf`/`X-CSRF-Token` (`api/deps.verify_csrf_token`) — survives; `tests/test_api_csrf.py` must stay green through teardown. |
| Auth bypass via deleted-login redirect loop | Elevation/Spoofing | Repoint `_verify_auth` → `/app/login` (Pitfall 4); SPA's global 401 handler already loop-breaks (SPA-04). |
| Silently dropping server-side settings caps by deleting `validate_settings_form` | Tampering | It SURVIVES (MUST-SURVIVE list); `tests/test_api_settings.py` exercises the caps via `/api/v2`. |
| Removing nginx `/login` rate-limit by accident | DoS | Commit 3 KEEPS `location = /login` block (`nginx/telebot.conf:36-45`); only the SSE block (`:54-59`) is removed. |
| Leaving a dead but reachable legacy money endpoint post-bake | Tampering | Commit 1 deletes `/api/close|modify-*|close-partial|emergency-close|resume-trading`; CUT-03 not "done" until these 404. |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | ~~`api/settings.py` re-implements `validate_settings_form`~~ **RESOLVED — FALSE.** `api/settings.py:125` IMPORTS it from `dashboard`; it MUST survive. | Commit 1 | Resolved by grep; no residual risk if the KEEP list is honored. |
| A2 | ~~`api/stages.py` does its own stage enrichment~~ **RESOLVED — `_enrich_stage_for_ui` IS imported** (`api/stages.py:73`); it MUST survive. `_RESOLVED_STATUS_LABELS`/`_label_resolved_stage` appear HTML-only (api has `_enrich_resolved`) — confirm before deleting those two. | Commit 1 | Enrich fn resolved; only the two resolved-label helpers carry residual (low) risk — grep `api/stages.py` for `_label_resolved_stage`/`_RESOLVED_STATUS_LABELS`. |
| A3 | No external script/curl/cron depends on the bare legacy paths `/api/emergency-close`, `/api/resume-trading`, `/api/trading-status` (only the SPA via `/api/v2/*`). | Commit 1 | An ops script hitting the old path 404s after teardown. Operator should confirm. |
| A4 | ~~`static/css/_compat.css` is HTMX-era and deletable~~ **RESOLVED — no reference** found in `static/app`, `frontend/`, or `input.css`. Deletable. | Commit 3 | Resolved by grep. |
| A5 | The hashed `static/css/app.*.css` + `manifest.json` are build-time outputs, not committed source. | Commit 3 / Runtime State | If committed, they're stale dead files to delete; harmless either way once `_load_manifest` is gone. |
| A6 | A `/api/v2/auth/*` login regression test exists (covering what `test_login_flow.py` covered) before deleting `test_login_flow.py`. | Commit 4 | Deleting login-flow coverage with no replacement leaves auth untested. Confirm `tests/test_api_csrf.py` / auth contract covers it. |
| A7 | The `/staged` "recently resolved" labels (`_RESOLVED_STATUS_LABELS`, `_label_resolved_stage`) are HTML-only because `api/stages.py` has its own `_enrich_resolved`. | Commit 1 | If the API imports them, deleting breaks the resolved-stages JSON. Grep before deleting. |

**Note:** A1, A2 (enrich fn), and A4 were resolved during research by grep — folded into the MUST-SURVIVE list and the Commit-3 inventory. A3, A5, A6, A7 remain operator/planner-confirmable.

## Open Questions (RESOLVED)

1. **Is legacy `/login` (GET form + POST submit) deleted, or only the GET form?**
   - What we know: SPA logs in via `/api/v2/auth/login` (sets session itself). Legacy `POST /login` + `_render_login` + `login.html` are Jinja-coupled. `_verify_auth` redirects to `/login`.
   - What's unclear: whether any non-SPA client (a saved bookmark, a monitoring probe) still hits `GET /login`.
   - **RESOLVED:** Delete both legacy `/login` routes + `login.html` in Commit 1, repoint `_verify_auth` → `/app/login`, KEEP/repoint `/logout`. The SPA owns login. Confirm with operator that no bookmark/probe targets the old `/login`. Encoded in plan 12-03 Commit 1 (Pitfall-4 repoint).

2. **Order of Commit 4 (test prune) vs Commits 1-3 (code delete).**
   - What we know: Commits 1-3 make `test_ui_substrate.py`, `test_pending_stages_sse.py`, `test_settings_form.py`, parts of `test_auth_session.py`, and `test_login_flow.py` fail. Commit 4 prunes them.
   - **RESOLVED:** Sequence so the plan's final gate is green — either prune the dead tests inside the same commit that deletes their target, or land an all-then-prune ordering with one green checkpoint. The 4 commits stay independently revertable. Encoded in plan 12-03's D-10 4-commit grouping.

3. **Does CUT-03 need a `docker build` in CI, or is operator-side build sufficient?**
   - **RESOLVED:** Run `docker build .` locally/CI as Commit 3's gate to catch the Dockerfile half-removal trap (Pitfall 1) before the operator deploys. Encoded in plan 12-03 Commit 3 `<verify>`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| git | per-commit revert (D-01/D-10) | ✓ (repo) | system | — |
| pytest + pytest-asyncio | backend regression gate | ✓ (40 test files present) | repo-pinned | — |
| PostgreSQL | integration tests (conftest pool) | ✗ locally — tests `pytest.skip` if absent | — | Run on VPS / container w/ Postgres (MEMORY `project_local_dashboard_verification`) |
| node + npm | `npm run build` SPA gate | build-time only (Stage 2) | node:22 | — |
| docker | Commit 3 `docker build` gate | ✓ (operator/VPS) | — | Operator builds on VPS; give as copy-paste |
| nginx (shared-nginx container) | Commit 3 SSE-block deploy + reload | VPS-only | — | Operator copy-paste `docker exec shared-nginx nginx -s reload` |

**Missing dependencies with fallback:**
- PostgreSQL not guaranteed locally — DB-touching tests skip; run the full suite on the VPS / a Python 3.12 + Postgres container (per MEMORY `project_local_dashboard_verification`: verify dashboard standalone, NOT via full `bot.py` — Telegram session conflict).

**Missing dependencies with no fallback:** None block planning. The MT5-demo parity gate (CUT-02) is an operator action on the live VPS + MT5 demo, not an automatable CI dependency.

## Sources

### Primary (HIGH confidence — live source read this session)
- `dashboard.py` (full 1586 lines read) — every route/helper line number above.
- `nginx/telebot.conf` (full) — SSE block `:54-59`, rate-limit `:36-45`, proxy `:47-60`.
- `Dockerfile` (full) — Stage 1 `:1-40`, Stage-3 COPY traps `:63,68-69`, SPA overlay `:72`.
- `frontend/src` grep — SPA fetch targets (only `/api/v2/*` + `/app/*`).
- `api/auth.py`, `api/deps.py`, `api/settings.py`, `api/stages.py` — the 6 surviving `dashboard.py` imports (`from dashboard import` grep across `api/`).
- `bot.py:405-421` — `from dashboard import app, init_dashboard` + uvicorn launch.
- `tests/` tree (40 files) + per-file inspection of the 6 HTMX-candidate tests.
- `templates/` (21 files) + `static/vendor/`, `static/js/`, `static/css/` trees; `_compat.css` reference grep.
- CONTEXT.md (D-01..D-10), REQUIREMENTS.md (CUT-01..03 + Out of Scope), ROADMAP.md (Phase 12 success criteria), STATE.md (Pitfall 4, Phase 10/11 UAT-pending), PROJECT.md (constraints).
- `.planning/phases/06-staged-entry-execution/06-HUMAN-UAT.md` — checklist format precedent.

### Secondary / Tertiary
- None — no WebSearch/Context7 needed; this is a pure codebase-inventory phase.

## Metadata

**Confidence breakdown:**
- CUT-01 (no code change): HIGH — mount order + nginx single-proxy verified in live source; existing precedence test passes.
- Teardown inventory: HIGH — every deletion target is a grepped line number; the full `api/`→`dashboard` import surface (6 symbols) was grepped and folded into a MUST-SURVIVE list. Residual: A3/A6/A7 (operator/planner-confirmable, low risk).
- Per-page redirect + targets: HIGH — all legacy page routes confirmed `@app.get` (303 correct); SPA routes confirmed to exist.
- Safety (SPA caller-clean): HIGH — exhaustive `frontend/src` grep, no legacy reference.
- Bake-gate representation: HIGH — D-07/D-08 explicit; reinforced by MEMORY `feedback_commit_timing`.

**Research date:** 2026-06-07
**Valid until:** 2026-07-07 (stable — codebase inventory; re-verify line numbers if `dashboard.py` is edited before planning, since numbers drift on any edit)
