---
phase: 13-staged-entry-execution-correctness-and-direct-zone-multi-sta
plan: 02
subsystem: live-money staged-entry execution engine (executor.py read path)
tags: [executor, zone-watch, cascade, exec2-01, tdd, wave-1, staged-entries]
requires:
  - "staged_entries.signal_sl / signal_tp columns (Plan 01)"
  - "get_active_stages returns signal_sl/signal_tp on each stage dict (Plan 01)"
  - "RED Wave-0 stubs test_late_stage_carries_signal_sl_tp / test_correlated_cascade_uses_persisted_tp (Plan 01)"
provides:
  - "_fire_zone_stage sources synth sl/target_tp from the persisted stage row (NULL-safe)"
  - "price-based cascade reads persisted per-stage SL/TP (get_signal_targets is the NULL fallback)"
  - "correlated-sequence cascade no longer a silent no-op"
affects:
  - "executor._zone_watch_loop late-stage fills (every stage of a sequence now ends with signal-derived SL/TP)"
  - "executor price-cascade behavior for correlated sequences (now fires; previously dormant)"
tech-stack:
  added: []
  patterns:
    - "stage.get('signal_sl')/'signal_tp') with NULL → default_sl_pips sl_price fallback (never sl=0; D-08 backstop preserved)"
    - "cascade prefers persisted per-stage SL/TP; get_signal_targets only consulted when a column is NULL (pre-migration / direct-zone)"
    - "TDD RED (test commit) → GREEN (feat commit) per task; real assertion RED, not pytest.fail stub"
key-files:
  created: []
  modified:
    - executor.py
    - tests/test_staged_executor.py
    - tests/test_staged_safety_hooks.py
decisions:
  - "Kept the default_sl_pips/sl_price block intact as the NULL fallback (action spec) — resolved_sl = sl_price if signal_sl is None else signal_sl."
  - "target_tp now sourced from persisted signal_tp (may be None for an orphan with no TP — acceptable here; orphan-TP attach is Plan 03/04)."
  - "Cascade direction sourced from the stage row's `direction`; targets direction is the fallback. get_signal_targets is fetched ONLY when signal_sl/signal_tp/direction is missing — avoids a dead DB round-trip when the stage already carries everything."
  - "Added a guard: if no usable direction AND both SL/TP <= 0 from either source, skip (preserves the old not-targets no-op behavior for genuinely target-less stages)."
  - "Extended the test-only _insert_staged_row helper to seed signal_sl/signal_tp (additive kwargs, default None = pre-migration row)."
metrics:
  duration: ~22min
  tasks: 2
  files: 3
  completed: 2026-06-08
---

# Phase 13 Plan 02: Executor read path uses persisted SL/TP Summary

Fixed both READ-side effects of the Plan-01 persisted-column mechanism in `executor.py`: a late zone-watch stage now carries the signal's real persisted SL/TP (not a rebuilt `default_sl_pips` SL with TP=0), and the price-based cascade now reads those persisted per-stage columns so it actually fires for correlated sequences (whose orphan signals row is sl=0/tp=0 and made the old `get_signal_targets` cascade a silent no-op). Both paths are NULL-safe — a pre-migration row falls back to the existing default-SL behavior, never sl=0, and the D-08 `sl<=0` backstop is untouched.

## What Was Built

### Task 1 — `_fire_zone_stage` carries persisted signal SL/TP (RED 815f35f, GREEN 5edbe06)
- `executor.py::_fire_zone_stage`: before building the synth `SignalAction`, read `signal_sl = stage.get("signal_sl")` / `signal_tp = stage.get("signal_tp")`. `resolved_sl = sl_price if signal_sl is None else signal_sl`; synth `sl=resolved_sl`, `target_tp=signal_tp` (was hardcoded `None`). The `default_sl_pips`-derived `sl_price` block is retained verbatim as the NULL fallback.
- Test `tests/test_staged_executor.py::test_late_stage_carries_signal_sl_tp` (replaces the Plan-01 `pytest.fail` stub): drives `_fire_zone_stage` via a spy on `_execute_open_on_account` and asserts (1) persisted SL/TP carried verbatim, (2) NULL `signal_sl` → default-SL price (2035.0, never 0), NULL `signal_tp` → `target_tp` stays None.

### Task 2 — revive the price cascade off persisted per-stage SL/TP (RED 968ee8f, GREEN c844c09)
- `executor.py::_zone_watch_loop` cascade block: now prefers `stage.get("signal_sl")` / `stage.get("signal_tp")` / `stage.get("direction")`. `get_signal_targets` is fetched ONLY when one of those is NULL (pre-migration / direct-zone rows whose own signals row holds real sl/tp). Hit logic, `cancel_unfilled_stages_target_reached`, and the "target cascade" logging are unchanged. Added a skip guard when neither source yields a usable direction + non-zero SL/TP (preserves the old target-less no-op).
- Test `tests/test_staged_safety_hooks.py::test_correlated_cascade_uses_persisted_tp` (replaces the stub): orphan signals row (no sl/tp → `get_signal_targets` dead), stage rows carry persisted `signal_sl=2030/signal_tp=2060`; price at 2060.5 → stage 2 flips to `cancelled_target_reached` and a `tp_reached` "target cascade" log line is emitted.
- Extended the test-only `_insert_staged_row` helper with additive `signal_sl`/`signal_tp` kwargs (default None).

## Verification Results

Run in a `python:3.12-slim` container against an ephemeral `postgres:16-alpine` (mirroring the project's dev-container + dev-Postgres harness; `idempotency_keys` pre-created per the Plan-01 note about the autouse `clean_tables` fixture).

- **Task 1 target + grep gate:** `pytest tests/test_staged_executor.py -k late_stage_carries_signal_sl_tp -x -q` → `1 passed`; `grep -q 'stage.get("signal_sl")' executor.py` → OK. ✅
- **Task 2 target + cascade no-regression:** `pytest tests/test_staged_safety_hooks.py -k "correlated_cascade_uses_persisted_tp or zone_watch_cancels_pending_stages_when_price_reaches_tp or ...reaches_sl or ...does_not_cancel_when_price_between_sl_and_tp"` → `4 passed`. ✅ (the between-SL/TP no-cancel test stays green)
- **RED proof (per TDD):** before each GREEN, the test failed on a real assertion — Task 1 on `target_tp` being None; Task 2 on stage 2 staying `awaiting_zone` (cascade no-op). Not a `pytest.fail` stub. ✅
- **Full fast core (excluding the 6 still-RED stubs owned by Plans 03/04/05):** `pytest tests/test_staged_executor.py tests/test_staged_safety_hooks.py` → `35 passed, 6 deselected`. ✅
- **Adjacent staged battery:** `pytest tests/test_staged_db.py tests/test_staged_attribution.py` → `9 passed` (cascade change did not disturb shared paths). ✅

## TDD Gate Compliance

Each task has the mandatory `test(...)` RED commit followed by a `feat(...)` GREEN commit:
- Task 1: 815f35f (test) → 5edbe06 (feat)
- Task 2: 968ee8f (test) → c844c09 (feat)
No REFACTOR commit was needed (implementation was minimal and clean on first GREEN).

## Deviations from Plan

None to the intended behavior. One in-scope refinement worth recording (still within the action spec):

**[Refinement — within action spec] Cascade skip-guard + conditional get_signal_targets fetch**
- **Found during:** Task 2 implementation.
- **Detail:** The plan says "fall back to `get_signal_targets` when the stage columns are NULL." Implemented this as: fetch `get_signal_targets` ONLY when `signal_sl`/`signal_tp`/`direction` is missing on the stage (avoids a dead DB round-trip + matches the orphan reality), and added an explicit skip when neither source yields a usable direction + non-zero SL/TP. This preserves the original `if not targets: continue` no-op semantics for genuinely target-less stages while reviving the correlated path.
- **Files modified:** executor.py.
- **Commit:** c844c09.

## Threat Surface

The three STRIDE mitigations assigned to this plan are satisfied; no new threat surface introduced:
- **T-13-03 (order with no real stop):** `_fire_zone_stage` resolves SL from persisted `signal_sl`; NULL → `default_sl_pips` fallback; never sl=0; D-08 `sl<=0` guard at `trade_manager.py:724-730` remains the backstop. Covered by `test_late_stage_carries_signal_sl_tp` + existing `test_default_sl_zero_hard_rejects_text_only`.
- **T-13-04 (over-entry after target hit):** cascade now reads persisted SL/TP → fires for correlated sequences. Covered by `test_correlated_cascade_uses_persisted_tp` + existing `zone_watch_cancels_*_reaches_tp/sl`.
- **T-13-05 (between-SL/TP false cancel):** direction-aware between-SL/TP no-cancel branch preserved unchanged. Covered by `test_zone_watch_does_not_cancel_when_price_between_sl_and_tp` (green).
- **T-13-SC (package installs):** none — in-repo edits only.

## Known Stubs

None introduced by this plan. The 6 still-RED stubs in `test_staged_executor.py` / `test_staged_safety_hooks.py` (`percent_splits_risk`, `direct_zone_*`, `orphan_*`) are owned by Plans 03/04/05 and are intentionally still RED at this plan's completion.

## Self-Check: PASSED

- `executor.py`, `tests/test_staged_executor.py`, `tests/test_staged_safety_hooks.py` all exist on disk. ✅
- All 4 task commits present in git log (815f35f, 5edbe06, 968ee8f, c844c09). ✅
- Both target tests GREEN; 3 no-regression cascade tests + full fast-core green (35 passed). ✅
