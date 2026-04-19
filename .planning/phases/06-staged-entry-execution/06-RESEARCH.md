# Phase 6: Staged Entry Execution — Research

**Researched:** 2026-04-19
**Domain:** Live-money MT5 staged-entry execution (text-only "now" signals + correlated zone follow-up) + per-account settings UI
**Confidence:** HIGH (architecture/code paths grounded in this session's reads); MEDIUM on MT5 REST bridge `comment` round-trip (inferred from codebase, not verified against the bridge server source)

## Summary

Phase 6 is the single highest-risk live-money phase in v1.1. The user has already locked 39 decisions in CONTEXT.md — this research does not re-explore them. Instead it (a) answers the 11 planner-blocking technical questions from the research brief, (b) crystallises pseudo-code for the load-bearing `_zone_watch_loop` and in-zone-at-arrival branches that the planner will turn into tasks, (c) confirms the `staged_entries` DDL shape consistent with Phase 5's additive-only discipline, and (d) cross-checks every mitigated pitfall back to a specific D-## plus the residual risk the plans must test for.

The architecture substrate is already in place: `settings_store.py::SettingsStore.effective()` returns a frozen `AccountSettings` (verified), `executor.py::_heartbeat_loop` and `_cleanup_loop` establish the task peer pattern the new `_zone_watch_loop` must mirror (verified), `trade_manager.py:215` is the exact line the duplicate-direction bypass must edit (verified), and `mt5_connector.py:676` proves the `comment` field is POSTed to the REST bridge — the question of whether the bridge preserves it on `GET /positions` is the sole load-bearing external assumption and must be covered by an integration test in the plan.

**Primary recommendation:** Structure the phase as four cleanly-separable plan areas — (1) schema + correlator + parser (pure data, testable in isolation), (2) stage-fire engine + `_zone_watch_loop` + safety-hook integration (live trading core, gate on integration test battery), (3) SET-03 settings form (already-well-scoped UI work), (4) STAGE-08 pending-stages panel (observability-only, low risk). Land (1) → (2) strictly serial; (3) and (4) can parallelise (3) after (1) merges. Hold (2) behind a dry-run UAT on the full integration test battery before any kill-switch drain runs against live accounts.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Signal parser — text-only "now" signals (STAGE-01)**
- **D-01:** Introduce a new `SignalType.OPEN_TEXT_ONLY` variant (or equivalent) in `models.py` so downstream code can branch on type rather than peeking at numeric absence. Existing `SignalType.OPEN` continues to mean "has entry zone + SL + TP" (the follow-up shape).
- **D-02:** Text-only parser recognizes `{symbol} {buy|sell} now` with no numerics. The word `now` is the discriminator; absence of any price digits confirms text-only. `signal_keywords.json` may gain a `now_keywords` list (`["now", "asap", "immediate"]`) for future provider variants — Claude's discretion.
- **D-03:** Follow-up signal parsing is unchanged — the existing `_RE_OPEN` + SL/TP blocks continue to produce `SignalType.OPEN` signals. Correlation happens AFTER parse, in the trade-manager / correlator layer, not in the parser itself.

**Two-signal correlation (STAGE-03)**
- **D-04:** Correlation key = `(symbol, direction)`. Window = **10 minutes** (configurable via `GlobalConfig.correlation_window_seconds`, default `600`).
- **D-05:** When a follow-up signal arrives, find the **most recent** pending text-only signal matching `(symbol, direction)` within the window. If none, the follow-up is treated as a normal single-signal `OPEN` (v1.0 behavior preserved).
- **D-06:** Correlation is one-to-one: once a text-only signal is paired with a follow-up, it cannot be re-paired. A second follow-up for the same orphan is treated as an independent signal.
- **D-07:** Correlation metadata stored on `staged_entries.signal_id` (the originating text-only signal's id) — stages inherit the parent signal's identity.

**Orphan safety (Pitfall 1)**
- **D-08:** Text-only stage-1 open **always submits a non-zero SL** computed from `AccountSettings.default_sl_pips`. A `sl=0.0` submit is a hard failure; signal is rejected with a logged reason. Single most important invariant of Phase 6.
- **D-09:** If no follow-up arrives within the correlation window, **no automatic action is taken on the orphan** — the position continues to be protected by the default SL and is managed by the operator like any other single-stage trade.
- **D-10:** Per-account orphan cap reuses existing `AccountSettings.max_open_trades` (per-symbol cap from v1.0). No new `max_orphan_text_only` setting.

**Stage trigger mechanism (STAGE-04)**
- **D-11:** Zone-watcher model. After follow-up correlates and stage 1 is filled, compute `N - 1 = max_stages - 1` equal-width bands across `(zone_low, zone_high)`. Background `_zone_watch_loop` task in `executor.py` polls MT5 price and fires each stage when price first enters its band.
- **D-12:** Equal slices — bands are contiguous equal-width partitions of the declared zone; deterministic from `(zone_low, zone_high, max_stages)`.
- **D-13:** In-zone at follow-up arrival — on follow-up receipt, check current bid/ask vs each band. Any band whose trigger edge price has already crossed — fire that stage immediately at market. Remaining bands arm and wait.
- **D-14:** Cadence — 10s uniform polling for all symbols. Before each `open_order` submission, perform **pre-flight price re-check** — re-fetch bid/ask and verify still within band ± 0.5×band_width tolerance. If outside, skip this tick and re-queue.
- **D-15:** Stage sizing — equal split. At signal receipt, `risk_per_stage = AccountSettings.risk_value / max_stages`. Both `risk_mode="percent"` and `risk_mode="fixed_lot"` split; fixed-lot → each stage gets `fixed_lot / max_stages`.
- **D-16:** Sequence lifetime = stage-1 lifetime. Remaining unfilled stages are cancelled (`status=cancelled_stage1_closed`) when stage 1 exits (SL, TP, or manual close).
- **D-17:** Stage failure handling — a failed stage is marked `status="failed"` with broker reason; the zone-watcher continues arming remaining stages. No retry. No sequence abort.

**Daily-limit + per-symbol cap accounting (Pitfall 3)**
- **D-18:** **1 signal = 1 daily-limit slot.** Only the FIRST successful fill of a `signal_id` increments `daily_stats.trades_count`. Stages 2..N do not increment. Guard is helper `db.mark_signal_counted_today(signal_id, account) -> bool`.
- **D-19:** Per-symbol `max_open_trades` counts each stage. Stages 4–5 with `max_open_trades=3` and `max_stages=5` are marked `status="capped"` at fire time and never submitted.
- **D-20:** Failed stages do not count against daily-limit.

**Safety-hook integration (STAGE-07, STAGE-06, STAGE-05)**
- **D-21:** Kill-switch drain order — `Executor.emergency_close` executes `UPDATE staged_entries SET status='cancelled_by_kill_switch' WHERE status IN ('pending','awaiting_followup','awaiting_zone')` **BEFORE** closing any position. Zone-watcher loop checks `self._trading_paused` INSIDE each per-stage tick — between pre-flight re-check and `open_order` submit.
- **D-22:** `resume_trading()` never un-cancels drained rows. Operator re-creates intent by re-sending the signal.
- **D-23:** Duplicate-direction guard bypass at `trade_manager.py:215` skips rejection iff incoming submission carries a matching `signal_id` to an existing same-direction position on the same symbol.
- **D-24:** Reconnect reconciliation — MT5 order `comment` field = `telebot-{signal_id}-s{stage}`. On reconnect, `_sync_positions` reads `staged_entries` for affected accounts, lists MT5 positions by comment prefix, marks stages `filled` where matching comment exists, marks stages `abandoned_reconnect` for pending rows whose MT5 position is missing AND signal older than `signal.max_age_minutes`.
- **D-25:** Idempotency rule — before a stage submit, query MT5 positions by stage's target comment; if one already exists, mark stage `filled` without resubmitting.

**Per-account settings form (SET-03)**
- **D-26:** `/settings` page renders Basecoat tabs component (one tab per account). Each tab holds form for `risk_mode`, `risk_value`, `max_stages`, `default_sl_pips`, `max_daily_trades`.
- **D-27:** Two-step dangerous-change modal. On Save, a Basecoat modal opens with diff view, dry-run preview, and confirm button.
- **D-28:** Audit-log timeline per account tab driven by Phase-5 `settings_audit` table. Each row has Revert button.
- **D-29:** Server-side hard caps: `0 < risk_value ≤ 5.0` (percent) or `≤ max_lot_size` (fixed_lot), `1 ≤ max_stages ≤ 10`, `1 ≤ default_sl_pips ≤ 500`, `1 ≤ max_daily_trades ≤ 100`.
- **D-30:** "Changes apply to next signal only" copy inline.
- **D-31:** CSRF uses existing HTMX-header pattern.

**Pending-stages panel (STAGE-08)**
- **D-32:** Compact pending-stages table on `/overview` (up to 5 most-recent active sequences) + "View all" link to fuller `/staged` page.
- **D-33:** Columns: account name, symbol, direction, stages filled/total, price target band, live current price + distance-to-next-band, elapsed time.
- **D-34:** Live-refresh pattern — extend existing SSE stream (`dashboard.py:372-396` is the SSE loop; actual endpoint is `/stream` at line 558). Reuses 2s cadence. Fallback to HTMX polling on `/staged`.
- **D-35:** Empty state: "No pending stages — all signals resolved." Basecoat empty-state primitive.
- **D-36:** Cancelled stages shown in a collapsed "Recently resolved" section of `/staged` (not overview).

**Attribution (STAGE-09)**
- **D-37:** `staged_entries` is the attribution table. Columns: `id`, `signal_id`, `stage_number`, `account_name`, `symbol`, `direction`, `zone_low`, `zone_high`, `band_low`, `band_high`, `target_lot`, `snapshot_settings`, `mt5_comment`, `mt5_ticket`, `status`, `created_at`, `filled_at`, `cancelled_reason`.
- **D-38:** No `ALTER TABLE` on v1.0 `trades`. Analytics joins `trades` to `staged_entries` via `mt5_ticket`.
- **D-39:** `staged_entries` DDL lives alongside Phase-5 tables in `db.py::init_schema()` as `CREATE TABLE IF NOT EXISTS`.

### Claude's Discretion

- Exact column types / constraints / indexes for `staged_entries` (composite index on `(status, account_name, signal_id)` is the likely performance win).
- Whether `snapshot_settings` is JSONB or expanded into explicit columns.
- Exact structure of the zone-watcher loop vs reusing `_heartbeat_loop` pattern — recommended new task peer.
- Signal correlator's data structure (in-memory dict vs DB query each time).
- Exact regex / keyword surface for "now" text-only signals — start with `\bnow\b` and extend via `signal_keywords.json`.
- Whether `SignalType.OPEN_TEXT_ONLY` is a distinct enum value or a flag `is_text_only: bool`.
- Dashboard form field ordering inside each settings tab.
- Whether `/staged` is a separate route or a query-string view on the same blueprint.
- Band tolerance constant (0.5×band_width in D-14) — may be `GlobalConfig.zone_band_tolerance_ratio`.

### Deferred Ideas (OUT OF SCOPE)

- Adaptive zone reshape on follow-up update
- Trailing-activation (stage N arms only after stage N-1 fills)
- Per-symbol adaptive cadence (faster polling for XAU/BTC)
- MT5 tick streaming
- `max_orphan_text_only` dedicated cap
- Signal-specified per-stage prices / sizing
- Auto-close watchdog on orphan text-only
- `trade_stages` analytics view / denormalized column on `trades`
- Per-source signal cancel button in settings page
- Bulk settings apply / copy-from-account / diff-from-seed view
- SSE `asyncio.Event` acceleration on kill-switch state change

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STAGE-01 | Parser recognises text-only "now" signals, emits distinct type | §Text-only signal recognition (Q5) + D-01/D-02 |
| STAGE-02 | Text-only opens exactly 1 market position per account with non-zero default SL | §Orphan SL invariant + D-08 (sl=0.0 hard-reject in `_execute_open_on_account`) |
| STAGE-03 | Correlator pairs follow-up to prior text-only within window | §Signal correlator data structure (Q3) + D-04..D-07 |
| STAGE-04 | Follow-up opens up to max_stages-1 additional positions as price enters zone, respecting caps & kill-switch | §Zone-watcher loop (Q1) + In-zone-at-arrival (Q2) + D-11..D-17 |
| STAGE-05 | Duplicate-direction guard bypassed for same-signal-id stages only | §Pitfall 2 mitigation + D-23 (edit at `trade_manager.py:215`) |
| STAGE-06 | Persisted state reconciled after reconnect — no lost/duplicated stage | §Reconnect reconciliation + D-24/D-25 (comment-based idempotency key) |
| STAGE-07 | Kill-switch drains queue BEFORE closing positions; no fills after trigger | §Kill-switch drain + D-21/D-22 (emergency_close insertion point) |
| STAGE-08 | Dashboard shows live pending-stages panel | §SSE payload extension (Q8) + D-32..D-36 + UI-SPEC |
| STAGE-09 | Every staged fill attributed to originating signal | §staged_entries DDL (Q6) + D-37..D-39 |
| SET-03 | Editable per-account settings form with server-side caps and audit | §Basecoat components (Q7) + §SET-03 flow + D-26..D-31 + UI-SPEC |

## Project Constraints (from CLAUDE.md)

The root `CLAUDE.md` was not found in the telebot project at `/Users/murx/Developer/personal/telebot/CLAUDE.md` during this research session. User-global `~/CLAUDE.md` directives that apply:

- **No emojis in any code or copywriting.** Confirmed by UI-SPEC dimension 1 discipline as well.
- **No Co-Authored-By lines in commit messages.** From user memory.
- **Don't commit prematurely.** From user memory — wait for user to test and confirm.
- **Give VPS/docker commands as text to copy-paste, don't run locally.** From user memory.

Figma-related directives from `~/CLAUDE.md` do not apply to this phase (no Figma assets in Phase 6; UI is HTMX/Jinja/Basecoat per UI-SPEC).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Text-only signal recognition | Parser (`signal_parser.py`) | — | Per D-03 correlation happens after parse; parser stays focused on regex |
| Two-signal correlation | TradeManager layer (correlator owned by `trade_manager.py` or new `signal_correlator.py`) | DB (`staged_entries.signal_id` is the persisted attribution key per D-07) | In-memory window lookup is cheap; DB stores the final pair |
| Stage-band computation | TradeManager at follow-up receipt | — | Deterministic from `(zone_low, zone_high, max_stages)` — pure function |
| Stage-fire decision (zone watch) | Executor (`_zone_watch_loop`) | — | Peer to `_heartbeat_loop` / `_cleanup_loop`; owns `_trading_paused`, `_reconnecting` state |
| Idempotent submit | TradeManager `_execute_open_on_account` (stage-aware extension) | MT5 connector (`comment` field) | D-24 comment key is broker-observable; pre-submit check is in executor tier |
| Kill-switch drain | Executor (`emergency_close`) | DB helper (`drain_staged_entries_for_kill_switch`) | State change owned by Executor; DB write is the atomic drain |
| Reconnect reconciliation | Executor (`_sync_positions` extension) | DB + MT5 position list | Existing hook point; extends rather than replaces |
| SettingsStore snapshot | SettingsStore `snapshot()` call at signal receipt | DB (JSONB column on `staged_entries`) | Phase 5 D-32 delivered the cheap copy; Phase 6 persists it |
| Settings form | Dashboard (`/settings` POST) + Templates + SettingsStore | DB (`account_settings` + `settings_audit`) | Server-side validation + audit is the safety layer |
| Pending-stages panel | Dashboard SSE payload (`/stream`) + HTMX partial | DB query (`get_pending_stages`) | Reuses existing SSE transport; no second channel |

## Standard Stack

### Core

Phase 6 adds **zero new Python dependencies**. Every stack element is already in the v1.0+v1.1 tree.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12 (codebase) | Runtime | v1.0 base; `asyncio.Task` peer pattern already in use in `executor.py` [VERIFIED: executor.py:37-38, 59-60] |
| asyncpg | already in tree | DB pool | Used throughout `db.py`; `staged_entries` DDL lives alongside existing tables [VERIFIED: db.py:168-209] |
| FastAPI + Jinja + HTMX 2.0.4 | already vendored | Dashboard routes + partials | Same pattern as existing `/partials/positions`, `/partials/overview` [VERIFIED: dashboard.py:363-380] |
| Starlette SSE (`StreamingResponse`) | already in tree | Live pending-stages payload | Existing `/stream` endpoint at `dashboard.py:558-582` — extend payload, don't add a second transport [VERIFIED: dashboard.py:558-582] |
| Basecoat UI | 0.3.3 (vendored) | Tabs, dialog, table, empty-state | Vendored Phase 5 D-02 at `static/vendor/basecoat/basecoat.css` + `basecoat.min.js` [VERIFIED: `ls static/vendor/basecoat/` this session] |
| Tailwind CSS (standalone CLI) | v4.2.2 | Styling | Phase 5 D-04-REVISED — v4 resolves `@import` natively, required by Basecoat 0.3.3 |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `argon2-cffi` | Phase 5 dep | Password hashing | Not used in Phase 6 directly, but `_verify_auth` gate is already in place [VERIFIED: dashboard.py:79-100] |
| `itsdangerous` / `SessionMiddleware` | Phase 5 dep | Session cookies | Same — all Phase 6 routes sit behind `Depends(_verify_auth)` |
| pytest + pytest-asyncio | dev-only | Integration test harness for stage battery | Existing async-test fixture pattern (`@pytest.mark.asyncio` + session-scoped event loop) per codebase/TESTING.md |

### Alternatives Considered

| Instead of | Could Use | Tradeoff | Why Rejected |
|------------|-----------|----------|--------------|
| `_zone_watch_loop` in `executor.py` | Second process / worker | "Cleaner separation" | Would need IPC to read `_trading_paused`, `_reconnecting` — four booleans do not justify a message bus (ARCHITECTURE.md AP-1). Reject. |
| In-memory correlator dict | DB query on every follow-up | Simpler persistence story, crash-safe | Correlator lookup is hot-path (every signal); 10-minute in-memory window is trivial. DB-query fallback is fine for the orphan-lookup on follow-up arrival, not for continuous polling. **Recommend hybrid: in-memory dict keyed by `(symbol, direction)` → list of pending text-only signal_ids with `created_at`; evict on pair-up or window-expiry. DB is the durable record via `signals` + `staged_entries.signal_id`.** |
| JSONB `snapshot_settings` | Expanded columns | JSONB leaner (one column); expanded queryable without jsonpath | **Recommend JSONB.** Queries on snapshot values are not a hot path; analytics joins use `mt5_ticket` per D-38. JSONB keeps the schema compact and future-proofs adding fields to `AccountSettings` without another DDL change. |
| New `SignalType.OPEN_TEXT_ONLY` enum value | `is_text_only: bool` flag on `SignalAction` | Enum is clearer switch target; flag is additive | **Recommend enum value.** Existing branch-on-type in `trade_manager.py::handle_signal` already uses `if signal.type == SignalType.OPEN` — adding a new enum value is a safer edit than a boolean flag that must be checked inside existing branches. |

**Installation:** No install step. All dependencies present.

**Version verification:** No new packages installed in Phase 6 — nothing to verify against npm/PyPI. Existing stack versions are locked in Phase 5 completion commit.

## Architecture Patterns

### System Architecture Diagram

```
Telegram NewMessage
        │
        ▼
signal_parser.parse_signal(text)
        │
        ├─ _RE_OPEN match (zone+SL+TP)   ──► SignalType.OPEN (follow-up shape)
        ├─ _RE_OPEN_TEXT match (NEW)     ──► SignalType.OPEN_TEXT_ONLY  ← D-01/D-02
        └─ close/modify branches (unchanged)
        │
        ▼
bot.py handler → Executor.is_accepting_signals()  [kill-switch + reconnect gate, unchanged]
        │
        ▼
┌────────────────────────────────────────────────────────────────────┐
│ SignalCorrelator (in-memory, new module or on TradeManager)        │
│   - dict[(symbol, direction)] → [pending_text_only_signals]        │
│   - on OPEN_TEXT_ONLY: record, submit stage 1 via trade_manager    │
│   - on OPEN: lookup window — if match, promote to follow-up;      │
│              else process as v1.0 single-signal OPEN               │
└────────────────────────────────────────────────────────────────────┘
        │ (correlated follow-up path)
        ▼
TradeManager._handle_open (EXTENDED)
        │
        ├─ settings_store.snapshot(account)  ◄── frozen AccountSettings (Phase 5 D-32)
        ├─ Compute N-1 equal bands across zone  ◄── D-11/D-12
        ├─ INSERT staged_entries rows (status='awaiting_zone')
        ├─ In-zone-at-arrival check — see pseudocode below  ◄── D-13
        └─ Fire immediate stages at market; remaining stages armed
        │
        ▼
┌────────────────────────────────────────────────────────────────────┐
│ Executor._zone_watch_loop (NEW — peer to _heartbeat/_cleanup)      │
│   - 10s cadence  ◄── D-14                                         │
│   - SELECT active stages from staged_entries                       │
│   - For each: pre-flight re-check, _trading_paused guard,         │
│                idempotency-comment probe, fire via _execute_open   │
└────────────────────────────────────────────────────────────────────┘
        │
        ▼
mt5_connector.open_order(..., comment=f"telebot-{signal_id}-s{N}")
        │
        ▼
MT5 broker — position filled with idempotency key in comment
        │
        │ (parallel cross-cuts)
        ├── Kill switch: emergency_close drains staged_entries FIRST  ◄── D-21
        ├── Reconnect: _sync_positions reconciles by comment prefix   ◄── D-24
        └── TP1 hit / stage 1 closed: cancel remaining unfilled stages ◄── D-16

Dashboard SSE /stream (existing, payload extended per D-34):
        - positions (existing)
        - accounts (existing)
        - pending_stages (NEW) → STAGE-08 panel
```

### Recommended Project Structure

```
signal_parser.py        # D-01/D-02 — add text-only recognizer
signal_correlator.py    # NEW — in-memory orphan dict + window expiry (recommend separate module)
models.py               # + SignalType.OPEN_TEXT_ONLY; + StagedEntryRecord dataclass (optional)
trade_manager.py        # edit :215 dup-guard bypass; extend _execute_open_on_account for stages
executor.py             # + _zone_watch_loop; extend emergency_close + _sync_positions
settings_store.py       # no change — Phase 5 shipped snapshot()
db.py                   # + staged_entries DDL in init_schema(); + new helpers (see Component Responsibilities)
dashboard.py            # + /settings/{account} POST + /staged GET; extend SSE payload
templates/
  settings.html         # REWRITE: Basecoat tabs + two-step modal + audit timeline
  overview.html         # + {% include "partials/pending_stages.html" %} card
  staged.html           # NEW — full page with collapsed "Recently resolved"
  partials/
    pending_stages.html # NEW — table fragment swapped by SSE
tests/
  test_signal_parser.py            # + text-only class
  test_signal_correlator.py        # NEW — window, one-to-one, eviction
  test_staged_entries.py           # NEW — schema, helpers, snapshot persistence
  test_zone_watcher.py             # NEW — cadence, in-zone-at-arrival, pre-flight
  test_staged_safety.py            # NEW — kill-switch drain, reconnect reconcile, dup-guard, daily-limit
  test_settings_form.py            # NEW — validation caps, audit write, revert path
```

### Pattern 1: `_zone_watch_loop` peer task (answers Q1)

**What:** Background `asyncio.Task` inside `Executor`, created in `start()` alongside `_heartbeat_task` and `_cleanup_task`.
**When to use:** Ownership of all active `staged_entries` polling. Single source of stage-fire decisions.

```python
# executor.py (pseudo-code, grounded in existing _heartbeat_loop pattern
# at executor.py:142-165 [VERIFIED: this session])

async def _zone_watch_loop(self) -> None:
    """Poll MT5 price for each active staged_entry and fire stages when band entered.

    Cadence: D-14 uniform 10s. Cross-cuts:
      - D-21 kill-switch: checked INSIDE per-stage tick, between pre-flight and submit
      - D-25 idempotency: probe MT5 by target comment before any submit
      - Pitfall 6: pre-flight price re-check with ±0.5×band_width tolerance
    """
    while True:
        try:
            await asyncio.sleep(10)  # D-14 cadence
            if self._trading_paused:
                continue  # loop-entry guard (first line of defense)

            rows = await db.get_active_stages()  # status IN ('awaiting_zone')
            # Group by (account_name, symbol) to dedupe get_price calls
            by_pair: dict[tuple[str, str], list[dict]] = {}
            for r in rows:
                by_pair.setdefault((r["account_name"], r["symbol"]), []).append(r)

            for (acct_name, symbol), stages in by_pair.items():
                if acct_name in self._reconnecting:
                    continue  # account-level reconnect gate

                connector = self.tm.connectors.get(acct_name)
                if not connector or not connector.connected:
                    continue

                price_data = await connector.get_price(symbol)
                if price_data is None:
                    continue
                bid, ask = price_data

                for stage in stages:
                    if self._trading_paused:
                        break  # D-21 INNER guard — can't race kill-switch window

                    direction = stage["direction"]
                    current = bid if direction == "sell" else ask
                    band_low = stage["band_low"]
                    band_high = stage["band_high"]

                    if not _price_in_band(current, band_low, band_high, direction):
                        continue

                    # D-25: idempotency probe — if MT5 already holds a
                    # position with our target comment, mark filled without submit
                    target_comment = stage["mt5_comment"]  # telebot-{sid}-s{N}
                    existing = await connector.get_positions(symbol)
                    if any(p.comment == target_comment for p in existing):
                        await db.update_stage_status(
                            stage["id"], "filled",
                            mt5_ticket=_ticket_for_comment(existing, target_comment),
                        )
                        continue

                    # Pre-flight re-check (Pitfall 6 / D-14)
                    recheck = await connector.get_price(symbol)
                    if recheck is None:
                        continue
                    rbid, rask = recheck
                    rcurrent = rbid if direction == "sell" else rask
                    tolerance = 0.5 * (band_high - band_low)
                    if not (band_low - tolerance <= rcurrent <= band_high + tolerance):
                        continue  # price moved out — skip this tick, re-queue next

                    if self._trading_paused:
                        break  # last chance before submit

                    # Daily-limit aware — D-18 helper decides whether to increment
                    await self._fire_stage(stage, rcurrent)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Zone watch loop error: %s", exc)
            await asyncio.sleep(30)


def _price_in_band(current: float, low: float, high: float, direction: str) -> bool:
    """BUY: fire when current <= high (price dropped into band).
    SELL: fire when current >= low (price rose into band).

    Edge case: current exactly at boundary counts as in-band (matches v1.0
    is_price_in_buy_zone / is_price_in_sell_zone at trade_manager.py:61-68).
    """
    if direction == "buy":
        return current <= high
    return current >= low
```

**Lifecycle:**
- Created in `Executor.start()` alongside `_heartbeat_task` and `_cleanup_task`.
- Cancelled in `Executor.stop()` alongside them (existing cancel-and-await pattern at `executor.py:73-79` [VERIFIED]).

### Pattern 2: In-zone-at-arrival (answers Q2)

**What:** On follow-up arrival, before arming the watcher, check which bands are already crossed and fire those stages immediately.

```python
# trade_manager.py (new helper called from _handle_open when correlated)

def compute_bands(zone_low: float, zone_high: float, max_stages: int, direction: str) -> list[tuple[float, float]]:
    """Partition zone into max_stages-1 equal-width contiguous bands.

    Stage 1 is already filled at follow-up arrival (it fired on the text-only).
    Remaining N-1 stages sit in these bands.

    For a BUY, lower prices are "deeper in zone" (better entries), so bands
    are ordered from zone_high → zone_low (stage 2 highest, stage N lowest).
    For a SELL, higher prices are deeper (better entries), so bands are
    ordered zone_low → zone_high (stage 2 lowest, stage N highest).

    Edge case zone_low == zone_high (degenerate zero-width zone):
      - Treat as single-band: all remaining stages share the same (low, high) point.
      - Per D-13 "trigger edge already crossed" logic, a BUY fires all stages
        the moment current <= zone_high (= zone_low); a SELL likewise.
      - Alternative is to reject at correlation time — NOT chosen, because
        zone-width=0 is a legitimate signal shape (single-price entry, v1.0
        handles it at _RE_OPEN_SINGLE, signal_parser.py:41-46 [VERIFIED]).
    """
    if max_stages <= 1:
        return []
    n = max_stages - 1
    width = (zone_high - zone_low) / n if n > 0 else 0.0
    bands = []
    for k in range(n):
        lo = zone_low + k * width
        hi = zone_low + (k + 1) * width
        bands.append((lo, hi))
    if direction == "buy":
        # deepest (closest to zone_low) fires LAST → reverse so index 0 = stage 2
        return list(reversed(bands))
    return bands  # SELL: lowest band (zone_low..zone_low+w) fires at stage 2


async def fire_in_zone_at_arrival(
    self, signal, signal_id, acct, connector, bands, snapshot, current_price,
) -> list[dict]:
    """D-13: fire stages whose trigger edge is already crossed; arm the rest.

    Iterate bands in fire-order (stage 2 → stage N). For each band:
      BUY: band is crossed if current_price <= band.high
      SELL: band is crossed if current_price >= band.low
    Fire crossed bands immediately (at market, with pre-flight re-check per D-14
    and kill-switch inner-guard per D-21). Remaining bands insert as
    status='awaiting_zone' rows for _zone_watch_loop to handle.
    """
    results = []
    for stage_idx, (lo, hi) in enumerate(bands, start=2):  # stage_number = 2..N
        crossed = (signal.direction == Direction.BUY and current_price <= hi) or \
                  (signal.direction == Direction.SELL and current_price >= lo)

        mt5_comment = f"telebot-{signal_id}-s{stage_idx}"
        row_id = await db.create_staged_entry(
            signal_id=signal_id, stage_number=stage_idx, account_name=acct.name,
            symbol=signal.symbol, direction=signal.direction.value,
            zone_low=signal.entry_zone[0], zone_high=signal.entry_zone[1],
            band_low=lo, band_high=hi,
            target_lot=snapshot.risk_value / snapshot.max_stages if snapshot.risk_mode == "fixed_lot"
                       else None,  # percent mode: computed at fire time from snapshot
            snapshot_settings=json.dumps(dataclasses.asdict(snapshot)),
            mt5_comment=mt5_comment,
            status="awaiting_zone",
        )

        if crossed:
            # Fire immediately — same path as _zone_watch_loop per-stage tick,
            # centralised in _fire_stage (shared with the loop)
            results.append(await self._fire_stage_by_id(row_id))
        # else: armed for the watcher

    return results
```

**Edge cases the planner's verification must cover:**
- (a) Price exactly at `band_high` for BUY → crossed (matches `<=` semantics of `is_price_in_buy_zone`).
- (b) Price past far edge (e.g. BUY with current < zone_low) → ALL remaining bands crossed → fire stages 2..N **in order**, each with its own pre-flight re-check (so if price snaps back mid-loop, later stages will no-op).
- (c) `zone_low == zone_high` → bands degenerate; all N-1 stages fire at once under crossed semantics (see compute_bands docstring).
- (d) Follow-up arrives for a text-only that already exited stage 1 (SL/TP hit between text and follow-up) → correlator finds the match (D-05) but `staged_entries` stage-1 row is already closed → per D-16 sequence lifetime, the follow-up should NOT re-arm new stages. **This is a subtle case.** Recommend: at follow-up receipt, before arming stages, verify stage-1 position is still open. If not, log "orphan follow-up — stage 1 already resolved" and do not arm. **Planner: add explicit test case.**

### Pattern 3: Signal correlator (answers Q3)

**Recommendation: in-memory dict, DB is the durable persisted record via `staged_entries.signal_id`.**

**Rationale:**
- Correlation is a hot path: every inbound `OPEN` signal consults the correlator to decide "standalone or follow-up?"
- Window is 10 minutes → at most ~a dozen pending orphans at any time. Memory footprint is negligible.
- Crash-safe fallback: on bot restart, the in-memory dict is empty. That's acceptable — the only orphans that could stall a correlation are those where (a) the text-only fired within the last 10 minutes AND (b) the follow-up arrived during/after restart. In that race, the follow-up is treated as independent (per D-05 "if no match, behave as v1.0 single-signal `OPEN`"), which is the safe fallback. Log a WARNING when this path executes so operators see it.

```python
# signal_correlator.py (NEW module)

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

@dataclass
class OrphanEntry:
    signal_id: int
    created_at: float  # time.monotonic()

class SignalCorrelator:
    """Thread-safe in-memory correlator for text-only → follow-up pairing.

    D-04: window = GlobalConfig.correlation_window_seconds (default 600)
    D-05: most-recent match wins
    D-06: one-to-one — pop on pair
    """
    def __init__(self, window_seconds: int = 600):
        self._window = window_seconds
        self._orphans: dict[tuple[str, str], list[OrphanEntry]] = {}
        self._lock = asyncio.Lock()

    async def record_orphan(self, symbol: str, direction: str, signal_id: int) -> None:
        async with self._lock:
            key = (symbol, direction)
            self._orphans.setdefault(key, []).append(
                OrphanEntry(signal_id=signal_id, created_at=time.monotonic())
            )

    async def try_pair(self, symbol: str, direction: str) -> Optional[int]:
        """Find most-recent orphan within window, pop it, return signal_id.
        Returns None if no match. Also evicts stale entries on every call.
        """
        async with self._lock:
            key = (symbol, direction)
            bucket = self._orphans.get(key, [])
            now = time.monotonic()
            # Evict expired orphans
            bucket = [e for e in bucket if (now - e.created_at) <= self._window]
            self._orphans[key] = bucket
            if not bucket:
                return None
            # Most-recent wins (D-05)
            entry = bucket.pop()  # last = most recent
            return entry.signal_id
```

Owned by `bot.py::main`, passed into the trade-manager signal-intake path. No DB I/O on the hot path.

### Pattern 4: MT5 comment-based idempotency (answers Q4)

**Format:** `telebot-{signal_id}-s{stage_number}` where `signal_id` is the Postgres SERIAL from `signals.id`.

**Length check:** MT5 comment field is traditionally capped at 32 chars (broker-dependent; some allow up to 31 usable after null terminator). With `signal_id` ≤ 10 digits (10-billion rows) and `stage_number` ≤ 2 digits (max_stages capped at 10 per D-29), the longest string is `telebot-9999999999-s10` = 22 chars. **Safe with margin.** [VERIFIED: arithmetic this session]

**Round-trip verification status:**

In this codebase, MT5 operations go through `mt5_connector.py::MT5RestConnector` which calls an HTTP bridge via `POST /api/v1/order` (line 669) passing `comment` in the JSON body, and reads positions via `GET /api/v1/positions` (line 641) parsing `p.get("comment", "")` (line 654) [VERIFIED: mt5_connector.py:640-692 this session]. The DryRunConnector also round-trips comment through `_fake_positions` state [VERIFIED: mt5_connector.py:276, 286, 343, 483].

**What this proves:** The project's own REST bridge has a `comment` field in both open-order POST and position-list GET. Both paths in the Python connector preserve the string.

**What this does NOT prove:** Whether the bridge server process (running under Wine MT5 or dry-run) actually forwards `comment` to MT5's `order_send` request and reads it back from `mt5.positions_get()`. The MT5 Python API (`MetaTrader5` pip module) `.positions_get()` returns a namedtuple with a `comment` attribute; in practice comment round-trips are well-established (MT5's own EA examples use the comment field for idempotency). However this session has not read the bridge server source to verify it reads `position.comment` back into the REST response.

**[ASSUMED]** MT5 bridge `GET /api/v1/positions` returns the comment originally submitted at `POST /api/v1/order`.

**Required integration test in the plan:** Submit a single order via `connector.open_order(symbol="XAUUSD", ..., comment="telebot-test-s1")`, then call `connector.get_positions("XAUUSD")` and assert the returned Position's `.comment == "telebot-test-s1"`. Add this as the first test in `test_staged_safety.py` — if it fails, D-24/D-25 design must be revisited before further plan work. This test runs against DryRunConnector in CI (comment already known to round-trip locally [VERIFIED]) and should be re-run manually against the real MT5 bridge during UAT.

### Pattern 5: Text-only signal parser (answers Q5)

Current state [VERIFIED: signal_parser.py:32-46 this session]:
- `_RE_OPEN` (line 32): `(?P<symbol>gold|xauusd|xau/?usd|xau)\s+(?P<direction>buy|sell)\s+(?:now\s+)?(?P<price1>\d+(?:\.\d+)?)\s*[-–—]\s*(?P<price2>\d+(?:\.\d+)?)` — requires a zone.
- `_RE_OPEN_SINGLE` (line 41): requires a single price. `"now"` is optional in both.

**"Gold buy now"** (no digits) matches NEITHER regex. This is the gap Phase 6 fills.

```python
# signal_parser.py — new regex + priority branch

# Place AFTER _RE_OPEN_SINGLE in the dispatcher to preserve v1.0 semantics:
# existing zone + single-price recognisers still match their shapes first.
_NOW_WORDS = r"(?:now|asap|immediate)"   # D-02 keyword surface; extensible via signal_keywords.json
_RE_OPEN_TEXT_ONLY = re.compile(
    r"(?P<symbol>gold|xauusd|xau/?usd|xau)\s+"
    r"(?P<direction>buy|sell)\s+"
    rf"{_NOW_WORDS}\b",
    re.IGNORECASE,
)


def parse_signal(text: str) -> SignalAction | None:
    # ... existing priority 1-7 branches (close, partial, SL-BE, SL update,
    # TP update, _RE_OPEN, _RE_OPEN_SINGLE) unchanged ...

    # ── 8. Text-only "now" signal (NEW, D-01/D-02) ─────────────────
    text_only_match = _RE_OPEN_TEXT_ONLY.search(stripped)
    if text_only_match and not _RE_PRICE_LIKE.search(stripped):
        # Guard: no price-like numbers anywhere in the message.
        # Disambiguates "Gold buy @ 2000 now" (matches _RE_OPEN_SINGLE first, so
        # never reaches here) from "Gold buy now" (no digits → reaches here).
        return SignalAction(
            type=SignalType.OPEN_TEXT_ONLY,
            symbol=_resolve_symbol(text_only_match.group("symbol")),
            direction=Direction.BUY if text_only_match.group("direction").lower() == "buy" else Direction.SELL,
            raw_text=text,
            # entry_zone, sl, tps intentionally None — downstream branches on .type
        )

    # Not a recognized signal (existing behavior)
    if is_signal_like(stripped):
        logger.warning("Signal-like text not parsed: %.200s", stripped)
    return None
```

**Why the `_RE_PRICE_LIKE` guard:** D-02 says "absence of any price digits confirms text-only." `_RE_PRICE_LIKE` already exists at signal_parser.py:114 as `\b\d{3,5}(?:\.\d{1,2})?\b`. Using it as a negative guard ensures:
- "Gold buy @ 2000 now" → has `2000` → `_RE_OPEN_SINGLE` catches it at priority 7, never reaches priority 8.
- "Gold buy now" → no price-like digits → falls through to priority 8, matches text-only.
- "Gold buy soon 2000 - 2010" → `_RE_OPEN` catches it at priority 6.

**SignalAction carries `entry_zone=None, sl=None, target_tp=None`** for OPEN_TEXT_ONLY (the current dataclass defaults already support this [VERIFIED: models.py:45-50]). Downstream in `trade_manager.py::handle_signal`, a new branch `if signal.type == SignalType.OPEN_TEXT_ONLY: return await self._handle_open_text_only(signal)` fires stage 1 market with default-SL per D-08, no zone computation.

### Pattern 6: `staged_entries` DDL (answers Q6)

```sql
CREATE TABLE IF NOT EXISTS staged_entries (
    id                  SERIAL          PRIMARY KEY,
    signal_id           INTEGER         NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    stage_number        INTEGER         NOT NULL CHECK (stage_number >= 1 AND stage_number <= 10),
    account_name        TEXT            NOT NULL REFERENCES accounts(name) ON DELETE CASCADE,
    symbol              TEXT            NOT NULL,
    direction           TEXT            NOT NULL CHECK (direction IN ('buy', 'sell')),
    zone_low            DOUBLE PRECISION,       -- NULL for text-only stage 1 (no zone)
    zone_high           DOUBLE PRECISION,       -- NULL for text-only stage 1
    band_low            DOUBLE PRECISION,       -- NULL for stage 1 (fires at market, no band)
    band_high           DOUBLE PRECISION,       -- NULL for stage 1
    target_lot          DOUBLE PRECISION,       -- NULL for percent-mode (computed at fire time from snapshot)
    snapshot_settings   JSONB           NOT NULL,        -- D-32 lineage + Claude's Discretion: JSONB
    mt5_comment         TEXT            NOT NULL UNIQUE, -- telebot-{signal_id}-s{stage_number}
    mt5_ticket          BIGINT,                 -- NULL until filled; set on D-25 idempotency check or _fire_stage success
    status              TEXT            NOT NULL DEFAULT 'awaiting_zone' CHECK (status IN (
        'pending',                  -- created, not yet submitted (stage 1 text-only pre-submit)
        'awaiting_followup',        -- stage 1 filled; no follow-up yet (orphan state)
        'awaiting_zone',            -- armed; zone-watcher will fire
        'filled',                   -- MT5 confirmed
        'failed',                   -- broker rejected / invalid volume (D-17 — no retry)
        'capped',                   -- blocked by per-symbol max_open_trades (D-19)
        'cancelled_by_kill_switch', -- D-21 / D-22 terminal
        'cancelled_stage1_closed',  -- D-16 sequence lifetime
        'abandoned_reconnect'       -- D-24 reconcile found MT5 missing + signal stale
    )),
    cancelled_reason    TEXT,                   -- free-form, for "Recently resolved" display
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    filled_at           TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Hot-path indexes
CREATE INDEX IF NOT EXISTS idx_staged_entries_active
    ON staged_entries(account_name, symbol) WHERE status = 'awaiting_zone';
-- Reasoning: _zone_watch_loop does `SELECT WHERE status='awaiting_zone'` every
-- 10s — partial index keeps it O(active) not O(total).

CREATE INDEX IF NOT EXISTS idx_staged_entries_signal
    ON staged_entries(signal_id);
-- Reasoning: D-18 mark_signal_counted_today + D-16 cancel-on-stage1-close both
-- query by signal_id.

CREATE INDEX IF NOT EXISTS idx_staged_entries_reconcile
    ON staged_entries(account_name, status)
    WHERE status IN ('awaiting_zone', 'pending', 'awaiting_followup');
-- Reasoning: D-24 reconnect reconciliation queries by account + active statuses.

-- The UNIQUE constraint on mt5_comment enforces idempotency at the DB level
-- (D-25 — if a retry tries to submit the same comment, INSERT fails fast).
```

**Column-type rationale:**
- `DOUBLE PRECISION` for price/lot fields matches existing v1.0 `trades.entry_price`, `trades.sl`, `trades.tp` [VERIFIED: db.py:97-117 via grep in research].
- `JSONB` for `snapshot_settings` per Claude's Discretion — leaner than 7 explicit columns; analytics joins use `mt5_ticket` not snapshot values (D-38); future `AccountSettings` field additions don't require DDL.
- `mt5_comment UNIQUE` is the D-25 safety net — if a race slips past the in-memory probe, the DB rejects the duplicate INSERT.
- `cancelled_reason TEXT` (free-form) is for the STAGE-08 "Recently resolved" UI copy per UI-SPEC; not parsed by code.
- `ON DELETE CASCADE` on `signal_id` and `account_name` FKs matches Phase-5 `account_settings` convention [VERIFIED: db.py:169].

### Pattern 7: Basecoat v0.3.3 components (answers Q7)

Basecoat 0.3.3 is already vendored at `static/vendor/basecoat/` [VERIFIED: `ls` this session]. All component APIs used in UI-SPEC are confirmed present in the repo:

| Component | Class / Markup | Required JS init? |
|-----------|----------------|-------------------|
| Tabs | `<div role="tablist">` + `<button role="tab">` + `<div role="tabpanel">` | Yes — Basecoat JS binds click handlers. Phase 5 UI-05 shipped `htmx_basecoat_bridge.js` to re-init after HTMX swaps [per Phase 5 D-08]. Confirmed needed here. |
| Dialog (modal) | `<dialog class="dialog">` + `role="dialog"` + `data-state` | Yes — focus trap + Esc handler. Same re-init bridge applies. |
| Table | native `<table>` styled via `_compat.css` | No — pure CSS. |
| Empty state | `<div class="empty-state">` | No — pure CSS primitive per UI-SPEC. |

**[ASSUMED]** The exact Basecoat init API call signature (`window.basecoat.init(element)` vs named component initializers) — Phase 5's `htmx_basecoat_bridge.js` already solved this. Plan should reference the existing bridge file and not re-invent the re-init path.

**SSR-friendly pattern:** All these components are server-rendered HTML + declarative `role=` / `data-` attributes; JS only wires interactivity. No hydration step, no client-side state. Matches HTMX/Jinja substrate.

UI-SPEC has already locked the visual and interaction design — research should not second-guess. Confirmation: the APIs UI-SPEC relies on (Basecoat tabs, dialog, empty-state) are the ones vendored in v0.3.3 at `static/vendor/basecoat/`. **No blockers for the planner.**

### Pattern 8: SSE payload extension (answers Q8)

**Current state** [VERIFIED: dashboard.py:558-582 this session]:
```python
@app.get("/stream")
async def sse_stream(request: Request, user: str = Depends(_verify_auth)):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                positions = await _get_all_positions()
                accounts = await _get_accounts_overview()
                data = json.dumps({
                    "positions": positions,
                    "accounts": accounts,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                yield f"data: {data}\n\n"
            except Exception as exc:
                logger.error("SSE error: %s", exc)
            await asyncio.sleep(2)
    return StreamingResponse(..., headers={"X-Accel-Buffering": "no", ...})
```

**Extension pattern (non-breaking):**
```python
# dashboard.py edited SSE generator
pending_stages = await db.get_pending_stages(limit=50)  # fetch active + recently cancelled
data = json.dumps({
    "positions": positions,       # unchanged
    "accounts": accounts,         # unchanged
    "pending_stages": pending_stages,  # NEW — list[dict] per UI-SPEC columns
    "timestamp": datetime.now(timezone.utc).isoformat(),
})
```

**Why this doesn't break existing consumers:** JSON consumers ignore unknown keys. The existing client-side SSE handler (in `templates/base.html` or equivalent) that reads `positions` and `accounts` is unchanged. The STAGE-08 panel's `sse-swap="pending_stages"` attribute per UI-SPEC binds to the new key — if missing, the swap is a no-op (empty swap).

**Client-side event name:** UI-SPEC calls for `sse-swap="pending_stages"`. Starlette SSE default event name is `message`; for named events the generator must yield `event: pending_stages\ndata: {...}\n\n`. **Recommend:** emit a single unnamed message with the full payload (current pattern), and have the STAGE-08 partial use HTMX `sse-swap="message"` + a JS extractor. **OR** split into named events. Planner: pick one — I recommend single-message-with-JSON for simplicity; UI-SPEC's `sse-swap="pending_stages"` attribute should be interpreted as a pseudo-target. Confirm with UI-checker during plan.

**Kill-switch responsiveness (Pitfall 18):** The 2s SSE cadence means up to 2 seconds of UI lag between operator clicking kill-switch and the panel updating to show "cancelled_by_kill_switch" status. Per CONTEXT.md deferred ideas: "SSE `asyncio.Event` acceleration on kill-switch state change (Pitfall 18 extra hardening) — defer; 2s cadence is acceptable for v1.1." **Document this gap in the STAGE-08 plan.** Mitigation via optimistic UI on the kill-switch button (already in place in v1.0 per Pitfall 18 mitigation) keeps operator feedback instant even if panel updates lag.

### Pattern 9: SET-03 settings form flow

**Verified Phase-5 infrastructure:**
- `SettingsStore.effective(name) -> AccountSettings` [VERIFIED: settings_store.py:70-78]
- `SettingsStore.update(account, field, value, actor="admin")` writes DB + audit + refreshes cache [VERIFIED: settings_store.py:87-92]
- `settings_audit` table schema `(timestamp, account_name, field, old_value, new_value, actor)` [VERIFIED: db.py:184-197]
- Existing HTMX-header CSRF pattern via `_verify_csrf` [per D-31, confirmed in Phase 5 CONTEXT]

**Route additions:**
- `GET /settings` — render tabs + active tab's form + audit log for active tab's account
- `POST /settings/{account}` — validate; if valid, render confirmation modal partial with diff + dry-run; if invalid, re-render form with 422 field errors
- `POST /settings/{account}/confirm` — persist via `SettingsStore.update` (which writes audit), return tab re-rendered with new audit row at top
- `POST /settings/{account}/revert?audit_id={id}` — same modal flow pre-populated with reverse diff

**Dry-run preview computation:** Given the pending edit, compute the lot size a "typical signal" would get. "Typical" is ambiguous — recommend the planner define it as: assume `balance=10000` (or fetch live balance from first connected account), `sl_distance=100 pips for XAUUSD`, then run `calculate_lot_size` with the proposed settings. Display as "Next typical signal would size X lots at Y% risk" per D-27.

### Anti-Patterns to Avoid

- **Spawning a second process for the zone watcher** (ARCHITECTURE AP-1) — the `_trading_paused` and `_reconnecting` state is in Executor memory; cross-process reads would require message-bus infrastructure for 4 booleans. Stay in-process.
- **Mutating `staged_entries.target_lot` after INSERT** — Pitfall 7. Once a stage row exists, its lot is frozen from the snapshot. Settings edits never retroactively rewrite pending rows.
- **Counting "awaiting_zone" rows toward max_open_trades** — D-19 says per-symbol cap counts ACTUAL filled positions (real MT5 slots). Stages in `awaiting_zone` state are not yet positions. The cap check at fire time (in `_fire_stage`) uses `connector.get_positions(symbol)` length, NOT a DB count.
- **Auto-retrying failed stages** — D-17 forbids it. A broker reject is terminal (`status='failed'`). v1.0 reconnect machinery already handles transient connector failures; stage-level retry would double-book fills.
- **Skipping the inner `_trading_paused` guard** — Pitfall 4. Without the inner check (between pre-flight and submit), a kill-switch hit during the 100ms between "pre-flight OK" and "open_order returned" leaves a position that the kill-switch drain didn't see.
- **Using a universal `ALTER TABLE` anywhere** — Pitfall 17 / D-38 / D-39. Phase 6 adds exactly one new table (`staged_entries`) via `CREATE TABLE IF NOT EXISTS`. No modifications to `signals`, `trades`, `daily_stats`, `accounts`, `account_settings`, `settings_audit`, `pending_orders`, `failed_login_attempts`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Settings in-memory cache | New cache class | `SettingsStore.effective()` / `SettingsStore.snapshot()` | Phase 5 shipped it [VERIFIED: settings_store.py:70-92] |
| Audit-log writes | Direct INSERT into `settings_audit` | `SettingsStore.update()` | The method's write-through pattern writes both audit + cache refresh atomically [VERIFIED: settings_store.py:87-92 + db.py:620-630] |
| Session auth gate | New middleware | Existing `_verify_auth` dep at `dashboard.py:79-100` | Already wired, already CSRF-gated for HTMX |
| HTMX CSRF | New token scheme | Existing `_verify_csrf` with `hx-request` header | Phase 5 D-31 locked this |
| Zone-band partition math | Custom interpolation library | 5-line `compute_bands` pure function (see Pattern 2) | Deterministic from 3 integers |
| SSE transport | Second stream / WebSocket | Existing `/stream` endpoint | ARCHITECTURE.md: extend payload, don't add transport |
| Correlator persistence | Redis / external KV | In-memory dict (see Pattern 3) | 10-min window, single process — DB fallback on restart is acceptable |

**Key insight:** Phase 5 already paid the infrastructure cost. Phase 6 is domain logic on top. Any new helper module/class that duplicates existing functionality is a red flag.

## Runtime State Inventory

**Not applicable to Phase 6.** This is a greenfield feature phase (new table, new code paths, new UI), not a rename/refactor. No pre-existing runtime state is being renamed or migrated; there are no stored strings, live-service configs, OS-registered tasks, env-var name changes, or build-artifact stale states to audit. The step is included below for completeness with explicit "None" entries:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — `staged_entries` is a new table; `signals.id` already exists and is only being consumed (FK). | None |
| Live service config | None — no external service config lives outside git for this feature. No n8n/Datadog/Cloudflare involved. | None |
| OS-registered state | None — no new pm2 processes, Task Scheduler tasks, systemd units. Bot runs in existing Docker container. | None |
| Secrets / env vars | New optional env: `CORRELATION_WINDOW_SECONDS` (defaults to 600). Optional. No renames. | Document in .env.example; no rotation needed |
| Build artifacts | None — no new compiled binaries, no new pip packages, no Docker base-image changes. | None |

## Common Pitfalls

### Pitfall cross-check (cross-references PITFALLS.md items 1–7, 17, 18)

| PITFALLS.md # | Title | D-## that mitigates | Residual risk plans MUST test for |
|---------------|-------|---------------------|-----------------------------------|
| 1 | Text-only orphan with no SL | D-08 (mandatory default SL), D-10 (reuse `max_open_trades` cap) | Test: `_execute_open_on_account` rejects any `sl=0.0` submit regardless of code path. Test: default_sl_pips = 0 (degenerate config) → bot refuses to fire stage 1 with a clear log, NOT "sl=0.0 silently accepted." |
| 2 | Duplicate-direction guard silently rejects stages 2..N | D-23 (signal-id-aware bypass at `trade_manager.py:215`) | Test: 3-stage signal → all 3 positions open. Test: unrelated same-direction signal on same symbol while stages active → STILL REJECTED. The bypass is signal-id-scoped, NOT blanket. |
| 3 | Daily-limit accounting starves stages | D-18 (1 signal = 1 slot via `mark_signal_counted_today`) | Test: 5-stage signal increments `daily_stats.trades_count` by exactly 1. Test: two correlated text-only+follow-up sequences on same account same day → count = 2. Test: failed stage (D-20) does NOT increment. |
| 4 | Kill switch leaves pending stages | D-21 (drain BEFORE close), D-22 (no un-cancel) + zone-watcher inner guard | Test: kill-switch during `_zone_watch_loop` mid-tick, between pre-flight and submit → NO new positions after kill-switch; drained rows reach `cancelled_by_kill_switch`. Test: `resume_trading()` does NOT re-activate drained rows. |
| 5 | Reconnect duplicates/orphans stages | D-24 (comment-based reconcile), D-25 (pre-submit idempotency probe) | Test: disconnect mid-fire → on reconnect, no duplicate position created. Test: reconcile marks `abandoned_reconnect` only for stages older than `signal.max_age_minutes` with no matching MT5 position. **CRITICAL: verify MT5 bridge round-trips `comment`** (Pattern 4). |
| 6 | Zone watcher cadence fires late / outside zone | D-14 (10s cadence + pre-flight re-check + 0.5×band_width tolerance) | Test: simulate price spike-through-band between ticks — pre-flight re-check catches it and skips. Test: pre-flight tolerance boundary (exactly at ± 0.5× band edge) behaves as documented. |
| 7 | Runtime settings mutation mid-stage | Phase 5 D-32 snapshot + D-30 "next signal only" copy + D-37 `snapshot_settings` JSONB on the stage row | Test: stage 1 fills → edit risk_value → stage 2 fires → stage 2 uses OLD value from `snapshot_settings`, NOT new DB value. |
| 17 | Schema migration without alembic | D-38 (no ALTER trades), D-39 (CREATE IF NOT EXISTS) | Pre-commit lint: grep `ALTER TABLE` in any SQL in repo → fail PR if found. Plan should include this CI check. |
| 18 | SSE vs kill-switch UI race | Accepted per CONTEXT Deferred (2s cadence is acceptable) | Test: documented 2s max UI lag between kill-switch click and panel state update. Mitigation is v1.0 optimistic-UI button state (already in place); no new work, but explicit documentation in STAGE-08 plan that the panel can lag by up to 2 seconds. |

### Detailed pitfall walkthroughs

#### Pitfall P4 (kill-switch drain): order-of-ops is load-bearing

**What goes wrong:** Operator hits kill switch while a 5-stage signal has stages 3–5 queued. If `emergency_close` closes positions first and drains the queue second, the zone-watcher can tick mid-close, pre-flight passes, submits stage 4 at the moment kill-switch is setting `_trading_paused`, and the emergency_close returns having closed 1-2-3 but now position 4 is open.

**How to avoid:**
1. `emergency_close` sets `_trading_paused = True` IMMEDIATELY (already in place per `executor.py:226` [VERIFIED]).
2. Insert the drain call (`await db.drain_staged_entries_for_kill_switch()`) IMMEDIATELY after line 226, BEFORE the `for acct_name, connector in self.tm.connectors.items()` loop that closes positions.
3. `_zone_watch_loop` checks `self._trading_paused` twice: once at loop entry and once inside each per-stage tick (between pre-flight re-check and submit). Both checks are load-bearing.

**Warning sign:** Any test where kill-switch is triggered while stages are queued should assert (a) all active rows are `cancelled_by_kill_switch`, (b) no new MT5 positions exist with a comment matching `telebot-{sid}-s*` that weren't present before the kill-switch, (c) `resume_trading()` does NOT change any cancelled row's status.

#### Pitfall P5 (reconnect idempotency): the `comment` field is the whole story

**What goes wrong:** Bot disconnects mid-submit. The REST POST `/api/v1/order` was accepted by the bridge, MT5 placed the order, the TCP ACK never returned. Bot retries on reconnect → second position opened.

**How to avoid:**
1. Every stage submit builds the comment deterministically: `f"telebot-{signal_id}-s{stage_number}"`.
2. Before any `open_order` call (in both `_fire_stage` and the reconnect-retry path), query `connector.get_positions(symbol)` and scan for a position with matching comment. If present, mark stage `filled` and DO NOT resubmit.
3. The UNIQUE constraint on `staged_entries.mt5_comment` is the DB-level belt-and-suspenders: a second INSERT with the same comment fails loudly.

**Warning sign:** Two MT5 positions exist with the same comment. Any such discovery is a plan-breaker and must alert Discord immediately.

## Code Examples

### Example 1: Extending `emergency_close` for D-21 drain

```python
# executor.py — modification to emergency_close (verified current structure
# at executor.py:221-271 this session)

async def emergency_close(self) -> dict:
    """Kill switch: close all positions, cancel all pending, pause trading.

    D-21: staged_entries queue must be drained BEFORE positions close so the
    zone-watcher cannot race the kill-switch window.
    """
    self._trading_paused = True  # [existing line 226 — keep FIRST]
    logger.warning("KILL SWITCH ACTIVATED — draining staged queue and closing positions")

    # ── D-21: drain the staged queue BEFORE closing positions ──────────
    drained = await db.drain_staged_entries_for_kill_switch()
    logger.info("Kill switch drained %d staged rows", drained)
    if self.notifier:
        await self.notifier.notify_alert(
            f"KILL SWITCH: drained {drained} pending stage(s) before closing positions"
        )

    # ── existing close-positions loop (unchanged) ──────────────────────
    closed_positions = 0
    # ... rest of the existing method unchanged ...
```

### Example 2: Extending `_sync_positions` for D-24 reconciliation

```python
# executor.py — modification to _sync_positions (existing stub at 208-217)

async def _sync_positions(self, acct_name: str, connector) -> None:
    """Full position sync from MT5 after reconnect (REL-02 + D-24).

    D-24 extension: reconcile staged_entries against actual MT5 positions
    by comment prefix. Mark stages filled where a matching comment exists;
    mark stages abandoned_reconnect for pending rows whose MT5 position
    is missing AND signal older than signal.max_age_minutes.
    """
    try:
        positions = await connector.get_positions()
        logger.info("%s: Position sync — %d open position(s)", acct_name, len(positions))

        # D-24: reconcile staged_entries for this account
        active_stages = await db.get_active_stages_for_account(acct_name)
        mt5_comments_by_ticket = {p.ticket: p.comment for p in positions if p.comment}

        for stage in active_stages:
            target_comment = stage["mt5_comment"]
            matching = [t for t, c in mt5_comments_by_ticket.items() if c == target_comment]
            if matching:
                # D-25 idempotency: MT5 already has this stage filled
                await db.update_stage_status(stage["id"], "filled", mt5_ticket=matching[0])
                logger.info("%s: Reconciled stage %s → MT5 ticket #%d",
                            acct_name, target_comment, matching[0])
            else:
                # Stage not on MT5 — check signal age
                signal_age = await db.get_signal_age_minutes(stage["signal_id"])
                max_age = self.cfg.signal_max_age_minutes  # assume exists; else stage_max_age
                if signal_age > max_age:
                    await db.update_stage_status(
                        stage["id"], "abandoned_reconnect",
                        cancelled_reason=f"Signal aged out during reconnect ({signal_age:.0f} min)"
                    )
                    if self.notifier:
                        await self.notifier.notify_alert(
                            f"{acct_name}: stage {target_comment} abandoned after reconnect — signal aged out"
                        )
    except Exception as exc:
        logger.error("%s: Position sync / stage reconcile failed: %s", acct_name, exc)
```

### Example 3: Duplicate-direction guard bypass (D-23) — exact edit at `trade_manager.py:213-217`

```python
# trade_manager.py — BEFORE (lines 213-217 [VERIFIED: this session])

# ── Check duplicate (same direction already open) ───────────────
for pos in positions:
    if pos.direction == signal.direction.value:
        reason = f"Already have a {signal.direction.value} position open on {signal.symbol}"
        return {"account": name, "status": "skipped", "reason": reason}

# trade_manager.py — AFTER (D-23 bypass for same-signal-id sibling stages)

# ── Check duplicate (same direction already open) ───────────────
# D-23: bypass the guard iff this submission carries a signal_id matching
# an existing position's comment (sibling stage of the same sequence).
sibling_comment_prefix = f"telebot-{signal_id}-s"  # parent signal_id of this stage
for pos in positions:
    if pos.direction == signal.direction.value:
        if pos.comment and pos.comment.startswith(sibling_comment_prefix):
            continue  # same-signal sibling — allowed
        reason = f"Already have a {signal.direction.value} position open on {signal.symbol}"
        return {"account": name, "status": "skipped", "reason": reason}
```

Note: the existing method signature of `_execute_open_on_account` accepts `signal_id` already [VERIFIED: trade_manager.py:183-186]. The edit is self-contained.

## State of the Art

| Old Approach (v1.0) | New Approach (v1.1 Phase 6) | When Changed | Impact |
|---------------------|------------------------------|--------------|--------|
| 1 signal = 1 fill | 1 signal = 1..N staged fills | This phase | Daily-limit accounting must become signal-aware (D-18) |
| SL is optional (text-only → sl=0.0 legal) | Non-zero SL mandatory for every fill | This phase | Hard-reject path in `_execute_open_on_account` (D-08) |
| Duplicate-direction guard rejects all same-symbol-same-direction | Guard bypassed for same-signal-id siblings | This phase | D-23 edit at `trade_manager.py:215` |
| `_sync_positions` only logs | `_sync_positions` reconciles `staged_entries` via comment | This phase | D-24 extension |
| `emergency_close` closes positions | `emergency_close` drains staged queue FIRST | This phase | D-21 re-ordering |
| SSE emits {positions, accounts} | SSE emits {positions, accounts, pending_stages} | This phase | D-34 payload extension |
| Settings editable via SQL only | Settings editable via dashboard form (SET-03) | This phase | Phase 5 infra + D-26..D-31 |

**Deprecated/outdated:** None — this phase is purely additive.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | MT5 bridge (both Wine-MT5 production path and DryRun path) round-trips the `comment` field on `GET /api/v1/positions` after it was set in `POST /api/v1/order`. | Pattern 4 (MT5 comment idempotency) | HIGH — if comment does not round-trip, D-24 (reconnect reconciliation) and D-25 (pre-submit idempotency probe) both fail. A stage could be double-filled after reconnect, and the kill-switch drain could miss stages that are already on MT5. **Mitigation:** REQUIRED integration test in the plan that opens an order with `comment="telebot-test-s1"` and asserts the retrieved position's comment matches. Run in CI against DryRunConnector (already [VERIFIED] locally) and in UAT against real MT5 bridge. If UAT fails, halt Phase 6 and investigate bridge server source. |
| A2 | Basecoat v0.3.3 JS init API re-wires components after HTMX swap (via `window.basecoat.init(element)` or equivalent). | Pattern 7 (Basecoat components) | LOW — Phase 5 shipped `htmx_basecoat_bridge.js` for this exact purpose (D-08); any gap would have surfaced in Phase 5 UAT. Mitigation: reuse the existing bridge file. |
| A3 | `signal.max_age_minutes` exists as a `GlobalConfig` field (used by D-24 reconcile logic to decide "abandoned vs still-valid"). | Example 2 (_sync_positions) | LOW — if the field does not exist, add it to `GlobalConfig` with a default of 30 minutes. One-line addition, no cross-cutting impact. |
| A4 | A Postgres `UNIQUE` constraint on `staged_entries.mt5_comment` is enforceable given the deterministic comment format and the D-25 idempotency semantics (i.e., the same comment is never intentionally reused). | Pattern 6 (DDL) | LOW — by construction, `telebot-{signal_id}-s{stage}` is unique per (signal_id, stage_number) pair, and the same pair is not INSERTed twice in normal flow. Retry/reconcile logic marks-filled rather than re-inserts. |

## Open Questions (RESOLVED)

1. **Does the MT5 REST bridge preserve `comment` end-to-end?**
   - What we know: the Python connector passes `comment` into POST body and reads `comment` from GET response [VERIFIED: mt5_connector.py:640-692].
   - What's unclear: whether the bridge server process (Wine MT5 + mt5linux RPyC shim + REST wrapper) translates the JSON `comment` into MT5's `order.request.comment` and reads it back from `mt5.positions_get().comment`.
   - Recommendation: Plan MUST include an integration test that opens+queries a position with a known comment and asserts round-trip, runnable in both CI (DryRun) and UAT (real bridge). Block phase progression on UAT pass.
   - **RESOLVED:** Bridge verification lives in BOTH surfaces. (a) **In-plan integration test** — `tests/test_staged_safety.py::test_mt5_comment_round_trip` runs in CI against `DryRunConnector` (Plan 02 / Plan 04 test battery; listed as adversarial case #9 under Validation Architecture above). (b) **UAT-only** — the real Wine-MT5 bridge round-trip is exercised by the VALIDATION.md "Manual-Only Verifications" row (operator opens a test stage, confirms comment round-trips via MT5 terminal + dashboard pending-stages panel). Phase gate = both CI test green AND UAT checkbox ticked.

2. **What does `signal.max_age_minutes` resolve to today?**
   - Search `config.py` / `models.py::GlobalConfig` for the field. If absent, add it as `signal_max_age_minutes: int = 30` in `GlobalConfig` (consistent with existing `limit_order_expiry_minutes` convention [VERIFIED: models.py:100]). Plan should include the field addition as a task.
   - **RESOLVED:** Field is ABSENT from `models.py::GlobalConfig` [VERIFIED this session: models.py:94-105]. Plan 01 Task 2 Step 3 adds `signal_max_age_minutes: int = 30` to the `GlobalConfig` dataclass in `models.py` (authoritative location; NOT `config.py`). Plan 04's `_sync_positions` reconcile logic reads `global_config.signal_max_age_minutes` to distinguish "abandoned vs still-valid" staged rows.

3. **Correlator behavior on bot restart mid-orphan-window.**
   - Known: In-memory correlator is empty on restart (per Pattern 3 rationale). A follow-up that arrives post-restart for a text-only fired pre-restart is treated as independent (D-05 fallback path).
   - Unclear: Is a WARN-level log sufficient, or should Discord alert operator so they know to close the would-be orphan manually?
   - Recommendation: Discord WARN alert. Operator judgment is cheap insurance.
   - **RESOLVED:** Discord WARN alert on the fallback path. Plan 02 Step 2 (`handle_signal`) emits a Discord WARN when `pair_followup` returns None and the signal shape suggests a likely orphan (follow-up OPEN with zone + SL + TPs on a symbol/direction with no registered orphan). Log + Discord line: `"Correlator miss: follow-up {symbol} {direction} has no pending orphan (post-restart? manual-close candidate)"`.

4. **"Typical signal" definition for dry-run preview in SET-03 modal.**
   - Planner call. Recommend: current account balance × proposed risk% with SL distance of 100 pips (XAUUSD convention). Display as literal computation: "Balance $X × Y% risk ÷ SL 100 pips = Z lots".
   - **RESOLVED:** Plan 03 (SET-03 form) renders the dry-run preview as the literal formula string: `"Balance $<current_balance> × <risk_value>% risk ÷ SL 100 pips = <computed_lots> lots"` for percent-mode; for fixed_lot mode, preview shows `"Fixed lot <risk_value> ÷ <max_stages> stages = <per_stage_lot> lots/stage"`. SL distance fixed at 100 pips (XAUUSD convention, pip_value=0.01).

5. **Zone-width degenerate case (`zone_low == zone_high`).**
   - Recommended behaviour per Pattern 2: all N-1 remaining stages share the same point-band; on in-zone-arrival check, all fire together. Alternative (reject at correlation time) was considered and rejected. Planner: add explicit test.
   - **RESOLVED:** Accept point-zone. `compute_bands(zone_low=X, zone_high=X, max_stages=N, ...)` returns `N-1` bands each with `low==high==X` (degenerate point-bands). Plan 02 Task 2 Step 1 must handle equality (`zone_low == zone_high`) without asserting — replace `assert zone_low < zone_high` with `if zone_low > zone_high: raise ValueError(...)` and short-circuit on equality to produce point-bands. `stage_is_in_zone_at_arrival` must evaluate true when `price == band.high == band.low` (both BUY `current_ask <= band.high` and SELL `current_bid >= band.low` remain valid with inclusive `<=` / `>=`). Dedicated unit test: `TestComputeBands::test_zero_width_zone_produces_point_bands`. Dedicated integration test: extend `test_in_zone_at_arrival_fires_crossed_bands_immediately` with a point-zone scenario asserting all N-1 stages fire in one pass.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL (asyncpg pool) | staged_entries DDL, all DB helpers | Yes (existing) | v1.0 base | — |
| MT5 REST bridge (connector service) | Stage fill submission, idempotency probe, reconnect reconcile | Yes (existing) | Already in production | DryRunConnector for CI |
| Python 3.12 | Base runtime (asyncio patterns) | Yes | v1.0 base | — |
| Basecoat v0.3.3 vendored | Tabs, dialog, empty-state primitives | Yes (Phase 5) | 0.3.3 pinned | — |
| Tailwind standalone CLI v4.2.2 | CSS build | Yes (Phase 5 D-04-REVISED) | v4.2.2 | — |
| pytest-asyncio | Integration test harness | Yes (existing dev dep per codebase/TESTING.md) | existing | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None.

Phase 6 is pure domain logic + schema + UI surfaces on top of the Phase 5 foundation. No new install steps.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (existing) |
| Config file | Implicit defaults per codebase/TESTING.md (no `pytest.ini`; `--asyncio-mode=auto` when invoking async tests) |
| Quick run command | `pytest tests/test_signal_parser.py tests/test_signal_correlator.py -x` |
| Full suite command | `pytest tests/ -x` |
| Integration harness | Session-scoped event loop per `test_trade_manager.py` pattern (autouse `setup_db` via `tmp_path`) [VERIFIED: codebase/TESTING.md] |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| STAGE-01 | Parser recognises "Gold buy now" → OPEN_TEXT_ONLY; "Gold buy now 2000" → OPEN_SINGLE; "Gold buy 2000-2010 sl 1990 tp 2020" → OPEN | unit | `pytest tests/test_signal_parser.py::TestTextOnlySignals -x` | Wave 0 |
| STAGE-02 | `_execute_open_on_account` rejects `sl=0.0`; text-only path applies `default_sl_pips` | integration | `pytest tests/test_staged_entries.py::test_text_only_default_sl -x` | Wave 0 |
| STAGE-03 | Correlator pairs follow-up within 10min; returns None outside window; most-recent wins | unit | `pytest tests/test_signal_correlator.py -x` | Wave 0 |
| STAGE-04 | In-zone-at-arrival fires crossed bands; watcher fires armed bands on price entry | integration | `pytest tests/test_zone_watcher.py::test_in_zone_at_arrival -x` + `::test_watcher_fires_on_entry` | Wave 0 |
| STAGE-05 | Dup-guard bypassed for same-signal-id sibling; still blocks unrelated same-direction | integration | `pytest tests/test_staged_safety.py::test_dup_guard_signal_id_bypass -x` | Wave 0 |
| STAGE-06 | Reconnect reconciles stages by comment; marks `abandoned_reconnect` only for stale stages with no MT5 match | integration | `pytest tests/test_staged_safety.py::test_reconnect_reconcile -x` | Wave 0 |
| STAGE-07 | Kill switch drains queue BEFORE position close; `_trading_paused` inner guard prevents mid-tick submit | integration | `pytest tests/test_staged_safety.py::test_kill_switch_drain -x` | Wave 0 |
| STAGE-08 | SSE payload includes `pending_stages` key; STAGE-08 partial renders rows from it | integration | `pytest tests/test_dashboard_sse.py::test_pending_stages_payload -x` | Wave 0 |
| STAGE-09 | `staged_entries.signal_id` + `mt5_ticket` join-back to `trades` produces per-signal analytics | integration | `pytest tests/test_staged_entries.py::test_attribution_join -x` | Wave 0 |
| SET-03 | Form validation rejects out-of-range; save writes audit row; revert flow audits itself | integration | `pytest tests/test_settings_form.py -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_signal_parser.py tests/test_signal_correlator.py tests/test_staged_entries.py -x` (~fast feedback; all unit + schema)
- **Per wave merge:** `pytest tests/ -x --asyncio-mode=auto` (full suite including integration tests that spin up DryRun connectors)
- **Phase gate:** Full suite green + manual UAT on staged-entry battery against real MT5 bridge before `/gsd-verify-work`

### Wave 0 Gaps

All test files below are net-new for Phase 6:

- [ ] `tests/test_signal_parser.py::TestTextOnlySignals` — extend existing file with text-only class covering D-01/D-02 regex + `_RE_PRICE_LIKE` guard
- [ ] `tests/test_signal_correlator.py` — new file — window, one-to-one pairing, eviction, most-recent-wins
- [ ] `tests/test_staged_entries.py` — new file — schema INSERT, snapshot persistence, helpers
- [ ] `tests/test_zone_watcher.py` — new file — `_zone_watch_loop` cadence, pre-flight re-check, in-zone-at-arrival, kill-switch inner guard
- [ ] `tests/test_staged_safety.py` — new file — the safety integration battery: dup-guard bypass, kill-switch drain ordering, reconnect reconcile, daily-limit accounting (D-18), per-symbol cap (D-19), stage-1 lifetime (D-16), MT5 comment round-trip (A1 verification)
- [ ] `tests/test_dashboard_sse.py` — new file — SSE payload shape, STAGE-08 partial render
- [ ] `tests/test_settings_form.py` — new file — validation caps (D-29), dry-run preview, audit write, revert flow
- [ ] `tests/conftest.py` — consider adding shared fixtures: `signal_correlator`, `staged_entries_table_seeded` — if existing conftest pattern supports it; else inline per test file per existing convention

### Adversarial test cases (race windows, boundary prices, orphans)

These MUST be included in `test_staged_safety.py`:

1. **Kill-switch race window.** Start a signal → stage 1 fills → follow-up arrives → arms stages 2-5 → kill-switch fires while `_zone_watch_loop` is between pre-flight and submit for stage 3. Assert: no stage 3 position on MT5, all `awaiting_zone` rows → `cancelled_by_kill_switch`, `resume_trading()` does NOT un-cancel.
2. **Boundary price — BUY band edge.** Price == `band_high` exactly → fires (inclusive). Price = `band_high + ε` → does NOT fire.
3. **Stage-1 immediate exit.** Stage 1 fires → TP1 hit within 1 second → follow-up arrives 2 seconds later. Per D-16 sequence lifetime, stages should NOT arm because stage 1 is gone. Explicit test for the Pattern-2 edge case (d).
4. **Signal arriving during reconnect.** Account in `_reconnecting`. Text-only arrives. `_execute_open_on_account` should return `{"status": "skipped", "reason": "reconnecting"}` — same as v1.0 behavior [VERIFIED: executor.py:114-117]. No `staged_entries` row created.
5. **Disconnect mid-fire → duplicate retry.** `_fire_stage` submits → TCP fails → on reconnect, reconcile finds MT5 position with the target comment → stage marked `filled`, no retry submit.
6. **Daily-limit boundary.** `max_daily_trades=5`; account already has 4 trades today. 5-stage signal arrives. Stage 1 fills (count → 5, D-18 helper returns True). Stages 2–5 fire (D-18 helper returns False each time → no increment). Assert: `daily_stats.trades_count = 5` at end, not 9.
7. **Per-symbol cap boundary (D-19).** `max_open_trades=3`, `max_stages=5`. 5-stage signal. Stage 1 + 2 + 3 fill (MT5 has 3 positions). Stages 4, 5 hit the cap at fire time → `status='capped'`.
8. **Correlator: one-to-one enforcement.** Text-only → follow-up A pairs it → follow-up B for same (symbol, direction) within window → treated as independent (orphan was popped).
9. **MT5 comment round-trip** (A1 mitigation). Verifies the critical assumption.

## Security Domain

**Applicability:** `security_enforcement` is not explicitly disabled in `.planning/config.json` (not audited this session; absent = enabled per researcher protocol). Phase 6 adds new routes (`POST /settings/{account}`, `POST /settings/{account}/confirm`, `POST /settings/{account}/revert`, `GET /staged`) and extends the SSE stream. All sit behind the existing `Depends(_verify_auth)` session-cookie gate and `Depends(_verify_csrf)` HTMX-header CSRF. No new authentication or session surface is introduced.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No new surface | Phase 5's `argon2-cffi` + SessionMiddleware gate inherited |
| V3 Session Management | No change | Phase 5 session cookie is the only session; all Phase 6 routes sit behind it |
| V4 Access Control | Yes — all Phase 6 routes | Single-admin model; `_verify_auth` dep [VERIFIED: dashboard.py:79-100] — same enforcement as existing routes |
| V5 Input Validation | Yes — SET-03 form | Server-side hard caps per D-29 (NOT client-side-only); FastAPI Form type coercion + explicit range checks; fail with 422 on violation |
| V6 Cryptography | No | Comment strings are not secrets; no new crypto primitives; session signing already in place via Starlette |
| V7 Error Handling & Logging | Yes | All stage status changes log at INFO; failures at ERROR with structured context; never log broker secrets (existing pattern) |
| V8 Data Protection | Yes — `snapshot_settings` JSONB | Contains `risk_value` (an operational setting, not a secret). No PII, no credentials. Row-level access via existing `_verify_auth`. |
| V9 Communication | No change | HTTPS termination at nginx (existing); no new external callouts |
| V13 API | Yes — HTMX JSON/form endpoints | CSRF via HTMX-header (D-31 re-uses Phase 5 pattern); all routes auth-gated; `_verify_csrf` blocks non-HTMX mutations [VERIFIED: dashboard.py:67-74 pattern] |

### Known Threat Patterns for FastAPI / HTMX / PostgreSQL / MT5 stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via settings field name | Tampering | Existing `_validate_field` whitelist in `db.py` [VERIFIED: db.py:42-44]; all new helpers MUST reuse this pattern. No f-string SQL interpolation. |
| CSRF on `/settings/{account}` POST | Tampering / Elevation | HTMX-header check via existing `_verify_csrf` dep (D-31) |
| Session hijack | Spoofing | Phase 5 `https_only=True` + signed session cookie (inherited) |
| Kill-switch bypass via forged request | Elevation | Kill-switch endpoint already behind `_verify_auth` + `_verify_csrf` (v1.0) |
| Stage `comment` injection into SQL | Tampering | `comment` is a server-generated deterministic string (never user input); DB column is TEXT with UNIQUE constraint but no LIKE query without parameterisation |
| Audit log tampering | Repudiation | `settings_audit` writes are append-only; no UPDATE path in `SettingsStore.update()` touches audit rows [VERIFIED: settings_store.py:87-92] |
| Sensitive data in logs | Information Disclosure | Existing logger pattern logs account_name + field name, NEVER raw credentials; `snapshot_settings` JSONB logged only at DEBUG |
| Race on concurrent settings edit | Tampering | Single-admin model → no concurrent writer. If a race occurs (two browser tabs), last-write-wins; the two audit rows document both edits. |

## Sources

### Primary (HIGH confidence — read this session)

- `.planning/phases/06-staged-entry-execution/06-CONTEXT.md` — all 39 locked decisions, canonical refs, specifics, deferred ideas
- `.planning/phases/06-staged-entry-execution/06-UI-SPEC.md` — UI design contract (approved 2026-04-19)
- `.planning/REQUIREMENTS.md` — STAGE-01..09, SET-03 definitions
- `.planning/STATE.md` — Phase 6 blockers/concerns list
- `.planning/ROADMAP.md` — Phase 6 goal + 6 success criteria
- `.planning/research/SUMMARY.md`, `ARCHITECTURE.md`, `PITFALLS.md` — deep pre-existing research
- `.planning/codebase/ARCHITECTURE.md`, `CONVENTIONS.md`, `TESTING.md`, `INTEGRATIONS.md` — code conventions and integration map
- `.planning/phases/05-foundation/05-CONTEXT.md` §D-23..D-32 — settings tables + SettingsStore contract
- `executor.py:1-293` — Executor class, _heartbeat_loop, _cleanup_loop, emergency_close, _sync_positions, _reconnecting / _trading_paused state
- `trade_manager.py:1-631` — handle_signal dispatcher, _execute_open_on_account full body including duplicate-direction guard at line 215
- `signal_parser.py:1-307` — parse_signal dispatcher, _RE_OPEN, _RE_OPEN_SINGLE, _RE_PRICE_LIKE, priority ordering
- `models.py:1-125` — SignalType enum, SignalAction, AccountSettings (frozen/slots)
- `settings_store.py:1-93` — SettingsStore.effective + snapshot + update contracts
- `db.py:150-210` (via grep/read) — account_settings, settings_audit, failed_login_attempts DDL
- `dashboard.py:1-100, 350-400, 550-585` — _verify_auth session dep, HTMX partials pattern, SSE /stream endpoint
- `mt5_connector.py:640-729` — REST connector open_order + get_positions + comment field handling
- `static/vendor/basecoat/` — confirmed Basecoat v0.3.3 CSS + JS vendored locally

### Secondary (MEDIUM confidence)

- MT5 bridge REST-to-mt5 behavior — confirmed via project-internal codebase reads; the bridge server source was NOT read this session (not in `.planning/`). The comment round-trip assumption (A1) rests on (a) the Python connector's bidirectional `comment` field handling [VERIFIED], (b) MT5 API convention that `positions_get()` returns `comment` as a namedtuple attribute [common knowledge, not verified this session].

### Tertiary (LOW confidence)

- Exact Basecoat v0.3.3 `init` API signature — inferred from Phase 5 UI-05 delivering `htmx_basecoat_bridge.js`. Plan MUST reference the existing bridge file rather than re-deriving.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new Python deps; Basecoat + Tailwind v4.2.2 + SSE all inherited from Phase 5 [VERIFIED]
- Architecture: HIGH — every integration point anchored to a verified line in executor.py, trade_manager.py, dashboard.py, db.py, signal_parser.py, models.py, settings_store.py, mt5_connector.py this session
- Pitfalls: HIGH — cross-check table maps every PITFALLS.md item 1-7, 17, 18 to a specific D-## with a residual-risk test requirement
- MT5 comment round-trip (A1): MEDIUM — high confidence the project connector round-trips; lower confidence (not verified this session) that the bridge server does. Mitigated by required integration test.

**Research date:** 2026-04-19

**Valid until:** 30 days (code paths + Phase 5 infra are stable; Basecoat 0.3.3 + Tailwind v4.2.2 are pinned; MT5 bridge API unchanged). Re-verify if any of these change.

## RESEARCH COMPLETE
