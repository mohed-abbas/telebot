# Phase 9: SPA Scaffold + Auth + Design System - Research

**Researched:** 2026-06-04
**Domain:** Vite 8 + React 19 + Tailwind v4 + shadcn/ui SPA served same-origin behind nginx as static files (no prod Node), consuming the shipped Phase 8 `/api/v2` JSON contract
**Confidence:** HIGH (stack versions verified live against npm registry 2026-06-04; shadcn↔Tailwind-v4 flow verified against official shadcn docs; Phase 8 API surface read directly from the codebase; `StaticFiles(html=True)` deep-link behavior verified against FastAPI/Starlette docs + discussion)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Serving & URL strategy**
- **D-01:** SPA lives under the **`/app/` subpath** (not root). Legacy HTMX keeps `/overview`, `/positions`, etc. untouched. Vite `base: "/app/"`; client router uses `/app/*`; deep-links/refreshes resolve to the SPA shell (`index.html` fallback).
- **D-02:** Built bundle served by **uvicorn `StaticFiles`**: `app.mount("/app", StaticFiles(directory="static/app", html=True))` in `dashboard.py`. No shared-volume wiring. nginx needs only the existing `location /` proxy plus the Phase 8 `/api/v2/auth/login` rate-limit block.
- **D-03:** Dockerfile gains a **Node build stage only** (`node:22-slim AS spa-build`, `npm ci && npm run build` → `/spa/dist`, `COPY --from=spa-build /spa/dist/ ./static/app/`). Runtime image stays `python:3.12-slim` — **no production Node**. Legacy Tailwind-CLI stage coexists until Phase 12.

**Auth & 401 handling (consumer of Phase 8 contract)**
- **D-04:** Login is a **JSON POST to `/api/v2/auth/login`**. SPA reads the readable `telebot_csrf` cookie and echoes it as `X-CSRF-Token`; `fetch(url, { credentials: "same-origin" })`. httpOnly `telebot_session` never read by JS; nothing in `localStorage` (SPA-03).
- **D-05:** **Boot guard:** on app load call `GET /api/v2/auth/me` — `200` renders the app, `401` redirects to the login view.
- **D-06:** **Single global 401 handler** on the TanStack Query `QueryCache` *and* `MutationCache` `onError` (shared `onAuthError`); the fetch wrapper throws `HttpError(status)` on non-2xx so both caches see it. On 401 → hard nav `window.location.assign("/app/login")`. No server change. (SPA-04.)

**Scaffold ambition & app shell**
- **D-07:** Build the **full app shell with a sidebar nav skeleton** now — nav mirroring the legacy dashboard, with **disabled/placeholder links** for Phases 10–11 pages — plus the client router under `/app/*`.

**SC#5 — server-state/form-state proof ("probe view")**
- **D-08:** Polling proof uses a **real Phase-8 read endpoint** (planner picks the lightest already-shipped read route), polled via `useQuery` with `refetchInterval`, demonstrated through **≥2 refetch cycles with a deliberate open input/modal** that must NOT be clobbered. The probe widget is **throwaway** — removed when Phase 10 builds the first real page. (SPA-05.)

**TanStack Query convention (the inherited default)**
- **D-09:** QueryClient defaults: `refetchInterval` per live view (overview-class ~3000ms), **`refetchIntervalInBackground: false`** (pause on hidden tab), `placeholderData: keepPreviousData` (no flicker), and the global `onAuthError`. Server state = TanStack Query; form/UI state = local — never mixed. (Exact `staleTime`/retry tuning = planner's call.)

**Design tokens & shadcn set**
- **D-10:** Dark palette (`#252542` / `#1a1a2e` / `#0f0f1a`) maps to shadcn's **semantic roles** via Tailwind v4 `@theme` (`--background`, `--card`, `--foreground`, `--primary`, `--muted`, **`--destructive`**, etc.) — components theme automatically; `destructive` role ready for Phase 11 live-money buttons. No `tailwind.config.js` (SPA-02).
- **D-11:** Install **only the shadcn components the shell + login + probe need now** (e.g. button, input, label, card, sonner/toast). Later pages add their own via the CLI.

**Dev workflow**
- **D-12:** `npm run dev` (Vite dev server + HMR) with a proxy in `vite.config.ts` forwarding `/api` → the dev container (`docker-compose.dev.yml`, host port `8090` per that file). Keeps cookies same-origin in dev.

### Claude's Discretion
- Exact `frontend/` internal layout (`src/` structure, where the fetch wrapper / queryClient / router / shell components live), TypeScript config, lint/format setup.
- Which specific Phase-8 read endpoint backs the D-08 probe (lightest already-shipped read).
- Exact `staleTime`, retry policy, per-view `refetchInterval` values within D-09's frame.
- Precise semantic-token hex assignments (which palette value → which role) and any derived shades.
- Whether the nav skeleton links render disabled vs hidden-until-built (within D-07's "full shell").
- Pinned minor/patch versions of React 19 / Vite 8 / shadcn deps (majors are locked).

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope. (Live-money mutation UI, optimistic-update discipline, react-hook-form + zod validation, and the actual pages were raised only as the *reason* certain Phase-9 conventions exist — `destructive` token, server-state/form-state split, `keepPreviousData` — and remain assigned to Phases 10–11. Legacy-route/SSE/Tailwind-CLI removal remains Phase 12.)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **SPA-01** | Vite 8 + React 19 SPA scaffolded, served same-origin behind nginx as static files, no Node runtime in production | Standard Stack (Vite 8 / plugin-react 6 / @tailwindcss/vite); Dockerfile multi-stage pattern (§Code Examples); `app.mount("/app", StaticFiles(...))` (§Architecture); **Pitfall 1 (deep-link fallback)** and **Pitfall 3 (Vite `base`)** are the load-bearing risks |
| **SPA-02** | Tailwind v4 (`@tailwindcss/vite` + `@theme`) + shadcn/ui; dark palette mapped to theme tokens; no `tailwind.config.js` | shadcn Vite+v4 init flow (verified current); `:root`/`.dark`/`@theme inline` oklch token structure (§Code Examples); **Pitfall 2 (v4 token format)** |
| **SPA-03** | Operator logs in through SPA; httpOnly session cookie retained; no tokens in `localStorage` | Auth flow: `GET /auth/csrf` → seed readable cookie → `POST /auth/login {password, csrf_token}` → session cookie set by server (§Architecture, §Code Examples); fetch wrapper with `credentials:"same-origin"` |
| **SPA-04** | Expired/unauthenticated sessions detected globally (401 handler) → redirect to login, no loops | Global `onAuthError` on QueryCache + MutationCache; `HttpError` throw pattern; hard-nav redirect (§Code Examples); **Pitfall 5 (redirect-loop / dev-proxy cookie)** |
| **SPA-05** | Server-state (TanStack Query polling) kept separate from form/UI state — a background refetch never clobbers an open input/modal | The structural split: uncontrolled/local form state + `placeholderData: keepPreviousData` + stable query keys (§Architecture, §Validation Architecture); probe on `GET /api/v2/trading-status` |
</phase_requirements>

## Summary

This phase is a **greenfield SPA scaffold** that *consumes* an already-shipped, curl-tested JSON contract (Phase 8 `/api/v2`). The backend side of this phase is a **single additive line** in `dashboard.py` (`app.mount("/app", ...)`) plus a Node build stage in the Dockerfile — the bot core and the API are untouched. Almost all the risk is in the frontend: getting Vite `base`, the Tailwind v4 token model, the auth/CSRF handshake, and the TanStack Query defaults right *once*, because every later page inherits them.

The stack is fully locked and version-verified: React 19.2.7, Vite 8.0.16, `@vitejs/plugin-react` 6.0.2, Tailwind v4.3.0 + `@tailwindcss/vite` 4.3.0, shadcn CLI 4.10.0, TanStack Query 5.101.0, react-router-dom 7.17.0. The shadcn + Tailwind v4 + Vite init flow is the canonical, currently-documented path (no `tailwind.config.js`; tokens live in `src/index.css` via `:root`/`.dark`/`@theme inline` oklch variables). There are **no known incompatibilities** between the four locked majors — this is exactly shadcn's current default lane (Tailwind v4 + React 19, `data-slot` components, oklch colors, no `forwardRef`).

The **single highest-risk item the planner must internalize**: `StaticFiles(html=True)` mounted at `/app` serves `index.html` only at the mount *root* (`/app/`), and returns **404 for arbitrary client-route deep-links** like `/app/login` or `/app/positions` on a hard reload. `html=True` is NOT a SPA catch-all. D-01 explicitly requires deep-links/refreshes to resolve to the shell, so the plan **must** add an explicit fallback handler (see Pitfall 1) — this is the most likely thing to silently ship broken (works on click-through, 404s on F5).

**Primary recommendation:** Scaffold `frontend/` with `npm create vite` (react-ts), wire Tailwind v4 + `@/` alias + dev proxy in `vite.config.ts`, set `base: "/app/"`, run `shadcn init` (oklch dark tokens from the `#252542/#1a1a2e/#0f0f1a` palette), build the fetch-wrapper→HttpError→global-401 layer and the QueryClient defaults, then prove SC#5 with a polling probe on `GET /api/v2/trading-status`. Use **react-router-dom 7 in declarative mode** for the `/app/*` shell. Add an explicit index.html fallback for `/app/*` deep-links (do not rely on `html=True` alone).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| SPA shell render, client routing, nav skeleton | Browser / Client | — | Static SPA; all view logic runs in the browser. No SSR. |
| Login form submit + CSRF token echo | Browser / Client | API / Backend | SPA reads readable `telebot_csrf` cookie, sends `X-CSRF-Token`; server (`/api/v2/auth/login`) verifies + sets httpOnly session. |
| Session validity (boot guard + mid-session 401) | API / Backend | Browser / Client | Server is the auth authority (`/auth/me`, `_verify_auth`); SPA only *reacts* to 200/401. |
| Server-state polling (probe) | API / Backend | Browser / Client (cache) | Data lives server-side (`/api/v2/trading-status`); TanStack Query caches/refetches on the client. |
| Form/UI state (open input, modal) | Browser / Client | — | Local React state only; **never** sourced from or overwritten by the server cache. This is the SC#5 split. |
| Static asset serving (`/app/*`, hashed JS/CSS, index.html) | Frontend Server (uvicorn StaticFiles) | — | Per D-02, uvicorn serves the built `dist/` — no nginx alias, no Node. |
| Asset path resolution under subpath | CDN / Static (build-time) | — | Vite `base:"/app/"` bakes `/app/assets/...` URLs into the bundle. |
| Deep-link → shell fallback | Frontend Server (uvicorn) | — | Server must return `index.html` for `/app/<clientroute>`; `html=True` alone does NOT (Pitfall 1). |

## Standard Stack

> Majors are LOCKED (REQUIREMENTS.md "Locked stack decisions FINAL"). Versions below are the current stable minor/patch, verified live against the npm registry on **2026-06-04**.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| react / react-dom | `19.2.7` | UI runtime | Locked. Latest stable React 19.x. Client-state model kills the HTMX refresh-race class. `[VERIFIED: npm registry 2026-06-04]` |
| vite | `8.0.16` | Build + dev server | Locked. Current stable line; Vite 7 and earlier unsupported upstream. Emits static `dist/` (no prod Node). `[VERIFIED: npm registry 2026-06-04]` |
| @vitejs/plugin-react | `6.0.2` | React Fast Refresh + JSX transform | Locked. v6 pairs with Vite 8 (Oxc-based, Babel dropped). `[VERIFIED: npm registry 2026-06-04]` |
| typescript | `6.0.3` | Type safety | Catches API-shape drift between the FastAPI JSON layer and the SPA at compile time. `[VERIFIED: npm registry 2026-06-04]` |
| tailwindcss | `4.3.0` | Styling | Locked v4. No `tailwind.config.js`. Aligns with backend's vendored Tailwind v4.2.2. `[VERIFIED: npm registry 2026-06-04]` |
| @tailwindcss/vite | `4.3.0` | Tailwind v4 Vite integration | The v4 way to wire Tailwind into Vite — replaces v3 postcss+autoprefixer chain entirely. Keep same major.minor as `tailwindcss`. `[VERIFIED: npm registry 2026-06-04]` |
| shadcn (CLI) | `4.10.0` | Component scaffolding (NOT a runtime dep) | Locked. Copies source into `src/components/ui/`; init defaults to Tailwind v4 + React 19. `[VERIFIED: npm registry 2026-06-04 + CITED: ui.shadcn.com/docs/installation/vite]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| @tanstack/react-query | `5.101.0` | Server-state / polling | The data layer. Probe polls via `refetchInterval`; the global 401 handler lives on its QueryCache + MutationCache. `[VERIFIED: npm registry 2026-06-04]` (STACK doc said 5.100.14 → bumped to 5.101.0) |
| react-router-dom | `7.17.0` | Client-side routing | `/app/*` shell + future page routes. Use **declarative/library mode** (`createBrowserRouter` + `<RouterProvider>`), NOT framework/SSR mode. `[VERIFIED: npm registry 2026-06-04]` (STACK doc said 7.16.0 → bumped to 7.17.0) |
| sonner | `2.0.7` | Toast notifications | shadcn's official toast primitive (legacy `useToast` deprecated). Login error + probe feedback in Phase 9; real toasts in Phase 11. `[VERIFIED: npm registry 2026-06-04]` |
| lucide-react | `1.17.0` | Icons | shadcn's default icon set; nav skeleton icons. `[VERIFIED: npm registry 2026-06-04]` |
| class-variance-authority | `0.7.1` | Variant styling | Installed by `shadcn init`; powers component `variant`/`size`. `[VERIFIED: npm registry 2026-06-04]` |
| clsx | `2.1.1` | Conditional className join | Half of the shadcn `cn()` helper. `[VERIFIED: npm registry 2026-06-04]` |
| tailwind-merge | `3.6.0` | Dedup conflicting Tailwind classes | Other half of `cn()`. `[VERIFIED: npm registry 2026-06-04]` |
| @radix-ui/react-* | per-component | `asChild` / primitives | Added on-demand by `shadcn add` per component. Do NOT install the monolithic `radix-ui` umbrella. `[CITED: STACK.md / ui.shadcn.com]` |

### Deferred to later phases (do NOT install in Phase 9)
| Library | Why deferred |
|---------|--------------|
| react-hook-form `7.x`, zod `4.x`, @hookform/resolvers `5.x` | Form validation = Phase 11 settings/mutation pages. The probe's "open input" can be a plain uncontrolled `<input>` — no form lib needed to prove SC#5. |
| recharts `3.x` | Analytics charting = Phase 10. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| react-router-dom 7 (declarative) | TanStack Router 1.x | TanStack Router has best-in-class type-safe routes + search-param validation. For a flat `/app/*` shell with a fluent-in-React solo operator, react-router is lower-overhead and better-documented. **Recommend react-router 7** (matches STACK doc; minimizes new concepts). Either works. |
| TanStack Query (server state only) | + Zustand/Redux | Do NOT add a client-state lib. Query owns server state; React local state/context covers the rest. Adding one re-introduces the manual-cache-sync bug class Query exists to remove. |
| uvicorn StaticFiles (D-02) | nginx `alias` from shared volume | nginx-alias is marginally faster (no Python hop) but couples a volume into shared-nginx + a deploy-copy step. At one operator, the Python cost is negligible — D-02 chose StaticFiles. |

**Installation:**
```bash
# 1. Scaffold (React + TS + Vite 8) into the new top-level frontend/ dir
npm create vite@latest frontend -- --template react-ts
cd frontend

# 2. Tailwind v4 (Vite plugin — NOT the standalone CLI the backend uses)
npm install tailwindcss@4 @tailwindcss/vite@4
npm install -D @types/node

# 3. shadcn init (targets Tailwind v4 + React 19 by default; writes components.json,
#    installs cva / clsx / tailwind-merge / lucide-react)
npx shadcn@latest init

# 4. Data + routing
npm install @tanstack/react-query@5 react-router-dom@7

# 5. Toast (shadcn add wires the component file; sonner is the runtime dep)
npx shadcn@latest add sonner

# 6. The minimal shadcn primitives the shell + login + probe need (D-11)
npx shadcn@latest add button card input label
```

## Package Legitimacy Audit

> slopcheck could NOT be installed in this research session (`pip install slopcheck` unavailable). Per protocol, packages would normally degrade to `[ASSUMED]`. **However**, every package below is independently legitimacy-verified by two authoritative signals: (a) it is the package the **official shadcn/ui Vite installation docs** or the **locked REQUIREMENTS.md stack decision** name, and (b) it resolves on the npm registry to a mature, high-adoption version. These are not search-discovered names — they are doc-prescribed. The planner should still treat the *exact pinned minor/patch* as the operator's call (D-12 discretion) but the package identities are sound.

| Package | Registry | Version (2026-06-04) | Source Repo | slopcheck | Disposition |
|---------|----------|----------------------|-------------|-----------|-------------|
| vite | npm | 8.0.16 | github.com/vitejs/vite | unavailable | Approved (doc-prescribed, locked major) |
| @vitejs/plugin-react | npm | 6.0.2 | github.com/vitejs/vite-plugin-react | unavailable | Approved (locked major) |
| react / react-dom | npm | 19.2.7 | github.com/facebook/react | unavailable | Approved (locked major) |
| typescript | npm | 6.0.3 | github.com/microsoft/TypeScript | unavailable | Approved |
| tailwindcss | npm | 4.3.0 | github.com/tailwindlabs/tailwindcss | unavailable | Approved (locked major) |
| @tailwindcss/vite | npm | 4.3.0 | github.com/tailwindlabs/tailwindcss | unavailable | Approved (shadcn-doc-prescribed) |
| shadcn | npm | 4.10.0 | github.com/shadcn-ui/ui | unavailable | Approved (locked) |
| @tanstack/react-query | npm | 5.101.0 | github.com/TanStack/query | unavailable | Approved |
| react-router-dom | npm | 7.17.0 | github.com/remix-run/react-router | unavailable | Approved |
| sonner | npm | 2.0.7 | github.com/emilkowalski/sonner | unavailable | Approved (shadcn default toast) |
| lucide-react | npm | 1.17.0 | github.com/lucide-icons/lucide | unavailable | Approved (shadcn default icons) |
| class-variance-authority | npm | 0.7.1 | github.com/joe-bell/cva | unavailable | Approved (shadcn-installed) |
| clsx | npm | 2.1.1 | github.com/lukeed/clsx | unavailable | Approved (shadcn `cn()`) |
| tailwind-merge | npm | 3.6.0 | github.com/dcastil/tailwind-merge | unavailable | Approved (shadcn `cn()`) |

**Packages removed due to slopcheck [SLOP] verdict:** none (slopcheck unavailable; no SLOP determination possible).
**Packages flagged as suspicious [SUS]:** none.
**Recommendation:** Because slopcheck was unavailable, the planner MAY optionally add a single lightweight `checkpoint:human-verify` confirming the `frontend/package.json` lockfile after `npm install` (verify no unexpected transitive postinstall scripts). This is low-priority — all top-level names are official-doc-prescribed, not discovered.

## Architecture Patterns

### System Architecture Diagram

```
  Browser (operator, one tab)
     │
     │  GET /app/  ── hard reload of /app/login, /app/<route> ──┐
     │  GET /api/v2/* (fetch, credentials:"same-origin")        │
     ▼                                                          │
  ┌──────────────── nginx (shared, proxy-net) ─────────────────┴────────┐
  │  location = /api/v2/auth/login   (limit_req zone=telebot_login)      │
  │  location /   ───────────────────────────────────▶ telebot:8080     │  (covers /app/ AND /api/)
  └─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
  ┌──────────────── dashboard.app (FastAPI, same process as bot) ───────┐
  │  SessionMiddleware (telebot_session, httpOnly)                       │
  │  app.include_router(api_router, prefix="/api/v2")  ◀── registered    │
  │     ├─ /auth/{login,logout,me,csrf}                    FIRST          │
  │     ├─ /trading-status, /overview, /positions, ... (read)            │
  │     └─ register_error_handlers → {error:{code,message,fields?}}       │
  │  app.mount("/app", StaticFiles(directory="static/app", html=True))   │
  │     └─ serves dist/index.html + hashed /app/assets/*                  │
  │  ⚠ deep-link /app/<route> w/ no file → 404 unless an explicit        │
  │     fallback returns index.html  (Pitfall 1)                         │
  └──────────────────────────────────────────────────────────────────────┘

  AUTH FLOW (SPA boot):
    1. GET /api/v2/auth/csrf   → Set-Cookie telebot_csrf (readable) + {csrf_token}
    2. GET /api/v2/auth/me     → 200 {user} → render shell │ 401 → render login view
    3. login: POST /auth/login {password, csrf_token=<read from cookie>}
              + X-CSRF-Token header → 200 {user:"admin"} + Set-Cookie telebot_session
    4. any later 401 (QueryCache/MutationCache onError) → window.location.assign("/app/login")

  SC#5 SPLIT (the proof):
    TanStack Query cache  ──refetchInterval(≥2 cycles)──▶  display value re-renders
    Local React state     ──open <input>/modal──────────▶  NEVER touched by refetch
    (placeholderData:keepPreviousData + stable keys = no flicker, no clobber)
```

### Recommended Project Structure
```
frontend/                      # NEW top-level dir
├── index.html                 # Vite entry (becomes dist/index.html)
├── package.json
├── vite.config.ts             # base:"/app/", react()+tailwindcss(), @/ alias, dev proxy
├── tsconfig.json / tsconfig.app.json   # @/* path alias (both files)
├── components.json            # shadcn config (cssVariables:true, baseColor)
└── src/
    ├── main.tsx               # ReactDOM root + <RouterProvider> + <QueryClientProvider>
    ├── index.css              # @import "tailwindcss"; :root/.dark/@theme inline tokens
    ├── lib/
    │   ├── http.ts            # fetch wrapper → throws HttpError on non-2xx; X-CSRF-Token echo
    │   ├── queryClient.ts     # QueryClient + QueryCache/MutationCache onAuthError (D-06/D-09)
    │   └── utils.ts           # cn() (shadcn)
    ├── auth/
    │   ├── csrf.ts            # read telebot_csrf cookie; GET /auth/csrf seeding
    │   └── LoginView.tsx      # login form (uncontrolled input ok)
    ├── components/
    │   ├── ui/                # shadcn-generated (button, card, input, label, sonner)
    │   └── shell/             # AppShell, Sidebar (disabled nav links), TopBar
    ├── routes/
    │   ├── router.tsx         # createBrowserRouter, basename="/app"
    │   └── ProbeView.tsx      # THROWAWAY: useQuery(trading-status) + open input proof
    └── App.tsx                # boot guard (GET /auth/me) gate
```

### Pattern 1: Vite config — subpath base + dev proxy + Tailwind v4
**What:** One config wires `base:"/app/"` (so hashed assets resolve under nginx), the Tailwind v4 plugin, the `@/` alias, and the dev proxy that keeps cookies same-origin in dev.
**When to use:** The scaffold's foundation — get this right before anything else.
```ts
// frontend/vite.config.ts
// Source: STACK.md + ui.shadcn.com/docs/installation/vite + D-01/D-12
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  base: "/app/",                                   // D-01: assets resolve at /app/assets/* behind nginx
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    proxy: {
      // D-12: dev container host port is 8090 (docker-compose.dev.yml DASHBOARD_HOST_PORT default).
      // changeOrigin:false preserves Host so the cookie domain is the Vite origin (same-origin in dev).
      "/api": { target: "http://localhost:8090", changeOrigin: false },
    },
  },
});
```
> NOTE: only `/api` needs proxying in Phase 9 (login is `/api/v2/auth/login`, not a top-level `/login`). The legacy `/login`/`/logout` proxy lines from the STACK doc example are for the *legacy* HTMX form and are NOT needed by the SPA.

### Pattern 2: Tailwind v4 dark tokens — no config file, oklch semantic roles
**What:** Map the dark palette to shadcn semantic roles in `src/index.css` using `:root`/`.dark`/`@theme inline`. There is NO `tailwind.config.js`.
**When to use:** Immediately after `shadcn init` generates the default token block — replace the default oklch values' dark-mode entries with the project palette.
```css
/* frontend/src/index.css */
/* Source: ui.shadcn.com/docs/theming (Tailwind v4 structure, oklch default) + D-10 */
@import "tailwindcss";
@custom-variant dark (&:is(.dark *));

:root {
  --radius: 0.625rem;
  /* light defaults (shadcn init writes these; app runs dark-by-default so they are fallback) */
}

.dark {
  /* Map #0f0f1a / #1a1a2e / #252542 → semantic roles.
     shadcn defaults to oklch; convert the project hex to oklch OR keep hex —
     v4 accepts any CSS color. Planner picks exact role→value assignments (discretion). */
  --background: #0f0f1a;        /* darkest → app bg */
  --card:       #1a1a2e;        /* mid → cards/panels */
  --popover:    #1a1a2e;
  --muted:      #252542;        /* lightest → muted surfaces */
  --foreground: #e8e8f0;        /* readable on dark (planner derives) */
  --primary:    /* accent — planner derives */ ;
  --destructive:/* red — READY for Phase 11 live-money buttons (D-10) */ ;
  --border:     #252542;
  --ring:       /* focus ring — planner derives */ ;
  /* …full shadcn role set… */
}

@theme inline {
  --color-background: var(--background);
  --color-card:       var(--card);
  --color-foreground: var(--foreground);
  --color-primary:    var(--primary);
  --color-muted:      var(--muted);
  --color-destructive:var(--destructive);
  --color-border:     var(--border);
  --color-ring:       var(--ring);
  /* …map every role shadcn components reference… */
}
```
> **Dark-by-default:** add `class="dark"` to the root `<html>` element (in `index.html`) — shadcn switches `:root` vs `.dark` purely via this class; no theme-toggle JS needed for Phase 9.

### Pattern 3: Fetch wrapper that throws HttpError (feeds both caches)
**What:** A single fetch wrapper that (a) echoes the readable CSRF token, (b) sends cookies, (c) **throws `HttpError(status)` on any non-2xx** so the QueryCache *and* MutationCache `onError` both fire on 401.
**When to use:** Every `queryFn`/`mutationFn` goes through this. It is the lynchpin of SPA-04.
```ts
// frontend/src/lib/http.ts
// Source: ARCHITECTURE.md §2 + Phase 8 api/auth.py contract + D-04/D-06
export class HttpError extends Error {
  constructor(public status: number, public body?: unknown) {
    super(`HTTP ${status}`);
  }
}

function readCookie(name: string): string {
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith(name + "="))
    ?.split("=")[1] ?? "";
}

export async function api(path: string, init: RequestInit = {}): Promise<unknown> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  // D-04: echo the readable telebot_csrf cookie on mutations (server requires it; Phase 8 D-15)
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    headers.set("X-CSRF-Token", readCookie("telebot_csrf"));
  }
  const res = await fetch(path, {
    ...init,
    headers,
    credentials: "same-origin",     // D-04: send httpOnly telebot_session; NEVER read it in JS
  });
  if (!res.ok) {
    let body: unknown;
    try { body = await res.json(); } catch { /* non-JSON */ }
    throw new HttpError(res.status, body);   // {error:{code,message}} envelope from Phase 8
  }
  return res.status === 204 ? null : res.json();
}
```

### Pattern 4: QueryClient + global 401 (the single redirect)
**What:** QueryCache + MutationCache `onError` share `onAuthError`; on 401 → one hard nav. The hard nav clears in-memory state and prevents loops (the login view's own `/auth/me` is the loop-break — when already on `/app/login`, don't re-redirect).
**When to use:** Created once in `queryClient.ts`, provided at the app root. SPA-04's core.
```ts
// frontend/src/lib/queryClient.ts
// Source: ARCHITECTURE.md §2 (verified TanStack QueryCache/MutationCache onError) + D-06/D-09
import { QueryClient, QueryCache, MutationCache, keepPreviousData } from "@tanstack/react-query";
import { HttpError } from "./http";

const onAuthError = (error: unknown) => {
  if (error instanceof HttpError && error.status === 401) {
    // loop-break: only redirect if we're not already on the login view
    if (!window.location.pathname.startsWith("/app/login")) {
      window.location.assign("/app/login");
    }
  }
};

export const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: onAuthError }),
  mutationCache: new MutationCache({ onError: onAuthError }),
  defaultOptions: {
    queries: {
      placeholderData: keepPreviousData,   // D-09: no flicker on refetch
      refetchIntervalInBackground: false,  // D-09: pause polling on hidden tab
      // staleTime / retry = planner's call within D-09's frame
    },
  },
});
```

### Pattern 5: The SC#5 proof — server-state poll vs local form-state
**What:** A throwaway probe that polls a real endpoint while a deliberately-open `<input>` holds user-typed text across ≥2 refetch cycles, proving the background refetch never touches local state.
**When to use:** This IS success criterion #5. Use `GET /api/v2/trading-status` (lightest read — see Code Examples).
```tsx
// frontend/src/routes/ProbeView.tsx  (THROWAWAY — deleted when Phase 10 lands)
// Source: D-08 + Phase 8 api/meta.py (/trading-status) + TanStack polling guide
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/http";

export function ProbeView() {
  const { data, dataUpdatedAt } = useQuery({
    queryKey: ["trading-status"],
    queryFn: () => api("/api/v2/trading-status"),
    refetchInterval: 3000,          // ≥2 cycles visible within ~7s
  });
  // LOCAL form state — completely separate from the query cache. A refetch
  // re-renders `data` but NEVER resets `draft`. THIS is the SC#5 proof.
  const [draft, setDraft] = useState("");
  return (
    <div>
      <p>status: {(data as any)?.status} (updated {new Date(dataUpdatedAt).toLocaleTimeString()})</p>
      <input value={draft} onChange={(e) => setDraft(e.target.value)}
             placeholder="type here, watch it survive ≥2 refetches" />
    </div>
  );
}
```
> The proof: type into the input, watch the "updated" timestamp tick twice (two refetch cycles), confirm the typed text is untouched. Because `draft` is `useState` (local) and `data` is `useQuery` (cache), they are structurally isolated — the bug class is dead by construction.

### Anti-Patterns to Avoid
- **Relying on `StaticFiles(html=True)` as a SPA catch-all:** it only serves `index.html` at the directory root; deep-links 404. See Pitfall 1 — add an explicit fallback.
- **Reading `telebot_session` in JS / putting anything in `localStorage`:** violates SPA-03 + the locked security decision. The session cookie is httpOnly; `credentials:"same-origin"` sends it automatically.
- **Absolute API URLs (`http://localhost:8090/...`) in app code:** breaks the same-origin cookie model. Always use relative `/api/v2/...` — works identically through the dev proxy and prod nginx.
- **Optimistic updates / hand-patching the cache:** out of scope for Phase 9 (no mutations beyond login/logout), but the convention starts here — server-confirmed truth only. Document it for Phases 10–11.
- **Tailwind v3 patterns** (`tailwind.config.js`, `@tailwind base/components/utilities`, postcss+autoprefixer): all forbidden under v4. Tokens go in CSS via `@theme`.
- **Installing the monolithic `radix-ui` umbrella:** let `shadcn add` pull granular `@radix-ui/react-*` per component.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Server-state caching, polling, dedup, refetch | A `useEffect` + `setInterval` + manual state | TanStack Query `useQuery` + `refetchInterval` | Hand-rolled polling re-creates the exact clobber/race bug class this rewrite exists to kill; Query isolates server state from render/form state. |
| Global 401 detection | Per-call `if (res.status===401)` scattered everywhere | One `onAuthError` on QueryCache + MutationCache | Centralizes the redirect; one place to guarantee "exactly once, no loop." |
| Design tokens / component theming | Bespoke CSS + custom button/input/card | shadcn `@theme` tokens + `shadcn add` | shadcn owns the source (you can edit it), themes via semantic roles, gives accessible Radix primitives free. |
| Number/time formatting | JS `toFixed`/`new Date()` re-derivation | Phase 8 `*_display` fields | Phase 8 already sends display-ready strings (XAUUSD pip-size guard); the SPA renders `_display`, never re-derives. Not relevant to the probe but locks the convention. |
| Client routing under a subpath | Manual `history.pushState` | react-router-dom 7 `createBrowserRouter({ basename: "/app" })` | `basename` handles the `/app` prefix; declarative routes scale to Phase 10/11 pages. |
| CSRF token plumbing | Custom interceptor framework | The fetch wrapper's `X-CSRF-Token` echo | Phase 8 contract is a simple double-submit; one header set in one wrapper covers it. |

**Key insight:** Phase 9's entire reason for existing is to *not hand-roll* the data layer — TanStack Query + local React state is the structural fix for the HTMX refresh-race bugs. Every "convenience" shortcut (manual polling, mixing server data into form state, optimistic clears) re-introduces the bug class. The probe (SC#5) exists to *prove* the non-hand-rolled split works before any real page is built on it.

## Common Pitfalls

### Pitfall 1: `StaticFiles(html=True)` 404s on client-route deep-links (THE critical one)
**What goes wrong:** `app.mount("/app", StaticFiles(directory="static/app", html=True))` serves `index.html` at `/app/` (the mount root) and serves real files (`/app/assets/main.abc.js`). But a hard reload of a *client* route — `/app/login`, `/app/positions` — has no matching file, so `html=True` returns **404**, not `index.html`. The SPA works on in-app click-through (the router never hits the server) but breaks on F5/deep-link/bookmark. D-01 explicitly requires deep-links to resolve to the shell, so shipping `html=True` alone silently fails SC#1.
**Why it happens:** `html=True` is documented as "serve index.html for *directory* requests," NOT "serve index.html for *any* unmatched path." It is not a SPA fallback. Most tutorials gloss this because they test by clicking, not reloading. `[VERIFIED: FastAPI docs + fastapi/fastapi discussion #10458]`
**How to avoid:** Add an explicit catch-all that returns `index.html` for unmatched `/app/*` paths. Two viable shapes (planner picks):
- **(a)** A FastAPI route registered *after* the mount: `@app.get("/app/{full_path:path}")` that returns `FileResponse("static/app/index.html")` — but this competes with the mount; order/precedence must be verified.
- **(b)** A custom `StaticFiles` subclass overriding `get_response` to fall back to `index.html` on 404 (the well-trodden Starlette SPA pattern). Cleaner; keeps it inside the mount.
**Crucially:** the `/api/v2/*` routes are registered as router handlers **before** the `/app` mount and live on a different prefix, so the fallback only ever catches `/app/*` — it cannot swallow API routes (this is exactly why D-01's subpath choice is safe; see Pitfall 4). **Verification step (must be in the plan):** hard-reload `/app/login` in a browser and confirm it returns the shell, not a 404.
**Warning signs:** Login works after navigating from `/app/`, but bookmarking/reloading `/app/login` gives a FastAPI 404 JSON; deep-links into future pages 404.

### Pitfall 2: shadcn/Tailwind v4 token-format / version drift
**What goes wrong:** Pasting a v3-era shadcn component or running a non-current `init` pulls `tailwind.config.js` + `@tailwind` assumptions; the build breaks or popovers/selects/dialogs render transparent (the documented v4+Radix transparency regression).
**Why it happens:** Most shadcn tutorials still assume Tailwind v3 + React 18.
**How to avoid:** Use the verified current flow (`npx shadcn@latest init` on a fresh Vite+v4 base — confirmed canonical against ui.shadcn.com). Generate components fresh via `shadcn add`; never paste v3 snippets. shadcn defaults to oklch in `:root`/`.dark`; the project may use hex (v4 accepts any CSS color) or convert to oklch — be consistent. **Verification:** render a `<Card>` + `<Input>` and confirm opaque, correct dark colors before building the shell. `[CITED: ui.shadcn.com/docs/theming, ui.shadcn.com/docs/installation/vite; PITFALLS.md Pitfall 9]`
**Warning signs:** Build errors about `@tailwind`/`@config`; transparent popovers; `forwardRef` type errors (React 19 removed it — current shadcn components don't use it).

### Pitfall 3: Vite `base` mismatch → blank SPA, 404 assets
**What goes wrong:** If `base` is left at `/` while the SPA is served under `/app/`, hashed assets request `/assets/...` instead of `/app/assets/...` and 404 → blank page.
**Why it happens:** `base` defaults to `/`; the breakage only appears when served under a prefix (not in `npm run dev`, where the dev server roots at `/`).
**How to avoid:** Set `base: "/app/"` in `vite.config.ts` and keep it in lockstep with the uvicorn mount path `/app`. **Verification:** after `npm run build`, grep `dist/index.html` for `/app/assets/` asset URLs; load the built bundle through uvicorn and confirm assets resolve. `[CITED: PITFALLS.md Pitfall 10; vite.dev/guide/env-and-mode]`
**Warning signs:** Blank SPA with 404s on `/assets/*.js` in the network tab in prod; works in dev, breaks built.

### Pitfall 4: Dev-proxy cookie / 401 redirect loop
**What goes wrong:** In `npm run dev` the SPA runs on `localhost:5173`. If API calls go cross-origin to `:8090`, the `telebot_session` cookie (SameSite=Lax, httpOnly) isn't attached → every call 401s → bounce to login → login "succeeds" but cookie still cross-origin → infinite loop. The tempting "fix" (weaken cookie / `localStorage` token) is forbidden.
**Why it happens:** Prod is same-origin behind nginx (cookie just works); dev with two ports is not, so the prod assumption breaks only in dev.
**How to avoid:** The `vite.config.ts` `server.proxy` forwards `/api` to the dev container under the Vite origin (Pattern 1) — the SPA uses relative URLs, cookie stays same-origin. `changeOrigin:false`. NEVER add credentialed-wildcard CORS. The global-401 loop-break (Pattern 4: don't redirect when already on `/app/login`) is the second guard. **Verification:** log in under `npm run dev` and confirm a subsequent `/auth/me` carries the cookie (no loop, no `localStorage`). `[CITED: PITFALLS.md Pitfall 3]`
**Warning signs:** Login works but next API call 401s; `Set-Cookie` present but cookie absent on later requests; redirect loop `/app/login → /app → /app/login`; a PR adding CORS or `localStorage.setItem`.

### Pitfall 5: CSRF token not seeded before first login
**What goes wrong:** `POST /api/v2/auth/login` requires both a `csrf_token` in the JSON body AND a matching readable `telebot_csrf` cookie (server does `compare_digest`). On a *cold* first visit (no cookie yet), the login form has nothing to echo → login 403s.
**Why it happens:** The double-submit cookie is set on login *success* and by `GET /api/v2/auth/csrf` — but a first-time visitor hasn't called either yet. `[VERIFIED: codebase api/auth.py login() requires cookie+body match; csrf() seeds the cookie]`
**How to avoid:** The login view must `GET /api/v2/auth/csrf` on mount (it sets the readable cookie AND returns `{csrf_token}` in the body), then submit that token in the login body + `X-CSRF-Token` header. The fetch wrapper reads the cookie for the header; the login form reads the body token (or the cookie) for the body field. **Verification:** cold login from a cleared-cookie browser succeeds (no 403).
**Warning signs:** First login attempt 403s with `{"error":{"code":"forbidden","message":"CSRF token invalid"}}`; works only on the second attempt.

### Pitfall 6: nginx — no new location block needed, but `/api/v2/auth/login` rate-limit must exist
**What goes wrong:** Under D-02 uvicorn serves `/app` so the existing nginx `location /` proxy already reaches it — **no `/app/` location block is needed**. But the Phase 8 contract requires the `limit_req zone=telebot_login` block to cover `/api/v2/auth/login` (Phase 8 D-14). If a deploy adds a naive SPA `try_files /index.html` catch-all, it would swallow `/api/`, `/stream`, legacy HTMX routes mid-parallel-run.
**Why it happens:** SPA hosting guides universally recommend a root `try_files` catch-all — wrong during page-by-page parallel-run.
**How to avoid:** Do NOT add a root catch-all. The only nginx change Phase 9/deploy needs is the `location = /api/v2/auth/login` rate-limit block (may already be in place from Phase 8 — verify). Everything else stays proxied to uvicorn. `[CITED: PITFALLS.md Pitfall 5; ARCHITECTURE.md §3; Phase 8 D-14]`
**Warning signs:** A still-HTMX page renders the SPA shell or blank; `/api/*` returns HTML; the login endpoint isn't rate-limited.

## Runtime State Inventory

> This is a greenfield scaffold (new `frontend/` dir + new `static/app/` build output + one additive `app.mount` line). It is NOT a rename/refactor/migration. No existing runtime state is renamed or re-keyed.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — verified: Phase 9 adds no DB tables, keys, or collections; it consumes the existing Phase 8 read endpoints. | None |
| Live service config | None new — the only nginx touch is the Phase 8 `/api/v2/auth/login` rate-limit block (verify present, not new to Phase 9). | Verify Phase 8's nginx rate-limit block is deployed; no `/app/` block needed (D-02). |
| OS-registered state | None — verified: no new systemd/cron/task-scheduler registrations; SPA runs inside the existing telebot container. | None |
| Secrets/env vars | None — verified: NO `VITE_*` env vars (relative URLs only, per Pitfall 3 / locked decision). No secret may be baked into the bundle. | None — enforce "no `VITE_*` secrets" as a build-time check (grep `dist/` for sensitive strings). |
| Build artifacts | NEW `static/app/` directory (Vite `dist/` output) baked into the runtime image; new `node:22-slim AS spa-build` Dockerfile stage. The legacy `css-build` Tailwind-CLI stage coexists (removed Phase 12). | Add Node build stage + `COPY --from=spa-build /spa/dist/ ./static/app/`; ensure `.dockerignore`/build context includes `frontend/`. |

## Code Examples

### The lightest Phase-8 read endpoint for the D-08 probe — `GET /api/v2/trading-status`
```python
# Source: codebase api/meta.py:43-48 (READ-ONLY, NO DB or MT5 round-trip)
@router.get("/trading-status", response_model=TradingStatus)
async def trading_status(_user: str = Depends(require_user)) -> TradingStatus:
    executor = require_executor()
    paused = getattr(executor, "_trading_paused", False)
    return TradingStatus(paused=paused, status="paused" if paused else "running")
# Response schema (api/schemas.py): { "paused": bool, "status": "running"|"paused" }
```
**Recommendation:** Use `GET /api/v2/trading-status` for the probe (D-08). It is the **lightest** shipped read — it only reads an in-memory executor flag (no DB query, no MT5 bridge call), so polling it every 3s for the SC#5 proof is zero-cost and can't fail on data availability. Alternatives (`/overview`, `/positions`) hit DB + MT5 and are heavier/flakier for a pure "does polling work" proof.

### Auth contract the SPA consumes (read directly from Phase 8 `api/auth.py`)
```
GET  /api/v2/auth/csrf   → 200 { "csrf_token": "<t>" } + Set-Cookie telebot_csrf=<t> (httponly=false, SameSite=Lax, path=/)
GET  /api/v2/auth/me     → 200 { "user": "admin" }  │  401 { "error": {"code":"unauthorized","message":"Session expired"} }
POST /api/v2/auth/login  → body { "password": "...", "csrf_token": "<echo of telebot_csrf cookie>" }
                           200 { "user": "admin" } + Set-Cookie telebot_session (httpOnly) + refreshed telebot_csrf
                           401 { "error": {"code":"unauthorized","message":"invalid_credentials"} }
                           403 { "error": {"code":"forbidden","message":"CSRF token invalid"} }   ← cold-start (Pitfall 5)
                           429 { "error": {"code":"rate_limited","message":"rate_limited"} }
POST /api/v2/auth/logout → requires X-CSRF-Token header; 200 { "ok": true }
```
> The error envelope on failures is `{"error":{"code","message","fields?}}` (Phase 8 `api/errors.py`); success bodies are bare. The fetch wrapper's `HttpError.body` will carry this envelope.

### Dockerfile Node build stage (additive — D-03)
```dockerfile
# Source: ARCHITECTURE.md §5 + existing Dockerfile (python:3.12-slim runtime, api/ + static/ copied)
# ── Stage A: SPA build (NEW) ──────────────────────────────
FROM node:22-slim AS spa-build
WORKDIR /spa
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build                 # vite build → /spa/dist (base:"/app/")

# ── Stage 1: existing css-build (UNCHANGED, coexists until Phase 12) ──
# ── Stage 2: runtime (MODIFIED — add ONE copy line) ──────
FROM python:3.12-slim
# … existing: COPY *.py *.json, api/, templates/, static/, scripts/, css overlay …
COPY --from=spa-build /spa/dist/ ./static/app/      # NEW: SPA bundle → served at /app
# … existing CMD ["python", "-u", "bot.py"] …
```

### The single additive line in `dashboard.py` (D-02)
```python
# Add AFTER app.include_router(api_router) (line ~219) and the existing
# app.mount("/static", ...) (line ~234), so /api/v2 routes are registered FIRST.
app.mount("/app", StaticFiles(directory=str(BASE_DIR / "static" / "app"), html=True), name="spa")
# ⚠ html=True serves index.html at /app/ ONLY — add the deep-link fallback (Pitfall 1)
#   so /app/login, /app/<route> reloads return the shell, not 404.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Tailwind v3 `tailwind.config.js` + `@tailwind` directives + postcss/autoprefixer | Tailwind v4 `@tailwindcss/vite` + `@import "tailwindcss"` + `@theme` tokens in CSS | Tailwind v4 (2025) | No config file; tokens in CSS; shadcn defaults to v4. |
| shadcn HSL CSS-var tokens | shadcn **oklch** tokens in `:root`/`.dark` + `@theme inline` mapping | shadcn v4 era | Project may keep hex or convert to oklch; v4 accepts any CSS color. |
| `@vitejs/plugin-react` (Babel) | plugin-react v6 (Oxc-based, Babel-free) | Vite 8 / plugin-react 6 | Smaller install, faster Fast Refresh. |
| React `forwardRef` in shadcn primitives | `ref` as a prop (React 19) | React 19 | Current shadcn components have no `forwardRef`; old snippets need the codemod — don't paste them. |
| HTMX 3s full-DOM refresh (clobbers inputs) | TanStack Query cache + local form state split | This rewrite (v1.2) | The structural fix SC#5 proves. |

**Deprecated/outdated:**
- shadcn `toast`/`useToast` → replaced by **sonner** (current default).
- Vite 7 and earlier → unsupported upstream; Vite 8 only.
- Monolithic `radix-ui` umbrella → granular `@radix-ui/react-*` per component via `shadcn add`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Dev container host port is `8090` for the Vite proxy target | Pattern 1, Pitfall 4 | LOW — verified `DASHBOARD_HOST_PORT:-8090` default in `docker-compose.dev.yml`; if the operator overrides it, the proxy target must match. Planner should make the port a documented config point, not a magic constant. |
| A2 | `GET /api/v2/trading-status` is the lightest probe endpoint and is unauthenticated-safe behind `require_user` | Code Examples, D-08 | LOW — verified in `api/meta.py`; it reads only an in-memory flag. If the executor flag attr name changes it would break, but it's read defensively (`getattr(..., False)`). |
| A3 | slopcheck-level legitimacy is satisfied by official-doc prescription (slopcheck tool was unavailable) | Package Legitimacy Audit | LOW — every package is named by official shadcn docs or locked REQUIREMENTS; none are search-discovered. Residual risk is transitive-dependency supply chain, mitigable by an optional lockfile checkpoint. |
| A4 | The nginx `/api/v2/auth/login` rate-limit block is already deployed from Phase 8 | Pitfall 6, Runtime State | MEDIUM — Phase 8 D-14 specified it but it's an nginx (deploy) artifact, not app code; the planner should add a verify-step (don't assume deployed). |

## Open Questions (RESOLVED)

1. **Deep-link fallback implementation shape (subclass vs route)** — **RESOLVED: `StaticFiles` subclass** (overriding `get_response` to fall back to `index.html` on 404), selected in plan 09-02 Task 2 with a Wave-0 deep-link serving test.
   - What we know: `html=True` 404s on deep-links; both a custom `StaticFiles` subclass and a `@app.get("/app/{path:path}")` route work.
   - What's unclear: which interacts most cleanly with the existing mount + `/api/v2` precedence in *this* app.
   - Recommendation: Prefer the `StaticFiles` subclass (overriding `get_response` to fall back to `index.html` on 404) — it's self-contained within the `/app` mount and can't accidentally shadow API routes. Plan a browser hard-reload verification either way.

2. **Exact palette hex → semantic role assignment (Claude's discretion per D-10)** — **RESOLVED: oklch role map specified in plan 09-01's `<interfaces>` block** (`#0f0f1a → background`, `#1a1a2e → card/popover`, `#252542 → muted/border`, derived `--foreground`/`--primary`/`--destructive`).
   - What we know: three palette values + the full shadcn role set; shadcn defaults oklch.
   - What's unclear: which value maps to `--primary`/`--ring`/`--destructive` and what derived shades (foreground, accent, border) are needed for contrast.
   - Recommendation: planner assigns `#0f0f1a → background`, `#1a1a2e → card/popover`, `#252542 → muted/border`, derives `--foreground` for WCAG contrast, picks an accent for `--primary`, and a red for `--destructive` (ready for Phase 11). Verify a rendered Card/Input/Button before building the shell.

## Environment Availability

> External tooling for the build. The runtime needs none beyond the existing Python image.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js (build-time only) | `npm create vite`, `npm ci`, `vite build` (local dev + Docker `spa-build` stage) | Build-stage `node:22-slim` (Docker); local dev needs Node ≥20 | node:22-slim in image | None needed — only the Docker build stage requires it; prod runtime has no Node (the whole point). |
| npm | Install + build | ships with Node | — | pnpm works identically (shadcn docs use `pnpm dlx`); use whatever the operator runs. |
| Docker / BuildKit | Multi-stage image build (`TARGETARCH` used by existing css-build stage) | Existing build pipeline | — | None — already in use. |
| uvicorn (runtime) | Serving `/app` StaticFiles | Already running (`dashboard.app` in the telebot process) | existing | None — additive mount only. |

**Missing dependencies with no fallback:** none for the runtime. **Build-time:** local Node for `npm run dev`/`build` — present on the operator's dev machine (the SPA is built in CI/Docker for prod; local Node is only for HMR dev). The planner should not assume a specific local Node version beyond ≥20 (Vite 8 requirement).

## Validation Architecture

> `workflow.nyquist_validation: true` in config — included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Backend: `pytest` (existing; `tests/test_api_csrf.py` etc.). Frontend: **none yet** — Phase 9 is a scaffold; heavy unit testing is not the SC focus. The SC#5 proof is a **browser/manual** check by design (D-08). |
| Config file | `pytest` (existing repo config); no frontend test runner in scope for Phase 9. |
| Quick run command | Backend mount/serving: `pytest tests/ -k "static or app_mount or spa" -x` (Wave 0 — tests don't exist yet). |
| Full suite command | `pytest tests/ -x` (must stay green — bot core + Phase 8 API untouched). |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SPA-01 | Built `dist/` served at `/app/` by uvicorn; deep-link `/app/login` returns index.html (not 404) | integration | `pytest tests/test_spa_serving.py::test_app_deeplink_returns_index -x` | ❌ Wave 0 |
| SPA-01 | No Node in runtime image | smoke/manual | `docker run … which node` returns nonzero, OR inspect final stage has no node | ❌ Wave 0 (manual/CI) |
| SPA-02 | No `tailwind.config.js` in `frontend/`; build succeeds on Tailwind v4 | build/smoke | `test ! -f frontend/tailwind.config.js && (cd frontend && npm run build)` | ❌ Wave 0 |
| SPA-02 | shadcn Card/Input/Button render opaque dark tokens | manual (browser) | Visual check — render the components, confirm opaque + correct palette | manual |
| SPA-03 | Cold login through SPA succeeds; `localStorage` empty of auth tokens | manual (browser devtools) | Log in, then `Object.keys(localStorage)` empty of session/token | manual |
| SPA-03 | Login sends `X-CSRF-Token` + `credentials:same-origin`; gets `telebot_session` | integration (optional) | A backend test asserting login flow works with the contract (already covered by Phase 8 `tests/test_api_csrf.py` server-side) | ✅ (server side) |
| SPA-04 | Expired session → single redirect to `/app/login`, no loop | manual (browser) | Clear session cookie, trigger an authed query, confirm one redirect | manual |
| SPA-05 | Polling probe runs ≥2 refetch cycles without clobbering an open input | manual (browser) — **the headline SC** | Type in the probe input, watch ≥2 refetch ticks, confirm text intact | manual |

### Sampling Rate
- **Per task commit:** `cd frontend && npm run build` (catches Vite/Tailwind/TS breakage fast) + `pytest tests/ -k spa -x` once Wave-0 tests exist.
- **Per wave merge:** `pytest tests/ -x` (full backend suite green — bot core + Phase 8 untouched) + `cd frontend && npm run build`.
- **Phase gate:** All five SC manually verified in a browser (login, no-localStorage, single-401-redirect, deep-link-reload, ≥2-cycle probe), full backend suite green, before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_spa_serving.py` — asserts `/app/` and a deep-link `/app/login` both return the SPA `index.html` (200, HTML), and `/api/v2/trading-status` still returns JSON (mount didn't shadow the API) — covers SPA-01 + Pitfall 1.
- [ ] No frontend test runner is required for Phase 9 (the SC are browser-verifiable by design). If the planner wants a smoke test, a single Vitest "renders `<App/>` without crashing" is optional, not load-bearing.
- [ ] Build-as-test: `cd frontend && npm run build` is the de-facto type+compile gate (TS 6 strict catches API-shape drift).

*(SC#3/#4/#5 are inherently browser/manual proofs per D-08 — the plan must include explicit manual verification steps, not just automated tests. The Phase-8 server-side auth/CSRF behavior is already covered by `tests/test_api_csrf.py`.)*

## Security Domain

> `security_enforcement` not explicitly `false` in config → included.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (consumer) | Phase 8 owns argon2 verify + rate-limit; Phase 9 consumes `/auth/login` and must NOT weaken it (no token storage). |
| V3 Session Management | yes | httpOnly `telebot_session` retained; SPA never reads it; `credentials:"same-origin"`. No `localStorage`/JWT (locked decision, SPA-03). |
| V4 Access Control | yes | Boot guard (`/auth/me`) + global 401 redirect gate the shell; every API call carries the session cookie. |
| V5 Input Validation | minimal (Phase 9) | Only the login password field + the throwaway probe input. Real form validation (zod) = Phase 11. |
| V6 Cryptography | no (Phase 9) | CSRF token generation + argon2 are server-side (Phase 8). SPA only echoes a token — no client crypto. |
| V13 API/Web Service | yes | CSRF double-submit on mutations (`X-CSRF-Token`); error envelope leaks no traceback (Phase 8 `api/errors.py`). |

### Known Threat Patterns for React-SPA-over-cookie-auth
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Auth token theft via XSS | Spoofing / Info Disclosure | httpOnly session cookie — never readable by JS; **nothing in `localStorage`** (SPA-03, locked). |
| CSRF on state-changing requests | Tampering | SameSite=Lax (backbone) + double-submit `telebot_csrf`→`X-CSRF-Token` (Phase 8 D-15); cross-site can't set the custom header. |
| Cross-origin cookie leak in dev | Info Disclosure | Same-origin Vite dev proxy (Pitfall 4); never credentialed-wildcard CORS; never weaken cookie attrs. |
| Secret baked into JS bundle | Info Disclosure | No `VITE_*` secrets; relative URLs only; grep `dist/` for sensitive strings (Pitfall 3 / Runtime State). |
| nginx catch-all exposing/swallowing routes | Tampering / DoS | No root `try_files` catch-all during parallel-run; only the `/app/*` mount + `/api/v2/auth/login` rate-limit (Pitfall 6). |
| 401 redirect loop (availability) | DoS (self-inflicted) | Loop-break in `onAuthError` (don't redirect when already on `/app/login`); hard-nav clears in-memory state (SPA-04). |

## Sources

### Primary (HIGH confidence)
- **Codebase (read directly):** `api/auth.py` (auth contract, CSRF cookie semantics, error codes), `api/meta.py` (`/trading-status` probe endpoint + `OverviewMeta`/`TradingStatus` schemas), `api/errors.py` (error envelope shape), `api/schemas.py` (`LoginIn`, `TradingStatus`), `dashboard.py` (app creation L212, `include_router` L219, `app.mount("/static")` L234, `BASE_DIR` L45), `Dockerfile` (python:3.12-slim runtime, css-build stage, copy layout), `docker-compose.dev.yml` (dev host port 8090).
- **npm registry (live, 2026-06-04):** verified `latest` for vite 8.0.16, @vitejs/plugin-react 6.0.2, react/react-dom 19.2.7, tailwindcss + @tailwindcss/vite 4.3.0, shadcn 4.10.0, @tanstack/react-query 5.101.0, react-router-dom 7.17.0, typescript 6.0.3, sonner 2.0.7, lucide-react 1.17.0, cva 0.7.1, clsx 2.1.1, tailwind-merge 3.6.0.
- `.planning/research/ARCHITECTURE.md` §2 (auth/CSRF/401), §3 (same-origin nginx, StaticFiles option b), §4 (TanStack polling), §5 (Vite Dockerfile stage, base, dev proxy) — primary design source.
- `.planning/research/STACK.md` (locked stack, version compat, install flow, dev proxy), `.planning/research/PITFALLS.md` (Pitfalls 3, 5, 9, 10), `.planning/phases/08-json-api-foundation/08-CONTEXT.md` (consumed contract: D-05 dual-value, D-06/07 ISO+UTC, D-12 auth, D-15 CSRF).
- https://ui.shadcn.com/docs/installation/vite — current canonical Vite + Tailwind v4 + shadcn init flow (verified 2026-06-04).
- https://ui.shadcn.com/docs/theming — Tailwind v4 `:root`/`.dark`/`@theme inline` oklch token structure (verified 2026-06-04).
- https://fastapi.tiangolo.com/tutorial/static-files/ + https://github.com/fastapi/fastapi/discussions/10458 — `StaticFiles(html=True)` deep-link 404 behavior; subpath mount avoids API-route interference.

### Secondary (MEDIUM confidence)
- TanStack Query polling guide (refetchInterval semantics, pause-on-blur) — cross-referenced via ARCHITECTURE.md's verified citation.

### Tertiary (LOW confidence)
- None load-bearing — all critical claims grounded in codebase or official docs.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every version verified live against npm registry 2026-06-04; majors locked; shadcn flow verified against official docs.
- Architecture: HIGH — auth contract, probe endpoint, mount point, and error envelope read directly from the shipped Phase 8 codebase.
- Pitfalls: HIGH — `html=True` deep-link 404 verified against FastAPI docs + discussion; Vite `base`/dev-proxy/CSRF-cold-start grounded in codebase + v1.2 PITFALLS.md.

**Research date:** 2026-06-04
**Valid until:** 2026-07-04 (stable locked majors; re-verify minor/patch versions if scaffolding slips >30 days, as React/Vite/TanStack ship frequent patches).

## RESEARCH COMPLETE

**Phase:** 9 - SPA Scaffold + Auth + Design System
**Confidence:** HIGH

### Key Findings
- **THE critical pitfall:** `StaticFiles(html=True)` at `/app` 404s on client-route deep-links (`/app/login` on F5) — it is NOT a SPA catch-all. The plan MUST add an explicit `index.html` fallback (recommend a `StaticFiles` subclass overriding `get_response`) or SC#1 silently ships broken. Subpath mount (D-01) safely avoids any `/api/v2` interference.
- **Probe endpoint resolved:** `GET /api/v2/trading-status` is the lightest shipped read (in-memory executor flag, no DB/MT5) — ideal for the D-08 SC#5 polling proof.
- **Auth handshake gotcha:** cold first-visit login needs `GET /api/v2/auth/csrf` on the login view's mount to seed the readable `telebot_csrf` cookie before `POST /auth/login {password, csrf_token}` — otherwise the first login 403s.
- **Stack fully version-verified (npm 2026-06-04):** all locked majors current; two minor bumps since the STACK doc — TanStack Query 5.100.14→5.101.0, react-router-dom 7.16.0→7.17.0. shadcn+Tailwind-v4+Vite init flow confirmed canonical.
- **Backend footprint is tiny:** one additive `app.mount("/app", StaticFiles(...))` line + a Node `spa-build` Dockerfile stage. No bot-core or API change. nginx needs no `/app/` block (uvicorn serves it); only verify the Phase 8 `/api/v2/auth/login` rate-limit is deployed.

### File Created
`.planning/phases/09-spa-scaffold-auth-design-system/09-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Standard Stack | HIGH | All versions verified live vs npm registry; shadcn flow vs official docs. |
| Architecture | HIGH | Auth contract, probe endpoint, mount point, error envelope read from the shipped codebase. |
| Pitfalls | HIGH | `html=True` deep-link 404 verified vs FastAPI docs + discussion; rest grounded in codebase + v1.2 PITFALLS.md. |

### Open Questions (RESOLVED)
1. Deep-link fallback shape (StaticFiles subclass vs catch-all route) — RESOLVED: StaticFiles subclass selected in plan 09-02 Task 2 (Wave-0 deep-link serving test).
2. Exact palette hex→semantic-role assignment (D-10 discretion) — RESOLVED: oklch role map specified in plan 09-01's `<interfaces>` block; verify a rendered Card/Input/Button.

### Ready for Planning
Research complete. Planner can now create PLAN.md files for SPA-01..SPA-05.
