# Stack Research

**Domain:** Internal single-operator live-trading dashboard — React 19 + Vite SPA over a same-origin FastAPI JSON API
**Researched:** 2026-06-01
**Confidence:** HIGH (all versions verified live against the npm registry; shadcn ↔ Tailwind v4 compatibility verified against official shadcn docs)

> Supersedes the 2026-04-18 v1.1 STACK research (Basecoat/HTMX UI substrate), which is obsolete now that the dashboard is being rewritten as a React/Vite SPA.
>
> Scope note: The locked stack (React 19 · Vite · shadcn/ui · Tailwind CSS) is **final and not re-litigated** here. This document pins exact current versions, resolves the shadcn ↔ Tailwind v4 question, fills the unspecified slots (routing, server-state, forms, toast, charting), and specifies the nginx-static-serving + dev-proxy cookie-auth integration. Backend deps (FastAPI, asyncpg, Telethon, argon2, itsdangerous) are unchanged — see `requirements.txt`.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| react / react-dom | `19.2.7` | UI runtime | Locked. Latest stable React 19.x. Client-side state model eliminates the HTMX refresh-race bug class that motivated the rewrite. |
| vite | `8.0.16` | Build tool + dev server | **Vite 8 is the current stable line** (verified npm `latest`). Vite 7 and earlier are no longer supported upstream — pin to 8. Produces a static `dist/` (no Node runtime in prod — satisfies the minimize-deps constraint). |
| @vitejs/plugin-react | `6.0.2` | React Fast Refresh + JSX transform | v6 pairs with Vite 8; uses Oxc for the Refresh transform (Babel dropped → smaller install, faster). Standard plugin for non-RSC React SPAs. |
| typescript | `6.0.3` | Type safety | Operator fluent in React; TS catches API-shape drift between the FastAPI JSON layer and the SPA at compile time. Strongly recommended given the live-money surface. |
| tailwindcss | `4.3.0` | Styling | Locked. **Use v4** (see Version Compatibility — shadcn now defaults to v4 and this is the non-negotiable alignment point). Backend already vendors Tailwind v4.2.2 CLI; the SPA uses the Vite plugin instead of the standalone CLI. |
| @tailwindcss/vite | `4.3.0` | Tailwind v4 Vite integration | The v4 way to wire Tailwind into Vite. Replaces the v3 `postcss` + `tailwind.config.js` + `autoprefixer` chain entirely. No `postcss.config.js`, no `autoprefixer` needed. |
| shadcn (CLI) | `4.10.0` | Component scaffolding (not a runtime dep) | Locked. Copies component source into `src/components/ui/` — you own the code, nothing to version-bump as a dependency. CLI init targets Tailwind v4 + React 19 by default now. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| @tanstack/react-query | `5.100.14` | Server-state / data-fetching / live polling | **The data layer for the whole app.** Positions/prices poll via `refetchInterval`. Replaces the HTMX 3s-refresh model that clobbered inputs — Query caches server state separately from form/UI state, so a background refetch never touches an open SL/TP input. Peer-supports React 19. |
| react-router-dom | `7.16.0` | Client-side routing | 9 views (overview, positions, history, signals, staged, settings, analytics, login, root-redirect). Use **declarative / library mode** (`createBrowserRouter` + `<RouterProvider>`), NOT framework/SSR mode — we are a static SPA. Mature, lowest cognitive overhead. |
| react-hook-form | `7.77.0` | Form state + validation wiring | Settings page (folds SEED-001) and all mutation forms (modify SL/TP, partial close). Uncontrolled-input model means a background poll cannot re-render and clobber a field — directly addresses the bug class that killed HTMX. |
| zod | `4.4.3` | Schema validation | Validate settings inputs (recommended ranges + footgun warnings from SEED-001) and optionally parse API responses to catch JSON-shape drift. |
| @hookform/resolvers | `5.4.0` | Bridge zod ↔ react-hook-form | Single line: `resolver: zodResolver(schema)`. Required to use zod schemas as RHF validators. resolvers 5.x supports zod 4. |
| sonner | `2.0.7` | Toast notifications | shadcn's official toast primitive (the old `toast`/`useToast` component is deprecated in favor of sonner). Drives the settings save/error toasts in the SEED-001 UX. |
| recharts | `3.8.1` | Charting (analytics page only) | React 19 supported (peer dep `^19.0.0` verified). shadcn's `Chart` component is a thin themeable wrapper over recharts, so it drops straight into the design system. Analytics is the read-only pilot page — low risk, ideal first cutover. |
| lucide-react | `1.17.0` | Icons | shadcn's default icon set. Now post-1.0 (verified `latest = 1.17.0`). Tree-shaken per-icon imports. |
| class-variance-authority | `0.7.1` | Variant styling for shadcn components | Installed automatically by shadcn init; powers component `variant`/`size` props. |
| clsx | `2.1.1` | Conditional className join | Part of the shadcn `cn()` helper. |
| tailwind-merge | `3.6.0` | Dedup conflicting Tailwind classes | Other half of `cn()` — lets component consumers override classes safely. |
| @radix-ui/react-slot | `1.2.4` | `asChild` polymorphism | Pulled in by shadcn primitives. Individual `@radix-ui/react-*` packages are added on-demand by `shadcn add` per component — do NOT install the deprecated monolithic `radix-ui` umbrella; let the CLI add the granular ones you actually use. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Vite dev server | Local dev with HMR | Configure `server.proxy` to forward `/api` (and login/logout routes) to FastAPI so the **httpOnly session cookie survives** — see Dev-Time Setup below. |
| @types/node | Types for `path.resolve` in vite.config | Required by the shadcn Vite guide for the `@/*` alias setup. |
| ESLint + typescript-eslint | Lint | Vite React-TS template ships a baseline config; keep it minimal (minimize-deps ethos). Optional. |
| pnpm or npm | Package manager | shadcn docs use `pnpm dlx`; npm/`npx` works identically. Use whatever the operator already runs. |

## Installation

```bash
# 1. Scaffold (React + TS + Vite 8)
npm create vite@latest dashboard -- --template react-ts
cd dashboard

# 2. Tailwind v4 (Vite plugin — NOT the standalone CLI the backend uses)
npm install tailwindcss@4 @tailwindcss/vite@4
npm install -D @types/node

# 3. shadcn init (targets Tailwind v4 + React 19 by default; writes components.json,
#    installs cva / clsx / tailwind-merge / lucide-react)
npx shadcn@latest init

# 4. Data + routing
npm install @tanstack/react-query@5 react-router-dom@7

# 5. Forms + validation
npm install react-hook-form@7 zod@4 @hookform/resolvers@5

# 6. Toast (shadcn add wires the component file; sonner is the runtime dep)
npx shadcn@latest add sonner

# 7. Charting (analytics page only — defer until that wave)
npm install recharts@3
npx shadcn@latest add chart

# shadcn primitives are added per-component as pages are built, e.g.:
npx shadcn@latest add button card dialog input form table tabs tooltip badge
```

`vite.config.ts` (Tailwind v4 + `@/` alias + dev proxy):

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    proxy: {
      // Forward API + auth to FastAPI so the httpOnly session cookie works in dev
      "/api": { target: "http://localhost:8000", changeOrigin: false },
      "/login": { target: "http://localhost:8000", changeOrigin: false },
      "/logout": { target: "http://localhost:8000", changeOrigin: false },
    },
  },
});
```

`src/index.css` (v4 — replaces the entire v3 `@tailwind base/components/utilities` chain):

```css
@import "tailwindcss";

/* Map the existing v1.0 dark palette as v4 @theme tokens (no tailwind.config.js in v4) */
@theme {
  --color-dark-700: #252542;
  --color-dark-800: #1a1a2e;
  --color-dark-900: #0f0f1a;
}
```

## Production Serving — Vite static build behind nginx (same origin)

Goal: zero Node runtime in prod; static `dist/` served by nginx on the **same origin** as FastAPI so the httpOnly session cookie and CSRF double-submit cookie work without CORS.

1. `vite build` → emits `dist/` (hashed JS/CSS + `index.html`). Bake this into the Docker image (multi-stage: a Node stage builds, then copy `dist/` into the nginx/app image; the final runtime image has **no Node**).
2. nginx serves the SPA and proxies API calls on one host:

```nginx
# API + auth → FastAPI (cookie stays first-party, same origin)
location /api/   { proxy_pass http://telebot:8000; proxy_set_header Host $host; }
location /login  { proxy_pass http://telebot:8000; }
location /logout { proxy_pass http://telebot:8000; }

# Static SPA assets (long-cache the hashed files)
location /assets/ { root /usr/share/nginx/html; expires 1y; add_header Cache-Control "immutable"; }

# SPA fallback — every other path returns index.html so client routing works on reload
location / {
  root /usr/share/nginx/html;
  try_files $uri $uri/ /index.html;
}
```

3. **Parallel-run cutover** (per PROJECT.md): keep the existing HTMX dashboard reachable (e.g. under a path prefix or the legacy `location` blocks) and route page-by-page to the SPA fallback as each React view is verified against the MT5 demo. Because both are same-origin behind one nginx, the session cookie is shared between old and new pages during the transition.

Because the cookie is `httpOnly` and same-origin, the SPA **cannot and should not read it** — `fetch`/Query just send it automatically (same-origin requests include cookies by default). For mutations, read the CSRF token from the non-httpOnly double-submit cookie in JS and echo it in a request header (preserve the existing v1.0 scheme).

## Dev-Time Setup — keeping auth cookies working

- Run FastAPI on `:8000`, Vite dev on `:5173`.
- Vite `server.proxy` (above) forwards `/api`, `/login`, `/logout` to FastAPI. Because the browser only ever talks to the Vite origin (`localhost:5173`), the session cookie is **first-party to the Vite origin** — no `SameSite`/CORS headaches, mirrors the prod same-origin model.
- Set `changeOrigin: false` so the `Host` header (and thus cookie domain) is preserved.
- In app code, use relative URLs (`fetch("/api/positions")`), never absolute `http://localhost:8000/...` — that would make the cookie cross-origin and break it. Relative URLs work identically in dev (through the proxy) and prod (through nginx).
- TanStack Query `queryFn`s should use the same relative paths; no base-URL config needed.

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| react-router-dom 7 (declarative mode) | TanStack Router 1.170.x | TanStack Router has best-in-class type-safe routing + search-param validation. Choose it if you want compile-time-checked routes and are already deep in the TanStack ecosystem. For 9 flat views with a fluent-in-React solo operator, react-router is the lower-overhead, more-documented pick. Either works; react-router minimizes new concepts. |
| TanStack Query (server state only) | + Zustand/Redux for client state | Add a client-state lib ONLY if genuinely app-wide *client* state emerges (it likely won't). Query covers all server state; React local state / context covers the rest. Do not pre-emptively add one. |
| recharts 3 | shadcn chart wrapper alone / visx / nivo | recharts IS what shadcn's `Chart` wraps — use them together. visx/nivo only if you outgrow recharts' chart types (unlikely for win-rate / profit-factor analytics). |
| sonner | Old shadcn `toast` (`useToast`) | None — the legacy toast is deprecated; sonner is the current default. |
| Vite SPA | Next.js / Remix (SSR) | Already decided against (PROJECT.md): SSR/SEO irrelevant for an internal tool and would add a Node prod runtime. Do not reopen. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Next.js / Remix / any SSR framework | Adds a Node runtime in prod, violating the minimize-deps constraint; SSR/SEO worthless for an internal single-operator tool | Vite SPA → static `dist/` behind nginx |
| A Node process in production | Same — the whole point of choosing Vite over Next was to ship static files only | nginx serving prebuilt `dist/` |
| Redux / Zustand / Jotai / MobX (state lib) | TanStack Query owns server state; there is no meaningful global *client* state in a polling dashboard. Adding one is dead weight + a footgun (re-introduces the manual-cache-sync bug class Query exists to remove) | TanStack Query + React local state / Context |
| Tailwind CSS **v3** in the SPA | shadcn now defaults to v4; the backend already vendors v4; mixing v3 config (`tailwind.config.js`, `@tailwind` directives) with v4 components causes broken styling and OKLCH/HSL color mismatches | Tailwind v4 via `@tailwindcss/vite` + `@theme` tokens in CSS |
| `postcss.config.js` + `autoprefixer` | The v3 build chain. Tailwind v4's Vite plugin handles this internally | `@tailwindcss/vite` plugin only |
| The standalone Tailwind CLI (the backend's approach) | Right for the HTMX/Jinja side; wrong for a Vite SPA — bypasses HMR and the v4 plugin | `@tailwindcss/vite` |
| Monolithic `radix-ui` umbrella package | Pulls in primitives you don't use; shadcn adds granular `@radix-ui/react-*` per component | Let `shadcn add` install the specific primitives |
| `localStorage` / JWT tokens for auth | Decided against (PROJECT.md): XSS-exfiltration risk + CORS/cookie complexity | Keep httpOnly session cookie, same-origin, CSRF double-submit |
| Axios | Extra dependency; native `fetch` + TanStack Query covers everything for same-origin relative calls | `fetch` inside Query `queryFn`s |
| Vite 7 or earlier | No longer supported upstream | Vite 8 |

## Stack Patterns by Variant

**For the live-money mutation views (positions: close / modify SL-TP / partial close):**
- Forms via react-hook-form (uncontrolled inputs) so background polls never clobber an open field — the exact failure mode that killed HTMX.
- Mutations via TanStack Query `useMutation` with explicit `onSuccess` invalidation of the positions query (don't optimistically update live-money state — confirm against server, then refetch).
- Send the CSRF token header on every mutation; surface failures via sonner.

**For the analytics page (read-only pilot):**
- Pure `useQuery` + recharts via the shadcn chart wrapper. No mutations, no CSRF, no live-money risk → correct first page to cut over.

**For polling cadence:**
- `refetchInterval: 3000` (matching the old HTMX cadence) on positions/prices; rely on Query's default pause-on-tab-blur. Crucially, polling now lives in the cache layer, decoupled from form/render state.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| shadcn CLI `4.10.0` | tailwindcss `4.x` + react `19.x` | **CRITICAL ALIGNMENT:** shadcn init now defaults to Tailwind **v4** and React 19. Components ship with `data-slot` attributes, OKLCH colors, no `forwardRef`. Using Tailwind v3 here = broken styling. v3 is only "still works" for *existing* v3 apps — a fresh SPA must be v4. This aligns with the backend's vendored Tailwind v4.2.2 (same major). |
| tailwindcss `4.3.0` | @tailwindcss/vite `4.3.0` | Keep these two on the same major/minor. v4 has NO `tailwind.config.js` — tokens go in CSS via `@theme`. |
| vite `8.0.16` | @vitejs/plugin-react `6.0.2` | plugin-react v6 is the Vite 8 pairing (Oxc-based, Babel-free). |
| @tanstack/react-query `5.100.14` | react `^18 \|\| ^19` | React 19 verified in peer deps. |
| react-router-dom `7.16.0` | react `>=18` | Use declarative/library mode (`createBrowserRouter`), not framework/SSR mode. |
| recharts `3.8.1` | react `^19.0.0` (peer) | React 19 explicitly in peer deps; pairs with shadcn `chart` wrapper. |
| react-hook-form `7.77.0` + @hookform/resolvers `5.4.0` + zod `4.4.3` | each other | resolvers 5.x supports zod 4. Pin zod to 4.x (zod 4 has API changes vs 3). |
| sonner `2.0.7` | react `19.x` | Current shadcn default toast. |

## Sources

- npm registry (live, 2026-06-01) — exact `latest` versions for vite (8.0.16), @vitejs/plugin-react (6.0.2), react/react-dom (19.2.7), tailwindcss + @tailwindcss/vite (4.3.0), shadcn (4.10.0), @tanstack/react-query (5.100.14), react-router-dom (7.16.0), @tanstack/react-router (1.170.10), react-hook-form (7.77.0), zod (4.4.3), @hookform/resolvers (5.4.0), sonner (2.0.7), recharts (3.8.1), lucide-react (1.17.0), cva (0.7.1), clsx (2.1.1), tailwind-merge (3.6.0), @radix-ui/react-slot (1.2.4), typescript (6.0.3) — HIGH confidence (authoritative registry).
- npm peer-dependency queries — recharts / react-router / tanstack-query React 19 support — HIGH confidence.
- https://ui.shadcn.com/docs/tailwind-v4 — shadcn defaults to Tailwind v4; v3 backward-compatible only for existing apps — HIGH confidence.
- https://ui.shadcn.com/docs/installation/vite — exact Vite + Tailwind v4 setup (`@tailwindcss/vite`, `@import "tailwindcss"`, `@/*` alias, `@types/node`) — HIGH confidence.
- https://vite.dev/releases — Vite 8 is the current stable line; v7 and earlier unsupported — HIGH confidence.
- https://tanstack.com/query/latest/docs/framework/react/guides/polling — `refetchInterval` semantics, pause-on-blur default — HIGH confidence.
- Existing repo: `requirements.txt`, `tailwind.config.js`, `.planning/PROJECT.md` — backend deps, dark palette tokens, locked decisions.

---
*Stack research for: React 19 + Vite SPA over same-origin FastAPI JSON API (internal live-trading dashboard)*
*Researched: 2026-06-01*
