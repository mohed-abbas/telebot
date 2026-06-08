# Phase 13: Staged-entry execution correctness and direct-zone multi-stage - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-08
**Phase:** 13-staged-entry-execution-correctness-and-direct-zone-multi-sta
**Areas discussed:** EXEC2-06 entry mechanics, Band distribution, EXEC2-05 orphan policy, Risk-split + edge cases

---

## EXEC2-06 entry mechanics

### Q1 — Which mechanism places the stages for a direct zone+SL+TP OPEN?

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror text-only flow | Reuse the Phase 6 zone-watcher (compute_bands + _zone_watch_loop); inherits D-21/D-14/D-24 safety machinery | ✓ |
| All resting-limit orders | Submit N limit orders across the zone; fills survive disconnect but create a new reconcile/cancel surface | |
| You decide | — | |

**User's choice:** Mirror text-only flow
**Notes:** Locked because it inherits kill-switch drain, pre-flight re-check, and reconnect reconcile for free — zero new safety surface in a real-money correctness phase.

### Q2 — Which stages fire immediately on arrival?

| Option | Description | Selected |
|--------|-------------|----------|
| Only crossed bands | Fire only bands price has already entered; arm the rest; nothing fires if price outside the zone | ✓ |
| Force stage-1 at market | Always fire stage 1 at market like text-only, regardless of price position | |
| You decide | — | |

**User's choice:** Only crossed bands
**Notes:** A direct zone signal means "enter across the zone" — no "now" semantics, so no forced market anchor.

### Q3 — What bounds the sequence lifetime with no guaranteed stage-1 anchor?

| Option | Description | Selected |
|--------|-------------|----------|
| First fill anchors it | First filled band becomes the anchor; D-16 then applies; pre-fill validity via existing stale/max-age window | ✓ |
| Fixed expiry window | Arm all bands for a fixed duration; cancel unfilled at expiry; adds a timer/new knob | |
| You decide | — | |

**User's choice:** First fill anchors it
**Notes:** Reuses D-16 with minimal change for the no-anchor case.

### Q4 — How should a direct zone signal enter when max_stages=1?

| Option | Description | Selected |
|--------|-------------|----------|
| One band = whole zone | Treat entire zone as one band: market when in/crossed, else arm and wait; uniform with multi-stage path | ✓ |
| Keep v1.0 single-fill | Fall back to _handle_open: market if in zone else resting limit at zone_mid | |
| You decide | — | |

**User's choice:** One band = whole zone
**Notes:** Uniform model across all max_stages values; eliminates the zone_mid full-fill entirely.

---

## Band distribution

### Q1 — Change the equal-width band layout (D-12)?

| Option | Description | Selected |
|--------|-------------|----------|
| Keep equal-width | Stay with D-12 equal-width contiguous bands; accept that deep stages rarely fill | ✓ |
| Front-weight toward entry edge | Narrower near-edge bands to improve fill rate; adds distribution algorithm + likely new knob | |
| You decide | — | |

**User's choice:** Keep equal-width
**Notes:** Pure-correctness phase; no new distribution behavior. Unfilled deep bands simply expire with the sequence.

---

## EXEC2-05 orphan policy

### Q1 — Policy for an orphan text-only position (no follow-up in window)?

| Option | Description | Selected |
|--------|-------------|----------|
| Attach protective exit | Keep position; ensure it has both SL and TP so it's never unmanaged | ✓ |
| Auto-close at expiry | Close/cancel the orphan entirely at window expiry | |
| Let me explain | — | |

**User's choice:** Attach protective exit
**Notes:** Revises Phase 6 D-09 ("no action"). Keep riding the entry but make it managed.

### Q2 — How to derive the protective TP (no signal TP)?

| Option | Description | Selected |
|--------|-------------|----------|
| R-multiple off default SL | TP = entry ± (sl_distance × R) using the existing default_sl_pips distance | ✓ |
| Fixed default_tp_pips | Add a new per-account TP-distance setting | |
| You decide | — | |

**User's choice:** R-multiple off default SL
**Notes:** Reuses an existing setting; consistent with "no new safety knobs."

### Q3 — When to attach the protective TP?

| Option | Description | Selected |
|--------|-------------|----------|
| At window expiry only | Set protective TP only when window expires with no follow-up; existing 10s loop is the watchdog | ✓ |
| At stage-1 fill | Set TP immediately on fill; follow-up overwrites it; risks premature close at default TP | |
| You decide | — | |

**User's choice:** At window expiry only
**Notes:** Avoids pre-empting the real signal TP if a follow-up is imminent; no new task.

### Q4 — What R-multiple for the orphan TP?

| Option | Description | Selected |
|--------|-------------|----------|
| 1:1 (R=1) | TP distance = SL distance; hardcoded constant, no new config | ✓ |
| 1:2 (R=2) | TP distance = 2× SL distance | |
| Configurable ratio | New global zone_orphan_tp_ratio knob | |

**User's choice:** 1:1 (R=1)
**Notes:** Simplest defensible default; symmetric.

---

## Risk-split + edge cases

### Q1 — percent-mode risk semantics (EXEC2-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Total split across stages | risk_value is the TOTAL budget; each stage risks risk_value / max_stages; matches fixed_lot | ✓ |
| Per-stage with a cap | Keep risk_value per-stage with a total ceiling; diverges from fixed_lot | |
| You decide | — | |

**User's choice:** Total split across stages
**Notes:** Matches the lot-semantics memory and success criterion #3. /staged target_lot must show the per-stage slice (EXEC2-03).

### Q2 — Partial-fill exposure intended?

| Option | Description | Selected |
|--------|-------------|----------|
| Accept partial exposure | Unfilled stages mean less risk deployed; no redistribution; risk_value is a ceiling | ✓ |
| Redistribute to filled stages | Resize filled stages so total ≈ risk_value; complex, can exceed plan | |
| You decide | — | |

**User's choice:** Accept partial exposure
**Notes:** Matches conservative-bot principle — total risk never exceeds risk_value.

### Q3 — Late / past-zone arrival handling

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse existing stale check | _check_stale rejects entries too far from the zone before any band fires; pre-flight is backstop | ✓ |
| Fire all crossed bands at market | Treat a passed zone as all-crossed and fill at market; chases a moved market | |
| You decide | — | |

**User's choice:** Reuse existing stale check
**Notes:** Never chase a moved market — the core point of EXEC2-06.

### Q4 — SL-less standalone signal (EXEC2-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Normal skip + reason | Route through the existing skip path with a reason; no exception, no EXECUTION ERROR | ✓ |
| Distinct warning alert | Skip but raise a separate conspicuous warning for malformed signals | |
| You decide | — | |

**User's choice:** Normal skip + reason
**Notes:** Consistent with every other skip reason; D-08 sl<=0 guard remains the backstop.

---

## Claude's Discretion

- EXEC2-01 SL/TP persistence mechanism (persist on staged_entries vs parent-signal lookup) — outcome locked, mechanism is the planner's call.
- signal_id attribution for direct-zone sequences (the OPEN's own logged id).
- Whether compute_bands itself or the dispatcher handles the max_stages=1 whole-zone band.
- Exact reason-string wording for the SL-less skip and orphan-TP log/audit lines.
- Whether the protective-TP attach uses the modify-levels align path or a direct TP set.

## Deferred Ideas

- Front-weighted / adaptive band distribution.
- Configurable orphan TP ratio (zone_orphan_tp_ratio).
- default_tp_pips per-account setting.
- Risk redistribution to filled stages.
- Carried-forward Phase 6 deferrals (adaptive zone reshape, trailing-activation, per-symbol adaptive cadence, MT5 tick streaming, trade_stages analytics view).
