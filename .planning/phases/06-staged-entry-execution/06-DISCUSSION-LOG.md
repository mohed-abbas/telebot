# Phase 6: Staged entry execution - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-19
**Phase:** 06-staged-entry-execution
**Areas discussed:** Stage 2..N trigger mechanism, Correlation + orphan safety, Daily-limit accounting, Dashboard UX (STAGE-08 + SET-03)

---

## Gray-Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Stage 2..N trigger mechanism | When follow-up zone signal arrives, how do stages 2..N fire? | ✓ |
| Correlation + orphan safety | Correlation window, multi-orphan handling, no-follow-up behavior, orphan cap | ✓ |
| Daily-limit accounting (blocking) | 1 signal = 1 slot vs 1 stage = 1 slot | ✓ |
| Dashboard UX (STAGE-08 + SET-03) | Pending-stages panel + settings edit form | ✓ |

**User's choice:** All four areas.

---

## Stage 2..N Trigger Mechanism

### Core trigger model

| Option | Description | Selected |
|--------|-------------|----------|
| Zone-watcher bands (Recommended) | Subdivide zone into N-1 bands; background task fires each stage as price enters band | ✓ |
| Batch-fire immediately | Open N-1 market positions immediately on follow-up arrival | |
| Single re-entry threshold | Single mid-zone price fires all remaining stages at once | |
| Limit orders at band edges | Place N-1 MT5 pending limit orders, broker fills at each level | |

**User's choice:** Zone-watcher bands.

### Band derivation

| Option | Description | Selected |
|--------|-------------|----------|
| Equal slices (Recommended) | (max_stages-1) equal-width contiguous bands across zone | ✓ |
| Signal-specified prices | Signal payload enumerates per-stage entry prices | |
| Mid-zone as single band | Whole zone = one band; all stages fire on first entry | |
| Skip — using batch-fire | N/A (zone-watcher chosen) | |

**User's choice:** Equal slices.

### Per-stage lot sizing

| Option | Description | Selected |
|--------|-------------|----------|
| Equal split (Recommended) | risk_value / max_stages per stage (from snapshotted settings) | ✓ |
| Full risk per stage | Each stage sized as standalone (risk × N total exposure) | |
| Signal-specified sizing | Payload dictates per-stage sizing | |
| Fixed split with front-loading | Stage 1 weighted 40%, rest split remainder | |

**User's choice:** Equal split.

### Cadence + pre-flight re-check

| Option | Description | Selected |
|--------|-------------|----------|
| 10s uniform + pre-flight re-check (Recommended) | 10s polling all symbols; pre-submit re-fetch bid/ask, verify band ±0.5×width | ✓ |
| Per-symbol adaptive | 2s XAU/BTC, 10s majors | |
| Event-driven MT5 ticks | Subscribe to tick stream (needs connector confirmation) | |
| Slower cadence — 5s | 5s uniform no tuning | |

**User's choice:** 10s uniform + pre-flight re-check.

### Follow-up edge cases (second batch)

| Question | Options Presented | User's Choice |
|----------|-------------------|---------------|
| Price already in zone at follow-up arrival | Fire crossed stages immediately (rec) / Fire one stage, wait for others / Skip crossed bands / Wait for re-entry | **Fire crossed stages immediately** |
| Price exits zone after stage 1 fills, never returns | Expire after max_age_minutes (rec) / Cancel on first exit / Keep pending indefinitely / Cancel when SL or TP hit on stage 1 | **Cancel when SL or TP hit on stage 1** |
| Stage N fails at broker | Continue with next stages (rec) / Abort entire sequence / Retry once then continue / Retry once then abort | **Continue with next stages** |
| Sequence active-window duration | 60 min (rec) / 30 min / Reuse signal.max_age_minutes / Until stage 1 closes | **Until stage 1 closes (SL/TP)** |

**Notes:** User's exit-zone + expiry choices align into one elegant rule: "Sequence lifetime = stage-1 lifetime." No separate max_age_minutes timer; remaining unfilled stages are cancelled when stage 1's position exits. Captured as D-16 in CONTEXT.md.

---

## Correlation + Orphan Safety

| Question | Options Presented | User's Choice |
|----------|-------------------|---------------|
| Correlation window | 10 min (rec) / 30 min / 5 min / Per-source configurable | **10 minutes** |
| Multi-orphan disambiguation | Most recent (rec) / Oldest / All matching / Reject if ambiguous | **Most recent same symbol+direction** |
| No follow-up arrives | Leave with default SL, no action (rec) / Auto-close at expiry / Force heuristic SL+TP / Notify + keep open | **Leave with default SL; no action** |
| Per-account orphan cap | Use max_open_trades (rec) / New max_orphan_text_only / No cap / Global single-orphan rule | **Use max_open_trades** |

**Notes:** Orphan safety posture is "rely on the default SL + existing guards." No new knobs, no watchdog auto-close, no dedicated orphan cap. Captured as D-04..D-10.

---

## Daily-Limit Accounting

| Question | Options Presented | User's Choice |
|----------|-------------------|---------------|
| max_daily_trades counting rule | 1 signal = 1 slot (rec) / 1 stage = 1 slot / 1 signal except orphans / Per-account configurable | **1 signal = 1 slot** |
| max_open_trades counting rule | Yes stages count (rec) / Signal = 1 / Cap stage count too / Separate cap | **Yes — stages count** |
| Attribution persistence (additive-only) | staged_entries.signal_id helper (rec) / New daily_stats_by_signal table / Check trades.signal_id / Defer to planner | **staged_entries.signal_id + new helper** |
| Failed stages counting | No, only successes (rec) / Yes, any attempt / Failures count per signal / Only count retries after N failures | **No — only successful fills count** |

**Notes:** Schema discipline is tight — no ALTER on daily_stats; signal-id attribution lives on the new staged_entries table. Captured as D-18..D-20.

---

## Dashboard UX (STAGE-08 + SET-03)

| Question | Options Presented | User's Choice |
|----------|-------------------|---------------|
| Pending-stages panel location | Overview partial + drill-down link (rec) / Standalone /staged only / Sidebar widget / Modal drawer | **Overview partial + drill-down link** |
| Pending-stages panel info (multi) | Account name (rec) / Live price + distance-to-next-band / Cancel button per row / Signal source + raw text peek | **Account name + Live price + distance-to-next-band** |
| Settings edit form layout | Tabs per account (rec) / Accordion per account / One page per account / Single combined table | **Tabs per account** |
| Dangerous-change confirm + rollback | Two-step modal + audit rollback (rec) / Inline confirm only / Dry-run, no rollback / No confirm, undo toast | **Two-step modal + audit rollback** |

**Notes:** User wants operational observability on the pending panel (live price + distance-to-next-band beyond the required minimum). Inline cancel button NOT selected — kill switch remains the single-point intervention for live-money safety. Captured as D-26..D-36.

---

## Claude's Discretion

Areas where user deferred to Claude's judgment:

- Exact `staged_entries` DDL column types, constraints, and indexes
- Whether `snapshot_settings` is JSONB or flat columns on `staged_entries`
- `_zone_watch_loop` task structure (recommended: sibling to `_heartbeat_loop` + `_cleanup_loop`)
- Signal correlator data structure (in-memory dict vs DB query per signal)
- Regex/keyword surface for "now" text-only recognition
- `SignalType.OPEN_TEXT_ONLY` as enum value vs `is_text_only: bool` flag
- Settings form field ordering inside each account tab
- `/staged` as separate route vs query view
- Band tolerance constant (0.5×band_width default) promotability to `GlobalConfig`

## Deferred Ideas

Captured in CONTEXT.md `<deferred>` section. Highlights:

- Adaptive zone reshape on follow-up updates (v1.2)
- Trailing-activation (stage N arms only after N-1 fills) (v1.2)
- Per-symbol adaptive cadence (v1.2)
- MT5 tick streaming (requires connector research spike)
- Dedicated `max_orphan_text_only` cap (not needed given default SL posture)
- Auto-close watchdog on orphan text-only (not needed given default SL posture)
- `trade_stages` analytics view (Phase 7 if analytics join proves painful)
- Bulk settings apply / copy-from-account (v1.2 polish)
