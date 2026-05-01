---
quick_id: 260501-mrw
status: complete
tasks_completed: 1
commits:
  - 08477cf
tests_passed: true
files_modified:
  - db.py
  - trade_manager.py
  - tests/test_trade_manager.py
---

# Quick 260501-mrw — Align stage-1 SL/TP with correlated follow-up

One-liner: stage-1 MT5 position now gets its SL/TP modified to the follow-up's
jittered plan the moment a correlated follow-up arrives, with D-17 failure
isolation so a modify reject can't abort band creation.

## What changed

- `db.py:1139-1153` — new `get_stage_by_signal_account(signal_id, account_name, stage_number)`
  async helper. Uses parameterized SELECT (`$1, $2, $3`) on
  `staged_entries (signal_id, account_name, stage_number)`. Returns dict|None.
  Multi-account safe (the existing `get_stage_by_comment` collides across
  accounts because of the `mt5_comment UNIQUE` constraint — that's the
  deferred bug, see below).
- `trade_manager.py:396-475` — new stage-1 alignment block inserted at the
  top of the per-account loop in `_handle_correlated_followup`, after the
  snapshot fetch and BEFORE `max_stages = ...`. The block:
  - Looks up stage 1 via the new helper (per `(paired_signal_id, acct_name, 1)`).
  - Skips silently when stage 1 is missing, not yet filled, or has no `mt5_ticket`.
  - Computes `new_sl = calculate_sl_with_jitter(signal.sl, jitter, direction)`
    and `new_tp = calculate_tp_with_jitter(signal.target_tp, jitter, direction)`
    when `signal.target_tp` truthy; otherwise `new_tp = 0.0` (guards against
    `target_tp=None`).
  - Calls `connector.modify_position(ticket, sl=new_sl, tp=new_tp)` inside
    a try/except — any raised exception is converted to an `OrderResult(success=False, ...)`
    so band creation always proceeds (D-17).
  - On success: appends `{"status": "stage1_aligned", "ticket": ..., "sl": ..., "tp": ...}`
    and writes a `db.log_signal(signal_type='modify_sl_tp', ...)` audit row.
    Audit-row failures are also wrapped in try/except so they cannot abort.
  - On failure: appends `{"status": "stage1_align_failed", "ticket": ..., "reason": ...}`.
- `tests/test_trade_manager.py:317-559` — new `TestCorrelatedFollowupStage1Align`
  class with 4 regression tests:
  - `test_followup_aligns_stage1_sl_and_tp_when_filled` — happy path, asserts
    `modify_position` await with jittered SL/TP plus `stage1_aligned` result
    plus `db.log_signal(signal_type='modify_sl_tp')` audit row.
  - `test_followup_skips_stage1_align_when_not_filled` — stage1 row exists
    but `status='awaiting_zone'` and `mt5_ticket=None`; asserts no modify call,
    no `stage1_*` results, but `staged` band-summary still present.
  - `test_followup_continues_band_fill_when_stage1_align_fails` — D-17
    isolation; modify returns `success=False`, asserts `stage1_align_failed`
    AND `staged` summary both present.
  - `test_followup_with_no_tp_still_aligns_stage1_sl` — `target_tp=None`
    edge case; asserts modify still called with `sl=jittered_sl, tp=0.0`
    and no exception from the jitter call (None-guard works).

## How verified

- `pytest tests/test_trade_manager.py -v -k "stage1_align or followup_aligns or followup_skips or followup_continues or followup_with_no_tp"` → 4 passed (the new tests).
- `pytest tests/test_trade_manager.py -v` → 19 passed, 4 skipped (the
  4 skips are db-integration tests requiring Postgres; same skip pattern
  pre-change).
- `pytest -x` smoke → fails on the documented pre-existing
  `tests/test_rest_api_connector.py::TestConnect::test_connect_sends_correct_json_and_sets_connected`
  failure noted in the prior 260501-i7u SUMMARY. Two adjacent rest-api
  connector/integration failures (`test_connect_clears_password_on_success`,
  `test_full_market_buy_flow`) are also pre-existing — verified by stashing
  this plan's changes and re-running: same 2 failures reproduce on a clean
  tree. Out of scope per plan.

Commit: `08477cf` (single atomic commit covering helper + call site + tests).
No `Co-Authored-By` footer per `feedback_no_coauthor.md`.

## Live verification needed

Operator must run on Vantage Demo-10k:

1. Send `Gold buy now` (text-only). Wait for stage 1 to fill — dashboard
   shows ticket + SL=default-derived + TP=—.
2. Send the structured follow-up (zone + SL + TP).
3. Within ~3s the dashboard should show:
   - Stage 1 ticket: SL = jittered(follow-up.SL), TP = jittered(follow-up.TP)
     — visually aligned with stages 2/3.
   - Stages 2/3: same as before (jittered follow-up SL/TP).
4. Inspect `signals` table: a row with `signal_type='modify_sl_tp'` and
   `action_taken` containing `stage1_aligned ticket=...`.
5. Negative path (optional): send a follow-up BEFORE stage 1 fills — confirm
   no errors, bands still get created, no `stage1_align_failed` row.

## Deferred

- **Multi-account stage-1 `mt5_comment` UNIQUE collision** — `_handle_text_only_open:313`
  builds `comment = f"telebot-{signal_id}-s1"` without the account name.
  With multiple accounts enabled, the second account's stage-1 insert will
  violate `mt5_comment UNIQUE` and silently skip. Operator runs single-account
  today, so this is dormant. The new `get_stage_by_signal_account(signal_id, account, 1)`
  helper added by this plan is the right shape to fix it later (account-scoped
  lookup). Track as a future quick task.

## Out of scope (operator-confirmed)

- `stage_lot_size()` and the lot-size branches in `_execute_open_on_account`
  remain untouched — operator confirmed lot-size semantics are intentional.
- No SL/TP columns added to `staged_entries` (snapshot_settings already
  captures fill-time state).
- No `trades` table SL/TP backfill (dashboard reads positions live from MT5).
- The 3 pre-existing rest-api connector/integration test failures are
  unrelated to this plan.

## Self-Check: PASSED

- File `db.py` modified — `get_stage_by_signal_account` present at line 1139.
- File `trade_manager.py` modified — alignment block present in
  `_handle_correlated_followup`.
- File `tests/test_trade_manager.py` modified — `TestCorrelatedFollowupStage1Align`
  class with 4 tests appended.
- Commit `08477cf` exists in `git log` on `main`.
- All 4 new tests pass; no regressions in `tests/test_trade_manager.py`.
