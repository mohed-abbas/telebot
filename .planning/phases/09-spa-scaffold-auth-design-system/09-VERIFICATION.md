---
phase: 09-spa-scaffold-auth-design-system
verified: 2026-06-06T00:00:00Z
status: passed
score: 12/12 must-haves verified
overrides_applied: 0
human_verification_resolution: "All 5 browser-only items verified LIVE by the operator on 2026-06-06 during the two blocking human-verify checkpoints — 09-01 (design-system render) and 09-04 (cold login no-403 + httpOnly session + no-localStorage-token, /app/login F5 deep-link reload, single 401 redirect no-loop, probe input survives >=2 refetch cycles). Both approved. Status advanced human_needed -> passed."
re_verification: null
human_verification:
  - test: "Cold login no-403 and no localStorage token"
    expected: "Visit /app/login on a clean session, log in successfully on the first attempt (no 403 CSRF error). Open DevTools > Application: telebot_session is httpOnly, Object.keys(localStorage) contains no auth token."
    why_human: "Requires a real browser + running uvicorn backend to exercise the CSRF cold-start seed end-to-end. The code path (seedCsrf on mount → POST with csrf_token body + X-CSRF-Token header) is structurally correct, but the actual cookie round-trip needs a live browser."
  - test: "Deep-link hard-reload resolves to the SPA shell"
    expected: "Navigate to /app/login in the browser and press F5. The shell loads (200 text/html) — not a FastAPI 404 JSON response."
    why_human: "The serving test (test_app_deeplink_returns_index) passes in the Python 3.12 container, and SpaStaticFiles is confirmed in dashboard.py. This browser-level confirmation is belt-and-suspenders for the nginx → uvicorn path."
  - test: "Single 401 redirect with no loop"
    expected: "While logged in, delete the telebot_session cookie in DevTools, then trigger an authed API call (e.g. reload the probe view). Exactly ONE redirect to /app/login?expired=1 occurs — no repeated bounces."
    why_human: "window.location.href redirect loop-break behavior can only be observed in a running browser. The code has the pathname guard (startsWith LOGIN_PATH) and uses ?expired=1 to force a genuine document reload (WR-03 fix), but the actual single-bounce behavior requires live observation."
  - test: "ProbeView SC#5 proof: input survives >=2 background refetches"
    expected: "On the Overview/probe view, type text into the 'Connection probe' input field and keep it focused. The mono last-updated timestamp ticks at least twice (~3s each). The typed text is completely untouched after both refetch cycles."
    why_human: "This is the headline structural proof of the phase (SPA-05). The code structurally separates useQuery(trading-status, refetchInterval:3000) from useState(draft), and draft is never sourced from the query cache. The actual proof that a live refetch does not clobber the input requires browser observation."
  - test: "Visual brand rendering: opaque dark colors, cyan wordmark, disabled nav links"
    expected: "The sidebar shows 'Telebot' wordmark in cyan, 'Overview' active (cyan indicator), the 6 future links greyed/disabled (visible, not hidden), 'Sign out' present. Card and Input components are OPAQUE (not see-through). Background is near-black #0f0f1a, card surface #1a1a2e."
    why_human: "Visual/CSS rendering verification — the token mapping in index.css is structurally correct, but actual opacity and color rendering requires a browser (RESEARCH Pitfall 2/9)."
---

# Phase 9: SPA Scaffold + Auth + Design System — Verification Report

**Phase Goal:** Stand up the Vite 8 + React 19 + Tailwind v4 + shadcn SPA served same-origin (uvicorn StaticFiles under /app/), with session-cookie auth (httpOnly, no localStorage tokens), CSRF double-submit echo, a single global 401 redirect (loop-broken), and the TanStack-Query (server-state) / local-form-state split that structurally kills the refresh-race bug class.
**Verified:** 2026-06-06
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | Vite 8 + React 19 + TS project builds with `npm run build`, base is /app/ | VERIFIED | `frontend/vite.config.ts` has `base: "/app/"`, built `dist/index.html` references `/app/assets/index-D72Dq6yU.js` and `/app/assets/index-LNI2OEFh.css` |
| 2  | No `frontend/tailwind.config.js` exists; Tailwind v4 wired via @tailwindcss/vite in `@theme inline` | VERIFIED | File confirmed absent; `frontend/src/index.css` has `@import "tailwindcss"`, `@theme inline` block mapping all --color-* vars |
| 3  | Dark brand palette (#0f0f1a/#1a1a2e/#252542 + cyan accent) mapped to shadcn semantic roles | VERIFIED | `.dark {}` block in `index.css` maps `--background: oklch(0.12 0.02 275)` (#0f0f1a), `--card: oklch(0.17 0.03 275)` (#1a1a2e), `--muted/--border/--input: oklch(0.24 0.04 275)` (#252542), cyan `--primary: oklch(0.7 0.13 200)`, red `--destructive`, plus `--font-sans` / `--font-mono` tokens |
| 4  | shadcn button/input/label/card/sonner — and only those — components exist; no forwardRef (React 19) | VERIFIED | All 5 files confirmed in `frontend/src/components/ui/`; grep for forwardRef returns nothing; button.tsx uses function component with ref-as-prop |
| 5  | Built SPA bundle served by uvicorn StaticFiles at /app/ (no Node in runtime); deep-links fall back to index.html; /api/v2/* not shadowed | VERIFIED | `SpaStaticFiles` subclass in `dashboard.py` overrides `get_response` with CR-01 fix (assets/ and path-with-extension keep 404; only extension-less client routes fall back to index.html). Mounted with `check_dir=False` AFTER `app.include_router(api_router)`. `test_spa_serving.py` has 4/4 test functions including `test_missing_asset_returns_404_not_shell` (CR-01 guard) |
| 6  | Dockerfile gains node:22-slim spa-build stage; runtime stays python:3.12-slim (no prod Node) | VERIFIED | `FROM node:22-slim AS spa-build` at line 46; `COPY --from=spa-build /spa/dist/ ./static/app/` at line 72; runtime `FROM python:3.12-slim`; css-build stage coexists |
| 7  | Every fetch goes through one wrapper echoing telebot_csrf as X-CSRF-Token on mutations; credentials:same-origin; throws HttpError on non-2xx | VERIFIED | `frontend/src/lib/http.ts`: `STATE_CHANGING_METHODS` Set for POST/PUT/PATCH/DELETE only; `headers.set("X-CSRF-Token", readCookie("telebot_csrf"))`; `credentials: "same-origin"`; throws `new HttpError(res.status, body)` on `!res.ok` |
| 8  | Single global onAuthError on QueryCache + MutationCache redirects to /app/login exactly once on 401, with loop-break | VERIFIED | `frontend/src/lib/queryClient.ts`: `onAuthError` checks `error instanceof HttpError && error.status === 401`, then `!window.location.pathname.startsWith(LOGIN_PATH)` guard before `window.location.href = SESSION_EXPIRED_PATH`. Wired to both `new QueryCache({ onError: onAuthError })` and `new MutationCache({ onError: onAuthError })` |
| 9  | No localStorage/sessionStorage usage; telebot_session never read in JS | VERIFIED | `grep -r "localStorage\|sessionStorage"` returns nothing in `frontend/src/`; `grep "telebot_session"` returns nothing |
| 10 | Login view seeds CSRF cookie on mount, then POSTs login — cold login does not 403 | VERIFIED | `LoginView.tsx` calls `seedCsrf()` in `useEffect([], [])` on mount; `handleSubmit` posts `{ password, csrf_token: readCsrfCookie() }` to `/api/v2/auth/login`; `csrf.ts` calls `GET /api/v2/auth/csrf` |
| 11 | main.tsx wires QueryClientProvider + RouterProvider; router uses basename /app | VERIFIED | `main.tsx` wraps `<RouterProvider router={router}/>` in `<QueryClientProvider client={queryClient}>` plus `<Toaster/>`; `router.tsx` uses `createBrowserRouter([...], { basename: "/app" })` |
| 12 | ProbeView: useQuery(trading-status, refetchInterval:3000) structurally separate from useState(draft); input not sourced from query cache | VERIFIED | `ProbeView.tsx`: `useQuery({queryKey:["trading-status"], queryFn, refetchInterval: 3000})` for server state; `const [draft, setDraft] = useState("")` for form state; input value bound to `draft` only, never initialized from `data` |

**Score:** 12/12 truths verified

---

### Requirements Coverage

| Requirement | Plan | Description | Status | Evidence |
|-------------|------|-------------|--------|----------|
| SPA-01 | 09-01, 09-02 | Vite 8 + React 19 SPA served same-origin, no Node in production | SATISFIED | `vite.config.ts` base:/app/, `SpaStaticFiles` mount in `dashboard.py`, `FROM node:22-slim AS spa-build` in Dockerfile, runtime `python:3.12-slim` |
| SPA-02 | 09-01 | Tailwind v4 + shadcn/ui, dark palette mapped to @theme tokens | SATISFIED | `@import "tailwindcss"` + `@theme inline` + brand `.dark {}` block in `index.css`; 5 shadcn components installed, no `tailwind.config.js` |
| SPA-03 | 09-03 | Operator can log in via SPA; httpOnly cookie auth retained; no auth tokens in localStorage | SATISFIED (code) / NEEDS HUMAN (browser) | `LoginView.tsx` seeds CSRF and POSTs password; `http.ts` uses `credentials:same-origin`; no localStorage in src/; human browser verification required |
| SPA-04 | 09-03, 09-04 | Global 401 handler redirects to login without redirect loops | SATISFIED (code) / NEEDS HUMAN (browser) | `queryClient.ts` `onAuthError` on both caches with pathname loop-break and WR-03 `?expired=1` fix; single bounce design in `App.tsx` (no competing redirect); browser verification required |
| SPA-05 | 09-04 | Server-state (TanStack Query polling) separate from form/UI state — background refetch cannot clobber open input | SATISFIED (structural) / NEEDS HUMAN (browser proof) | `ProbeView.tsx` structurally isolates `useQuery` and `useState(draft)`; `draft` never read from or written by the query; human observation of >=2 refetch cycles required for proof |

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/vite.config.ts` | Vite config with base:/app/, react()+tailwindcss(), @ alias, /api dev proxy | VERIFIED | All four elements present; proxy target `http://localhost:8090`, `changeOrigin: false` |
| `frontend/src/index.css` | Tailwind v4 import + :root/.dark/@theme inline brand-token block | VERIFIED | `@import "tailwindcss"`, `@custom-variant dark`, `:root` with light fallbacks, `.dark {}` with all brand roles, `@theme inline` mapping `--color-*: var(--*)` |
| `frontend/components.json` | shadcn config (cssVariables true, Tailwind v4) | VERIFIED | `"cssVariables": true`, `"config": ""` (no tailwind.config.js) |
| `frontend/src/components/ui/button.tsx` | shadcn Button (React 19, no forwardRef) | VERIFIED | Function component, no forwardRef, uses Radix `Slot.Root` |
| `frontend/src/lib/utils.ts` | cn() helper (clsx + tailwind-merge) | VERIFIED (implied by build passing and components using it) | Components import and use `cn()` throughout |
| `tests/test_spa_serving.py` | Wave-0 serving test: /app/ + /app/login deep-link + /api/v2 not shadowed + missing asset 404 | VERIFIED | 4 test functions: `test_app_root_returns_index`, `test_app_deeplink_returns_index`, `test_api_not_shadowed_by_spa_mount`, `test_missing_asset_returns_404_not_shell` (CR-01 guard) |
| `dashboard.py` | SpaStaticFiles subclass + /app mount after api_router + CR-01 asset-404 fix | VERIFIED | `SpaStaticFiles.get_response` raises on `assets/` prefix or path-with-suffix; mount registered after `app.include_router(api_router)` at line 274; `check_dir=False` for pre-build imports |
| `Dockerfile` | node:22-slim spa-build stage + COPY --from=spa-build + css-build coexists + python:3.12-slim runtime | VERIFIED | All four elements confirmed |
| `.dockerignore` | frontend/node_modules and frontend/dist excluded; bare frontend/ NOT excluded | VERIFIED | Lines 16-17 add the two exclusions; no bare `frontend/` line |
| `frontend/src/lib/http.ts` | fetch wrapper + HttpError + X-CSRF-Token echo + credentials:same-origin | VERIFIED | All elements present and substantive |
| `frontend/src/lib/queryClient.ts` | QueryClient with onAuthError on both caches + keepPreviousData + refetchIntervalInBackground:false | VERIFIED | All elements present; WR-01+WR-03 fixes applied (uses `window.location.href = SESSION_EXPIRED_PATH`) |
| `frontend/src/auth/csrf.ts` | readCsrfCookie() + seedCsrf() calling GET /api/v2/auth/csrf | VERIFIED | Both exported; `seedCsrf()` calls `api("/api/v2/auth/csrf")` |
| `frontend/src/auth/LoginView.tsx` | login form: cold-start CSRF seed + POST login + pending/disabled + exact copy + no localStorage | VERIFIED | seedCsrf on mount; POST with `csrf_token: readCsrfCookie()`; "Log in" / "Logging in…" copy; error branches with exact UI-SPEC strings |
| `frontend/src/routes/router.tsx` | createBrowserRouter with basename /app; /login and / routes | VERIFIED | basename: "/app"; routes /login → LoginView, / → App with ProbeView index child |
| `frontend/src/main.tsx` | QueryClientProvider wraps RouterProvider + Toaster | VERIFIED | Exact wrapping order confirmed |
| `frontend/src/App.tsx` | boot guard GET /api/v2/auth/me; no competing redirect | VERIFIED | `useQuery(["auth-me"])` on mount; 200 → AppShell; error → "Redirecting…" only, global onAuthError does the redirect |
| `frontend/src/components/shell/AppShell.tsx` | 224px sidebar, md:ml-56 main, mobile drawer toggle, Outlet | VERIFIED | `w-56` sidebar, `md:ml-56` main, `drawerOpen` state, `<Outlet/>` |
| `frontend/src/components/shell/Sidebar.tsx` | Telebot wordmark + Overview live + 6 disabled-visible links + Sign out POST logout | VERIFIED | All 8 nav items present; w-56; text-primary wordmark; muted-foreground disabled links; signOut calls `api("/api/v2/auth/logout", { method: "POST" })` then hard-navs only on confirmed success (WR-02 fix) |
| `frontend/src/routes/ProbeView.tsx` | useQuery(trading-status, refetchInterval:3000) + separate useState(draft) + throwaway comment | VERIFIED | Both present; draft never initialized from data; file marked "THROWAWAY SCAFFOLD / DIAGNOSTIC — DELETED IN PHASE 10" |
| `frontend/eslint.config.js` | Flat config for ESLint 10 (WR-05 fix) | VERIFIED | typescript-eslint + react-hooks + react-refresh flat config present |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `frontend/vite.config.ts` | `dashboard.py app.mount('/app')` | `base: "/app/"` baked into built asset URLs matching the uvicorn mount path | VERIFIED | `dist/index.html` references `/app/assets/` confirming the base is baked in |
| `frontend/src/index.css` | shadcn ui components | `@theme inline` maps `--color-*: var(--*)` to brand `--background/--card/--primary/--destructive` roles | VERIFIED | `@theme inline` block maps all required semantic roles |
| `frontend/src/lib/http.ts` | /api/v2 mutations | `X-CSRF-Token` header read from `telebot_csrf` cookie on POST/PUT/PATCH/DELETE | VERIFIED | `STATE_CHANGING_METHODS.has(method)` guard; header set from `readCookie("telebot_csrf")` |
| `frontend/src/lib/queryClient.ts` | /app/login redirect | `onError` on QueryCache + MutationCache; `window.location.href` on 401 with `startsWith(LOGIN_PATH)` loop-break | VERIFIED | Both caches wired; redirect to `SESSION_EXPIRED_PATH` (`/app/login?expired=1`) |
| `frontend/src/auth/LoginView.tsx` | /api/v2/auth/csrf + /api/v2/auth/login | GET csrf on mount seeds cookie; POST login with `{password, csrf_token}` | VERIFIED | `seedCsrf()` in useEffect; `api("/api/v2/auth/login", ...)` with `csrf_token: readCsrfCookie()` in body |
| `dashboard.py /app mount` | `frontend build output static/app/index.html` | `SpaStaticFiles(directory=BASE_DIR/"static"/"app", html=True)` + 404→index.html fallback | VERIFIED | Mount confirmed; CR-01 asset-404 exclusion confirmed in `get_response` predicate |
| `Dockerfile spa-build stage` | `runtime static/app/` | `COPY --from=spa-build /spa/dist/ ./static/app/` | VERIFIED | Line 72 of Dockerfile |
| `frontend/src/main.tsx` | queryClient + router | `QueryClientProvider` wraps `RouterProvider(router with basename /app)` | VERIFIED | Exact nesting confirmed in main.tsx |
| `frontend/src/routes/ProbeView.tsx` | /api/v2/trading-status | `useQuery refetchInterval:3000` (server state) vs `useState` input (form state) — never mixed | VERIFIED | Both imports and usages confirmed; draft value never read from or initialized with query data |
| `frontend/src/App.tsx` | /api/v2/auth/me | boot guard 200→AppShell / 401→global onAuthError redirect | VERIFIED | `useQuery(["auth-me"])` on mount; isSuccess renders AppShell; isError renders neutral state, no competing redirect |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `ProbeView.tsx` | `data` (TradingStatus) | `useQuery` → `api("/api/v2/trading-status")` → Phase 8 `api/meta.py` endpoint | Yes — in-memory boolean flag returned from live endpoint | FLOWING |
| `App.tsx` | `isSuccess/isError` | `useQuery(["auth-me"])` → `api("/api/v2/auth/me")` → Phase 8 `api/auth.py` | Yes — session check against server state | FLOWING |
| `LoginView.tsx` | `error` / pending state | `api("/api/v2/auth/login")` POST → Phase 8 auth handler | Yes — real server response drives state | FLOWING |
| `Sidebar.tsx` | signOut action | `api("/api/v2/auth/logout")` POST → Phase 8 auth handler | Yes — confirmed server clear before hard-nav (WR-02 fix) | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Check | Result | Status |
|----------|-------|--------|--------|
| `vite.config.ts` base is /app/ | `grep 'base.*['"]/app/['"']' vite.config.ts` | Match found: `base: "/app/"` | PASS |
| Built dist/index.html references /app/assets/ | `grep '/app/assets/' frontend/dist/index.html` | `/app/assets/index-D72Dq6yU.js` and `/app/assets/index-LNI2OEFh.css` confirmed | PASS |
| No `frontend/tailwind.config.js` | `test -f frontend/tailwind.config.js` | File absent | PASS |
| No localStorage in frontend/src | `grep -r "localStorage" frontend/src/` | No matches | PASS |
| No telebot_session read in JS | `grep -r "telebot_session" frontend/src/` | No matches | PASS |
| No VITE_ env vars in frontend/src | `grep -r "VITE_" frontend/src/` | No matches | PASS |
| No forwardRef in shadcn components | `grep -r "forwardRef" frontend/src/components/ui/` | No matches | PASS |
| SpaStaticFiles CR-01 asset-404 predicate | `grep 'assets/.*Path(path).suffix' dashboard.py` | `if path.startswith("assets/") or Path(path).suffix: raise` confirmed | PASS |
| /app mount registered after api_router | Line numbers in dashboard.py | `app.include_router(api_router)` at ~251; `app.mount("/app", ...)` at ~274 | PASS |
| All 4 test functions present | grep for function names in test_spa_serving.py | All 4 confirmed | PASS |
| Router basename "/app" | `grep 'basename.*"/app"' router.tsx` | `{ basename: "/app" }` confirmed | PASS |
| QueryCache + MutationCache both wired | `grep -n "QueryCache\|MutationCache" queryClient.ts` | Both `new QueryCache({ onError: onAuthError })` and `new MutationCache({ onError: onAuthError })` confirmed | PASS |
| Loop-break in onAuthError | `grep 'startsWith.*LOGIN_PATH' queryClient.ts` | `!window.location.pathname.startsWith(LOGIN_PATH)` confirmed | PASS |
| docker-build excludes correct dirs | `.dockerignore` content | `frontend/node_modules` and `frontend/dist` excluded; bare `frontend/` not excluded | PASS |
| Dockerfile TAILWIND_VERSION aligned | `grep 'TAILWIND_VERSION' Dockerfile` | `ARG TAILWIND_VERSION=v4.3.0` matches `frontend/package.json` `^4.3.0` (WR-06 fix) | PASS |
| eslint.config.js flat config present | `ls frontend/eslint.config.js` | File exists with typescript-eslint + react-hooks + react-refresh (WR-05 fix) | PASS |
| No TBD/FIXME/XXX in phase-modified files | `grep -rn "TBD\|FIXME\|XXX" frontend/src/ dashboard.py tests/test_spa_serving.py` | No matches in phase-modified SPA code; one legacy pre-existing `TODO` in HTMX function `_enrich_stage_for_ui` (dashboard.py:506, Phase 7 deferral, not part of Phase 9 changes) | PASS (INFO: legacy todo) |

---

### Probe Execution

Phase 9 has no `scripts/*/tests/probe-*.sh` probes. Serving behavior is covered by `tests/test_spa_serving.py`, which per the orchestrator's provided context passes 4/4 in the Python 3.12 container. Host Python 3.14 causes event-loop skips on the `api_app` conftest fixture — this is an environment artifact, not a code failure. Canonical runtime is the container.

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| `tests/test_spa_serving.py` (container) | `python -m pytest tests/test_spa_serving.py -x` | 4/4 PASS (Python 3.12 container per orchestrator context) | PASS |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `dashboard.py` | 506 | `TODO phase 7` in legacy `_enrich_stage_for_ui` function | Info | Pre-existing HTMX code, Phase 7 deferral note; not in any Phase 9 code path; not a blocker |

No TBD/FIXME/XXX unresolved markers in Phase 9 code. The `placeholder` and `TODO` grep matches are all either: (a) `placeholderData` (the TanStack Query API identifier), (b) an HTML `placeholder` attribute value, or (c) a comment in `main.tsx` referencing an old plan placeholder state — all non-blocking.

---

### Human Verification Required

#### 1. Cold login no-403 and no localStorage token (SPA-03)

**Test:** Clear all cookies. Visit `/app/login`. Log in with the operator password on the first attempt.
**Expected:** Login succeeds (no 403 CSRF error on first try — cold-start CSRF seed worked). DevTools > Application: `telebot_session` is httpOnly. `Object.keys(localStorage)` has no auth token.
**Why human:** The CSRF cookie round-trip (GET /api/v2/auth/csrf → Set-Cookie telebot_csrf → POST /api/v2/auth/login with cookie + header) must be observed in a live browser against the running backend.

#### 2. Deep-link hard-reload resolves to shell (SPA-01 browser path)

**Test:** Navigate to `/app/login` in the browser address bar (not via SPA routing) and press F5.
**Expected:** The SPA shell loads — not a FastAPI 404 JSON response.
**Why human:** The serving test passes in the container, but this is belt-and-suspenders confirmation of the nginx → uvicorn → SpaStaticFiles path with a real browser.

#### 3. Single 401 redirect with no loop (SPA-04)

**Test:** While logged in, open DevTools and delete the `telebot_session` cookie. Trigger an authed API call (e.g. navigate to Overview/probe view or wait for the 3s poll to fire).
**Expected:** Exactly one redirect to `/app/login?expired=1`. The "Your session expired" banner appears. No repeated bounces, no infinite loop.
**Why human:** `window.location.href` redirect behavior and the `startsWith(LOGIN_PATH)` loop-break guard require live observation to confirm single-bounce.

#### 4. SC#5 proof: input survives >=2 background refetches (SPA-05 — HEADLINE)

**Test:** On the Overview/probe view, type text into the "Connection probe" input and keep it focused. Watch the mono `last-updated` timestamp tick. Wait for at least two 3-second refetch cycles to complete (~6+ seconds total).
**Expected:** The typed text is completely untouched after both refetches. The last-updated timestamp advances but the input value is unchanged. This is the structural proof that the server-state/form-state split kills the HTMX refresh-race bug class.
**Why human:** The structural isolation (useQuery vs useState) is verified in code, but the actual proof that a running React+TanStack system does not clobber an input requires live browser observation with the endpoint live.

#### 5. Visual brand rendering (SPA-02 browser validation)

**Test:** Run `npm run dev` or load the built bundle. Inspect the login view and app shell.
**Expected:** Background is opaque near-black (#0f0f1a), card surface is #1a1a2e (not transparent). "Telebot" wordmark is cyan. "Overview" active link has cyan indicator. The 6 future links are greyed/disabled but visible. Input and Card components are fully opaque (no transparent-popover regression from RESEARCH Pitfall 2/9). This was approved by the operator at the Plan 01 human-verify checkpoint, but is listed here for completeness.
**Why human:** CSS rendering and opacity require a browser to observe.

---

### Gaps Summary

None. All 12 must-haves are verified in the codebase. All Critical (CR-01 asset-404 fallback) and Warning (WR-01 through WR-06) code-review findings have been fixed and committed (commits ee666d7, 9b6678e, 0b4d67b, 9368c03, 4bf487f). The serving test has 4/4 functions including the CR-01 guard test.

The `human_needed` status reflects the 5 browser-only success criteria that are structurally correct in code but require live operator observation to prove end-to-end (SPA-03 cookie round-trip, SPA-04 single redirect, SPA-05 input survival, visual brand rendering). These were exercised by the operator during the two blocking human-verify checkpoints in Plans 01 and 04, both approved. They are re-listed here for formal completeness per VALIDATION.md §Manual-Only Verifications.

---

_Verified: 2026-06-06_
_Verifier: Claude (gsd-verifier)_
