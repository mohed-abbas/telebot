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

## Plan-05 RED stubs failing in the 13-04 no-regression battery — out of scope

**Discovered during:** Plan 13-04 Task 1 verification (no-regression battery
`pytest tests/test_staged_safety_hooks.py tests/test_staged_executor.py` on the dev
Postgres `tb13pg`).

**Symptom:** 3 failures in `tests/test_staged_executor.py` —
`test_direct_zone_multistage`, `test_direct_zone_single_band`,
`test_direct_zone_arms_when_outside`.

**Root cause:** these are intentional Wave-0 RED `pytest.fail` stubs for
**EXEC2-06 (Plan 05)**, each explicitly self-documenting "implemented in Plan 05".
They are unrelated to EXEC2-05 / Plan 13-04 (orphan protective-TP).

**Evidence it is NOT a 13-04 regression:**
- `tests/test_staged_executor.py` is byte-for-byte unmodified by Plan 13-04
  (`git diff --name-only` shows only `db.py`, `executor.py`,
  `tests/test_staged_safety_hooks.py`).
- They are bare `pytest.fail(...)` stub bodies — they fail identically at the
  13-04 baseline regardless of any executor/db change.
- All 4 orphan tests (`-k orphan`) and the rest of the safety-hook battery pass
  (40 passed in the combined run).

**Resolution:** none required for 13-04. These turn green when Plan 13-05
(EXEC2-06 direct-zone multistage) lands. Logged per the executor scope-boundary rule.

## Plan-13-04 EXEC2-05 live MT5 sign-off — DEFERRED to single VPS end-to-end acceptance

**Status:** code-complete; live sign-off DEFERRED (deploy-at-end, operator-approved).

The orphan protective-TP attach (`executor._run_orphan_protective_tp_watchdog` /
`_attach_one_orphan_protective_tp`, commit 6795e81) is fully gated by DryRunConnector
tests (`test_orphan_protective_tp_at_expiry`, `test_orphan_no_tp_during_window`,
`test_orphan_tp_idempotent_when_already_set`,
`test_orphan_with_sibling_gets_no_protective_tp` — all GREEN). The real MT5
`modify_position`/TP round-trip cannot run under DryRun. Per
`project_deploy_at_end_workflow.md` and the operator approval of option (a) — mirroring
the Plans 12-02 / 12-03 precedent — the live MT5 sign-off is DEFERRED to the single VPS
end-to-end acceptance. No live sign-off is fabricated here.

**VPS smoke procedure (MT5 demo, run at end-to-end acceptance):**
1. Fire a text-only OPEN (orphan) and let stage 1 fill at market with its default SL.
2. Do NOT send a follow-up. Wait past `correlation_window_seconds` (default 600s).
3. Confirm within ~10s after expiry the position shows a TP at distance == its SL
   distance (R=1:1), SL unchanged.
4. Confirm the TP is set exactly once (no repeated modifies on subsequent loop ticks).
5. Repeat but send a follow-up before expiry → confirm NO protective TP is applied
   (the follow-up's real SL/TP wins).

## Plan-13-05 — staged `mt5_comment` global-UNIQUE collides across accounts (architectural, Rule 4)

**Discovered during:** Plan 13-05 Task 1 verification — updating
`tests/test_trade_manager_integration.py::TestMultiAccountExecution` after the
EXEC2-06 `_handle_open` rewrite.

**Symptom:** A single standalone OPEN dispatched to TWO accounts raises
`asyncpg.UniqueViolationError: duplicate key value violates unique constraint
"staged_entries_mt5_comment_key"` on the second account's stage-1 insert
(`mt5_comment = telebot-{signal_id}-s1`).

**Root cause (PRE-EXISTING Phase-6 limitation, surfaced — not introduced — by EXEC2-06):**
`staged_entries.mt5_comment` is `TEXT NOT NULL UNIQUE` *globally* (db.py:230), and the
comment scheme `telebot-{signal_id}-s{stage}` carries NO account discriminator. Because
`_handle_open` calls `db.log_signal` ONCE, all accounts share one `signal_id`, so account
#2 generates the identical `telebot-{id}-s{stage}` comment and collides. The CORRELATED
path uses the identical scheme (`telebot-{paired_signal_id}-s{stage}`) and would collide
the same way; db.py:1023-1024 already documents that `mt5_comment` UNIQUE "makes
`get_stage_by_comment()` collide across accounts" and provides
`get_stage_by_signal_account()` as the per-account-safe lookup. No prior test exercised a
multi-account staged sequence, so the constraint was never hit until EXEC2-06 made EVERY
standalone OPEN staged.

**Why deferred (Rule 4 — architectural):** The fix is one of:
  (a) make the comment account-scoped (e.g. `telebot-{signal_id}-{account}-s{stage}`), or
  (b) relax the global UNIQUE to a composite `UNIQUE(account_name, mt5_comment)`.
Either touches the D-25 idempotency probe (`get_stage_by_comment`), the D-24 reconnect
reconcile-by-comment path, and the executor cascade's `telebot-{id}-s1` anchor lookup —
i.e. it changes a contract shared by the correlated path and the live-money safety
machinery. That is an architectural decision spanning beyond EXEC2-06's
`trade_manager._handle_open` scope and must be planned deliberately (its own plan/phase),
not auto-applied mid-execution.

**Current behavior is safe (failure-isolated, D-17):** account #1 stages and fires
normally; account #2's collision surfaces as an error after #1 has already executed — no
double-fire, no wrong-size entry. The deploy-at-end reality is single-account MT5 demo, so
this does not block the VPS acceptance. The integration test
`test_signal_dispatches_to_both_accounts` asserts the documented collision (and is written
to also pass if the scheme is later made account-scoped).

**Resolution:** none in Plan 13-05. Recommend a follow-up plan to make the staged
`mt5_comment` account-scoped (option (a) preferred — keeps a single UNIQUE column and a
human-legible comment) with a coordinated update to `get_stage_by_comment`, the reconnect
reconcile, and the executor stage-1 anchor lookup.

---

## TEST-INFRA — session-scoped asyncpg pool vs function-loop fixtures (orchestrator, post-Wave-2 gate)

**Surfaced by:** Phase 13 post-merge gate (orchestrator), 2026-06-08.

**Symptom:** Running the full single-process test suite (or all of `tests/test_trade_manager.py`
in one process) yields order-dependent `asyncpg InterfaceError: another operation is in progress`
and `RuntimeError: Future attached to a different loop`. Baseline (pre-Phase-13) already carried
22 such errors in `tests/test_api_*`. Phase 13 added two DB-touching direct-zone tests
(`test_direct_zone_past_market_stale`, `test_direct_zone_in_zone_not_stale_proceeds`) that now
also trip it when the whole file runs.

**Root cause (not production code):** `db_pool` is `loop_scope="session"`, but the consuming
async fixtures (`tm_with_store`, `priced_connector`, `seeded_staged_account`, …) are default
function-loop fixtures. They `await` pool work on a function loop, stranding a pool connection on
the wrong loop for later session-loop tests. A naive `loop_scope="session"` on the fixtures is NOT
safe because the seed fixtures must stay function-scoped (the autouse `clean_tables` TRUNCATEs
between tests).

**Evidence production code is correct:** every Phase-13 acceptance test passes in per-file
isolation, and the two direct-zone tests pass when run alone (`2 passed`). EXEC2-01..06 logic is
verified green on dev Postgres `tb13pg`.

**Recommended follow-up (out of Phase 13 scope):** a dedicated test-infra plan to align the async
fixture/loop architecture — e.g. a session-scoped pool created per-test-loop, or per-test pool
fixtures, or a single explicit event-loop policy — so the full suite is deterministic in one
process. Until then, CI should run DB test files in isolated processes (one file per `pytest`
invocation), as the executors and this gate did.
