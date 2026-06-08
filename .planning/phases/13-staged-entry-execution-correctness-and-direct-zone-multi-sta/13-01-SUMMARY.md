---
phase: 13-staged-entry-execution-correctness-and-direct-zone-multi-sta
plan: 01
subsystem: live-money staged-entry execution engine (persistence + test foundation)
tags: [db, schema, ddl, tdd, wave-0, staged-entries, exec2-01]
requires:
  - staged_entries table (Phase 6, db.py)
  - signals.sl/tp columns (existing)
  - pytest + pytest-asyncio + dev Postgres test harness (conftest.py)
provides:
  - "staged_entries.signal_sl / signal_tp columns (additive, nullable)"
  - "create_staged_entries persists signal_sl/signal_tp (KeyError-safe via .get())"
  - "get_active_stages returns signal_sl/signal_tp on each stage dict"
  - "11 RED Wave-0 stubs gating EXEC2-01..06 downstream tasks"
  - "GREEN schema-column assertion (test_db_schema)"
affects:
  - executor._fire_zone_stage read path (Plan 02 sources signal_sl/signal_tp here)
  - executor price-cascade (Plan 02/03 revive the dormant correlated cascade)
  - trade_manager row-builders (Plan 03/05 add signal_sl/signal_tp keys to rows)
tech-stack:
  added: []
  patterns:
    - "ALTER TABLE ... ADD COLUMN IF NOT EXISTS for additive columns on an existing table (NOT CREATE TABLE IF NOT EXISTS — Pitfall 1)"
    - "r.get() on optional row-dict keys so not-yet-updated callers insert NULL rather than raising KeyError"
    - "Wave-0 RED stubs as plain sync pytest.fail() with contract docstring + requirement ID"
key-files:
  created: []
  modified:
    - db.py
    - tests/test_db_schema.py
    - tests/test_staged_executor.py
    - tests/test_staged_safety_hooks.py
    - tests/test_trade_manager.py
    - tests/test_stages_contract.py
decisions:
  - "Used ALTER TABLE ADD COLUMN IF NOT EXISTS (mirroring db.py:99 source_name precedent), placed immediately after the staged_entries CREATE TABLE block — CREATE IF NOT EXISTS would silently no-op on the already-created table (RESEARCH Pitfall 1)."
  - "Columns are nullable with no default so pre-migration awaiting_zone rows tolerate NULL; the Plan 02 read path is responsible for NULL-safe fallback."
  - "create_staged_entries uses r.get('signal_sl') / r.get('signal_tp') so existing callers (Plan 03/05 row-builders) that have not yet added the keys insert NULL instead of raising KeyError."
  - "Wave-0 stubs are plain sync pytest.fail() (no fixtures/event loop) so they are guaranteed collected-and-RED regardless of dev-Postgres presence; the implementing plan replaces each body."
metrics:
  duration: ~18min
  tasks: 2
  files: 6
  completed: 2026-06-08
---

# Phase 13 Plan 01: Persistence + Test Foundation Summary

Added additive `signal_sl`/`signal_tp` columns to the already-created `staged_entries` table via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, wired them through `create_staged_entries` (write) and `get_active_stages` (read), and laid down all 11 RED Wave-0 test stubs (plus one GREEN schema assertion) so every downstream EXEC2-01..06 task has a concrete `pytest -k` gate to turn green.

## What Was Built

### Task 1 — DDL + persistence foundation (commit 9564b66)
- `db.py::init_schema`: two guarded `ALTER TABLE staged_entries ADD COLUMN IF NOT EXISTS signal_sl/signal_tp DOUBLE PRECISION` statements placed immediately after the `CREATE TABLE IF NOT EXISTS staged_entries` block, mirroring the existing `ALTER TABLE signals ADD COLUMN IF NOT EXISTS source_name` precedent (db.py:99).
- `db.create_staged_entries`: INSERT column list + placeholders extended to carry `signal_sl, signal_tp`; values passed via `r.get(...)` (KeyError-safe for not-yet-updated callers).
- `db.get_active_stages`: SELECT list extended with `signal_sl, signal_tp` so the zone-watch read path (Plan 02) receives them on each stage dict.
- Did NOT touch `_handle_correlated_followup` / `_handle_open` row-builders — Plan 03/05 add the keys to their `rows` dicts. This task only makes the schema + helpers capable of carrying the values.

### Task 2 — Wave-0 red stubs + schema assertion (commit d14a4ea)
- 11 RED stubs (`pytest.fail` with a contract docstring + requirement ID each):
  - `test_staged_executor.py`: `late_stage_carries_signal_sl_tp` (EXEC2-01), `percent_splits_risk` (EXEC2-02), `direct_zone_multistage`, `direct_zone_single_band`, `direct_zone_arms_when_outside` (EXEC2-06)
  - `test_staged_safety_hooks.py`: `correlated_cascade_uses_persisted_tp` (EXEC2-01), `orphan_protective_tp_at_expiry`, `orphan_no_tp_during_window` (EXEC2-05)
  - `test_trade_manager.py`: `sl_less_open_skips_cleanly` (EXEC2-04), `direct_zone_past_market_stale` (EXEC2-06/D2-14)
  - `test_stages_contract.py`: `target_lot_matches_volume` (EXEC2-03)
- 1 GREEN assertion: `test_db_schema.py::test_staged_entries_has_signal_sl_tp_columns` — proves the columns exist on the already-created table (the Pitfall-1 guard), mirroring the existing `information_schema.columns` pattern in that file.

## Verification Results

Run in a `python:3.12-slim` container against an ephemeral `postgres:16-alpine` (mirroring the project's dev-container + dev-Postgres harness):

- **Task 1 grep gate:** `grep -c "ADD COLUMN IF NOT EXISTS signal_sl DOUBLE PRECISION" db.py` == 1; same for `signal_tp`; `CREATE TABLE ... staged_entries` body contains NO `signal_sl` (ALTER, not inline). ✅
- **11 stubs collected + RED:** `--co` lists all 11; running them yields `11 failed`. ✅
- **Schema assertion GREEN:** `pytest tests/test_db_schema.py -k staged_entries -x` → `1 passed`. ✅
- **No-regression:** `tests/test_staged_db.py` → 6 passed; no-regression battery (`test_staged_safety_hooks.py` + `test_staged_executor.py` excluding the new stubs) → 33 passed. ✅
- **Combined sweep across all 6 touched files:** `11 failed (the intended stubs), 70 passed, 1 skipped` — the only failures are the 11 Wave-0 stubs; the 1 skip is the env-dependent live HTTP contract layer in `test_stages_contract.py`. ✅

## Deviations from Plan

None to the production code. One environment-only investigation worth recording:

**[Investigation — not a code change] Ephemeral-DB `idempotency_keys` artifact**
- **Found during:** Task 2 verification (no-regression run of `tests/test_staged_db.py`).
- **Symptom:** `test_drain_for_kill_switch_terminal` asserted `drained == 2` but got `3`; other staged_db tests hit `mt5_comment UNIQUE` violations — i.e. tables were not being truncated between tests.
- **Root cause:** The autouse `clean_tables` fixture (conftest.py:48) `TRUNCATE`s `idempotency_keys`, a table created lazily by `api/idempotency.py` (Phase 8), NOT by `db.init_db`. My throwaway Postgres lacked it, so the TRUNCATE raised and the fixture's bare `except` silently swallowed the entire cleanup → cross-test row leakage. The real dev Postgres has `idempotency_keys`, so this never reproduces there.
- **Resolution:** Created `idempotency_keys` in the ephemeral DB to match the real dev DB; the staged_db regression then passed clean (6/6). No source change made — this was an artifact of my one-shot test infra, not a defect in the plan's changes or the test-isolation logic. Logged here for the wave-merge runner (the project's standard dev-Postgres already carries the table).

## Threat Surface

No new threat surface introduced. The two STRIDE mitigations assigned to this plan are satisfied:
- **T-13-01 (silent DDL no-op):** mitigated by using `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` + the GREEN `test_db_schema` assertion proving the columns exist on the already-created table.
- **T-13-02 (loss of protective levels):** columns are nullable + `create_staged_entries` uses `.get()` so pre-migration rows are NULL-safe; the NULL→default-SL fallback lives in the Plan 02 read path (out of scope for this plan).

## Known Stubs

The 11 RED stubs are intentional Wave-0 TDD gates, each tied to a downstream plan that turns it green (Plan 02–05). They are NOT accidental placeholders — they are the executable acceptance criteria for the rest of Phase 13. The schema assertion is the only Phase-13 test expected GREEN at this plan's completion.

## Self-Check: PASSED

- All 6 modified files exist on disk. ✅
- Both task commits exist in git log (9564b66, d14a4ea). ✅
