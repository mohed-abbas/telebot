---
slug: 260501-tpc-cancel-pending-stages-on-tp-sl
status: in-progress
created: 2026-05-01
---

# Quick Task: Auto-cancel pending stages when price reaches signal TP or SL

## Problem
A stage that's still `awaiting_zone` keeps waiting indefinitely (or until the
30-minute reconnect-abandon path) even when the trade's exit levels (TP2 / SL)
have already been hit on price. Operator wants pending stages cancelled the
moment live price reaches the signal's target_tp or sl, regardless of whether
stage 1's broker-side close has already propagated.

## Existing related logic
D-16 cascade in `executor.py:470-505` already cancels pending stages when
stage 1's MT5 position has disappeared. That requires:
  - the broker to have actually closed the position, AND
  - the next zone-watch tick to fetch positions and detect the absence.

The new check is **price-based** and runs FIRST (faster, broker-independent):
during the same tick where we fetch `bid/ask` for a (account, symbol) group,
we also check each signal_id's stored `sl + tp` against the live price.

## Files

1. **db.py** — add helpers:
   - `async def get_signal_targets(signal_id: int) -> dict | None`
     returns `{direction, sl, tp}` or None.
   - `async def cancel_unfilled_stages_target_reached(signal_id: int, reason: str) -> int`
     mirrors `cancel_unfilled_stages_for_signal` but sets
     `status='cancelled_target_reached'`. Reason field carries which level
     ("tp_reached" or "sl_reached").
   - Update `get_recently_resolved_stages` query to include the new status
     in its WHERE clause.

2. **executor.py** — in `_zone_watch_loop`, after fetching `bid, ask` for the
   (account, symbol) group, before per-stage iteration:
   - Build `signal_ids = {s["signal_id"] for s in stages}`.
   - For each signal_id, fetch targets ONCE (memoized per tick).
   - Direction-aware check:
       * BUY  → cancel if `bid >= tp` (and tp > 0) OR `bid <= sl` (and sl > 0)
       * SELL → cancel if `ask <= tp` (and tp > 0) OR `ask >= sl` (and sl > 0)
   - On cancel: call new helper, log `INFO`, populate per-tick skip-set so the
     band-fire loop also skips those stages.

3. **dashboard.py** — add `"cancelled_target_reached": "Target/SL reached"`
   to `_RESOLVED_STATUS_LABELS`.

4. **tests/test_staged_safety_hooks.py** — add 3 regression tests:
   - BUY: bid touches tp → stage 2 status flips to cancelled_target_reached
   - BUY: bid touches sl → stage 2 status flips to cancelled_target_reached
   - BUY: bid still inside zone (between sl and tp) → no cancel

## Out of scope
- TP1/TP2 distinction (per operator: only TP2 — already what's stored in
  `signals.tp` because `target_tp` defaults to TP2).
- SELL direction — symmetric logic, same code path; covered by direction guard.
- Re-evaluation of ALREADY-filled stages (already-open positions are managed
  by the broker's SL/TP on the position, not here).

## Atomic commits
1. `feat(db): add get_signal_targets + cancel_unfilled_stages_target_reached helpers`
2. `feat(executor): auto-cancel pending stages when price reaches signal TP or SL`
3. `feat(dashboard): label cancelled_target_reached in resolved-stages section`
4. `test(executor): regression coverage for price-based stage cancellation`
