# Phase 6: Staged entry execution - Context

**Gathered:** 2026-04-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Ship the text-only → correlated-follow-up staged-entry execution feature on top of the Phase 5 foundation, end-to-end, without regressing any v1.0 safety primitive:

1. **Signal parser extension** — recognize text-only "now" signals (e.g. "Gold buy now") and emit a distinct signal shape with no entry/SL/TP numerics.
2. **Two-signal correlation** — match a follow-up zone/SL/TP signal to a prior text-only signal by `(symbol, direction)` within a configurable window and treat them as one trade sequence.
3. **Staged execution engine** — text-only opens stage 1 immediately at market with a mandatory default SL; follow-up arms a zone-watcher that fires stages 2..N as price enters pre-declared bands; per-stage sizing, idempotency, and safety-hook integration.
4. **Kill-switch + reconnect integration** — `emergency_close` drains `staged_entries` queue BEFORE closing positions; MT5 reconnect reconciles `staged_entries` against live MT5 positions by comment-based idempotency key.
5. **Per-account settings form (SET-03)** — dashboard page to edit `AccountSettings` at runtime, backed by the Phase-5 `SettingsStore` + `settings_audit` tables.
6. **Pending-stages panel (STAGE-08)** — live operator view of in-flight staged sequences.
7. **Attribution (STAGE-09)** — every staged fill traceable back to its originating signal for per-source analytics.

**Out of this phase:**
- Full Basecoat restyle of every existing dashboard page (overview, positions, history, analytics) → Phase 7
- Mobile-responsive layout / slide-over sidebar → Phase 7
- Positions drilldown / trade-history filters / per-source analytics deep-dive UI → Phase 7
- Dual-key `SESSION_SECRET` rotation, alembic tooling (`DBE-01`) → v1.2
- Martingale / averaging-down strategies → explicitly prohibited

</domain>

<decisions>
## Implementation Decisions

### Signal parser — text-only "now" signals (STAGE-01)

- **D-01:** Introduce a new `SignalType.OPEN_TEXT_ONLY` variant (or equivalent) in `models.py` so downstream code can branch on type rather than peeking at numeric absence. Existing `SignalType.OPEN` continues to mean "has entry zone + SL + TP" (the follow-up shape).
- **D-02:** Text-only parser recognizes `{symbol} {buy|sell} now` with no numerics. The word `now` is the discriminator; absence of any price digits confirms text-only. `signal_keywords.json` may gain a `now_keywords` list (`["now", "asap", "immediate"]`) for future provider variants — Claude's discretion.
- **D-03:** Follow-up signal parsing is unchanged — the existing `_RE_OPEN` + SL/TP blocks continue to produce `SignalType.OPEN` signals. Correlation happens AFTER parse, in the trade-manager / correlator layer, not in the parser itself.

### Two-signal correlation (STAGE-03)

- **D-04:** Correlation key = `(symbol, direction)`. Window = **10 minutes** (configurable via `GlobalConfig.correlation_window_seconds`, default `600`).
- **D-05:** When a follow-up signal arrives, find the **most recent** pending text-only signal matching `(symbol, direction)` within the window. If none, the follow-up is treated as a normal single-signal `OPEN` (v1.0 behavior preserved).
- **D-06:** Correlation is one-to-one: once a text-only signal is paired with a follow-up, it cannot be re-paired. A second follow-up for the same orphan is treated as an independent signal.
- **D-07:** Correlation metadata stored on `staged_entries.signal_id` (the originating text-only signal's id) — stages inherit the parent signal's identity.

### Orphan safety (Pitfall 1)

- **D-08:** Text-only stage-1 open **always submits a non-zero SL** computed from `AccountSettings.default_sl_pips`. A `sl=0.0` submit is a hard failure; signal is rejected with a logged reason. This is the single most important invariant of Phase 6.
- **D-09:** If no follow-up arrives within the correlation window, **no automatic action is taken on the orphan** — the position continues to be protected by the default SL and is managed by the operator like any other single-stage trade. No watchdog auto-close, no heuristic SL/TP force-set.
- **D-10:** Per-account orphan cap reuses existing `AccountSettings.max_open_trades` (per-symbol cap from v1.0). No new `max_orphan_text_only` setting. Rationale: every stage-1 text-only fill is a real MT5 position and already counts; adding a second cap is surface area without additional safety.

### Stage trigger mechanism (STAGE-04)

- **D-11:** **Zone-watcher model.** After a follow-up correlates and stage 1 is already filled, compute `N - 1 = max_stages - 1` equal-width bands across the signal's `(zone_low, zone_high)` range. A background `_zone_watch_loop` task in `executor.py` polls MT5 price and fires each stage when price first enters its band.
- **D-12:** **Equal slices.** Bands are contiguous equal-width partitions of the declared zone; deterministic from `(zone_low, zone_high, max_stages)` — no signal-payload extension needed.
- **D-13:** **In-zone at follow-up arrival:** on follow-up receipt, check current bid/ask vs each band. Any band whose trigger edge the price has already crossed — fire that stage immediately at market. Remaining bands arm and wait. Matches "enters the zone" intent when price got there before us.
- **D-14:** **Cadence:** 10s uniform polling for all symbols. Before each `open_order` submission, perform a **pre-flight price re-check** — re-fetch bid/ask and verify still within the band ± 0.5×band_width tolerance. If outside, skip this tick and re-queue. Mitigates Pitfall 6.
- **D-15:** **Stage sizing — equal split.** At signal receipt, compute `risk_per_stage = AccountSettings.risk_value / max_stages` (applied to the snapshotted `AccountSettings` per Phase-5 D-32). `risk_mode="percent"` and `risk_mode="fixed_lot"` both split; in fixed-lot mode, each stage gets `fixed_lot / max_stages`.
- **D-16:** **Sequence lifetime = stage-1 lifetime.** Remaining unfilled stages are cancelled (status=`cancelled_stage1_closed`) when stage 1 exits (SL, TP, or manual close). No separate `max_age_minutes` timer for the sequence. Reconciled via `_sync_positions` + the zone-watcher on every tick checking `staged_entries.stage_1_ticket` status.
- **D-17:** **Stage failure handling:** a failed stage (broker reject, invalid volume, connection flake) is marked `status="failed"` with the broker reason; the zone-watcher continues arming remaining stages independently. No retry. No sequence abort. Rationale: each stage is a real independent position; one failure shouldn't take down the rest, and retry layers are already handled by the v1.0 executor reconnect machinery.

### Daily-limit + per-symbol cap accounting (Pitfall 3)

- **D-18:** **1 signal = 1 daily-limit slot.** Only the FIRST successful fill of a `signal_id` increments `daily_stats.trades_count`. Stages 2..N do not increment. Guard is a helper (`db.mark_signal_counted_today(signal_id, account) -> bool`) that returns `True` the first time called for a given `(signal_id, account, date)` and `False` thereafter; the caller increments iff it returns `True`. Uses `staged_entries.signal_id` (new table) as the attribution key — zero `ALTER TABLE` on v1.0 `daily_stats`.
- **D-19:** **Per-symbol `max_open_trades` counts each stage.** Each stage is a real MT5 position that occupies a slot. If `max_open_trades=3` and `max_stages=5`, stages 4–5 are marked `status="capped"` at fire time (or blocked at pre-flight) and never submitted. This matches broker reality and preserves v1.0 per-symbol-cap semantics.
- **D-20:** **Failed stages do not count** against daily-limit — preserves v1.0 semantics (`trades_count` increments on successful `open_order` only). Failures log but don't burn budget.

### Safety-hook integration (STAGE-07, STAGE-06, STAGE-05)

- **D-21:** **Kill-switch drain order (STAGE-07):** `Executor.emergency_close` must execute `UPDATE staged_entries SET status='cancelled_by_kill_switch' WHERE status IN ('pending','awaiting_followup','awaiting_zone')` **BEFORE** closing any position. The zone-watcher loop checks `self._trading_paused` INSIDE each per-stage tick — between pre-flight re-check and `open_order` submit — so a watcher can't race the kill-switch window.
- **D-22:** **`resume_trading()` never un-cancels** drained rows. Operator re-creates intent by re-sending the signal. The `cancelled_by_kill_switch` status is terminal.
- **D-23:** **Duplicate-direction guard bypass (STAGE-05):** the guard at `trade_manager.py:215` is updated to skip rejection iff the incoming submission carries a matching `signal_id` to an existing same-direction position on the same symbol (i.e. a sibling stage of the same correlated sequence). All other same-direction rejections are preserved — unrelated signals same direction still rejected.
- **D-24:** **Reconnect reconciliation (STAGE-06):** MT5 order `comment` field is set to `telebot-{signal_id}-s{stage}` on every stage fill (stage 1 = `-s1`, stage 2 = `-s2`, …). On reconnect, `Executor._sync_positions` is extended to (a) read `staged_entries` for affected accounts, (b) list MT5 positions by comment prefix, (c) mark stages `filled` where a matching comment exists, (d) mark stages `abandoned_reconnect` for pending rows whose MT5 position is missing AND signal is older than `signal.max_age_minutes`. Operator alerted on any `abandoned_reconnect`.
- **D-25:** **Idempotency rule:** before a stage submit, query MT5 positions by the stage's target comment; if one already exists (reconnect retry edge case), mark the stage `filled` without resubmitting.

### Per-account settings form (SET-03)

- **D-26:** `/settings` page (replaces the v1.0 `settings.html` stub) renders a **Basecoat tabs component with one tab per account**. Each tab holds a form for that account's `AccountSettings` fields: `risk_mode`, `risk_value`, `max_stages`, `default_sl_pips`, `max_daily_trades`. Per-account `enabled` flag and account-level metadata (login, server) remain read-only (seeded from `accounts.json`).
- **D-27:** **Two-step dangerous-change modal.** On Save, a Basecoat modal opens with a diff view (`risk_value: 1.0 → 2.0`), a dry-run preview ("Next typical signal would size X lots at Y% risk"), and a confirm button. Cancel discards the form change. Mirrors the v1.0 kill-switch confirmation pattern.
- **D-28:** **Audit-log timeline per account tab**, driven by the Phase-5 `settings_audit` table. Each row shows timestamp, field, old → new, and a **Revert button** that re-posts the old value through the same two-step modal (one-click rollback with the same safety gate as a forward edit).
- **D-29:** **Server-side hard caps** reject the form with a clear per-field error: `0 < risk_value ≤ 5.0` (percent) or `0 < risk_value ≤ max_lot_size` (fixed_lot), `1 ≤ max_stages ≤ 10`, `1 ≤ default_sl_pips ≤ 500`, `1 ≤ max_daily_trades ≤ 100`. Client-side echo of these is Claude's discretion.
- **D-30:** **"Changes apply to next signal only" copy** appears inline near each field and in the confirmation modal. Already-enqueued stages use the snapshot taken at signal receipt (Phase-5 D-32); this phase's form never mutates in-flight sequences.
- **D-31:** CSRF uses the existing HTMX-header pattern (authenticated route). No double-submit-cookie here — that pattern is login-only.

### Pending-stages panel (STAGE-08)

- **D-32:** **Location:** a compact pending-stages table on `/overview` (rendered as a partial alongside existing cards) + a "View all" link to a fuller `/staged` page. Overview version shows up to 5 most-recent active sequences; `/staged` shows all.
- **D-33:** **Columns (REQUIREMENTS.md + user additions):** account name, symbol, direction, stages filled / total, price target band (current band low–high), **live current price + distance-to-next-band**, elapsed time since sequence start.
- **D-34:** **Live-refresh pattern:** extend the existing SSE stream (`dashboard.py:372-396`) to include pending-stages payload. Reuses the 2s cadence. Falls back to HTMX polling (`hx-trigger="every 5s"`) on `/staged` standalone page if SSE drops. `X-Accel-Buffering: no` header preserved on SSE (Pitfall gotcha).
- **D-35:** **Empty state:** "No pending stages — all signals resolved." Styled via Basecoat empty-state primitive.
- **D-36:** **Cancelled-stage visibility:** recently-cancelled stages (status in `cancelled_by_kill_switch`, `cancelled_stage1_closed`, `abandoned_reconnect`) are shown in a collapsed "Recently resolved" section of `/staged` (not on overview), with the cancellation reason visible. Prevents the panel going silent after kill-switch drain.

### Attribution (STAGE-09)

- **D-37:** **`staged_entries` is the attribution table.** Every staged fill writes a row with: `id`, `signal_id` (FK to signals, the originating text-only or single-follow-up parent), `stage_number` (1..N), `account_name`, `symbol`, `direction`, `zone_low`, `zone_high`, `band_low`, `band_high`, `target_lot`, `snapshot_settings` (JSONB of the frozen `AccountSettings`), `mt5_comment` (e.g. `telebot-{signal_id}-s{stage}`), `mt5_ticket` (nullable, set on fill), `status`, `created_at`, `filled_at`, `cancelled_reason`.
- **D-38:** **No `ALTER TABLE` on v1.0 `trades`.** Analytics per-signal joins `trades` to `staged_entries` via `staged_entries.mt5_ticket = trades.ticket`. If the analytics query shape becomes painful, Phase 7 may introduce a `trade_stages` view — not this phase.
- **D-39:** `staged_entries` DDL lives alongside the Phase-5 tables in `db.py::init_schema()` as `CREATE TABLE IF NOT EXISTS` (additive-only discipline from Phase 5 D-09 lineage).

### Claude's Discretion

- Exact column types / constraints / indexes for `staged_entries` (composite index on `(status, account_name, signal_id)` is the likely performance win).
- Whether `snapshot_settings` is JSONB or expanded into explicit columns (JSONB is leaner; explicit columns are queryable without jsonpath).
- Exact structure of the zone-watcher loop vs reusing `_heartbeat_loop` pattern — recommended: new task peer to `_heartbeat_loop` + `_cleanup_loop`.
- Signal correlator's data structure (in-memory dict of `{ (symbol, direction): [list of pending orphans] }` vs DB query each time) — in-memory is cheaper, DB is simpler.
- Exact regex / keyword surface for "now" text-only signals — start with `\bnow\b` and extend via `signal_keywords.json` if providers diverge.
- Whether `SignalType.OPEN_TEXT_ONLY` lives as a distinct enum value or as a flag `is_text_only: bool` on the existing `SignalAction` — either works; enum is cleaner.
- Dashboard form field ordering inside each settings tab.
- Whether `/staged` is a separate route or a query-string view on the same blueprint.
- Band tolerance constant (0.5×band_width in D-14) is a reasonable starting default; planner may make it `GlobalConfig.zone_band_tolerance_ratio`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & milestone scope
- `.planning/REQUIREMENTS.md` §Staged Entry Execution (STAGE-01..09), §Per-Account Settings (SET-03) — the 10 requirements this phase delivers
- `.planning/ROADMAP.md` Phase 6 — goal + 6 success criteria
- `.planning/PROJECT.md` §Current Milestone — staged-entry intent and safety bar
- `.planning/STATE.md` §Blockers/Concerns — the 5 Phase-6-specific pitfall notes already flagged

### Prior-phase handoffs
- `.planning/phases/05-foundation/05-CONTEXT.md` §D-32 — `SettingsStore.effective()` returns cheap-to-copy `AccountSettings` ready for stage-snapshot; §D-23..D-28 — accounts + account_settings + settings_audit tables that SET-03 edits; §D-04-REVISED — Tailwind v4 build that serves this phase's new templates
- `.planning/phases/05-foundation/05-VERIFICATION.md` — confirmation Phase-5 foundation shipped
- `models.py::AccountSettings` — frozen dataclass already defined with `max_stages`, `default_sl_pips`, `risk_mode`, `risk_value`, `max_daily_trades`

### Research synthesis (HIGH confidence, Phase-6 critical)
- `.planning/research/SUMMARY.md` §Open Questions #1 — resolved: two-signal correlation model (this context locks it)
- `.planning/research/ARCHITECTURE.md` §1 (SettingsStore), §3 (staged-entry data-flow diagram — note: described zone-watcher, matches D-11), §7 (build order)
- `.planning/research/PITFALLS.md` — **specifically Pitfalls 1–7, 17, 18** (the full Phase-6 pitfall set): orphan SL (P1), duplicate-direction guard (P2), daily-limit accounting (P3 — resolved by D-18), kill-switch drain (P4 — D-21), reconnect idempotency (P5 — D-24), zone-watcher cadence (P6 — D-14), settings mutation mid-stage (P7 — Phase-5 snapshot), schema ALTER (P17 — D-38/D-39), SSE-vs-kill-switch race (P18 — relevant to STAGE-08 panel)
- `.planning/research/FEATURES.md` §1 (staged-entry table-stakes), §2 (settings backend — already shipped in Phase 5)
- `.planning/research/STACK.md` §4 — zero new Python deps for staged entries (in-repo code only)

### Codebase intel
- `.planning/codebase/ARCHITECTURE.md` — `bot.py` / `executor.py` / `trade_manager.py` layering; the zone-watcher task joins existing `_heartbeat_loop` + `_cleanup_loop` peers
- `.planning/codebase/CONVENTIONS.md` — async patterns, DB helper conventions, logging style the new code must follow
- `.planning/codebase/INTEGRATIONS.md` — MT5 REST connector contract (bid/ask fetch, open_order signature, comment field handling)
- `.planning/codebase/TESTING.md` — pytest-asyncio fixtures, session-scoped event loop, integration-test harness for the staged-entry safety test battery

### Live code anchors (Phase 6 integration points)
- `executor.py:226` — `emergency_close`; D-21 drain logic inserts before the position-close loop
- `executor.py:208-217` — `_sync_positions`; D-24 reconciliation extends this
- `executor.py` `_heartbeat_loop` / `_cleanup_loop` pattern — `_zone_watch_loop` mirrors it (D-11)
- `trade_manager.py:215` — duplicate-direction guard; D-23 bypass for same-signal stages
- `trade_manager.py:263-270` — `_execute_open_on_account`; D-08 default-SL enforcement lives here (reject `sl=0.0` submissions)
- `trade_manager.py:168-172, 289` — `max_daily_trades` increment path; D-18 signal-id-aware guard wraps this
- `signal_parser.py::_RE_OPEN` + `SignalType` enum in `models.py` — D-01/D-02 text-only parsing extension
- `dashboard.py:372-396` — SSE stream; D-34 pending-stages payload extends the loop
- `settings_store.py` — Phase-5 `SettingsStore` that signal-receipt code calls `.effective(account_name)` against for the snapshot (D-15)
- `templates/settings.html` — rewritten in this phase for SET-03; currently a stub
- `templates/overview.html` — D-32 pending-stages panel inserted as a Basecoat card partial

### External docs (verify during research, cite in plans)
- MT5 REST connector docs — confirm `open_order` `comment` field round-trips on position list queries (needed for D-24 idempotency)
- Basecoat UI v0.3.3 — tabs, dialog (modal), table components JS surface (needed for D-26/D-27/D-32)
- Starlette SSE patterns — `EventSourceResponse`, `X-Accel-Buffering: no` (already in v1.0 `dashboard.py:395`; preserve)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `executor.py::Executor` — class already owns `_heartbeat_loop` + `_cleanup_loop` + `_reconnecting` state + `_trading_paused` flag; new `_zone_watch_loop` is a sibling task that reuses the same cadence / flag-check patterns.
- `executor.py::emergency_close` — existing hook point for kill switch; D-21 inserts a pre-step here, no new entry point needed.
- `executor.py::_sync_positions` — existing reconnect hook; D-24 extends this rather than adding a new reconciliation path.
- `trade_manager.py::_execute_open_on_account` — existing single-stage fill path; staged fills reuse this call site with `signal_id` + `stage_number` threaded through. Default-SL enforcement lives here.
- `settings_store.py::SettingsStore.effective(account_name)` — Phase 5 deliverable returning a frozen `AccountSettings`; stage snapshot is a simple dataclass copy at signal receipt.
- `models.py::AccountSettings` — frozen / slotted; already carries `max_stages`, `default_sl_pips`, `risk_mode`, `risk_value`, `max_daily_trades`. Zero model changes needed for settings consumption.
- `models.py::TradeRecord.signal_id` — field already exists on the dataclass; if it's also persisted in the trades DB table, the analytics join is trivial (planner to verify).
- `db.py` — existing asyncpg pool wiring; new `staged_entries` table uses the same pool + transaction patterns.
- `signal_parser.py` — existing OPEN parser handles follow-up-shaped signals unchanged; D-01/D-02 only adds the text-only recognizer.
- `dashboard.py::SSE stream` (lines 372-396) — existing 2s cadence event stream; D-34 extends payload. `X-Accel-Buffering: no` already set.
- `templates/base.html` + Basecoat vendored in Phase 5 — tabs / modal / table primitives ready to use.

### Established Patterns
- **Additive-only DDL** (v1.1 discipline from Phase 5): `CREATE TABLE IF NOT EXISTS` for `staged_entries`; no `ALTER TABLE` on `trades`, `signals`, `daily_stats`, or any other v1.0 table. Analytics uses joins.
- **Snapshot settings at signal receipt** (Phase 5 D-32 lineage): `dataclasses.replace()` on the `AccountSettings` instance; persist into `staged_entries.snapshot_settings` (JSONB or flat columns — Claude's discretion).
- **Comment-based idempotency**: `telebot-{signal_id}-s{stage}` format; same pattern used in existing close-position comments.
- **Kill-switch drain-before-close**: order-of-ops discipline baked into `emergency_close`; preserved and extended here.
- **HTMX-header CSRF for authenticated routes** (Phase 5 D-14): settings form POST uses existing header-based CSRF; double-submit cookie is login-only.
- **Two-step confirmation modal**: mirrors v1.0 kill-switch UX; applied to SET-03 dangerous-change confirm (D-27) and audit rollback (D-28).

### Integration Points
- `bot.py::main` — wire the signal-correlator state (or in-memory orphan dict) before `TradeManager`; spawn `_zone_watch_loop` as a peer to existing `_heartbeat_loop` after MT5 connect.
- `executor.py::emergency_close` — insert `staged_entries` drain call before the existing position-close loop.
- `executor.py::_sync_positions` — extend to reconcile `staged_entries` by comment prefix on reconnect.
- `trade_manager.py:215` — same-signal-id bypass for duplicate-direction guard.
- `trade_manager.py::_execute_open_on_account` — enforce non-zero SL on text-only fills; thread `signal_id` + `stage_number` through for comment + attribution.
- `trade_manager.py::daily-limit increment path` (lines 168-172, 289) — wrap in helper that no-ops when `signal_id` already counted today.
- `signal_parser.py` — new text-only recognizer; returns a distinct `SignalType` variant.
- `models.py` — add `SignalType.OPEN_TEXT_ONLY` (or flag). Potentially add `StagedEntryRecord` dataclass for DB row mapping.
- `dashboard.py` — add `/settings/{account}` POST handler, `/staged` GET route; extend SSE payload with pending-stages.
- `templates/settings.html` — rewrite on Basecoat tabs per account + two-step modal + audit timeline.
- `templates/overview.html` — insert pending-stages partial.
- `templates/staged.html` + `templates/partials/pending_stages.html` — new templates.
- `db.py` — `init_schema` DDL for `staged_entries`; new helpers: `create_staged_entries`, `update_stage_status`, `get_pending_stages`, `drain_staged_entries_for_kill_switch`, `mark_signal_counted_today`, `reconcile_staged_entries_after_reconnect`.

</code_context>

<specifics>
## Specific Ideas

- **"sl=0.0 is never acceptable."** Text-only stage-1 opens always carry a non-zero SL from `AccountSettings.default_sl_pips`. The `_execute_open_on_account` path hard-rejects any submit with `sl=0.0`, including the text-only branch. This is the single invariant that must survive the phase.
- **"Sequence lifetime = stage-1 lifetime."** The zone-watcher doesn't run on a max-age timer; it runs until stage 1 closes. This ties stage 2..N fate to the primary position's fate in a way that matches trader intuition: if the idea exits, the scaling-in plan dies with it.
- **"Enter the zone" means what the user said — not 'enter if crossed.'** When a follow-up arrives and price is already inside the zone (bands crossed), fire immediately for the crossed bands rather than waiting for a re-entry from outside. This is the "the trade is already on" path.
- **"Dashboard = observability + safe edits."** The pending-stages panel is an operator observability tool (no actions except cancel). The settings form is the one live-mutation surface and it wears a two-step modal + rollback button like armor.
- **"No new safety knobs."** `max_open_trades` and `max_daily_trades` are the ceiling — no separate `max_orphan_text_only`, no `max_staged_positions_per_signal`. Fewer knobs, fewer footguns.
- **"One-to-one correlation, most-recent match."** A follow-up correlates to the most-recent pending same-(symbol, direction) text-only within 10 min. Simple rule; operationally legible in logs.

</specifics>

<deferred>
## Deferred Ideas

- **Adaptive zone reshape on follow-up update** — if a second follow-up arrives updating the zone while stages pending, adapt unfilled stages to the new zone. Defer to v1.2; v1.1 treats subsequent follow-ups as independent.
- **Trailing-activation** (stage N arms only after stage N-1 fills) — defer; current model arms all stages on follow-up receipt.
- **Per-symbol adaptive cadence** (faster polling for XAU/BTC) — defer; 10s uniform + pre-flight re-check is the v1.1 bar.
- **MT5 tick streaming** — connector may not support; defer to a future research spike.
- **`max_orphan_text_only` dedicated cap** — deferred; `max_open_trades` is the ceiling in v1.1.
- **Signal-specified per-stage prices / sizing** — providers don't emit this today; equal slices + equal split is the v1.1 default.
- **Auto-close watchdog on orphan text-only** — deferred; default SL is the protection, operator is the intervention.
- **`trade_stages` analytics view / denormalized column on `trades`** — defer to Phase 7 if analytics join proves painful.
- **Per-source signal cancel button in the settings page** — deferred; pending-stages panel has per-sequence cancel in Phase 6 scope.
- **Bulk settings apply / copy-from-account / diff-from-seed view** — defer to v1.2 dashboard polish.
- **SSE `asyncio.Event` acceleration on kill-switch state change (Pitfall 18 extra hardening)** — defer; 2s cadence is acceptable for v1.1; can upgrade in Phase 7 if operator friction reports.

</deferred>

---

*Phase: 06-staged-entry-execution*
*Context gathered: 2026-04-19*
