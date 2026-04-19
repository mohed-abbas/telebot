---
phase: 06-staged-entry-execution
verified: 2026-04-20T12:00:00Z
status: human_needed
score: 6/6
overrides_applied: 0
human_verification:
  - test: "Text-only signal opens exactly 1 market position with SL != 0"
    expected: "Send 'Gold buy now' to bot; exactly one position opens per enabled account with a valid SL; staged_entries row created with status=filled; no duplicate on re-send within dup-guard window"
    why_human: "Requires live MT5 connection and real/demo broker session; cannot mock the full chain from Telegram dispatch to MT5 order fill"
  - test: "Correlated follow-up arms N-1 pending stages; stages fire as price enters bands"
    expected: "After text-only (stage 1 filled), send structured follow-up with entry_zone + SL + TP; N-1 rows appear in staged_entries as awaiting_zone; as price enters each band the zone-watch loop fires additional positions"
    why_human: "Requires live price feed and MT5 execution; zone entry timing is inherently real-time"
  - test: "Kill switch drains all pending stages before closing positions; resume never un-cancels"
    expected: "With pending stages present, toggle kill switch; staged_entries rows transition to cancelled BEFORE positions are closed; resume trading leaves cancelled rows as cancelled"
    why_human: "Drain ordering (D-21) and stage-cancel immutability (D-22) must be verified against actual DB state under concurrent execution"
  - test: "MT5 reconnect reconciles positions by idempotency comment"
    expected: "Simulate reconnect while stage is in-flight; _sync_positions matches position by comment 'telebot-{signal_id}-s{n}'; no duplicate trade log entry; abandoned stages become abandoned_reconnect after signal_max_age_minutes"
    why_human: "Requires MT5 connector disconnect/reconnect cycle; idempotency key matching depends on broker returning correct comment fields"
  - test: "Dashboard /staged shows live pending stages with price flash on update"
    expected: "Navigate to /staged; pending stages panel renders correctly; price cells flash indigo when SSE pushes updates; empty-state shown when no pending stages"
    why_human: "Visual rendering and CSS animation (ring-indigo-400/40, 150ms flash) require browser; SSE stream continuity requires running server"
  - test: "Settings form validates hard caps and applies only to future signals"
    expected: "Set max_stages=11 → rejected; set risk_value=5.1 → rejected; valid change shows confirmation modal with 'This applies to signals received AFTER you confirm'; confirm applies; signals already in flight use previous settings"
    why_human: "Form validation UX and modal interaction require browser; 'future signals only' semantic requires verifying snapshot_settings captured at signal-dispatch time, not at confirm time"
---

# Phase 6: Staged-Entry Execution Verification Report

**Phase Goal:** A text-only 'Gold buy now' signal opens exactly one protected position immediately, and a correlated follow-up signal with zone/SL/TP opens additional positions as price enters the zone — without regressing any v1.0 safety primitive (kill switch, reconnect sync, daily limits, stale re-check, duplicate guard).
**Verified:** 2026-04-20T12:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                             | Status     | Evidence                                                                                      |
|----|---------------------------------------------------------------------------------------------------|------------|-----------------------------------------------------------------------------------------------|
| 1  | Text-only signal opens exactly 1 market position per enabled account, no sl=0                    | ✓ VERIFIED | `_handle_text_only_open` (TM:257), D-08 guard (TM:639), D-18 bypass stage_number>1 (TM:526), `OPEN_TEXT_ONLY` dispatch (signal_parser.py:236) |
| 2  | Correlated follow-up opens up to max_stages-1 additional positions respecting limits             | ✓ VERIFIED | `_handle_correlated_followup` (TM:361), `compute_bands` (TM:52), `SignalCorrelator.pair_followup` (signal_correlator.py:61), D-23 dup-guard bypass (TM:566-571) |
| 3  | Kill switch drains all pending stages before closing positions; resume never un-cancels          | ✓ VERIFIED | `drain_staged_entries_for_kill_switch()` called at executor.py:307 BEFORE position-close loop at :326; `resume_trading` (executor.py:358) does not un-cancel drained rows (D-22) |
| 4  | MT5 reconnect reconciles by comment-based idempotency key                                        | ✓ VERIFIED | `_sync_positions` (executor.py:216) extended with D-24/D-25 comment matching; `db.get_stage_by_comment` (db.py:877); `abandoned_reconnect` status for age-expired in-flight stages |
| 5  | Dashboard live pending-stages panel + trade attribution to originating signal                    | ✓ VERIFIED | `/staged` (dashboard.py:446), `/partials/pending_stages` (dashboard.py:464), SSE `pending_stages` event (dashboard.py:1021), `_enrich_stage_for_ui` (dashboard.py:357), `db.log_trade(signal_id=signal_id, ...)` (TM:728) |
| 6  | Per-account settings form with hard caps, confirmation, apply to future signals only             | ✓ VERIFIED | `validate_settings_form` hard caps (dashboard.py:520): max_stages(1,10), default_sl_pips(1,500), max_daily_trades(1,100), risk_value≤5.0; confirm modal text "This applies to signals received AFTER you confirm" (settings_confirm_modal.html:37); `store.update()` (dashboard.py:715) |

**Score:** 6/6 truths verified at code layer

### Deferred Items

None. All Phase 6 success criteria are fully addressed in this phase. Step 9b produced no later-phase coverage matches.

### Required Artifacts

| Artifact                                            | Expected                                       | Status     | Details                                                                          |
|-----------------------------------------------------|------------------------------------------------|------------|----------------------------------------------------------------------------------|
| `signal_correlator.py`                              | asyncio-safe orphan↔follow-up pairing          | ✓ VERIFIED | `asyncio.Lock`, `register_orphan`, `pair_followup`, lazy `_evict_expired` (line 27+) |
| `models.py` — `SignalType.OPEN_TEXT_ONLY`           | New signal type enum member                    | ✓ VERIFIED | Line 15: `OPEN_TEXT_ONLY = "open_text_only"` |
| `models.py` — `StagedEntryRecord`                   | Frozen slotted dataclass for stage rows        | ✓ VERIFIED | Line 97: `@dataclass(frozen=True, slots=True)` |
| `db.py` — `staged_entries` DDL                      | Table with `mt5_comment UNIQUE`               | ✓ VERIFIED | Lines 213-237: `CREATE TABLE IF NOT EXISTS staged_entries`, `mt5_comment TEXT NOT NULL UNIQUE` |
| `db.py` — `signal_daily_counted` DDL               | Daily-slot dedup table                         | ✓ VERIFIED | Lines 239+: `CREATE TABLE IF NOT EXISTS signal_daily_counted` |
| `db.py` — 9 staged-entry helpers                   | CRUD + drain + count helpers                   | ✓ VERIFIED | `create_staged_entries` (746), `get_active_stages` (817), `drain_staged_entries_for_kill_switch` (827), `cancel_unfilled_stages_for_signal` (838), `mark_signal_counted_today` (865), `get_stage_by_comment` (877) |
| `trade_manager.py` — `compute_bands`               | Splits zone into max_stages-1 bands            | ✓ VERIFIED | Lines 52-88: returns list of Band NamedTuples |
| `trade_manager.py` — `_handle_text_only_open`      | Stage-1 insert + immediate market open         | ✓ VERIFIED | Lines 257-359: iterates accounts, inserts stage 1, calls `_execute_open_on_account(staged=True, stage_number=1)` |
| `trade_manager.py` — `_handle_correlated_followup` | Bulk-insert N-1 bands + fire at-arrival stages | ✓ VERIFIED | Lines 361+: bulk insert awaiting_zone rows, fires stages where `stage_is_in_zone_at_arrival` |
| `executor.py` — CR-01 fix                           | Propagate correlator + settings_store to temp_tm | ✓ VERIFIED | Lines 144-145: `temp_tm.settings_store = getattr(self.tm, "settings_store", None)` and `temp_tm.correlator = getattr(self.tm, "correlator", None)` (commit f8b3281) |
| `executor.py` — `_zone_watch_loop`                 | 10s cadence zone-watch with D-14/D-16/D-21    | ✓ VERIFIED | Lines 385+: 10s sleep, loop-entry D-21 guard, D-16 cascade, D-14 pre-flight, D-25 probe |
| `executor.py` — kill switch drain ordering         | Drain before close (D-21)                      | ✓ VERIFIED | `drain_staged_entries_for_kill_switch()` at line 307, position-close loop at line 326 |
| `executor.py` — `resume_trading` no un-cancel      | Resume leaves cancelled rows immutable (D-22)  | ✓ VERIFIED | Lines 358+: no un-cancel logic |
| `executor.py` — `_sync_positions` idempotency      | D-24/D-25 reconciliation on reconnect          | ✓ VERIFIED | Lines 216-287: comment-keyed reconcile, `abandoned_reconnect` status |
| `dashboard.py` — `/staged` route                   | Staged entries page                            | ✓ VERIFIED | Lines 446-462 |
| `dashboard.py` — `/partials/pending_stages`        | HTMX partial for SSE swap                      | ✓ VERIFIED | Lines 464-478, `_enrich_stage_for_ui` at line 357 |
| `dashboard.py` — SSE `pending_stages` event        | Named SSE event for hx-swap                    | ✓ VERIFIED | Lines 1019-1021: `event: pending_stages\n` |
| `dashboard.py` — settings GET/POST routes          | Per-account settings form + hard caps          | ✓ VERIFIED | GET:480, validate:520, POST:631, confirm:691, revert:731 |
| `templates/staged.html`                            | Staged entries page template                   | ✓ VERIFIED | `sse-swap="pending_stages"` at line 12 |
| `templates/partials/pending_stages.html`           | Pending stages panel with aria-live            | ✓ VERIFIED | `aria-live="polite"`, `data-price-cell`, empty-state at lines 2-52 |
| `templates/settings.html`                          | Settings tab interface                         | ✓ VERIFIED | `role="tablist"`, `role="tabpanel"` |
| `templates/partials/settings_confirm_modal.html`   | Confirm/discard/revert modal                   | ✓ VERIFIED | "This applies to signals received AFTER you confirm." at line 37 |
| `static/js/htmx_basecoat_bridge.js`               | Price-flash JS for `data-price-cell`           | ✓ VERIFIED | Lines 11-26: `ring-indigo-400/40`, 150ms flash |
| `bot.py` — correlator wiring                       | SignalCorrelator attached to TM at startup     | ✓ VERIFIED | Lines 185-193: `correlator = SignalCorrelator(...)`, `tm.correlator = correlator` |

### Key Link Verification

| From                              | To                                   | Via                                          | Status     | Details                                                                          |
|-----------------------------------|--------------------------------------|----------------------------------------------|------------|----------------------------------------------------------------------------------|
| `signal_parser.py`                | `SignalType.OPEN_TEXT_ONLY`         | `_RE_OPEN_TEXT_ONLY` regex dispatch (line 236) | ✓ WIRED  | Signals matching text-only pattern get OPEN_TEXT_ONLY type |
| `bot.py`                          | `SignalCorrelator`                   | `tm.correlator = correlator` (lines 185-193) | ✓ WIRED   | Correlator initialized and attached to TM at startup |
| `trade_manager.handle_signal`     | `_handle_text_only_open`            | OPEN_TEXT_ONLY branch (line 277)             | ✓ WIRED    | Dispatch calls correct handler for text-only signals |
| `trade_manager.handle_signal`     | `_handle_correlated_followup`       | `correlator.pair_followup` (line 238)        | ✓ WIRED    | Follow-up OPEN signals check correlator before fallthrough |
| `executor._execute_single_account` | `tm.correlator` / `tm.settings_store` | getattr copy-over (lines 144-145)           | ✓ WIRED    | CR-01 fix — per-account temp TM inherits both attributes (commit f8b3281) |
| `_handle_text_only_open`          | `db.create_staged_entries`          | Direct call (TM:~280)                        | ✓ WIRED    | Stage-1 row inserted before execution |
| `_handle_text_only_open`          | `db.mark_signal_counted_today`      | D-18 daily-slot call                         | ✓ WIRED    | Stage 1 counts against daily limit; siblings bypass |
| `executor._zone_watch_loop`       | `_fire_zone_stage`                  | 10s loop calling price-check + fire          | ✓ WIRED    | Zone-watch fires stages when price enters band |
| `executor.emergency_close`        | `db.drain_staged_entries_for_kill_switch` | Called at line 307 before position close | ✓ WIRED  | D-21 drain ordering confirmed |
| `trade_manager._execute_open_on_account` | `db.log_trade(signal_id=...)`  | Attribution on fill (TM:728)                 | ✓ WIRED    | STAGE-09: trade rows carry originating signal_id |
| `dashboard /settings` POST        | `store.update(account_name, ...)`   | Lines 715+                                   | ✓ WIRED    | Validated settings written to SettingsStore |
| `templates/overview.html`         | `partials/pending_stages.html`      | `sse-swap="pending_stages"` include (line 58-59) | ✓ WIRED | Overview card subscribes to SSE named event |
| `templates/staged.html`           | `partials/pending_stages.html`      | `sse-swap="pending_stages"` (line 12)        | ✓ WIRED    | Staged page subscribes to SSE named event |

### Data-Flow Trace (Level 4)

| Artifact                      | Data Variable     | Source                                  | Produces Real Data | Status      |
|-------------------------------|-------------------|-----------------------------------------|--------------------|-------------|
| `pending_stages.html`         | `stages`          | `db.get_pending_stages()` → `_enrich_stage_for_ui` (dashboard.py:464-478) | Yes — DB query `SELECT * FROM staged_entries WHERE status IN (...)` (db.py:792-813) | ✓ FLOWING |
| `staged.html`                 | `stages`          | Same as above via `/staged` route (dashboard.py:446-462) | Yes | ✓ FLOWING |
| `settings.html`               | `settings_by_account[name]` | `store.effective(name)` (dashboard.py:489) | Yes — SettingsStore reads from DB | ✓ FLOWING |
| SSE `pending_stages` event    | `pending_stages`  | `db.get_pending_stages()` in SSE loop (dashboard.py:1009) | Yes — DB query each SSE cycle | ✓ FLOWING |

Note: `_enrich_stage_for_ui` `current_price` lookup (dashboard.py:377-388) is dead code — `_get_all_positions` does not emit `price_current`. This is flagged in the review as IN-02 and acknowledged in the docstring as deferred. Not goal-blocking.

### Behavioral Spot-Checks

Step 7b: SKIPPED — No runnable entry points without a live MT5 broker connection and Telegram session. Server startup requires active connector configuration; isolated unit tests cover the core logic.

Test suite coverage verified via SUMMARY.md self-checks:
- `tests/test_signal_correlator.py`: 27 tests passed
- `tests/test_staged_trade_manager.py`: 59 tests passed
- `tests/test_staged_executor.py`: 33 tests passed
- `tests/test_settings_store.py`: 10 tests passed
- `tests/test_pending_stages_sse.py`: 7 tests passed

### Requirements Coverage

| Requirement | Source Plan | Description                                                        | Status      | Evidence                                                          |
|-------------|-------------|--------------------------------------------------------------------|-------------|-------------------------------------------------------------------|
| STAGE-01    | 06-01-PLAN  | Text-only signal produces staged entry record + immediate stage-1 open | ✓ SATISFIED | `_handle_text_only_open` (TM:257), `create_staged_entries` (db.py:746), stage-1 fill (TM:727) |
| STAGE-02    | 06-02-PLAN  | `compute_bands` splits zone into N-1 equal-width bands             | ✓ SATISFIED | `compute_bands` (TM:52-88), `stage_is_in_zone_at_arrival` (TM:89) |
| STAGE-03    | 06-01-PLAN  | SignalCorrelator pairs text-only orphan with follow-up by symbol+direction | ✓ SATISFIED | `SignalCorrelator` (signal_correlator.py), correlator attached at bot.py:185-193 |
| STAGE-04    | 06-02, 06-04 | Zone-watch loop fires pending stages when price enters band (D-14 pre-flight) | ✓ SATISFIED | `_zone_watch_loop` (executor.py:385), D-14 tolerance check, `_fire_zone_stage` |
| STAGE-05    | 06-02-PLAN  | Per-stage lot sizing via SettingsStore (D-15)                      | ✓ SATISFIED | `stage_lot_size` (TM:107), `snapshot_settings` in stage row, settings_store propagated (executor.py:144) |
| STAGE-06    | 06-04-PLAN  | Kill switch drains all pending stages before closing positions (D-21) | ✓ SATISFIED | `drain_staged_entries_for_kill_switch()` at executor.py:307, position-close at :326 |
| STAGE-07    | 06-04-PLAN  | MT5 reconnect reconciles stage status by idempotency comment (D-24/D-25) | ✓ SATISFIED | `_sync_positions` (executor.py:216), `get_stage_by_comment` (db.py:877) |
| STAGE-08    | 06-05-PLAN  | Dashboard pending-stages panel with SSE live updates               | ✓ SATISFIED | `/staged` (dashboard.py:446), SSE `pending_stages` event (dashboard.py:1021), `_enrich_stage_for_ui` (dashboard.py:357) |
| STAGE-09    | 06-01, 06-02 | Trade log rows carry originating signal_id (attribution)           | ✓ SATISFIED | `db.log_trade(signal_id=signal_id, ...)` (TM:728) |
| SET-03      | 06-03-PLAN  | Per-account settings form with hard caps, preview-before-commit, future-only apply | ✓ SATISFIED | `validate_settings_form` hard caps (dashboard.py:520), confirm modal "after you confirm" (settings_confirm_modal.html:37), `store.update()` (dashboard.py:715) |

**Requirements coverage: 10/10 SATISFIED**

No orphaned requirements. All 10 Phase 6 requirements appear in plan frontmatter and have implementation evidence.

### Anti-Patterns Found

The following items are carried from the code review (06-REVIEW.md). All were evaluated for goal impact.

| ID     | File                     | Line(s)      | Pattern                                                                | Severity     | Impact                                                                    |
|--------|--------------------------|--------------|------------------------------------------------------------------------|--------------|---------------------------------------------------------------------------|
| WR-01  | `executor.py`            | 455-456, 515-517 | Pre-flight tolerance is 1.5× band_width from center (3× wide envelope) vs documented 0.5× | ⚠️ Warning | Stages fire too early relative to spec; no goal blocker but spec drift |
| WR-02  | `db.py`                  | 868 vs 341-353 | `mark_signal_counted_today` uses Postgres column default `CURRENT_DATE` (server TZ) while `increment_daily_stat` uses Python-side UTC | ⚠️ Warning | TZ mismatch can double-count at midnight if Postgres TZ ≠ UTC; low operational risk on UTC servers |
| WR-03  | `dashboard.py`           | 480-499      | GET `/settings` passes `None` to template when SettingsStore is absent; template dereferences `s.risk_mode` → `AttributeError` | ⚠️ Warning | Crash risk when `trading_enabled=False`; all POST handlers are guarded (lines 611, 639, 697, 741) |
| WR-04  | `dashboard.py`           | 391-408      | Mixed sign typography (Unicode `−` vs ASCII `+`) in `_enrich_stage_for_ui`; "to next band" label misleading when price past band | ℹ️ Info      | Visual inconsistency only; no functional impact                           |
| WR-05  | `tests/test_pending_stages_sse.py` | 270-272 | SSE media_type assertion brittle — some stacks append `; charset=utf-8` | ℹ️ Info   | Low impact; prefer asserting `Content-Type` header                        |
| WR-06  | `dashboard.py` / `db.py` | 450, 792-813 | `_get_pending_stages` unbounded query; O(positions) enrichment per row | ⚠️ Warning | Availability risk under backlog; suggested fix: `limit=500`, defer to Phase 7 |
| IN-02  | `dashboard.py`           | 377-388      | `current_price` lookup in `_enrich_stage_for_ui` is dead code; `_get_all_positions` never emits `price_current` | ℹ️ Info    | Acknowledged in docstring as deferred; fallback `current_price=None` always taken |
| IN-04  | `dashboard.py`           | 35, 1115-1122 | `_daily_limit_warned` module-level set never resets at UTC midnight   | ℹ️ Info      | Latent: warning suppressed after first hit until restart; fix: track as `set[tuple[str, date]]` |

**Blocker anti-patterns:** 0  
No anti-patterns block the phase goal. CR-01 (the one critical review finding) is resolved in commit f8b3281.

### Human Verification Required

The following scenarios require a live environment (MT5 demo/real, Telegram session, browser) and cannot be verified programmatically.

#### 1. Text-Only Signal → Single MT5 Position

**Test:** Send a text message matching the text-only pattern (e.g. "Gold buy now") via Telegram to the bot.
**Expected:** Exactly one position opens per enabled account with a valid SL (not 0.0); a `staged_entries` row is created with `status=filled`, non-empty `snapshot_settings`, and a `mt5_comment` matching `telebot-{signal_id}-s1`; re-sending within the dup-guard window produces no second position.
**Why human:** Requires live MT5 broker connection and active Telegram webhook; full dispatch chain (Telegram → bot.py → executor → MT5) cannot be exercised without both services running.

#### 2. Correlated Follow-Up Arms and Fires Pending Stages

**Test:** After the text-only stage 1 fills, send a structured follow-up signal for the same symbol and direction with an entry zone, SL, and TP within the correlation window (default 600s).
**Expected:** N-1 `staged_entries` rows appear as `awaiting_zone`; as price enters each band sequentially, the zone-watch loop (10s cadence) transitions each row to `filled` and opens the corresponding MT5 position; D-08 SL guard prevents any sl=0.0 submission.
**Why human:** Requires live price feed and real-time zone entry; band-entry timing depends on market movement and cannot be simulated without live connectivity.

#### 3. Kill Switch Drain Ordering and Resume Immutability

**Test:** With at least one `awaiting_zone` stage present, toggle the kill switch (emergency close) from the dashboard.
**Expected:** All `awaiting_zone` rows transition to `cancelled` in the database BEFORE any position-close requests are sent to MT5 (D-21 ordering); after resuming trading, the previously cancelled rows remain `cancelled` — they are not reactivated (D-22).
**Why human:** Drain ordering and stage-cancel immutability require observing DB state transitions under concurrent execution; timing guarantee (drain before close) cannot be asserted with static analysis alone.

#### 4. MT5 Reconnect Idempotency

**Test:** Simulate an MT5 connector disconnect while a stage is executing (i.e. the open request was sent but the fill confirmation has not been received). Reconnect within `signal_max_age_minutes`.
**Expected:** `_sync_positions` matches the open position by its comment (`telebot-{signal_id}-s{n}`); the `staged_entries` row transitions to `filled` without creating a duplicate trade log entry; a stage whose signal has expired beyond `signal_max_age_minutes` is set to `abandoned_reconnect`.
**Why human:** Requires controlled MT5 disconnect/reconnect cycle; idempotency key matching depends on the broker returning the comment field accurately in the positions list.

#### 5. Dashboard Pending Stages Panel and Price Flash

**Test:** With pending stages in the database, open the dashboard overview page and the `/staged` page in a browser.
**Expected:** The pending stages panel renders with correct stage data (symbol, direction, band, lot size, distance to band); when the SSE stream pushes an update, price cells with `data-price-cell` flash with an indigo ring for ~150ms; when no stages are pending, the empty-state "No pending stages" message is shown.
**Why human:** Visual rendering, CSS animation (`ring-indigo-400/40` in `htmx_basecoat_bridge.js`), and SSE stream continuity require a real browser session and running server.

#### 6. Settings Form Hard Caps and Future-Only Semantics

**Test:** In the settings form for an account, attempt to set `max_stages=11` and `risk_value=5.1` (both above hard caps). Then set a valid value (e.g. `max_stages=3`) and confirm.
**Expected:** Values above caps are rejected with a validation error message; the valid change shows the confirmation modal with the text "This applies to signals received AFTER you confirm"; confirming applies the change; a signal dispatched immediately after confirm uses the new settings; a signal already in-flight (stage rows already created with `snapshot_settings`) continues using the snapshotted settings.
**Why human:** Form validation feedback and modal interaction require browser; the "future signals only" semantic requires verifying that `snapshot_settings` is captured at signal-dispatch time by exercising a concurrent scenario.

---

_Verified: 2026-04-20T12:00:00Z_
_Verifier: Claude (gsd-verifier)_
