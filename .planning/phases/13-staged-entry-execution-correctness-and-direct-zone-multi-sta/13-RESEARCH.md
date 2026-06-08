# Phase 13: Staged-entry execution correctness and direct-zone multi-stage - Research

**Researched:** 2026-06-08
**Domain:** Live-money trade-execution engine (async Python; `trade_manager.py`, `executor.py`, `signal_parser.py`, `db.py`) — Phase 6 lineage
**Confidence:** HIGH (all claims verified against live source in this session)

## Summary

This is a backend-only correctness phase. Every design decision is already locked in `13-CONTEXT.md` (D2-01..D2-14) carrying forward Phase 6 (D-01..D-39) unchanged. The job of this research was to **verify those locked decisions against the live code** and pin exact, current change sites. All six gaps were reproduced in the source.

The single most important finding is that **the existing zone-watch machinery is richer than CONTEXT.md assumed**, in two ways that change the EXEC2-01 plan: (1) `signals` already persists `sl` and `tp` columns and `db.get_signal_targets(signal_id)` already returns `{direction, sl, tp}`; but (2) staged rows are keyed to the **text-only orphan's** `signal_id` (`paired_signal_id`), whose `signals` row has `sl=0, tp=0` — the real SL/TP arrives only on the *follow-up* signal and is never written back to the orphan row. This means the existing price-based cascade in `_zone_watch_loop` (executor.py:585-639) is a **silent no-op for correlated sequences** and `_fire_zone_stage` cannot recover real SL/TP from the parent signal. The locked discretion call (persist `sl`/`target_tp` on the `staged_entries` row at creation, additive-only DDL) is therefore the correct mechanism — and it simultaneously repairs the dormant price-cascade. This is a discovered scope detail the planner must account for.

**Primary recommendation:** Add two additive columns `signal_sl DOUBLE PRECISION` and `signal_tp DOUBLE PRECISION` to `staged_entries` (via `CREATE TABLE IF NOT EXISTS` evolution — see Pitfall 1 on the IF-NOT-EXISTS limitation), write them at every `create_staged_entries` call site, read them in `_fire_zone_stage` (and feed the price-cascade), and rewrite `_handle_open` to mirror `_handle_correlated_followup`. The EXEC2-02 fix is a one-site change in `_execute_open_on_account` to divide percent risk by `max_stages`. EXEC2-03 then needs **no separate code** — `target_lot` is already written from `stage_lot_size()` and read straight through to the panel.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Direct zone+SL+TP → multi-stage entry (EXEC2-06) | `trade_manager._handle_open` (dispatch/orchestration) | `db.create_staged_entries` (persistence) | Band geometry + at-arrival fire is signal-handling logic, mirrors `_handle_correlated_followup` |
| Late-stage SL/TP carry (EXEC2-01) | `db` schema + `executor._fire_zone_stage` (read) | `trade_manager` create sites (write) | SL/TP must survive in-memory signal loss → must be persisted, then read by the watchdog loop |
| Percent risk split (EXEC2-02) | `trade_manager._execute_open_on_account` (sizing) | `trade_manager.stage_lot_size` (already correct for display) | The actual order-volume calc lives in the percent branch; only this branch over-sizes |
| `/staged` target_lot display (EXEC2-03) | `db.staged_entries.target_lot` (write-at-creation) | `api/stages.py` + `dashboard._enrich_stage_for_ui` (read-through) | Display reads a persisted column; fixing the write fixes the read for free |
| SL-less standalone skip (EXEC2-04) | `trade_manager.handle_signal`/`_handle_open` (early-detect) | existing skip-result stream | `signal.sl is None` is a routing decision, not a sizing one — belongs before `calculate_sl_distance` |
| Orphan protective-TP attach (EXEC2-05/D2-12) | `executor._zone_watch_loop` (watchdog) | `connector.modify_position` (TP set) | Window-expiry detection is a polling concern; the existing 10s loop is the only watchdog |

## Standard Stack

No new dependencies. This phase is pure in-repo Python. Confirmed by reading imports across `trade_manager.py`, `executor.py`, `db.py` — all use the existing stack:

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | (in-repo pool, `db._pool`) | Postgres access | Already the only DB layer; all helpers use it |
| pytest + pytest-asyncio | (installed; `loop_scope="session"`) | Async test harness | Existing staged-entry battery uses it (`tests/conftest.py`) |
| stdlib `asyncio` | — | `_zone_watch_loop` task | Existing peer to `_heartbeat_loop`/`_cleanup_loop` |

**Installation:** None. `[VERIFIED: codebase grep — no new imports needed]`

## Package Legitimacy Audit

Not applicable — this phase installs **no external packages**. All work is in-repo edits to existing modules. No registry verification required.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EXEC2-01 | Late zone-watch stages carry signal's real SL/TP, not `default_sl_pips`+`TP=0` | `_fire_zone_stage` (executor.py:799-820) hardcodes SL from `default_sl_pips`, `target_tp=None`. `signals.sl/tp` exist but orphan row carries zeros. **Fix: persist signal_sl/signal_tp on staged_entries at creation; read in `_fire_zone_stage`.** Repairs dormant price-cascade (executor.py:597) too. |
| EXEC2-02 | `percent` mode splits `risk_value` across `max_stages` | Bug confirmed at trade_manager.py:701-709 — percent branch calls `calculate_lot_size(risk_percent=risk_pct=full risk_value)`; no `/max_stages`. `fixed_lot` branch (693-695) already splits via `stage_lot_size`. **Fix: divide percent risk by `snapshot.max_stages` in the percent branch.** |
| EXEC2-03 | `/staged target_lot` equals actual submitted volume | `target_lot` is written from `stage_lot_size(snapshot)` at row creation (already correctly split) and read straight through `get_pending_stages`→`_enrich_stage_for_ui`→`api/stages.py`. **No separate UI code needed once EXEC2-02 lands — they converge.** |
| EXEC2-04 | SL-less standalone OPEN → clean skip, no `EXECUTION ERROR` | `signal_parser` yields `sl=None` for OPEN with no `SL:` line (signal_parser.py:268); validation at 277 only runs `if sl is not None`. Crashes at `calculate_sl_distance(entry, None)` (trade_manager.py:687 → `abs(entry - None)` TypeError). **Fix: detect `signal.sl is None` before sizing; route to skip-result.** |
| EXEC2-05 | Orphan text-only gets protective TP at window expiry | `_handle_text_only_open` opens stage 1 with default SL, `target_tp=None`. No watchdog attaches a TP. **Fix: in `_zone_watch_loop`, on window-expiry-without-followup, set protective TP = entry ± (sl_distance × 1) via `modify_position` (reuse stage-1-align pattern, trade_manager.py:418-421).** |
| EXEC2-06 | Standalone zone+SL+TP → multi-stage scale-in, not single `zone_mid` fill | `_handle_open` (trade_manager.py:548-577) does a single `_execute_open_on_account` per account. **Fix: rewrite to mirror `_handle_correlated_followup` band-compute→create_staged_entries→at-arrival-fire→arm pattern. `compute_bands` returns `[]` at max_stages<2 — D2-04 needs a whole-zone single band.** |

## Architecture Patterns

### System Architecture Diagram

```
Telegram/Discord signal
        │
        ▼
  signal_parser.parse_signal()
   ├─ OPEN_TEXT_ONLY (sl=None, no zone)
   ├─ OPEN          (zone, sl|None, tps)   ◄── EXEC2-04: sl=None must skip here
   └─ CLOSE / MODIFY ...
        │
        ▼
  TradeManager.handle_signal()  (trade_manager.py:229)
   ├─ OPEN_TEXT_ONLY ─────────► _handle_text_only_open  (stage 1 @market, default SL)
   │                                  │ registers orphan w/ correlator
   │                                  ▼ orphan window
   ├─ OPEN + correlated ──────► _handle_correlated_followup  (TEMPLATE for EXEC2-06)
   │                                  │ compute_bands → create_staged_entries
   │                                  │ stage-1 align (modify SL/TP)
   │                                  ▼ fire in-zone-at-arrival, arm rest
   └─ OPEN standalone ────────► _handle_open  ◄── EXEC2-06 REWRITE TARGET
                                      (today: single zone_mid fill)
        │
        ▼ (all staged fills funnel through)
  _execute_open_on_account()  (trade_manager.py:579)
   ├─ daily-limit (D-18) │ max_open (D-19) │ dup-guard+bypass (D-23)
   ├─ stale check │ D-08 sl<=0 reject │ D-25 idempotency probe
   └─ percent-lot calc  ◄── EXEC2-02 BUG SITE (no /max_stages)
        │
        ▼ armed rows (status='awaiting_zone')  in staged_entries
        │
        ▼  (background, every 10s)
  executor._zone_watch_loop()  (executor.py:521)
   ├─ price-based cascade (get_signal_targets) ◄── DORMANT for correlated (orphan sl=0)
   ├─ D-16 stage-1-exit cascade │ D-14 pre-flight │ D-25 idempotency
   ├─ fire entered bands → _fire_zone_stage()  ◄── EXEC2-01 BUG SITE (default_sl_pips, tp=None)
   └─ EXEC2-05/D2-12: orphan window-expiry → modify_position(tp=protective)  ◄── NEW
        │
        ▼
  MT5 REST connector (modify_position / open_order)  — UNTOUCHED
```

### Pattern 1: Mirror `_handle_correlated_followup` for EXEC2-06
**What:** The direct-zone `_handle_open` rewrite copies the band lifecycle from `_handle_correlated_followup` (trade_manager.py:362-544).
**Exact pattern to mirror (per account, after snapshot):**
```python
# Source: trade_manager.py:474-542 (live, verified 2026-06-08)
max_stages = snapshot.max_stages if snapshot else 1
bands = compute_bands(zone_low, zone_high, max_stages, direction.value)
if not bands:
    # D2-04: at max_stages=1 compute_bands returns [] — must NOT fall back to
    # zone_mid single fill. Treat whole zone as ONE band instead.
    ...
rows = [ {..., "band_low": b.low, "band_high": b.high,
          "target_lot": stage_lot_size(snapshot), ...} for b in bands ]
stage_ids = await db.create_staged_entries(rows)
bid, ask = await connector.get_price(symbol)
for band, stage_id in zip(bands, stage_ids):
    if not stage_is_in_zone_at_arrival(band, bid, ask, direction.value):
        continue  # armed — _zone_watch_loop fires later
    synth = SignalAction(type=OPEN, entry_zone=(band.low, band.high),
                         sl=signal.sl, tps=..., target_tp=signal.target_tp)
    await self._execute_open_on_account(synth, signal_id, acct, connector,
        staged=True, stage_number=band.stage_number, stage_row_id=stage_id, snapshot=snapshot)
```
**Key differences from the correlated path (per D2-01/D2-02):**
- **No stage-1 market anchor.** The correlated path's stage 1 is the prior text-only market fill; the direct-zone path has none. D2-02: fire *only* bands already crossed at arrival; if price is entirely outside the zone, **nothing fires** — all bands wait.
- **`signal_id` is the OPEN's own `log_signal` id** (no `paired_signal_id`). This means the EXEC2-01 SL/TP persistence is actually *easier* here — the OPEN's `signals` row already has real sl/tp (trade_manager.py:561-562 logs `sl=signal.sl, tp=signal.target_tp`), so `get_signal_targets(signal_id)` would work for direct-zone even without new columns. But the **correlated path still needs the new columns** (orphan row has zeros), so persist for both uniformly.

### Pattern 2: D2-04 whole-zone single band at max_stages=1
**What:** `compute_bands` returns `[]` when `max_stages < 2` (verified trade_manager.py:75). D2-04 forbids the v1.0 `zone_mid` fallback.
**Recommended (planner's discretion per CONTEXT):** special-case in the dispatcher — synthesize one `Band(stage_number=1, low=zone_low, high=zone_high)` and run it through the same at-arrival/arm logic. Do **not** modify `compute_bands`'s `max_stages<2 → []` contract (it's relied on by `_handle_correlated_followup:479` which treats `[]` as "no_bands" for the *follow-up* case where stage 1 already fired). A direct-zone single band is a different semantic.

### Pattern 3: EXEC2-05 orphan protective-TP via existing 10s loop
**What:** D2-12 — at correlation-window expiry without a follow-up, set TP = entry ± (sl_distance × R), R=1.
**Reusable mechanism:** `connector.modify_position(ticket, sl=..., tp=...)` (mt5_connector.py:137 ABC; DryRun + REST impls exist). The stage-1 align block (trade_manager.py:418-421) is the exact reuse template — it already calls `modify_position` failure-isolated. The orphan's `sl_distance` = `default_sl_pips × pip_size` (the same value used at `_handle_text_only_open:309-311`).
**Detection site:** `_zone_watch_loop` already iterates all active stages and already fetches `get_signal_targets`. Add an orphan-expiry check: a stage-1 row whose signal is older than `correlation_window_seconds` AND has no paired follow-up AND `mt5_ticket` is live → attach protective TP. (See Open Question 1 on how to detect "no follow-up arrived".)

### Anti-Patterns to Avoid
- **Resting-limit orders for EXEC2-06** (explicitly rejected by D2-01): would create a new cancel/reconcile surface outside `_zone_watch_loop`'s kill-switch/reconnect safety. Use armed `staged_entries` rows only.
- **Modifying `compute_bands`'s `max_stages<2 → []` return** — relied upon by the correlated path's `no_bands` branch.
- **Recomputing `target_lot` for display** (EXEC2-03) — it is a persisted column; fix the write, not the read.
- **Chasing a moved market** (D2-14) — never fire all "crossed" bands at market when price has run past the zone. `_check_stale` (trade_manager.py:670, 873) runs first and rejects.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Late-stage SL/TP recovery | A parent-signal re-parse / in-memory cache of live signals | Persist `signal_sl`/`signal_tp` on `staged_entries` row (additive DDL) | In-memory signal is gone by the time the watchdog fires hours later; DB row survives restart/reconnect |
| Orphan window watchdog | A new asyncio task / timer | Existing `_zone_watch_loop` 10s cadence | D2-12 explicit: no new task; loop already polls all stages + checks `_trading_paused` |
| Per-stage risk split | New sizing function | Existing `stage_lot_size()` (already correct) | The function already divides by `max_stages`; the bug is the percent branch *not calling it* |
| Kill-switch / reconnect for direct-zone | New reconcile path | Route EXEC2-06 through `staged_entries` + `_zone_watch_loop` | Inherits D-21 drain, D-24 reconcile, D-25 idempotency automatically |
| Protective-TP order round-trip | Raw MT5 call | `connector.modify_position(ticket, tp=...)` | Already abstracted; stage-1-align uses it failure-isolated |

**Key insight:** Almost every EXEC2 fix is a **re-wiring of existing, tested machinery**, not new subsystems. The dangerous temptation is to add a parallel path (resting limits, a new watchdog task) — CONTEXT.md explicitly rejects each.

## Runtime State Inventory

This phase is **not** a rename/refactor, but it **does** add persisted columns and change how live-money orders are sized/managed. The state audit:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data (schema) | `staged_entries` table (db.py:217). EXEC2-01 likely adds `signal_sl`, `signal_tp` columns. Existing rows have no such columns. | Additive DDL — but see Pitfall 1: `CREATE TABLE IF NOT EXISTS` will **not** add columns to an already-created table. A guarded `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` is required (Postgres supports it). This is the one place "additive-only" needs an explicit ADD COLUMN, not a CREATE. |
| Live service config | None — no external service config carries Phase 13 state. | None. |
| OS-registered state | None — no OS scheduler/process names involved. | None — verified: bot runs as a single process, no per-feature registrations. |
| Secrets/env vars | None new. No new config knobs (D2-11 R=1 hardcoded; no `zone_orphan_tp_ratio`). | None. |
| Build artifacts | None — pure source edits, no package rename. | None. |

**In-flight rows at deploy:** Per `project_deploy_at_end_workflow.md`, v1.2 deploys to VPS once at the end; local is the working env. But for **forward safety**: any `awaiting_zone` rows created *before* the new `signal_sl`/`signal_tp` columns exist will have NULLs. `_fire_zone_stage` must handle NULL gracefully (fall back to old `default_sl_pips` behavior, or skip). Flag for planner: backfill is not required if deploy is clean-cut, but the read path must be NULL-safe.

## Common Pitfalls

### Pitfall 1: `CREATE TABLE IF NOT EXISTS` does NOT add columns to an existing table
**What goes wrong:** The Phase 5/6 "additive-only DDL" discipline used `CREATE TABLE IF NOT EXISTS` because those tables were *new*. For EXEC2-01 you are adding columns to an **existing** `staged_entries` table — `CREATE TABLE IF NOT EXISTS` silently no-ops and the columns never appear.
**Why it happens:** Misreading "additive-only" as "always CREATE IF NOT EXISTS." The actual discipline is "no destructive ALTER" — adding a column is additive and safe.
**How to avoid:** Use `ALTER TABLE staged_entries ADD COLUMN IF NOT EXISTS signal_sl DOUBLE PRECISION;` (Postgres supports `ADD COLUMN IF NOT EXISTS`). Place it in `init_schema()` after the `CREATE TABLE`. Verify with `test_db_schema.py` (existing).
**Warning signs:** Insert fails with "column does not exist," or `get_active_stages` returns rows without the new fields.

### Pitfall 2: The price-based cascade is silently dead for correlated sequences
**What goes wrong:** `_zone_watch_loop` calls `get_signal_targets(signal_id)` (executor.py:597) which reads `signals.sl/tp`. For correlated sequences the `signal_id` is the **orphan** (sl=0, tp=0), so `sig_sl>0`/`sig_tp>0` are both false and the cascade never fires. EXEC2-01's column-persistence fix should ALSO feed this cascade, or it stays dead.
**Why it happens:** The orphan signal row never gets the follow-up's SL/TP written back (no `UPDATE signals SET sl/tp` helper exists — verified by grep).
**How to avoid:** After adding `signal_sl`/`signal_tp` to `staged_entries`, change the cascade to read from the stage row (or from the new columns) rather than `get_signal_targets`. Confirm with a test: correlated sequence + price reaching follow-up TP → unfilled stages cancelled.
**Warning signs:** Deep stages keep firing after price already hit the signal's TP.

### Pitfall 3: Percent-mode lot path ignores `stage_lot_size`
**What goes wrong:** `target_lot` written to the row uses `stage_lot_size(snapshot)` (split correctly), but the **submitted** volume in percent mode comes from `calculate_lot_size(risk_percent=risk_pct, ...)` where `risk_pct` is the full `risk_value` (trade_manager.py:701-709). Display and reality diverge (EXEC2-03), and exposure is N× (EXEC2-02).
**How to avoid:** In the percent branch, pass `risk_percent = risk_pct / snapshot.max_stages` (guard `max_stages>0`). Confirm the submitted `lot_size` matches the persisted `target_lot` in a test.
**Warning signs:** `/staged target_lot` ≠ actual MT5 volume; total deployed risk = `risk_value × stages_filled`.

### Pitfall 4: SL-less OPEN crashes before the D-08 guard
**What goes wrong:** D-08's `sl<=0` reject lives at trade_manager.py:727 — but `calculate_sl_distance(entry, None)` at :687 crashes *first* with a TypeError (`abs(entry - None)`). The guard is a backstop, not the primary defense.
**How to avoid:** Detect `signal.sl is None` at the top of `_handle_open` (and the EXEC2-06 dispatch) and return a skip-result before any sizing. Keep the D-08 `sl<=0` guard as the second backstop (D2-13).
**Warning signs:** `EXECUTION ERROR` alert with a TypeError stack instead of a clean "Skipped: no SL" line.

### Pitfall 5: D2-04 single-band collides with the correlated "no_bands" branch
**What goes wrong:** `_handle_correlated_followup` treats `compute_bands()==[]` as `{"status":"no_bands","reason":"max_stages=1"}` (trade_manager.py:479-481) — because for a *follow-up*, stage 1 already fired so max_stages=1 legitimately means "nothing left to stage." The direct-zone path must NOT inherit that branch; at max_stages=1 it must fire **one whole-zone band**.
**How to avoid:** Handle the `[]` case in the new `_handle_open` path explicitly with a synthesized whole-zone `Band` — do not call into or reuse the follow-up's no_bands return.

### Pitfall 6: Zone-watch fires deep-band stages without the protective context
**What goes wrong (D2-03 nuance):** D-16 ("sequence lifetime = stage-1 lifetime") assumed a guaranteed stage-1 anchor. For direct-zone, stage 1 may never fire (price never reaches the top band). The `_zone_watch_loop` D-16 cascade (executor.py:663-701) keys on `telebot-{signal_id}-s1` being live. If s1 never fills, the cascade logic treats "stage 1 still awaiting → fire OK" (line 696-698) — which is correct, but means **no anchor cancels the sequence until the first fill**. D2-03 locks: first fill anchors; before any fill, the stale/max-age window governs.
**How to avoid:** Verify the existing `stage1_live_cache` logic (executor.py:664-701) behaves correctly when stage 1 is a direct-zone band that may never fill. Add a test for "direct-zone, no fill, window expires → sequence invalidated by stale, not left armed forever."

## Code Examples

### EXEC2-02 fix site (percent-mode split)
```python
# Source: trade_manager.py:696-709 (live, verified 2026-06-08)
# BEFORE (bug): full risk_value applied per stage
else:
    acct_info = await connector.get_account_info()
    ...
    risk_pct, max_lot, _ = _effective(self, acct)
    lot_size = calculate_lot_size(
        account_balance=acct_info.balance,
        risk_percent=risk_pct,          # ◄── full risk_value, no /max_stages
        sl_distance=sl_distance, max_lot_size=max_lot, ...)

# AFTER (D2-06): split when this is a staged sequence
    risk_pct, max_lot, _ = _effective(self, acct)
    stages = (snapshot.max_stages if snapshot and snapshot.max_stages > 0 else 1)
    per_stage_risk = risk_pct / stages if staged else risk_pct
    lot_size = calculate_lot_size(risk_percent=per_stage_risk, ...)
```
Note: gate on `staged` so the v1.0 single-signal `_handle_open` (non-staged) path is unaffected — but after EXEC2-06, standalone OPEN becomes staged too, so it naturally splits.

### EXEC2-01 read site (`_fire_zone_stage`)
```python
# Source: executor.py:799-820 (live, verified 2026-06-08)
# BEFORE: rebuilds SL from default_sl_pips, target_tp=None
default_sl_pips = getattr(snapshot, "default_sl_pips", 100) if snapshot else 100
if direction_str == "buy":
    sl_price = entry_price - default_sl_pips * pip_size
...
synth = SignalAction(..., sl=sl_price, tps=[], target_tp=None)  # ◄── loses signal SL/TP

# AFTER (D2-05): read persisted signal_sl/signal_tp off the stage row
signal_sl = stage.get("signal_sl")
signal_tp = stage.get("signal_tp")
if signal_sl is None:        # NULL-safe fallback for pre-migration rows
    signal_sl = sl_price     # old default-SL behavior
synth = SignalAction(..., sl=signal_sl, tps=[], target_tp=signal_tp)
```

### EXEC2-04 early skip
```python
# Source: trade_manager.py:548 _handle_open (live)
async def _handle_open(self, signal, source_name=""):
    if signal.sl is None:                       # D2-13 — detect BEFORE sizing
        await db.log_signal(raw_text=signal.raw_text, signal_type="open",
            action_taken="skipped", symbol=signal.symbol,
            direction=signal.direction.value if signal.direction else "",
            source_name=source_name)
        return [{"account": "*", "status": "skipped",
                 "reason": "Skipped: signal has no SL (D-08 requires a stop)"}]
    ...  # existing path; D-08 sl<=0 guard at :727 remains the backstop
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `_handle_open` single `zone_mid` fill | Multi-stage scale-in via `compute_bands` | This phase (EXEC2-06) | Standalone OPEN now behaves like correlated follow-up |
| Late stages rebuilt SL from `default_sl_pips` | Persisted signal SL/TP carried to every stage | This phase (EXEC2-01) | Consistent signal-derived SL/TP across a sequence |
| `percent` mode = full risk per stage | `percent` mode = `risk_value/max_stages` | This phase (EXEC2-02) | Matches `fixed_lot`; risk_value is a ceiling |
| Orphan left on default SL, no TP (D-09) | Protective TP attached at window expiry (D2-09..D2-12) | This phase (EXEC2-05) | No unmanaged orphans; supersedes Phase 6 D-09 |

**Deprecated/outdated:**
- Phase 6 **D-09** ("no action on orphan") — superseded by D2-09 (attach protective exit).
- Phase 6 **D-16** anchor assumption — revised by D2-03 (first fill anchors, not guaranteed stage 1).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The cleanest EXEC2-01 mechanism is new `staged_entries` columns vs parent-signal lookup | Don't Hand-Roll / Pattern | Low — CONTEXT.md D2-05 explicitly leaves mechanism to planner and names columns as "likely-cleanest"; verified parent-lookup fails for correlated path |
| A2 | `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` is the correct DDL (not CREATE IF NOT EXISTS) | Pitfall 1 | Medium — if the project has a different migration convention I didn't see; mitigated by reading db.py:215-249 (only CREATE patterns exist, so ADD COLUMN is the additive choice) |
| A3 | "No follow-up arrived" for orphan detection can be derived from correlator state + age | Open Question 1 | Medium — exact detection signal is a planner design call |
| A4 | The percent-split should gate on `staged` so v1.0 non-staged path is unaffected | Code Examples | Low — once EXEC2-06 makes standalone OPEN staged, all OPEN paths split; the gate is belt-and-suspenders |

## Open Questions

1. **How does `_zone_watch_loop` detect "orphan window expired without follow-up" (EXEC2-05/D2-12)?**
   - What we know: orphan registered via `correlator.register_orphan` (trade_manager.py:280); window = `GlobalConfig.correlation_window_seconds` (default 600). The stage-1 row has `created_at`. A follow-up, if it arrived, would have created sibling stage rows (stage_number ≥ 2) for the same `signal_id`.
   - What's unclear: the cleanest "no follow-up" signal — absence of sibling rows for `signal_id`, OR correlator marking the orphan consumed. The correlator is one-to-one (D-06) and may already expose "is this orphan still pending."
   - Recommendation: in the loop, for each stage-1 row older than `correlation_window_seconds` with `mt5_ticket` live and `target_tp` not yet set and **no sibling stages**, attach the protective TP once (idempotent — check current TP first). Read `signal_correlator.py` during planning to confirm the cleanest "consumed?" query.

2. **Does the protective-TP attach need to persist that it ran (to stay idempotent across reconnect)?**
   - What we know: `modify_position` is not idempotency-guarded the way `open_order` is (no comment scheme for modifies).
   - Recommendation: either check the live position's current TP before setting (skip if already non-zero), or record a flag on the stage row. The "check current TP" approach needs no schema change — prefer it.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL (test) | pytest staged-entry battery | ✓ (per conftest, `localhost:5433`) | dev container | `pytest.skip` when absent (conftest.py:39-43) |
| Python 3.12 container | Running the async test suite | ✓ (per `project_local_dashboard_verification.md`) | 3.12 | — |
| MT5 REST bridge | Live `modify_position`/`open_order` round-trips | N/A for tests (DryRunConnector) | — | DryRunConnector simulates full lifecycle |

**Missing dependencies with no fallback:** None — all execution paths have a `DryRunConnector` test double.
**Note:** Per memory `project_local_dashboard_verification.md`, verify locally WITHOUT full `bot.py` (Telegram session conflict). The staged-entry tests run standalone against the dev Postgres; no live MT5 needed.

## Validation Architecture

> nyquist_validation is enabled (`.planning/config.json: nyquist_validation: true`). This phase modifies live-money execution paths — the full safety-regression battery MUST stay green.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (`loop_scope="session"`) |
| Config file | none — pytest defaults; `tests/conftest.py` holds fixtures |
| Quick run command | `pytest tests/test_staged_executor.py tests/test_staged_safety_hooks.py -x` |
| Full suite command | `pytest tests/ -q` (requires dev Postgres at `localhost:5433`, Python 3.12 container) |

### Existing safety-regression battery (NO-REGRESSION criteria — must stay green)
These already exist in `tests/test_staged_safety_hooks.py` / `test_staged_executor.py` / `test_staged_db.py` / `test_staged_attribution.py` and cover the carried-forward Phase 6 invariants:

| Behavior | Decision | Existing test |
|----------|----------|---------------|
| Kill-switch drain BEFORE close | D-21/D-22 | `test_emergency_close_drains_staged_before_positions`, `test_resume_trading_does_not_uncancel_drained_stages` |
| Reconnect reconcile by comment | D-24 | `test_reconnect_marks_filled_when_comment_exists_on_mt5`, `test_reconnect_marks_abandoned_when_signal_aged_and_no_mt5_position`, `test_reconnect_leaves_young_unfilled_stages_alone` |
| Daily-slot accounting (1 signal = 1 slot) | D-18 | `test_one_signal_id_one_daily_slot`, `test_mark_signal_counted_today_idempotent` |
| Duplicate-direction guard + sibling bypass | D-23 | `test_dup_guard_bypass_same_signal_id_different_stage`, `test_dup_guard_still_rejects_unrelated_same_direction` |
| D-08 sl<=0 hard reject | D-08 | `test_default_sl_zero_hard_rejects_text_only` |
| Comment-based idempotency | D-25 | `test_zone_watch_idempotency_probe_marks_filled_without_submit`, `test_reconcile_after_reconnect_matches_by_comment` |
| Stale re-check / stage-1 cascade | D-14/D-16 | `test_zone_watch_cancels_remaining_stages_when_stage1_closed`, `test_zone_watch_does_not_cascade_when_stage1_still_awaiting` |
| Price-target cascade | (cascade) | `test_zone_watch_cancels_pending_stages_when_price_reaches_tp/sl`, `test_zone_watch_does_not_cancel_when_price_between_sl_and_tp` |
| max_open_trades per-stage cap | D-19 | `test_stage_marked_capped_when_max_open_trades_reached` |
| Failure isolation | D-17 | `test_stage_marked_failed_on_broker_reject_others_continue` |

### Phase 13 Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EXEC2-01 | Late zone-watch stage carries signal SL/TP (not default+0) | integration | `pytest tests/test_staged_executor.py -k late_stage_carries_signal_sl_tp` | ❌ Wave 0 |
| EXEC2-01 | Correlated price-cascade fires using persisted SL/TP | integration | `pytest tests/test_staged_safety_hooks.py -k correlated_cascade_uses_persisted_tp` | ❌ Wave 0 |
| EXEC2-02 | percent submitted volume == risk_value/max_stages | unit+integration | `pytest tests/test_staged_executor.py -k percent_splits_risk` | ❌ Wave 0 |
| EXEC2-03 | `/staged target_lot` == submitted volume | contract | `pytest tests/test_stages_contract.py -k target_lot_matches_volume` | ❌ Wave 0 (extend existing `test_stages_contract.py`) |
| EXEC2-04 | SL-less OPEN → clean skip, no exception | integration | `pytest tests/test_trade_manager.py -k sl_less_open_skips_cleanly` | ❌ Wave 0 |
| EXEC2-04 | D-08 sl<=0 backstop still holds | regression | (existing `test_default_sl_zero_hard_rejects_text_only`) | ✅ |
| EXEC2-05 | Orphan gets protective TP at window expiry (R=1) | integration | `pytest tests/test_staged_safety_hooks.py -k orphan_protective_tp_at_expiry` | ❌ Wave 0 |
| EXEC2-05 | Orphan does NOT get TP before window expiry (don't pre-empt follow-up) | integration | `pytest tests/test_staged_safety_hooks.py -k orphan_no_tp_during_window` | ❌ Wave 0 |
| EXEC2-06 | Standalone zone+SL+TP → N stages (max_stages=N) | integration | `pytest tests/test_staged_executor.py -k direct_zone_multistage` | ❌ Wave 0 |
| EXEC2-06 | max_stages=1 → exactly one whole-zone entry (no zone_mid) | integration | `pytest tests/test_staged_executor.py -k direct_zone_single_band` | ❌ Wave 0 |
| EXEC2-06 | Price entirely outside zone → nothing fires at arrival (D2-02) | integration | `pytest tests/test_staged_executor.py -k direct_zone_arms_when_outside` | ❌ Wave 0 |
| EXEC2-06 | Past-zone arrival rejected as stale (D2-14) | integration | `pytest tests/test_trade_manager.py -k direct_zone_past_market_stale` | ❌ Wave 0 |
| EXEC2-06 | Direct-zone inherits kill-switch drain + reconnect (D2-01) | regression | (re-run existing D-21/D-24 tests with direct-zone signal_id) | ✅ extend |

### Sampling Rate
- **Per task commit:** `pytest tests/test_staged_executor.py tests/test_staged_safety_hooks.py -x` (the fast core)
- **Per wave merge:** `pytest tests/ -q` (full suite, dev Postgres up)
- **Phase gate:** Full suite green before `/gsd:verify-work`; manual live-money smoke per `project_deploy_at_end_workflow.md` (deploy-at-end).

### Wave 0 Gaps
- [ ] `tests/test_staged_executor.py` — add direct-zone multi-stage cases (EXEC2-06), percent-split (EXEC2-02), late-stage SL/TP carry (EXEC2-01). Reuse `tm_with_store` + `_PricedDry` fixtures (lines 101-135).
- [ ] `tests/test_staged_safety_hooks.py` — add orphan protective-TP cases (EXEC2-05), correlated-cascade-uses-persisted-TP (EXEC2-01). Reuse `executor_fixture` + reconnect helpers.
- [ ] `tests/test_trade_manager.py` — add SL-less skip (EXEC2-04) and past-zone stale (D2-14). Reuse `make_signal` factory (conftest.py:255).
- [ ] `tests/test_stages_contract.py` — extend with `target_lot == submitted volume` assertion (EXEC2-03).
- [ ] `tests/test_db_schema.py` — assert new `signal_sl`/`signal_tp` columns exist on `staged_entries` (EXEC2-01 DDL).
- [ ] No framework install needed — pytest/pytest-asyncio + dev Postgres already present.

## Security Domain

> `security_enforcement` is absent in config → treated as enabled. This phase is a backend execution engine with no new auth/network surface, but financial-correctness controls apply.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth changes; `/staged` read route is session-gated via existing `require_user` (api/stages.py:22) |
| V3 Session Management | no | Unchanged; reuses existing session middleware |
| V4 Access Control | yes (read) | `/stages` route already `Depends(require_user)` — preserve |
| V5 Input Validation | yes | Signal parsing (`signal.sl is None`, zone bounds) — EXEC2-04 is precisely an input-validation hardening; `compute_bands` raises on inverted zone |
| V6 Cryptography | no | None — no crypto in this phase |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Over-exposure from N× risk (EXEC2-02) | Denial of (capital) | Cap risk at `risk_value` ceiling; `max_open_trades` per-stage gate (D-19) |
| Unmanaged orphan (EXEC2-05) | Tampering (uncontrolled loss) | Mandatory protective TP + default SL (D-08 invariant) |
| SL=0 submit (D-08) | Tampering | Hard-reject at trade_manager.py:727; EXEC2-04 routes SL-less to skip *before* this |
| SQL injection in `/staged` LIMIT | Injection | Already mitigated — `int(limit)` coercion (db.py:1077, T-06-02) |
| Stale/moved-market chase (D2-14) | Tampering | `_check_stale` runs first; pre-flight re-check (D-14) is second backstop |

## Sources

### Primary (HIGH confidence — read in this session)
- `trade_manager.py` (full, 1133 lines) — `handle_signal`, `_handle_open`, `_handle_correlated_followup`, `_handle_text_only_open`, `_execute_open_on_account`, `compute_bands`, `stage_lot_size`, `_effective`, `_check_stale`
- `executor.py:227-376, 521-869` — `_sync_positions`, `emergency_close`, `_zone_watch_loop`, `_fire_zone_stage`
- `db.py:213-249, 1008-1196` — `staged_entries` schema + all helpers, `get_signal_targets`
- `signal_parser.py:226-299` — text-only + `_build_open_signal` (sl=None path)
- `risk_calculator.py:26-90` — `calculate_lot_size`, `calculate_sl_distance`
- `models.py` — `SignalAction`, `AccountSettings`, `SignalType`
- `api/stages.py` (full) — `/staged` serializer, `target_lot` read-through
- `tests/conftest.py` (full) + `tests/test_staged_*.py` (test inventory) — validation harness
- `.planning/phases/13-.../13-CONTEXT.md`, `.planning/phases/06-.../06-CONTEXT.md` (full) — locked decisions
- `.planning/codebase/TESTING.md`, `.planning/ROADMAP.md:135-162`

### Secondary (MEDIUM confidence)
- Memory files: `project_lot_semantics.md`, `project_deploy_at_end_workflow.md`, `project_local_dashboard_verification.md`

### Tertiary (LOW confidence)
- None — all findings verified against live source.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; verified by import inspection
- Architecture: HIGH — all six bug sites read in live source; line anchors confirmed (with corrections noted)
- Pitfalls: HIGH — each pitfall traced to a specific verified code location
- Validation: HIGH — existing test battery enumerated from actual test files

**Line-anchor corrections vs CONTEXT.md (anchors had drifted):**
- EXEC2-01 `_fire_zone_stage` SL rebuild: CONTEXT said ~799-820 → **confirmed at executor.py:799-820** (accurate).
- EXEC2-02 percent bug: CONTEXT said 679-712 / `_effective:144` → **confirmed at trade_manager.py:696-709, `_effective` at 130-148 (risk_percent resolution at 144)**.
- EXEC2-04 crash: CONTEXT said :687 → **confirmed `calculate_sl_distance(entry_for_calc, signal.sl)` at trade_manager.py:687**; D-08 guard at **:724-730** (CONTEXT said :724-729).
- `_handle_open`: CONTEXT said 548-577 → **confirmed trade_manager.py:548-577**.
- `_handle_correlated_followup`: CONTEXT said 474-544 → **actual span 362-544** (the per-account band loop is 474-542; the method starts at 362).
- `_zone_watch_loop`: CONTEXT said 521-750 → **confirmed executor.py:521-750**.
- **New discovery not in CONTEXT:** existing dormant price-cascade at executor.py:585-639 using `get_signal_targets` — EXEC2-01 fix should revive it.

**Research date:** 2026-06-08
**Valid until:** 2026-07-08 (stable in-repo code; re-verify line anchors if `trade_manager.py`/`executor.py` are edited before planning)

## RESEARCH COMPLETE

**Phase:** 13 - Staged-entry execution correctness and direct-zone multi-stage
**Confidence:** HIGH

### Key Findings
- All six gaps reproduced in live source; exact change sites confirmed and line anchors corrected vs CONTEXT.md (`_handle_correlated_followup` actually starts at 362, not 474; price-cascade at 585-639 is a new discovery).
- **EXEC2-01 mechanism resolved with a discovered nuance:** `signals.sl/tp` exist and `get_signal_targets` exists, but correlated staged rows key to the *orphan* signal_id (sl=0/tp=0), so the existing price-cascade is a silent no-op and `_fire_zone_stage` can't recover real SL/TP from the parent. Persisting `signal_sl`/`signal_tp` on `staged_entries` (additive `ALTER TABLE ADD COLUMN IF NOT EXISTS`) is the correct fix and revives the dormant cascade.
- **EXEC2-02/03 converge:** `target_lot` is already written from `stage_lot_size()` (correctly split) and read straight to the panel; the bug is the percent branch submitting full-`risk_value` volume (trade_manager.py:701-709). One-site fix; EXEC2-03 needs no separate UI code.
- **EXEC2-06 template confirmed:** `_handle_correlated_followup` is the exact mirror; `compute_bands` returns `[]` at max_stages<2, so D2-04 needs a synthesized whole-zone single band (must NOT reuse the follow-up's `no_bands` branch).
- **Pitfall surfaced:** "additive-only DDL" via `CREATE TABLE IF NOT EXISTS` will NOT add columns to the existing `staged_entries` table — must use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

### File Created
`.planning/phases/13-staged-entry-execution-correctness-and-direct-zone-multi-sta/13-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Standard Stack | HIGH | No new deps; verified by import inspection |
| Architecture | HIGH | All six bug sites + safety hooks read in live source |
| Pitfalls | HIGH | Each traced to a specific verified line |
| Validation | HIGH | Existing safety battery enumerated from actual test files |

### Open Questions
1. Cleanest "orphan window expired without follow-up" detection signal for EXEC2-05 (correlator state vs absence of sibling rows vs age) — read `signal_correlator.py` during planning.
2. Whether protective-TP attach needs a persisted idempotency flag or can check the live position's current TP (prefer the latter — no schema change).

### Ready for Planning
Research complete. Planner can now create PLAN.md files. All locked decisions (D2-01..D2-14) verified consistent with live code; the only material additions to the plan beyond CONTEXT.md are the `ALTER TABLE ADD COLUMN IF NOT EXISTS` DDL nuance (Pitfall 1) and reviving the dormant price-cascade (Pitfall 2).
