---
phase: 13-staged-entry-execution-correctness-and-direct-zone-multi-sta
plan: 05
subsystem: trade-execution
tags: [staged-entry, trade-manager, zone-scale-in, compute_bands, stale-check, multi-stage, EXEC2-06]

# Dependency graph
requires:
  - phase: 13-03
    provides: "percent risk split + _handle_open SL-less early skip + staged_entries.signal_sl/signal_tp columns + create-site row keys"
  - phase: 06-staged-entry-execution
    provides: "compute_bands / stage_is_in_zone_at_arrival / stage_lot_size helpers, _zone_watch_loop, D-14/D-16/D-21/D-24/D-25 safety machinery, _handle_correlated_followup band-lifecycle template"
provides:
  - "_handle_open rewritten as a multi-stage zone scale-in (N bands numbered 1..N, fire crossed bands at arrival, arm the rest) mirroring _handle_correlated_followup"
  - "D2-04 whole-zone single band at max_stages=1 (no zone_mid fallback, no no_bands reuse)"
  - "D2-02 at-arrival-only firing (price outside zone → nothing fires, all bands arm)"
  - "D2-14 pre-band stale rejection (moved-market arrival → clean skip, no staged rows)"
  - "create-site persistence of signal_sl/signal_tp on every direct-zone row"
  - "shared staged integration fixtures (_PricedDry/priced_connector/tm_with_store) promoted to conftest"
affects: [phase-13-verify, vps-end-to-end-acceptance, future-multi-account-comment-scheme-plan]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Direct-zone band numbering 1..N (lowest band = stage 1) vs correlated 2..N — uniform model giving the executor D-16 cascade a real telebot-{id}-s1 anchor that may never fill"
    - "compute_bands(max_stages+1) to obtain N bands for the direct path (the helper emits max_stages-1 bands for the correlated case where stage 1 is external)"
    - "pre-band _check_stale guard runs FIRST per account (reuses the existing helper + threshold; no new heuristic)"

key-files:
  created: []
  modified:
    - "trade_manager.py — _handle_open multi-stage rewrite + pre-band stale guard"
    - "tests/test_staged_executor.py — 3 direct_zone integration tests (RED→GREEN); local fixtures removed (promoted)"
    - "tests/test_trade_manager.py — 2 D2-14 stale tests + updated EXEC2-04 guard test"
    - "tests/conftest.py — promoted _PricedDry/priced_connector/tm_with_store fixtures"
    - "tests/test_trade_manager_integration.py — updated 7 tests to the staged scale-in contract; fixtures seed accounts"
    - ".planning/phases/13-.../deferred-items.md — multi-account mt5_comment UNIQUE collision (Rule 4)"

key-decisions:
  - "Direct-zone bands numbered 1..N (lowest = stage 1); call compute_bands with max_stages+1 to get N bands then re-base numbering — keeps the model uniform and gives the executor cascade a real s1 anchor (Pitfall 6 verified safe at executor.py:733-736)"
  - "D2-04 max_stages=1 synthesizes ONE whole-zone Band(1, zone_low, zone_high); no zone_mid fallback, no reuse of the correlated empty-band branch (Pitfall 5)"
  - "Pre-band _check_stale guard fetches price once up front, reused for the at-arrival fire decision (removed the duplicate post-create get_price)"
  - "Multi-account staged mt5_comment collision is a PRE-EXISTING Phase-6 scheme limitation surfaced (not introduced) by EXEC2-06 — deferred as a Rule-4 architectural follow-up rather than auto-changing the shared comment/UNIQUE contract"
  - "Live MT5 sign-off DEFERRED to single VPS end-to-end acceptance (deploy-at-end, operator-approved; mirrors Plans 12-02/12-03/13-04)"

patterns-established:
  - "Direct-zone scale-in routes through staged_entries + _zone_watch_loop (NO resting limits, D2-01) → inherits D-21 drain / D-14 pre-flight / D-24 reconnect reconcile for free"
  - "Stale check precedes the band lifecycle so a moved market never creates staged rows (D2-14); D-14 per-band pre-flight stays the second backstop"

requirements-completed: [EXEC2-06]

# Metrics
duration: ~40min
completed: 2026-06-08
---

# Phase 13 Plan 05: Direct-zone multi-stage `_handle_open` Summary

**Standalone zone+SL+TP OPENs now scale across the zone as N staged bands (numbered 1..N, whole-zone band at max_stages=1) mirroring `_handle_correlated_followup`, firing only already-crossed bands at arrival and rejecting moved-market arrivals as stale before any band fires — replacing the v1.0 single `zone_mid` full-fill.**

## Performance

- **Duration:** ~40 min
- **Started:** 2026-06-08
- **Completed:** 2026-06-08
- **Tasks:** 2 auto tasks (TDD) + 1 human-verify checkpoint (deferred per deploy-at-end)
- **Files modified:** 6

## Accomplishments

- **EXEC2-06 / D2-01..D2-04:** `_handle_open` rewritten from the v1.0 single `zone_mid` full-fill into a multi-stage scale-in — per account: snapshot → `compute_bands` → build rows → `create_staged_entries` (status `awaiting_zone`) → fetch price → fire at-arrival crossed bands at market → arm the rest. Routes through `staged_entries` + the zone-watcher (NO resting limits) so it inherits kill-switch drain, pre-flight, and reconnect reconcile.
- **D2-04 whole-zone band:** `max_stages=1` synthesizes exactly ONE `Band(1, zone_low, zone_high)` and runs it through the same at-arrival/arm logic — no `zone_mid` fallback, no reuse of the correlated empty-band branch.
- **D2-02 at-arrival-only firing:** only bands price has already crossed fire; price entirely outside the zone → nothing fires, all bands arm for `_zone_watch_loop`.
- **D2-14 pre-band stale rejection:** the existing `_check_stale` guard runs FIRST (per account) — a past-zone (moved-market) arrival returns a clean stale skip with NO staged rows created; D-14 per-band pre-flight remains the second backstop.
- **EXEC2-01 carry:** every direct-zone row persists `signal_sl=signal.sl` / `signal_tp=signal.target_tp` (the OPEN's own `log_signal` id, no `paired_signal_id`); fired stages use a synth `SignalAction` carrying the real SL/TP.
- 5 new tests RED→GREEN; full plan core suite (integration + staged_executor + trade_manager + safety_hooks) 81 passed; remaining staged DB/contract/schema/attribution 18 passed / 1 skipped.

## Task Commits

1. **Task 1 RED: failing direct-zone multistage tests** - `65e2f01` (test)
2. **Task 1 GREEN: `_handle_open` multi-stage scale-in rewrite** - `629e858` (feat)
3. **Task 2 RED: failing D2-14 past-zone stale tests + promote fixtures** - `3551b58` (test)
4. **Task 2 GREEN: pre-band stale guard + regression-fixed integration tests** - `ac6b8e2` (feat)

**Task 3 (checkpoint):** live VPS acceptance — DEFERRED (see Checkpoint Disposition).

_TDD: each task is a test(RED) → feat(GREEN) pair._

## Files Created/Modified

- `trade_manager.py` — `_handle_open` rewritten as a per-account band lifecycle (compute_bands → create_staged_entries → at-arrival fire → arm) with a pre-band `_check_stale` guard; degenerate `entry_zone is None` path preserves v1.0 single-fill behavior.
- `tests/test_staged_executor.py` — `test_direct_zone_multistage` / `test_direct_zone_single_band` / `test_direct_zone_arms_when_outside`; local `_PricedDry`/`priced_connector`/`tm_with_store` removed (now shared via conftest).
- `tests/test_trade_manager.py` — `test_direct_zone_past_market_stale` / `test_direct_zone_in_zone_not_stale_proceeds`; `test_open_with_real_sl_unchanged` updated to stub `create_staged_entries` for the now-staged path.
- `tests/conftest.py` — promoted `_PricedDry`, `priced_connector`, `tm_with_store` fixtures.
- `tests/test_trade_manager_integration.py` — 7 tests updated to the staged scale-in contract; `tm`/`multi_account_tm` fixtures now seed `accounts` (staged_entries FK).
- `.planning/phases/13-.../deferred-items.md` — logged the multi-account `mt5_comment` UNIQUE collision (Rule 4 architectural follow-up).

## Decisions Made

- **Stage numbering 1..N for direct-zone (vs 2..N correlated).** The correlated path's stage 1 is an external text-only market fill, so `compute_bands` emits `max_stages-1` bands. The direct path has no external anchor — every stage is a band — so it calls `compute_bands(max_stages+1)` to get N bands and re-bases them to 1..N. The lowest band is stage 1, giving the executor's D-16 cascade a real `telebot-{id}-s1` anchor that may never fill; verified safe at `executor.py:733-736` ("stage 1 still awaiting → fire OK", no spurious cascade). Documented because Pitfall 6 called this out as the key direct-vs-correlated divergence.
- **Pre-band stale guard fetches price once.** `_check_stale` now runs before `compute_bands`; the same `bid/ask` is reused for the at-arrival fire decision (removed the duplicate `get_price`).
- **Live sign-off deferred** to the single VPS end-to-end acceptance (deploy-at-end, operator-approved precedent).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Direct-zone band count: compute_bands yields N-1, plan/truth requires N stages**
- **Found during:** Task 1 (GREEN)
- **Issue:** `compute_bands(max_stages)` returns `max_stages-1` bands (designed for the correlated case where stage 1 is the external text-only fill). For the direct path the truth is "max_stages=N → N stages"; a naive call produced only N-1 bands.
- **Fix:** For `max_stages>=2`, call `compute_bands(zone_low, zone_high, max_stages+1, direction)` and re-base the returned stages 2..(N+1) to 1..N. `max_stages=1` keeps the synthesized whole-zone band.
- **Files modified:** trade_manager.py
- **Verification:** `test_direct_zone_multistage` asserts exactly 5 stages numbered 1..5 for max_stages=5.
- **Committed in:** `629e858`

**2. [Rule 1 - Bug] Pre-EXEC2-06 tests encode the v1.0 single-fill / resting-limit contract that EXEC2-06 deliberately changes**
- **Found during:** Task 2 (GREEN) — full plan-suite run after the rewrite
- **Issue:** `test_open_with_real_sl_unchanged` (test_trade_manager.py) and 7 tests in `test_trade_manager_integration.py` (`test_open_sell_market_in_zone`, `test_open_buy_limit_above_zone`, `test_open_sell_with_db_logging`, `test_daily_limit_blocks_trades`, `test_signal_executes_on_both_accounts`, `test_sell_in_zone_market_order`, `test_buy_above_zone_limit_order`) all asserted the v1.0 standalone-OPEN behavior (single market/limit fill, zone-midpoint resting limit, single result) and used `tm` fixtures that did not seed the `accounts` table required by the new `staged_entries` FK. All 7 integration tests passed on the pre-plan baseline (`c1d8103`) and failed after the rewrite — genuine, expected consequences of EXEC2-06.
- **Fix:** Updated the tests to the staged scale-in contract: in-zone OPEN → whole-zone band fires at market + a `staged` summary; above-zone OPEN → band ARMS (D2-01: no resting limit); daily-limit/multi-account/zone-logic assertions scan for executed/skipped across results; `tm`/`multi_account_tm` fixtures seed `accounts` + `account_settings`. `test_open_with_real_sl_unchanged` now stubs `create_staged_entries` while still proving `calculate_sl_distance` is reached and no SL-less skip occurs.
- **Files modified:** tests/test_trade_manager.py, tests/test_trade_manager_integration.py
- **Verification:** 81 passed across integration + staged_executor + trade_manager + safety_hooks.
- **Committed in:** `ac6b8e2`

**3. [Rule 3 - Blocking] Shared staged fixtures not visible to test_trade_manager.py**
- **Found during:** Task 2 (RED)
- **Issue:** The D2-14 stale tests need `tm_with_store`/`priced_connector`, which were defined locally in `test_staged_executor.py` and unavailable in `test_trade_manager.py`.
- **Fix:** Promoted `_PricedDry`, `priced_connector`, `tm_with_store` to `tests/conftest.py` (mirrors the Plan 01 `seeded_signal` promotion) and removed the local copies.
- **Files modified:** tests/conftest.py, tests/test_staged_executor.py
- **Verification:** Both files green with the shared fixtures.
- **Committed in:** `3551b58`

### Architectural finding (Rule 4 — deferred, NOT auto-applied)

**4. [Rule 4 - Architectural] Staged `mt5_comment` is globally UNIQUE with no account discriminator**
- **Found during:** Task 2 (updating the multi-account integration test)
- **Issue:** `staged_entries.mt5_comment` is `TEXT NOT NULL UNIQUE` globally (db.py:230) and the scheme `telebot-{signal_id}-s{stage}` carries no account name. A single OPEN dispatched to N accounts shares one `signal_id` (one `log_signal`), so account #2's stage-1 row collides. This is a PRE-EXISTING Phase-6 scheme limitation (the correlated path uses the identical scheme; db.py:1023-1024 documents the cross-account collision) that EXEC2-06 surfaces by making every standalone OPEN staged.
- **Why not auto-fixed:** The fix (account-scoped comment or composite `UNIQUE(account_name, mt5_comment)`) changes a contract shared by the D-25 idempotency probe, D-24 reconnect reconcile-by-comment, and the executor's stage-1 anchor lookup — an architectural decision beyond `trade_manager._handle_open`. Per Rule 4 it was NOT applied mid-execution.
- **Disposition:** Logged to `deferred-items.md` with a recommended follow-up (account-scoped comment preferred). Current behavior is failure-isolated (D-17) and safe under single-account deploy-at-end. The integration test `test_signal_dispatches_to_both_accounts` asserts the documented collision and is written to also pass if the scheme is later made account-scoped.

---

**Total deviations:** 3 auto-fixed (2 Rule-1 bugs, 1 Rule-3 blocking) + 1 Rule-4 architectural finding deferred.
**Impact on plan:** Auto-fixes were necessary to make the EXEC2-06 behavior change land cleanly and keep the no-regression battery green. The Rule-4 finding is a pre-existing limitation surfaced (not introduced) by the plan; deferred deliberately. No scope creep into the comment-scheme contract.

## Threat Surface / Mitigations Applied

- **T-13-13 (wrong-size/wrong-SL entry):** mitigated — band scale-in carries the signal's real SL/TP per stage; verified by `test_direct_zone_multistage`/`test_direct_zone_single_band`.
- **T-13-14 / T-13-15 (chase a moved market / fire all crossed bands on a gap-through):** mitigated — `_check_stale` runs FIRST and rejects past-zone arrivals before any band fires; only genuinely-crossed bands fire when not stale; verified by `test_direct_zone_past_market_stale`.
- **T-13-16 (loss of kill-switch/reconnect coverage):** mitigated — NO resting limits; armed rows ride `_zone_watch_loop`; D-21/D-24 staged tests stay green with a direct-zone signal_id.
- **T-13-17 (max_stages=1 collides with follow-up empty-band branch):** mitigated — dedicated synthesized whole-zone band; `no_bands` token absent from `_handle_open`.

## Checkpoint Disposition (Task 3 — live VPS acceptance, deploy-at-end)

**Code-complete; live MT5 sign-off DEFERRED to the single VPS end-to-end acceptance.**

The direct-zone multi-stage behavior is fully gated by DryRunConnector tests (the three `direct_zone_*` cases + the D2-14 stale cases, all GREEN). The live MT5 staged scale-in cannot run under DryRun. Per `project_deploy_at_end_workflow.md` and the operator-approved precedent (Plans 12-02 / 12-03 / 13-04), the live sign-off is deferred to the single VPS end-to-end acceptance — no live sign-off is fabricated here.

**VPS smoke procedure (MT5 demo, run at end-to-end acceptance):**
1. Fire a standalone OPEN with zone+SL+TP and `max_stages=N`; confirm N stages register, already-crossed bands fill with the signal's SL and TP (not default SL / TP=0) at the per-stage volume, and the rest arm.
2. Let price walk into the zone; confirm armed bands fill as price enters, each carrying the signal SL/TP.
3. Fire the same with `max_stages=1`; confirm exactly ONE whole-zone entry (no zone_mid single-fill).
4. Fire an OPEN whose price has already run past the zone; confirm it is skipped as stale and NO order is placed.
5. Confirm a direct-zone sequence is drained by the kill-switch and reconciled on reconnect (inherited safety).

## Issues Encountered

- Establishing the integration-test baseline required running the pre-plan `trade_manager.py` (`c1d8103`) against the dev Postgres to confirm the 7 failures were genuine EXEC2-06 consequences (all 11 passed pre-plan), not environmental noise — resolved and documented.

## User Setup Required

None — no external service configuration required (in-repo Python edits only).

## Next Phase Readiness

- EXEC2-06 (the last of the six Phase-13 execution-correctness gaps) is code-complete; all Phase-13 plans (13-01..13-05) are now executed.
- **Ready for `/gsd:verify-work 13`** after the full no-regression battery on the dev Postgres.
- **Carried to VPS acceptance:** the deferred live MT5 sign-offs for 13-04 (orphan protective-TP) and 13-05 (direct-zone multi-stage), plus the deferred multi-account `mt5_comment` architectural follow-up.

## Self-Check: PASSED

- `13-05-SUMMARY.md` — FOUND
- Commit `65e2f01` (test Task 1 RED) — FOUND
- Commit `629e858` (feat Task 1 GREEN) — FOUND
- Commit `3551b58` (test Task 2 RED + fixtures) — FOUND
- Commit `ac6b8e2` (feat Task 2 GREEN + regression fixes) — FOUND

---
*Phase: 13-staged-entry-execution-correctness-and-direct-zone-multi-sta*
*Completed: 2026-06-08*
