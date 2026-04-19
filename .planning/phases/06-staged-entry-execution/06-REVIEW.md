---
status: issues_found
phase: 06-staged-entry-execution
reviewed: 2026-04-20
depth: standard
files_reviewed: 22
findings:
  critical: 1
  warning: 6
  info: 8
  total: 15
---

# Phase 6: Code Review Report

**Reviewed:** 2026-04-20
**Depth:** standard
**Files Reviewed:** 22 (9 Python source, 7 Jinja templates, 1 JS, 5 test files)
**Status:** issues_found

## Summary

Phase 6 (staged-entry execution). The staged-entry state machine, correlator, zone-watch loop, DB schema/helpers, and UI/SSE wiring are coherent and well-tested at the unit level. Cross-cut concerns (D-08 SL guard, D-16 cascade, D-21 kill-switch drain ordering, D-25 idempotency, D-22 terminal cancellation, D-23 dup-guard bypass, D-18 daily-slot accounting) look correctly implemented.

However, there is one CRITICAL production defect: the `Executor._execute_single_account` path constructs a fresh per-account `TradeManager` without propagating the `correlator` or `settings_store` attributes, silently losing all Phase 6 staged behavior on the primary production signal path. Tests pass because they call `tm_with_store.handle_signal(...)` directly and never exercise the executor path.

## Critical Issues

### CR-01: `Executor._execute_single_account` drops correlator + settings_store

**File:** `executor.py:130-144`

**Issue:** `_execute_single_account` constructs a per-call `temp_tm = TradeManager(connectors={...}, accounts=[...], global_config=...)` and invokes `temp_tm.handle_signal(signal)`. The new `TradeManager.__init__` initializes `self.settings_store = None` and does not define `self.correlator`. Neither the parent TM's `correlator` nor its `settings_store` is copied over.

Downstream consequences:
- `_handle_text_only_open` line 277: `correlator = getattr(self, "correlator", None)` returns `None`, so orphans are never registered. Follow-up OPEN signals will never correlate.
- `_handle_text_only_open` line 297: `store = getattr(self, "settings_store", None)` returns `None`, so every stage row's `snapshot_settings` is stored as `{}`, `target_lot` is `0.0`, `default_sl_pips` falls back to the hard-coded `100`, and D-15 per-stage lot sizing never runs.
- `handle_signal` line 236-240 (OPEN branch): `correlator` is `None`; `pair_followup` is never called; the signal always falls through to `_handle_open` (v1.0 standalone path). **This defeats the entire Phase 6 staged-entry feature on the primary signal path.**

The zone-watch loop on the SAME `Executor` references `self.tm` directly and continues to see the correctly-wired `settings_store`, but that loop only fires stages that were created in the first place — and they're never created because the text-only/follow-up path is broken.

Tests do not catch this because `tests/test_staged_executor.py` calls `tm_with_store.handle_signal(...)` directly on a hand-built `TradeManager` with both attributes set.

**Fix:** Copy the two attributes onto the temp TM before dispatch:

```python
async def _execute_single_account(
    self, signal: SignalAction, target_account: str,
) -> list[dict]:
    temp_tm = TradeManager(
        connectors={target_account: self.tm.connectors[target_account]},
        accounts=[self.tm.accounts[target_account]],
        global_config=self.tm.cfg,
    )
    # Phase 6: propagate optional components so staged/correlated paths work.
    temp_tm.settings_store = getattr(self.tm, "settings_store", None)
    temp_tm.correlator = getattr(self.tm, "correlator", None)
    return await temp_tm.handle_signal(signal)
```

Add an integration test driving a signal through `executor.execute_signal(...)` that asserts a staged_entries row is created with non-empty `snapshot_settings` and non-zero `target_lot`.

## Warnings

### WR-01: D-14 pre-flight tolerance is 3× the intended window

**File:** `executor.py:455-456, 515-517` (comment at `executor.py:390`)

**Issue:** Comment at line 390 states the pre-flight check requires price "within band ± 0.5*band_width". Implementation:
```python
band_width = max(band_high - band_low, 0.0)
tolerance = 0.5 * band_width
...
if abs(mid_price - price_center) > band_width + tolerance:  # = 1.5 * band_width
```
Half-window is `1.5 * band_width` from the band center. Full rejection envelope is `3 * band_width` wide — far more permissive than documented.

**Fix:** Align to documented intent:
```python
tolerance = 0.5 * band_width
half_band = band_width / 2.0
if abs(mid_price - price_center) > half_band + tolerance:  # = band_width from center
    ...
```
Add a unit test verifying the drift threshold matches the documented envelope for normal and point-band cases.

### WR-02: Daily-slot TZ mismatch between `mark_signal_counted_today` and `increment_daily_stat`

**File:** `db.py:868` vs `db.py:341-353`

**Issue:** `increment_daily_stat` anchors on `_utc_today()` (Python-side UTC). `mark_signal_counted_today` relies on Postgres column default `date DEFAULT CURRENT_DATE`, which uses the server's `timezone` GUC. If Postgres TZ ≠ UTC, D-18 "1 signal = 1 daily slot" can split across midnight: the same signal_id can double-increment the UTC daily counter at any TZ-offset midnight.

**Fix:**
```python
async def mark_signal_counted_today(signal_id, account_name):
    row = await _pool.fetchrow(
        """INSERT INTO signal_daily_counted (signal_id, account_name, date)
           VALUES ($1, $2, $3)
           ON CONFLICT (signal_id, account_name, date) DO NOTHING
           RETURNING signal_id""",
        signal_id, account_name, _utc_today(),
    )
    return row is not None
```
Or change the column default to `(NOW() AT TIME ZONE 'UTC')::date`. Test at a synthetic midnight boundary.

### WR-03: Settings page crashes when `SettingsStore` is `None`

**File:** `dashboard.py:480-499`, `templates/partials/account_settings_tab.html`

**Issue:** `settings_page` sets `settings_by_account[name] = store.effective(name) if store else None`. The partial dereferences `s.risk_mode`, `s.risk_value`, etc. — `AttributeError` when store is None. `_get_settings_store()` returns `None` when `_executor is None` (possible when `settings.trading_enabled == False`). Other POST handlers explicitly raise 503; GET does not.

**Fix:** Raise 503 in the page when store is missing (matching `settings_validate` and `settings_confirm`).

### WR-04: `_enrich_stage_for_ui` sign rendering inconsistent

**File:** `dashboard.py:391-408`

**Issue:** Mixed typography (Unicode minus `\u2212` vs ASCII `+`) across sibling rows. Label "to next band" misleading when price is already past the band.

**Fix:** Normalize sign characters; clarify "past band" vs "to next band" wording.

### WR-05: SSE media_type assertion brittleness

**File:** `dashboard.py:1038-1042`, `tests/test_pending_stages_sse.py:270-272`

**Issue:** Test asserts on `resp.media_type`; some stacks emit `text/event-stream; charset=utf-8` via `Content-Type`. Low-impact note.

**Fix:** Prefer asserting the `Content-Type` header, or accept both shapes.

### WR-06: `_get_pending_stages` unbounded query on `/staged`

**File:** `dashboard.py:450`, `db.py:792-813`

**Issue:** `staged_page` calls `db.get_pending_stages()` with no limit. During an outage/backlog, row count could reach hundreds/thousands; each row runs O(positions) enrichment. Availability risk.

**Fix:** Add `limit=500` with UI hint, or paginate. Defer to Phase 7.

## Info

### IN-01: Zone-watch stage-1 edge case

**File:** `trade_manager.py:327`

`_handle_text_only_open` inserts stage 1 as `awaiting_zone` then immediately fires at market. On crash between create and fill, stage-1 is left `awaiting_zone` with zero-width band; zone-watch may misbehave. Reconcile handles it after `signal_max_age_minutes`, but a distinct `stage_1_pending_exec` status would be clearer.

### IN-02: Live-price lookup in `_enrich_stage_for_ui` is dead code

**File:** `dashboard.py:377-388`

`_get_all_positions` does not emit `price_current`/`current_price`. Fallback `current_price = None` is always taken. Docstring acknowledges this ("deferred"). Flag as unreachable code today.

### IN-03: `compute_bands` silently accepts `zone_low == zone_high`

**File:** `trade_manager.py:80-81`

Zero-width zones produce N-1 point-bands all at the same price. All fire simultaneously per `stage_is_in_zone_at_arrival`. Intentional (Research Q5) — add a one-line docstring note.

### IN-04: `_daily_limit_warned` never resets at UTC midnight

**File:** `dashboard.py:35, 1115-1122`

Module-level set accumulates account names. Never cleared on day rollover. Fix: track as `set[tuple[str, date]]` or clear on `_utc_today()` change.

### IN-05: Settings tab uses inline `onclick` JS

**File:** `templates/settings.html:15`

~400 chars of inline JS on every tab button. Violates Basecoat convention. Cosmetic — replace with Basecoat tabs primitive or extract to `htmx_basecoat_bridge.js`.

### IN-06: Signal entry_zone gate is safe

**File:** `trade_manager.py:479-480`

Correctly gated: `if signal.entry_zone else 0`. No change.

### IN-07: `_sync_positions` D-24 loop ignores `_trading_paused`

**File:** `executor.py:214-287`

Reconcile continues during kill switch. Arguably correct (filled stays filled, abandoned stays abandoned). Confirm spec.

### IN-08: Tests rely on dashboard module-global state

**File:** `tests/conftest.py:48-66`, `dashboard.py:35`

`_daily_limit_warned` not reset by `wired_dashboard` teardown. No current tests exercise the warning path; latent risk.

**Fix:** Add `dashboard._daily_limit_warned.clear()` to teardown.

---

## Out-of-Scope Notes

- `db.py:544` — 30-day months for archival cutoff; not a correctness issue.
- `bot.py:154, 174` — `_password` popped from raw dicts; still carried into connector's `password` attribute.
- `trade_manager.py:537-542` — `msg_count` daily cap applies to each sibling stage as separate server message (likely intentional).
- `dashboard.py:1019` — `.replace("\n", "")` on rendered HTML partial for SSE `data:` line safety.

---

**Reviewer:** Claude (gsd-code-reviewer)
**Depth:** standard
**Findings:** 1 critical / 6 warning / 8 info (15 total)

**Key paths:**
- `executor.py` (CR-01, WR-01, IN-07)
- `db.py` (WR-02)
- `dashboard.py` (WR-03, WR-04, WR-06, IN-02, IN-04, IN-08)
- `trade_manager.py` (IN-01, IN-03)
- `templates/settings.html` (IN-05)
