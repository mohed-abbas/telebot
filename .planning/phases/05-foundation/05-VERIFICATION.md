---
phase: 05-foundation
verified: 2026-04-19T12:00:00Z
status: gaps_found
score: 14/15 requirements verified
overrides_applied: 0
gaps:
  - truth: "Operator can log out from any page"
    status: failed
    reason: "No logout link or button exists in base.html or any other template. The /logout endpoint is implemented and functional, but there is no UI affordance — the operator must manually type /logout in the browser. ROADMAP SC#3 specifically states 'from any page'."
    artifacts:
      - path: "templates/base.html"
        issue: "Sidebar nav has no logout link"
    missing:
      - "Add a logout link/button to the sidebar in templates/base.html"
deferred:
  - truth: "Settings read by an in-flight staged-entry sequence are snapshotted at signal receipt; later edits do not mutate already-enqueued stages"
    addressed_in: "Phase 6"
    evidence: "Phase 6 goal: 'A text-only Gold buy now signal opens exactly one protected position immediately ... staged entry execution'. Phase 6 requirements include STAGE-01..09, SET-03. AccountSettings frozen+slots=True and SettingsStore.snapshot() exist — the infrastructure Phase 6 depends on is ready; actual snapshotting at signal receipt is Phase 6 work."
---

# Phase 5: Foundation Verification Report

**Phase Goal:** Operator can log in through a styled form, per-account runtime settings exist in the database with an audit trail, and every dashboard page is served from a production-grade Tailwind build with Basecoat primitives ready for later phases.
**Verified:** 2026-04-19T12:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### ROADMAP Success Criteria

| # | Success Criterion | Status | Evidence |
|---|-------------------|--------|---------|
| 1 | Dashboard serves its own CSS — no `cdn.tailwindcss.com` script in production HTML; stylesheet is a content-hashed file built from the standalone Tailwind CLI and Basecoat is vendored under `static/` | VERIFIED | grep over templates returns no CDN Tailwind; Dockerfile has 2-stage build with Tailwind v3.4.19 CLI; `static/vendor/basecoat/basecoat.css` (42 374 bytes) and `basecoat.min.js` (15 682 bytes) confirmed present; `test_ui_substrate.py` PASSES |
| 2 | Operator lands on a styled `/login` page (not a browser HTTPBasic prompt), authenticates with a password verified against an argon2 hash, and remains signed in across tabs and browser restarts via a signed session cookie | VERIFIED | `/login` GET/POST routes implemented in `dashboard.py`; `login.html` extends `base.html` and uses Basecoat primitives (`.card`, `.card-header`, `.card-body`, `.input`, `.btn`, `.alert`); `PasswordHasher().verify()` used; `SessionMiddleware` registered (30-day cookie); `test_auth_session.py` 6 tests PASS; HTTPBasic fully removed (grep returns 0 hits) |
| 3 | Operator can log out **from any page** and is rate-limited after repeated failed attempts; bot refuses to start if `SESSION_SECRET` is missing or below the required entropy | FAILED (partial) | `/logout` endpoint exists and clears session + 303-redirects; rate-limit implemented (5 failures/15 min per IP via `failed_login_attempts` + nginx `limit_req`); `SESSION_SECRET` fail-fast validator in `config.py` with entropy check (`>=32 bytes`); BUT **no logout link exists in any template** — operator cannot log out from any page via UI |
| 4 | `account_settings` rows exist for every account in `accounts.json` on first boot, DB overrides supersede static JSON at lookup time, and every settings write produces an audit-log entry | VERIFIED | `bot.py` idempotent seed loop: `db.upsert_account_if_missing()` → `db.upsert_account_settings_if_missing()`; `_effective()` in `trade_manager.py` prefers `settings_store.effective(acct.name)` over `AccountConfig`; `db.update_account_setting()` uses a transaction that inserts audit row BEFORE updating, capturing old_value → new_value, actor, timestamp |
| 5 | Basecoat interactive components stay functional after HTMX partial swaps; no class names used by Python-side HTMX fragments are purged from the built CSS | VERIFIED | `htmx_basecoat_bridge.js` installs `htmx:afterSwap → basecoat.initAll()` listener; `tailwind.config.js` content glob includes `./**/*.py` (Pitfall 10 mitigation); `text-green-400` and `text-red-400` safelisted for `dashboard.py` inline HTMLResponse fragments; `test_ui_substrate.py` PASSES all substrate checks |

**Score: 4/5 success criteria verified** (SC#3 partially failed on logout UI affordance)

### Observable Truths — 15 Requirements

| # | Requirement | Truth | Status | Evidence |
|---|-------------|-------|--------|---------|
| 1 | UI-01 | Tailwind Play CDN removed; CSS built from standalone CLI at Docker build time | VERIFIED | No CDN script in any template; Dockerfile `AS css-build` with Tailwind v3.4.19; `test_base_html_has_no_play_cdn` PASSES |
| 2 | UI-02 | Basecoat vendored under `static/vendor/basecoat/` | VERIFIED | Both files confirmed on disk at expected sizes; referenced from `base.html:9` |
| 3 | UI-03 | Tailwind content globs include `*.py` | VERIFIED | `tailwind.config.js:5` `./**/*.py` glob present; `test_tailwind_content_glob_includes_python` PASSES |
| 4 | UI-04 | CSS asset deployed with content-hashed filename | VERIFIED | `scripts/build_css.sh` emits `app.{sha256[0:12]}.css` + `manifest.json`; `asset_url()` resolves via manifest; Dockerfile copies hashed CSS; `test_dockerfile_has_tailwind_build_stage` PASSES |
| 5 | UI-05 | Basecoat JS re-initializes after HTMX swaps | VERIFIED | `static/js/htmx_basecoat_bridge.js` wired `htmx:afterSwap → basecoat.initAll()`; `test_htmx_bridge_installed` PASSES |
| 6 | AUTH-01 | Dashboard gated by styled login form replacing HTTPBasic on all existing protected routes | VERIFIED | `/login` returns `TemplateResponse("login.html", ...)`; 19 `Depends(_verify_auth)` call sites; HTTPBasic grep returns 0; `test_auth_session.py` PASSES |
| 7 | AUTH-02 | Passwords verified against argon2 hash; plaintext `DASHBOARD_PASS` migrated and rejected | VERIFIED | `argon2-cffi==25.1.0` in `requirements.txt`; `_password_hasher.verify()` in POST /login; `config.py` raises `SystemExit` if `DASHBOARD_PASS` env var present; `test_plaintext_dashboard_pass_refuses_boot` PASSES |
| 8 | AUTH-03 | Sessions use `SessionMiddleware` with `SESSION_SECRET`; bot refuses to start below 32 bytes entropy | VERIFIED | `app.add_middleware(SessionMiddleware, secret_key=app_settings.session_secret, ...)` confirmed; `_require_session_secret()` validates byte length; `test_session_secret_missing_raises` + `test_session_secret_too_weak_raises` PASS |
| 9 | AUTH-04 | Login POST CSRF-protected via double-submit cookie; HTMX routes use header-based CSRF | VERIFIED | `CSRF_COOKIE = "telebot_login_csrf"` set on GET /login (path=/login, httponly, samesite=lax); POST /login checks `_secrets.compare_digest(cookie_token, csrf_token)`; existing HTMX routes use `_verify_csrf` (HX-Request header check) |
| 10 | AUTH-05 | Login has per-IP rate limiting with constant-time credential comparison | VERIFIED | `db.get_failed_login_count(ip, minutes=15)` checked before argon2; argon2 uses constant-time comparison by design; `_client_ip()` prefers `X-Real-IP`; nginx `limit_req zone=telebot_login burst=5 nodelay`; `limit_req_zone ... rate=10r/m` in `limit_req_zones.conf` |
| 11 | AUTH-06 | Logout clears session and redirects to /login | PARTIAL | Endpoint `request.session.clear()` + 303 → `/login` implemented and confirmed; **no UI link to logout exists in any template** — the requirement's letter is met (endpoint) but the ROADMAP SC spirit ("from any page") is not |
| 12 | SET-01 | Per-account settings persisted in DB, editable at runtime, supersede accounts.json | VERIFIED | `account_settings` table created; `SettingsStore.effective()` used by `_effective()` in `trade_manager.py`; `db.update_account_setting()` write-through path wired |
| 13 | SET-02 | Settings include `risk_mode`, `risk_value`, `max_stages`, `default_sl_pips`, `max_daily_trades` | VERIFIED | `_ACCOUNT_SETTINGS_FIELDS = frozenset({"risk_mode", "risk_value", "max_stages", "default_sl_pips", "max_daily_trades"})` confirmed; `AccountSettings` dataclass has all 5 fields plus convenience fields |
| 14 | SET-04 | Settings changes recorded in audit log (timestamp, field, old→new, actor) | VERIFIED | `db.update_account_setting()` uses a transaction: `INSERT INTO settings_audit (account_name, field, old_value, new_value, actor)` BEFORE UPDATE; `settings_audit` table has `created index idx_settings_audit_account_ts` |
| 15 | SET-05 | Settings snapshotted at signal receipt; later edits do not mutate enqueued stages | DEFERRED | `AccountSettings` is `frozen=True, slots=True`; `SettingsStore.snapshot()` returns `dataclasses.replace(effective(name))`; infrastructure ready; **actual snapshot-at-signal-receipt is Phase 6 work** (staged entry executor does not exist yet) |

**Score: 14/15 requirements** (1 gap: AUTH-06 logout UI; 1 deferred: SET-05 consumption; 13 fully verified)

---

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `db.py` | VERIFIED | 8 tables created via DDL (signals, trades, daily_stats, pending_orders, accounts, account_settings, settings_audit, failed_login_attempts); all required helpers present: `upsert_account_if_missing`, `upsert_account_settings_if_missing`, `get_failed_login_count`, `log_failed_login`, `clear_failed_logins`, `update_account_setting` with audit |
| `settings_store.py` | VERIFIED | `SettingsStore` class with `load_all()`, `effective()`, `snapshot()`, `update()`, `reload()`; uses JOIN query over account_settings + accounts |
| `models.py` | VERIFIED | `AccountSettings` with `frozen=True, slots=True`; 8 fields confirmed |
| `bot.py` | VERIFIED | Idempotent seed loop (lines 75–104); `SettingsStore` constructed and assigned to `tm.settings_store` |
| `trade_manager.py` | VERIFIED | `_effective(tm, acct)` at module level; called at lines 208, 252; `self.settings_store = None` default with `getattr` fallback |
| `config.py` | VERIFIED | `_require_session_secret()` (entropy check); `_require_dashboard_hash()` (reject `DASHBOARD_PASS` plaintext, reject short hash); `session_secret`, `dashboard_pass_hash`, `session_cookie_secure` fields present |
| `dashboard.py` | VERIFIED | `SessionMiddleware` registered; `_verify_auth` session-based; `asset_url()` Jinja global; GET/POST `/login`; POST+GET `/logout`; 19 `Depends(_verify_auth)` call sites |
| `templates/base.html` | PARTIAL | No CDN Tailwind link; uses `{{ asset_url('app.css') }}`; loads vendored Basecoat JS + HTMX bridge; **no logout link in nav** |
| `templates/login.html` | VERIFIED | Extends base.html; Basecoat primitives (`.card`, `.card-header`, `.card-body`, `.input`, `.btn btn-primary`, `.alert.alert-destructive`); CSRF hidden field; `next_path` hidden field; no username field (password-only) |
| `static/vendor/basecoat/basecoat.css` | VERIFIED | 42 374 bytes |
| `static/vendor/basecoat/basecoat.min.js` | VERIFIED | 15 682 bytes; loaded in base.html as `/static/vendor/basecoat/basecoat.min.js` |
| `tailwind.config.js` | VERIFIED | `"./**/*.py"` content glob; dark palette; safelist for inline fragment classes |
| `static/css/input.css` | VERIFIED | Imports compat shim + Basecoat layers |
| `static/css/_compat.css` | VERIFIED | `.card`, `.btn`, `.btn-red/blue/green`, `.badge-*`, `.nav-active`, `.profit`, `.loss`, table/td/th + input[type=number] — all v1.0 classes covered via `@apply` |
| `scripts/build_css.sh` | VERIFIED | sha256 prefix + `manifest.json` emit; `set -euo pipefail` |
| `scripts/hash_password.py` | VERIFIED | Interactive `getpass`; enforces ≥12 char minimum; prints `DASHBOARD_PASS_HASH=...` |
| `static/js/htmx_basecoat_bridge.js` | VERIFIED | `htmx:afterSwap → basecoat.initAll()` listener |
| `Dockerfile` | VERIFIED | `AS css-build` stage with Tailwind v3.4.19; runtime stage copies hashed CSS + manifest via `COPY --from=css-build` |
| `nginx/telebot.conf` | VERIFIED | `location = /login { limit_req zone=telebot_login burst=5 nodelay; limit_req_status 429; proxy_set_header X-Real-IP $remote_addr; }` |
| `nginx/limit_req_zones.conf` | VERIFIED | `limit_req_zone $binary_remote_addr zone=telebot_login:10m rate=10r/m` |
| `VPS_DEPLOYMENT_GUIDE.md` | VERIFIED | Documents `DASHBOARD_PASS_HASH` generation via `scripts/hash_password.py`, `SESSION_SECRET` generation, cutover steps, hard-cutover behavior; checklist at lines 527–528 |
| `requirements.txt` | VERIFIED | `argon2-cffi==25.1.0`, `itsdangerous==2.2.0` (required by SessionMiddleware) both present |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `base.html` | `asset_url('app.css')` | Jinja global `asset_url` registered in `templates.env.globals` | WIRED | Confirmed at dashboard.py:68; test_asset_url_helper_registered PASSES |
| `POST /login` | `db.get_failed_login_count` | Per-IP 15-min count before argon2 | WIRED | dashboard.py:231 |
| `POST /login` | `db.log_failed_login` | INSERT on password mismatch | WIRED | dashboard.py:254 |
| `POST /login` | `db.clear_failed_logins` | DELETE on successful auth | WIRED | dashboard.py:264 |
| `POST /login` success | `request.session['user']` | `request.session["user"] = "admin"` | WIRED | dashboard.py:263 |
| `_verify_auth` | `request.session.get("user")` | Returns user or raises HTTPException | WIRED | dashboard.py:88 |
| `bot.py` | `SettingsStore` | Constructed with `db._pool`, loaded, assigned to `tm.settings_store` | WIRED | bot.py:181–183 |
| `_effective()` | `settings_store.effective(acct.name)` | Called at trade execution time | WIRED | trade_manager.py:48–55 |
| `db.update_account_setting` | `settings_audit` | Transaction-based audit INSERT before UPDATE | WIRED | db.py:618–633 |
| `GET /login` | `templates/login.html` | `TemplateResponse("login.html", ...)` with csrf_token + next_path | WIRED | dashboard.py:143–157 |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| SessionMiddleware registered in app | `user_middleware` inspection | `Middleware(SessionMiddleware, ...)` confirmed | PASS |
| `/login` and `/logout` routes exist | Route list check | Both present | PASS |
| `asset_url` in Jinja globals | `dashboard.templates.env.globals` | Confirmed | PASS |
| Config fail-fast: missing `SESSION_SECRET` | `test_session_secret_missing_raises` | PASSES | PASS |
| Config fail-fast: weak `SESSION_SECRET` | `test_session_secret_too_weak_raises` | PASSES | PASS |
| Config fail-fast: plaintext `DASHBOARD_PASS` | `test_plaintext_dashboard_pass_refuses_boot` | PASSES | PASS |
| Unauthenticated page → 303 /login | `test_page_route_redirects_on_missing_session` | PASSES | PASS |
| Unauthenticated HTMX → 401 | `test_htmx_route_returns_401_on_missing_session` | PASSES | PASS |
| Basecoat assets vendored | `test_basecoat_vendored` | PASSES | PASS |
| drizzle.config.json removed | `test_drizzle_config_removed` | PASSES | PASS |
| Tailwind Python glob present | `test_tailwind_content_glob_includes_python` | PASSES | PASS |
| Dockerfile has CSS build stage | `test_dockerfile_has_tailwind_build_stage` | PASSES | PASS |
| HTMX bridge installed | `test_htmx_bridge_installed` | PASSES | PASS |
| Full non-DB test suite | `pytest test_config.py test_auth_session.py test_ui_substrate.py` | 21 passed, 3 skipped | PASS |

DB-dependent tests (`test_login_flow.py`, `test_rate_limit.py`, `test_settings_store.py`, `test_seed_accounts.py`, `test_settings.py`) skip cleanly when Postgres is unreachable — confirmed pre-existing; see `deferred-items.md`.

---

### Requirements Coverage

| Requirement | Plans | Description Summary | Status |
|-------------|-------|---------------------|--------|
| SET-01 | 05-01 | Per-account settings in DB, runtime-editable, supersede JSON | SATISFIED |
| SET-02 | 05-01 | 5 required settings fields | SATISFIED |
| SET-04 | 05-01 | Audit log on every settings write | SATISFIED |
| SET-05 | 05-01 | Snapshot infra ready (`frozen+slots`, `snapshot()`) | DEFERRED (Phase 6 consumption) |
| UI-01 | 05-02 | Tailwind CDN removed, standalone-CLI build | SATISFIED |
| UI-02 | 05-02 | Basecoat vendored under `static/` | SATISFIED |
| UI-03 | 05-02 | Python glob in Tailwind content | SATISFIED |
| UI-04 | 05-02 | Content-hashed CSS + manifest.json | SATISFIED |
| UI-05 | 05-02 | HTMX afterSwap → Basecoat re-init | SATISFIED |
| AUTH-01 | 05-03, 05-04 | Styled login form replaces HTTPBasic on all routes | SATISFIED |
| AUTH-02 | 05-03 | argon2 verification; plaintext DASHBOARD_PASS rejected | SATISFIED |
| AUTH-03 | 05-03 | SessionMiddleware; SESSION_SECRET fail-fast | SATISFIED |
| AUTH-04 | 05-04 | Double-submit CSRF on /login | SATISFIED |
| AUTH-05 | 05-04 | Per-IP rate limiting; constant-time comparison | SATISFIED |
| AUTH-06 | 05-04 | Logout endpoint clears session → /login | PARTIAL — endpoint present, no UI affordance |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `templates/base.html` | 14–35 | Sidebar nav has no logout link | Blocker | AUTH-06 / ROADMAP SC#3 gap — operator cannot log out without typing the URL manually |
| `templates/base.html` | 8 | HTMX loaded from `unpkg.com` CDN (`https://unpkg.com/htmx.org@2.0.4`) | Info | Breaks "offline-capable" property claimed in Plan 02 rationale; HTMX plan 02 only committed to removing Tailwind CDN (UI-01 satisfied), so not a requirement miss; note for VPS deployment in air-gapped environment |
| `risk_calculator.py` | 14 | `from models import AccountConfig, Direction` — `AccountConfig` imported but never used | Info | Dead import; pre-existing; no functional impact |

---

### Deferred Items

Items with infrastructure delivered in Phase 5 but consumption deferred to Phase 6.

| # | Item | Addressed In | Evidence |
|---|------|-------------|---------|
| 1 | Staged-entry snapshot at signal receipt (SET-05 consumption) | Phase 6 | Phase 6 goal: staged entry execution; Phase 6 requirements include `STAGE-01..09, SET-03`. `AccountSettings frozen+slots=True` and `SettingsStore.snapshot()` are in place — the contract Phase 6 depends on is satisfied. |

---

### Human Verification Required

None required for automated gap determination. The gap (no logout link in nav) is conclusively determined by code inspection — not a UI appearance question.

---

### Gaps Summary

**1 gap blocking full goal achievement:**

**AUTH-06 / ROADMAP SC#3 — No logout UI affordance**

The `/logout` endpoint is correctly implemented (clears session, 303 → `/login`). However, `templates/base.html` sidebar contains no logout link or button. The ROADMAP explicitly states: *"Operator can log out from any page"* (SC#3). Without a link in the nav, the operator must manually type `/logout` — this does not satisfy the intent.

Fix: Add a logout link in `templates/base.html` sidebar, e.g.:

```html
<a href="/logout" class="block px-4 py-2.5 text-sm hover:bg-dark-700 text-slate-400">Sign out</a>
```

This is a one-line fix in the sidebar nav block (before or after the `<div class="flex-1 py-4">` nav links section). No backend change required.

---

_Verified: 2026-04-19T12:00:00Z_
_Verifier: Claude (gsd-verifier)_
