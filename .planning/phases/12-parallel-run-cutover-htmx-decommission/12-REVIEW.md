---
phase: 12-parallel-run-cutover-htmx-decommission
reviewed: 2026-06-08T00:00:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - dashboard.py
  - Dockerfile
  - nginx/telebot.conf
  - tests/test_api_csrf.py
  - tests/test_auth_session.py
  - tests/test_cutover_redirects.py
  - tests/test_post_teardown.py
findings:
  critical: 1
  warning: 4
  info: 3
  total: 8
status: issues_found
---

# Phase 12: Code Review Report

**Reviewed:** 2026-06-08T00:00:00Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Phase 12 cut the live-money dashboard from a legacy HTMX/Jinja UI to a pre-built
React SPA and decommissioned the HTMX stack. dashboard.py shrank from ~1486 to
543 lines. I verified the four CRITICAL invariants from the phase intent:

- **MUST-SURVIVE helpers — INTACT.** `validate_settings_form`, `_compute_dry_run`,
  `_enrich_stage_for_ui`, `_client_ip`, `_password_hasher`, `app_settings` are all
  present and correctly referenced by the deferred imports in api/auth.py,
  api/settings.py, api/stages.py, api/accounts.py, api/actions.py, api/deps.py. No
  dangling import.
- **Route precedence — CORRECT.** `app.include_router(api_router)` (dashboard.py:174)
  runs before `app.mount("/app", SpaStaticFiles(...))` (dashboard.py:197). /api/v2/*
  cannot be shadowed by the SPA mount.
- **_verify_auth repoint — CORRECT and functional.** The 303 → /app/login path works:
  even though api/errors.py installs a global HTTPException handler, its
  non-api-v2 branch (errors.py:51-57) re-emits a 303 JSONResponse WITH the Location
  header, so browsers still follow the redirect. `test_unauth_root_redirects_to_app_login`
  validly exercises this.
- **CSRF gate — INTACT.** test_api_csrf.py still proves the double-submit guard on
  /api/v2/auth/logout.

The work is largely sound, but there is **one BLOCKER**: two assertions in
`test_cutover_redirects.py` are now structurally impossible to pass because the
teardown DELETED the legacy page routes rather than converting them to redirects.
The 12-03-SUMMARY's "pass-or-skip" claim is an artifact of Postgres being absent
locally — when Postgres is present (the real go-live gate), these assertions FAIL.
A nginx rate-limit and a dead auth branch round out the warnings.

## Critical Issues

### CR-01: `test_cutover_redirects.py` asserts 303 for routes that teardown DELETED — hollow gate that fails when Postgres is present

**File:** `tests/test_cutover_redirects.py:54-63` and `tests/test_cutover_redirects.py:66-75`
**Issue:**
This file was created in Wave-0 (commit b7e9a88) as a *per-page progress guard*:
its premise (file docstring + Plan 12-02) is that each legacy GET page route would
be **converted in place** to `RedirectResponse(url="/app/<page>", status_code=303)`.
But the 12-03 teardown **deleted** those routes entirely. The only app-level routes
remaining are `/health`, `/logout`, and `/` (verified — no catch-all `{path}` route
exists). Therefore:

- `test_legacy_page_redirects_to_spa` GETs `/analytics`, `/signals`, `/history`,
  `/staged`, `/overview`, `/settings`, `/positions` and asserts `status_code == 303`
  with `location == /app/<page>`. Every one now returns a Starlette **404** (no
  matching route), so all 7 parametrized rows FAIL.
- `test_unauth_redirects_to_app_login` GETs `/positions` expecting `303` →
  `/app/login`. Because `/positions` has no route, Starlette returns **404 before
  `_verify_auth` ever runs** — so this asserts 303 but gets 404 and FAILS.

The 12-03-SUMMARY (line 139-142) reports "4 passed, 22 skipped … pass-or-skip"
ONLY because the `api_app` conftest fixture `pytest.skip`s when Postgres is absent
(it is, locally). In the real go-live CI where Postgres is present, this suite goes
RED. This is exactly the failure mode the adversarial review must surface: a green
local run masking a broken gate on a live-money control surface. Worse, the same
contradiction is enshrined as ground truth in test_post_teardown.py, which
*correctly* asserts `/overview` now returns 404 — the two files now make mutually
exclusive assertions about `/overview`.

**Fix:** Reconcile the test to the actual teardown decision. Since the routes were
deleted (not redirected), delete or rewrite `test_cutover_redirects.py` so it no
longer asserts 303 on deleted paths. If a cutover-redirect guard is still desired,
point it at a route that actually performs the redirect (only `/`), and drop the
7-row legacy-page parametrization, e.g.:

```python
# tests/test_cutover_redirects.py — replace test_legacy_page_redirects_to_spa
def test_root_redirects_to_app_login_when_unauth(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/app/login?next=")
```

and delete `test_unauth_redirects_to_app_login` (its `/positions` premise is gone —
the equivalent surviving-route assertion already lives in test_post_teardown.py).
Then re-run the suite **against a live Postgres** to prove the gate is green, not
skipped.

## Warnings

### WR-01: nginx login rate-limit now protects a deleted endpoint; the real login route `/api/v2/auth/login` is unthrottled at the proxy

**File:** `nginx/telebot.conf:36-45`
**Issue:**
`location = /login` (exact match) applies `limit_req zone=telebot_login` — the
AUTH-05 / D-18 belt-and-suspenders brute-force defense. But Phase 12 deleted the
legacy `/login` route; the live login endpoint is now `/api/v2/auth/login`, which
matches `location /` (line 47) and has **no rate limit**. The nginx-layer
protection described in the comment now defends a 404 path while the real
credential endpoint is exposed to unthrottled attempts at the proxy. The
application-layer guard (api/auth.py: `get_failed_login_count >= 5 → 429`) still
exists, so this is a defense-in-depth regression, not a total bypass — hence
WARNING, not BLOCKER. On a live-money control surface the layered defense is worth
restoring.

**Fix:** Repoint the rate-limited location at the real endpoint:

```nginx
location = /api/v2/auth/login {
    limit_req zone=telebot_login burst=5 nodelay;
    limit_req_status 429;
    proxy_pass http://telebot:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Delete the now-dead `location = /login` block.

### WR-02: dead `hx-request` branch in `_verify_auth` after HTMX decommission

**File:** `dashboard.py:96`
**Issue:**
`if request.headers.get("hx-request") or request.url.path.startswith("/api/"):`
The `hx-request` header is an HTMX artifact. Phase 12's stated goal is to fully
decommission the HTMX stack, and no surviving route is HTMX-driven. The branch is
now dead for its original purpose. It is harmless (it only short-circuits to a 401
when an `hx-request` header is present, which the SPA never sends), but leaving HTMX
references in the auth path contradicts the teardown's intent and invites confusion
about whether HTMX is truly gone. Note that `_verify_auth` is now only consumed by
the `/` route (verified — only call site is dashboard.py:224), so the whole helper
is borderline over-engineered for a single redirect.

**Fix:** Drop the HTMX clause; key the API-vs-page distinction on the path alone:

```python
if request.url.path.startswith("/api/"):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
```

### WR-03: `_get_all_positions` last-good cache is never cleared on a real empty result, contradicting its own docstring

**File:** `dashboard.py:471-486`
**Issue:**
The module-level comment (lines 45-50) and the function docstring (lines 437-442)
both promise: "Only a successful fetch that returns zero positions counts as
'really empty' and clears the cache." But the success branch unconditionally does
`_last_positions_by_account[acct_name] = acct_positions`. When `result` is an empty
list, `acct_positions` is `[]`, which is falsy — so a *later* failed tick hits
`cached = _last_positions_by_account.get(acct_name)` → `[]` → `if cached:` is False →
nothing extended. The net behavior happens to be correct (an empty cache yields no
stale rows), so this is not a data bug. However, the code does not match its
documented "clears the cache explicitly" contract; a future edit that changes the
`if cached:` truthiness check (e.g. `if cached is not None:`) would silently
resurrect a real-zero state as stale positions on a live trading view. Tighten the
code to the contract.

**Fix:** Make the clear explicit so the invariant survives future edits:

```python
if not acct_positions:
    _last_positions_by_account.pop(acct_name, None)  # real zero-position state
else:
    _last_positions_by_account[acct_name] = acct_positions
positions.extend(acct_positions)
```

### WR-04: `test_valid_session_passes_auth` is an unconditional `pytest.skip` — the auth happy-path has zero coverage in this file

**File:** `tests/test_auth_session.py:46-55`
**Issue:**
The test that should prove a valid session actually passes `_verify_auth` does
nothing but `pytest.skip(...)`. The skip message defers coverage to "Plan 04's
/login integration test," but this file is the named home of the
`_verify_auth + SessionMiddleware integration` (per its module docstring). On a
live-money surface, the positive auth path (valid session → access granted) is the
single most important auth assertion and it is untested here. A skipped test reads
as "covered" in the count but proves nothing. This is a coverage gap, not a code
bug — WARNING.

**Fix:** Implement the happy path using SessionMiddleware directly (sign a session
cookie via a throwaway TestClient route, or use Starlette's session test helper) so
the assertion actually executes, or delete the placeholder and rely on a named,
verifiable test elsewhere rather than a perpetual skip.

## Info

### IN-01: `_enrich_stage_for_ui` "pips to next band" sign for the already-past-band case is display-cosmetic but inconsistent

**File:** `dashboard.py:280-288`
**Issue:**
When price is already past the trigger band (the `else` at line 285-288), the sign
is flipped relative to the approaching case (buy → "−", sell → "+"), labeled "to
next band." For a buy that has crossed `band_high`, showing "−X pips to next band"
is semantically odd (it has already passed, not approaching). This is display-only
text in a modal sub-line, no trade logic depends on it, and `current_price` is
currently always `None` in practice (the docstring at lines 256-257 notes no
live-price field is carried), so this branch is effectively unreachable today.
Cosmetic.

**Fix:** When past the band, label it explicitly (e.g. "past band by X pips") rather
than reusing "to next band," once a live-price source is wired.

### IN-02: Dockerfile `COPY *.py *.json ./` bakes `accounts.json` into the runtime image layer

**File:** `Dockerfile:22`
**Issue:**
`COPY *.py *.json ./` copies `accounts.json` (account roster: name/server/login,
risk caps) into the image. Verified that `accounts.json` is **gitignored** and uses
`password_env` references rather than raw passwords, so no credential is leaked into
the image. This is a pre-existing pattern (not introduced by Phase 12) and stores no
secrets, so it is informational only. Worth noting that account login IDs and broker
servers are still embedded in the published image layer.

**Fix:** If account topology is considered sensitive, mount `accounts.json` at
runtime (volume / secret) instead of `COPY`-ing it into the layer. No action needed
for Phase 12.

### IN-03: SPA shell fallback in `SpaStaticFiles.get_response` returns the shell with a 200 for any extensionless missing path, including unknown deep links

**File:** `dashboard.py:160-163`
**Issue:**
The fallback serves `index.html` for any 404 whose path is not under `assets/` and
has no file suffix. This is the intended deep-link behavior, but it means a typo'd
client route under `/app/` (e.g. `/app/positons`) returns the SPA shell with 200
rather than a 404 — the router then renders its in-app not-found. This is the
standard, acceptable SPA tradeoff (the asset-vs-route guard at line 160 correctly
keeps missing assets as real 404s, which is the genuinely dangerous case and is
handled well). Noted for completeness; no change recommended.

---

_Reviewed: 2026-06-08T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
