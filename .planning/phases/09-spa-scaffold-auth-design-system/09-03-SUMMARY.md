---
phase: 09-spa-scaffold-auth-design-system
plan: 03
subsystem: frontend-data-auth
tags: [react, tanstack-query, csrf, auth, fetch-wrapper, spa]
requires:
  - "09-01: frontend/ Vite+React+Tailwind+shadcn scaffold (package.json, ui components, index.css tokens)"
provides:
  - "frontend/src/lib/http.ts — api() fetch wrapper + HttpError (X-CSRF-Token echo, credentials:same-origin)"
  - "frontend/src/lib/queryClient.ts — queryClient with single global onAuthError 401 redirect + D-09 polling defaults"
  - "frontend/src/auth/csrf.ts — seedCsrf() cold-start + readCsrfCookie()"
  - "frontend/src/auth/LoginView.tsx — login view consuming /api/v2/auth/login"
affects:
  - "Plan 09-04 (router/shell/boot-guard) wires LoginView into /app/login and provides queryClient at the app root"
  - "Phase 10/11 pages inherit api(), queryClient defaults, and the server-state/form-state split"
tech-stack:
  added:
    - "@tanstack/react-query@5.101.0"
    - "react-router-dom@7.17.0 (installed here; consumed in Plan 04)"
  patterns:
    - "Single fetch path: every queryFn/mutationFn goes through api()"
    - "One global 401 handler on QueryCache + MutationCache with loop-break"
    - "Server state = TanStack Query; form/UI state = local React state (never mixed)"
key-files:
  created:
    - frontend/src/lib/http.ts
    - frontend/src/lib/queryClient.ts
    - frontend/src/auth/csrf.ts
    - frontend/src/auth/LoginView.tsx
  modified:
    - frontend/package.json
    - frontend/package-lock.json
decisions:
  - "D-04: login JSON POST to /api/v2/auth/login; telebot_csrf echoed as X-CSRF-Token; credentials:same-origin; no localStorage"
  - "D-06: single global onAuthError on QueryCache + MutationCache; HttpError(status) throw; 401 -> hard nav /app/login with loop-break"
  - "D-09: QueryClient inherited defaults keepPreviousData + refetchIntervalInBackground:false; staleTime:1000, retry:false (executor's call for an internal same-origin tool)"
metrics:
  duration: 6min
  tasks: 2
  files: 6
  completed: 2026-06-06
---

# Phase 9 Plan 03: Data + Auth Layer Summary

JWT-free cookie auth core for the SPA: a single `api()` fetch wrapper that echoes the readable
`telebot_csrf` cookie as `X-CSRF-Token` on mutations and throws `HttpError` on non-2xx, one global
401 handler shared by the QueryCache and MutationCache (hard-nav to `/app/login` with a loop-break),
the cold-start CSRF seeding helper, and a login view that consumes the Phase 8 `/api/v2/auth/*`
contract — with zero auth token in browser storage.

## What Was Built

### Task 1 — http.ts + queryClient.ts (commit 05f8f7b)
- Installed `@tanstack/react-query@5.101.0` and `react-router-dom@7.17.0` (router consumed in Plan 04;
  installed now because package.json is owned by this plan).
- `frontend/src/lib/http.ts`: `HttpError` class (carrying `status` + `body`) and the `api(path, init)`
  wrapper. Reads the readable `telebot_csrf` cookie via `readCookie()`; sets `X-CSRF-Token` on
  POST/PUT/PATCH/DELETE only (matching `api/deps.py` `_STATE_CHANGING_METHODS`); calls `fetch` with
  `credentials: "same-origin"`; parses the `{error:{code,message}}` envelope into `HttpError.body`
  on non-2xx; returns `null` for 204 else `res.json()`. No localStorage; the httpOnly session cookie
  is never read in JS.
- `frontend/src/lib/queryClient.ts`: `onAuthError` redirects to `/app/login` on `HttpError.status === 401`,
  skipping the redirect when `window.location.pathname` already starts with `/app/login` (loop-break).
  Wired on BOTH `new QueryCache({ onError })` and `new MutationCache({ onError })`. Defaults:
  `placeholderData: keepPreviousData`, `refetchIntervalInBackground: false`, `staleTime: 1000`,
  `retry: false`.

### Task 2 — csrf.ts + LoginView.tsx (commit f847584)
- `frontend/src/auth/csrf.ts`: `seedCsrf()` GETs `/api/v2/auth/csrf` (seeds the readable cookie and
  returns the token); `readCsrfCookie()` reads the cookie value (reusing http.ts `readCookie`).
- `frontend/src/auth/LoginView.tsx`: centered shadcn `<Card>` on the `--background` field; "Telebot"
  Display 28px/600 title; "Username" + "Password" labels with uncontrolled-style local-state inputs
  (no form lib — deferred to Phase 11). Calls `seedCsrf()` on mount (cold-start guard, Pitfall 5).
  Submits `POST /api/v2/auth/login {password, csrf_token}` (the wrapper adds `X-CSRF-Token`); the
  backend `LoginIn` schema takes `password` + `csrf_token` only, so Username is rendered for UI
  parity but NOT submitted. Button shows "Log in" / "Logging in…" and is disabled while pending.
  Error branches: 401 -> "Incorrect username or password.", everything else (403/429/500/network) ->
  "Something went wrong. Please try again." The cyan `--primary` CTA is the only saturated element.
  Optional session-expired banner shows only when arrived via an `?expired`/`?reason=expired` flag.
  On success, hard-nav to `/app/` (the router/boot-guard gate lands in Plan 04).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] TS parameter-property shorthand rejected by `erasableSyntaxOnly`**
- **Found during:** Task 1
- **Issue:** `tsconfig.app.json` (from Plan 01) enables `erasableSyntaxOnly`, which forbids the
  `constructor(public readonly status: number, ...)` parameter-property shorthand (TS1294), failing
  `tsc -b`.
- **Fix:** Rewrote `HttpError` with explicit `readonly` field declarations and plain constructor
  assignments. Pure syntax change, identical runtime/type behavior.
- **Files modified:** frontend/src/lib/http.ts
- **Commit:** 05f8f7b

**2. [Rule 3 - Blocking] localStorage/session grep gate tripped by comment prose**
- **Found during:** Task 1
- **Issue:** The acceptance grep gates (`! grep -rq localStorage src/`, no `telebot_session`) are
  literal substring checks; explanatory comments that mentioned "localStorage/sessionStorage" and
  "telebot_session" tripped them despite no actual usage.
- **Fix:** Reworded the comments to describe the security posture without the literal forbidden
  tokens. The hard SPA-03 gate now passes cleanly (no real storage/session-read usage ever existed).
- **Files modified:** frontend/src/lib/http.ts
- **Commit:** 05f8f7b

## Deferred Issues

- Pre-existing eslint `react-refresh/only-export-components` error in
  `frontend/src/components/ui/button.tsx:64` (shadcn-generated `buttonVariants` export from Plan 01).
  Out of scope for this plan; logged to `deferred-items.md`. Does not affect the build. The new files
  (csrf.ts, LoginView.tsx, http.ts, queryClient.ts) produce no lint errors.

## Threat Surface

All four threat-register mitigations for this plan are satisfied:
- **T-09-06** (auth token storage): no localStorage/sessionStorage (grep-clean); httpOnly session
  cookie never read in JS; `credentials:"same-origin"` only.
- **T-09-07** (CSRF on mutations): `X-CSRF-Token` echoed from the readable cookie on
  POST/PUT/PATCH/DELETE only; server compares with `compare_digest`.
- **T-09-08** (401 redirect loop): `onAuthError` skips the redirect when already on `/app/login`;
  hard-nav clears in-memory state (single bounce).
- **T-09-09** (cross-origin cookie leak): relative `/api/v2` URLs only; same-origin via the dev proxy.

No new security surface introduced beyond the plan's threat model.

## Verification Results

- `cd frontend && npm run build` exits 0 (tsc -b + vite build).
- `grep -rq localStorage frontend/src` returns nothing (SPA-03 hard gate).
- http.ts: `X-CSRF-Token` on mutations + `credentials:same-origin` + `HttpError` throw — confirmed.
- queryClient.ts: `onError` on QueryCache + MutationCache, `/app/login` loop-break, `keepPreviousData`,
  `refetchIntervalInBackground:false` — confirmed.
- LoginView: cold-start `seedCsrf()`, exact copy strings, pending/disabled, 401 vs generic error
  branches — confirmed.
- Manual browser gate (deferred to phase gate): cold login no 403, no auth token in localStorage,
  single 401 redirect with no loop.

## Self-Check: PASSED

- Files: http.ts, queryClient.ts, csrf.ts, LoginView.tsx — all FOUND.
- Commits: 05f8f7b, f847584 — both FOUND in git log.
