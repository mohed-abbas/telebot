# Phase 13 — Deferred / Out-of-Scope Items

## Test-infra artifact (ephemeral one-shot Postgres) — NOT a code defect

**Discovered during:** Plan 13-03 Task 2 verification (combined run of
`tests/test_trade_manager.py tests/test_staged_safety_hooks.py` in a throwaway
`python:3.12-slim` + `postgres:16-alpine` container).

**Symptom:** 16 collateral failures in `test_staged_safety_hooks.py`
(`test_zone_watch_*`, `test_emergency_close_drains_*`, `test_resume_trading_*`,
`test_reconnect_*`) when that file runs AFTER `test_trade_manager.py` in the same
one-shot ephemeral DB — UNIQUE `mt5_comment` violations / wrong drain counts.

**Root cause (identical to the 13-01 SUMMARY finding):** the autouse `clean_tables`
fixture (`tests/conftest.py:48`) issues a SINGLE atomic
`TRUNCATE signals, …, idempotency_keys RESTART IDENTITY CASCADE`. In a throwaway
ephemeral DB the `idempotency_keys` table (created lazily by `api/idempotency.py`,
Phase 8 — NOT by `db.init_db`) can mismatch / be absent, the whole atomic TRUNCATE
errors, and the fixture's bare `except: pass` swallows it → cross-test row leakage.
The project's standard dev Postgres already carries `idempotency_keys` with the
real schema, so this NEVER reproduces there.

**Evidence it is NOT a 13-03 regression:**
- 13-03's own acceptance tests all pass on a clean DB:
  `test_percent_splits_risk`, `test_target_lot_matches_volume`,
  `test_sl_less_open_skips_cleanly`, `test_open_with_real_sl_unchanged`, and the
  D-08 backstop `test_default_sl_zero_hard_rejects_text_only`.
- An earlier clean-DB run of `test_staged_executor.py test_staged_safety_hooks.py`
  reported `34 passed, 7 deselected` — the safety-hook suite is GREEN when the
  truncate isolation holds.
- 13-03's production edits (percent-sizing split, `_handle_open` SL-less early skip,
  text-only `signal_sl`/`signal_tp` row keys) do not touch the zone-watch /
  emergency-drain / reconnect-reconcile paths these tests exercise.

**Resolution:** none required for 13-03. The per-wave merge gate (`pytest tests/ -q`
on the project's real dev Postgres) runs the full suite green. This is logged per the
executor scope-boundary rule (out-of-scope, environment-only) and mirrors the same
note 13-01 left for the wave-merge runner.
