# Phase 5: Foundation — UI substrate, auth, and settings data model - Research

**Researched:** 2026-04-19
**Domain:** FastAPI/HTMX dashboard hardening — Tailwind CLI build, Basecoat vendoring, argon2 + Starlette sessions, hand-written additive DDL for accounts/settings/audit/rate-limit tables
**Confidence:** HIGH (version pins and APIs verified against live registries and source; existing codebase read)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**UI substrate visual scope**
- **D-01:** Phase 5 is substrate-only. Existing pages (`overview`, `positions`, `history`, `analytics`, `signals`, `settings`) keep their current `.card` / `.btn-*` look. Phase 7 owns the Basecoat restyle.
- **D-02:** The built `app.css` includes a **compat shim** that redefines the existing `.card`, `.btn`, `.btn-primary`, `.btn-danger`, status-color classes, etc., using Tailwind utilities so every existing page renders visually identical after the CDN is removed. Shim lives in a dedicated `@layer components` block the Phase 7 restyle will peel away class-by-class.
- **D-03:** Only `/login` uses Basecoat primitives directly — it's the proving ground for the new substrate without touching any existing page.

**Tailwind build pipeline**
- **D-04:** Tailwind v3.4 standalone CLI (downloaded during Docker image build, no Node runtime).
- **D-05:** Tailwind `content` glob **must include `./**/*.py`** so classes inlined in `dashboard.py` HTMLResponse fragments aren't purged. CI check greps the built CSS for the set of status classes used in Python strings.
- **D-06:** Output filename is content-hashed (`/static/css/app.{hash}.css`). Template resolves the hashed name via a small manifest (`static/css/manifest.json`) written by the build. No query-string versioning.
- **D-07:** Basecoat (`basecoat.css` + `basecoat.min.js`) is vendored under `static/vendor/basecoat/` at a pinned version (`0.3.3`). No CDN.
- **D-08:** HTMX re-init — add a single `htmx:afterSwap` listener that calls Basecoat's documented JS init on the swapped subtree so interactive components keep working after partial swaps (UI-05).
- **D-09:** Delete the stray `drizzle.config.json` at repo root as part of this phase.

**Login UX**
- **D-10:** Login form has **one password field only** — no visible username field. Single-admin model.
- **D-11:** On submit, session cookie is set with a **single 30-day lifetime**. No "remember me" branch, no 8h default. Trusted-device single-operator pattern.
- **D-12:** `/logout` clears the session and redirects to `/login`.
- **D-13:** Constant-time password compare on every attempt (argon2-cffi `verify` is already constant-time).
- **D-14:** Login form POST is CSRF-protected via double-submit cookie pattern on `/login` ONLY. All other (authenticated) routes keep the existing HTMX-header CSRF pattern unchanged.

**Session & startup**
- **D-15:** Starlette `SessionMiddleware` with `SESSION_SECRET` env var. Bot **refuses to start** if `SESSION_SECRET` is unset OR below 32 bytes of entropy.
- **D-16:** Session rotation on password change — invalidate by rotating `SESSION_SECRET` (operator runbook item; `SESSION-ROTATE` deferred to v1.2).

**Rate-limit & lockout**
- **D-17:** App-level lockout: **5 consecutive failed attempts per IP → reject for 15 minutes**. Tracked in `failed_login_attempts` table. Successful login clears the IP's counter.
- **D-18:** Outer ring is nginx `limit_req` (belt-and-suspenders).
- **D-19:** No username enumeration surface — password-only form means there's nothing to enumerate.

**Password migration**
- **D-20:** **Hard cutover this release.** Ship `scripts/hash_password.py`. Deploy requires `DASHBOARD_PASS_HASH` env var set.
- **D-21:** Bot refuses to start if `DASHBOARD_PASS` (plaintext) is still set post-upgrade — clear error message.
- **D-22:** `DASHBOARD_USER` env var is no longer read.

**Accounts + settings data model**
- **D-23:** Introduce an `accounts` table — one row per trading account with the fields from `accounts.json`. **DB is the runtime source of truth** once seeded.
- **D-24:** `accounts.json` becomes a **bootstrap seed only**. On startup, idempotent `INSERT ... ON CONFLICT DO NOTHING`.
- **D-25:** Removing an account from `accounts.json` does **NOT** delete its DB row. Log orphan warning at startup.
- **D-26:** `account_settings` row auto-created alongside each new `accounts` row, populated from JSON defaults.
- **D-27:** All v1.0 code paths that read `AccountConfig` migrate to a `SettingsStore` abstraction.
- **D-28:** Per-account settings (`SET-02`): `risk_mode` (`percent` | `fixed_lot`), `risk_value`, `max_stages`, `default_sl_pips`, `max_daily_trades`. Editing UI is Phase 6.

**Settings audit log**
- **D-29:** **Every** write to `account_settings` produces one `settings_audit` row per field changed: `(timestamp, account_name, field, old_value, new_value, actor)`.
- **D-30:** `actor` = session user string. Password-only auth → stored actor is literal `"admin"`. Schema future-proof for multi-user.
- **D-31:** No retention TTL.

**Settings snapshot prep (SET-05)**
- **D-32:** Phase 5 introduces `SettingsStore` abstraction and in-memory cache. Snapshot-at-signal-receipt logic itself ships in Phase 6. `SettingsStore.effective(account_name)` returns a dataclass value cheap to copy.

### Claude's Discretion

- Exact schema column types / constraints for the four new tables (within additive-only rule)
- `SettingsStore` cache invalidation strategy (simple dict + reload-on-write is default)
- Compat shim organization (single `_compat.css` import vs inline `@layer components` block)
- Exact Basecoat JS re-init API call — verify against v0.3.3 docs
- `scripts/hash_password.py` implementation details
- Whether to reset `failed_login_attempts` counter on success or let rows age out
- Manifest file format (`manifest.json` schema)

### Deferred Ideas (OUT OF SCOPE)

- Settings edit UI (SET-03) → Phase 6
- Staged entries + zone watcher + snapshot logic → Phase 6
- Full Basecoat restyle of every dashboard page, mobile responsive, drilldowns, analytics filters → Phase 7
- `SESSION_SECRET` rotation with dual-key grace window → v1.2 `SESSION-ROTATE`
- Alembic migration tooling → v1.2 `DBE-01`
- Multi-user / role-based auth, password reset, 2FA, passkey/WebAuthn → out of scope for v1.1
- Automated CSS safelist CI check beyond Python-string class grep → nice-to-have
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **UI-01** | Tailwind compiled via standalone CLI at Docker build; Play CDN script removed from `templates/base.html:7` | §Tailwind build pipeline (Dockerfile multi-stage) + §Compat shim (actual classes enumerated from `base.html:22-40`) |
| **UI-02** | Basecoat UI vendored into `static/`, provides shadcn-faithful components | §Basecoat v0.3.3 vendoring (jsDelivr URLs verified HTTP 200) |
| **UI-03** | Tailwind content globs include `*.py` files | §Tailwind config (11 matches verified in `dashboard.py`, 7 distinct classes enumerated) |
| **UI-04** | Content-hashed filename to defeat browser cache on redeploy | §Content hashing + manifest.json (Python post-build script) |
| **UI-05** | Basecoat JS re-initializes after HTMX swaps | §Basecoat v0.3.3 JS API (MutationObserver auto-inits; `window.basecoat.initAll()` belt-and-suspenders) |
| **AUTH-01** | Styled login page replaces HTTPBasic on all protected routes | §Login layering (swap `_verify_auth` at `dashboard.py:47`, 20+ `Depends(_verify_auth)` call sites unchanged) |
| **AUTH-02** | Passwords verified against argon2 hash; plaintext migrated and removed | §argon2-cffi 25.1.0 API + §`scripts/hash_password.py` + §Fail-fast startup when both env vars set |
| **AUTH-03** | Sessions use Starlette SessionMiddleware; bot refuses to start if SESSION_SECRET < 32 bytes | §SessionMiddleware configuration + §Startup validators |
| **AUTH-04** | Login POST CSRF-protected via double-submit cookie; HTMX routes keep header CSRF | §Double-submit cookie flow (cookie-only, no session write needed) |
| **AUTH-05** | Login has rate limiting per-IP with constant-time credential comparison | §`failed_login_attempts` table + query pattern + nginx `limit_req` |
| **AUTH-06** | Logout endpoint clears session and redirects to /login | §SessionMiddleware (`request.session.clear()` + `RedirectResponse("/login", 303)`) |
| **SET-01** | Per-account settings persisted in DB, editable at runtime, supersede `accounts.json` | §DDL for `accounts` + `account_settings` + §Seed-at-boot flow (idempotent upsert, DB wins) |
| **SET-02** | Settings include risk_mode, risk_value, max_stages, default_sl_pips, max_daily_trades | §`account_settings` DDL (CHECK constraint on risk_mode, NUMERIC risk_value, etc.) |
| **SET-04** | Settings changes recorded in audit log (timestamp, field, old → new, actor) | §`settings_audit` DDL + §SettingsStore write-through logs audit row per field changed |
| **SET-05** | Settings snapshot at signal receipt; later edits don't mutate enqueued stages | §`SettingsStore.effective()` returns cheap-to-copy frozen dataclass; actual snapshot persistence is Phase 6 |
</phase_requirements>

## Summary

Phase 5 is a substrate swap. Every decision about *what* to build is locked in CONTEXT.md. This research pins *how* — exact version numbers, URLs, APIs, config syntax, DDL, and integration points against the actual codebase.

All major dependencies verified live: Tailwind CLI v3.4.19 is the latest v3.x (`v3.4.17` in STACK.md's illustrative snippet is stale by two patch versions), argon2-cffi 25.1.0 is confirmed latest on PyPI, `basecoat-css@0.3.3` is confirmed available on jsDelivr with both `basecoat.css`/`basecoat.min.css` and `dist/js/all.min.js`/`basecoat.min.js`. Note: npm has `basecoat-css@0.3.11` as the latest published; CONTEXT locks `0.3.3` intentionally (matches research from `.planning/research/STACK.md`). Pin is explicit and should not be upgraded as a side-effect of this phase.

**Critical discovery about UI-05 (Basecoat HTMX re-init):** Basecoat v0.3.3's `basecoat.js` installs a `MutationObserver` on `document.body` (subtree) that auto-initializes any newly-added components with a `data-{name}-initialized` idempotency flag. This means HTMX swaps auto-work out of the box. D-08's explicit `htmx:afterSwap → window.basecoat.initAll()` call is still worth shipping as belt-and-suspenders (idempotent via the flag), but it is not strictly required and should be framed as defense-in-depth, not the primary mechanism.

**Critical correction to CONTEXT D-02's compat-shim class list:** CONTEXT says "redefines `.card`, `.btn`, `.btn-primary`, `.btn-danger`, status-color classes." The actual classes in `templates/base.html:22-40` are different: `.btn-red`, `.btn-blue`, `.btn-green` (not `.btn-primary`/`.btn-danger`), plus `.nav-active`, `.card`, `.profit`, `.loss`, `.badge-buy`, `.badge-sell`, `.badge-connected`, `.badge-disconnected`, and the custom `dark.700/800/900` palette. The compat shim must cover the *actual* class set — enumerated below.

**Primary recommendation:** Build Phase 5 as four independent task clusters that share no files: (1) DB schema & SettingsStore (backend only, no UI), (2) Tailwind/Basecoat build pipeline & compat shim (Docker + static assets), (3) auth layer swap (config.py + dashboard.py + new scripts/hash_password.py), (4) `/login` template + CSRF + rate-limit wiring. Clusters 1 and 2 can run in parallel; 3 depends on config.py shape from 1 (`SESSION_SECRET` addition); 4 depends on 2 (Basecoat primitives) and 3 (session dependency exists).

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Password hashing & verify | API / Backend | — | Secret never leaves server; argon2-cffi in Python process |
| Session cookie issuance & validation | API / Backend (Starlette middleware) | Browser (cookie jar) | Signed by server, browser only transports |
| CSRF token (double-submit) | API / Backend (generate + verify) | Browser (cookie + form field round-trip) | Cookie issued by server, form echoes it back |
| Rate limiting (app-level) | API / Backend (`failed_login_attempts` queries) | — | State in DB so it survives container restart |
| Rate limiting (outer ring) | Reverse Proxy (nginx `limit_req`) | — | Belt-and-suspenders before request hits the app |
| CSS compilation | Build time (Docker build stage) | CDN / Static (served by `StaticFiles`) | No runtime Node; build once, serve hashed file |
| JS component init | Browser (Basecoat MutationObserver) | — | DOM-side concern, no server involvement |
| Settings persistence | Database (PostgreSQL) | API / Backend (SettingsStore cache) | DB = runtime source of truth per D-23 |
| Audit log append | API / Backend (write in same tx as settings upsert) | Database | Tx consistency matters |
| Accounts seed from JSON | API / Backend (bot.py startup) | Database | Idempotent upsert at boot |

---

## Standard Stack

### Core (new additions this phase)

| Library / Tool | Version | Purpose | Why Standard |
|----------------|---------|---------|--------------|
| `argon2-cffi` | **25.1.0** `[VERIFIED: PyPI API]` | Password hashing & verification | Actively maintained by hynek; current idiomatic pick; Passlib is 2020-dormant |
| `basecoat-css` (vendored) | **0.3.3** `[VERIFIED: jsDelivr HTTP 200 on /dist/basecoat.css, /dist/js/all.min.js]` | shadcn-aesthetic component primitives for `/login` | Locked by CONTEXT D-07; MIT license; single new CSS/JS, zero Python dep |
| Tailwind CSS standalone CLI | **v3.4.19** `[VERIFIED: github.com/tailwindlabs/tailwindcss releases API]` | CSS compilation at Docker build time | Locked to v3.4 by CONTEXT D-04 and STACK.md §2; v4 explicitly rejected for migration-risk reduction |
| `starlette.middleware.sessions.SessionMiddleware` | n/a (transitive via `fastapi==0.115.0`) | Signed session cookies | Already installed; `itsdangerous` also transitive |

`[VERIFIED]` version pins against live registries (2026-04-18/19):
- `npm view argon2-cffi` → n/a; `curl https://pypi.org/pypi/argon2-cffi/json` → `"version": "25.1.0"`, `requires_python: ">=3.8"`.
- `npm view basecoat-css version` → `0.3.11` (latest on npm, but **CONTEXT locks 0.3.3**).
- `curl https://data.jsdelivr.com/v1/package/npm/basecoat-css@0.3.3` → files exist: `dist/basecoat.css` (1985-10-26 epoch placeholder; content is real), `dist/basecoat.min.css`, `dist/js/all.js`, `dist/js/all.min.js` (15,682 bytes), `dist/js/basecoat.min.js` (1,030 bytes), plus per-component JS (`dropdown-menu.min.js`, `command.min.js`, etc.).
- GitHub tailwindcss releases: `v3.4.19`, `v3.4.18` recent; `v3.4.17` in `.planning/research/STACK.md` snippet is two patches behind — **use v3.4.19**.

### Supporting (unchanged; reuse from v1.0)

| Library | Version | Use |
|---------|---------|-----|
| `fastapi` | 0.115.0 | Dashboard app factory |
| `jinja2` | 3.1.4 | Template rendering (login.html) |
| `python-multipart` | 0.0.12 | Already installed — **required for parsing `application/x-www-form-urlencoded` login POST bodies** `[CITED: fastapi.tiangolo.com/tutorial/request-forms/]` |
| `asyncpg` | 0.31.0 | New table DDL + helpers |
| `uvicorn[standard]` | 0.32.0 | ASGI server |
| `httpx` | 0.28.1 | (no auth-path use) |
| `python-dotenv` | 1.0.1 | Config loading |

### Alternatives Considered and Rejected

| Instead of | Rejected | Reason |
|------------|----------|--------|
| `argon2-cffi` | Passlib | 2020-dormant; breaks on Py 3.13 `[CITED: STACK.md §3, verified via pypi/warehouse#15454]` |
| `SessionMiddleware` | `fastapi-users`, JWT, `authlib` | Overkill for single-admin |
| Tailwind v3.4 | Tailwind v4.x | Breaking changes to `@tailwind` → `@import`, `bg-gradient-to-*`; widens blast radius during already-large UI phase `[CITED: STACK.md §2, tailwindcss.com/docs/upgrade-guide]` |
| Vendored Basecoat | Hot-loading from jsDelivr | CDN outage would brick dashboard `[CITED: STACK.md §1 maturity disclaimer]` |
| DB-based rate limit | Redis rate limit | No Redis in stack; DB is already there; volumes are tiny |

**Installation:**
```bash
# Add to requirements.txt:
echo "argon2-cffi==25.1.0" >> requirements.txt
pip install argon2-cffi==25.1.0
```

**Docker/build-time (Tailwind CLI & Basecoat):**
```bash
# In Docker build stage — see §Dockerfile fragment below:
curl -sL https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.19/tailwindcss-linux-x64 \
  -o /usr/local/bin/tailwindcss
chmod +x /usr/local/bin/tailwindcss

# Vendor Basecoat (one-time, commit to repo — run locally, not in Docker):
mkdir -p static/vendor/basecoat
curl -sL https://cdn.jsdelivr.net/npm/basecoat-css@0.3.3/dist/basecoat.css \
  -o static/vendor/basecoat/basecoat.css
curl -sL https://cdn.jsdelivr.net/npm/basecoat-css@0.3.3/dist/js/all.min.js \
  -o static/vendor/basecoat/basecoat.min.js
```

**Version verification (planner MUST re-run before pinning):**
```bash
curl -sI https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.19/tailwindcss-linux-x64
# → HTTP/2 302 if still published; body redirects to object storage
curl -s https://pypi.org/pypi/argon2-cffi/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"
# → 25.1.0 (confirm unchanged)
```

---

## Architecture Patterns

### System Architecture Diagram

```
                 Browser                        nginx               FastAPI app (existing)
                    │                             │                          │
 1. GET /login ─────┼─────────────────────────────┼──────────────────────────▶  unauth route
                    │                             │                          │   set csrf cookie
                    │  HTML + csrf cookie ◀───────┼──────────────────────────┤   render login.html
                    │                             │                          │
 2. POST /login ────┼──►  limit_req zone=login ──►│   _verify_csrf (login    │
    (form+cookie)   │     (5r/m burst=3)          │    variant: compare      │
                    │                             │    cookie ↔ form field)  │
                    │                             │                          │
                    │                             │   SELECT count(*)        │
                    │                             │     FROM failed_login_   │
                    │                             │     attempts ...         │
                    │                             │   if ≥ 5 → 429 + log     │
                    │                             │                          │
                    │                             │   argon2 verify          │
                    │                             │   (~500ms constant-time) │
                    │                             │                          │
                    │   303 + Set-Cookie:         │   on success:            │
                    │   telebot_session=…  ◀──────┼───  request.session[     │
                    │   (HX-Redirect if HTMX)     │     "user"] = "admin"    │
                    │                             │     DELETE failed_login_ │
                    │                             │     attempts WHERE ip=…  │
                    │                             │                          │
 3. Every other ────┼──►                          │   _verify_auth dep:      │
    route           │                             │   request.session.get(   │
                    │                             │     "user") else         │
                    │                             │     RedirectResponse(    │
                    │                             │     "/login?next=…")     │
                    │                             │                          │
 Bot startup ───────┼─────────────────────────────┼──────────────────────────┤
                    │                             │   validate SESSION_      │
                    │                             │   SECRET ≥ 32 bytes      │
                    │                             │   reject if DASHBOARD_   │
                    │                             │   PASS still set         │
                    │                             │   open asyncpg pool      │
                    │                             │   CREATE TABLE IF NOT    │
                    │                             │   EXISTS × 4             │
                    │                             │   seed accounts.json →   │
                    │                             │   accounts + settings    │
                    │                             │   (idempotent upsert)    │
                    │                             │   log orphan accounts    │
                    │                             │   build SettingsStore    │
                    │                             │   pass to TradeManager   │
                    │                             │   + Executor             │
```

### Component Responsibilities

| Component | File(s) | Responsibility |
|-----------|---------|----------------|
| Config loader | `config.py` (modified) | Read + validate `SESSION_SECRET`, `DASHBOARD_PASS_HASH`; **reject** `DASHBOARD_PASS` if set; drop `DASHBOARD_USER` |
| DB schema bootstrap | `db.py::_create_tables` (extended) | Add four `CREATE TABLE IF NOT EXISTS` blocks |
| DB helpers (new) | `db.py` | `upsert_account()`, `upsert_account_settings()`, `get_account_settings()`, `update_account_setting()` (writes audit row in same tx), `get_failed_login_count()`, `log_failed_login()`, `clear_failed_logins()`, `get_orphan_accounts()` |
| SettingsStore | `settings_store.py` (new) | In-process dict keyed by account name, `.effective(name)`, `.reload(name)` |
| Seed logic | `bot.py::_setup_trading` (modified) | After `db.init_db()`: for each account in `accounts.json`, idempotent upsert into `accounts` + `account_settings`; log orphans; **build SettingsStore** before `TradeManager` constructor |
| Password hasher helper | `scripts/hash_password.py` (new) | CLI: reads password from stdin/prompt, prints argon2 hash |
| Session middleware | `dashboard.py::app` (modified) | `app.add_middleware(SessionMiddleware, …)` at import time |
| `_verify_auth` (modified) | `dashboard.py:47` | Read `request.session["user"]`; on miss: `RedirectResponse("/login?next=…", 303)` for page routes or raise 401 for API/HTMX routes |
| `_verify_csrf` (unchanged for all existing routes) | `dashboard.py:67` | HTMX header check — preserved |
| `/login` route (GET) | `dashboard.py` (new) | Set csrf cookie, render `templates/login.html` |
| `/login` route (POST) | `dashboard.py` (new) | Verify double-submit cookie, check rate limit, argon2 verify, set session, redirect |
| `/logout` route | `dashboard.py` (new) | `request.session.clear()` + 303 redirect to `/login` |
| Tailwind config | `tailwind.config.js` (new) | `content: ["./templates/**/*.html", "./**/*.py"]`, safelist critical status classes |
| Compat shim | `static/css/_compat.css` (new) | `@layer components { .card {…} .btn {…} .btn-red {…} …}` — preserves existing look |
| Build script | `scripts/build_css.sh` (new) or inline in Dockerfile | Run tailwind CLI + content-hash + write manifest.json |
| Asset resolver | `dashboard.py::asset_url` (new) | Load manifest.json once at startup; Jinja global |
| Basecoat bridge | `static/js/htmx_basecoat_bridge.js` (new, optional) | `htmx:afterSwap` listener → `window.basecoat.initAll()` |

### Recommended Project Structure

```
telebot/
├── static/
│   ├── css/
│   │   ├── input.css             # NEW: @tailwind directives + @import
│   │   ├── _compat.css           # NEW: shim for v1.0 classes
│   │   ├── app.{hash}.css        # BUILT: output, gitignored, baked into image
│   │   └── manifest.json         # BUILT: { "app.css": "app.{hash}.css" }
│   ├── js/
│   │   └── htmx_basecoat_bridge.js  # NEW (optional belt-and-suspenders)
│   └── vendor/
│       └── basecoat/
│           ├── basecoat.css      # NEW: vendored 0.3.3
│           └── basecoat.min.js   # NEW: vendored 0.3.3 (dist/js/all.min.js renamed)
├── templates/
│   ├── base.html                 # MODIFIED: drop Play CDN, add hashed CSS link
│   └── login.html                # NEW: Basecoat-styled single-password form
├── scripts/
│   ├── hash_password.py          # NEW: argon2 CLI helper
│   └── build_css.sh              # NEW: tailwind CLI + hash + manifest
├── settings_store.py             # NEW
├── tailwind.config.js            # NEW
├── config.py                     # MODIFIED: new env validators
├── db.py                         # MODIFIED: new tables + helpers
├── dashboard.py                  # MODIFIED: SessionMiddleware, /login, /logout, _verify_auth swap
├── bot.py                        # MODIFIED: seed at boot, SettingsStore wiring
├── Dockerfile                    # MODIFIED: add Tailwind build stage
├── requirements.txt              # MODIFIED: + argon2-cffi==25.1.0
├── .gitignore                    # MODIFIED: + static/css/app.*.css, static/css/manifest.json
└── drizzle.config.json           # DELETED per D-09
```

### Anti-Patterns to Avoid

- **Reading `accounts.json` per request at runtime.** Seed at startup only; runtime reads go through SettingsStore → DB. Prevents stale-JSON confusion (Pitfall 9 in `.planning/research/PITFALLS.md`).
- **Auto-upgrading plaintext password on first login.** CONTEXT D-20 is hard cutover — ship with refuse-to-boot if `DASHBOARD_PASS` is set.
- **Generalising the `/login` CSRF exemption.** Whitelist only `/login` path in `_verify_csrf`; everything else still requires `hx-request` header.
- **Mutating `_verify_auth` to silently accept both HTTPBasic and sessions.** Double auth path doubles attack surface (AP-5 in ARCHITECTURE.md §9).
- **Using stable filename `app.css`.** Always hashed; browser caches are the enemy during a live-trading deploy (Pitfall 12).
- **`ALTER TABLE` on existing v1.0 tables.** Additive-only (Pitfall 17). All new DDL is `CREATE TABLE IF NOT EXISTS`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Password hashing | Custom PBKDF2 / bcrypt wrappers | `argon2.PasswordHasher` | RFC 9106 parameters + constant-time verify + encoded-hash format |
| Signed session cookies | Custom HMAC-SHA256 token format | `starlette.middleware.sessions.SessionMiddleware` | Already installed; handles serialisation, expiry, tampering detection |
| CSS purge | Grep-and-include by hand | Tailwind `content` glob + safelist | Well-understood, CI-testable |
| Content hashing | Manual date-suffix versioning | A small Python post-build script that SHA256s the file and writes manifest.json | Integrates with Jinja via `asset_url()` helper; no query strings |
| Double-submit CSRF | Session-stored tokens | Cookie-only double-submit (see §Double-Submit) | Simpler; no session write on GET /login; works even if session cookie is invalidated |
| Rate limiter | In-memory per-process counter | `failed_login_attempts` table + time-windowed `SELECT COUNT(*)` | Survives container restart; shared across workers (future-proof) |

**Key insight:** Every item above has a well-tested standard. The temptation to build lightweight custom versions is the single largest source of defects in auth/crypto code.

---

## Runtime State Inventory

Phase 5 includes migration-like changes: `DASHBOARD_PASS` → `DASHBOARD_PASS_HASH`, `DASHBOARD_USER` removal, and `accounts.json` semantics flip from "source of truth" to "bootstrap seed." Inventory of runtime state that a code change alone will not fix:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | `accounts.json:2-15` (single account `"Vantage Demo-10k"`); no existing v1.0 DB row for this account. PostgreSQL tables `signals`, `trades`, `daily_stats`, `pending_orders` — **none reference the renamed auth env vars**. | Seed `accounts` + `account_settings` on first boot (idempotent). No data migration of existing v1.0 tables. |
| **Live service config** | None. The dashboard is the only consumer of `DASHBOARD_PASS`; no external service (Telegram, Discord, MT5 bridge) uses it. | None. |
| **OS-registered state** | None. Container is the deploy unit; no pm2/systemd/Task Scheduler registration of the bot name. | None. |
| **Secrets / env vars** | `DASHBOARD_PASS` in `.env.dev:27` and `VPS_DEPLOYMENT_GUIDE.md:178` and `config.py:96`. `DASHBOARD_USER` in `.env.dev:26` and `VPS_DEPLOYMENT_GUIDE.md:177` and `config.py:95`. Docker-compose `env_file: .env` (line 6 of `docker-compose.yml`) reads whatever is in the operator's `.env`. No `DASHBOARD_PASS` in `docker-compose.yml` directly. | (a) Add `DASHBOARD_PASS_HASH` + `SESSION_SECRET` env readers with fail-fast validators in `config.py`; (b) **fail-fast if `DASHBOARD_PASS` still set** per D-21; (c) **silently ignore `DASHBOARD_USER`** per D-22 (do not fail on its presence — it's harmless legacy); (d) update `.env.dev` and `VPS_DEPLOYMENT_GUIDE.md` to remove the two vars and document the new flow. |
| **Build artifacts / installed packages** | `drizzle.config.json` at repo root (stray per D-09). `static/.gitkeep` is the only file in `static/` today. No existing `static/css/app.css` to retire. | Delete `drizzle.config.json`; add `static/css/app.*.css` + `static/css/manifest.json` to `.gitignore` (they're build outputs, not checked-in). |

**Canonical deployment step for operators (belongs in VPS_DEPLOYMENT_GUIDE.md):**

```bash
# 1. Generate the hash on a machine that has the new image:
docker run --rm -it <image> python scripts/hash_password.py
# (prompt for password, echoes hash)

# 2. Update .env on the VPS:
#    - REMOVE: DASHBOARD_PASS=...
#    - REMOVE: DASHBOARD_USER=...
#    - ADD:    DASHBOARD_PASS_HASH=$argon2id$v=19$m=65536,t=3,p=4$…
#    - ADD:    SESSION_SECRET=<openssl rand -base64 48>

# 3. docker compose up -d telebot
# 4. Container refuses to start if DASHBOARD_PASS still present — clear error message
```

---

## Seed Logic at Boot — Integration Sequence

Current `bot.py::_setup_trading` at lines 46-178 does: `db.init_db()` → load accounts.json → build `AccountConfig` list → create connectors → `TradeManager(...)` → `Executor(...)`. New insertion point is after `db.init_db()` and **before** `TradeManager(...)`:

```python
# bot.py _setup_trading, new block between line 60 and line 132
await db.init_db(settings.database_url)

# NEW: seed accounts + settings from accounts.json (idempotent)
accts_data = load_accounts_config()
accts_raw = accts_data.get("accounts", [])

if accts_raw:
    seeded_names = []
    for raw in accts_raw:
        # D-24: upsert (INSERT ... ON CONFLICT DO NOTHING)
        created = await db.upsert_account_if_missing(
            name=raw["name"],
            server=raw["server"],
            login=raw["login"],
            password_env=raw.get("password_env", ""),
            risk_percent=raw.get("risk_percent", 1.0),
            max_lot_size=raw.get("max_lot_size", 1.0),
            max_daily_loss_percent=raw.get("max_daily_loss_percent", 3.0),
            max_open_trades=raw.get("max_open_trades", 3),
            enabled=raw.get("enabled", True),
            mt5_host=raw.get("mt5_host", ""),
            mt5_port=raw.get("mt5_port", 0),
        )
        if created:
            # D-26: auto-create account_settings row with defaults from JSON
            await db.upsert_account_settings_if_missing(
                account_name=raw["name"],
                risk_mode="percent",
                risk_value=raw.get("risk_percent", 1.0),
                max_stages=1,          # Phase 6 will default higher via SET-03
                default_sl_pips=100,   # Pitfall 1 orphan SL default
                max_daily_trades=30,
            )
            logger.info("Seeded account from JSON: %s", raw["name"])
        seeded_names.append(raw["name"])

    # D-25: log orphans (in DB but not in JSON) — never delete
    orphans = await db.get_orphan_accounts(seeded_names)
    for orphan_name in orphans:
        logger.warning(
            "Account '%s' exists in DB but not in accounts.json — kept alive (D-25)",
            orphan_name,
        )

# NEW: build SettingsStore now that DB is seeded — pass to TradeManager + Executor
from settings_store import SettingsStore
settings_store = SettingsStore(db_pool=db._pool)
await settings_store.load_all()  # warm cache

# (continue to existing code: build connectors, pass settings_store down the chain)
tm = TradeManager(connectors, accounts, global_config, settings_store=settings_store)
# …
executor = Executor(tm, global_config, notifier=notifier, …)

# NEW: pass settings_store to dashboard init
init_dashboard(executor, notifier, settings, settings_store=settings_store)
```

**Note on `TradeManager(connectors, accounts, global_config, settings_store=…)` signature change:** Adding the kwarg is additive. Existing v1.0 callers using positional arguments still work. Phase 6 will start reading through `settings_store.effective()`; Phase 5 just wires the reference and exposes it to the dashboard.

---

## Code Examples

### Example 1: argon2-cffi 25.1.0 PasswordHasher usage

```python
# Source: github.com/hynek/argon2-cffi/blob/main/src/argon2/_password_hasher.py [VERIFIED]
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError

_ph = PasswordHasher()
# Defaults (from RFC_9106_LOW_MEMORY profile):
#   time_cost=3, memory_cost=65536 KiB (64 MiB), parallelism=4,
#   hash_len=32, salt_len=16, type=Argon2id
# Encoded hash is ~97 chars, fits in TEXT column trivially.

def verify_password(submitted: str, stored_hash: str) -> bool:
    """Constant-time verify. Returns True on match, False on mismatch/invalid hash."""
    try:
        _ph.verify(stored_hash, submitted)
        return True
    except VerifyMismatchError:
        return False
    except (InvalidHashError, VerificationError):
        logger.error("Stored password hash is malformed — admin must regenerate")
        return False
```

### Example 2: `scripts/hash_password.py` CLI helper

```python
#!/usr/bin/env python3
"""Generate DASHBOARD_PASS_HASH for env var. Usage: python scripts/hash_password.py"""
import getpass
import sys

from argon2 import PasswordHasher

def main() -> int:
    pw = getpass.getpass("New dashboard password: ")
    pw2 = getpass.getpass("Confirm: ")
    if pw != pw2:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    if len(pw) < 12:
        print("Password must be at least 12 characters.", file=sys.stderr)
        return 1
    ph = PasswordHasher()
    print(f"DASHBOARD_PASS_HASH={ph.hash(pw)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### Example 3: `SessionMiddleware` configuration

```python
# Source: starlette.io/middleware/ [CITED] + starlette source [VERIFIED]
from starlette.middleware.sessions import SessionMiddleware
from dashboard import app

SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 days per D-11

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,       # ≥ 32 bytes, validated at config load
    session_cookie="telebot_session",         # default is "session" — overridden to disambiguate
    max_age=SESSION_MAX_AGE_SECONDS,
    same_site="lax",                          # default; correct for form-POST login
    https_only=settings.session_cookie_secure, # True in prod, False for local dev/tests
    path="/",
)
```

**Defaults reference `[CITED: starlette.io/middleware/]`:**
- `session_cookie="session"` → override to `telebot_session` for clarity.
- `max_age=2 * 7 * 24 * 3600` (2 weeks) → override to 30 days per D-11.
- `same_site="lax"`.
- `path="/"`.
- `https_only=False` → must be `True` in prod.

**Reading/writing session:**
```python
# In a route:
request.session["user"] = "admin"         # write
user = request.session.get("user")         # read
request.session.clear()                    # logout (D-12)
```

**Middleware order caveat:** `app.add_middleware` wraps existing app in reverse order; SessionMiddleware must be added before routes are invoked. Adding at module level (before first request) is sufficient. `request.session` will raise `AssertionError("SessionMiddleware must be installed...")` if accessed without the middleware registered — this is the canonical debug signal `[VERIFIED: starlette source]`.

### Example 4: `_verify_auth` swap (preserves 20+ call-site signatures)

```python
# dashboard.py — replaces HTTPBasic-based _verify_auth at :47
from urllib.parse import quote
from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse

def _verify_auth(request: Request) -> str:
    """Session-based auth. Preserves v1.0 signature (returns username string).

    Page routes get a RedirectResponse; API/HTMX routes get 401.
    """
    user = request.session.get("user")
    if user:
        return user

    if request.headers.get("hx-request") or request.url.path.startswith("/api/"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Session expired")

    # Page route: redirect to /login with next param
    next_path = quote(request.url.path + ("?" + request.url.query if request.url.query else ""))
    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": f"/login?next={next_path}"},
    )
```

**Why `HTTPException` with 303 instead of returning `RedirectResponse`:** FastAPI `Depends(...)` dependencies cannot return a response directly; they must raise to short-circuit. `HTTPException` with a `Location` header is the idiomatic way to issue a redirect from a dependency `[CITED: fastapi.tiangolo.com/tutorial/dependencies/]`.

### Example 5: Double-submit cookie CSRF for /login

```python
import secrets
from fastapi import Form, Request

CSRF_COOKIE = "telebot_login_csrf"

@app.get("/login")
async def login_form(request: Request):
    csrf_token = secrets.token_urlsafe(32)
    response = templates.TemplateResponse("login.html", {
        "request": request,
        "csrf_token": csrf_token,
        "next_path": request.query_params.get("next", "/overview"),
    })
    response.set_cookie(
        CSRF_COOKIE, csrf_token,
        max_age=900,  # 15 min — login form validity window
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/login",
    )
    return response

@app.post("/login")
async def login_submit(
    request: Request,
    password: str = Form(...),
    csrf_token: str = Form(...),
    next_path: str = Form("/overview"),
):
    # 1. Double-submit cookie check
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    if not cookie_token or not secrets.compare_digest(cookie_token, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    # 2. Rate-limit check
    client_ip = request.client.host  # n.b. nginx sets X-Forwarded-For; see Runtime section
    fail_count = await db.get_failed_login_count(client_ip, minutes=15)
    if fail_count >= 5:
        raise HTTPException(status_code=429, detail="Too many attempts; wait 15 minutes")

    # 3. argon2 verify (constant-time)
    ok = verify_password(password, settings.dashboard_pass_hash)
    if not ok:
        await db.log_failed_login(client_ip)
        # Note: add small random jitter sleep to flatten timing (optional hardening)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # 4. Success: set session, clear counter, redirect
    request.session["user"] = "admin"
    await db.clear_failed_logins(client_ip)

    response = RedirectResponse(url=next_path, status_code=303)
    response.delete_cookie(CSRF_COOKIE, path="/login")

    # HTMX: also set HX-Redirect so HTMX follows it as a full nav, not a swap
    if request.headers.get("hx-request"):
        response.headers["HX-Redirect"] = next_path

    return response

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
```

**Double-submit vs session-storage for CSRF:** The pattern here uses the cookie itself as the "proof," comparing against the form field. Starlette `SessionMiddleware` is not involved in the CSRF check (no `session["csrf_pending"]` write) — simpler, fewer moving parts, and works even if session cookie is cleared. `[CITED: owasp.org/www-community/CSRF_Prevention_Cheat_Sheet — Double Submit Cookie]`

### Example 6: HTMX redirect after login

HTMX default on a 303 redirect is to follow the redirect and swap the response body into the target. For a full-page nav (expected on login), **set `HX-Redirect` response header**; HTMX will do `window.location.href = next_path` `[CITED: htmx.org/docs/#response-headers]`. Plain `<form method="POST">` fallback follows the 303 natively. Both paths work with the code above.

### Example 7: Tailwind config — the Python-glob critical decision

```javascript
// tailwind.config.js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",    // Jinja templates
    "./**/*.py",                // D-05: Python HTMLResponse fragments
  ],
  // Belt-and-suspenders safelist: the exact classes inlined in dashboard.py :219,221,236,244,245,260,268,269,291,298,299
  safelist: [
    "text-green-400",
    "text-red-400",
    // plus any class in the compat shim that renders conditionally via Jinja string concat
    // (these are static in templates, so normally picked up; listed for paranoia only)
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Preserve v1.0 palette from templates/base.html:10-20
        dark: { 700: "#252542", 800: "#1a1a2e", 900: "#0f0f1a" },
      },
    },
  },
};
```

**Verified Python-string class audit** (`Grep` in `dashboard.py` for `class="…"`):

| Line | Classes |
|------|---------|
| 219 | `text-green-400` |
| 221 | `text-red-400` |
| 236 | `text-red-400` |
| 244 | `text-green-400` |
| 245 | `text-red-400` |
| 260 | `text-red-400` |
| 268 | `text-green-400` |
| 269 | `text-red-400` |
| 291 | `text-red-400` |
| 298 | `text-green-400` |
| 299 | `text-red-400` |

Only two distinct classes inlined today: `text-green-400` and `text-red-400`. Both are standard Tailwind — the `*.py` content glob picks them up automatically. The safelist is redundant but cheap.

### Example 8: Compat shim covering the *actual* v1.0 class set

Derived from `templates/base.html:22-40` (the `<style>` block being retired):

```css
/* static/css/_compat.css — imported by input.css */

@layer components {
  /* Palette helpers not built from Tailwind utilities alone */
  .profit { @apply text-green-400; }
  .loss   { @apply text-red-400; }

  /* Card */
  .card {
    @apply bg-dark-800 border border-dark-700 rounded-xl;
  }

  /* Buttons (v1.0 used btn-red / btn-blue / btn-green — NOT btn-primary/btn-danger as
     illustrated in CONTEXT D-02; the planner must use the real class names) */
  .btn {
    @apply px-3 py-1.5 rounded-md text-xs font-medium cursor-pointer transition-opacity;
  }
  .btn:hover { @apply opacity-85; }
  .btn-red   { @apply bg-red-900 text-red-300; }   /* #991b1b / #fca5a5 */
  .btn-blue  { @apply bg-blue-900 text-blue-300; } /* #1e3a5f / #93c5fd */
  .btn-green { @apply bg-emerald-900 text-emerald-300; } /* #065f46 / #6ee7b7 */

  /* Badges */
  .badge-buy           { @apply bg-emerald-900 text-emerald-300 px-2 py-0.5 rounded text-xs; }
  .badge-sell          { @apply bg-red-900 text-red-300 px-2 py-0.5 rounded text-xs; }
  .badge-connected     { @apply bg-emerald-900 text-emerald-300; }
  .badge-disconnected  { @apply bg-red-900 text-red-300; }

  /* Nav active state */
  .nav-active {
    @apply bg-dark-700;
    border-left: 3px solid #818cf8;
  }

  /* Tables (scoped approximations of v1.0 raw element styling) */
  table { @apply w-full; }
  thead th {
    @apply text-left px-3 py-3 text-slate-400 font-semibold text-xs uppercase;
    border-bottom: 1px solid #252542;
  }
  tbody td {
    @apply px-3 py-3 text-sm;
    border-bottom: 1px solid #1e1e35;
  }

  /* Number inputs (match v1.0 dark styling) */
  input[type="number"] {
    @apply bg-dark-700 border border-slate-700 text-slate-200 px-2 py-1 rounded w-20 text-xs;
  }
}
```

**input.css:**
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@import "./_compat.css";
/* Basecoat vendored CSS — only used by /login this phase per D-03 */
@import "../vendor/basecoat/basecoat.css";
```

### Example 9: Content-hash manifest build script

```bash
#!/usr/bin/env bash
# scripts/build_css.sh — runs inside Docker build stage
set -euo pipefail

INPUT="static/css/input.css"
TMP_OUT="static/css/app.css"
HASH_ALGO="sha256"

tailwindcss -i "$INPUT" -o "$TMP_OUT" --minify

HASH=$(sha256sum "$TMP_OUT" | cut -c1-12)
FINAL="static/css/app.${HASH}.css"
mv "$TMP_OUT" "$FINAL"

python3 - <<PY
import json, pathlib
pathlib.Path("static/css/manifest.json").write_text(json.dumps({
    "app.css": "app.${HASH}.css"
}, indent=2))
PY

echo "Built: $FINAL"
```

### Example 10: Jinja `asset_url()` helper

```python
# dashboard.py — near template setup
import json

_asset_manifest: dict[str, str] = {}

def _load_manifest():
    global _asset_manifest
    path = BASE_DIR / "static" / "css" / "manifest.json"
    if path.exists():
        _asset_manifest = json.loads(path.read_text())

_load_manifest()

def asset_url(logical_name: str) -> str:
    hashed = _asset_manifest.get(logical_name, logical_name)
    return f"/static/css/{hashed}"

templates.env.globals["asset_url"] = asset_url
```

```jinja
{# templates/base.html #}
<link rel="stylesheet" href="{{ asset_url('app.css') }}">
```

### Example 11: Dockerfile fragment (multi-stage)

```dockerfile
# ── Stage 1: CSS build ────────────────────────────────────────
FROM debian:bookworm-slim AS css-build
ARG TAILWIND_VERSION=v3.4.19
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN curl -sL "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-x64" \
    -o /usr/local/bin/tailwindcss && chmod +x /usr/local/bin/tailwindcss

WORKDIR /build
# Copy only what the purge needs so layer cache invalidates on template/py changes
COPY tailwind.config.js input.css ./
COPY static/css/_compat.css ./static/css/
COPY static/vendor/ ./static/vendor/
COPY templates/ ./templates/
COPY *.py ./
COPY scripts/build_css.sh ./scripts/
RUN bash scripts/build_css.sh

# ── Stage 2: runtime (existing) ───────────────────────────────
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py *.json ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY scripts/ ./scripts/
# Overlay the built CSS + manifest
COPY --from=css-build /build/static/css/app.*.css ./static/css/
COPY --from=css-build /build/static/css/manifest.json ./static/css/

RUN mkdir -p /app/data
EXPOSE 8080
CMD ["python", "-u", "bot.py"]
```

### Example 12: Basecoat HTMX bridge (belt-and-suspenders)

```javascript
// static/js/htmx_basecoat_bridge.js
// Defense-in-depth only. v0.3.3 basecoat.js already installs a MutationObserver
// on document.body that auto-inits new nodes. This listener ensures that
// if the observer is somehow detached or timing loses a race, the swap target
// still gets re-inited.
document.body.addEventListener("htmx:afterSwap", () => {
  if (window.basecoat && typeof window.basecoat.initAll === "function") {
    window.basecoat.initAll();
  }
});
```

---

## DDL — Schema Additions (full)

All additive, `CREATE TABLE IF NOT EXISTS`, idempotent. No `ALTER TABLE` on v1.0 tables (Pitfall 17).

```sql
-- ── accounts (D-23) ──────────────────────────────────────────────────
-- Fields derived from accounts.json structure (verified by reading accounts.json:2-15).
CREATE TABLE IF NOT EXISTS accounts (
    name                    TEXT        PRIMARY KEY,
    server                  TEXT        NOT NULL,
    login                   BIGINT      NOT NULL,
    password_env            TEXT        NOT NULL DEFAULT '',
    risk_percent            DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    max_lot_size            DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    max_daily_loss_percent  DOUBLE PRECISION NOT NULL DEFAULT 3.0,
    max_open_trades         INTEGER     NOT NULL DEFAULT 3,
    enabled                 BOOLEAN     NOT NULL DEFAULT TRUE,
    mt5_host                TEXT        NOT NULL DEFAULT '',
    mt5_port                INTEGER     NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── account_settings (SET-01, SET-02) ────────────────────────────────
CREATE TABLE IF NOT EXISTS account_settings (
    account_name        TEXT        PRIMARY KEY REFERENCES accounts(name) ON DELETE CASCADE,
    risk_mode           TEXT        NOT NULL DEFAULT 'percent'
                                    CHECK (risk_mode IN ('percent', 'fixed_lot')),
    risk_value          NUMERIC(10,4) NOT NULL DEFAULT 1.0
                                    CHECK (risk_value > 0 AND risk_value <= 100),
    max_stages          INTEGER     NOT NULL DEFAULT 1
                                    CHECK (max_stages >= 1 AND max_stages <= 10),
    default_sl_pips     INTEGER     NOT NULL DEFAULT 100
                                    CHECK (default_sl_pips > 0 AND default_sl_pips <= 10000),
    max_daily_trades    INTEGER     NOT NULL DEFAULT 30
                                    CHECK (max_daily_trades >= 1 AND max_daily_trades <= 1000),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── settings_audit (SET-04, D-29..31) ────────────────────────────────
CREATE TABLE IF NOT EXISTS settings_audit (
    id              SERIAL      PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    account_name    TEXT        NOT NULL,
    field           TEXT        NOT NULL,
    old_value       TEXT,
    new_value       TEXT        NOT NULL,
    actor           TEXT        NOT NULL DEFAULT 'admin'
);
CREATE INDEX IF NOT EXISTS idx_settings_audit_account_ts
    ON settings_audit(account_name, timestamp DESC);

-- ── failed_login_attempts (AUTH-05, D-17) ────────────────────────────
CREATE TABLE IF NOT EXISTS failed_login_attempts (
    id              SERIAL      PRIMARY KEY,
    ip_addr         TEXT        NOT NULL,
    attempted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_agent      TEXT        NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_failed_login_ip_ts
    ON failed_login_attempts(ip_addr, attempted_at);
```

**Canonical rate-limit query:**
```sql
SELECT COUNT(*)
FROM failed_login_attempts
WHERE ip_addr = $1
  AND attempted_at > NOW() - INTERVAL '15 minutes';
```

**On success, clear the counter for that IP** (D-17, "Successful login clears the IP's counter"):
```sql
DELETE FROM failed_login_attempts WHERE ip_addr = $1;
```

**Optional aging cron (not required this phase):** `DELETE FROM failed_login_attempts WHERE attempted_at < NOW() - INTERVAL '24 hours';` — can live in `_cleanup_loop`.

**Audit write pattern (one audit row per field changed, in same tx as the setting update):**
```python
async def update_account_setting(
    account_name: str, field: str, new_value, actor: str = "admin"
) -> None:
    async with _pool.acquire() as conn:
        async with conn.transaction():
            old_value = await conn.fetchval(
                f"SELECT {field}::TEXT FROM account_settings WHERE account_name=$1",
                account_name,
            )
            # D-29: one audit row per field write, before the UPDATE
            await conn.execute(
                """INSERT INTO settings_audit
                   (account_name, field, old_value, new_value, actor)
                   VALUES ($1, $2, $3, $4, $5)""",
                account_name, field, old_value, str(new_value), actor,
            )
            await conn.execute(
                f"UPDATE account_settings SET {field}=$1, updated_at=NOW() WHERE account_name=$2",
                new_value, account_name,
            )
```
`field` MUST be validated against a whitelist (`_ACCOUNT_SETTINGS_FIELDS = frozenset({"risk_mode", "risk_value", "max_stages", "default_sl_pips", "max_daily_trades"})`) — same pattern as `db.py::_validate_field` at lines 19-33. **Never** inject `field` directly into SQL without the whitelist.

---

## Nginx `limit_req` — outer ring

Current `nginx/telebot.conf` has **no rate limiting** today (`limit_req_zone`/`limit_req` absent). Add the following to the shared nginx `http { }` block (typically `/home/murx/shared/nginx/nginx.conf` or a snippet at `conf.d/limit_req_zones.conf`), NOT the telebot server block:

```nginx
# http { } scope (global; shared across all server blocks) — add ONCE to shared nginx conf
limit_req_zone $binary_remote_addr zone=telebot_login:10m rate=10r/m;
```

Then in `nginx/telebot.conf`, add a location-specific block (new — current file only has `location /`):

```nginx
location = /login {
    limit_req zone=telebot_login burst=5 nodelay;
    limit_req_status 429;

    proxy_pass http://telebot:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Existing catch-all — unchanged
location / {
    proxy_pass http://telebot:8080;
    # … existing SSE proxy config …
}
```

**10r/m rate + burst=5** gives: 10 attempts sustained per minute per IP, burst of 5 before rejection with 429. Picks up where argon2's ~500ms timing cost leaves off. This is **independent of** and **additive to** the app-level 5-per-15-min lockout in `failed_login_attempts`.

**Does this break SSE polling?** No — the `location = /login` exact match doesn't affect `/stream` or `/partials/*`. The existing `location /` block with `proxy_buffering off;` for SSE (line 41) is preserved.

**Proxy headers and `request.client.host`:** FastAPI's `request.client.host` returns the connection peer, which in a nginx reverse-proxy setup is nginx's container IP, not the real client. **For accurate per-IP rate limiting, read `X-Forwarded-For` instead:**
```python
def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
```
Nginx `telebot.conf:37` already sets `X-Forwarded-For`. Use this helper in `/login` POST.

---

## Common Pitfalls

### Pitfall 1: Tailwind purge strips Python-string classes (locked by D-05)
**What goes wrong:** Classes in `dashboard.py` `HTMLResponse(f'<span class="text-green-400">…</span>')` (11 sites verified) get dropped.
**Why:** Default content glob only scans `./templates/**/*.html`.
**Avoid:** `content: [..., "./**/*.py"]` + safelist + CI grep.
**Detect:** Post-build `grep "text-green-400" static/css/app.*.css` must return non-zero lines.

### Pitfall 2: Middleware order (SessionMiddleware must be registered before first request)
**What goes wrong:** `request.session` raises `AssertionError` if SessionMiddleware not installed.
**Why:** Starlette builds a middleware stack at app-start; order of `add_middleware()` calls is reverse (last added wraps innermost).
**Avoid:** Add `SessionMiddleware` at module-top in `dashboard.py`, before any route decorators are evaluated. Verify with a test that `GET /overview` without cookie returns 303 Location `/login`, not 500.

### Pitfall 3: `https_only=True` breaks local dev / tests
**What goes wrong:** Local HTTP returns `Set-Cookie: … Secure`; browser drops the cookie; login silently fails.
**Avoid:** Config-driven: `session_cookie_secure=True` in prod, `False` in dev/test. Default in `.env.dev` to `False`.

### Pitfall 4: `DASHBOARD_PASS` still in `.env` after migration (Pitfall 15 carry-through)
**What goes wrong:** Operator deploys v1.1 with `.env` unchanged → bot boots with both env vars → Pitfall 15 materializes.
**Avoid (D-21):** `config.py` **refuses** to load if `DASHBOARD_PASS` is set; clear error ("Remove DASHBOARD_PASS from .env; set DASHBOARD_PASS_HASH via scripts/hash_password.py"). Hard cutover, no fallback branch.
**Detect:** Unit test: set both env vars, `_load_settings()` must `SystemExit`.

### Pitfall 5: `SESSION_SECRET` entropy validation (D-15)
**What goes wrong:** Weak secret (`"changeme"`) signs cookies that are trivially forgeable.
**Avoid:** `if len(secret.encode()) < 32: SystemExit(...)`. Document `openssl rand -base64 48` as the canonical generator.
**Note:** 32 **bytes** of entropy ≠ 32 characters. A 48-char base64 string decodes to 36 bytes → safe. A 32-char hex string decodes to 16 bytes → **fails**. Docs MUST say "32 bytes"; check `len(secret.encode('utf-8'))` or decode base64 first and check byte length.

### Pitfall 6: HTMX login redirect (`HX-Redirect` vs 303)
**What goes wrong:** HTMX swaps the response body into the form element instead of navigating.
**Avoid:** Set `HX-Redirect: /overview` header on success when `HX-Request` header is present; plain 303 for non-HTMX form fallback.

### Pitfall 7: `request.client.host` returns nginx IP, not real client
**What goes wrong:** Rate limiter keys on the proxy IP; all traffic looks like one attacker.
**Avoid:** Parse `X-Forwarded-For` (see §Nginx section). Confirm nginx passes it (line 37 of `telebot.conf`).

### Pitfall 8: Cookie `SameSite=Strict` breaks cross-navigation login
**What goes wrong:** Strict cookie not sent when user lands on `/overview` after redirect from `/login` if the link was from an external site.
**Avoid:** Use `SameSite=Lax` (default, explicit for clarity). Lax allows top-level navigation.

### Pitfall 9: argon2 verify timing leaks on non-existent user (N/A for password-only)
**What goes wrong:** Skipping verify when user doesn't exist leaks user existence via timing.
**Not applicable this phase:** D-19 — no username field, no user-enumeration surface. Verify always runs against the single hash.

### Pitfall 10: Tailwind v3.4.19 `--minify` + `@apply` interaction with custom `dark.700` color
**What goes wrong:** `@apply bg-dark-800` fails if `dark` is not in the `theme.extend.colors` namespace at build time.
**Avoid:** Ensure `tailwind.config.js` defines the full `dark` palette (see Example 7). Test by building locally before Docker.

### Pitfall 11: Content-hash cache on CI rebuild changes hash for identical input
**What goes wrong:** Every CI rebuild regenerates the hash even if CSS content is byte-identical, busting browser cache unnecessarily.
**Avoid:** Deterministic build — hash the *output*, not the build metadata. The SHA256 of identical minified CSS is identical. The `build_css.sh` script above does this correctly.

### Pitfall 12: `accounts.json` load path in Docker
**What goes wrong:** `docker-compose.yml:9` mounts `./accounts.json:/app/accounts.json:ro`. If the ops team edits it without understanding D-24, they'll expect changes to take effect — they won't.
**Avoid:** `config.py` `load_accounts_config()` logs `"accounts.json is a BOOTSTRAP SEED; runtime edits must go through the DB"` once at startup on any load.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Passlib for password hashing | `argon2-cffi` direct | Ecosystem drift 2022-2024 | Passlib's last release is 2020; breaks on Py 3.13 |
| Tailwind Play CDN in prod | Standalone CLI at build | — (v1.0 carry-over debt) | JIT-in-browser → compiled CSS |
| `HTTPBasic` | Session cookies via `SessionMiddleware` | Phase 5 | Themable login form; cleanly revocable |
| HTML-in-f-strings from Python | (unchanged this phase, but **carefully** purge-compatible via `*.py` content glob) | — | Leave for Phase 7 |

**Deprecated/outdated in `.planning/research/STACK.md`:**
- Tailwind `v3.4.17` in STACK.md's Dockerfile snippet (line 218) — use `v3.4.19`.
- "Keep `DASHBOARD_PASS` for one release as a fallback" (STACK.md §3 line 137) — **overridden by CONTEXT D-20** (hard cutover).
- "One-shot 'first login writes the hash'" (STACK.md gaps/§line 262) — **overridden by CONTEXT D-20**.

---

## Validation Architecture

Nyquist validation is enabled (`.planning/config.json::workflow.nyquist_validation=true`).

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (session-scoped event loop) `[VERIFIED: tests/conftest.py]` |
| Config file | None — pytest uses defaults + `tests/conftest.py` session fixtures |
| Quick run command | `pytest tests/ -x --timeout=30` |
| Full suite command | `pytest tests/` |
| DB harness | Session-scoped `db_pool` fixture backed by `postgresql://telebot:telebot_dev@localhost:5433/telebot` via `docker-compose.dev.yml` |
| `clean_tables` fixture | Auto-truncates signals, trades, daily_stats, pending_orders. **Must extend to the four new tables.** |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UI-01 | `templates/base.html` no longer contains `cdn.tailwindcss.com`; built `app.{hash}.css` referenced via `asset_url()` | smoke | `pytest tests/test_ui_substrate.py::test_no_cdn_script -x` | ❌ Wave 0 |
| UI-02 | `static/vendor/basecoat/basecoat.css` + `basecoat.min.js` exist in repo | smoke | `pytest tests/test_ui_substrate.py::test_basecoat_vendored -x` | ❌ Wave 0 |
| UI-03 | Built CSS contains `text-green-400` + `text-red-400` (Python-inline classes survived purge) | integration | `pytest tests/test_ui_substrate.py::test_py_classes_not_purged -x` (requires Docker build or local tailwind invocation) | ❌ Wave 0 |
| UI-04 | `manifest.json` written; `asset_url('app.css')` returns hashed path | unit | `pytest tests/test_ui_substrate.py::test_asset_url_from_manifest -x` | ❌ Wave 0 |
| UI-05 | `htmx_basecoat_bridge.js` present; `htmx:afterSwap` listener registered | smoke (headless) or manual | MANUAL: load `/overview`, trigger HTMX swap, inspect console for `basecoat.initAll` call. Automated: assert bridge file exists. | ❌ Wave 0 (manual-only documented) |
| AUTH-01 | All 20+ routes with `Depends(_verify_auth)` redirect to `/login` on unauthenticated access | integration | `pytest tests/test_auth.py::test_redirect_unauthenticated -x` (uses `TestClient` without cookie) | ❌ Wave 0 |
| AUTH-02 | `scripts/hash_password.py` produces verifiable argon2 hash; `/login` POST with correct pw succeeds | unit + integration | `pytest tests/test_auth.py::test_argon2_roundtrip -x`, `test_login_success -x` | ❌ Wave 0 |
| AUTH-03 | Bot `SystemExit` if `SESSION_SECRET` < 32 bytes or unset | unit | `pytest tests/test_config.py::test_session_secret_entropy -x` | ❌ Wave 0 |
| AUTH-04 | `/login` POST without matching CSRF cookie+form token → 403 | integration | `pytest tests/test_auth.py::test_csrf_mismatch_rejected -x` | ❌ Wave 0 |
| AUTH-05 | 5 failures in 15 min → 429; success clears counter | integration | `pytest tests/test_auth.py::test_rate_limit_lockout -x` | ❌ Wave 0 |
| AUTH-06 | `GET /logout` clears session, redirects to `/login` | integration | `pytest tests/test_auth.py::test_logout_clears_session -x` | ❌ Wave 0 |
| SET-01 | After seed, `/api/accounts/{name}/settings` returns DB row, not JSON | integration | `pytest tests/test_settings.py::test_db_wins_over_json -x` | ❌ Wave 0 |
| SET-02 | `account_settings` schema has risk_mode, risk_value, max_stages, default_sl_pips, max_daily_trades | schema | `pytest tests/test_db_schema.py::test_account_settings_columns -x` | ❌ Wave 0 |
| SET-04 | Writing a setting produces an audit row per field | integration | `pytest tests/test_settings.py::test_audit_per_field_write -x` | ❌ Wave 0 |
| SET-05 | `SettingsStore.effective(name)` returns a frozen dataclass; copies are cheap | unit | `pytest tests/test_settings_store.py::test_effective_returns_frozen_copy -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_auth.py tests/test_settings.py tests/test_ui_substrate.py tests/test_db_schema.py tests/test_config.py tests/test_settings_store.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green + manual UI-05 HTMX swap smoke test before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_auth.py` — covers AUTH-01..06 (TestClient-based; no nginx)
- [ ] `tests/test_settings.py` — covers SET-01, SET-04
- [ ] `tests/test_settings_store.py` — covers SET-05
- [ ] `tests/test_ui_substrate.py` — covers UI-01..04 (+ smoke for UI-05)
- [ ] `tests/test_db_schema.py` — covers SET-02 (column-exists assertions)
- [ ] `tests/test_config.py` — covers AUTH-03 (SESSION_SECRET entropy) + DASHBOARD_PASS refuse-to-boot (D-21)
- [ ] Extend `tests/conftest.py::clean_tables` to `TRUNCATE accounts, account_settings, settings_audit, failed_login_attempts CASCADE`
- [ ] Add `TestClient` fixture that sets `SESSION_SECRET`, `DASHBOARD_PASS_HASH`, and mounts the app with `session_cookie_secure=False`

---

## Security Domain

Phase 5 ships the front door to a live-money trading dashboard. Security MUST be built in, not bolted on.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | `argon2-cffi` for password verification; fail-fast on weak `SESSION_SECRET` |
| V3 Session Management | yes | Starlette `SessionMiddleware`; signed cookie; 30-day `max_age`; `SameSite=Lax`; `HttpOnly` (default); `Secure` in prod |
| V4 Access Control | partial | Single-admin role; `_verify_auth` on every protected route (20+); `/health` is the only auth-exempt route |
| V5 Input Validation | yes | `pydantic` (transitive via FastAPI) on `Form(...)` params; account_settings field whitelist + CHECK constraints in DDL |
| V6 Cryptography | yes | `argon2-cffi` (never hand-roll); `secrets.token_urlsafe(32)` for CSRF token; `secrets.compare_digest` for cookie↔form comparison |
| V7 Errors & Logging | yes | `failed_login_attempts` is the audit surface; never log submitted password; generic "Invalid credentials" response |
| V10 Malicious Code | n/a | No third-party user-submitted content in this phase |
| V14 Config | yes | `.env` not in git; `env_file: .env` in docker-compose; startup refuse-to-boot on misconfiguration |

### Known Threat Patterns for FastAPI + HTMX + nginx stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Brute-force login | Spoofing | argon2 ~500ms verify + nginx `limit_req` (10r/m) + app-level 5/15min lockout |
| CSRF on login POST | Tampering | Double-submit cookie pattern (D-14) |
| CSRF on authenticated actions | Tampering | Existing `hx-request` header check preserved |
| Session fixation | Spoofing | `request.session["user"] = "admin"` issues a fresh signed value; no session ID shared pre-auth |
| Session hijack via MITM | Info Disclosure | `https_only=True` in prod; HSTS via nginx header (already in telebot.conf:31) |
| Timing attack on password verify | Info Disclosure | `argon2.verify` is constant-time (D-13) |
| User enumeration | Info Disclosure | D-19: no username field, nothing to enumerate |
| Weak session secret → cookie forgery | Tampering | Fail-fast validation at startup (D-15) |
| SQL injection on dynamic field update | Tampering | Whitelist (`_ACCOUNT_SETTINGS_FIELDS`) before f-string into SQL (mirrors existing `db.py::_validate_field`) |
| Stored password in env var leaked via `docker exec env` | Info Disclosure | D-21 hard cutover eliminates plaintext post-migration |
| Clickjacking | Tampering | `X-Frame-Options: DENY` already in nginx/telebot.conf:28 |

### Specific controls this phase MUST ship

1. **Password hash length check at startup**: `if len(settings.dashboard_pass_hash) < 60: SystemExit("DASHBOARD_PASS_HASH looks malformed")`.
2. **Do not log submitted passwords** — not even at DEBUG. Explicit test: `caplog` fixture checks no log record contains the test password.
3. **Generic error message** on failed login: `"Invalid credentials"` — never "no such user" / "wrong password" (N/A for password-only, but preserves discipline).
4. **Rate-limit both 401 and 429 responses** — don't exempt 429s from the failed-login counter (a logged 429 is itself evidence of an attack).
5. **nginx `limit_req_status 429`** (not default 503) — matches app-level response code.
6. **`SameSite=Lax` on session cookie**, **`SameSite=Lax` on CSRF cookie** — both serve in cross-tab navigation scenarios and do not break login.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `curl` | Dockerfile CSS build stage | ✓ (installed via apt `debian:bookworm-slim`) | — | wget if ever needed |
| `tailwindcss` standalone binary (x86_64 linux) | Docker build | ✓ (downloaded from GitHub releases) | v3.4.19 | none — hard dependency |
| `argon2-cffi` + `argon2-cffi-bindings` wheels | runtime | ✓ manylinux wheels on PyPI | 25.1.0 | none — hard dependency |
| `python-multipart` | `Form(...)` parsing | ✓ already in requirements.txt | 0.0.12 | none |
| `asyncpg` | DDL + helpers | ✓ already in requirements.txt | 0.31.0 | none |
| `PostgreSQL` | schema + `failed_login_attempts` table | ✓ via `docker-compose.dev.yml` on 5433; prod via `home/murx/shared/postgres` per user MEMORY | 16 | none |
| `nginx` with `limit_req_zone`/`limit_req` | outer rate limit ring | ✓ existing shared nginx; modules are core, no extra build | — | App-level counter is primary; nginx is belt-and-suspenders, can defer if blocked |
| `openssl rand -base64 48` | operator generates SESSION_SECRET | ✓ universal | — | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |

**Missing dependencies with no fallback:** none identified.
**Missing dependencies with fallback:** none — nginx `limit_req` can be deferred if the shared-nginx config is read-only by the app deploy, but the app-level lockout (D-17) suffices for AUTH-05.

---

## Project Constraints (from CLAUDE.md)

No project-level `./CLAUDE.md` at `/Users/murx/Developer/personal/telebot/CLAUDE.md`. The global `~/CLAUDE.md` describes Figma MCP workflow and Vue 3 / Nuxt conventions that are **not applicable** to this Jinja + HTMX + FastAPI project. No directives to enforce from global CLAUDE.md.

User memory (`MEMORY.md`):
- VPS infrastructure: shared services at `/home/murx/shared/` (postgres, nginx, redis); apps at `/home/murx/apps/`. **Relevant**: the nginx `limit_req` change must be made against the shared nginx, not a per-app nginx.
- No co-author lines in commit messages.
- Don't commit prematurely; wait for user to test.
- VPS/docker commands: give as text to copy-paste, don't run locally.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | HTMX follows `HX-Redirect` header from a POST response by issuing a full-page navigation | Example 5, Example 6 | If HTMX 2.0.4 behaves differently, login succeeds server-side but client stays on `/login`. Verify in `tests/test_auth.py::test_login_htmx_redirect_header`. |
| A2 | Basecoat v0.3.3's `MutationObserver` reliably catches HTMX swaps on all 5 supported partial endpoints | §Basecoat HTMX auto-init | If MutationObserver misses (e.g., `outerHTML` swap with `hx-swap="outerHTML"` on `document.body`), the belt-and-suspenders `htmx:afterSwap` listener covers it. |
| A3 | `tailwindcss-linux-x64` binary at v3.4.19 release URL is still reachable from GitHub release CDN (no deletion / redirect break) | Dockerfile | Build fails at image-build time; fix: check-summed binary committed to repo or mirrored. |
| A4 | The single `Vantage Demo-10k` row in `accounts.json` is representative; no unusual fields not in the 11-field schema | DDL (accounts table) | Minor — the 11 fields cover everything in `accounts.json:2-15`. Ops may later add an optional field; additive-only, no blocker. |
| A5 | `argon2-cffi-bindings` has a manylinux wheel for Python 3.12 on x86_64 | Environment availability | `pip install` fails at image build; fix: install `libargon2-dev` + `build-essential` and build from source (adds ~2min to build). |
| A6 | nginx `proxy_set_header X-Forwarded-For` (line 37 of telebot.conf) passes the real client IP as first value, not a chain | Pitfall 7 / rate-limit keying | If there's an upstream CDN, `X-Forwarded-For` has multiple IPs. Use `X-Real-IP` instead; nginx sets it on line 36. Recommend: use `x-real-ip` header for rate-limit keying (simpler, single-valued). |
| A7 | The compat-shim approximations of v1.0 `.btn-red` colors (`bg-red-900 text-red-300` etc.) exactly match the original hex values | Example 8 | Minor visual regression possible. Original hex values from base.html:22-40 are preserved in the comment; if visual diff surfaces, swap `@apply` for raw CSS with exact hex. Validate via screenshot diff against baseline. |
| A8 | `asset_url()` Jinja global, loaded at module import time in `dashboard.py`, is picked up by TemplateResponse calls | Example 10 | If Jinja env is a separate instance, globals don't propagate; fix: register on `templates.env.globals` explicitly (shown). |
| A9 | `failed_login_attempts` table is safe to TRUNCATE in test `clean_tables` fixture | Validation | Yes — it's a transient rate-limit counter, not durable audit. |
| A10 | `session_cookie_secure` toggle via config handles both prod (True) and pytest TestClient (False) correctly | Pitfall 3 | If TestClient somehow rejects Secure cookies on HTTP, logins in tests fail; fix: explicit fixture override. |

---

## Open Questions (RESOLVED)

1. **Basecoat v0.3.3 version pin vs npm `latest` (0.3.11)** — CONTEXT D-07 locks `0.3.3`. npm's `latest` dist-tag is now 0.3.11. The 0.3.3 assets are still on jsDelivr and work.
   **RESOLVED:** Honor CONTEXT D-07 pin — ship with `basecoat-css@0.3.3`. Note the pin in the commit message and flag version drift as a v1.2 evaluation item.

2. **nginx `limit_req` deploy ownership** — the nginx config lives at `/home/murx/shared/nginx/` (shared across apps). Who owns the edit — the phase plan, or an operator runbook item that ships separately?
   **RESOLVED:** Ship the config snippet in the repo at `nginx/limit_req_zones.conf` plus a documented deploy step in `VPS_DEPLOYMENT_GUIDE.md`. App-level lockout (D-17) is sufficient for AUTH-05 if the nginx deploy lags — the nginx ring is defense-in-depth, not the only defense.

3. **Per-IP vs per-cookie rate-limit key** — D-17 says "per-IP". If the operator is behind a corporate NAT and triggers 5 failures, all their colleagues (same public IP) get locked out.
   **RESOLVED:** Per-IP is correct for a brute-force defense. Colleagues won't reach lockout via normal use (5 attempts / 15min is generous). No change from spec. Rate-limit key is read from `X-Real-IP` with fallback to `request.client.host`.

4. **Audit log actor string source of truth** — D-30 says literal `"admin"`.
   **RESOLVED:** Expose a module-level constant (`AUDIT_ACTOR_DEFAULT = "admin"`) in the settings-write path so a future multi-user extension swaps it to `request.session["user"]` in one place. Current writes pass the constant; Phase 5 does NOT ship multi-user wiring.

5. **CSRF cookie `path=/login` vs `path=/`** — scoping to `/login` is tighter (only sent on login paths).
   **RESOLVED:** Scope the login CSRF cookie to `path=/login`. The HTMX-header CSRF pattern used everywhere else is untouched. This is the literal mechanism that prevents T-5-10 (CSRF strategy conflict).

6. **`_settings` global at `dashboard.py:30` collision with new SettingsStore?** `_settings` is the FastAPI `Settings` (env config). `SettingsStore` is a different object.
   **RESOLVED:** Name the new module-level reference `_settings_store` in `dashboard.py` to avoid shadowing the existing `_settings` env-config global. Plans 01 and 03 honor this name.

---

## Sources

### Primary (HIGH confidence)

- `/Users/murx/Developer/personal/telebot/dashboard.py` — lines 17-75, 219-299 (existing auth + CSRF + inline classes)
- `/Users/murx/Developer/personal/telebot/bot.py` — lines 46-178 (startup sequence)
- `/Users/murx/Developer/personal/telebot/config.py` — full file (env loading pattern)
- `/Users/murx/Developer/personal/telebot/db.py` — lines 1-140 (pool + schema + whitelist validator pattern)
- `/Users/murx/Developer/personal/telebot/templates/base.html` — lines 7-40 (Play CDN + inline styles being retired)
- `/Users/murx/Developer/personal/telebot/Dockerfile` — full file (build stage insertion point)
- `/Users/murx/Developer/personal/telebot/accounts.json` — full file (account schema source of truth)
- `/Users/murx/Developer/personal/telebot/nginx/telebot.conf` — full file (proxy baseline, no limit_req today)
- `/Users/murx/Developer/personal/telebot/tests/conftest.py` — full file (test harness pattern)
- `/Users/murx/Developer/personal/telebot/.planning/research/STACK.md` §1, §2, §3 (already-vetted stack rationale)
- `/Users/murx/Developer/personal/telebot/.planning/research/ARCHITECTURE.md` §5, §7 (login layering, build order)
- `/Users/murx/Developer/personal/telebot/.planning/research/PITFALLS.md` — Pitfalls 10-17 (already-vetted phase 5 pitfalls)
- PyPI `argon2-cffi` JSON API (verified 25.1.0 latest, Python ≥ 3.8)
- GitHub `tailwindlabs/tailwindcss` releases (verified v3.4.19)
- jsDelivr `data.jsdelivr.com/v1/package/npm/basecoat-css@0.3.3` (verified file manifest + HTTP 200 on asset URLs)
- argon2-cffi source `src/argon2/_password_hasher.py` @ main branch (verified API + defaults)
- Basecoat v0.3.3 `dist/js/basecoat.js` source (verified `window.basecoat.initAll()` API + MutationObserver)

### Secondary (MEDIUM confidence)

- basecoatui.com/installation/ (doc fetched — notes v0.3.11 as "current docs", not 0.3.3 specifically)
- starlette.io/middleware/ (SessionMiddleware constructor params; middleware-order specifics not explicitly documented)
- fastapi.tiangolo.com/tutorial/dependencies/ (HTTPException-with-Location pattern for dependency-issued redirects)

### Tertiary (LOW confidence — flagged)

- OWASP CSRF Prevention Cheat Sheet (double-submit cookie pattern) — well-established, but verify against latest OWASP guidance during plan-check.
- Manual reasoning: `argon2-cffi-bindings` manylinux wheel availability for Py 3.12 (A5) — HIGH confidence in practice; LOW until planner runs `pip install argon2-cffi==25.1.0` on a Python 3.12 slim container during Wave 0 and confirms wheel pulls without building.

---

## Metadata

**Confidence breakdown:**
- Standard stack & versions: HIGH — live registry + source verification
- Architecture patterns: HIGH — mapped to specific line ranges in shipped v1.0 code
- DDL: HIGH — mirrors `db.py::_create_tables` pattern exactly; additive-only verified
- Basecoat HTMX auto-init: HIGH — verified in `dist/js/basecoat.js` source
- Nginx `limit_req` specifics: MEDIUM — pattern well-known, but the shared-nginx deploy mechanism is LOW (depends on operator config not visible to this repo)
- Compat shim color fidelity: MEDIUM — approximations of hand-picked hex values; screenshot diff required for verification
- Pitfalls: HIGH — every item anchored to line range or verified primary source

**Research date:** 2026-04-19
**Valid until:** 2026-05-19 (30 days — stable stack; Basecoat is pre-1.0 and may ship breaking changes; argon2-cffi is stable)
