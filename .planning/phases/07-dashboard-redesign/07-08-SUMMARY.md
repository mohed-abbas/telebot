---
phase: 07-dashboard-redesign
plan: 08
subsystem: ui
tags: [css, cleanup, tailwind, basecoat]

# Dependency graph
requires:
  - phase: 07-01
    provides: Basecoat sidebar baseline + compat shim audit
  - phase: 07-02
    provides: Overview/positions restyle (drops .card-old usage)
  - phase: 07-03
    provides: Positions drilldown restyle
  - phase: 07-04
    provides: Trade history restyle
  - phase: 07-05
    provides: Analytics restyle
  - phase: 07-06
    provides: Settings restyle
  - phase: 07-07
    provides: Signals + staged restyle (last consumer of compat shim)
provides:
  - Phase 5 compat shim removed from CSS pipeline
  - Smaller compiled CSS bundle, cleaner @import graph
affects: [css-pipeline, dockerfile, tests]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  modified:
    - static/css/_compat.css
    - static/css/input.css
    - Dockerfile
    - tests/test_ui_substrate.py
    - templates/partials/account_settings_tab.html  # slug filter on element ids
    - templates/partials/settings_confirm_modal.html  # slug filter on hx-target
    - templates/settings.html  # slug filter on tab id + data-tab-target
    - dashboard.py  # _slug Jinja filter, _append_to_response_body helper
    - static/js/htmx_basecoat_bridge.js  # per-target init (no full initAll)
    - tests/test_settings_form.py  # added persistence + spaced-name regression

key-decisions:
  - "Keep _compat.css file as a tombstone comment rather than deleting it, so reviewers see the intent"
  - "Apply per-component basecoat.init() on the swap target only — full initAll() was closing the mobile sidebar after every HTMX swap"
  - "Add a _slug Jinja filter and apply it everywhere account names appear in HTML id / CSS selectors. Raw URL paths still use the unslugified name."

patterns-established:
  - "Pattern: when mutating a rendered TemplateResponse body, update Content-Length via _append_to_response_body() — Starlette sets it from the initial body and uvicorn enforces it"
  - "Pattern: account names with whitespace must be slugified for HTML id / CSS selector use"

requirements-completed: [DASH-01, DASH-02]

# Metrics
duration: ~25min (cleanup + verification)
completed: 2026-04-23
---

# Phase 07 Plan 08: Compat Shim Removal + Settings Persistence Hardening

## Scope

Plan 08 was originally CSS-only: remove the Phase 5 compat shim now that all
pages are restyled (Plans 01-07). During the human-verify checkpoint a settings
persistence regression surfaced — the per-account settings form appeared not to
save, but the DB write was actually succeeding. The fix landed in this plan
because (a) it had to ship before the human-verify gate could pass, and (b) it
reused this plan's CSS-cleanup window.

## CSS cleanup (original scope)

- Removed `@import './_compat.css'` from `static/css/input.css`
- Replaced `_compat.css` body with a tombstone comment (kept for review history)
- Verified no template references `badge-buy`, `badge-sell`, `btn-red`, `btn-blue`
- `tests/test_ui_substrate.py` updated to reflect the v4-native pipeline
- Dockerfile build stage already runs the v4 CLI; no changes needed

## Settings persistence regression (added scope)

**Symptom:** Operator changes a value on `/settings`, clicks Save, clicks
Confirm — modal disappears, page looks unchanged, audit timeline doesn't
update. Conclusion drawn was "settings don't persist." DB inspection showed
they did.

**Root causes (two independent bugs):**

1. **Invalid HTML id / CSS selector for spaced account names.** The only
   configured account is `Vantage Demo-10k`. Templates rendered
   `id="tab-Vantage Demo-10k"` (invalid HTML5 id; spaces are forbidden) and
   the confirm modal's `hx-target="#tab-Vantage Demo-10k .card"` parsed as
   *"find #tab-Vantage with descendant Demo-10k then .card"* — which finds
   nothing. So after the confirm POST succeeded, HTMX could not swap the
   refreshed tab content and the operator saw no change.

2. **Content-Length not updated when appending OOB toast/modal-clear
   fragments.** The validate and confirm handlers append HTML fragments to the
   rendered `TemplateResponse.body` for OOB swaps. Starlette set
   `Content-Length` at `Response.__init__` from the initial body; mutating
   `.body` afterward without updating the header made uvicorn raise
   `"Response content longer than Content-Length"` and the response 500'd —
   even though the DB write had already succeeded inside the handler.

**Fixes:**

- Added a `_slug` Jinja filter in `dashboard.py` that maps non-alphanumerics
  to `-`. Applied in `settings.html` (tab id + data-tab-target),
  `account_settings_tab.html` (form id), and `settings_confirm_modal.html`
  (hx-target). Raw URL paths still use the unslugified name (FastAPI URL-decodes
  it correctly).
- Added `_append_to_response_body()` helper that appends bytes to
  `response.body` AND updates `response.headers['content-length']`. Both call
  sites (validate error path, confirm success path) routed through it.
  Confirm path also adds an OOB clear of `#modal-root` so the modal closes
  reliably without relying on inline JS.
- Reworked `static/js/htmx_basecoat_bridge.js` to call `basecoat.init()`
  per-component scoped to `evt.detail.target` rather than `basecoat.initAll()`
  on the whole document. The `initAll()` call was resetting the mobile
  sidebar `aria-hidden`/`inert` state on every HTMX swap, closing it
  unexpectedly. While not the persistence bug, it surfaced during the same
  E2E walkthrough.

**Regression coverage:**

- `test_confirm_fixed_lot_mode_persists` — confirms a fixed_lot mode switch
  writes to DB and emits the modal-clear OOB swap.
- `test_settings_renders_with_space_in_account_name` — drives the validate
  step against a name containing whitespace and asserts both the slugified
  tab id renders and the modal's hx-target uses the slug, not the raw name.

## Verification

- All 12 settings form tests pass against the dev DB.
- `tests/test_ui_substrate.py::test_htmx_bridge_installed` updated to assert
  the new per-target init contract (instead of the removed `initAll`).
- Manual E2E in browser against `Vantage Demo-10k`:
  edit `risk_value` 0.05 -> 0.10, Save, Confirm. DB now stores 0.1, audit
  row written, modal closes, tab refreshes to new value, "Settings saved"
  toast appears.

## Files Modified

CSS cleanup (committed earlier in 267aa50, ae190e0):
- `static/css/_compat.css`, `static/css/input.css`, `Dockerfile`,
  `tests/test_ui_substrate.py`

Settings persistence + spaced-name regression (this commit):
- `dashboard.py`, `static/js/htmx_basecoat_bridge.js`, `templates/base.html`,
  `templates/settings.html`, `templates/partials/account_settings_tab.html`,
  `templates/partials/settings_confirm_modal.html`,
  `tests/test_settings_form.py`, `tests/test_ui_substrate.py`

## Next Phase Readiness

- Phase 7 dashboard redesign complete across all eight plans.
- Compat shim retired; CSS pipeline is v4-native + Basecoat-only.
- Settings flow validated end-to-end in browser against the spaced
  production account name.
