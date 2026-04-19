---
phase: 06
plan: 02
subsystem: staged-entry-executor
tags: [phase-6, trade-manager, staged-entries, correlator, tdd]
requires: [06-01]
provides:
  - stage-aware-execute-open-on-account
  - _handle_text_only_open
  - _handle_correlated_followup
  - compute_bands
  - stage_is_in_zone_at_arrival
  - stage_lot_size
affects: [trade_manager.py, tests/test_staged_executor.py, tests/test_staged_safety_hooks.py, tests/test_staged_attribution.py, tests/conftest.py, tests/test_staged_db.py]
tech_added:
  patterns:
    - keyword-only-feature-flag-on-existing-function
    - pure-helpers-for-testability
    - dataclass-asdict-snapshot-to-jsonb
    - comment-prefix-based-sibling-guard-bypass
    - first-fill-idempotency-for-daily-counters
    - failure-isolation-in-stage-loop
key_files:
  created:
    - tests/test_staged_executor.py
    - tests/test_staged_safety_hooks.py
    - tests/test_staged_attribution.py
    - .planning/phases/06-staged-entry-execution/06-02-SUMMARY.md
  modified:
    - trade_manager.py
    - tests/conftest.py
    - tests/test_staged_db.py
decisions:
  - "[06-02] Introduce staged=False keyword flag instead of branching on signal_id is not None: v1.0 _handle_open already passes a non-None signal_id via db.log_signal, so signal_id alone cannot distinguish paths. staged=True is set only by Phase 6 dispatchers"
  - "[06-02] Daily-limit pre-check is bypassed when staged and stage_number>1 (D-18): sibling stages must not be blocked by a cap that their own stage 1 already consumed"
  - "[06-02] Cap-check returns 'capped' status + writes update_stage_status on the staged path, 'skipped' on v1.0: matches STAGE-09 analytics expectations and /staged panel surfacing"
  - "[06-02] Stale re-check is conditional on signal.tps: text-only has no TPs, follow-up fires at market from in-zone-at-arrival — neither needs the re-check"
  - "[06-02] Band NamedTuple + pure helpers live in trade_manager.py not staged_math.py: cohesion with the executor code that consumes them; no circular import risk because helpers are pure functions"
  - "[06-02] pip_size_for_symbol hard-codes XAUUSD=0.01 and logs a warning for other symbols: v1.1 is gold-only; defer a full pip table to v1.2 when FX support lands"
  - "[06-02] seeded_signal promoted from tests/test_staged_db.py to tests/conftest.py: Phase 6 Plan 02 creates 3 test files that all need it; Plan 01's 'keep local' decision was right at 1 file, wrong at 4"
  - "[06-02] tm_with_store fixture constructed per-test-file (not in conftest): each test needs its own fresh correlator window to avoid orphan pollution across tests"
metrics:
  duration_minutes: 28
  tasks_completed: 2
  files_touched: 6
  completed_date: 2026-04-20
---

# Phase 06 Plan 02: Staged-Entry Executor Summary

## Overview

One-liner: Phase 6 live-money heart — stage-aware `_execute_open_on_account` gains `staged` / `stage_number` / `stage_row_id` / `snapshot` keyword-only parameters threading D-08 hard-SL-reject, D-18 one-signal-one-slot daily accounting, D-19 cap→`capped` status, D-23 sibling-stage dup-guard bypass, D-24 `telebot-{signal_id}-s{N}` comment attribution, and D-25 DB+MT5 idempotency probe; `_handle_text_only_open` + `_handle_correlated_followup` + pure helpers (`Band`, `compute_bands`, `stage_is_in_zone_at_arrival`, `stage_lot_size`) land the full two-signal correlation pipeline; v1.0 path (`staged=False`) remains byte-identical in behavior.

## What Was Built

### Pure helpers (trade_manager.py module-level, D-11..D-15)

```python
class Band(NamedTuple):
    stage_number: int   # 2..N
    low: float
    high: float

def compute_bands(zone_low, zone_high, max_stages, direction) -> list[Band]: ...
def stage_is_in_zone_at_arrival(band, current_bid, current_ask, direction) -> bool: ...
def stage_lot_size(snapshot: AccountSettings) -> float: ...
def _pip_size_for_symbol(symbol: str) -> float: ...  # XAUUSD=0.01
```

Invariants:
- `len(compute_bands(...))` == `max_stages - 1` (stage 1 is the text-only market fill, unbanded)
- point-band when `zone_low == zone_high` (Research Q5 resolved): all N-1 stages collapse to the same point
- inverted zone raises `ValueError`
- in-zone-at-arrival inclusive equality so a point-band triggers

### Stage-aware `_execute_open_on_account`

Phase 6 additions (all keyword-only; defaults preserve v1.0 behavior):

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `staged` | `False` | Gates D-08/D-18/D-19/D-23/D-24/D-25 staged-only behaviors. |
| `stage_number` | `1` | 1 for text-only stage-1; 2..N for sibling stages. |
| `stage_row_id` | `None` | `staged_entries.id`; populated with `mt5_ticket` on fill (D-38). |
| `snapshot` | `None` | Frozen `AccountSettings` for D-30 per-stage freeze. |

Edit sites (anchored by D-ID):

| D-ID | Site | Behavior |
|------|------|----------|
| D-18 | Daily-limit pre-check | Bypassed for `staged=True and stage_number>1` — sibling stages do not burn budget. |
| D-19 | `len(positions) >= max_open` | Staged path → `status='capped'` + `update_stage_status`; v1.0 → `'skipped'`. |
| D-23 | Duplicate-direction guard | `getattr(pos, 'comment', '').startswith(f'telebot-{signal_id}-s')` allowed through for staged calls. |
| D-08 | Post-jitter SL check | `jittered_sl is None or <= 0.0` → `'Refusing to submit sl=0.0 …'` failure; applies to all paths. |
| D-25 | Pre-submit idempotency probe | `db.get_stage_by_comment` + `connector.get_positions().comment` match → short-circuit without resubmit. |
| D-24 | `open_order` comment | `f'telebot-{signal_id}-s{stage_number}'` when staged; literal `'telebot'` when v1.0. |
| D-18 | Post-success increment | Staged → `mark_signal_counted_today` + `increment_daily_stat` only on first-fill; v1.0 → unconditional. |
| D-38 | Post-success | `update_stage_status(stage_row_id, 'filled', mt5_ticket=...)`. |

### `_handle_text_only_open` — STAGE-02

Flow:
1. `db.log_signal(signal_type='open_text_only')` → `signal_id`
2. `correlator.register_orphan(signal_id, symbol, direction)`
3. Per enabled connected account:
   - `snapshot = settings_store.snapshot(acct_name)` (D-30)
   - Compute `default_sl_price` = `current_ask - (default_sl_pips * pip_size)` for BUY, symmetric for SELL
   - Insert stage 1 row `(status='awaiting_zone', comment='telebot-{signal_id}-s1')`
   - `_execute_open_on_account(synth_signal, …, staged=True, stage_number=1, stage_row_id=stage_id, snapshot=snapshot)`
4. On failure: row flipped to `status='failed'` with the executor's reason.

### `_handle_correlated_followup` — STAGE-04

Flow:
1. Per enabled connected account: snapshot settings.
2. `bands = compute_bands(entry_zone_low, entry_zone_high, max_stages, direction)`
3. Bulk-insert all N-1 rows as `awaiting_zone` with `target_lot`, `snapshot_settings` (JSONB via `asdict`).
4. Fetch live price once; for each band where `stage_is_in_zone_at_arrival(band, bid, ask, direction)`:
   - Build synthetic SignalAction with band as `entry_zone`; call `_execute_open_on_account(…staged=True, stage_number=band.N, stage_row_id=..)`
   - Failure → `update_stage_status(row, 'failed')`, continue to next band (D-17 failure isolation).
5. Remaining armed rows stay `awaiting_zone` — Plan 04's `_zone_watch_loop` services them.

### `handle_signal` dispatch

- `OPEN_TEXT_ONLY` → `_handle_text_only_open`
- `OPEN` → `correlator.pair_followup()`; if matched → `_handle_correlated_followup(signal, paired_signal_id)`; else → v1.0 `_handle_open`
- All other types unchanged.

## Commits

| Task | Commit | Subject |
|------|--------|---------|
| T1 RED | `12c20b8` | `test(06-02): RED — staged safety hooks + attribution tests` |
| T1 GREEN | `6126695` | `feat(06-02): stage-aware _execute_open_on_account` |
| T2 RED | `33ea785` | `test(06-02): RED — staged executor + band compute + in-zone-at-arrival` |
| T2 GREEN | `313d4f1` | `feat(06-02): correlator integration + text-only + correlated followup` |

TDD sequence `test → feat → test → feat` observed in `git log --oneline`.

## Test Results

21 new tests + 86 pre-existing tests = **107 total green**.

| Suite | Tests | Status |
|-------|-------|--------|
| `tests/test_staged_safety_hooks.py` | 3 | green |
| `tests/test_staged_attribution.py` | 3 | green |
| `tests/test_staged_executor.py` | 15 (10 unit + 5 integration) | green |
| `tests/test_trade_manager.py` | 16 | green (regression) |
| `tests/test_trade_manager_integration.py` | 11 | green (regression) |
| `tests/test_staged_db.py` | 6 | green (regression) |
| `tests/test_correlator.py` | 6 | green (regression) |
| `tests/test_signal_parser_text_only.py` | 5 | green (regression) |
| `tests/test_signal_parser.py` | 42 | green (regression) |

Run: `pytest tests/test_staged_*.py tests/test_trade_manager*.py tests/test_correlator.py tests/test_signal_parser*.py -v` → `107 passed`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 — missing critical distinction] `staged` feature flag**

- **Found during:** Task 1 GREEN verification (regression on all test_trade_manager_integration tests).
- **Issue:** Plan described gating new behavior on `signal_id is not None`, but `_handle_open` (v1.0) already passes a non-None `signal_id` from `db.log_signal`. Using that signal caused the v1.0 path to engage Phase 6 behaviors (`mark_signal_counted_today` FK violation on tests that don't seed the `accounts` table).
- **Fix:** Added keyword-only `staged: bool = False` flag; Phase 6 dispatchers pass `staged=True`, v1.0 `_handle_open` does not.
- **Files:** `trade_manager.py`
- **Commit:** `6126695`

**2. [Rule 3 — blocking fixture plumbing] Promoted `seeded_signal` to conftest**

- **Found during:** Task 1 RED scaffolding.
- **Issue:** Plan 01 kept `seeded_signal` local to `tests/test_staged_db.py`. Plan 02 creates 3 new test files, all needing it → duplication risk.
- **Fix:** Moved fixture to `tests/conftest.py`; added `seeded_staged_account` helper that seeds + bumps `max_stages` + `default_sl_pips` for band tests.
- **Files:** `tests/conftest.py`, `tests/test_staged_db.py` (removed local fixture).

**3. [Rule 3 — blocking] Stale re-check conditional on `signal.tps`**

- **Found during:** Task 1 integration tests for text-only path.
- **Issue:** EXEC-02 stale re-check fetches price again and compares to TP1. Text-only has no TPs and follow-up-stage submissions fire after an explicit in-zone-at-arrival decision. The unconditional re-check triggered on `signal.tps = []`, returning `None` (the stale check handles empty TPs), so no actual failure — but the extra price fetch was unnecessary and could race with the earlier reading for staged paths.
- **Fix:** Wrapped re-check in `if signal.tps:`. v1.0 callers always pass `tps=[..]` so the re-check still runs. Purely behavior-preserving for v1.0; avoids redundant work for staged.
- **Files:** `trade_manager.py`

**4. [Rule 3 — blocking] Text-only `entry_zone=None` branch in executor**

- **Found during:** Task 1 GREEN.
- **Issue:** Plan's synthetic-signal design builds a SignalAction with `entry_zone=None`. The existing `zone_low, zone_high = signal.entry_zone` line would raise TypeError.
- **Fix:** Added `if signal.entry_zone is None: use_market, limit_price = True, 0.0` before the zone-typed unpack.
- **Files:** `trade_manager.py`

None of the above required user intervention per Rules 1–3. All are documented for auditability.

## Claude's Discretion

1. **`staged` keyword vs. `stage_row_id` sentinel:** considered using `stage_row_id is not None` as the flag. Rejected because it would force every staged call to pre-insert a row before `_execute_open_on_account`, which matches the text-only pattern but not the D-25 idempotency probe which may fire before a row exists.
2. **Pip size location:** `_pip_size_for_symbol` is file-private inside `trade_manager.py`. A `risk_calculator.PIP_TABLE` or `models.SYMBOL_META` table would be cleaner but v1.1 is gold-only — deferring.
3. **Failure-isolation policy:** `_handle_correlated_followup` catches per-band failures via `result.get('status') == 'failed'` rather than try/except around `_execute_open_on_account`. The executor never raises; it returns failed dicts. Keeping the pattern avoids unnecessary try/except.
4. **`seeded_staged_account` fixture seeds `max_stages=5` + `default_sl_pips=100`:** default `max_stages=1` yields zero bands, breaking every test that exercises the follow-up path. A single fixture with reasonable defaults keeps test bodies focused on the behavior under test.
5. **T-06-13 (per-symbol cap) test:** plan specified calling `_handle_correlated_followup` with a low cap; in practice the DryRunConnector returns `_fake_positions` counts, so I set `max_open_trades=1` on the accounts row directly and reloaded the SettingsStore. This is what bot.py does at runtime via `/settings` edits.

## Threat Model Compliance

| Threat ID | Disposition | Landed Mitigation |
|-----------|-------------|-------------------|
| T-06-08 (Tampering, default SL calc) | mitigate | D-08 hard reject `jittered_sl <= 0.0` with literal reason; `test_default_sl_zero_hard_rejects_text_only` green |
| T-06-09 (Tampering, dup-guard bypass) | mitigate | Bypass keyed on exact `f'telebot-{signal_id}-s'` prefix; `test_dup_guard_still_rejects_unrelated_same_direction` green |
| T-06-10 (Repudiation, daily accounting) | mitigate | `mark_signal_counted_today` ON CONFLICT guarantees exactly-once; `test_one_signal_id_one_daily_slot` green |
| T-06-11 (Info disclosure, snapshot_settings) | accept | Operator-only dashboard; no PII |
| T-06-12 (DoS, correlator) | accept | O(1) dict at <10 signals/min |
| T-06-13 (EoP, cap bypass) | mitigate | Per-symbol cap runs before submit; `test_stage_marked_capped_when_max_open_trades_reached` green |
| T-06-14 (Tampering, idempotency race) | mitigate | D-25 DB + live MT5 probe before submit; implicit in all staged tests |

## Known Stubs

None. All new code is wired end-to-end against real fixtures.

## Self-Check: PASSED

Files verified:
- `trade_manager.py` — FOUND (815 lines)
- `tests/test_staged_safety_hooks.py` — FOUND
- `tests/test_staged_attribution.py` — FOUND
- `tests/test_staged_executor.py` — FOUND
- `tests/conftest.py` — FOUND (modified)
- `tests/test_staged_db.py` — FOUND (modified; local seeded_signal fixture removed)

Commits verified in `git log`:
- `12c20b8` — FOUND
- `6126695` — FOUND
- `33ea785` — FOUND
- `313d4f1` — FOUND

Acceptance greps (spot-check):
- `def compute_bands` in trade_manager.py — present (line 52)
- `def stage_is_in_zone_at_arrival` in trade_manager.py — present (line 89)
- `def stage_lot_size` in trade_manager.py — present (line 107)
- `_handle_text_only_open` in trade_manager.py — present (method + dispatch branch)
- `_handle_correlated_followup` in trade_manager.py — present (method + dispatch branch)
- `self.correlator.pair_followup` in trade_manager.py — present
- `register_orphan` in trade_manager.py — present
- `create_staged_entries` in trade_manager.py — present (both dispatchers)
- `settings_store.snapshot` (via `store.snapshot(acct_name)`) — present (both dispatchers)
- `telebot-{signal_id}-s` format in trade_manager.py — present (dup-guard + open_order comment)
- `mark_signal_counted_today` in trade_manager.py — present (post-success branch)
- `Refusing to submit sl=0.0` literal in trade_manager.py — present (D-08 guard)
- `get_stage_by_comment` in trade_manager.py — present (idempotency probe)
- `status.*capped` in trade_manager.py — present (D-19 cap branch)
