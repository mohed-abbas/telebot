---
phase: 13-staged-entry-execution-correctness-and-direct-zone-multi-sta
plan: 04
subsystem: live-money staged-entry execution engine (orphan protective-TP watchdog)
tags: [executor, zone-watch, orphan, protective-tp, exec2-05, watchdog, tdd, wave-2, deploy-at-end]
requires:
  - "staged_entries.signal_sl / signal_tp columns + text-only stage-1 persistence (Plans 13-01 / 13-03)"
  - "connector.modify_position(ticket, sl=, tp=) → OrderResult(success, ticket, error) (DryRun + REST impls, Phase 6)"
  - "GlobalConfig.correlation_window_seconds (default 600) — orphan window-expiry threshold"
  - "stage-1-align failure-isolated modify_position + log_signal audit pattern (trade_manager.py:418-467)"
  - "GOLD_PIP_SIZE for XAUUSD pip-size (executor.py, parity with _fire_zone_stage)"
provides:
  - "db.get_orphan_candidate_stage1s(window_seconds): DB-side orphan/window-expiry detection (filled stage-1 + aged past window + live ticket + NO sibling stage_number>=2)"
  - "executor._run_orphan_protective_tp_watchdog: self-fetching watchdog, runs FIRST each _zone_watch_loop tick, independent of get_active_stages (an orphan has no awaiting_zone siblings)"
  - "executor._attach_one_orphan_protective_tp: R=1:1 protective TP = entry ± default_sl_pips*pip_size; SL preserved; idempotent (skip non-zero TP); failure-isolated; orphan_protective_tp audit row"
  - "test_orphan_protective_tp_at_expiry / test_orphan_no_tp_during_window / test_orphan_tp_idempotent_when_already_set / test_orphan_with_sibling_gets_no_protective_tp — all GREEN"
affects:
  - "Supersedes Phase 6 D-09 (the prior 'no action on orphan' policy) — no unmanaged text-only orphans"
  - "Plan 05 (EXEC2-06 direct-zone multistage) shares the _zone_watch_loop the watchdog now runs inside"
tech-stack:
  added: []
  patterns:
    - "DB-side window-expiry detection (the in-memory correlator pops the orphan on pairing → cannot be queried at expiry; RESEARCH Open Q1) via NOW() - make_interval + NOT EXISTS sibling check"
    - "Idempotency without schema: read the live position's CURRENT TP and skip when non-zero — survives reconnect / loop re-ticks (RESEARCH Open Q2)"
    - "Self-fetching watchdog inside the existing 10s loop (no new asyncio task) — an orphan has NO siblings so it never appears in get_active_stages(), forcing an independent candidate fetch rather than the plan's inline-after-positions_by_comment sketch"
    - "Failure isolation at three layers (watchdog wrapper, per-pair get_positions, per-row modify/audit) mirroring the stage-1-align pattern — one connector error never aborts the loop"
key-files:
  created: []
  modified:
    - db.py
    - executor.py
    - tests/test_staged_safety_hooks.py
    - .planning/phases/13-staged-entry-execution-correctness-and-direct-zone-multi-sta/deferred-items.md
decisions:
  - "Window-expiry detection lives in db.get_orphan_candidate_stage1s, NOT inline in the loop after positions_by_comment as the plan sketched — an orphan stage-1 has no sibling stages, so it is absent from get_active_stages()/by_pair; the watchdog MUST fetch its own candidates. This is the only path that can ever see an orphan (Rule 3 blocking-issue deviation)."
  - "R=1:1 is the literal constant 1: TP distance == SL distance == default_sl_pips*pip_size; no *_tp_ratio config knob added (D2-10/D2-11). grep confirms 0 tp_ratio occurrences."
  - "Idempotency reads position.tp and skips when != 0.0 (Open Q2) — no persisted flag, no schema change; survives reconnects and loop re-ticks."
  - "SL is preserved verbatim (modify_position called with sl=existing position.sl) — the default SL from the orphan open stays, only the TP is assigned (D-08 preserved)."
  - "default_sl_pips resolved from the frozen snapshot_settings (json-safe parse, defaults to 100) for parity with _fire_zone_stage / the orphan stage-1 open distance."
  - "Watchdog runs FIRST each tick, wrapped in its own try/except, ahead of the get_active_stages band-fire path; a watchdog error logs and continues into the normal loop body."
  - "Live MT5 modify/TP round-trip DEFERRED to single VPS end-to-end acceptance (deploy-at-end, operator-approved) — DryRunConnector tests gate the logic; no fabricated live sign-off."
metrics:
  duration: ~20min
  tasks: 1
  files: 4
  completed: 2026-06-08
---

# Phase 13 Plan 04: Orphan Protective-TP at Window Expiry Summary

EXEC2-05 (D2-09..D2-12) closes the last unmanaged-position gap: a text-only OPEN that fills stage 1 at market on its default SL and never gets a follow-up within the correlation window is no longer left riding with no target. At window expiry the existing 10s `_zone_watch_loop` now attaches an R=1:1 protective TP (TP distance == the default-SL distance) off the position's entry, keeping its default SL untouched. Detection is done DB-side (the in-memory correlator has already popped the orphan, so it cannot be queried at expiry), the attach is idempotent against reconnects/re-ticks by reading the live position's current TP, and every step is failure-isolated so a single connector error never aborts the loop. No new asyncio task and no new config knob. This supersedes Phase 6 D-09.

## What Was Built

### Task 1 — Orphan protective-TP watchdog (commit 6795e81)

**`db.py::get_orphan_candidate_stage1s(window_seconds)`** — the DB-side orphan/window-expiry oracle (RESEARCH Open Q1). Selects `stage_number = 1` rows that are `status = 'filled'` with a live `mt5_ticket IS NOT NULL`, `created_at < NOW() - make_interval(secs => $1)` (the correlation window has expired), AND `NOT EXISTS (… stage_number >= 2 sibling …)` (a follow-up would have created siblings). Returns the candidate rows; idempotency is decided downstream off the live position.

**`executor._run_orphan_protective_tp_watchdog()`** — runs FIRST and independently each `_zone_watch_loop` tick, before the `get_active_stages()` band-fire path, inside its own try/except. It resolves `correlation_window_seconds` (default 600), fetches candidates, groups them by `(account, symbol)`, runs `get_positions()` once per connector, builds `positions_by_comment`, skips reconnecting accounts, and dispatches each row to `_attach_one_orphan_protective_tp`. The independent fetch is essential: an orphan has no sibling stages, so it is never returned by `get_active_stages()` and could not be reached by the plan's inline-after-`positions_by_comment` sketch.

**`executor._attach_one_orphan_protective_tp(...)`** — for a single orphan: resolve the live position by comment `telebot-{signal_id}-s1` (return if MT5 shows none — just-closed); **idempotency** — read `position.tp` and return if non-zero (Open Q2); resolve `default_sl_pips` from the frozen `snapshot_settings` (json-safe, default 100); `pip_size = GOLD_PIP_SIZE` for XAUUSD; `sl_distance = default_sl_pips * pip_size`; `protective_tp = entry + sl_distance` (buy) / `entry - sl_distance` (sell) — **R=1:1**, no knob; call `connector.modify_position(ticket, sl=existing_sl, tp=protective_tp)` inside try/except (logs + returns on error). On `success`, emit a `log_signal` audit row with `signal_type="orphan_protective_tp"` (audit-log failure is itself isolated).

**Tests added to `tests/test_staged_safety_hooks.py`** (the Wave-0 RED stubs `test_orphan_protective_tp_at_expiry` / `test_orphan_no_tp_during_window` filled in, plus two new Rule-2 guards):
- `test_orphan_protective_tp_at_expiry` — backdated orphan past the 600s window → `modify_position` called with `tp == entry ± default_sl_pips*pip_size`, SL unchanged.
- `test_orphan_no_tp_during_window` — fresh orphan (age < window) → NO `modify_position` (don't pre-empt a follow-up's real target).
- `test_orphan_tp_idempotent_when_already_set` (Rule 2 / Open Q2) — orphan whose live position already has a TP → NO `modify_position`.
- `test_orphan_with_sibling_gets_no_protective_tp` (Rule 2) — a stage-1 with a `stage_number>=2` sibling (follow-up arrived) is not an orphan → `pos.tp == 0.0`, no protective TP even after the window.

## Verification Results

Run in a `python:3.12-slim` container against an ephemeral `postgres:16-alpine` (the project's standard dev-container harness; host has no pytest/Postgres).

- **Acceptance:**
  - `pytest tests/test_staged_safety_hooks.py -k "orphan_protective_tp_at_expiry or orphan_no_tp_during_window" -x -q` → passed. (All 4 `-k orphan` tests pass.)
  - No new asyncio task: `grep -c "asyncio.create_task" executor.py` = **5 at parent (6795e81^) and 5 now** — unchanged. The watchdog is a method call inside the existing loop.
  - No new config knob: `grep -c "tp_ratio" executor.py` = **0** (R is the literal constant 1).
  - Idempotency path present: `_attach_one_orphan_protective_tp` reads `position.tp` and returns when non-zero.
- **No-regression battery:** `pytest tests/test_staged_safety_hooks.py tests/test_staged_executor.py` → 40 passed; the only failures are 3 intentional Plan-05 (EXEC2-06) RED stubs in `test_staged_executor.py` (`test_direct_zone_multistage`, `test_direct_zone_single_band`, `test_direct_zone_arms_when_outside`) — byte-for-byte unmodified by this plan, self-documenting "implemented in Plan 05". Logged to `deferred-items.md` (out of scope).

## Live Verification — code-complete; live sign-off DEFERRED to VPS end-to-end acceptance

The DryRunConnector cannot exercise the real MT5 `modify_position`/TP round-trip. Per `project_deploy_at_end_workflow.md` and the operator-approved option (a) — following the Plans 12-02 / 12-03 precedent — the live MT5 sign-off is **DEFERRED to the single VPS end-to-end acceptance**. The automated DryRun tests gate the logic; this 5-step smoke gates the live behavior at final VPS acceptance. No fabricated live sign-off.

**VPS smoke procedure (MT5 demo, run at end-to-end acceptance):**
1. Fire a text-only OPEN (orphan) and let stage 1 fill at market with its default SL.
2. Do NOT send a follow-up. Wait past `correlation_window_seconds` (default 600s).
3. Confirm within ~10s after expiry the position shows a TP at distance == its SL distance (R=1:1), SL unchanged.
4. Confirm the TP is set exactly once (no repeated modifies on subsequent loop ticks).
5. Repeat but send a follow-up before expiry → confirm NO protective TP is applied (the follow-up's real SL/TP wins).

(Procedure also appended to `13-.../deferred-items.md`.)

## Deviations from Plan

**[Rule 3 — blocking-issue / structural correction] Self-fetching watchdog instead of inline-after-`positions_by_comment`**
- **Found during:** Task 1.
- **Issue:** The plan's `<action>` sketched the orphan check as an inline pass over `stage_number == 1` rows "after `positions_by_comment` is built" inside the per-(account,symbol) group. But `positions_by_comment` there is derived from `get_active_stages()`, which only returns `awaiting_zone`/active staged rows — an orphan has **no sibling stages**, so it is **never present** in that set. The inline approach could never see an orphan.
- **Fix:** Added `db.get_orphan_candidate_stage1s(window_seconds)` as the DB-side oracle and a dedicated `_run_orphan_protective_tp_watchdog` that fetches its own candidates, groups by pair, and runs its own `get_positions()`. It still runs inside the existing 10s `_zone_watch_loop` (no new asyncio task), honoring the plan's "reuse the existing watchdog / no new loop" constraint.
- **Files:** `db.py`, `executor.py`. **Commit:** 6795e81.

**[Rule 2 — added guard tests] `test_orphan_tp_idempotent_when_already_set`, `test_orphan_with_sibling_gets_no_protective_tp`**
- **Added during:** Task 1.
- **Why:** The threat register assigns `mitigate` to T-13-11 (double-modify across reconnect) and T-13-10 (pre-empting a real follow-up). Idempotency and the no-sibling gate are correctness requirements, not optional features; explicit regression tests prove both. Plan acceptance also enumerates both behaviors in `<behavior>`.
- **Files:** `tests/test_staged_safety_hooks.py`. **Commit:** 6795e81.

No production-code deviations beyond the single described EXEC2-05 attach + its DB oracle.

## Checkpoint Resolution

Task 2 (`checkpoint:human-verify`, gate=blocking) — the live VPS acceptance — resolved by operator approval of option (a) **Defer (deploy-at-end)**: live MT5 sign-off DEFERRED to the single VPS end-to-end acceptance, mirroring the Plans 12-02/12-03 precedent. Recorded above and in `deferred-items.md`; no live sign-off fabricated.

## Threat Surface

The four STRIDE mitigations assigned to this plan are satisfied:
- **T-13-09 (unmanaged orphan):** window-expiry attach of an R=1:1 protective TP; default SL preserved. Proven by `test_orphan_protective_tp_at_expiry`.
- **T-13-10 (pre-empting a real follow-up target):** attach ONLY after age > `correlation_window_seconds` AND only with no sibling stages (both enforced by `get_orphan_candidate_stage1s`). Proven by `test_orphan_no_tp_during_window` + `test_orphan_with_sibling_gets_no_protective_tp`.
- **T-13-11 (double-modify across reconnect):** read live position TP, skip if non-zero — no schema change. Proven by `test_orphan_tp_idempotent_when_already_set`.
- **T-13-12 (one modify failure aborts loop):** try/except at the watchdog, per-pair, and per-row layers, mirroring stage-1-align; logged + continue.
- **T-13-SC:** no package installs — in-repo edits only.

No new threat surface introduced — all edits are in-file, no network endpoints, no new auth/trust boundary.

## Known Stubs

None introduced by this plan. The remaining RED stubs in the touched/adjacent test files (`test_direct_zone_*` — Plan 05) belong to Plan 13-05 and are intentionally RED until EXEC2-06 lands.

## Self-Check: PASSED

- `db.py`, `executor.py`, `tests/test_staged_safety_hooks.py`, and `13-.../deferred-items.md` all exist on disk and carry the 6795e81 changes. ✅
- Task 1 commit exists in git log: 6795e81. ✅
- `grep -c "asyncio.create_task" executor.py` = 5 (unchanged from parent); `grep -c "tp_ratio" executor.py` = 0. ✅
- All 4 `-k orphan` acceptance tests GREEN in the python:3.12 + dev-Postgres container; 3 remaining failures are out-of-scope Plan-05 RED stubs (deferred-items.md). ✅
