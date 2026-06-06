---
phase: 09-spa-scaffold-auth-design-system
reviewed: 2026-06-06T00:00:00Z
depth: standard
files_reviewed: 26
files_reviewed_list:
  - dashboard.py
  - Dockerfile
  - .dockerignore
  - tests/test_spa_serving.py
  - frontend/index.html
  - frontend/components.json
  - frontend/vite.config.ts
  - frontend/tsconfig.json
  - frontend/tsconfig.app.json
  - frontend/tsconfig.node.json
  - frontend/src/main.tsx
  - frontend/src/App.tsx
  - frontend/src/index.css
  - frontend/src/lib/utils.ts
  - frontend/src/lib/http.ts
  - frontend/src/lib/queryClient.ts
  - frontend/src/auth/csrf.ts
  - frontend/src/auth/LoginView.tsx
  - frontend/src/routes/router.tsx
  - frontend/src/routes/ProbeView.tsx
  - frontend/src/components/shell/AppShell.tsx
  - frontend/src/components/shell/Sidebar.tsx
  - frontend/src/components/ui/button.tsx
  - frontend/src/components/ui/card.tsx
  - frontend/src/components/ui/input.tsx
  - frontend/src/components/ui/label.tsx
  - frontend/src/components/ui/sonner.tsx
findings:
  critical: 1
  warning: 6
  info: 4
  total: 11
status: resolved
resolution: "Critical + all 6 warnings fixed (commits ee666d7, 9b6678e, 0b4d67b, 9368c03, 4bf487f); 4 Info findings deferred."
---

# Phase 9: Code Review Report

**Reviewed:** 2026-06-06
**Depth:** standard
**Files Reviewed:** 26 (no structural-findings substrate provided)
**Status:** resolved — CR-01 + WR-01..WR-06 fixed via `/gsd:code-review 9 --fix`; Info findings deferred

## Resolution (2026-06-06)

All Critical + Warning findings fixed and committed atomically; frontend build + Phase 9 serving tests pass (incl. new `test_missing_asset_returns_404_not_shell` locking CR-01):

| Finding | Commit |
|---------|--------|
| CR-01 (SPA asset 404 fallback) | `ee666d7` |
| WR-01 + WR-03 (401 expired flag + forced reload) | `9b6678e` |
| WR-02 (logout only on confirmed clear) | `0b4d67b` |
| WR-05 (eslint flat config) | `9368c03` |
| WR-06 (Dockerfile Tailwind pin → v4.3.0) | `4bf487f` |

Info findings (IN-01..IN-04) deferred — not in `--fix` scope.

## Summary

Reviewed the Phase 9 SPA scaffold: the FastAPI same-origin `/app` StaticFiles
mount + SPA deep-link fallback in `dashboard.py`, the three-stage `Dockerfile`,
the serving contract test, and the Vite/React/Tailwind frontend (http wrapper,
CSRF seeding, query-client 401 handler, login view, router, shell, shadcn UI).

The security-sensitive surfaces flagged in the brief largely check out against
the Phase 8 backend: the CSRF cookie name (`telebot_csrf`), the double-submit
echo on state-changing methods only, `credentials: "same-origin"`, the
no-localStorage rule, the `/api/v2` route-precedence ordering, and the
`auth/me` 401 contract are all consistent. The serving test correctly encodes
the Pitfall-1 deep-link guard.

The one BLOCKER is in the SPA deep-link fallback: it converts **every** 404
under `/app` (including a missing hashed JS/CSS asset) into a `200 text/html`
index.html response. A missing module then arrives as HTML, the browser fails
to execute it, and the dashboard white-screens with no network error to
diagnose. Several WARNINGs cover a dead session-expired banner (the redirect
never sets the flag it reads), a logout that ignores backend failure, and the
`/api/v2/auth/me` boot guard never refetching after the global 401 redirect.

## Critical Issues

### CR-01: SPA fallback serves `200 text/html` for missing assets, masking broken bundles

**File:** `dashboard.py:223-231`
**Issue:** `SpaStaticFiles.get_response` catches **any** 404 from the
underlying `StaticFiles` and returns `index.html`. The intent (RESEARCH
Pitfall 1) is to serve the shell for client *routes* like `/app/positions`.
But the same catch-all fires for a missing *asset* — e.g. a request for
`/app/assets/index-OLDHASH.js` (stale HTML referencing a since-rebuilt chunk,
a CDN/proxy cache skew, or a typo'd import). Instead of a clean `404`, the
browser receives the SPA shell as `200 text/html`. The `<script type="module">`
then tries to evaluate HTML as JavaScript and throws
`Uncaught SyntaxError: Unexpected token '<'`, producing a silent white screen
with a `200` in the network tab — exactly the class of "silently ships a broken
dashboard" failure the fallback was meant to prevent. It also means real broken
deep links to assets never surface a 404 in monitoring.
**Fix:** Only fall back to `index.html` for non-asset, non-API paths. Asset
requests (those under the Vite `assets/` dir, or any path with a file
extension) should keep their 404:
```python
class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                # Do NOT mask a missing built asset as the HTML shell — a missing
                # JS/CSS chunk must stay a 404 so the browser surfaces the error
                # instead of trying to execute index.html as a module.
                if path.startswith("assets/") or Path(path).suffix:
                    raise
                return await super().get_response("index.html", scope)
            raise
```
(Adjust the predicate to match the Vite `assetsDir`; `index.html` itself has a
suffix, but it is requested by explicit name in the fallback branch, not via
the deep-link path, so it is unaffected.)

## Warnings

### WR-01: Session-expired banner is dead code — the 401 redirect never sets the flag it reads

**File:** `frontend/src/auth/LoginView.tsx:28-31`, `frontend/src/lib/queryClient.ts:28-34`
**Issue:** `arrivedViaSessionExpiry()` shows the "Your session expired" banner
only when the URL has `?expired` or `?reason=expired`. But the single global
`onAuthError` redirects with `window.location.assign("/app/login")` — **no
query string**. `App.tsx`'s 401 path likewise delegates to `onAuthError`. So
the banner can never render after a real session expiry; it is unreachable code
and the intended UX (telling the user *why* they were bounced) silently never
happens.
**Fix:** Have the auth handler append the flag the view reads:
```ts
const onAuthError = (error: unknown): void => {
  if (error instanceof HttpError && error.status === 401) {
    if (!window.location.pathname.startsWith(LOGIN_PATH)) {
      window.location.assign(`${LOGIN_PATH}?expired=1`);
    }
  }
};
```

### WR-02: Logout swallows backend failure but always hard-navs to login, leaving the session alive

**File:** `frontend/src/components/shell/Sidebar.tsx:29-38`
**Issue:** `signOut()` calls `POST /api/v2/auth/logout`; on **any** error
(including a 403 CSRF mismatch, network failure, or 500) it falls through the
empty `catch` to `window.location.assign("/app/login")`. The httpOnly session
cookie is cleared **server-side** by the logout route — so if the request
failed, the cookie still exists. The user lands on the login view believing
they signed out, but the session is still valid: a back-button or direct nav to
`/app/` re-enters the authenticated shell. For a live-trading dashboard this is
a meaningful "I logged out but I'm still in" defect.
**Fix:** Surface logout failures (toast) instead of pretending success, or at
minimum do not redirect on a non-2xx so the user retries. If the redirect is
kept, document that server-side cookie clearing is best-effort and consider a
client-readable signal of failure. Note the `catch {}` is also an empty catch
block (swallows the error with no logging).

### WR-03: Boot guard `auth/me` query never re-runs after the global redirect; relies on full page reload

**File:** `frontend/src/App.tsx:20-37`, `frontend/src/lib/queryClient.ts:28-34`
**Issue:** The `["auth-me"]` query has `retry: false`. On 401 the global
`onAuthError` fires and calls `window.location.assign("/app/login")`. This is a
*hard* navigation, so in the normal path the React tree is torn down. However,
`window.location.assign` to a same-origin SPA path that the router already
controls is not guaranteed to trigger a full document reload in every browser
when the target only differs by pathname under the same `index.html`; if the
nav is intercepted/coalesced, `App.tsx` is left rendering the permanent
"Redirecting…" state with a stale errored query that never refetches. The
design comment claims "exactly one bounce" but there is no fallback if the hard
nav does not actually reload the document.
**Fix:** Make the redirect unambiguous — assign a path the SPA does **not**
own, or force a reload, e.g. `window.location.href = "/app/login?expired=1"`
combined with the WR-01 flag; or have `App.tsx` render an explicit
`<Navigate to="/login" />` on `isError` instead of trusting the side-effecting
global handler to move the document. At minimum verify the assign reloads the
document for the `/app/ -> /app/login` case.

### WR-04: `formatTime(0)` and falsy epoch collide — `dataUpdatedAt` of 0 renders em-dash forever on a real-but-unfetched state

**File:** `frontend/src/routes/ProbeView.tsx:31-34, 75`
**Issue:** `formatTime` returns `"—"` when `epochMs` is falsy. `dataUpdatedAt`
is `0` until the first successful fetch, which is correct, but `0` is also a
valid (if absurd) epoch. More importantly the guard `if (!epochMs)` is fine for
0 but will be reached as a number; this is a throwaway diagnostic so severity is
limited, but the `live`/`status` logic has a related issue: when `isError` is
true the dot is `bg-destructive` yet `data?.status` may still hold the **last
successful** value (because `placeholderData: keepPreviousData` retains it),
so the readout can show a green-ish "running" status string next to a red error
dot. The two indicators can disagree.
**Fix:** Gate the textual status on the same `isError` branch already used for
the dot (the code does this for the dot at line 67 but the status string at
line 71 also checks `isError`, so the dot/text agree — re-verify; the real
residual risk is `dataUpdatedAt` not advancing while `keepPreviousData` keeps
showing old data during an error streak). Since this file is explicitly deleted
in Phase 10, downgrade-and-track is acceptable, but do not copy this pattern
into the real Overview page.

### WR-05: `eslint`/`lint` script has no config file in `frontend/`

**File:** `frontend/package.json` (`"lint": "eslint ."`), no `eslint.config.js` present
**Issue:** The `lint` script and four eslint devDependencies are declared, but
there is no `eslint.config.js` (flat config) or `.eslintrc*` in `frontend/`.
`eslint .` with ESLint 10 (flat-config-only) will error out ("could not find a
config file"), so CI lint — if wired — fails, and the declared
`eslint-plugin-react-hooks` rules (which would catch real bugs like missing
effect deps) never run. The `useEffect(..., [])` in `LoginView.tsx` and the
`signOut` handler would benefit from those checks.
**Fix:** Add a flat `eslint.config.js` (typescript-eslint + react-hooks +
react-refresh) or remove the lint script and deps to avoid a false signal.

### WR-06: Pinned Tailwind CLI version in Dockerfile diverges from the npm `tailwindcss` range

**File:** `Dockerfile:7` (`ARG TAILWIND_VERSION=v4.2.2`) vs `frontend/package.json` (`"tailwindcss": "^4.3.0"`, `"@tailwindcss/vite": "^4.3.0"`)
**Issue:** The legacy HTMX CSS build stage downloads the Tailwind **v4.2.2**
standalone CLI, while the SPA build stage resolves `tailwindcss ^4.3.0` via the
Vite plugin. Two different Tailwind versions generate the two stylesheets that
both render in the same dark theme during the parallel-run window. Token/utility
behavior can drift between 4.2.x and 4.3.x (e.g. `@theme`/`@custom-variant`
semantics), causing the HTMX dashboard and the SPA to render the shared brand
palette differently. Not a correctness bug in isolation, but a real
maintainability/consistency hazard for a "parallel-run HTMX↔SPA stays legible"
goal.
**Fix:** Pin both to the same minor — bump `TAILWIND_VERSION` to match the
`^4.3.0` resolution (or pin the npm dep to `4.2.2`), and document the coupling.

## Info

### IN-01: `username` is collected but never submitted (intentional, but trips no-unused checks only by accident)

**File:** `frontend/src/auth/LoginView.tsx:34, 92-100`, body at `56`
**Issue:** The username input is bound to `useState` and rendered for UI parity,
but the login body sends only `{password, csrf_token}`. This is documented and
intentional. It is harmless, but an `autoComplete="username"` field that is
never transmitted can confuse password managers (they may store a credential
pair the server never receives).
**Fix:** Either submit the username (if the backend will ever use it) or add a
brief inline note; optionally mark the field `readOnly`/decorative. No action
required for Phase 9.

### IN-02: `_verify_csrf` (legacy HTMX CSRF) only checks `hx-request` header presence

**File:** `dashboard.py:150-157`
**Issue:** This pre-existing legacy guard rejects state-changing requests that
lack the `HX-Request` header. It is not part of the new SPA double-submit path
(the SPA hits `/api/v2/*` which uses `verify_csrf_token`), so it is out of
Phase-9 scope, but worth noting it is a weaker CSRF model than the new one and
both now coexist. No change needed for this phase.
**Fix:** Track for the Phase 12 HTMX decommission; no action now.

### IN-03: `readCookie` returns `""` for a missing CSRF cookie, sending an empty `X-CSRF-Token`

**File:** `frontend/src/lib/http.ts:34-40, 51-53`
**Issue:** If the `telebot_csrf` cookie is absent on a mutation (cold start,
cookie expiry, or a third-party-cookie-blocking context), the wrapper sets
`X-CSRF-Token: ""`. The backend `compare_digest` correctly rejects this with a
403, so it is safe — but the empty-string header makes the failure mode
indistinguishable from "header missing" in logs and offers no client-side
early warning.
**Fix:** Optionally skip setting the header when the cookie is empty, or log a
dev-mode warning. Backend already fails closed, so this is cosmetic/diagnostic.

### IN-04: Deep-link test does not cover the missing-asset case behind CR-01

**File:** `tests/test_spa_serving.py:78-91`
**Issue:** The serving test covers `/app/`, a route deep-link (`/app/login`),
and API non-shadowing — but not a request for a missing asset
(e.g. `/app/assets/missing.js`), which is the exact gap CR-01 describes. The
current fallback would (incorrectly) return the HTML shell with 200 and the
test suite would not catch it.
**Fix:** After fixing CR-01, add a test asserting
`GET /app/assets/missing-abc.js` returns `404` (not `200 text/html`), to lock
in the asset/route distinction.

---

_Reviewed: 2026-06-06_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
