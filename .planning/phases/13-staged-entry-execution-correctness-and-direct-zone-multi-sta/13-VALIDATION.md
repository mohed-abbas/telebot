---
phase: 13
slug: staged-entry-execution-correctness-and-direct-zone-multi-sta
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-08
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> This phase modifies **live-money execution paths** — the carried-forward Phase 6 safety battery (D-18/D-21/D-22/D-23/D-24/D-25, stale, cascade) MUST stay green at every commit.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio (`loop_scope="session"`) |
| **Config file** | none — pytest defaults; `tests/conftest.py` holds fixtures (`tm_with_store`, `_PricedDry`, `make_signal`, `executor_fixture`) |
| **Quick run command** | `pytest tests/test_staged_executor.py tests/test_staged_safety_hooks.py -x` |
| **Full suite command** | `pytest tests/ -q` (requires dev Postgres at `localhost:5433`, Python 3.12 container; DryRunConnector — no live MT5) |
| **Estimated runtime** | ~30 seconds quick · ~90 seconds full |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_staged_executor.py tests/test_staged_safety_hooks.py -x`
- **After every plan wave:** Run `pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~30 seconds (quick core)

---

## Per-Task Verification Map

| Req ID | Behavior | Test Type | Automated Command | File Exists | Status |
|--------|----------|-----------|-------------------|-------------|--------|
| EXEC2-01 | Late zone-watch stage carries signal SL/TP (not default+`TP=0`) | integration | `pytest tests/test_staged_executor.py -k late_stage_carries_signal_sl_tp` | ❌ W0 | ⬜ pending |
| EXEC2-01 | Correlated price-cascade fires using persisted signal SL/TP (revives dormant no-op) | integration | `pytest tests/test_staged_safety_hooks.py -k correlated_cascade_uses_persisted_tp` | ❌ W0 | ⬜ pending |
| EXEC2-02 | `percent` submitted volume == `risk_value / max_stages` per stage | unit+integration | `pytest tests/test_staged_executor.py -k percent_splits_risk` | ❌ W0 | ⬜ pending |
| EXEC2-03 | `/staged` `target_lot` == actually-submitted volume | contract | `pytest tests/test_stages_contract.py -k target_lot_matches_volume` | ❌ W0 (extend) | ⬜ pending |
| EXEC2-04 | SL-less OPEN → clean skip, no exception/`EXECUTION ERROR` | integration | `pytest tests/test_trade_manager.py -k sl_less_open_skips_cleanly` | ❌ W0 | ⬜ pending |
| EXEC2-04 | D-08 `sl<=0` backstop still holds | regression | `pytest -k test_default_sl_zero_hard_rejects_text_only` | ✅ | ⬜ pending |
| EXEC2-05 | Orphan gets protective TP at window expiry (R=1:1) | integration | `pytest tests/test_staged_safety_hooks.py -k orphan_protective_tp_at_expiry` | ❌ W0 | ⬜ pending |
| EXEC2-05 | Orphan does NOT get TP during window (don't pre-empt follow-up) | integration | `pytest tests/test_staged_safety_hooks.py -k orphan_no_tp_during_window` | ❌ W0 | ⬜ pending |
| EXEC2-06 | Standalone zone+SL+TP → N stages (`max_stages=N`) | integration | `pytest tests/test_staged_executor.py -k direct_zone_multistage` | ❌ W0 | ⬜ pending |
| EXEC2-06 | `max_stages=1` → exactly one whole-zone entry (no `zone_mid`) | integration | `pytest tests/test_staged_executor.py -k direct_zone_single_band` | ❌ W0 | ⬜ pending |
| EXEC2-06 | Price entirely outside zone → nothing fires at arrival (D2-02) | integration | `pytest tests/test_staged_executor.py -k direct_zone_arms_when_outside` | ❌ W0 | ⬜ pending |
| EXEC2-06 | Past-zone arrival rejected as stale (D2-14) | integration | `pytest tests/test_trade_manager.py -k direct_zone_past_market_stale` | ❌ W0 | ⬜ pending |
| EXEC2-06 | Direct-zone inherits kill-switch drain + reconnect reconcile (D2-01) | regression | re-run D-21/D-24 tests with direct-zone `signal_id` | ✅ extend | ⬜ pending |

### No-regression battery (carried-forward Phase 6 invariants — must stay green)

| Behavior | Decision | Existing test |
|----------|----------|---------------|
| Kill-switch drain BEFORE close | D-21/D-22 | `test_emergency_close_drains_staged_before_positions`, `test_resume_trading_does_not_uncancel_drained_stages` |
| Reconnect reconcile by comment | D-24 | `test_reconnect_marks_filled_when_comment_exists_on_mt5`, `test_reconnect_marks_abandoned_when_signal_aged_and_no_mt5_position`, `test_reconnect_leaves_young_unfilled_stages_alone` |
| Daily-slot accounting (1 signal = 1 slot) | D-18 | `test_one_signal_id_one_daily_slot`, `test_mark_signal_counted_today_idempotent` |
| Duplicate-direction guard + sibling bypass | D-23 | `test_dup_guard_bypass_same_signal_id_different_stage`, `test_dup_guard_still_rejects_unrelated_same_direction` |
| Comment-based idempotency | D-25 | `test_zone_watch_idempotency_probe_marks_filled_without_submit`, `test_reconcile_after_reconnect_matches_by_comment` |
| Stale re-check / stage-1 cascade | D-14/D-16 | `test_zone_watch_cancels_remaining_stages_when_stage1_closed`, `test_zone_watch_does_not_cascade_when_stage1_still_awaiting` |
| Price-target cascade | cascade | `test_zone_watch_cancels_pending_stages_when_price_reaches_tp/sl`, `test_zone_watch_does_not_cancel_when_price_between_sl_and_tp` |
| max_open_trades per-stage cap | D-19 | `test_stage_marked_capped_when_max_open_trades_reached` |
| Failure isolation | D-17 | `test_stage_marked_failed_on_broker_reject_others_continue` |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_staged_executor.py` — new stubs: `late_stage_carries_signal_sl_tp`, `percent_splits_risk`, `direct_zone_multistage`, `direct_zone_single_band`, `direct_zone_arms_when_outside`
- [ ] `tests/test_staged_safety_hooks.py` — new stubs: `correlated_cascade_uses_persisted_tp`, `orphan_protective_tp_at_expiry`, `orphan_no_tp_during_window`
- [ ] `tests/test_trade_manager.py` — new stubs: `sl_less_open_skips_cleanly`, `direct_zone_past_market_stale`
- [ ] `tests/test_stages_contract.py` — extend with `target_lot_matches_volume`
- [ ] Framework already installed (pytest-asyncio present) — no install task

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live-money staged scale-in against MT5 demo | EXEC2-01..06 | DryRunConnector cannot exercise the real MT5 `modify`/TP round-trip; deploy-at-end policy | Per `project_deploy_at_end_workflow.md`: single VPS end-to-end acceptance with MT5 demo — fire a direct zone+SL+TP signal, confirm N stages fill with signal SL/TP and correct per-stage volume; confirm orphan gets R=1 protective TP at window expiry |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
