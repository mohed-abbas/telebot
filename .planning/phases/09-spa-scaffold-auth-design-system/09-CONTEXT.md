# Phase 9: SPA Scaffold + Auth + Design System - Context

**Gathered:** 2026-06-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Stand up the **Vite 8 + React 19 + Tailwind v4 + shadcn/ui** single-page app in a
new `frontend/` top-level dir, served **same-origin behind nginx as static files
with no Node runtime in production**, and establish the conventions every later
page inherits. Phase 9 ships the *consumer* of the Phase 8 JSON API — not any real
page.

In scope (SPA-01..SPA-05):
1. **Scaffold** — `frontend/` Vite project (`@vitejs/plugin-react` 6, `@tailwindcss/vite`),
   built into the runtime image, served at `/app/` via uvicorn `StaticFiles`.
2. **Design system** — dark palette mapped to Tailwind v4 `@theme` **semantic** tokens;
   shadcn/ui themed automatically; no `tailwind.config.js`.
3. **Auth consumer** — login view + fetch wrapper + boot guard, against the **already-shipped**
   Phase 8 `/api/v2/auth/*` contract (httpOnly session cookie retained; nothing in `localStorage`).
4. **Global 401 redirect** — one TanStack-Query cache handler redirects to the login view
   exactly once, no loops.
5. **Server-state / form-state split** — TanStack Query (polling) kept separate from local
   form/UI state, **proven on a real-endpoint probe** running ≥2 refetch cycles without
   clobbering an open input/modal. This is the structural kill of the HTMX refresh-race bug class.
6. **App shell** — full shell with a sidebar nav skeleton (placeholder/disabled links for the
   future pages) + client router under `/app/*`, so Phase 10 slots real pages into ready routes.

**Out of this phase (hard boundary):**
- ANY real page (analytics, signals, history, staged, overview, positions, settings, kill switch)
  → Phases 10–11. Phase 9 builds the shell + a throwaway probe widget only.
- ANY live-money action / mutation UI and optimistic-update discipline → Phase 11.
- ANY change to the bot core (`executor.py`, `trade_manager.py`, `db.py`, `mt5_connector.py`,
  MT5 bridge) — unchanged since v1.2 confines blast radius to presentation.
- New JSON API endpoints → Phase 8 (done). Phase 9 only consumes the existing contract;
  if the probe needs a read endpoint, it MUST reuse one Phase 8 already shipped.
- Removing legacy HTMX routes / SSE `/stream` / legacy Tailwind CLI stage → Phase 12.
  Legacy dashboard runs in parallel at `/` throughout Phase 9.

</domain>

<decisions>
## Implementation Decisions

### Serving & URL strategy (Open Questions 2 & 3 — RESOLVED)
- **D-01:** SPA lives under the **`/app/` subpath** (not root). Legacy HTMX keeps `/overview`,
  `/positions`, etc. untouched for parallel-run. Vite `base: "/app/"`; client router uses
  `/app/*`; deep-links/refreshes resolve to the SPA shell (`index.html` fallback). Clean,
  reversible cutover; instant rollback. (Resolves OQ2.)
- **D-02:** The built bundle is served by **uvicorn `StaticFiles`**, not nginx:
  `app.mount("/app", StaticFiles(directory="static/app", html=True))` in `dashboard.py`
  (`html=True` gives the index.html fallback for client routes). No shared-volume wiring,
  one fewer moving part; per-asset Python cost is negligible at one operator. nginx needs
  only the existing `location /` proxy (plus the Phase 8 `/api/v2/auth/login` rate-limit
  block). (Resolves OQ3; chosen over nginx-alias-from-shared-volume despite the operator's
  existing `/home/murx/shared` nginx, to avoid the volume + deploy-copy coupling.)
- **D-03:** The Dockerfile gains a **Node build stage only** (`node:22-slim AS spa-build`,
  `npm ci && npm run build` → `/spa/dist`, `COPY --from=spa-build /spa/dist/ ./static/app/`).
  Runtime image stays `python:3.12-slim` — **no production Node** (honors the locked decision).
  The legacy Tailwind-CLI stage coexists until Phase 12.

### Auth & 401 handling (consumer of Phase 8 contract)
- **D-04:** Login is a **JSON POST to `/api/v2/auth/login`** (already shipped Phase 8 D-12).
  The SPA reads the readable `telebot_csrf` cookie (Phase 8 D-15) and echoes it as
  `X-CSRF-Token`; `fetch(url, { credentials: "same-origin" })` (same-origin ⇒ no CORS).
  httpOnly `telebot_session` is never read by JS; nothing stored in `localStorage` (SPA-03).
- **D-05:** **Boot guard:** on app load the SPA calls `GET /api/v2/auth/me` — `200` renders the
  app, `401` redirects to the login view.
- **D-06:** **Single global 401 handler** lives on the TanStack Query `QueryCache` *and*
  `MutationCache` `onError` (a shared `onAuthError`); the fetch wrapper throws `HttpError(status)`
  on non-2xx so both caches see it. On 401 → hard nav `window.location.assign("/app/login")`
  (clears in-memory state, prevents loops). No server change (`/api/v2` already hits the
  `_verify_auth` 401 branch). (SPA-04.)

### Scaffold ambition & app shell
- **D-07:** Build the **full app shell with a sidebar nav skeleton** now — nav structure
  mirroring the legacy dashboard, with **disabled/placeholder links** for the pages that land
  in Phases 10–11 — plus the client router under `/app/*`. Phase 10 slots real pages into
  ready-made routes rather than restructuring the shell. (Smoother handoff to page-migration phases.)

### SC#5 — server-state/form-state proof ("probe view")
- **D-08:** The polling proof uses a **real Phase-8 read endpoint** (e.g. trading-status or
  overview-meta — planner picks the lightest already-shipped read route), polled on the shell
  via `useQuery` with `refetchInterval`, demonstrated through **≥2 refetch cycles with a
  deliberate open input/modal** that must NOT be clobbered by a background refetch. This proves
  the *real* data path (not a synthetic counter). The probe widget is **throwaway** — removed
  when Phase 10 builds the first real page. (SPA-05.)

### TanStack Query convention (the inherited default — research §4)
- **D-09:** Establish the QueryClient defaults every later page inherits: `refetchInterval`
  per live view (overview-class views ~3000ms), **`refetchIntervalInBackground: false`**
  (pause polling on hidden tab), `placeholderData: keepPreviousData` (no flicker on refetch),
  and the global `onAuthError`. Server state = TanStack Query; form/UI state = local
  (react-hook-form later) — never mixed. (Exact `staleTime`/retry tuning = planner's call.)

### Design tokens & shadcn set
- **D-10:** Dark palette (`#252542` / `#1a1a2e` / `#0f0f1a`) maps to shadcn's **semantic
  roles** via Tailwind v4 `@theme` (`--background`, `--card`, `--foreground`, `--primary`,
  `--muted`, **`--destructive`**, etc.) — components theme automatically and the `destructive`
  role is ready for the live-money buttons in Phase 11. No `tailwind.config.js` (SPA-02).
- **D-11:** Install **only the shadcn components the shell + login + probe need now** (e.g.
  button, input, label, card, sonner/toast). Each later page adds its own components via the
  shadcn CLI as needed — keeps Phase 9 lean, avoids unused/re-themed components.

### Dev workflow
- **D-12:** `npm run dev` (Vite dev server + HMR) with a proxy in `vite.config.ts` forwarding
  `/api` → the dev container (`docker-compose.dev.yml`, port per that file). Vite proxying the
  API under the same dev origin keeps cookies same-origin in dev. (Research §5.)

### Claude's Discretion (planner/researcher decides)
- Exact `frontend/` internal layout (`src/` structure, where the fetch wrapper / queryClient /
  router / shell components live), TypeScript config, and lint/format setup.
- Which specific Phase-8 read endpoint backs the D-08 probe (lightest already-shipped read).
- Exact `staleTime`, retry policy, and per-view `refetchInterval` values within D-09's frame.
- The precise semantic-token hex assignments (which palette value → which role) and any
  derived shades shadcn needs.
- Whether the nav skeleton links render disabled vs hidden-until-built (within D-07's
  "full shell, placeholders for future pages").
- Pinned minor/patch versions of React 19 / Vite 8 / shadcn deps (majors are locked).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & milestone scope
- `.planning/REQUIREMENTS.md` §SPA — Frontend Foundation (SPA-01..SPA-05) — the 5 requirements
  this phase delivers; "Locked stack decisions (FINAL)" note (Vite 8, `@vitejs/plugin-react` 6,
  Tailwind v4 mandatory) and Open Questions 1–3.
- `.planning/ROADMAP.md` Phase 9 — goal + 5 success criteria + Research flag + UI hint.
- `.planning/PROJECT.md` §Current Milestone + §Key Decisions — "Vite SPA (static behind nginx)
  over Next.js", "keep httpOnly session-cookie auth, same-origin; no localStorage tokens".
- `.planning/STATE.md` §Blockers/Concerns — Pitfall 1 (no optimistic updates — a Phase-11
  concern but the convention starts here), Pitfall 5 (server-side formatting — SPA reads
  `*_display`, submits the bare numeric); Phase 9 prep todo (URL strategy + static-serving —
  resolved here as D-01/D-02).

### v1.2 research synthesis (HIGH confidence — primary design source for this phase)
- `.planning/research/ARCHITECTURE.md` §2 (Auth for an SPA on session cookies — login flow,
  boot guard, global 401, CSRF echo, same-origin cookie), §3 (Same-origin nginx routing —
  `/app/` subpath, serving options a/b), §4 (Live data transport — keep polling, TanStack
  Query `refetchInterval` + `refetchIntervalInBackground:false` + `keepPreviousData`),
  §5 (Build/Deploy — Vite stage in Dockerfile, `frontend/` dir, `base:"/app/"`, uvicorn mount,
  dev proxy), §"New vs Modified Components", §"Anti-Patterns to Avoid" (1 localStorage,
  2 toast HTML, 3 HX-Request CSRF, 5 no WebSocket). **Most directly applicable doc.**
- `.planning/research/PITFALLS.md` — Pitfall 1 (no optimistic updates), Pitfall 2 (CSRF for SPA),
  Pitfall 5 (server-side number/time formatting).
- `.planning/research/STACK.md` — locked v1.2 frontend stack (React 19, Vite 8, Tailwind v4,
  shadcn/ui, TanStack Query).
- `.planning/research/FEATURES.md` — SPA foundation feature breakdown.
- `.planning/research/SUMMARY.md` — executive summary + must-mitigate pitfalls.

### Phase 8 contract this SPA consumes (do NOT change — consume only)
- `.planning/phases/08-json-api-foundation/08-CONTEXT.md` — D-05 dual-value `*_display`
  fields (SPA reads `_display` for render, bare field for submit), D-06/D-07 ISO+UTC
  timestamps, D-12 full `/api/v2/auth/{login,logout,me,csrf}` contract, D-15 `telebot_csrf`
  cookie + `X-CSRF-Token` double-submit, D-16 CSRF regression test.
- `.planning/phases/08-json-api-foundation/08-04-SUMMARY.md`, `08-05-SUMMARY.md` — the shipped
  mutation + settings JSON envelopes the later pages (10/11) will call.

### Codebase intel & grounding (current system)
- `dashboard.py` — FastAPI app: `app.mount` site for `/app` StaticFiles (D-02), `_verify_auth`
  `/api/`→401 branch reused by the SPA (no change), existing nginx `location /` proxy.
  ⚠ `.planning/codebase/STACK.md` / `STRUCTURE.md` are dated 2026-03-19 (pre-v1.1/v1.2) — they
  predate the Postgres migration and the entire v1.2 SPA work; treat ROADMAP/REQUIREMENTS/
  research + Phase 8 CONTEXT as authoritative over those maps.
- `Dockerfile` / `docker-compose.dev.yml` — the multi-stage build (add Node `spa-build` stage,
  D-03) and the dev API origin for the Vite dev proxy (D-12).
- nginx config (shared-nginx at `/home/murx/shared`) — `location /` proxy + Phase 8
  `/api/v2/auth/login` rate-limit; no `/app/` location needed under D-02 (uvicorn serves it).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Phase 8 `/api/v2/auth/*`** (login/logout/me/csrf) — shipped & curl-tested; the SPA is a
  pure consumer. `/api/v2` read endpoints (trading-status, overview-meta, etc.) back the D-08 probe.
- **Phase 8 dual-value contract** (`*_display` + bare field) — the SPA's render/submit rule is
  already defined by the API; no client-side formatting (guards the XAUUSD pip-size bug class).
- **`_verify_auth` `/api/`→401 branch** (`dashboard.py`) — the SPA's global 401 redirect needs
  no server change; `/api/v2` already 401s when unauthenticated.
- **Existing Tailwind v4.2.2 on the backend** — the SPA's Tailwind v4 choice aligns; `@theme`
  token approach is consistent with the backend.

### Established Patterns
- **Presentation-layer-only blast radius** (v1.2): bot core modules stay untouched; the SPA is
  additive (`frontend/` + `static/app/` + `app.mount`).
- **Parallel-run** (CUT-01): legacy HTMX at `/`, SPA at `/app/`, both live; cutover is
  per-page and reversible — Phase 9 only stands up the empty shell.
- **Server-side formatting discipline** (Pitfall 5): SPA never re-derives precision.

### Integration Points
- `app.mount("/app", StaticFiles(..., html=True))` in `dashboard.py` (single additive line).
- Dockerfile `spa-build` stage + `COPY --from=spa-build … ./static/app/`.
- Vite `base:"/app/"`; dev proxy `/api` → dev container.
- nginx: existing `location /` proxy covers `/app/` (served by uvicorn); no new location block.

</code_context>

<specifics>
## Specific Ideas

- **"No real pages in Phase 9."** The deliverable is an *empty but complete* shell: login works,
  401 redirects once, the nav skeleton is there with disabled links, and a throwaway probe
  proves the polling/form-state split. Pages are Phases 10–11.
- **"Prove the bug-class is dead before building on it."** SC#5 is the whole point — a real
  background poll running through ≥2 cycles must not clobber an open input/modal. This is the
  structural fix for the HTMX refresh-race bugs that triggered the rewrite; demonstrate it on a
  real endpoint, not a toy.
- **"Simplest serving that honors no-Node-in-prod."** uvicorn StaticFiles over nginx-alias —
  fewer moving parts win for a single-operator tool, even with a shared nginx available.
- **"destructive role ready now."** Semantic tokens include `--destructive` up front so the
  Phase 11 live-money buttons inherit it without re-theming.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (Live-money mutation UI, optimistic-update
discipline, react-hook-form + zod validation, and the actual pages were raised only as the
*reason* certain Phase-9 conventions exist — `destructive` token, server-state/form-state split,
keepPreviousData — and remain assigned to Phases 10–11. The legacy-route/SSE/Tailwind-CLI
removal remains Phase 12.)

</deferred>

---

*Phase: 9-spa-scaffold-auth-design-system*
*Context gathered: 2026-06-04*
</content>
</invoke>
