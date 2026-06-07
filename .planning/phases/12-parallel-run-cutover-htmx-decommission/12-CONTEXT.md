# Phase 12: Parallel-run Cutover + HTMX Decommission - Context

**Gathered:** 2026-06-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Flip the operator from the legacy HTMX dashboard to the already-built React SPA
**page-by-page** — each flip gated on an MT5-demo parity check — then, after a live
bake window, delete the HTMX/Jinja stack, the Tailwind standalone-CLI build stage, and
the Basecoat vendor assets. The live-money control surface must never regress and every
step must be reversible. Requirements: **CUT-01, CUT-02, CUT-03**.

**Critical starting state (already shipped by Phase 9 — NOT this phase's work):**
The parallel-run substrate (CUT-01) is largely structural-complete. The SPA is mounted
at `/app/` via `SpaStaticFiles` (client-route 404→shell fallback; registered after the
`/api/v2` router so the API always wins precedence — `dashboard.py:215-276`). The legacy
HTMX dashboard serves `/` (`/` → `RedirectResponse('/overview')`, `dashboard.py:382-384`)
plus `/overview`, `/positions`, `/history`, `/signals`, `/staged`, `/settings`,
`/analytics`, `/login`. Both flow through the single nginx `location /` proxy to
`telebot:8080` (`nginx/telebot.conf:47-60`). The SPA login already exists (SPA-03).
So Phase 12 adds the **per-page switch**, the **verification gate**, and the **teardown** —
it does not build the parallel-run plumbing from scratch.

**In scope:**
1. **CUT-01 (finish):** confirm/formalize the parallel-run routing; both stacks reachable
   throughout the phase.
2. **CUT-02:** per-page MT5-demo parity verification → per-page backend redirect cutover,
   read-only pages first, live-money pages last.
3. **CUT-03:** after a 7-day live bake, remove the HTMX/Jinja templates, the Dockerfile
   CSS-build stage, the Basecoat vendor assets, the SSE `/stream` endpoint, and the legacy
   HTML routes — keeping `dashboard.py` as the surviving FastAPI app host.

**Out of this phase (hard boundary — carried from v1.2 invariants):**
- ANY change to the bot core (`executor.py`, `trade_manager.py`, `db.py` write paths,
  `mt5_connector.py`, MT5 REST bridge) — untouched; v1.2 confines blast radius to
  presentation.
- ANY new SPA page, JSON API endpoint, or feature — the SPA pages (Phases 10/11) and the
  `/api/v2` contract (Phase 8) are complete. Phase 12 cuts over and tears down; it does
  not build pages or endpoints.
- New trading capability / signal-handling change — bot core unchanged by design.

</domain>

<decisions>
## Implementation Decisions

### Cutover switch mechanism (CUT-02)
- **D-01:** **Per-page backend redirect.** When a page passes its MT5-demo parity gate,
  change that page's legacy route to `RedirectResponse('/app/<page>', status_code=303)`,
  committed **one page per commit**. Rollback of any single page = `git revert` that one
  commit; nginx config stays untouched (no per-page nginx rewrites, no nginx reload per
  cutover). The switch lives in Python next to the route it replaces. (Rejected: per-page
  nginx rewrite — splits cutover state onto the VPS config + needs reloads; flip-root-only
  — a big-bang flip that defeats CUT-02's incremental/reversible intent.)
- **D-02:** **Root `/` flips last.** Keep `/` → `/overview` (legacy) until *every* page
  has individually cut over and verified, then flip `/` → `RedirectResponse('/app/')` as
  the final cutover step. The operator's default landing changes only once the whole SPA
  is proven.

### Verification gate, evidence & order (CUT-02)
- **D-03:** **Phase 12 OWNS the MT5-demo UAT.** Phase 10 (read-only) and Phase 11
  (live-money) pages have NOT yet passed live MT5-demo UAT (STATE.md). Rather than treat
  that as an external precondition (nothing currently schedules it), each page's MT5-demo
  parity check is a **task within this phase**, and passing it is exactly what unblocks
  that page's D-01 redirect commit. This phase IS the verification phase.
- **D-04:** **Per-page checklist + dated sign-off.** Maintain a
  `12-CUTOVER-CHECKLIST.md` in the phase dir: one row per page listing the parity items
  to verify (SPA data matches legacy on live data, live-money actions behave correctly,
  no console errors, poll-safe modals/drilldowns) and an operator-dated sign-off line.
  Each D-01 redirect commit references its checklist row. Mirrors the existing
  `06-HUMAN-UAT.md` pattern.
- **D-05:** **Cutover order — read-only first, live-money last:**
  `analytics (pilot) → signals → history → staged → overview → settings → positions →
  kill-switch`. Lowest blast radius first; the destructive live-money surfaces cut over
  last, when confidence is highest. Matches the roadmap's stated analytics-pilot ordering.

### Rollback / bake period (CUT-03 timing)
- **D-06:** **Live bake period, then teardown.** After all pages cut over, the legacy
  HTMX code keeps shipping (dormant, still reachable by direct legacy URL since only the
  redirect was added, not a deletion) for a bake window. CUT-03 deletion happens only
  after the SPA runs clean in production. During the bake, rollback = revert one redirect
  commit and legacy serves again instantly.
- **D-07 / D-08:** **Bake gate = 7 days clean + operator go-ahead.** Teardown is gated on
  the SPA serving all pages with **no operator-reported regression for 7 days of live
  trading**, followed by an **explicit operator go-ahead** to run CUT-03. (7 days exercises
  daily signal flow plus a weekend while still closing v1.2 promptly.) This is a real
  future obligation — the planner should NOT schedule CUT-03 execution inside the same
  uninterrupted run; it waits for the bake + go-ahead.

### Decommission scope & structure (CUT-03)
- **D-09:** **`dashboard.py` survives as the FastAPI app host.** KEEP: the app factory +
  middleware, `app.include_router(api_router)` (`/api/v2`), `app.mount('/app', SpaStaticFiles)`,
  the `/static` mount, auth (login POST + session + `/logout`), `/health`, and `/` →
  `RedirectResponse('/app/')`. DELETE: the ~65 `TemplateResponse`/`HTMLResponse` page +
  partial routes, the SSE `/stream` endpoint (+ its polling-fallback partial routes), the
  `Jinja2Templates` setup, and the `asset_url`/CSS-manifest helper machinery. `bot.py`'s
  import of `dashboard.py` stays unchanged (lowest churn). (Rejected: rename/split into
  `app.py` — more churn + touches `bot.py` import for a cleanup.)
- **D-10:** **Teardown committed in ~4 grouped, independently-revertable commits:**
  (1) remove HTML page/partial routes + `/stream` SSE + Jinja setup from `dashboard.py`;
  (2) delete `templates/` + `static/vendor/` (Basecoat);
  (3) remove Dockerfile **Stage 1 (`css-build`)** + `tailwind.config.js` +
  `static/css/input.css` + `scripts/build_css.sh` + the nginx SSE block
  (`proxy_buffering off` etc. in `location /`, `nginx/telebot.conf:54-59`);
  (4) prune HTMX-era tests (e.g. `test_ui_substrate.py` and other Jinja/HTMX-fragment
  tests). Each commit reviewable + partially revertable.

### Claude's Discretion (planner/researcher decides)
- Whether CUT-01 needs any code change at all, or is satisfied as-is by the existing
  Phase-9 routing (the planner should verify the parallel-run state and document it rather
  than assume new work).
- Exact contents/columns of the per-page `12-CUTOVER-CHECKLIST.md` parity rows per page.
- The precise inventory sweep for CUT-03 (the researcher should enumerate every Jinja
  template, every HTML/partial route line, every Basecoat/vendor asset, the asset_url/
  manifest call sites, and the HTMX-specific tests) so nothing is half-removed.
- Whether the SPA login fully replaces legacy `/login` (legacy `/login` template route is
  in scope for D-09 deletion; the login **POST/auth/session** endpoints stay — confirm the
  SPA already posts to the surviving auth endpoint before deleting the legacy template).
- Whether the `/api/emergency-preview`, `/partials/*`, and `/api/trading-status`
  HTML-returning legacy endpoints are all classified under D-09 deletion (they appear to be
  HTMX-era; verify nothing in `/app` still calls them — the SPA should use `/api/v2`).
- Exact 303-vs-307/308 redirect status nuance per page if any page is reached via a
  non-GET legacy path (overview/positions/etc. are GET — 303 is fine).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & milestone scope
- `.planning/REQUIREMENTS.md` §CUT — **CUT-01, CUT-02, CUT-03** (the 3 requirements this
  phase delivers) + §"Out of Scope" + the carried-forward note (Phase 6/10/11 UAT status).
- `.planning/ROADMAP.md` Phase 12 — goal + success criteria + the v1.2 phase ordering
  (8→9→10→11→12) and the dependency note (depends on Phases 10 + 11).
- `.planning/PROJECT.md` §Key Decisions — "Parallel-run + page-by-page cutover behind
  nginx" + "Live-money operator control surface must NEVER regress" + "minimize-deps / no
  Node runtime in prod" (the constraints shaping cutover + teardown).
- `.planning/STATE.md` — confirms Phase 10/11 pages are **awaiting MT5-demo UAT** (the
  fact that drives D-03), and Phase 6 (staged) carried-forward status.

### Current serving / routing layer this phase modifies
- `dashboard.py` — the FastAPI app host. SPA mount + `SpaStaticFiles` fallback
  (`:215-276`), `/api/v2` router mount (`:246`), `/static` mount (`:266`), root redirect
  `/` → `/overview` (`:382-384`), legacy page routes (`/overview` `:387`, `/positions`
  `:411`, `/history` `:422`, `/signals` `:475`, `/staged` `:589`, `/settings` `:624`,
  `/analytics` `:993`, `/login` `:292`), HTML partial routes (`/partials/*`), SSE
  `/stream` (`:1411-1462`), `/api/emergency-preview` HTML (`:1350`), `/api/trading-status`
  (`:1401`). ~65 `TemplateResponse`/`HTMLResponse` sites total — the D-09/D-10 deletion set.
- `nginx/telebot.conf` — single `location /` proxy (`:47-60`) carrying both stacks; the
  SSE block (`proxy_buffering off` / `proxy_cache off` / long `proxy_read_timeout`,
  `:54-59`) is removed in D-10 commit 3. `/login` rate-limit block (`:36-45`) must survive.
- `Dockerfile` — **Stage 1 `css-build`** (Tailwind v4 standalone CLI, `:1-40`) is the
  CUT-03 removal target; **Stage 2 `spa-build`** (Vite, `:42-52`) and the Stage-3 SPA
  overlay (`COPY --from=spa-build /spa/dist/ ./static/app/`, `:71-72`) STAY. Note WR-06
  comment (`:7-12`): the two Tailwind stylesheets share the brand palette only during the
  parallel-run window — that coupling disappears once Stage 1 is gone.

### Teardown deletion targets (CUT-03 inventory — researcher to fully enumerate)
- `templates/` — all Jinja templates (page + partials: `overview.html`, `positions.html`,
  `partials/positions_table.html`, `edit_levels_modal.html`, `position_drilldown.html`,
  `kill_switch_preview.html`, `settings.html`, `account_settings_tab.html`,
  `settings_confirm_modal.html`, `settings_audit_timeline.html`, `pending_stages.html`, …).
- `static/vendor/` — Basecoat assets; `static/css/input.css`, `tailwind.config.js`,
  `scripts/build_css.sh`, the hashed `static/css/app.*.css` + `manifest.json` artifacts.
- HTMX-era tests under `tests/` (e.g. `test_ui_substrate.py`).

### Phase contracts this phase relies on (already shipped — do not modify)
- `.planning/phases/08-json-api-foundation/08-CONTEXT.md` — the `/api/v2` contract the SPA
  consumes (so legacy HTML endpoints can be safely deleted once nothing calls them).
- `.planning/phases/09-spa-scaffold-auth-design-system/09-CONTEXT.md` — D-03 SPA mount /
  `base:/app/`, SPA-03 SPA login, the parallel-run substrate state Phase 12 inherits.
- `.planning/phases/10-read-only-page-migration-analytics-pilot-signals-history-sta/10-CONTEXT.md`
  — the 4 read-only SPA pages cut over first (D-05 order).
- `.planning/phases/11-live-money-pages-settings/11-CONTEXT.md` — the live-money SPA pages
  (overview/positions/kill-switch/settings) cut over last; their parity targets list the
  exact legacy templates each SPA page must match for the D-04 checklist.

### UAT pattern to mirror
- `.planning/phases/06-staged-entry-execution/06-HUMAN-UAT.md` — the format precedent for
  the per-page `12-CUTOVER-CHECKLIST.md` sign-off rows (D-04).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Parallel-run is already live** — `SpaStaticFiles` SPA mount + legacy routes coexist
  behind one nginx `location /`. CUT-01 is mostly a confirm/document task, not new build.
- **Per-page redirect is a one-line change per route** — each legacy `@app.get` already
  returns a page; swapping its body for `RedirectResponse('/app/<page>', 303)` is minimal,
  and `RedirectResponse` is already imported (`dashboard.py:22`).
- **bot.py imports dashboard.py unchanged** — D-09 keeps the module name + app object, so
  no bot.py churn.

### Established Patterns
- **Reversible-at-every-step** — the whole cutover is built so each step is one revertable
  commit (D-01 redirects, D-10 grouped teardown commits).
- **Server-confirmed live-money discipline (Phase 11)** — unchanged by cutover; the SPA
  pages already enforce it. Cutover only changes *which* UI the operator reaches.
- **Two Tailwind stylesheets during parallel run** — the HTMX CSS (Dockerfile Stage 1) and
  the SPA CSS (Vite) both render the brand palette; this coupling (Dockerfile WR-06 note)
  ends when Stage 1 is removed in CUT-03.

### Integration Points
- `dashboard.py` legacy routes → redirect bodies (D-01), then deletion (D-09/D-10).
- `nginx/telebot.conf` `location /` SSE block → removed once `/stream` is gone (D-10).
- `Dockerfile` Stage 1 `css-build` → removed; Stage 2 `spa-build` + Stage-3 SPA overlay
  stay (D-10).

</code_context>

<specifics>
## Specific Ideas

- **"Per-page redirect, one commit each — rollback is `git revert`."** The cutover unit is
  a single page's redirect commit; reversibility is literally commit-granular.
- **"Phase 12 does the MT5-demo UAT."** The still-open Phase 10/11 live verification folds
  into the cutover gate — verify a page on the demo, then cut it over.
- **"Read-only first, kill-switch last."** analytics → signals → history → staged →
  overview → settings → positions → kill-switch.
- **"Bake 7 days clean, then operator says go, then tear down."** Legacy stays deployed but
  dormant during the bake; teardown is a separate, later, go-ahead-gated step.
- **"dashboard.py stays the app host."** Strip the HTML/SSE/Jinja surface; keep the app
  factory, /api/v2 mount, SPA mount, auth, health, and `/`→`/app/`.
- **"Tear down in 4 grouped commits, not one sweep."** routes/SSE · templates+Basecoat ·
  Dockerfile-Stage-1+CSS-CLI+nginx-SSE · HTMX tests.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. The dashboard.py rename/split was considered
and rejected (kept as-is to avoid churn, D-09). No new pages, endpoints, or features were
introduced. The 7-day bake before CUT-03 is an intentional in-phase wait, not a deferral to
a later phase.

</deferred>

---

*Phase: 12-parallel-run-cutover-htmx-decommission*
*Context gathered: 2026-06-07*
