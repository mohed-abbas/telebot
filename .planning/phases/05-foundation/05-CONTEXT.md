# Phase 5: Foundation — UI substrate, auth, and settings data model - Context

**Gathered:** 2026-04-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Land the prerequisites the rest of v1.1 depends on, and nothing more:

1. **UI substrate** — Replace Play-CDN Tailwind with a standalone-CLI build, vendor Basecoat `basecoat-css@0.3.3`, and ship a content-hashed `app.css`. Existing dashboard pages render identically post-swap (compat shim); only `/login` is styled with Basecoat primitives.
2. **Auth** — Replace HTTPBasic with a styled `/login` form backed by argon2 + Starlette `SessionMiddleware`. Hard cutover from plaintext `DASHBOARD_PASS` → `DASHBOARD_PASS_HASH`.
3. **Data model** — Introduce `accounts` + `account_settings` + `settings_audit` + `failed_login_attempts` tables via hand-written additive DDL. DB becomes the runtime source of truth for both accounts and their settings; `accounts.json` becomes a bootstrap seed only.

**Out of this phase:**
- Staged-entry execution logic and `staged_entries` table → Phase 6
- Dashboard redesign (Basecoat restyle of every existing page, mobile responsive, drilldowns, analytics filters) → Phase 7
- Settings UI form (editing settings from the dashboard) → Phase 6 (SET-03)
- Alembic migration tooling → v1.2 (DBE-01)

</domain>

<decisions>
## Implementation Decisions

### UI substrate visual scope
- **D-01:** Phase 5 is substrate-only. Existing pages (`overview`, `positions`, `history`, `analytics`, `signals`, `settings`) keep their current `.card` / `.btn-*` look. Phase 7 owns the Basecoat restyle.
- **D-02:** The built `app.css` includes a **compat shim** that redefines the existing `.card`, `.btn`, `.btn-primary`, `.btn-danger`, status-color classes, etc., using Tailwind utilities so every existing page renders visually identical after the CDN is removed. Shim lives in a dedicated `@layer components` block the Phase 7 restyle will peel away class-by-class.
- **D-03:** Only `/login` uses Basecoat primitives directly — it's the proving ground for the new substrate without touching any existing page.

### Tailwind build pipeline
- **D-04:** Tailwind v3.4 standalone CLI (downloaded during Docker image build, no Node runtime).
- **D-05:** Tailwind `content` glob **must include `./**/*.py`** so classes inlined in `dashboard.py` HTMLResponse fragments aren't purged. CI check greps the built CSS for the set of status classes used in Python strings.
- **D-06:** Output filename is content-hashed (`/static/css/app.{hash}.css`). Template resolves the hashed name via a small manifest (`static/css/manifest.json`) written by the build. No query-string versioning.
- **D-07:** Basecoat (`basecoat.css` + `basecoat.min.js`) is vendored under `static/vendor/basecoat/` at a pinned version (`0.3.3`). No CDN.
- **D-08:** HTMX re-init — add a single `htmx:afterSwap` listener that calls Basecoat's documented JS init on the swapped subtree so interactive components keep working after partial swaps (UI-05).
- **D-09:** Delete the stray `drizzle.config.json` at repo root as part of this phase.

### Login UX
- **D-10:** Login form has **one password field only** — no visible username field. Single-admin model.
- **D-11:** On submit, session cookie is set with a **single 30-day lifetime**. No "remember me" branch, no 8h default. Trusted-device single-operator pattern.
- **D-12:** `/logout` clears the session and redirects to `/login`.
- **D-13:** Constant-time password compare on every attempt (argon2-cffi `verify` is already constant-time).
- **D-14:** Login form POST is CSRF-protected via double-submit cookie pattern on `/login` ONLY. All other (authenticated) routes keep the existing HTMX-header CSRF pattern unchanged.

### Session & startup
- **D-15:** Starlette `SessionMiddleware` with `SESSION_SECRET` env var. Bot **refuses to start** if `SESSION_SECRET` is unset OR below 32 bytes of entropy.
- **D-16:** Session rotation on password change — invalidate by rotating `SESSION_SECRET` (operator runbook item; actual rotation tooling with dual-key grace window is `SESSION-ROTATE`, deferred to v1.2).

### Rate-limit & lockout
- **D-17:** App-level lockout: **5 consecutive failed attempts per IP → reject for 15 minutes**. Tracked in a `failed_login_attempts` table (INSERT row per failure, query last-15-min count per IP on each attempt). Successful login clears the IP's counter.
- **D-18:** Outer ring is nginx `limit_req` (configured in the nginx reverse-proxy layer, already present in v1.0) as belt-and-suspenders.
- **D-19:** No username enumeration surface — password-only form means there's nothing to enumerate.

### Password migration
- **D-20:** **Hard cutover this release.** Ship `scripts/hash_password.py` (CLI: reads a password from stdin, prints the argon2 hash). Deploy requires `DASHBOARD_PASS_HASH` env var set.
- **D-21:** Bot refuses to start if `DASHBOARD_PASS` (plaintext) is still set post-upgrade — clear error message directing the operator to the helper script.
- **D-22:** `DASHBOARD_USER` env var is no longer read (password-only login makes it moot).

### Accounts + settings data model
- **D-23:** Introduce an `accounts` table — one row per trading account with the fields currently in `accounts.json` (name, credentials, broker/server, lot defaults, etc.). **DB is the runtime source of truth** once seeded.
- **D-24:** `accounts.json` becomes a **bootstrap seed only**. On startup, for every account in `accounts.json`, INSERT a row in `accounts` IF NOT EXISTS (idempotent). Existing rows are untouched — DB edits win.
- **D-25:** Removing an account from `accounts.json` does **NOT** delete its DB row (safety — avoid accidental wipe of a live-trading account). An orphaned DB row (no matching JSON entry) is logged at startup but kept.
- **D-26:** Corresponding `account_settings` row is auto-created alongside each new `accounts` row, populated from the JSON defaults.
- **D-27:** All v1.0 code paths that currently call into `AccountConfig` (loaded from JSON) migrate to a `SettingsStore`-style abstraction that reads from `accounts` + `account_settings` in the DB. `AccountConfig` remains as the JSON-parse dataclass used only at seed time.
- **D-28:** Per-account settings (`SET-02`): `risk_mode` (`percent` | `fixed_lot`), `risk_value`, `max_stages`, `default_sl_pips`, `max_daily_trades`. Settings are independently editable at runtime (editing UI is Phase 6's SET-03).

### Settings audit log
- **D-29:** **Every** write to `account_settings` produces one `settings_audit` row per field changed: `(timestamp, account_name, field, old_value, new_value, actor)`.
- **D-30:** `actor` = the session user string. Because this release ships password-only auth, the stored actor is the literal `"admin"` (the role the session cookie authenticates). Schema is future-proof for multi-user.
- **D-31:** No retention TTL. Log volume is tiny; operator forensics matter more than table size.

### Settings snapshot for staged entries (SET-05 prep)
- **D-32:** Phase 5 introduces the `SettingsStore` abstraction and its in-memory cache but does **NOT** implement the "snapshot at signal receipt" logic itself — that logic lives alongside `staged_entries` in Phase 6. Phase 5 only guarantees that `SettingsStore.effective(account_name)` returns a dataclass value that is cheap to copy (so Phase 6 can persist a snapshot into its `staged_entries` row without extra machinery).

### Claude's Discretion
- Exact schema column types / constraints for the four new tables (within the additive-only rule)
- `SettingsStore` cache invalidation strategy (simple dict + reload-on-write is the default)
- How the Tailwind compat shim is organized (single `_compat.css` import vs inline `@layer components` block)
- Exact Basecoat JS re-init API call — verify against v0.3.3 docs during research
- `scripts/hash_password.py` implementation details
- Whether to reset the `failed_login_attempts` counter on success or let old rows age out naturally
- Manifest file format (`manifest.json` schema)

</decisions>

<specifics>
## Specific Ideas

- **"Every existing page must render identically after the CDN swap."** The compat shim is not a nice-to-have — Phase 5 is foundation work, and any visual regression on `overview` / `positions` / `analytics` would be invisible damage to live operations.
- **"One password box, nothing else."** Single-admin bot: no username field, no remember-me toggle, no 2FA prompt. Minimize surface area.
- **"Bot should die loudly at startup if anything is misconfigured."** Missing `SESSION_SECRET`, weak `SESSION_SECRET`, plaintext `DASHBOARD_PASS` still set post-migration, `DASHBOARD_PASS_HASH` not set — all fail-fast with a clear error pointing at the fix.
- **"DB is the source of truth for runtime config."** Operator edits in the DB (directly in v1.1 via CLI/SQL; via dashboard form in Phase 6's SET-03) must always win over stale values in `accounts.json`.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & milestone scope
- `.planning/REQUIREMENTS.md` §UI Foundation (UI-01..UI-05), §Authentication (AUTH-01..AUTH-06), §Per-Account Settings (SET-01, SET-02, SET-04, SET-05) — the 15 requirements this phase delivers
- `.planning/ROADMAP.md` Phase 5 — goal + success criteria (5 items)
- `.planning/PROJECT.md` §Current Milestone — milestone intent, substrate decision lineage
- `.planning/STATE.md` §Blockers/Concerns — five phase-5-specific pitfall notes already flagged

### Research synthesis (HIGH confidence)
- `.planning/research/SUMMARY.md` — executive summary + stack additions + 5 must-mitigate pitfalls
- `.planning/research/STACK.md` — Basecoat v0.3.3, Tailwind v3.4 standalone CLI, argon2-cffi 25.1.0 rationale
- `.planning/research/ARCHITECTURE.md` §1 (SettingsStore design), §5 (login layering), §7 (build order)
- `.planning/research/PITFALLS.md` — specifically Pitfall 10 (Tailwind purge), Pitfall 11 (Basecoat HTMX re-init), Pitfall 12 (CSS cache), Pitfall 13 (CSRF split), Pitfall 14 (session-secret rotation), Pitfall 15 (plaintext env lingering), Pitfall 16 (brute-force rate limiting), Pitfall 17 (additive-only DDL)
- `.planning/research/FEATURES.md` §2 (per-account settings backend layer)

### Codebase intel
- `.planning/codebase/ARCHITECTURE.md` — existing bot.py / dashboard.py / executor.py layering the new `accounts` + `SettingsStore` plugs into
- `.planning/codebase/CONVENTIONS.md` — naming, async patterns, DB helper conventions the new code must follow
- `.planning/codebase/STACK.md` — v1.0 stack baseline (asyncpg, FastAPI, HTMX)

### External docs (verify during research, cite in plans)
- Basecoat UI — `https://basecoatui.com/` + `https://github.com/hunvreus/basecoat` (pin version 0.3.3 release)
- Tailwind standalone CLI — `https://tailwindcss.com/blog/standalone-cli`
- argon2-cffi — `https://argon2-cffi.readthedocs.io/` (25.1.0 API)
- Starlette SessionMiddleware — `https://www.starlette.io/middleware/#sessionmiddleware`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable assets
- `dashboard.py:19,33,47` — current `HTTPBasic()` wiring + `_verify_auth` dependency. Replacement swaps this to a session-cookie dependency; every `Depends(_verify_auth)` call site (20+ routes) keeps the same signature.
- `dashboard.py:_verify_csrf` (existing) — header-based CSRF used by HTMX routes; stays unchanged. Only `/login` gets a double-submit cookie variant.
- `db.py` — existing asyncpg pool wiring; new tables use the same pool, same transaction patterns.
- `config.py::AccountConfig` — JSON-parse dataclass; repurposed as the seed-time type only.
- `templates/base.html:7` — the Play-CDN script tag to remove (UI-01).
- `accounts.json` — remains as seed; no format changes (v1.0 backwards-compat constraint honored).
- `nginx/` — existing reverse-proxy config; `limit_req` directive is the outer rate-limit ring.
- `Dockerfile` — needs a Tailwind build stage (download standalone CLI binary, run build, copy `static/css/app.{hash}.css` + manifest into final image).
- `tests/` — existing pytest + pytest-asyncio fixtures (session-scoped event loop from Phase 4) — new auth tests and DB-seed tests plug in directly.

### Established patterns
- Additive-only DDL (v1.1 milestone policy): `CREATE TABLE IF NOT EXISTS` on boot; no `ALTER TABLE` on v1.0 tables. Lint/CI check for `ALTER TABLE` is a companion deliverable.
- Fail-fast startup validation (`config.py` already does this for other env vars) — new `SESSION_SECRET` / `DASHBOARD_PASS_HASH` checks follow the same pattern.
- HTMX header-based CSRF for dashboard routes — leave alone; don't cross-contaminate with the login form's double-submit cookie.
- Docker image is the unit of deploy; content-hashed CSS filename ties to image tag for cache-bust.

### Integration points
- `bot.py:main` — wire `SettingsStore` before `TradeManager` and `Executor`; run DB seed (upsert `accounts` + `account_settings` from `accounts.json`) after pool creation, before handlers start.
- `dashboard.py` app factory — add `SessionMiddleware`, add `/login` + `/logout` routes, swap `_verify_auth`, add `/static` Basecoat path if not already mounted.
- Every route in `dashboard.py` depending on `_verify_auth` — implementation swap only, signature preserved.
- `config.py` — add `SESSION_SECRET`, `DASHBOARD_PASS_HASH` env readers + fail-fast validators; remove / refuse `DASHBOARD_PASS`.

</code_context>

<deferred>
## Deferred Ideas

- **Settings edit UI** — SET-03 lives in Phase 6. Phase 5 only provides the data layer + audit log; no dashboard form yet.
- **Staged entries + zone watcher + snapshot logic** — Phase 6 (STAGE-01..09, SET-05 implementation).
- **Full Basecoat restyle of every dashboard page, mobile responsive layout, positions drilldown, analytics filters** — Phase 7 (DASH-01..05).
- **`SESSION_SECRET` rotation with dual-key grace window** — tracked as v1.2 `SESSION-ROTATE` in REQUIREMENTS.md.
- **Alembic migration tooling** — v1.2 `DBE-01`.
- **Multi-user / role-based auth, password reset flow, 2FA, passkey/WebAuthn** — explicitly out of scope for v1.1 per REQUIREMENTS.md "Out of Scope".
- **Automated CSS safelist CI check beyond the Python-string class grep** — nice-to-have, only if time remains; Pitfall 10 mitigation is the grep.

</deferred>

---

*Phase: 05-foundation*
*Context gathered: 2026-04-18*
