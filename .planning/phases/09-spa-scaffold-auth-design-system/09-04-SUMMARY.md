---
phase: 09-spa-scaffold-auth-design-system
plan: 04
subsystem: frontend-shell-router
tags: [react, react-router-dom, tanstack-query, app-shell, boot-guard, probe, sc5]
requires:
  - "09-01: frontend/ Vite+React+Tailwind+shadcn scaffold (ui components, index.css tokens, placeholder main.tsx)"
  - "09-03: http.ts api() wrapper, queryClient (global 401 onAuthError + polling defaults), LoginView"
provides:
  - "frontend/src/routes/router.tsx — createBrowserRouter basename /app: /login -> LoginView, / -> AppShell (index = ProbeView)"
  - "frontend/src/main.tsx — QueryClientProvider wraps RouterProvider + root sonner Toaster"
  - "frontend/src/App.tsx — boot guard GET /api/v2/auth/me (200 -> shell, 401 -> global redirect, single bounce)"
  - "frontend/src/components/shell/AppShell.tsx — 224px-sidebar layout + md:ml-56 main + mobile drawer + <Outlet/>"
  - "frontend/src/components/shell/Sidebar.tsx — Telebot wordmark + Overview live + 6 disabled-visible links + Sign out (logout POST)"
  - "frontend/src/routes/ProbeView.tsx — THROWAWAY SC#5 proof: useQuery(trading-status, refetchInterval 3000) structurally separate from useState input"
affects:
  - "Phase 10 replaces ProbeView with the first real page and enables the disabled-visible nav links in place"
  - "Every Phase 10/11 page slots into the AppShell <Outlet/> and inherits the server-state/form-state split convention"
tech-stack:
  added:
    - "react-router-dom@7.17.0 declarative mode (createBrowserRouter + RouterProvider) — installed in Plan 03, consumed here"
  patterns:
    - "Declarative client router with basename /app (in lockstep with Vite base + uvicorn StaticFiles mount)"
    - "Boot guard gates the shell on /auth/me; 401 redirect delegated to the single global onAuthError (no competing redirect)"
    - "Server state (useQuery refetchInterval) and form state (useState) structurally isolated — a refetch re-renders data, never resets the input"
    - "Disabled-visible future nav (muted-foreground, non-interactive, not hidden) so Phase 10 enables in place"
    - "Cyan --primary reserved for wordmark + active indicator + focus rings only"
key-files:
  created:
    - frontend/src/routes/router.tsx
    - frontend/src/components/shell/AppShell.tsx
    - frontend/src/components/shell/Sidebar.tsx
    - frontend/src/routes/ProbeView.tsx
  modified:
    - frontend/src/main.tsx
    - frontend/src/App.tsx
decisions:
  - "D-07: full app shell + 224px sidebar nav skeleton (disabled-visible future links) + /app/* declarative client router; main.tsx wires QueryClientProvider + RouterProvider (basename /app)"
  - "D-05: boot guard GET /api/v2/auth/me — 200 -> shell, 401 -> login delegated to the single global onAuthError (single bounce, SPA-04)"
  - "D-08: throwaway probe on a real Phase-8 read endpoint (trading-status), useQuery(refetchInterval 3000) vs useState input — proven ≥2 refetch cycles without clobbering the open input (SPA-05)"
metrics:
  duration: 12min
  tasks: 3
  files: 6
  completed: 2026-06-06
---

# Phase 9 Plan 04: App Shell + Router + Boot Guard + SC#5 Probe Summary

The complete Phase 9 shell: a declarative react-router-dom 7 `/app/*` router (basename `/app`) with a
QueryClient + Router provider root, an `/auth/me` boot guard that delegates its 401 redirect to the
single global handler (single bounce), the 224px Telebot-branded sidebar with the disabled-visible nav
skeleton, and the THROWAWAY polling probe that proves the headline structural fix — a real background
poll runs ≥2 refetch cycles without clobbering an open input. This is the convention every Phase 10/11
page slots into.

## What Was Built

### Task 1 — router.tsx + main.tsx providers + App.tsx boot guard (commit 524de41)
- `frontend/src/routes/router.tsx`: `createBrowserRouter([...], { basename: "/app" })` (declarative
  mode). Routes written WITHOUT the `/app` prefix (basename supplies it): `/login` -> `<LoginView/>`;
  `/` -> `<AppShell/>` with an index child rendering the Overview landing (`<ProbeView/>`). basename
  `/app` keeps the router in lockstep with the Vite base and the uvicorn StaticFiles mount (Pitfall 1/3).
- `frontend/src/main.tsx`: wraps `<RouterProvider router={router}/>` in
  `<QueryClientProvider client={queryClient}>` (both imported from Plan 03 + Task 1), and mounts the
  shadcn sonner `<Toaster/>` at the root for later toast use. This is the provider wiring Plan 01 left
  as a placeholder.
- `frontend/src/App.tsx`: the boot guard. On mount it resolves auth via `useQuery(["auth-me"], () =>
  api("/api/v2/auth/me"))`. On 200 it renders the protected shell/outlet; while resolving it renders a
  neutral loading state; on 401 it relies on the global `onAuthError` (Plan 03 queryClient) to hard-nav
  to `/app/login` — App.tsx adds NO second competing redirect (single bounce, SPA-04 / T-09-11).

### Task 2 — AppShell + Sidebar nav skeleton + throwaway ProbeView (commit feb17cb)
- `frontend/src/components/shell/Sidebar.tsx`: a fixed 224px (`w-56`) sidebar on `--sidebar`. Header:
  "Telebot" wordmark in `text-primary` (cyan) + "Trading Dashboard" subtitle in `muted-foreground`. Nav
  mirrors `templates/base.html` EXACT labels — "Overview" as the live/active route (cyan active
  indicator when current); "Positions", "Trade History", "Signal Log", "Analytics", "Pending Stages",
  "Settings" rendered DISABLED-VISIBLE (greyed `muted-foreground`, non-interactive, NOT hidden — D-07)
  so Phase 10 enables them in place. Footer "Sign out" -> `api("/api/v2/auth/logout", { method: "POST" })`
  (the http wrapper adds `X-CSRF-Token`), then hard-nav to `/app/login`. The cyan accent appears ONLY
  on the wordmark + active indicator + focus rings — disabled links never use it.
- `frontend/src/components/shell/AppShell.tsx`: layout = Sidebar + main content offset `md:ml-56`, with
  a top-bar mobile drawer toggle (sidebar hidden by default under `md`, toggled open). Renders an
  `<Outlet/>` for routed content; empty-content fallback copy "Select a section to get started."
- `frontend/src/routes/ProbeView.tsx` (THROWAWAY — commented as scaffold/diagnostic, removed in Phase
  10). Heading "Connection probe". `useQuery({ queryKey: ["trading-status"], queryFn: () =>
  api("/api/v2/trading-status"), refetchInterval: 3000 })` for SERVER state — renders `status` + a
  last-updated timestamp from `dataUpdatedAt` in `--font-mono`. Separately, `const [draft, setDraft] =
  useState("")` LOCAL form state bound to an open `<input>`. The proof: `draft` (useState) and `data`
  (useQuery) are structurally isolated — a background refetch re-renders the timestamp but never resets
  `draft`. The input value is NOT sourced from the query cache.

### Task 3 — Manual phase gate (human-verify checkpoint, gate="blocking") — APPROVED
The four browser-only success criteria (per VALIDATION.md §Manual-Only Verifications) were verified
LIVE in a browser against a dashboard-only backend (Vite dev proxy -> FastAPI). The human responded
**"approved"** with all five checks passing:

1. **SPA-03** (cold login + no localStorage): cleared cookies, visited `/app/login`, logged in — login
   succeeded with NO 403 on first attempt (cold-start CSRF seed worked); `telebot_session` confirmed
   httpOnly; `localStorage` held NO auth token.
2. **SPA-01** (deep-link reload): navigated to `/app/login` and pressed F5 — the SPA loaded (NOT a
   FastAPI 404 JSON), confirming the SpaStaticFiles deep-link fallback.
3. **SPA-04** (single 401 redirect): while logged in, deleted the `telebot_session` cookie and triggered
   an authed call — exactly ONE redirect to `/app/login`, no loop, no repeated bounces.
4. **SPA-05** (THE headline proof): typed text into the "Connection probe" input and kept it focused
   while the mono last-updated timestamp ticked at least TWICE (≥2 refetch cycles, ~3s each) — the typed
   text was completely untouched (not cleared, not reset, not reverted). This proves the
   server-state/form-state split structurally killed the HTMX refresh-race bug class.
5. **Visual**: sidebar shows the "Telebot" wordmark in cyan, "Overview" active, the 6 future links
   greyed/disabled (not hidden), "Sign out" present; brand dark colors opaque and correct.

The verification environment (Vite dev server, a throwaway `dev_dashboard.py` launcher, and a
dashboard-only docker container) was an orchestrator-only aid, set up and torn down by the orchestrator;
it was never part of this plan and leaves no artifacts in the working tree.

## Deviations from Plan

None — plan executed exactly as written. The boot guard was implemented as `App.tsx` at the planned
path (the plan permitted either App.tsx or an equivalent guard component at the same path).

## Known Stubs

- `frontend/src/routes/ProbeView.tsx` is the PLANNED throwaway diagnostic (D-08), explicitly commented
  as scaffold and scheduled for removal in Phase 10 when the first real page lands. Not a defect — it is
  the SC#5 proof harness and is intentionally temporary.
- The 6 disabled-visible nav links ("Positions", "Trade History", "Signal Log", "Analytics", "Pending
  Stages", "Settings") are intentional disabled-visible placeholders (D-07 / UI-SPEC) that Phase 10
  enables in place. Documented in the plan as the explicit convention — not stubbed data flowing to UI.

## Threat Surface

The two plan-04 mitigations land here; the others were satisfied in Plan 03:
- **T-09-10** (Elevation — shell render before auth): the boot guard gates the shell on
  `GET /auth/me`, and every data call is independently auth-gated server-side. No client-trusted auth
  state. Verified live (deleting the session cookie forced a redirect, not a leaked shell).
- **T-09-11** (DoS — 401 redirect loop): App.tsx delegates the 401 redirect to the single global
  `onAuthError` (loop-break on `/app/login`) and adds no competing redirect — single bounce. Verified
  live (SPA-04: exactly one redirect, no loop).
- **T-09-12** (Tampering — logout without CSRF): Sign out POSTs through the http wrapper, which sets
  `X-CSRF-Token` from the readable cookie.
- **T-09-13** (Info disclosure — probe polling): `accept` — `/trading-status` returns only an auth-gated
  boolean paused flag; no PII.

No new security surface introduced beyond the plan's threat model.

## Verification Results

- `cd frontend && npm run build` exits 0 (tsc -b + vite build; 1916 modules, dist built).
- router.tsx: `createBrowserRouter` with `basename: "/app"`, `/login` + `/` routes (no `/app` prefix) — confirmed.
- main.tsx: `QueryClientProvider` wraps `RouterProvider` + root sonner `<Toaster/>` — confirmed.
- App.tsx: boot guard calls `/api/v2/auth/me`, no competing redirect — confirmed.
- Sidebar.tsx: Telebot wordmark + Overview live + 6 disabled-visible labels + Sign out -> /auth/logout POST — confirmed.
- ProbeView.tsx: `useQuery` with `refetchInterval: 3000` for trading-status + a SEPARATE `useState` input not sourced from cache — confirmed.
- Manual browser phase gate: APPROVED by the human — all five checks passed live (cold login no-403, no localStorage token, deep-link reload, single 401 redirect, input survived ≥2 refetches).

## Requirements Satisfied

- **SPA-04**: single global 401 redirect to login with no loop — proven live (already marked complete in Plan 03; re-confirmed end-to-end here through the boot guard).
- **SPA-05**: real-endpoint background poll runs ≥2 refetch cycles without clobbering an open input — the server-state/form-state split proven live before any real page is built.

## Self-Check: PASSED

- Files: router.tsx, main.tsx, App.tsx, AppShell.tsx, Sidebar.tsx, ProbeView.tsx — all FOUND.
- Commits: 524de41, feb17cb — both FOUND in git log.
- Build: `npm run build` exits 0.
