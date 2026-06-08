---
phase: 13-staged-entry-execution-correctness-and-direct-zone-multi-sta
plan: 03
subsystem: live-money staged-entry execution engine (percent risk split + SL-less skip)
tags: [trade-manager, risk-sizing, percent-split, sl-less-skip, exec2-02, exec2-03, exec2-04, tdd, wave-1]
requires:
  - "staged_entries.signal_sl / signal_tp columns + create_staged_entries .get()-safe persistence (Plan 13-01)"
  - "stage_lot_size() per-stage split helper (Phase 6, trade_manager.py:107)"
  - "calculate_lot_size / calculate_sl_distance (risk_calculator.py)"
  - "D-08 sl<=0 hard-reject guard (trade_manager.py, Phase 6)"
provides:
  - "_execute_open_on_account percent branch divides risk_pct by max_stages for staged sequences (per_stage_risk)"
  - "v1.0 non-staged percent path unchanged (full risk_pct); fixed_lot branch untouched"
  - "_handle_open early signal.sl is None skip BEFORE calculate_sl_distance (clean skip-result, no TypeError)"
  - "_handle_text_only_open stage-1 row persists signal_sl (default-SL price) + signal_tp (None)"
  - "test_percent_splits_risk (EXEC2-02) GREEN; test_target_lot_matches_volume (EXEC2-03) GREEN; test_sl_less_open_skips_cleanly (EXEC2-04) GREEN"
affects:
  - "Plan 02 read path consumes the persisted signal_sl/signal_tp on text-only stage rows"
  - "/staged panel target_lot now equals the actually-submitted percent-mode per-stage volume (display == reality)"
  - "Plan 05 (EXEC2-06) direct-zone create-site will set signal_sl/signal_tp to the OPEN's real signal.sl/target_tp"
tech-stack:
  added: []
  patterns:
    - "Gate the staged-only risk split on the `staged` flag so the v1.0 single-signal path keeps full risk (belt-and-suspenders)"
    - "Early-return skip BEFORE the crash site, routing to the existing skip-result stream; keep the downstream guard as a second backstop"
    - "Additive row-dict keys (signal_sl/signal_tp) consumed KeyError-safe by create_staged_entries via .get() (Plan 01 contract)"
    - "Display read-through: api/stages surfaces persisted target_lot verbatim (out=dict(stage)); no recompute"
key-files:
  created:
    - .planning/phases/13-staged-entry-execution-correctness-and-direct-zone-multi-sta/deferred-items.md
  modified:
    - trade_manager.py
    - tests/test_staged_executor.py
    - tests/test_stages_contract.py
    - tests/test_trade_manager.py
decisions:
  - "Percent split uses `stages = snapshot.max_stages if snapshot and snapshot.max_stages > 0 else 1` then `per_stage_risk = risk_pct / stages if staged else risk_pct` — guards max_stages>0 and the v1.0 non-staged path (D2-06/D2-07)."
  - "risk_pct still sourced from _effective() (SettingsStore/AccountConfig); only the divisor is added — snapshot is consulted solely for max_stages, matching how stage_lot_size splits fixed_lot."
  - "SL-less skip logs the signal with action_taken='skipped' (audit trail) and returns a single {account:'*', status:'skipped'} result, mirroring the existing skip-result shape; D-08 sl<=0 guard left intact as the second backstop for present-but-non-positive SL."
  - "Text-only orphan persists signal_sl = the computed default-SL price (available at row-build time) and signal_tp = None (Plan 04 attaches the protective TP later)."
  - "EXEC2-03 needed NO api/stages.py change — _enrich_active already passes target_lot through verbatim (out = dict(stage)); the contract test asserts the read-through + the shared risk_value/max_stages divisor convergence."
metrics:
  duration: ~35min
  tasks: 2
  files: 5
  completed: 2026-06-08
---

# Phase 13 Plan 03: Percent Risk Split + SL-less Clean Skip Summary

Three localized `trade_manager.py` money-correctness fixes — all clear of `executor.py` so this plan runs parallel to Plan 02: (1) the percent-mode sizing branch now divides `risk_pct` by `max_stages` for staged sequences so `risk_value` is a true never-exceed ceiling instead of N× exposure (EXEC2-02); (2) the `/staged` `target_lot` display and the submitted per-stage volume now share one `risk_value/max_stages` divisor, so the panel matches reality (EXEC2-03); (3) a standalone OPEN with `signal.sl is None` is routed to a clean skip BEFORE `calculate_sl_distance(entry, None)` can raise, with the D-08 `sl<=0` guard preserved as the second backstop (EXEC2-04). The text-only create-site now persists `signal_sl`/`signal_tp` so Plan 02's read path has them.

## What Was Built

### Task 1 — Percent-mode risk split + /staged contract (commit 272e7b5)
- **`trade_manager.py::_execute_open_on_account` percent branch:** inserted
  `stages = snapshot.max_stages if snapshot and snapshot.max_stages > 0 else 1` and
  `per_stage_risk = risk_pct / stages if staged else risk_pct`, then passed
  `risk_percent=per_stage_risk` to `calculate_lot_size`. The `fixed_lot` branch and
  `stage_lot_size()` are byte-for-byte untouched (they already split via
  `risk_value / max_stages`).
- **`tests/test_staged_executor.py::test_percent_splits_risk`** (was a Plan-01 RED stub →
  now GREEN): percent-mode `risk_value=2.0`, `max_stages=4`; a staged
  `_execute_open_on_account` call submits a volume equal to
  `calculate_lot_size(risk_percent=2.0/4, …)`, which is `expected_full / 4` and strictly
  less than the un-split full-risk volume.
- **`tests/test_stages_contract.py::test_target_lot_matches_volume`** (RED stub → GREEN):
  proves the two halves of D2-08 — (a) the persisted `target_lot` is the per-stage slice
  `stage_lot_size(snapshot)` and `_enrich_active` surfaces it verbatim (no recompute in the
  display layer), and (b) the submit path's per-stage risk shares the same
  `risk_value/max_stages` divisor, so display and submitted volume converge.
- **`api/stages.py`:** confirmed NO change needed — `_enrich_active` does `out = dict(stage)`
  so `target_lot` flows through unchanged (read-through, no recompute).

### Task 2 — SL-less clean skip + signal_sl/tp persistence (commit 39bf2e0)
- **`trade_manager.py::_handle_open`:** added an early `if signal.sl is None:` branch at the
  very top — logs the signal with `action_taken="skipped"` and returns a single
  `{account:"*", status:"skipped", reason:"Skipped: signal has no SL (D-08 requires a stop)"}`.
  This guarantees `calculate_sl_distance(entry_for_calc, signal.sl)` (line 714) is never
  reached on a `None` SL (the `abs(entry - None)` TypeError crash site, which previously fired
  BEFORE the D-08 guard at line ~727). The D-08 `sl<=0` hard-reject is preserved as the second
  backstop for present-but-non-positive SL values.
- **`trade_manager.py::_handle_text_only_open` stage-1 row:** added `"signal_sl": sl_price`
  (the computed default-SL price) and `"signal_tp": None` (orphan has no signal TP — Plan 04
  attaches a protective TP later) to the `stage_row` dict so `create_staged_entries`
  (Plan 01) persists them for Plan 02's read path.
- **`tests/test_trade_manager.py::test_sl_less_open_skips_cleanly`** (RED stub → GREEN): an
  SL-less OPEN returns a single skip-result, `calculate_sl_distance` is never called (spy
  asserts `call_count == 0`), and the signal is logged as `skipped` (no silent drop).
- **`tests/test_trade_manager.py::test_open_with_real_sl_unchanged`** (added — Rule 2 guard):
  an OPEN WITH a real SL still reaches sizing (`calculate_sl_distance` called ≥1) and does NOT
  take the skip path, proving the early skip is gated strictly on `signal.sl is None`.

## Verification Results

Run in a `python:3.12-slim` container against an ephemeral `postgres:16-alpine` (the project's
standard dev-container + dev-Postgres harness; host has only Python 3.14 and no pytest).

- **Task 1 acceptance:**
  - `pytest tests/test_staged_executor.py -k percent_splits_risk -x -q` → `1 passed`. ✅
  - `pytest tests/test_stages_contract.py -k target_lot_matches_volume -x -q` → `1 passed`. ✅
  - `grep -q "per_stage_risk" trade_manager.py` ✅; the division references `max_stages`
    (`stages = snapshot.max_stages …`). ✅
  - `fixed_lot` branch + `stage_lot_size` unchanged (no diff). ✅
  - api/stages.py contains no `target_lot` recompute. ✅
  - Fast-core (excluding other-plan RED stubs): `test_staged_executor.py
    test_staged_safety_hooks.py` → `34 passed, 7 deselected`. ✅
- **Task 2 acceptance:**
  - `pytest tests/test_trade_manager.py -k "sl_less_open_skips_cleanly or open_with_real_sl_unchanged" -x -q`
    → `2 passed`. ✅
  - `pytest tests/test_staged_safety_hooks.py -k default_sl_zero_hard_rejects_text_only -x -q`
    → `1 passed` (D-08 backstop intact). ✅
  - `grep -q "signal.sl is None" trade_manager.py` ✅; `grep -q '"signal_sl"' trade_manager.py`
    ✅; the `signal.sl is None` line (563) precedes the first `calculate_sl_distance` (714). ✅

## Deviations from Plan

**[Rule 2 — added guard test] `test_open_with_real_sl_unchanged`**
- **Added during:** Task 2.
- **Why:** the SL-less skip is a new early-return in the hot `_handle_open` path; the plan's
  behavior contract requires "OPEN with a real SL → unchanged behavior." Added an explicit
  regression test proving the skip is gated strictly on `signal.sl is None` (a WITH-SL OPEN
  still reaches sizing). Correctness requirement, no architectural change.
- **Files:** `tests/test_trade_manager.py`. **Commit:** 39bf2e0.

No production-code deviations beyond the plan's three described fixes.

## Out-of-Scope Discovery (logged, not fixed)

**Ephemeral-DB cross-test isolation artifact** — see
`13-.../deferred-items.md`. When `test_staged_safety_hooks.py` runs AFTER
`test_trade_manager.py` in a single one-shot ephemeral Postgres, 16 safety-hook tests
(`test_zone_watch_*`, `test_emergency_close_drains_*`, `test_resume_trading_*`,
`test_reconnect_*`) fail with UNIQUE-violation / wrong-count errors. This is the SAME
`idempotency_keys`/atomic-TRUNCATE artifact the 13-01 SUMMARY documented (the single
`TRUNCATE …, idempotency_keys RESTART IDENTITY CASCADE` rolls back atomically on any table
issue; the bare `except: pass` swallows it → row leakage). It does NOT reproduce on the
project's real dev Postgres (which carries `idempotency_keys`), and is NOT a 13-03 regression:
the safety-hook suite ran GREEN (`34 passed`) on a clean DB earlier in this same session, and
13-03's edits do not touch the zone-watch / emergency-drain / reconnect paths. The per-wave
merge gate (`pytest tests/ -q` on dev Postgres) is where the full suite runs green.

## Threat Surface

The three STRIDE mitigations assigned to this plan are satisfied:
- **T-13-06 (N× over-exposure):** `per_stage_risk = risk_pct / max_stages` for staged
  percent sequences; `risk_value` is now a never-exceed ceiling (D2-07). Proven by
  `test_percent_splits_risk`.
- **T-13-07 (order with no stop / crash alert):** early `signal.sl is None` skip before
  `calculate_sl_distance`; D-08 `sl<=0` guard remains the backstop. Proven by
  `test_sl_less_open_skips_cleanly` + `test_default_sl_zero_hard_rejects_text_only`.
- **T-13-08 (misinformed operator):** display reads persisted `target_lot` (already split);
  display and submit share one divisor. Proven by `test_target_lot_matches_volume`.

No new threat surface introduced — all edits are in-file, no package installs (T-13-SC: accept).

## Known Stubs

None introduced by this plan. The remaining RED Wave-0 stubs in the touched test files
(`test_late_stage_carries_signal_sl_tp` — Plan 02; `test_direct_zone_*`,
`test_direct_zone_past_market_stale` — Plan 05; `orphan_*`,
`correlated_cascade_uses_persisted_tp` — Plans 02/04) belong to other Phase-13 plans and are
intentionally still RED until those plans land.

## Self-Check: PASSED

- `trade_manager.py`, `tests/test_staged_executor.py`, `tests/test_stages_contract.py`,
  `tests/test_trade_manager.py`, and `13-.../deferred-items.md` all exist on disk. ✅
- Both task commits exist in git log: 272e7b5 (Task 1), 39bf2e0 (Task 2). ✅
- All plan acceptance criteria + grep gates verified GREEN in the python:3.12 + dev-Postgres
  container. ✅
