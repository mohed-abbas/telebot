---
phase: 06-staged-entry-execution
plan: 03
subsystem: dashboard
tags: [SET-03, settings-form, audit-revert, basecoat, htmx]
requirements: [SET-03]
dependency-graph:
  requires: [06-01]
  provides: ["GET /settings tabs + POST /settings/{a} + /confirm + /revert", validate_settings_form, db.get_settings_audit, db.get_settings_audit_row]
  affects: [dashboard.py, db.py, templates/settings.html, templates/partials/*.html]
tech-stack:
  added: []
  patterns: [basecoat-tabs-inline-shim, htmx-hx-headers-csrf, two-step-modal-confirm, inverted-revert-diff-through-same-confirm]
key-files:
  created:
    - templates/partials/account_settings_tab.html
    - templates/partials/settings_audit_timeline.html
    - templates/partials/settings_confirm_modal.html
    - tests/test_settings_form.py
  modified:
    - dashboard.py
    - db.py
    - templates/settings.html
decisions:
  - "validate_settings_form lives inline in dashboard.py (no new module) — single call site, tight coupling to HTMX partial rendering"
  - "revert path re-opens the SAME /confirm flow with hidden inputs pre-populated to the audit row's old_value (D-28); no separate /revert-confirm endpoint"
  - "AsyncClient + ASGITransport (not fastapi.testclient.TestClient) so tests share the session-scoped asyncpg loop — TestClient spawns its own thread/loop, which triggers 'another operation in progress' under Py3.12+"
  - "Inline onclick tab-switch shim in settings.html (3-line JS) instead of a new htmx_basecoat_bridge helper — one-page, zero-dependency, and keeps the JS surface minimal"
metrics:
  duration: 18min
  completed: 2026-04-20
---

# Phase 06 Plan 03: SET-03 Settings Form Summary

**One-liner:** Per-account tabbed settings form (Basecoat tabs + HTMX) with server-side D-29 hard-cap validation, two-step confirmation modal (diff + dry-run + warning), and audit-log revert that flows through the same /confirm path.

## Route Signatures

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/settings` | Render `templates/settings.html`: 1 Basecoat tab per account + effective settings + 50-row audit timeline |
| POST | `/settings/{account_name}` | Validate hard caps → 422 partial on error, modal HTML on valid diff, quiet "No changes" on no-op |
| POST | `/settings/{account_name}/confirm` | Apply each changed field via `SettingsStore.update` (atomic settings+audit write); re-render tab partial |
| POST | `/settings/{account_name}/revert?audit_id=N` | Return the same confirm-modal pre-populated with the inverted diff; Confirm posts to `/confirm` (revert is itself audited) |

All POST routes: `user: str = Depends(_verify_auth), _csrf=Depends(_verify_csrf)`.
CSRF gate = presence of `hx-request` header (D-31 double-submit model).

## Validator Rules

`validate_settings_form(form, max_lot_size) -> (parsed_dict, errors)`

| Field | Rule | Error message format |
|-------|------|----------------------|
| `risk_mode` | ∈ {"percent", "fixed_lot"} | `Risk mode must be "percent" or "fixed_lot".` |
| `risk_value` (percent) | `0 < v ≤ 5.0` | `risk_value must be between 0 and 5.0.` |
| `risk_value` (fixed_lot) | `0 < v ≤ max_lot_size` | `Risk value exceeds max_lot_size for this account.` |
| `max_stages` | `1 ≤ v ≤ 10` | `max_stages must be between 1 and 10.` |
| `default_sl_pips` | `1 ≤ v ≤ 500` | `default_sl_pips must be between 1 and 500.` |
| `max_daily_trades` | `1 ≤ v ≤ 100` | `max_daily_trades must be between 1 and 100.` |

Parsed dict is empty when errors is non-empty. Integer parse errors return `{field} must be an integer.` messages.

## Templates (line counts + role)

| File | Lines | Role |
|------|-------|------|
| `templates/settings.html` | 35 | Page shell: tabs wrapper + tabpanel per account + `#modal-root` slot |
| `templates/partials/account_settings_tab.html` | 53 | 5-field form + `{% include settings_audit_timeline %}` |
| `templates/partials/settings_audit_timeline.html` | 37 | Audit table with timestamp/field/old→new/actor/Revert button |
| `templates/partials/settings_confirm_modal.html` | 58 | Dialog with diff table + dry-run block + alert-destructive warning + Confirm/Discard |

All 4 templates compile (Jinja2 Environment syntax-check passes).

## UI-SPEC Conformance Spot-Check

| Check | Location | Verified |
|-------|----------|----------|
| `role="tablist"` | settings.html:9 | ✓ |
| `role="tab"` buttons per account | settings.html:11 | ✓ |
| `role="tabpanel"` per account | settings.html:21 | ✓ |
| `role="dialog"` on modal | settings_confirm_modal.html:1 | ✓ |
| `alert alert-destructive` warning banner | settings_confirm_modal.html:37 | ✓ |
| Primary CTA `btn btn-primary` (Save settings / Confirm change) | tab + modal | ✓ |
| Revert button `btn btn-blue` | settings_audit_timeline.html:24 | ✓ |
| Error text `text-xs text-red-400` + `role="alert"` | account_settings_tab.html (5 fields) | ✓ |
| Helper text `text-xs text-slate-500` | account_settings_tab.html (5 fields) | ✓ |
| Copy: "Save settings" verbatim | account_settings_tab.html:49 | ✓ |
| Copy: "Confirm change" / "Discard changes" | settings_confirm_modal.html | ✓ |
| Copy: "Revert change" | settings_audit_timeline.html:24 | ✓ |
| Copy: "This applies to signals received AFTER you confirm. In-flight staged sequences are unaffected." | settings_confirm_modal.html:38 | ✓ |
| Client min/max echo of server hard caps | account_settings_tab.html (risk_value max=5.0, max_stages max=10, default_sl_pips max=500, max_daily_trades max=100) | ✓ |
| Typography: `text-2xl font-semibold` page h2, `text-lg font-semibold` card h3 | settings.html:3 + tab:52 | ✓ |
| Spacing: `p-6` card, `p-8` modal, `space-y-4` form, `mt-6` section break | across files | ✓ |

## Tests

**File:** `tests/test_settings_form.py` (329 lines, 10 tests — all passing).

| # | Test | D-ref |
|---|------|-------|
| 1 | `test_settings_get_renders_tabs_per_account` | D-26 |
| 2 | `test_post_rejects_without_htmx_header` (403) | D-31 / T-06-17 |
| 3 | `test_post_hard_cap_risk_value_percent_over_5` (422) | D-29 / T-06-15 |
| 4 | `test_post_hard_cap_max_stages_over_10` (422) | D-29 |
| 5 | `test_post_hard_cap_default_sl_pips_over_500` (422) | D-29 |
| 6 | `test_post_valid_renders_modal` | D-27 |
| 7 | `test_post_no_change_bounces_quietly` | — |
| 8 | `test_confirm_writes_audit_row` | D-27 / T-06-18 |
| 9 | `test_revert_post_renders_modal_with_inverted_diff` | D-28 |
| 10 | `test_revert_confirm_writes_new_audit_row` | D-28 / T-06-19 |

**Regression:** `tests/test_settings.py` (5 tests) + `tests/test_settings_store.py` (6 tests) still pass — 21/21 green across all settings tests.

## DB Helpers Added

`db.get_settings_audit(account_name: str, limit: int = 50) -> list[dict]` — newest-first audit rows for one account (id, account_name, field, old_value, new_value, actor, timestamp).
`db.get_settings_audit_row(audit_id: int) -> dict | None` — single row lookup by id (powers the revert path).

Both read the existing `settings_audit` table (column is `timestamp` not `created_at`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] db.get_settings_audit / get_settings_audit_row did not exist**
- **Found during:** Task 1 (writing tests)
- **Issue:** Plan's interfaces section claimed Phase-5 delivered these helpers; grep confirmed only the `settings_audit` table DDL (db.py:185) and a write path (`update_account_setting`) existed. No read helper. Revert flow needs both.
- **Fix:** Added both helpers in db.py (after `update_account_setting`), using `timestamp` column (not the plan's referenced `created_at` — the schema column is `timestamp`).
- **Commit:** c0af6ca

**2. [Rule 3 — Blocking] Schema column is `timestamp`, not `created_at`**
- **Found during:** Task 2 (template + helper alignment)
- **Issue:** Plan's `settings_audit_timeline.html` template referenced `row.created_at.strftime(...)`. Actual column is `timestamp TIMESTAMPTZ` (db.py:187).
- **Fix:** Template uses `row.timestamp.strftime(...)`; helper returns `timestamp` key.
- **Commit:** 0d56073

**3. [Rule 3 — Blocking] AsyncClient over ASGITransport instead of TestClient**
- **Found during:** Task 1 (first test run)
- **Issue:** Plan suggested building `authenticated_client` on Phase-5's `test_login_flow.py` `TestClient` pattern. Under Python 3.14 `TestClient` spawns a worker thread with its own event loop; the asyncpg pool created in conftest's session-scoped loop then rejects cross-loop queries with `InterfaceError: another operation is in progress`. (Phase-5's `test_login_flow.py` tests are already skipped in this environment for the same reason — a pre-existing gap, not a regression this plan introduces.)
- **Fix:** Use `httpx.AsyncClient(transport=ASGITransport(app=...))` so the ASGI app runs on the same loop as the pool. Tests now execute cleanly against the real DB.
- **Commit:** c0af6ca

**4. [Rule 2 — Critical functionality] Tab switching needs a tiny inline JS shim**
- **Found during:** Task 2 (template authoring)
- **Issue:** Basecoat's `basecoat.min.js` exposes tabs but requires specific data-attr conventions; rather than load-test the vendored lib here, I inlined a 3-line onclick function on each tab button that toggles `data-state` + `.hidden`. Keeps settings.html self-contained; no risk of a vendor-lib mismatch breaking the operator UI.
- **Fix:** Inline `onclick` handler on `role="tab"` buttons in settings.html.
- **Commit:** 0d56073

### Plan Mapping

- **Plan Task 1 (routes + tests)** → 2 commits: `test(06-03)` c0af6ca (RED) + `feat(06-03)` 0d56073 (GREEN).
- **Plan Task 2 (templates)** → included in the GREEN commit (routes need templates to render the 422/modal/confirm paths, so they ship together).

The plan's two-task split was preserved in the commit body (Task 1 and Task 2 noted explicitly) but atomic-per-task separation was collapsed because Task 1's tests fail without Task 2's templates.

## Commits

| Commit | Message |
|--------|---------|
| `c0af6ca` | `test(06-03): failing route tests + get_settings_audit helpers` |
| `0d56073` | `feat(06-03): SET-03 settings form — routes + templates + validator` |

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED  | c0af6ca | 10 failing tests + db read helpers scaffolded |
| GREEN | 0d56073 | 10 tests pass; all UI-SPEC spot-checks pass |
| REFACTOR | — | Not needed (initial implementation already minimal) |

## Acceptance Criteria (from plan)

- ✓ GET `/settings` handler exists (dashboard.py:334)
- ✓ POST `/settings/{account_name}` exists (dashboard.py:485)
- ✓ POST `/settings/{account_name}/confirm` exists (dashboard.py:545)
- ✓ POST `/settings/{account_name}/revert` exists (dashboard.py:585)
- ✓ `Depends(_verify_csrf)` count = 9 (was 6 pre-edit, +3 for the new POSTs)
- ✓ `validate_settings_form` defined inline in dashboard.py
- ✓ Hard-cap literals present for max_stages (1–10), default_sl_pips (1–500), max_daily_trades (1–100)
- ✓ `pytest tests/test_settings_form.py` — 10/10 green
- ✓ No regression on `tests/test_settings.py` + `tests/test_settings_store.py` (11 tests green)
- ✓ Jinja2 compile succeeds for all 4 templates
- ✓ All UI-SPEC required classes present (role=tablist, role=dialog, btn-primary, alert-destructive, text-red-400, client min/max echoes)
- ✓ Verbatim UI-SPEC copywriting present ("Save settings", "Confirm change", "Discard changes", "Revert change", D-30 warning banner text)

## Self-Check: PASSED

- FOUND: dashboard.py (modified; 4 new routes + validator + 3 helpers)
- FOUND: db.py (modified; get_settings_audit + get_settings_audit_row)
- FOUND: templates/settings.html (rewritten)
- FOUND: templates/partials/account_settings_tab.html (new)
- FOUND: templates/partials/settings_audit_timeline.html (new)
- FOUND: templates/partials/settings_confirm_modal.html (new)
- FOUND: tests/test_settings_form.py (new, 10 tests green)
- FOUND: c0af6ca (RED commit)
- FOUND: 0d56073 (GREEN commit)
