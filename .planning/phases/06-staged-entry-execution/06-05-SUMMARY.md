---
phase: 06
plan: 05
subsystem: pending-stages-observability
tags: [phase-6, ui, sse, htmx, dashboard, stage-08]
requires: [06-01 (db.get_pending_stages, db.get_recently_resolved_stages, staged_entries table)]
provides:
  - "SSE `/stream` named event `pending_stages` (HTML partial) + JSON payload `pending_stages` key"
  - "GET /staged full-page view (active sequences + collapsed Recently resolved)"
  - "GET /partials/pending_stages?all=0|1 (HTMX polling fallback partial)"
  - "overview.html pending-stages top-5 card (SSE-subscribed)"
  - "price-cell tick-flash helper in htmx_basecoat_bridge.js (data-price-cell)"
affects:
  - dashboard.py
  - templates/overview.html
  - templates/staged.html
  - templates/partials/pending_stages.html
  - static/js/htmx_basecoat_bridge.js
  - tests/test_pending_stages_sse.py
tech_added:
  patterns:
    - sse-named-event-with-pre-rendered-html-partial
    - htmx-sse-plus-polling-fallback
    - weakmap-backed-dom-diff-flash-helper
    - jinja-template-render-inside-sse-generator
key_files:
  created:
    - templates/staged.html
    - templates/partials/pending_stages.html
    - tests/test_pending_stages_sse.py
    - .planning/phases/06-staged-entry-execution/06-05-SUMMARY.md
  modified:
    - dashboard.py
    - templates/overview.html
    - static/js/htmx_basecoat_bridge.js
decisions:
  - "[06-05] SSE emits dual events per tick: named `event: pending_stages` with rendered HTML (sse-swap consumer) + default `data:` with JSON (raw-data consumer). Backwards compatible; HTML line collapsed via `replace('\\n','')`."
  - "[06-05] `filled` field is approximated in v1.1 as the stage's own stage_number (the next-to-fire). A precise grouped COUNT per signal_id is deferred to Phase 7 — per-plan documented trade-off."
  - "[06-05] `current_price` lookup against `_get_all_positions()` output keys on `p['account']` (NOT `p['account_name']` as plan template suggested — advisor-caught typo). `_get_all_positions` does not yet expose a live-price field, so in practice `current_price=None` today and the cell renders an em-dash. This is acceptable for v1.1; live-price wiring is deferred (per UI-SPEC TODO)."
  - "[06-05] SSE `_drive_sse_once` test harness invokes the coroutine directly rather than via HTTP stream — httpx.ASGITransport buffers entire responses and hangs on infinite SSE generators. Direct invocation exercises the real production generator including template render + headers."
  - "[06-05] Overview handler seeds initial `stages` context (top-5 via db.get_pending_stages(limit=5)) so the first server-render is non-empty when rows exist; SSE then takes over for live updates. Defensive try/except falls back to empty list so any lookup failure still renders the empty-state (not a 500)."
  - "[06-05] Price-flash helper is an IIFE with a WeakMap cache — does not pollute the global namespace and lets garbage-collected DOM nodes drop their cache entries automatically. Runs on both htmx:afterSwap and htmx:sseMessage."
metrics:
  duration_minutes: 18
  tasks_completed: 2
  files_touched: 6
  completed_date: 2026-04-20
---

# Phase 06 Plan 05: STAGE-08 Pending Stages Observability Panel Summary

## Overview

One-liner: Live pending-stages observability — SSE /stream extended with dual events (named `pending_stages` HTML + JSON `data:`), `/staged` full-page view with collapsed "Recently resolved", `/partials/pending_stages` polling fallback, overview top-5 card, and a WeakMap-backed 150ms price-cell tick-flash helper.

## What Was Built

### SSE payload extension (`dashboard.py::sse_stream`)

Per tick (2s cadence), the generator now emits **two events**:

```
event: pending_stages
data: <div class="card overflow-x-auto" role="region" ...>...</div>

data: {"positions":[...],"accounts":[...],"pending_stages":[...],"timestamp":"..."}
```

- Named event carries the rendered `partials/pending_stages.html` partial so HTMX can swap it directly via `sse-swap="pending_stages"`.
- Default event keeps the existing JSON consumer contract and adds a `pending_stages` array key (D-34).
- HTML is single-line-collapsed before emit (`replace("\n", "")`) because SSE `data:` lines cannot contain raw newlines.
- `X-Accel-Buffering: no` header preserved (Pitfall 18 / T-06-35 fallback also preserved).

### Route signatures

```python
@app.get("/staged", response_class=HTMLResponse)
async def staged_page(request, user=Depends(_verify_auth)) -> HTMLResponse:
    # Renders templates/staged.html with:
    #   active   = [enriched stages from db.get_pending_stages()]
    #   resolved = [labeled stages from db.get_recently_resolved_stages(50)]

@app.get("/partials/pending_stages", response_class=HTMLResponse)
async def pending_stages_partial(request, all: int = 0, user=Depends(_verify_auth)):
    # Default (all=0): top 5 rows. ?all=1: all rows. HTMX polling fallback.
```

### Helpers added to `dashboard.py`

- `_enrich_stage_for_ui(stage, positions)` → UI-display dict
  - `filled` / `total` (v1.1 approximation — see Deferred Issues)
  - `current_price` (None until `_get_all_positions` exposes a price field)
  - `distance_str` (e.g. `"+4.2 pips to next band"` / `"inside band"` / `"—"`)
  - `elapsed` (`mm:ss` for <1h, `hh:mm:ss` otherwise)
- `_label_resolved_stage(r)` → row + `status_label` (e.g. `"Kill-switch drain"`)
- `_RESOLVED_STATUS_LABELS` constant mapping the six terminal statuses.

### Template file inventory

| File | Lines | Purpose |
|------|-------|---------|
| `templates/staged.html` | 59 | Full-page `/staged` view — SSE-subscribed active table + collapsed `<details>` Recently resolved |
| `templates/partials/pending_stages.html` | 60 | Shared partial — 7-column Basecoat table, `role="region"` + `aria-live="polite"`, `data-price-cell` on current-price `<td>`, Basecoat `empty-state` primitive on zero rows |
| `templates/overview.html` (modified) | +13 | Appended pending-stages top-5 card (`sse-swap="pending_stages"`) after Open Positions |
| `tests/test_pending_stages_sse.py` | 332 | 7 integration tests |

### JS helper (`static/js/htmx_basecoat_bridge.js`)

Appended IIFE with private `WeakMap` cache keyed by DOM element. On `htmx:afterSwap` and `htmx:sseMessage`, scans `[data-price-cell]` elements; if the rendered `innerText` differs from the cached value, applies `ring-1 ring-indigo-400/40` for 150ms then removes it. Does not touch the pre-existing Basecoat re-init listener.

## Commits

| Task | Commit | Subject |
|------|--------|---------|
| T1 (RED) | `b4c9f6c` | `test(06-05): failing tests for pending-stages SSE + /staged + /partials/pending_stages` |
| T1+T2 (GREEN) | `8e8fc41` | `feat(06-05): STAGE-08 pending-stages SSE + /staged + overview card + price-flash` |

RED → GREEN sequence observed in `git log`.

## Test Results

**7 new tests green** (scoped to this plan):

```
tests/test_pending_stages_sse.py::test_sse_payload_includes_pending_stages_key PASSED
tests/test_pending_stages_sse.py::test_sse_emits_named_pending_stages_event PASSED
tests/test_pending_stages_sse.py::test_sse_accel_buffering_header_set PASSED
tests/test_pending_stages_sse.py::test_sse_content_type_event_stream PASSED
tests/test_pending_stages_sse.py::test_staged_page_renders_empty_state PASSED
tests/test_pending_stages_sse.py::test_staged_page_includes_recently_resolved_when_present PASSED
tests/test_pending_stages_sse.py::test_partials_pending_stages_all_param PASSED
```

Combined Phase-6 suite (scoped): `24 passed in 11.93s` (Plan 01 + Plan 05 tests).

`tests/test_settings_form.py` (Plan 03) — **10 passed in 1.37s** in isolation → no regression.

### Pre-existing cross-module loop quirk

Running `test_login_flow.py` together with `test_settings_form.py` under the same pytest invocation triggers pre-existing `anyio.from_thread` "attached to a different loop" errors. This occurs on main before this plan's changes (verified by stashing our diff). Not a Plan 05 regression — tracked separately.

## UI-SPEC Conformance Spot-Check

| UI-SPEC requirement | Landed |
|---------------------|--------|
| 7-column pending-stages table with exact headings (`Account`, `Symbol`, `Direction`, `Stages`, `Target band`, `Current price`, `Elapsed`) | Yes |
| Direction badges `badge-buy` / `badge-sell` with uppercase text labels | Yes |
| `data-price-cell` attribute on current-price `<td>` | Yes |
| `role="region"` + `aria-live="polite"` on outer wrapper | Yes |
| Basecoat `empty-state` primitive when `stages` empty — copy "No pending stages" + body "All signals resolved. New staged sequences will appear here automatically." | Yes |
| `<details>` wrapper for "Recently resolved (N)" on full page only | Yes |
| Accent flash (150ms `ring-1 ring-indigo-400/40`) on price-cell diff | Yes |
| HTMX SSE subscribe: `hx-ext="sse" sse-connect="/stream" sse-swap="pending_stages"` — present on BOTH overview card + /staged outer div | Yes |
| Full-page fallback: `hx-get="/partials/pending_stages?all=1" hx-trigger="every 5s"` | Yes |
| Overview heading copy: `Pending Stages` with `(showing top 5)` muted suffix | Yes |
| `/staged` page heading + subhead copy: `Pending Stages` / `Live view of in-flight staged entry sequences. Auto-refreshes every 2 seconds.` | Yes |
| D-36 resolved-status human labels (Kill-switch drain / Stage 1 exited / Abandoned (reconnect) / Failed / Capped / Filled) | Yes |

## Key Decisions (Claude's Discretion)

1. **Dual SSE event emission order** — named `event: pending_stages` first (so HTMX sees the HTML swap before the heavier JSON payload), default `data:` second. Both fire every 2s; reliable ordering because they're in a single `yield` sequence.
2. **Overview handler try/except wrapping** — initial server-render of `stages` swallows exceptions and falls back to `[]`. Rationale: if `_get_all_positions()` or `db.get_pending_stages()` errors at render time, the page still loads with the empty-state rather than returning 500. SSE repopulates on first tick.
3. **Test harness via direct coroutine invocation** — httpx.ASGITransport buffers streaming responses and hangs on infinite SSE generators. The `_drive_sse_once` helper calls `dashboard.sse_stream(stub_request, user='admin')` directly, iterates a bounded number of body-iterator chunks, and closes the iterator. Covers real generator logic (template render, headers, payload shape) without an HTTP round-trip.
4. **WeakMap instead of Map in flash helper** — prevents the cache from pinning detached DOM nodes in memory when HTMX swaps the table.
5. **Distance-to-next-band semantics** — when `current_price` is inside [band_low, band_high], show `"inside band"`. Otherwise render signed pips-to-trigger-edge (band_high for buys, band_low for sells). With `current_price=None` (today), always renders `"—"`.

## Deviations from Plan

### Rule 1 — Bug: plan's helper used wrong key on positions lookup

**Found during:** Task 1 implementation
**Issue:** Plan's pseudo-code for `_enrich_stage_for_ui` matched `p.get("account_name")` against `stage["account_name"]`. `_get_all_positions()` returns dicts keyed `account` (no `_name` suffix), so the predicate would always miss and `current_price` would stay `None` even if the positions list eventually carries a price field.
**Fix:** Use `p.get("account")` for the match. Keep price-field fallback chain `price_current` → `current_price` → `None` for future-proofing.
**Files:** `dashboard.py`
**Commit:** `8e8fc41`

### Rule 3 — Blocker: `authenticated_client` fixture not in conftest

**Found during:** Task 1 test scaffold
**Issue:** Plan's note "reuse from conftest if already added" was optimistic. The fixture chain (`app`, `wired_dashboard`, `seeded_accounts`, `authenticated_client`, `_StubExecutor`, `_StubTM`, `_StubConnector`) lives only in `tests/test_settings_form.py` (module-scoped).
**Fix:** Duplicated the fixture chain into `tests/test_pending_stages_sse.py`. Matches existing per-file fixture idioms used elsewhere in the suite (e.g. `test_staged_db.py` had its own `seeded_signal` before Plan 02 promoted it to conftest). Low-risk duplication; touches no shared file.
**Files:** `tests/test_pending_stages_sse.py`
**Commit:** `b4c9f6c`

### Rule 3 — Blocker: httpx.ASGITransport does not stream SSE responses

**Found during:** Initial RED→GREEN run
**Issue:** `authenticated_client.stream("GET", "/stream")` with ASGITransport buffers the entire response before yielding lines. On an infinite SSE generator (`while True`), it hangs forever. The plan's test code used this pattern verbatim.
**Fix:** Added `_drive_sse_once` helper that invokes `dashboard.sse_stream(request, user='admin')` directly via its coroutine signature, then iterates the returned `StreamingResponse.body_iterator` for a bounded number of chunks. Exercises the same production code path (template render, header wiring, JSON serialization) without the ASGITransport buffering bug.
**Files:** `tests/test_pending_stages_sse.py`
**Commit:** `b4c9f6c` (tests) + `8e8fc41` (implementation that makes them pass)

## Deferred Issues

### Precise `filled / total` stage count (Phase 7)

Current implementation exposes `filled = stage.stage_number` (i.e. the NEXT-to-fire stage's number) as an approximation of how many stages have already filled. A precise grouped `COUNT(*) FROM staged_entries WHERE signal_id=$1 AND status='filled'` per row would add one DB round-trip per row on the 2s SSE cadence. Acceptable trade-off for v1.1 (plan explicitly calls this out); denormalizing `filled_count` on `staged_entries` is the recommended Phase 7 optimization.

### Live current-price on pending-stages rows

`_get_all_positions()` returns MT5 position dicts without a `price_current` field (only `open_price`). The `_enrich_stage_for_ui` lookup is future-ready (matches on symbol+account, falls back through `price_current` → `current_price` → `None`), but today every row renders `—`. A later plan can either (a) extend `_get_all_positions` to call `connector._get_current_price(symbol)` per position, or (b) add a dedicated `/api/prices` SSE payload. Cost-benefit of (a) is one `symbol_info_tick` per open position per 2s tick.

## Threat Model Compliance

| Threat ID | Category | Disposition | Landed Mitigation |
|-----------|----------|-------------|-------------------|
| T-06-31 | Spoofing | mitigate | `/staged`, `/partials/pending_stages`, `/stream` all declare `user: str = Depends(_verify_auth)` |
| T-06-32 | Tampering (XSS via row content) | mitigate | Jinja2 auto-escape ON (phase 5 default); verified via template inspection — `mt5_comment`, `cancelled_reason`, `symbol`, `account_name` all render through `{{ }}` escape |
| T-06-33 | Information Disclosure (signal_id / ticket) | accept | Operator-internal identifiers; single-operator dashboard |
| T-06-34 | DoS (SSE N+5 DB queries) | mitigate | 2s cadence, top-5 cap, index-backed `get_pending_stages` (Plan 01 `idx_staged_entries_active`) |
| T-06-35 | Repudiation (SSE drop) | mitigate | `hx-trigger="every 5s"` + `hx-on::sse-error="this.classList.add('sse-fallback')"` on /staged outer div |
| T-06-36 | EoP (panel action) | accept | Panel is READ-ONLY in v1.1 — no write endpoints added |
| T-06-37 | Tampering (SSE event injection) | accept | HTTPS terminates at proxy; same trust model as existing SSE |

## Self-Check: PASSED

Files verified present:
- `templates/staged.html` — FOUND (59 lines)
- `templates/partials/pending_stages.html` — FOUND (60 lines)
- `tests/test_pending_stages_sse.py` — FOUND (332 lines)
- `static/js/htmx_basecoat_bridge.js` — MODIFIED (contains `data-price-cell` + `ring-indigo-400`)
- `templates/overview.html` — MODIFIED (contains `partials/pending_stages.html` include + `showing top 5`)
- `dashboard.py` — MODIFIED (contains `_enrich_stage_for_ui`, `/staged`, `/partials/pending_stages`, `event: pending_stages`)

Commits verified in `git log --oneline -4`:
- `b4c9f6c` — FOUND (test RED)
- `8e8fc41` — FOUND (feat GREEN)

Acceptance greps (all passing):
- `"pending_stages"` in dashboard.py → 2 (payload key + named event)
- `@app.get("/staged"` in dashboard.py → 1
- `@app.get("/partials/pending_stages"` in dashboard.py → 1
- `_enrich_stage_for_ui` in dashboard.py → 5 (def + SSE + /staged + /partials + overview)
- `get_recently_resolved_stages` in dashboard.py → 1
- `X-Accel-Buffering` in dashboard.py → 1 (preserved)
- `Kill-switch drain` in dashboard.py → 1 (D-36 copy)
- `event: pending_stages` in dashboard.py → 2 (docstring + emit)
- `sse-swap="pending_stages"` in templates → overview.html(1) + staged.html(1)
- `role="region"` + `aria-live="polite"` in partial → 2
- `empty-state`, `No pending stages`, `Recently resolved`, `showing top 5`, `ring-indigo-400` — all present

Tests: `pytest tests/test_pending_stages_sse.py -v` → 7 passed in 9.07s.
Regression check: `pytest tests/test_settings_form.py -v` → 10 passed in 1.37s (Plan 03 intact).
Jinja compile: all 3 templates load without errors.
