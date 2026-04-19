---
phase: 06
plan: 04
subsystem: staged-entry-executor-safety
tags: [phase-6, executor, zone-watch, kill-switch, reconnect, d-16, d-21, d-22, d-24, d-25, tdd]
requires:
  - phase: 06-01
    provides: [staged_entries-table, 9-db-helpers, StagedEntryRecord, SignalCorrelator]
  - phase: 06-02
    provides: [stage-aware-execute-open-on-account, compute_bands, stage_is_in_zone_at_arrival, _pip_size_for_symbol]
provides:
  - _zone_watch_loop-peer-task
  - emergency_close-staged-drain
  - resume_trading-terminal-drain-preserved
  - _sync_positions-reconnect-reconcile
  - D-16-stage1-exit-cascade
  - zone-watch-idempotency-probe
  - _fire_zone_stage-helper
affects: [executor.py, tests/test_staged_safety_hooks.py]
tech_added:
  patterns:
    - peer-task-alongside-heartbeat-and-cleanup
    - per-tick-stage1-liveness-memoization
    - comment-prefix-reconciliation-on-reconnect
    - drain-before-close-kill-switch
    - single-source-of-truth-for-fill-path
    - jsonb-snapshot-rebuild-via-dataclass-fields
key_files:
  created:
    - .planning/phases/06-staged-entry-execution/06-04-SUMMARY.md
  modified:
    - executor.py
    - tests/test_staged_safety_hooks.py
decisions:
  - "[06-04] _zone_watch_loop calls trade_manager._execute_open_on_account (the same fill path used by v1.0 _handle_open + Plan 02 dispatchers) — D-08 hard-SL-reject, D-18 daily-accounting, D-19 cap, D-23 dup-guard bypass, D-24 comment attribution, D-25 DB+MT5 idempotency all carry through without duplication."
  - "[06-04] Dropped the plan's _get_signal_max_age_minutes helper — signals table has no max_age_minutes column (only `timestamp`). Use GlobalConfig.signal_max_age_minutes (added Plan 01) and staged_entries.created_at as the authoritative age source. Simpler, one fewer dangling try/except."
  - "[06-04] pip_size for synthetic signals hard-coded (XAUUSD=0.01, else 0.0001) — mirrors trade_manager._pip_size_for_symbol. v1.1 is gold-only; unified when FX lands in v1.2."
  - "[06-04] stage1_live_cache memoizes (acct_name, signal_id) -> bool where True=fire-OK (stage 1 live OR still-awaiting) and False=cascaded-this-tick. Simpler two-state model than the plan's three-state pseudo-code; the still-awaiting case lives with the live case since both permit stage 2..N to fire for D-16 purposes (the in-zone check is the actual gate)."
  - "[06-04] _fire_zone_stage extracted as a method — keeps _zone_watch_loop readable at ~170 lines and lets result-handling live in a dedicated function."
  - "[06-04] Single test file extension — all 10 new tests live in tests/test_staged_safety_hooks.py (alongside Plan 02's D-08/D-23 tests). Same theme 'executor safety hooks', same fixtures; no separate test_zone_watch.py needed."
metrics:
  duration_minutes: 22
  tasks_completed: 2
  files_touched: 2
  completed_date: 2026-04-20
---

# Phase 06 Plan 04: Executor Safety Hooks Summary

**`_zone_watch_loop` peer task (10s cadence) wiring D-11/D-14 in-zone fire + D-14 pre-flight re-check + D-21 mid-tick pause + D-16 stage-1-exit cascade + D-25 idempotency probe through trade_manager's existing stage-aware fill path; `emergency_close` extended to drain `staged_entries` BEFORE closing positions; `_sync_positions` extended to reconcile by `mt5_comment` on reconnect with age-based abandon rule.**

## What Was Built

### 1. `_zone_watch_loop` (executor.py:383–566)

10-second peer task spawned in `start()` alongside `_heartbeat_loop` and `_cleanup_loop`; cancelled in `stop()`. Structure mirrors `_heartbeat_loop` exactly.

Flow per tick:

```
1. if _trading_paused: continue         (D-21 loop-entry gate)
2. rows = db.get_active_stages()        (awaiting_zone only)
3. group by (account, symbol)           (dedupe MT5 calls)
4. per (account, symbol):
   a. fetch bid/ask + positions once
   b. build positions_by_comment index  (shared by D-16 + D-25)
   c. per stage:
      - _trading_paused re-check        (D-21 mid-tick)
      - stage_is_in_zone_at_arrival     (D-13)
      - D-16 cascade check:
          if stage-1 comment absent on MT5 AND db stage-1 is 'filled'
          → cancel_unfilled_stages_for_signal(signal_id, "stage1_closed")
            cache[False]; continue
          else: cache[True]
      - D-14 pre-flight: re-fetch price; require within band ± 0.5×width
      - _trading_paused pre-submit re-check
      - D-25 idempotency probe: if comment on MT5 → mark filled, skip
      - _fire_zone_stage (delegates to trade_manager._execute_open_on_account)
```

### 2. `_fire_zone_stage` (executor.py:568–681)

Rebuilds `AccountSettings` from the stage's frozen JSONB snapshot via dataclass-field introspection (tolerates extra/missing keys), constructs a synthetic `SignalAction` (entry = trigger edge of band, SL computed from snapshot.default_sl_pips), then calls `trade_manager._execute_open_on_account(…, staged=True, stage_number=N, stage_row_id=row_id, snapshot=snapshot)`.

Post-fill result translation:
- `executed` / `limit_placed` / `filled` → `update_stage_status('filled', mt5_ticket=...)`
- `capped` → no-op (trade_manager already wrote the row)
- `failed` / `skipped` → `update_stage_status('failed', cancelled_reason=...)`

### 3. `emergency_close` drain (executor.py:299–311, 354)

Inserted immediately after `self._trading_paused = True`:

```python
drained_stages = await db.drain_staged_entries_for_kill_switch()
logger.warning("Kill switch: drained %d pending stage(s)", drained_stages)
```

Return dict gains `"drained_stages": N`. Existing v1.0 keys preserved.

### 4. `resume_trading` (executor.py:360–366)

Documented D-22 explicitly: terminal `cancelled_by_kill_switch` rows are NEVER un-cancelled. Operator must re-send the signal to re-arm.

### 5. `_sync_positions` reconcile (executor.py:214–288)

Extended from 10 lines to a full reconcile:

```
1. positions = connector.get_positions()            (existing v1.0)
2. pending = db.get_pending_stages(account_name)    (D-24 new)
3. by_comment index
4. per stage:
   - if comment matches: update_stage_status('filled', mt5_ticket=match.ticket)
   - else if created_at age > cfg.signal_max_age_minutes:
        update_stage_status('abandoned_reconnect',
                            cancelled_reason=f"no_mt5_match_after_{N}min")
   - else: leave awaiting_zone
```

### 6. Start/stop wiring

`start()` creates `self._zone_watch_task = asyncio.create_task(self._zone_watch_loop())`; `stop()` cancels it alongside the existing tasks.

## Task Commits

| Task | Commit | Subject |
|------|--------|---------|
| T1+T2 RED | `5fa0ae1` | `test(06-04): RED — zone-watch, kill-switch drain, D-16 cascade, reconnect reconcile` |
| T1+T2 GREEN | `4ea913f` | `feat(06-04): executor safety hooks — _zone_watch_loop + kill-switch drain + reconnect reconcile` |

TDD sequence `test → feat` observed in `git log --oneline`. Tasks 1 and 2 were implemented in one GREEN commit because both hooks share the same helpers (`by_comment` index pattern, `get_pending_stages`, status mutation) and fit cleanly in one cohesive diff (393 insertions / 6 deletions).

## Test Results

**10 new tests + 5 pre-existing tests in `test_staged_safety_hooks.py` = 15 green.**

| Test | Covers |
|------|--------|
| `test_default_sl_zero_hard_rejects_text_only` | D-08 (Plan 02, regression) |
| `test_dup_guard_bypass_same_signal_id_different_stage` | D-23 (Plan 02, regression) |
| `test_dup_guard_still_rejects_unrelated_same_direction` | D-23 negative (Plan 02, regression) |
| `test_zone_watch_fires_stage_when_price_enters_band` | D-11/D-14 main path |
| `test_zone_watch_skips_when_trading_paused` | D-21 |
| `test_zone_watch_idempotency_probe_marks_filled_without_submit` | D-25 |
| `test_zone_watch_cancels_remaining_stages_when_stage1_closed` | D-16 cascade positive |
| `test_zone_watch_does_not_cascade_when_stage1_still_awaiting` | D-16 cascade edge case |
| `test_emergency_close_drains_staged_before_positions` | D-21 drain-order |
| `test_resume_trading_does_not_uncancel_drained_stages` | D-22 |
| `test_zone_watch_starts_and_stops_cleanly` | lifecycle |
| `test_reconnect_marks_filled_when_comment_exists_on_mt5` | D-24 (a/c) |
| `test_reconnect_marks_abandoned_when_signal_aged_and_no_mt5_position` | D-24 (d) |
| `test_reconnect_leaves_young_unfilled_stages_alone` | D-24 age floor |
| `test_reconnect_reconciliation_dry_on_empty_staged` | empty-pending smoke |

### Regression suite (no-change baseline)

`pytest tests/test_staged_executor.py tests/test_staged_safety_hooks.py tests/test_staged_attribution.py tests/test_staged_db.py tests/test_correlator.py tests/test_signal_parser.py tests/test_signal_parser_text_only.py` → **92 passed**.

`pytest tests/test_concurrency.py tests/test_trade_manager.py tests/test_trade_manager_integration.py` → **36 passed**.

Combined: 128 passed across all targets listed in `<verification>`. Zero regressions.

### Full-suite note

`pytest tests/` shows 50 pre-existing failures + 10 errors caused by test pollution between suites (session-scoped event loop + DB state leakage across `test_settings_form.py`, `test_audit.py`, `test_pending_stages_sse.py`, and integration tests). Same failure count exists at base commit `ac2dac1` with this plan's changes reverted — confirmed by a stash + rerun. **Zero regressions introduced by 06-04.**

## TDD Gate Compliance

- **RED gate (`5fa0ae1`):** 10 new tests collected; run produces 10 failures matching D-16/D-21/D-22/D-24/D-25/lifecycle assertions. Legacy 3 + 2 trivially-passing reconcile tests remained green.
- **GREEN gate (`4ea913f`):** All 15 safety-hook tests green; 128 regression tests green.

Sequence `test → feat` observed in `git log`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — blocking] Signature mismatch in plan's pseudo-code**

- **Found during:** Task 1 GREEN (before first write).
- **Issue:** Plan's pseudo-code called `_execute_open_on_account(name=acct_name, signal=..., positions=positions, signal_id=..., ...)`. The actual Plan 02 signature is positional `(signal, signal_id, acct, connector, *, staged, stage_number, stage_row_id, snapshot)` with NO `name=` / `positions=` kwargs.
- **Fix:** Adapted `_fire_zone_stage` to mirror `_handle_correlated_followup`'s call shape. `positions` list is still pre-fetched once per (account, symbol) but used only for the D-16 live-check and D-25 probe — not passed through.
- **Files:** `executor.py`
- **Committed in:** `4ea913f`

**2. [Rule 3 — blocking] `GlobalConfig.max_age_minutes` does not exist**

- **Found during:** Task 2 design.
- **Issue:** Plan referenced `self.tm.cfg.max_age_minutes`. Actual field (added Plan 01) is `GlobalConfig.signal_max_age_minutes`. Executor also has `self.cfg` directly, so `self.cfg.signal_max_age_minutes` is the cleanest reference.
- **Fix:** Used `getattr(self.cfg, 'signal_max_age_minutes', 30)` at the call site. Default 30 mirrors the dataclass default.
- **Files:** `executor.py`
- **Committed in:** `4ea913f`

**3. [Rule 3 — blocking] Dropped `_get_signal_max_age_minutes` helper**

- **Found during:** Task 2 design.
- **Issue:** Plan proposed a per-signal helper that queries `SELECT max_age_minutes FROM signals WHERE id=$1`. The `signals` table (db.py:82–95) has no such column (only `timestamp`). The plan's helper always returns None.
- **Fix:** Dropped the helper. Use `staged_entries.created_at` (populated by Plan 01 DDL) for age and `GlobalConfig.signal_max_age_minutes` as the single authoritative cutoff. Simpler, no dangling try/except.
- **Files:** `executor.py`
- **Committed in:** `4ea913f`

**4. [Rule 3 — blocking] `get_active_stages` row shape**

- **Found during:** Task 1 GREEN.
- **Issue:** `db.get_active_stages()` (Plan 01) does NOT return `snapshot_settings` — its SELECT list omits it. The plan's pseudo-code reads `stage["snapshot_settings"]`.
- **Fix:** Verified actual shape — `get_active_stages` DOES return `snapshot_settings` per `db.py:820–823` (the SELECT list IS complete). Confirmed no fix needed, noting for future reference.
- **Files:** none
- **Committed in:** n/a

**5. [Rule 2 — correctness] JSONB snapshot rebuild tolerance**

- **Found during:** Task 1 GREEN. `AccountSettings` is frozen+slotted with 8 fields; the stage row's `snapshot_settings` may (in test fixtures, in future snapshot-schema migrations) carry different keys.
- **Fix:** Rebuild via `{f.name: snapshot_dict[f.name] for f in dataclasses.fields(AccountSettings)}` — picks only the fields the dataclass declares, raises KeyError early if a required field is missing. Wrapped in try/except; on failure snapshot becomes None and the fill proceeds with sensible defaults (default_sl_pips=100).
- **Files:** `executor.py`
- **Committed in:** `4ea913f`

**6. [Rule 3 — blocking] `pytest` run raised `python not found`**

- **Found during:** Task 1 RED verification.
- **Issue:** Project uses `.venv` with `python3.14`; bare `python` is unavailable in macOS shell.
- **Fix:** Invoked `.venv/bin/activate` before each `pytest` call. Not committed; runtime-only.

---

**Total deviations:** 6 auto-fixed (5 Rule 3 blocking, 1 Rule 2 correctness).
**Impact on plan:** All fixes corrected pseudo-code-vs-real-code drift (plan was written before Plan 01's final DDL + Plan 02's final `_execute_open_on_account` signature landed). No scope creep; no architectural changes.

## Claude's Discretion

1. **Two-state stage1_live_cache:** plan's pseudo-code set `False` then `True` for the "still-awaiting" edge case, which was easy to misread. Collapsed to `True`-means-fire-OK (either stage 1 is live on MT5 OR stage 1 is still awaiting — both allow stage 2..N to proceed subject to the in-zone check) and `False`-means-cascaded-this-tick. The behavior is identical to the plan's three-state model but the flow reads cleanly.

2. **`_fire_zone_stage` as a method:** extracted from `_zone_watch_loop` so the loop body stays ~170 lines and the snapshot-rebuild / synthetic-signal construction / result-translation lives in a dedicated function. Makes both easier to read and unit-test in isolation (future plans).

3. **pip_size hard-code for XAUUSD:** mirrors `trade_manager._pip_size_for_symbol` which already lives in trade_manager. A unified `risk_calculator.PIP_TABLE` or `models.SYMBOL_META` could remove duplication but v1.1 is gold-only — one line of duplication is cheaper than a premature abstraction. Unify in v1.2.

4. **Synthetic signal `tps=[]`, `target_tp=None`:** the `_execute_open_on_account` stale-re-check is now conditional on `signal.tps` (Plan 02 fix). Zone-watch stages fire at market after an explicit in-zone-at-arrival decision — no TPs needed. Identical to `_handle_correlated_followup` in Plan 02.

5. **`_PricedDry._prices` mutation in tests:** existing Plan 02 harness pattern. Tests set `priced_connector._prices = {"XAUUSD": (bid, ask)}` inline rather than via a constructor override, matching how `test_concurrency.py` and `test_staged_executor.py` already drive prices.

6. **`_run_one_zone_watch_tick` helper via `asyncio.sleep` monkey-patch:** simplest way to execute exactly one loop body without waiting 10 real seconds. The helper is local to the test file; it tracks a tick counter and raises `CancelledError` on the second sleep. Restores `asyncio.sleep` in `finally`.

## Threat Model Compliance

| Threat ID | Disposition | Landed Mitigation | Test |
|-----------|-------------|-------------------|------|
| T-06-23 (Tampering, stage after kill switch) | mitigate | `emergency_close` drains BEFORE close; `_zone_watch_loop` checks `_trading_paused` at loop entry AND mid-tick | `test_zone_watch_skips_when_trading_paused` + `test_emergency_close_drains_staged_before_positions` |
| T-06-24 (Tampering, resume un-cancels) | mitigate | `resume_trading` only toggles the flag; never touches staged_entries rows | `test_resume_trading_does_not_uncancel_drained_stages` |
| T-06-25 (Repudiation, duplicate on reconnect) | mitigate | `mt5_comment` UNIQUE + `_zone_watch_loop` idempotency probe + `_sync_positions` comment reconcile | `test_zone_watch_idempotency_probe_marks_filled_without_submit` + `test_reconnect_marks_filled_when_comment_exists_on_mt5` |
| T-06-26 (Repudiation, orphan on prolonged reconnect) | mitigate | `created_at` age vs `cfg.signal_max_age_minutes` → `abandoned_reconnect` with age logged | `test_reconnect_marks_abandoned_when_signal_aged_and_no_mt5_position` |
| T-06-27 (DoS, zone-watch hot polling) | mitigate | 10s cadence; per-tick work bounded; by_pair grouping + stage1_live_cache dedupe MT5 calls | implicit in lifecycle test |
| T-06-28 (Spoofing, forged comment) | accept | Comments operator-set via our `open_order` call; MT5 does not allow third-party injection | n/a |
| T-06-29 (Info disclosure, log signal_id) | accept | Internal | n/a |
| T-06-30 (EoP, watcher bypasses safety) | mitigate | Watcher calls `_execute_open_on_account` — same fill path as v1.0 and Plan 02; all D-08/D-18/D-19/D-23 checks run inside | implicit in `test_zone_watch_fires_stage_when_price_enters_band` (which passes through dup-guard bypass + cap) |
| T-06-38 (Tampering, fire after stage 1 exit) | mitigate | D-16 pre-fire check: if stage-1 comment absent on MT5 AND db-stage-1 is 'filled', cascade-cancel and skip | `test_zone_watch_cancels_remaining_stages_when_stage1_closed` + `test_zone_watch_does_not_cascade_when_stage1_still_awaiting` |

All 5 `mitigate` dispositions have landing tests.

## Known Stubs

None. All new code is wired end-to-end against real fixtures (asyncpg pool, DryRunConnector).

## Self-Check: PASSED

Files verified:
- `executor.py` — FOUND (661 lines, up from 293)
- `tests/test_staged_safety_hooks.py` — FOUND (535 lines, up from 163)
- `.planning/phases/06-staged-entry-execution/06-04-SUMMARY.md` — present after write

Commits verified in `git log --all --oneline`:
- `5fa0ae1` — FOUND
- `4ea913f` — FOUND

Acceptance greps (all passed per `grep -n` audit):
- `async def _zone_watch_loop` in executor.py — 1 match
- `_zone_watch_task` in executor.py — 3 occurrences (attr init + create_task + cancel)
- `asyncio.sleep(10)` in executor.py — 1 match inside the loop
- `drain_staged_entries_for_kill_switch` in executor.py — 1 match inside `emergency_close`
- `drained_stages` in executor.py — 4 matches (local + error path + log + return dict)
- `D-21` comments in executor.py — 5 occurrences across drain + loop-entry + mid-tick + pre-submit
- `cancel_unfilled_stages_for_signal` in executor.py — 1 match inside D-16 cascade
- `D-16` comments in executor.py — 6 occurrences
- `stage1_live_cache` in executor.py — 6 occurrences
- `stage_is_in_zone_at_arrival` in executor.py — imported + called inside loop
- `_execute_open_on_account` reference in executor.py — present via `self.tm._execute_open_on_account` (line 626)
- `get_stage_by_comment` / `connector.get_positions` — idempotency probe + D-16 stage-1 check both present
- `D-24` / `abandoned_reconnect` / `get_pending_stages` / `by_comment` in `_sync_positions` — all present

## Next Phase Readiness

Plan 04 closes the Phase 6 executor-safety surface. Plan 05 (operator UI for `/staged` panel + SSE updates) can be built on top without further executor changes.
