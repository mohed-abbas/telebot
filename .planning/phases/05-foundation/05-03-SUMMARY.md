---
phase: 05-foundation
plan: 03
subsystem: auth-backend
tags: [phase-5, auth-backend, session, argon2, config, startup-validation, dashboard]

# Dependency graph
requires:
  - phase: 05-foundation plan 02
    provides: vendored Basecoat + Tailwind build + content-hashed `app.<hash>.css` + manifest.json
provides:
  - argon2-cffi runtime dependency (password hashing)
  - itsdangerous runtime dependency (SessionMiddleware signing, transitive)
  - Config fail-fast on misconfiguration (SESSION_SECRET entropy, DASHBOARD_PASS_HASH presence, DASHBOARD_PASS plaintext purge)
  - Starlette SessionMiddleware wired with 30-day cookie, SameSite=Lax, config-driven https_only
  - Session-based `_verify_auth` dependency (signature preserved: returns str) that 303s to /login for pages and 401s for HTMX/API on missing session
  - `asset_url()` Jinja global that resolves logical CSS name via manifest.json
  - `scripts/hash_password.py` operator CLI
affects: [05-04 login UI + /login + /logout + CSRF + rate-limit]

# Tech tracking
tech-stack:
  added:
    - argon2-cffi@25.1.0 (runtime)
    - itsdangerous@2.2.0 (runtime, transitive — SessionMiddleware)
  patterns:
    - Startup fail-fast validators raise SystemExit on misconfiguration (D-15, D-20/D-21, Pitfall 5)
    - Session dependency reads `request.session.get('user')` and returns str so existing `Depends(_verify_auth)` call sites require zero edits (Pitfall 11)
    - Jinja global asset_url() loads manifest.json once at module import; dev-mode fallback to logical name
    - DASHBOARD_USER silently ignored (D-22 — harmless legacy)

key-files:
  created:
    - scripts/hash_password.py
    - tests/test_config.py
    - tests/test_auth_session.py
  modified:
    - requirements.txt
    - config.py
    - .env.example
    - dashboard.py
    - templates/base.html

key-decisions:
  - "itsdangerous==2.2.0 added to requirements.txt as Rule 3 deviation — Starlette's SessionMiddleware imports it at module load time; was not transitively pulled by fastapi==0.115.0 in this venv"
  - "hash_password.py hardcodes 12-char min (plan spec); not enforcing Argon2id params beyond library defaults (PasswordHasher() uses m=65536, t=3, p=4 → ≈97-char encoded hash)"
  - "asset_url() falls back to logical name rather than erroring when manifest.json absent — preserves dev workflow before first `scripts/build_css.sh` run (same contract as Plan 02)"

patterns-established:
  - "SessionMiddleware registered at module import, before lifespan — required because middleware must be in the stack before first request"
  - "_verify_auth branches on `HX-Request` header OR `/api/` path prefix for 401 vs 303 — HTMX partials get inline error, page loads get redirect"

requirements-completed: [AUTH-02, AUTH-03]

# Metrics
duration: ~15 min (including TDD RED/GREEN for both tasks + itsdangerous deviation handling)
completed: 2026-04-19
---

# Phase 5 Plan 03: Auth-Backend Cutover Summary

**argon2 + config fail-fast + SessionMiddleware + session-based _verify_auth + asset_url helper — bot refuses to start on misconfiguration; every authenticated route returns 303→/login on missing cookie; hashed CSS wired via manifest.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-19T15:00:00Z
- **Completed:** 2026-04-19T15:15:00Z
- **Tasks:** 2 (both TDD)
- **TDD gates:** RED→GREEN×2 (4 commits) + no REFACTOR needed
- **Files changed:** 8 (3 created, 5 modified)

## Task Commits

| Task | Gate | Commit | Message (truncated) |
|------|------|--------|---------------------|
| 1    | RED  | `a0da15f` | test(05-03): add failing tests for config fail-fast validators |
| 1    | GREEN | `ff7ef88` | feat(05-03): argon2-cffi pin + config fail-fast + hash_password CLI + .env.example cutover |
| 2    | RED  | `5208612` | test(05-03): add failing tests for SessionMiddleware + session-based _verify_auth + asset_url |
| 2    | GREEN | `a62fdea` | feat(05-03): SessionMiddleware + session-based _verify_auth + asset_url helper + base.html cutover |

## Accomplishments

### Task 1 — argon2 + config fail-fast + hash_password CLI + .env.example
- `requirements.txt`: pinned `argon2-cffi==25.1.0`
- `config.py` Settings dataclass:
  - Removed `dashboard_user: str`, `dashboard_pass: str`
  - Added `session_secret: str`, `dashboard_pass_hash: str`, `session_cookie_secure: bool`
- `config.py` validators:
  - `_require_session_secret()`: tries base64-decode first, falls back to UTF-8 byte length; SystemExit when `<32 bytes` (Pitfall 5 — bytes not chars)
  - `_require_dashboard_hash()`: SystemExit on `DASHBOARD_PASS` present (D-21 hard cutover) or `DASHBOARD_PASS_HASH` missing/<60 chars
  - `DASHBOARD_USER` silently ignored (D-22)
- `scripts/hash_password.py`: prompts twice via `getpass`, enforces `≥12 chars`, prints `DASHBOARD_PASS_HASH=$argon2id...` on stdout (chmod +x)
- `.env.example`: removed `DASHBOARD_USER` + `DASHBOARD_PASS`; added `DASHBOARD_PASS_HASH`, `SESSION_SECRET`, `SESSION_COOKIE_SECURE`

### Task 2 — SessionMiddleware + _verify_auth swap + asset_url + base.html
- `dashboard.py`:
  - Removed `from fastapi.security import HTTPBasic, HTTPBasicCredentials` + `security = HTTPBasic()` + `import secrets` (no longer needed for compare_digest)
  - Added `from starlette.middleware.sessions import SessionMiddleware`, `from urllib.parse import quote`, `from config import settings as app_settings`
  - Registered `SessionMiddleware` at module top (after `app = FastAPI(...)`)
  - Swapped `_verify_auth` body to session-cookie variant (verbatim from RESEARCH Example 4)
  - Added `asset_url()` Jinja global + `_load_manifest()` + registration on `templates.env.globals`
- `templates/base.html`: removed Tailwind Play CDN script, inline tailwind.config, and entire inline `<style>` block; added `<link rel=stylesheet href="{{ asset_url('app.css') }}">`, Basecoat defer, HTMX-Basecoat bridge defer
- All 18 `Depends(_verify_auth)` call sites preserved with zero edits (confirmed by grep count)

## Config.py Diff Snippet (before → after)

```diff
     # ── Dashboard ──
     dashboard_enabled: bool
     dashboard_port: int
-    dashboard_user: str
-    dashboard_pass: str
+    session_secret: str
+    dashboard_pass_hash: str
+    session_cookie_secure: bool
```

```diff
         dashboard_enabled=_opt("DASHBOARD_ENABLED", "true").lower() in ("true", "1", "yes"),
         dashboard_port=int(_opt("DASHBOARD_PORT", "8080")),
-        dashboard_user=_opt("DASHBOARD_USER", "admin"),
-        dashboard_pass=_req("DASHBOARD_PASS"),
+        session_secret=_require_session_secret(environ.get("SESSION_SECRET")),
+        dashboard_pass_hash=_require_dashboard_hash(),
+        session_cookie_secure=_opt("SESSION_COOKIE_SECURE", "true").lower() in ("true", "1", "yes"),
```

New validators added inside `_load_settings()`:

```python
def _require_session_secret(val: str | None) -> str:
    """D-15 / Pitfall 5: >=32 BYTES of entropy."""
    if not val:
        raise SystemExit("FATAL: Missing SESSION_SECRET. Generate one with:\n  openssl rand -base64 48\nor: python -c 'import secrets; print(secrets.token_urlsafe(48))'")
    byte_len = 0
    try:
        import base64
        byte_len = len(base64.b64decode(val, validate=False))
    except Exception:
        pass
    if byte_len < 32:
        byte_len = len(val.encode("utf-8"))
    if byte_len < 32:
        raise SystemExit(f"FATAL: SESSION_SECRET has only {byte_len} bytes of entropy; need >=32. Use: openssl rand -base64 48")
    return val

def _require_dashboard_hash() -> str:
    """D-20/D-21: hard cutover. No fallback to plaintext."""
    if environ.get("DASHBOARD_PASS"):
        raise SystemExit("FATAL: DASHBOARD_PASS plaintext env var detected. Remove it from .env and set DASHBOARD_PASS_HASH via scripts/hash_password.py (see VPS_DEPLOYMENT_GUIDE.md).")
    h = environ.get("DASHBOARD_PASS_HASH", "")
    if len(h) < 60:
        raise SystemExit("FATAL: DASHBOARD_PASS_HASH missing or malformed. Generate via: python scripts/hash_password.py")
    return h
```

## SessionMiddleware Config Block

```python
app.add_middleware(
    SessionMiddleware,
    secret_key=app_settings.session_secret,
    session_cookie="telebot_session",
    max_age=30 * 24 * 60 * 60,        # 30 days (D-11)
    same_site="lax",
    https_only=app_settings.session_cookie_secure,
    path="/",
)
```

## asset_url Helper Signature

```python
def asset_url(logical_name: str) -> str:
    """Jinja global: resolves logical css name to hashed filename via manifest.
    Falls back to the logical name if manifest missing (dev workflow)."""
    hashed = _asset_manifest.get(logical_name, logical_name)
    return f"/static/css/{hashed}"

templates.env.globals["asset_url"] = asset_url
```

`_load_manifest()` runs at module import; `manifest.json` read once from `BASE_DIR / "static" / "css" / "manifest.json"`. Absent manifest → empty dict → fallback to logical name (dev workflow).

## 18 `Depends(_verify_auth)` Call Sites — Confirmed Unchanged

Grep count before plan (git HEAD~3) = 18; after plan = 18. Every call site is `user: str = Depends(_verify_auth)` or `user: str = Depends(_verify_auth), _csrf=Depends(_verify_csrf)`. Full list (line numbers post-Task-2):

| # | Line | Route |
|---|------|-------|
|  1 | 152 | `@app.get("/")` → root |
|  2 | 157 | `@app.get("/overview")` → overview |
|  3 | 170 | `@app.get("/positions")` → positions_page |
|  4 | 180 | `@app.get("/history")` → history_page |
|  5 | 190 | `@app.get("/signals")` → signals_page |
|  6 | 200 | `@app.get("/settings")` → settings_page |
|  7 | 212 | `@app.get("/analytics")` → analytics_page |
|  8 | 229 | `@app.get("/partials/positions")` |
|  9 | 238 | `@app.get("/partials/overview")` |
| 10 | 254 | `@app.post("/api/close/{account_name}/{ticket}")` |
| 11 | 278 | `@app.post("/api/modify-sl/{account_name}/{ticket}")` |
| 12 | 302 | `@app.post("/api/modify-tp/{account_name}/{ticket}")` |
| 13 | 326 | `@app.post("/api/close-partial/{account_name}/{ticket}")` |
| 14 | 359 | `@app.get("/api/emergency-preview")` |
| 15 | 386 | `@app.post("/api/emergency-close")` |
| 16 | 398 | `@app.post("/api/resume-trading")` |
| 17 | 410 | `@app.get("/api/trading-status")` |
| 18 | 424 | `@app.get("/stream")` |

Signature preservation works because FastAPI auto-resolves `Request` via the dependency system. The callers did not need to be edited.

## Exact Lines Removed from `templates/base.html`

```html
    <script src="https://cdn.tailwindcss.com"></script>                         <!-- UI-01 Play CDN -->
    <script>                                                                    <!-- inline tailwind.config -->
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        dark: { 800: '#1a1a2e', 900: '#0f0f1a', 700: '#252542' }
                    }
                }
            }
        }
    </script>
    <style>                                                                     <!-- full inline style block -->
        body { background: #0f0f1a; color: #e2e8f0; }
        .nav-active { background: #252542; border-left: 3px solid #818cf8; }
        .card { background: #1a1a2e; border: 1px solid #252542; border-radius: 0.75rem; }
        .profit { color: #4ade80; }
        .loss { color: #f87171; }
        .badge-buy { background: #065f46; color: #6ee7b7; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; }
        .badge-sell { background: #7f1d1d; color: #fca5a5; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; }
        .badge-connected { background: #065f46; color: #6ee7b7; }
        .badge-disconnected { background: #7f1d1d; color: #fca5a5; }
        table { width: 100%; }
        th { text-align: left; padding: 0.75rem; color: #94a3b8; font-weight: 600; font-size: 0.75rem; text-transform: uppercase; border-bottom: 1px solid #252542; }
        td { padding: 0.75rem; border-bottom: 1px solid #1e1e35; font-size: 0.875rem; }
        .btn { padding: 0.375rem 0.75rem; border-radius: 0.375rem; font-size: 0.75rem; font-weight: 500; cursor: pointer; transition: opacity 0.15s; }
        .btn:hover { opacity: 0.85; }
        .btn-red { background: #991b1b; color: #fca5a5; }
        .btn-blue { background: #1e3a5f; color: #93c5fd; }
        .btn-green { background: #065f46; color: #6ee7b7; }
        input[type="number"] { background: #252542; border: 1px solid #374151; color: #e2e8f0; padding: 0.25rem 0.5rem; border-radius: 0.25rem; width: 5rem; font-size: 0.75rem; }
    </style>
```

Replaced by:

```html
    <link rel="stylesheet" href="{{ asset_url('app.css') }}">
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <script defer src="/static/vendor/basecoat/basecoat.min.js"></script>
    <script defer src="/static/js/htmx_basecoat_bridge.js"></script>
```

Note: HTMX `<script>` kept as-is per plan (no change to HTMX loading in this plan).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking dependency] Added `itsdangerous==2.2.0` to requirements.txt**
- **Found during:** Task 2 GREEN (running `tests/test_auth_session.py`)
- **Issue:** `from starlette.middleware.sessions import SessionMiddleware` failed with `ModuleNotFoundError: No module named 'itsdangerous'`. It is an optional transitive dependency of Starlette (used for signed session cookies) not pulled by `fastapi==0.115.0` in this venv.
- **Fix:** `pip install itsdangerous==2.2.0` + pinned in `requirements.txt`.
- **Files modified:** `requirements.txt` (one-line add)
- **Commit:** `a62fdea` (folded into Task 2 GREEN)

**2. [Rule 1 — Test hygiene] Fixed cross-test env pollution in `tests/test_config.py::_reload_config`**
- **Found during:** Task 2 GREEN (running both test files together)
- **Issue:** `tests/test_auth_session.py` fixture sets `SESSION_COOKIE_SECURE=false` in `os.environ` and never clears it. When `test_session_cookie_secure_defaults_true` ran after, the stale `false` leaked in (not in `_reload_config`'s clear list) and the default-to-`True` test failed.
- **Fix:** Added `"SESSION_COOKIE_SECURE"` to the explicit clear-list tuple in `_reload_config`.
- **Files modified:** `tests/test_config.py` (one-line add)
- **Commit:** `a62fdea` (folded into Task 2 GREEN)

### Scope-boundary deferrals

29 pre-existing test failures in DB-dependent suites (`test_seed_accounts`, `test_settings`, `test_settings_store`, `test_trade_manager*`, `test_rest_api*`) reproduced without any of this plan's changes (verified via `git stash` + re-run). Logged to `.planning/phases/05-foundation/deferred-items.md`. **Out of scope for Plan 05-03** — argon2/SessionMiddleware cutover does not touch these code paths. No Postgres service was running at `postgresql://telebot:telebot_dev@localhost:5433/telebot`.

## Plan 04 Handoff Contract

Plan 04 (`/login` + `/logout` + CSRF + rate-limit) consumes this plan's output. The **only** write Plan 04 needs into the session is:

```python
request.session["user"] = "admin"  # value comes from verified argon2 hash match
```

and

```python
request.session.clear()  # for /logout
```

Once `request.session["user"]` is set, every existing `Depends(_verify_auth)` endpoint in `dashboard.py` works without further edits (no call-site changes, no new middleware). The argon2 verification loop in Plan 04 must read `app_settings.dashboard_pass_hash` and pass it to `PasswordHasher().verify(hash, plaintext)` — import path: `from argon2 import PasswordHasher`.

Test infrastructure handoff: `tests/test_auth_session.py::test_valid_session_passes_auth` is pytest-skipped with a message pointing to Plan 04. Plan 04 should either un-skip it (once `/login` exists to forge a signed cookie) or supersede it with a happy-path integration test.

## Verification Results

- `pytest tests/test_config.py tests/test_auth_session.py -x --tb=short` → **14 passed, 1 skipped** (plan-documented skip)
- All 12 acceptance criteria for Task 1 met
- All 13 acceptance criteria for Task 2 met
- `python -c "import dashboard"` with valid env → exits 0
- `python scripts/hash_password.py` (piped two-matching-password input) → prints valid `DASHBOARD_PASS_HASH=$argon2id...`
- 18 `Depends(_verify_auth)` call sites preserved (baseline match)
- `grep -c HTTPBasic dashboard.py` → 0
- `grep -c "cdn.tailwindcss.com" templates/base.html` → 0

## Issues Encountered

- `itsdangerous` missing — surfaced as `ModuleNotFoundError` at dashboard import time. Handled as Rule 3 auto-fix (dependency add).
- Cross-test env pollution between `test_auth_session.py` fixture and `test_config.py::test_session_cookie_secure_defaults_true`. Handled as Rule 1 auto-fix (explicit clear-list extension).
- `pytest` full run surfaced 29 pre-existing DB-dependent failures unrelated to this plan. Logged to `deferred-items.md`.

## User Setup Required

Operators deploying this cutover must:

1. Generate an Argon2 hash: `python scripts/hash_password.py` (prompted twice, prints one stdout line).
2. Copy the `DASHBOARD_PASS_HASH=$argon2id...` value into `.env`.
3. Generate a session secret: `openssl rand -base64 48`; set as `SESSION_SECRET=...` in `.env`.
4. Remove any legacy `DASHBOARD_PASS=...` line from `.env` (bot will SystemExit otherwise — D-21).
5. `pip install -r requirements.txt` (picks up `argon2-cffi==25.1.0` + `itsdangerous==2.2.0`).
6. For local HTTP dev or pytest, set `SESSION_COOKIE_SECURE=false`. Production defaults to `true`.

## Next Plan Readiness

- Plan 04 can now land `/login` + `/logout` + CSRF + rate-limit against the live `SessionMiddleware` + session-based `_verify_auth`.
- The session-write contract is one line: `request.session["user"] = <username>`.
- Argon2 verification helper is already importable: `from argon2 import PasswordHasher`.
- The session-happy-path integration test skeleton exists (`test_valid_session_passes_auth`) ready to be un-skipped in Plan 04.

## Self-Check: PASSED

All artifacts verified on disk:

- `requirements.txt` → `argon2-cffi==25.1.0` + `itsdangerous==2.2.0` present
- `config.py` → `_require_session_secret`, `_require_dashboard_hash` both present; `dashboard_user`/`dashboard_pass` fields removed
- `scripts/hash_password.py` → executable, contains `PasswordHasher`
- `.env.example` → `DASHBOARD_PASS_HASH` + `SESSION_SECRET` + `SESSION_COOKIE_SECURE` present; `DASHBOARD_PASS=` (plaintext) absent
- `dashboard.py` → `SessionMiddleware` imported + registered; `HTTPBasic` fully removed; 18 `Depends(_verify_auth)` call sites preserved
- `templates/base.html` → `cdn.tailwindcss.com` absent; `asset_url('app.css')`, `basecoat.min.js`, `htmx_basecoat_bridge.js` all present
- Commits verified in `git log`: `a0da15f`, `ff7ef88`, `5208612`, `a62fdea`

---
*Phase: 05-foundation*
*Plan: 03*
*Completed: 2026-04-19*
