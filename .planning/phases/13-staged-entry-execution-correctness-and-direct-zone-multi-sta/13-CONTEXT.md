# Phase 13: Staged-entry execution correctness and direct-zone multi-stage - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Backend-only execution-engine correctness work — the Phase 6 lineage (`trade_manager.py`, `executor.py`, `signal_parser.py`; MT5 REST bridge untouched). Independent of the v1.2 dashboard chain (Phases 8–12).

Close the 6 gaps found in live real-money testing of the Phase 6 staged-entry engine, **carrying forward every Phase 6 decision (D-01..D-39) and every v1.0/v1.1 safety primitive unchanged**:

1. **EXEC2-01** — late zone-watch stages lose the signal's SL/TP (`executor.py:_fire_zone_stage` rebuilds with `default_sl_pips` + `TP=0` instead of carrying the signal SL/TP like at-arrival bands).
2. **EXEC2-02** — `percent` risk-mode does not split `risk_value` across `max_stages` (full `risk_value` per stage → N× exposure); `fixed_lot` already splits correctly.
3. **EXEC2-03** — `/staged` panel `target_lot` display disagrees with the actual percent-mode order volume (UI half of EXEC2-02).
4. **EXEC2-04** — standalone OPEN with no `SL:` line throws `EXECUTION ERROR` (`calculate_sl_distance(entry, None)`, `trade_manager.py:687`) instead of a clean skip.
5. **EXEC2-05** — orphan text-only signal with no follow-up in the window leaves a live position with default SL and no TP, never managed.
6. **EXEC2-06** *(new behavior)* — a standalone OPEN carrying zone+SL+TP must scale into the zone via `compute_bands` (multi-stage), not open one full-size position at `zone_mid`.

**Out of this phase:**
- Any v1.2 dashboard/SPA work (Phases 8–12) — independent chain.
- Changes to the MT5 REST bridge — untouched.
- Front-weighted / adaptive band distribution — see Deferred Ideas.
- Martingale / averaging-down — still explicitly prohibited (Phase 6 boundary).

</domain>

<decisions>
## Implementation Decisions

> Numbering continues the Phase 6 series (D-01..D-39). These are EXEC2-prefixed for this phase.

### EXEC2-06 — direct zone+SL+TP → multi-stage entry mechanics

- **D2-01: Mirror the text-only zone-watcher flow.** A standalone `OPEN` carrying zone+SL+TP routes through the same machinery as the correlated-follow-up path: `compute_bands()` across the zone, register `staged_entries`, fire at-arrival bands, arm the rest, and let `executor.py::_zone_watch_loop` fill them as price enters. **Do NOT use resting-limit orders** — that would create a new reconcile/cancel surface outside the existing safety machinery. Reusing the zone-watcher inherits D-21 (kill-switch drain), D-14 (pre-flight re-check), and D-24 (reconnect reconcile) for free — zero new safety surface.
- **D2-02: Only already-crossed bands fire at arrival — no forced market anchor.** Unlike the text-only flow (where stage 1 always fires at market on the "buy now" semantics), a direct zone signal means "enter across this zone." On arrival, fire only the bands price has already crossed (D-13 in-zone logic); arm the rest. **If price is entirely outside the zone, nothing fires immediately** — all bands wait for price to enter. Price reaching the zone is the trigger.
- **D2-03: First fill anchors the sequence lifetime.** D-16 ("sequence lifetime = stage-1 lifetime") assumed a guaranteed stage-1 anchor, which no longer holds (stage 1 may never fire). Replacement: whichever band fills **first** becomes the anchor; once any stage is live, D-16 applies — when that anchoring position closes (SL/TP/manual), cancel the remaining unfilled bands. Before any fill, the signal's existing **stale / max-age window** governs whether the armed sequence is still valid.
- **D2-04: `max_stages=1` → one band spanning the whole zone.** `compute_bands` yields 0 bands at `max_stages=1`; do not fall back to the v1.0 `zone_mid` full-fill. Instead treat the **entire zone as a single band**: fire at market when price is in/crosses the zone, otherwise arm and wait. Uniform model — every `max_stages` value behaves the same way; satisfies success criterion #1 ("exactly one entry when `max_stages=1`") while eliminating the `zone_mid` single-fill the phase is moving away from.

### EXEC2-01 — late stages carry the signal's actual SL/TP

- **D2-05:** Every staged fill — at-arrival OR fired later by `_zone_watch_loop` — must carry the **signal's actual SL and target TP**, never `default_sl_pips` + `TP=0`. The late-stage firing path (`executor.py::_fire_zone_stage`, currently lines ~799–820) must source the real SL/TP rather than rebuilding from `default_sl_pips`. *Mechanism is the planner's call* — likely persisting the signal SL/TP on the `staged_entries` row at sequence creation so the loop has them when the in-memory signal is gone — but the **outcome is locked**: all stages of one sequence end with consistent, signal-derived SL/TP.

### EXEC2-02 / EXEC2-03 — percent-mode risk split (money semantics)

- **D2-06: `percent` `risk_value` is the TOTAL risk budget for the whole sequence**, split equally: each stage risks `risk_value / max_stages`. A 2% / 4-stage signal risks 0.5% per stage, 2% total only if all stages fill. This matches `fixed_lot` semantics (operator-confirmed: `risk_value` = total across stages, `stage_lot_size()`), the lot-semantics memory, and success criterion #3. Extends D-15 to the percent standalone path.
- **D2-07: `risk_value` is a never-exceeded CEILING — accept partial exposure.** Because each stage is sized `risk_value / max_stages` and deep bands often don't fill, a sequence frequently deploys **less** than the full `risk_value`. That is intended and conservative (under-fill, never over). **No redistribution** — filled stages keep their `risk_value / max_stages` slice; total risk reaches `risk_value` only on a full fill.
- **D2-08 (EXEC2-03):** The `/staged` panel `target_lot` must show the **actually-submitted per-stage slice** (the `risk_value / max_stages` volume), not the full-`risk_value` figure — the display must agree with the real order volume.

### EXEC2-05 — orphan text-only policy (revises Phase 6 D-09)

- **D2-09: Attach a protective exit — do NOT auto-close.** Phase 6 D-09 ("no action on orphan") is superseded. An orphan text-only position (stage 1 filled at market, default SL, no follow-up in the correlation window) must never be left unmanaged: ensure it carries both a stop and a target. Keep the position open riding on its default SL + an assigned protective TP.
- **D2-10: Protective TP = R-multiple off the default-SL distance.** No signal TP exists for an orphan, so derive it from the same `default_sl_pips` distance already used for the SL: `TP = entry ± (sl_distance × R)`. Reuses an existing setting, symmetric, explainable.
- **D2-11: R = 1:1 (R=1), constant.** TP distance = SL distance. Hardcoded constant — no new per-account or global config field. Simplest defensible default for an entry that lost its real target.
- **D2-12: Attach at window-expiry ONLY — via the existing 10s loop.** During the correlation window, leave the position on default SL with no TP (awaiting the real signal TP via follow-up alignment). Only when the window expires **without** a follow-up does `_zone_watch_loop` set the protective TP, converting it to a managed orphan. This avoids a premature close at a default TP if a follow-up is imminent, and reuses the existing 10s zone-watch loop as the watchdog — **no new task**.

### EXEC2-04 — SL-less standalone signal → clean skip

- **D2-13: Skip the whole signal cleanly through the normal skip path.** A standalone OPEN with no `SL:` line (`signal.sl is None`) must be detected **before** `calculate_sl_distance` is called (currently crashes at `trade_manager.py:687`) and routed through the existing skip-result path — same stream as daily-limit / stale skips — with a reason like `"Skipped: signal has no SL (D-08 requires a stop)"`. No exception, no `EXECUTION ERROR` alert. The `sl<=0` **D-08 guard still holds** as the second backstop.

### Edge cases

- **D2-14: Late / past-zone arrivals are rejected by the existing stale check.** A direct multi-stage OPEN can arrive after price has run through/past the zone (all bands would read as "crossed"). The v1.0 `_check_stale` guard runs first and rejects entries too far from the zone, so a moved-market signal is skipped as stale before any band fires. Per-band pre-flight re-check (D-14) is the second backstop. **Never chase a moved market** by firing all crossed bands at market.

### Claude's Discretion

- **EXEC2-01 SL/TP persistence mechanism** — how late stages obtain the signal's real SL/TP (persist on `staged_entries` at creation vs parent-signal lookup). Outcome locked (D2-05); mechanism is the planner's call. Persisting sl/target_tp columns on `staged_entries` is the likely-cleanest approach and additive-only (Phase 5/6 DDL discipline).
- Exact signal_id attribution for a direct-zone sequence (the OPEN's own logged `signal_id`, no parent text-only) — natural reuse of `_handle_open`'s existing `log_signal`.
- Whether `compute_bands` is extended to return a single whole-zone band at `max_stages=1` or the dispatcher special-cases it (D2-04 outcome is what matters).
- Exact reason-string wording for the SL-less skip (D2-13) and orphan-TP audit/log lines.
- Whether the protective-TP attach (D2-12) is a `modify-levels` call mirroring the existing stage-1 align path or a direct TP set.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & success criteria
- `.planning/ROADMAP.md` Phase 13 — goal, the 6 gaps (EXEC2-01..06), 6 success criteria, and the 3 open design forks (all resolved in this context)
- `.planning/STATE.md` §Decisions / §Blockers/Concerns — Phase 13 added 2026-06-08; live-testing gap list

### Phase 6 lineage — the locked decisions this phase carries forward UNCHANGED
- `.planning/phases/06-staged-entry-execution/06-CONTEXT.md` — **read in full.** Critical carried-forward decisions:
  - D-08 (sl=0.0 never acceptable — still the top invariant; EXEC2-04 routes SL-less standalone to a clean skip rather than violating it)
  - D-11..D-14 (zone-watcher model, equal-width bands, in-zone-at-arrival fires immediately, 10s cadence + pre-flight re-check)
  - D-15 (equal risk split across `max_stages` — EXEC2-02 extends this to the percent standalone path)
  - D-16 (sequence lifetime — revised by D2-03 for the no-anchor case)
  - D-18/D-19 (1 signal = 1 daily slot; per-stage `max_open_trades` counting)
  - D-21..D-25 (kill-switch drain, reconnect reconcile, duplicate-direction guard bypass for siblings, comment-based idempotency) — all "no regression" criteria
- `.planning/phases/06-staged-entry-execution/06-CONTEXT.md` §code_context — reusable assets + integration points (still accurate)

### Money semantics
- `/Users/murx/.claude/projects/-Users-murx-Developer-personal-telebot/memory/project_lot_semantics.md` — `fixed_lot` `risk_value` = TOTAL across `max_stages` (operator-confirmed 2026-05-01). EXEC2-02 makes `percent` match this. Do NOT change `stage_lot_size()` fixed_lot semantics.

### Codebase intel
- `.planning/codebase/ARCHITECTURE.md` — `bot.py` / `executor.py` / `trade_manager.py` layering; `_zone_watch_loop` peer to `_heartbeat_loop` / `_cleanup_loop`
- `.planning/codebase/CONVENTIONS.md` — async patterns, DB helper conventions, logging style
- `.planning/codebase/TESTING.md` — pytest-asyncio fixtures, integration-test harness for the staged-entry safety battery (the no-regression criteria must be tested)

### Live code anchors (Phase 13 integration points)
- `trade_manager.py:229-244` — `handle_signal` dispatch; standalone `OPEN` (no correlation) currently falls to `_handle_open`
- `trade_manager.py:548-577` — `_handle_open` (v1.0 single full-fill at `zone_mid`) — the EXEC2-06 rewrite target; should route to the staged/zone-watch path
- `trade_manager.py:474-544` — `_handle_correlated_followup` band/stage logic — the template EXEC2-06 mirrors (D2-01)
- `trade_manager.py:52-117` — `compute_bands`, `stage_lot_size` — `max_stages=1` whole-zone-band handling (D2-04); percent split (D2-06)
- `trade_manager.py:130-160` — `_effective` / risk-mode resolution — percent-mode split fix (EXEC2-02/D2-06)
- `trade_manager.py:679-712` — lot-size calc; percent path applies full `risk_value` today (EXEC2-02 bug site)
- `trade_manager.py:685-728` — `calculate_sl_distance(entry, signal.sl)` at :687 crashes on `sl=None` (EXEC2-04/D2-13); D-08 `sl<=0` guard at :724-729
- `executor.py:521-750` — `_zone_watch_loop` (the watchdog for D2-12 orphan-TP attach)
- `executor.py:752-841` — `_fire_zone_stage` — rebuilds SL from `default_sl_pips`, `target_tp=None` (EXEC2-01 bug site / D2-05)
- `staged_entries` table + `db.py` helpers (`create_staged_entries`, `update_stage_status`, `get_pending_stages`) — likely site for persisting signal SL/target_tp (D2-05, planner's call)

### External docs
- MT5 REST connector — confirm `modify`/TP-set round-trips for the protective-TP attach (D2-12) and that staged-fill SL/TP set correctly

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `executor.py::_zone_watch_loop` — existing 10s polling loop; EXEC2-06 stages ride it (D2-01) and it doubles as the orphan-expiry watchdog (D2-12). No new task needed.
- `executor.py::_fire_zone_stage` — existing late-stage fill builder; EXEC2-01 fix changes its SL/TP source (D2-05).
- `trade_manager.py::_handle_correlated_followup` (474-544) — the working multi-stage template; EXEC2-06's `_handle_open` rewrite mirrors its band-compute → create_staged_entries → at-arrival fire → arm pattern.
- `trade_manager.py::_execute_open_on_account` — single fill path already threads `staged=`, `stage_number=`, `stage_row_id=`, `snapshot=`; EXEC2-06 direct-zone stages reuse it unchanged. D-08 SL guard and D-18/D-19/D-23 gating already here.
- `trade_manager.py::compute_bands` / `stage_lot_size` — band geometry + per-stage sizing; touched by D2-04 (whole-zone band) and D2-06 (percent split).
- `trade_manager.py::_check_stale` — existing staleness guard; D2-14 reuses it to reject past-zone arrivals.
- The stage-1 align path (`_handle_correlated_followup`, ~440-467) — `modify-levels` pattern reusable for the orphan protective-TP attach (D2-12).

### Established Patterns
- **Additive-only DDL** (Phase 5/6 discipline): if EXEC2-01 needs signal SL/target_tp on `staged_entries`, add columns via `CREATE TABLE IF NOT EXISTS` evolution — no `ALTER` on v1.0 tables.
- **Snapshot settings at signal receipt** (D-30): direct-zone sequences snapshot `AccountSettings` the same way correlated ones do.
- **Comment-based idempotency** `telebot-{signal_id}-s{stage}` (D-24/D-25) — direct-zone stages use the same comment scheme; sibling duplicate-guard bypass (D-23) applies.
- **Kill-switch drain-before-close** (D-21) and **reconnect reconcile** (D-24) — inherited automatically by routing EXEC2-06 through the zone-watcher (the explicit reason D2-01 rejects resting-limit orders).
- **No new safety knobs** — orphan R hardcoded 1:1 (D2-11), no new caps; consistent with Phase 6 "fewer knobs, fewer footguns."

### Integration Points
- `trade_manager.py::handle_signal` — uncorrelated standalone `OPEN` must route to the new multi-stage path instead of `_handle_open`'s single fill.
- `executor.py::_zone_watch_loop` — add orphan-expiry protective-TP check (D2-12); ensure direct-zone sequences (signal_id = own OPEN id) are picked up by the same loop and reconnect reconcile.
- `db.py` — possible new `staged_entries` columns for persisted signal SL/target_tp (D2-05); `/staged` query must return the per-stage slice for the panel (D2-08).
- The `/staged` panel serializer (dashboard/API layer) — `target_lot` must reflect actual submitted volume (EXEC2-03/D2-08). Note: this is the one read-only display touch; confirm it doesn't cross into the v1.2 SPA chain's untouched bot-core boundary.

</code_context>

<specifics>
## Specific Ideas

- **"Enter across the zone" is literal.** A direct zone signal does not fire a market anchor — price reaching the zone is the only trigger (D2-02). This deliberately differs from the text-only "buy now" semantics, which DOES anchor at market.
- **"Never chase a moved market."** If price has already run past the zone, the signal is stale and skipped — not filled at a worse price (D2-14). This is the whole point of EXEC2-06 replacing the `zone_mid` full-fill.
- **"risk_value is a ceiling, never a target to force-hit."** Partial fills are good — they mean less risk deployed, never more (D2-07). No redistribution logic.
- **"An orphan must never be unmanaged, but don't pre-empt the real target."** Protective TP only attaches at window expiry, so a fast-arriving follow-up still gets to set the real SL/TP first (D2-12).
- **"Reuse the zone-watcher's safety machinery — that's why we don't use resting limits."** The explicit rationale for D2-01: kill-switch drain, pre-flight, reconnect reconcile all come for free.

</specifics>

<deferred>
## Deferred Ideas

- **Front-weighted / adaptive band distribution** — narrower near-edge bands to improve fill rate on narrow zones (addresses "deep stages rarely fill"). Deferred; this is a pure-correctness phase. Equal-width (D-12) stays.
- **Configurable orphan TP ratio** (`zone_orphan_tp_ratio` global knob) — deferred; hardcoded 1:1 for now (D2-11). Revisit only if the operator wants 1:2+ orphans.
- **`default_tp_pips` per-account setting** — an alternative orphan-TP source rejected in favor of the R-multiple off existing default SL; deferred unless an explicit independent TP distance is later wanted.
- **Risk redistribution to filled stages** — making total ≈ `risk_value` despite unfilled deep stages. Deferred (rejected by D2-07's never-exceed stance); would require dynamic resizing.
- **Carried forward from Phase 6 deferred set** (still deferred): adaptive zone reshape on follow-up update, trailing-activation staging, per-symbol adaptive cadence, MT5 tick streaming, auto-close watchdog on orphans (now partially addressed by the protective-TP policy), `trade_stages` analytics view.

None of these block Phase 13.

</deferred>

---

*Phase: 13-staged-entry-execution-correctness-and-direct-zone-multi-sta*
*Context gathered: 2026-06-08*
