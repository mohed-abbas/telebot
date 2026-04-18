---
phase: 5
slug: foundation-ui-substrate-auth-and-settings-data-model
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-18
updated: 2026-04-18
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

> **Filled from:** `05-RESEARCH.md` §Validation Architecture + plans `05-01-PLAN.md`..`05-04-PLAN.md`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio (v1.0 baseline; session-scoped event loop from Phase 4) |
| **Config file** | `pyproject.toml` (pytest section) + `tests/conftest.py` |
| **Quick run command** | `pytest tests/ -x --tb=short` |
| **Full suite command** | `pytest tests/` |
| **Estimated runtime** | ~25s quick, ~90s full (v1.0 baseline 113 tests + ~40 new) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x --tb=short` (all tests; incremental failures surface immediately)
- **After every plan wave:** Run `pytest tests/` (guard against slow-accumulating regression)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-T1 | 01 | 1 | SET-02, SET-04 | T-5-06, T-5-SQLi | 4 tables created idempotently; field whitelist blocks SQL injection; audit row written in same tx as UPDATE | unit + schema | `pytest tests/test_db_schema.py tests/test_settings.py -x --tb=short` | ❌ Wave 0 | ⬜ pending |
| 05-01-T2 | 01 | 1 | SET-01, SET-05 | T-5-07 | SettingsStore.effective() returns frozen dataclass; seed is idempotent; orphans are logged not deleted (D-25) | unit | `pytest tests/test_settings_store.py tests/test_seed_accounts.py -x --tb=short` | ❌ Wave 0 | ⬜ pending |
| 05-01-T3 | 01 | 1 | SET-01 | — | trade_manager.py reads risk_pct / max_lot_size / max_open_trades via SettingsStore.effective() when attached; falls back to AccountConfig otherwise | integration | `pytest tests/test_trade_manager.py tests/test_settings.py tests/test_settings_store.py tests/test_seed_accounts.py tests/test_risk_calculator.py -x --tb=short` | ❌ Wave 0 | ⬜ pending |
| 05-02-T1 | 02 | 1 | UI-02 | T-5-CDN | Basecoat vendored at v0.3.3 (>10 KB JS, contains `initAll`); drizzle.config.json deleted | filesystem smoke | `pytest tests/test_ui_substrate.py::test_basecoat_vendored tests/test_ui_substrate.py::test_drizzle_config_removed -x --tb=short` | ❌ Wave 0 | ⬜ pending |
| 05-02-T2 | 02 | 1 | UI-01, UI-03, UI-04, UI-05 | T-5-08, T-5-09 | Dockerfile has AS css-build stage with pinned Tailwind v3.4.19; build_css.sh emits deterministic hashed filename + manifest; Python-inlined classes survive purge; HTMX bridge present | build smoke + filesystem | `chmod +x scripts/build_css.sh && pytest tests/test_ui_substrate.py -x --tb=short` | ❌ Wave 0 | ⬜ pending |
| 05-03-T1 | 03 | 2 | AUTH-02, AUTH-03 | T-5-04, T-5-05 | Config fails fast on: missing SESSION_SECRET, <32-byte SESSION_SECRET, plaintext DASHBOARD_PASS still set, missing DASHBOARD_PASS_HASH; DASHBOARD_USER silently ignored (D-22) | unit | `pytest tests/test_config.py -x --tb=short` | ❌ Wave 0 | ⬜ pending |
| 05-03-T2 | 03 | 2 | AUTH-01, AUTH-03, UI-01, UI-04 | T-5-02, T-5-DBL-AUTH | SessionMiddleware registered; _verify_auth redirects 303 → /login on page miss, 401 on HTMX miss; HTTPBasic fully removed; base.html uses asset_url() not cdn.tailwindcss.com | integration | `pytest tests/test_auth_session.py tests/test_config.py -x --tb=short` | ❌ Wave 0 | ⬜ pending |
| 05-04-T1 | 04 | 3 | AUTH-01, AUTH-04, AUTH-05, AUTH-06 | T-5-01, T-5-03, T-5-10 | GET /login sets scoped CSRF cookie; POST /login enforces CSRF → rate-limit → argon2 verify; 5 failures → 429; success clears counter; /logout clears session and 303→/login; HTMX emits HX-Redirect | end-to-end | `pytest tests/test_login_flow.py tests/test_rate_limit.py -x --tb=short` | ❌ Wave 0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 sets up test scaffolding and new fixtures before any production code touches the new surfaces. Per-plan scaffolding lives inside each plan's Task 1 (no separate Plan 00) — see advisor guidance.

- [ ] `tests/conftest.py` — extend `clean_tables` TRUNCATE to include `accounts, account_settings, settings_audit, failed_login_attempts` (owned by Plan 01 Task 1)
- [ ] `tests/conftest.py` — add `seeded_account` fixture (owned by Plan 01 Task 1)
- [ ] `tests/test_db_schema.py` — column-exists + CHECK constraint assertions (Plan 01 Task 1; SET-02)
- [ ] `tests/test_settings.py` — audit row written per field write; whitelist blocks injection (Plan 01 Task 1; SET-04)
- [ ] `tests/test_settings_store.py` — frozen dataclass, snapshot copy, reload-on-update cache invalidation (Plan 01 Task 2; SET-05)
- [ ] `tests/test_seed_accounts.py` — idempotent seed, DB wins over JSON, orphan detection (Plan 01 Task 2; SET-01 / D-24 / D-25)
- [ ] `tests/test_ui_substrate.py` — Basecoat vendored, Python content glob, hashed filename + manifest deterministic, HTMX bridge present (Plan 02; UI-01..UI-05)
- [ ] `tests/test_config.py` — SESSION_SECRET entropy, plaintext DASHBOARD_PASS refuse-to-boot, DASHBOARD_USER silently ignored (Plan 03 Task 1; AUTH-03, D-21, D-22)
- [ ] `tests/test_auth_session.py` — SessionMiddleware registered, _verify_auth page vs HTMX behavior, asset_url helper, base.html cutover (Plan 03 Task 2; AUTH-01)
- [ ] `tests/test_login_flow.py` — full happy path + CSRF reject + logout clears session + HTMX HX-Redirect (Plan 04; AUTH-01, AUTH-04, AUTH-06)
- [ ] `tests/test_rate_limit.py` — 5/15min per-IP lockout + success clears counter (Plan 04; AUTH-05, D-17)

Each of these files is created by the earliest task that exercises it; the task's `<behavior>` block defines the assertions it must contain. When the task is implemented it simultaneously creates the test file and makes it pass.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Visual parity of every existing dashboard page after CDN → built-CSS swap | UI-01, UI-02 | Pixel-perfect compat-shim verification needs a human eye | Screenshot overview/positions/history/analytics/signals/settings pre- and post-swap on staging; compare side-by-side; no visible regression |
| `/login` form renders with Basecoat primitives at mobile + desktop widths | AUTH-01 | Layout/type/a11y judgment | Load `/login` at 360px and 1440px, check spacing, focus ring, error banner contrast |
| Content-hashed CSS invalidates browser cache on redeploy | UI-04 | Requires deploy + second browser visit | Deploy, visit dashboard, redeploy with any CSS tweak, hard-refresh check the new hash loads |
| Basecoat JS re-initializes after HTMX partial swaps | UI-05 | Interaction timing on real browser | Trigger an HTMX-returning action (e.g., close-position dialog) and verify the Basecoat dropdown/dialog still works on the swapped fragment |
| nginx `limit_req` on `/login` applies in prod | AUTH-05 (defense-in-depth) | Requires shared-nginx deploy | Operator runbook step: attempt 20 rapid `/login` POSTs from one IP, confirm 429 after burst |
| Bot refuses to start with missing/weak `SESSION_SECRET` or with plaintext `DASHBOARD_PASS` still set | AUTH-03, D-20/D-21 | Startup failure mode | Manual env-var permutation test in staging before prod cutover |
| `scripts/hash_password.py` interactive prompt flow | AUTH-02 | Requires TTY | Operator runs `python scripts/hash_password.py`, enters password twice, copies hash line into .env |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify commands (populated in per-task map above)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (every task has one)
- [x] Wave 0 covers all MISSING references (per-plan Task-1 scaffolding model)
- [x] No watch-mode flags (`-x --tb=short` is the canonical quick-run)
- [x] Feedback latency < 60s (quick pytest run well under 60s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending orchestrator review
