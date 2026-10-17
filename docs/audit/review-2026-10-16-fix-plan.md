# Code Review 2026-10-16 — Fix Plan

Fix plan for the 15 issues found by the 2026-10-16 code review of the audit-remediation series (`93ec594..0b74ffd`). The visual report is `telebot-code-review-2026-10-16.html` at the repo root; finding numbers (#1–#15) below match it.

Each batch is meant to be picked up on its own, from any machine: the entries say where the problem is, how it breaks, how to fix it and what to test. Line numbers are approximate (as of `7de138f`) — search by function name.

## Status

| Batch | Findings | State |
|---|---|---|
| 1 — quick wins | #4, #2, #8, #14, #15 | **Done** — `7de138f` (+ follow-up commit for test cleanup and constants) |
| 2 — stage tracking | #1, #5, #10, #6, #11 + kill-switch epoch | **Done** — full suite green (511 passed, 0 failed); 22 regression tests in `tests/test_review_batch2_stage_tracking.py` |
| 3 — harder fixes | #3, #13, #12, #7, #9 | **Done** — full suite green (531 passed, 0 failed); 20 regression tests in `tests/test_review_batch3_bridge_reads_and_closes.py`. #9 needs a deploy of `mt5-rest-server/server.py` to the Windows bridge. |
| 4 — minor items | ~10 small items | **Done** — full suite green (547 passed, 0 failed); 16 regression tests in `tests/test_review_batch4_minor_items.py`. Left out: shared bridge-payload test helpers (test-only refactor). |
| 5 — review follow-up | 9 findings of the 2026-10-17 `/code-review high` of batches 1–4 | **Done** — full suite green (563 passed, 0 failed); 16 regression tests in `tests/test_review_batch5_review_findings.py` |
| 6 — review follow-up | 9 findings of the 2026-10-17 `/code-review high` of batch 5 | **Done** — full suite green (573 passed, 0 failed); 10 regression tests in `tests/test_review_batch6_review_followup.py` |
| Test infrastructure | broken pool / event loop in the suite | **Done** — full suite green (489 passed, 0 failed) |

## Working rules for every batch

- One commit per batch, after the tests below pass. Push when the batch is done.
- Add a regression test per finding (they exist for batch 1 — copy their style: fakes for executor-only logic, the `tm_with_store` / `priced_connector` fixtures for DB-backed flows).
- Run a code review of the batch diff at `high` effort before committing; `max` is overkill for a batch this size.
- Run the **full suite** (`pytest -q`) before committing; it must stay at 0 failed. The per-file loop in "How to test" is only needed to isolate an order-dependent failure.

---

## Test infrastructure — done

**Problem (was).** A full `pytest` run reported ~100 failures, almost all `asyncpg InterfaceError: cannot perform operation: another operation is in progress` and `Task ... attached to a different loop`. Per file there were still 19 failures + 22 errors, so real regressions were easy to miss.

**Root causes found.**

```
session loop ──► db._pool (asyncpg, bound to this loop)
      │
      ├─ (a) conftest overrode pytest-asyncio's deprecated `event_loop` fixture →
      │      loop churn between tests → "attached to a different loop"
      │      (e.g. test_trade_manager direct-zone tests failed after TestFixedLotBranch)
      ├─ (b) api_app / settings_app / rate_limit popped `db` from sys.modules and ran a
      │      2nd init_db → two `db` modules, two pools; api.* kept the old one →
      │      shared connections used from two loops → the ~60 collateral failures
      └─ (c) Starlette TestClient runs handlers on its own thread + loop (anyio portal)
             → every DB-touching request through TestClient hit the pool cross-loop
```

Plus stale tests unrelated to loops: the legacy form `/login` (deleted in CUT-03) was still driven by test_api_contract / test_rate_limit / test_stages_contract; `/connect` mocks and the simulator returned `{"connected": true}` while the real bridge (and the connector since d14c16d) use `"login"`; test_concurrency never seeded the account the staged rows FK to; test_post_teardown assumed a built SPA bundle.

**Fix (landed).**

- `pytest-asyncio` 0.25 → 0.26, `asyncio_default_test_loop_scope = "session"` in `pyproject.toml`, custom `event_loop` fixture removed → every async test and fixture shares one loop, and `db_pool` lives on it.
- `conftest.api_app` depends on `db_pool`, never re-imports `db`, never creates its own pool. New `make_api_client(app, client_ip)` / `api_client` / `session_client` fixtures drive the app with `httpx.AsyncClient(ASGITransport)` on the session loop; `api_login()` does the real JSON login. `spa_index` (stub `static/app/index.html`) moved to conftest.
- All DB-backed API tests converted from `TestClient` to the async client (api_csrf, api_idempotency, api_settings, api_contract, rate_limit, post_teardown, stages_contract). TestClient remains only for DB-free tests.
- `clean_tables` no longer swallows exceptions (a silent failure is how no table was ever cleaned). Fixtures that relied on module-level seeding now seed per test (`test_api_settings`).
- Simulator `/api/v1/connect` returns the bridge's shape (`login/server/balance/equity`); connector unit tests use it and assert the password is kept for the heartbeat re-login.
- `test_concurrent_same_signal_no_duplicate` is `xfail(strict=True)`: the duplicate-position check is read-then-act (already in `remediation-backlog.md`). Fixing the race is bot work, not test work.

**Rule going forward.** For any test that hits a `/api/v2` route and the DB, use `api_client` / `session_client` / `make_api_client`, never `TestClient`. CI (`.github/workflows/ci.yml`) runs the full suite against a Postgres service.

---

## Batch 2 — done

**Model that landed.** A stage row has exactly one writer at a time, and every status write is a compare-and-set.

```
                 claim_stage_for_firing (CAS, sets firing_at)
 awaiting_zone ──────────────────────────────────────────► firing  (owned by the claiming coroutine)
      │                                                      │
      │ failed / capped / cancelled_* / abandoned_reconnect   │ owner finalizes, always:
      │ (only from awaiting_*; never over firing/filled)      │   open_order ok   → filled (+ticket)  BEFORE any bookkeeping
      ▼                                                      │   reject/raise    → failed   (expected_status=('firing',))
   terminal                                                  │   kill switch     → cancelled_by_kill_switch
                                                             ▼
                                                           filled ── never overwritten by a late writer

 stranded 'firing' (owner died / DB write lost)  ──► executor._reconcile_stale_firing_stages (each zone tick, >300 s)
                                                     position with the comment → filled ; none → failed (never re-armed)
```

`db.update_stage_status` now takes `expected_status` and returns `True/False`; the default rule per target status is `db._STAGE_TRANSITIONS`. Callers that lose a race leave the row alone (`already_filled` and `claim_lost` results are "no write").

**Reconcile rule** (`executor._sync_positions`, same code for startup and reconnect):

```
 pending row                               startup                 reconnect
 ─────────────────────────────────────────  ──────────────────────  ─────────────────────────────
 MT5 position carries its comment          filled (+ticket)        filled (+ticket)
 'firing', no position                     failed (interrupted)    failed once claim > 300 s old
 band, stage 1 filled & live on MT5        keep armed              keep armed            ◄ was: abandoned after 30 min (#6)
 band, stage 1 filled & gone               cancelled_stage1_closed cancelled_stage1_closed
 nothing filled yet ('awaiting_*')         keep armed              abandoned_reconnect after 30 min (D-24, unchanged)
```

The plan said "keep the age rule for reconnects"; it is kept only for sequences with nothing filled. A live sequence (stage 1 open) had the same bug on a connection drop as on a restart, so the D-16 rule applies to both paths. `bot.py` now runs the startup reconcile *before* `executor.start()`.

**Other pieces.**
- #1 — `db.update_stage_targets_for_position(account, comment, sl=, tp=)` (COALESCE, filled rows only, stage comments only). Called after a successful MODIFY_SL / MODIFY_TP (`trade_manager._record_stage_level_change`) and after the dashboard levels edit (`api/actions.levels`). The sweep then keeps the new level.
- #11 — `_handle_correlated_followup` persists the follow-up's SL/TP onto the stage-1 row whenever it is live (`awaiting_zone`/`firing`/`filled`); the broker modify is sent only when a ticket exists, otherwise the sweep aligns the position on its first tick after the fill.
- Kill-switch epoch — `Executor._kill_switch_epoch` (+1 per `emergency_close`); `TradeManager.handle_signal` records it in a `ContextVar`; `_kill_switch_gate(stage_ids=...)` refuses when the epoch changed even if the operator already resumed, and cancels only the rows the handler owns (no global drain after a resume).
- Schema: `staged_entries.firing_at TIMESTAMPTZ` (ALTER ... IF NOT EXISTS; nullable, old rows fall back to `created_at`).

**Judgment calls to confirm during the end-to-end test.**
- A stale `firing` row with no position becomes `failed`, not `awaiting_zone`: the order may have filled and already closed, and re-arming would double the entry. The operator re-sends if it was a missed entry.
- Post-fill bookkeeping failures (`log_trade`, daily stats) are logged, not raised: the position is open and the stage row already says `filled`.

---

## Batch 2 — stage tracking (original plan)

These all touch how a stage row's `status` / targets stay in step with the broker. They share code (`db.update_stage_status`, `executor._fire_zone_stage`, `trade_manager._execute_open_on_account`), so do them together.

### #1 SL/TP sweep undoes breakeven and TP edits — `executor.py` `_verify_one_stage_sltp` (~1110)
- **Problem.** The sweep treats `staged_entries.signal_sl/signal_tp` as permanent targets. `trade_manager._handle_modify_sl`, `_handle_modify_tp` and the dashboard levels edit (`api/actions.py` `levels`, ~104) change the live SL/TP but never update those columns.
- **Breaks as.** Provider says "SL to BE" → SL moved to entry → within ~10 s the sweep sets it back to the original SL. Same for MODIFY_TP and dashboard edits.
- **Fix.** After a successful modify of a bot position whose comment is `telebot-<signal>-s<n>`, update that stage row's target for the level that changed. `db.update_stage_targets` overwrites both columns — add a variant that updates only SL or only TP (or uses `COALESCE`).
- **Test.** Filled stage + MODIFY_SL to breakeven → run the sweep → no modify call, SL stays at breakeven.

### #5 Fire-path races overwrite "filled" / "firing" — `executor.py` `_fire_zone_stage` (~1330), pre-claim D-19 cap check
- **Problem.** Only the `filled` transition is guarded (`db.update_stage_status`, ~1092). `failed` (zone watch, reason `already_filled`) and `capped` (D-19 pre-claim check) are written unconditionally.
- **Breaks as.** Zone watch snapshots s2 as awaiting → the at-arrival path claims and fills s2 → zone watch's probe says already_filled → writes `failed` over the live position's row. The row drops out of the SL/TP sweep and the D-16 cascade.
- **Fix.** Give `update_stage_status` an allowed-previous-states guard for every status (e.g. `failed`/`capped` only from `awaiting_zone`; never from `filled`/`firing` unless the caller owns the claim). Treat reason `already_filled` as "no write".
- **Test.** Simulate both orderings; the final status must be `filled` with the ticket.

### #10 Stages stuck in "firing" — `trade_manager.py` `_execute_open_on_account` (~1100)
- **Problem.** After the claim, the row leaves `firing` only through this coroutine's own writes. If `increment_daily_stat` / `log_trade` raises after `open_order` succeeded (or the process crashes), the row stays `firing` with no ticket. Nothing else picks up `firing` rows.
- **Fix.** Write the `filled` status + ticket immediately after a successful `open_order`, before the other bookkeeping, and wrap the bookkeeping in try/except. In the reconcile (`executor._sync_positions` ~291) and zone watch, treat `firing` rows older than a few minutes: position with the comment exists → `filled`; otherwise back to `awaiting_zone` (or `failed`).
- **Test.** Make `log_trade` raise after a fill → the row is `filled` with the ticket.

### #6 Restart cancels armed scale-ins — `bot.py` startup reconcile (~308) → `executor._sync_positions` (~291, ~326–350)
- **Problem.** The startup reconcile applies the reconnect rule: pending bands older than `signal_max_age_minutes` (30) with no position → `abandoned_reconnect`. That includes bands of sequences whose stage 1 is still open.
- **Breaks as.** Stage 1 fills 10:00, bands armed 10:01, deploy restarts 10:45 → bands abandoned → price reaches the band at 11:00 and nothing fires.
- **Fix.** On startup, abandon a band only when its stage 1 is closed (the D-16 rule: sequence lifetime = stage-1 lifetime); keep the age rule for reconnects. Also mark the account as reconciling (add to `_reconnecting`) while the startup reconcile runs, or run it before `executor.start()`.
- **Test.** Stage 1 filled + live, bands 45 min old → startup reconcile → bands still `awaiting_zone`.

### #11 Follow-up that arrives too early skips the stage-1 alignment — `trade_manager.py` `_handle_correlated_followup` (~495)
- **Problem.** Alignment and `update_stage_targets` only run when stage 1 is already `filled`. A follow-up arriving while stage 1 is `awaiting_zone`/`firing` skips both (debug log only).
- **Breaks as.** Stage 1 fills with the default SL and TP 0; the sweep sees it as in sync, the orphan-TP watchdog skips it because siblings exist.
- **Fix.** Always persist the follow-up's targets onto the stage-1 row when it exists (any non-terminal status); only send the modify when it is `filled`. The sweep then aligns it once it fills.
- **Test.** Follow-up while stage 1 is `firing` → after stage 1 fills, one sweep tick sets SL/TP to the follow-up's values.

### Leftover from the batch-1 review — kill switch then quick resume
- A handler in flight when the kill switch fires, where the operator resumes before the handler reaches a check, still proceeds. Fix: an epoch counter the executor increments on `emergency_close`; the handler records it at start and the gate refuses if it changed.

---

## Batch 3 — done

Suite after the batch: `531 passed, 8 skipped, 1 xfailed, 0 failed` (was 511). Two existing tests were updated because they asserted the old behaviour: `test_rest_api_connector` (empty list on a failed read) and the one-tick helper in `test_staged_safety_hooks` (the maintenance passes now live in their own loop).

### #3 — timed-out order

```
open_order ──► POST /order ──► ReadTimeout (request WAS sent)
                                   │
          before: OrderResult(success=False)  ──► stage 'failed', trade 'failed', ticket 0
                                                  (a fill nobody tracks)
          now:    OrderResult(outcome_unknown=True)
                    │
                    ├─ staged:   row stays 'firing', cancelled_reason='outcome_unknown'
                    │            (no trade row yet) ──► stale-firing reconcile, EVERY tick:
                    │               position with the row's comment ──► 'filled' + ticket
                    │                                                  + trades row created
                    │                                                    from the position
                    │               no position, claim < 300 s  ──► wait (bridge may still work)
                    │               no position, claim > 300 s  ──► 'failed'
                    │                                        (…_after_unknown_outcome)
                    └─ unstaged: trades row status='unknown', ticket 0 (operator-visible;
                                 nothing can reconcile the legacy comment "telebot")
```

`RestApiConnector._last_outcome_unknown` is set by the non-GET ReadTimeout branch; every `OrderResult` built from a `None` response carries it. The adoption helper (`Executor._adopt_stage_position`) is also used by the startup/reconnect sync, so a fill whose bookkeeping died gets its trades row there too.

### #13 — failed read looked like "nothing there"

```
get_positions / get_pending_orders / get_history_deals  on a failed request
   before: []            now: raise ConnectorReadError

caller                         on ConnectorReadError
──────────────────────────────  ─────────────────────────────────────────────
_execute_open_on_account        skipped/broker_read_failed → stage stays armed
cleanup_expired_orders          'read_failed' result, order stays 'active', no cancel
CLOSE / CLOSE_PARTIAL /         account result failed/broker_read_failed, nothing touched
MODIFY_SL / MODIFY_TP
history sync                    watermark NOT advanced (no deal window skipped)
zone watch / sweep / orphan /   account skipped this tick (already try/except)
stale reconcile / sync
API levels, partial close       503 "broker read failed" (was 404 "position gone")
```

### #12 — one dead bridge delayed everyone

```
before, one task:   [orphan-TP] [SL/TP sweep] [stale reconcile] [band fires]   every 10 s
                     ^^^ each read every account, no connected check, 3×15 s timeouts

now, two tasks:     _zone_watch_loop        ──► _zone_watch_tick()  (fires only)
                    _stage_maintenance_loop ──► orphan-TP, sweep, stale reconcile

                    every broker read in both: asyncio.wait_for(…, 8 s)  (_read_bounded)
                    disconnected accounts: skipped (heartbeat owns them)
```

### #7 — dashboard close stuck in 'closing'

```
POST /positions/{acct}/{ticket}/close
   read floating profit (estimate) ──► close_position
      backend has deal history (REST)  ──► mark_trade_closing(close_price, pnl_estimate)
                                             │  guarded: only 'opened'/'closing' rows move;
                                             │  a reconciled 'closed' row never reopens
                                             └─ history sync finalizes with the real deal …
                                                … or after 600 s with no deal: finalized
                                                  from the estimate (warning logged)
      dry-run / simulator (no history)  ──► update_trade_close(estimate) immediately
```

### #9 — concurrent modifies on the bridge

`modify_position` and `close_position` in `mt5-rest-server/server.py` now take a per-ticket `asyncio.Lock` around read + `order_send`. The regression test loads the server against a fake `MetaTrader5` module and reproduces the lost update without the lock. **Deploy to the Windows bridge is required** for this one; nothing else in the batch touches the bridge.

### Judgment calls to confirm in the end-to-end test

- A trade with `status='unknown'` is a new value (legacy, non-staged path only). Dashboard/history filters that enumerate statuses will not list it until Batch 4 adds it.
- The stale-closing fallback writes the pre-close floating profit as the final P&L. It only runs after 600 s without a broker deal, and it logs a warning each time, so a misbehaving history sync is visible rather than silent.
- Reconcile of an outcome-unknown row without a position waits the normal 300 s before failing it, on the assumption the bridge's single MT5 thread may still be working the order.
- `_READ_TIMEOUT_SECONDS = 8` applies to zone-watch and maintenance reads only; emergency close and signal handlers keep the connector's own 15 s × 3 budget.

---

## Batch 3 — harder fixes (original plan)

### #3 Timed-out order is treated as rejected — `trade_manager.py` (~1150), `mt5_connector.py` `_request` ReadTimeout branch
- **Problem.** A non-GET ReadTimeout means the outcome is unknown (the bridge keeps running `order_send`), but it is reported like a broker rejection: trade logged `failed` with ticket 0, stage `failed`.
- **Breaks as.** The order fills → a live position nothing tracks (no SL/TP sweep, no P&L, no cascade).
- **Fix.** Return a distinct "outcome unknown" result; keep the stage `firing`; probe positions by the unique comment (`telebot-<signal>-s<n>`) on the next reconcile and adopt the position (stage `filled` + ticket, trade row). This was the audit's §4.1 remedy.
- **Test.** POST times out, the position later appears with the comment → stage `filled`, trade row has the ticket.

### #13 A failed read looks like "no positions" — `mt5_connector.py` `get_positions` / `get_pending_orders`; callers `cleanup_expired_orders` (~1378), zone watch D-16 check
- **Problem.** Both return `[]` on any request failure.
- **Breaks as.** Cleanup marks a still-resting limit order `cancelled` without cancelling it at the broker; zone watch cancels armed bands because stage 1 "is gone".
- **Fix.** Return `None` (or raise) on failure and make every caller skip the tick on `None`. Touches many callers — grep for both methods.
- **Test.** Failing read → no status changes.

### #12 One dead bridge delays fires on every account — `executor.py` `_run_stage_sltp_verification_sweep` (~1040)
- **Problem.** The sweep runs inline before the band-fire pass and doesn't check `connector.connected`; a dead bridge costs ~47 s per tick (3 × 15 s timeouts).
- **Fix.** Skip disconnected accounts; run the sweep after the fires, or as its own task with a per-account `asyncio.wait_for`.
- **Test.** One account's `get_positions` hangs → other accounts' in-band stages still fire on time.

### #7 Dashboard close stuck in "closing" — `api/actions.py` (~93), `db.mark_trade_closing` (~371)
- **Problem.** Close parks the trade in `closing` and relies on history sync, which never sees a deal on dry-run (default `TRADING_DRY_RUN=true`) or the mt5-simulator.
- **Fix.** Finalize directly when the backend has no history (dry-run); add a status guard to `mark_trade_closing`; add a timeout fallback for `closing` rows.
- **Test.** Dry-run close → trade `closed`.

### #9 Concurrent modifies on the bridge lose a change — `mt5-rest-server/server.py` `modify_position` / `close_position` (~421–505)
- **Problem.** Each MT5 call is a separate executor job, so two modifies on one ticket both read the old SL/TP and the later write restores a stale value.
- **Fix.** Per-ticket `asyncio.Lock` around read + `order_send`, or run the read and send as one job.
- **Test.** Two interleaved modifies (fake mt5 module) → final state has both changes. Needs a deploy to the Windows bridge.

---

## Batch 4 — done

Suite after the batch: `547 passed, 8 skipped, 1 xfailed, 0 failed` (was 531). Two existing tests updated: the heartbeat fake connector gained `has_credentials()`, and the connector error-detail test now expects the transport failure text instead of the fixed "REST API request failed".

```
item                                   fix
─────────────────────────────────────  ──────────────────────────────────────────────────
_last_error shared per connector       _request_ex() returns (data, error, outcome_unknown)
                                       per call; OrderResult.error comes from its own call
"10025" matches ticket digits          whole-number regex (?<!\d)10025(?!\d)
sweep re-reads all filled history      NOT EXISTS closed/cancelled trade, newest first,
                                       LIMIT db.SLTP_SWEEP_MAX_ROWS (500)
signals lost during startup reconcile  Telegram handler registered BEFORE connect +
                                       reconcile; trade execution awaits pipeline_ready,
                                       the Discord relay does not wait
idempotency JSON-encoded twice         dict handed to the jsonb codec; legacy string rows
                                       still decoded on replay
SPA logout leaves CSRF cookies         /api/v2/auth/logout expires session + CSRF cookies
                                       (same helper as the legacy form /logout)
drilldown Lots / "0.00 – 0.00"         lots = trades.lot_size (not the risk slice);
                                       a 0/0 band is reported as None → SPA shows "Market"
duplicated cascade SQL                 one _cancel_unfilled_stages(status, …) body
third pip-size helper                  risk_calculator.pip_size_for_symbol(); executor and
                                       trade_manager delegate
500 logged twice                       one-line error (the ASGI server logs the traceback)
CSRF retry resends stale body token    http.ts swaps csrf_token in a JSON body before the
                                       single retry (frontend build needed on deploy)
int() on SESSION_ABSOLUTE_MAX_AGE      dashboard._env_int(): garbage/zero → default + warning
sweep modifies not in server_messages  Executor._count_server_message after sweep /
                                       orphan-TP modifies
three has_credentials copies           MT5Connector.has_credentials()
backlog: pending limit trades          mark_pending_filled → trades 'opened';
                                       mark_pending_cancelled → trades 'cancelled'
backlog: CLOSE records floating P&L    _handle_close → mark_trade_closing(estimate) on a
                                       bridge with deal history; dry-run finalizes at once
```

`db.cancel_stage_for_kill_switch()` landed in batch 2 as `cancel_stages_for_kill_switch`. The `unknown` trade status from batch 3 needs no filter change: the history API passes `status` through and the SPA has no status enum.

### Judgment calls to confirm in the end-to-end test

- The startup gate holds trade execution (not the Discord relay) until MT5 connect + reconcile finish. A signal that arrives in that window executes a few seconds late instead of being dropped; the stale-signal check still applies when it runs.
- Bot-side CLOSE now shows `closing` for up to 600 s on a real bridge (same path as the dashboard close). Dry-run is unchanged.
- `mark_pending_cancelled` writes trades `status='cancelled'` — a new value for the trades table, excluded from analytics like `pending` was.

---

## Batch 5 — done (review follow-up)

The user-run `/code-review high` of batches 1–4 (2026-10-17) returned nine findings; this batch closes all of them. Suite after the batch: `563 passed, 8 skipped, 1 xfailed, 0 failed` (was 547). Two batch-3 tests adjusted: the stale-closing fallback test now sets a history watermark first, and the maintenance-loop test's pass stubs accept the shared positions cache and expect the fourth pass.

```
#  finding                                   fix
─  ────────────────────────────────────────  ─────────────────────────────────────────────────
1  mark_trade_closing skips 'pending' rows →  limit fills are detected every maintenance tick
   dashboard close of a filled limit is lost  (_detect_pending_order_fills: active pending_orders
                                              vs. positions by ticket → mark_pending_filled);
                                              the row is 'opened' long before any close
2  pending→cancelled also hits "filled and    cleanup_expired_orders: no order + no position on a
   closed before expiry"                      bridge with deal history → look for the OUT deal
                                              (_closed_deal_for_pending_order) → trade 'closed'
                                              with broker P&L (result status filled_closed);
                                              read failure → retried next cycle; no deal → cancelled
3  stale-closing fallback ran before the      fallback runs AFTER the deals fetch and only for rows
   deals fetch, on wall clock                 whose close_time < history watermark
                                              (get_stale_closing_trades(read_until=…)); a failed
                                              fetch never reaches it; no watermark → nothing final
8  pre-batch 'closing' rows (close_time NULL) COALESCE(close_time, timestamp) in the age predicate
   never picked up
4  D-14 pre-flight get_price unbounded        _read_bounded like every other read in the tick
5  bands kept armed when stage 1 ended        _stage1_state → (live|gone|terminal|pending|none,
   failed/capped/abandoned                    status); startup/reconnect reconcile AND the zone-
                                              watch D-16 check cascade on 'terminal' with reason
                                              stage1_<status>[_at_<mode>] (status stays
                                              cancelled_stage1_closed — no new SPA status)
6  3 get_positions per account per tick       _stage_maintenance_tick(): one bounded read per
                                              account shared by the four passes via positions_cache
                                              (a failed read is cached as None → skipped once)
7  'filled' kept cancelled_reason=            update_stage_status filled branch sets
   outcome_unknown                            cancelled_reason=NULL
9  drain hand-parsed the command tag          _rows_affected(result)
```

```
limit order life cycle (after batch 5)

 place ──► trades 'pending' + pending_orders 'active'
             │
             ├─ position with the order's ticket appears ──► maintenance tick (≤10 s)
             │                                                mark_pending_filled → trades 'opened'
             │                                                  └─ close (dashboard / bot / broker)
             │                                                     → 'closing' → history sync → 'closed'
             ├─ expiry, order still resting ──► cancel_pending → trades 'cancelled'
             ├─ expiry, no order, position ──► mark_pending_filled (unchanged)
             └─ expiry, no order, no position
                     ├─ OUT deal found  ──► 'closed' with broker P&L   (new)
                     ├─ history unreadable ──► retry next cycle         (new)
                     └─ no deal / dry-run ──► trades 'cancelled'
```

### Judgment calls to confirm in the end-to-end test

- A 'closing' row is finalized from its estimate only after the history sync has read past its close_time (plus the 600 s age). While the bridge cannot serve deal history, rows stay `closing` — that is the intended behaviour, not a stall.
- Bands whose stage 1 ended `failed` / `capped` / `abandoned_reconnect` / `cancelled_*` are now cancelled with status `cancelled_stage1_closed` and reason `stage1_<status>` (zone watch) or `stage1_<status>_at_startup|reconnect` (reconcile). Previously such bands fired standalone later.
- The pending-fill check uses the same 10 s cadence as the other maintenance passes; a fill that closes again within one tick is caught at expiry via the OUT-deal probe, which is one extra `GET /history/deals` per such order.

---

## Batch 6 — done (review follow-up on batch 5)

The user-run `/code-review high` of batch 5 returned nine findings (three behavioural, six hygiene); all closed. Suite after the batch: `573 passed, 8 skipped, 1 xfailed, 0 failed` (was 563). One batch-3 test adjusted for the new maintenance pass order.

```
#  finding                                     fix
─  ──────────────────────────────────────────  ────────────────────────────────────────────────
1  reconcile judged bands before their stage 1 pending rows sorted by (stage_number, id) before the
   (newest-first fetch + per-signal memo) →     pass → a 'firing' stage 1 failed by this pass is
   bands of a dead sequence stayed armed        seen by its bands' D-16 check
4  stage-1 lookup failure → 'none' → fire       new state 'unknown': zone watch skips the fire
   allowed (fail-open)                          (bands kept), reconcile keeps the band
3  sync accepted deal entry 1 only; probe 1+3   mt5_connector.CLOSING_DEAL_ENTRIES = {1, 2, 3}
                                                shared by history sync and expiry probe
2  dead history endpoint → fallback never runs, _warn_closing_rows_blocked: one logger.error per
   silently                                     account per outage, only when 'closing' rows are
                                                waiting; re-armed after a successful read.
                                                Behaviour unchanged (rows stay 'closing').
6  stale-firing 'failed' decided from a         pass order: stale-firing → pending-fill → orphan-TP
   snapshot aged by two modify passes           → SL/TP sweep (irreversible write on the fresh read)
5  filled_closed close_time = now               update_trade_close(close_time=) from the deal time
                                                (history sync too)
8  one history read per expired order           one read per account per cleanup cycle, seeded
                                                from the oldest expired order; a read failure is
                                                cached for the cycle
9  one pending-orders query per account/tick    one cross-account query, grouped by account
7  D-16 cascade block duplicated                Executor._cascade_dead_stage1(state, status, suffix)
```

### Judgment calls to confirm in the end-to-end test

- Reversal (`entry=2`) and close-by (`entry=3`) deals now close the matching trades row with the deal's profit. MT5 reports the closing leg's profit on these deals as it does for a plain OUT; if the broker reports reversals differently, the P&L of a reversed position would be wrong where before it fell to the 600 s estimate.
- `trades.close_time` is now the broker deal time for history-reconciled and expiry-probed closes; dashboard/estimate closes still use the submit time.
- A dead `/history/deals` endpoint produces one ERROR log line per account per outage listing the stuck tickets. No Discord alert (the heartbeat already alerts on a dead bridge).

---

## Batch 4 — minor items (original plan)

- `RestApiConnector._last_error` is shared per connector — a concurrent call can pick up another call's error (`mt5_connector.py` ~591).
- The `"10025"` substring check also matches ticket numbers such as 41002537 (`trade_manager.py` ~235).
- `get_filled_stages_for_sltp_verification` re-reads all filled history every tick — bound it.
- Startup reconcile delays Telegram handler registration; signals arriving meanwhile are lost.
- Cached idempotency results are JSON-encoded twice (`api/idempotency.py` ~112).
- Logout: cookie expiry only wired into the unused legacy `/logout`; SPA logout leaves the CSRF cookies.
- Drilldown: "Lots" shows the risk-percent slice in percent mode; text-only stage 1 shows "0.00 – 0.00" instead of "Market" (`api/positions.py` ~83/85).
- Cleanup: duplicated SQL branches, a third pip-size helper, 500 errors logged twice, CSRF retry resends a stale body token, unguarded `int()` on `SESSION_ABSOLUTE_MAX_AGE`, sweep modifies not counted in `server_messages`.
- From the batch-1 review: one `MT5Connector.has_credentials()` instead of three copies (`bot.py` ~286, `executor._heartbeat_tick`, `_reconnect_account`); shared test helpers with production-shape bridge payloads; `db.cancel_stage_for_kill_switch()` next to the drain.
- Already in `remediation-backlog.md`: limit-order `pending` trades never reconciled; CLOSE signals record floating P&L.

## Also worth scheduling (from the 2026-10-12 project analysis)

- **No sender allowlist** — any member of a source group can post a BUY or "close all" that the bot executes. Highest-impact item outside this review.
- No CI, no DB migrations, no metrics/alerting, the Windows bridge as a single point of failure, `mt5_comment` UNIQUE clash once a second account is added, live MT5 sign-off not done.

---

## How to test

Throwaway Postgres (does not touch the dev DB):

```bash
docker run -d --rm --name telebot-review-pg \
  -e POSTGRES_USER=telebot -e POSTGRES_PASSWORD=telebot_dev -e POSTGRES_DB=telebot \
  -p 55433:5432 postgres:16-alpine
export TEST_DATABASE_URL=postgresql://telebot:telebot_dev@localhost:55433/telebot
```

Run with Python 3.12 (production version) without touching `.venv`:

```bash
UVR="uv run --no-project --python 3.12 --with-requirements requirements.txt --with-requirements requirements-dev.txt"
$UVR python -m pytest -q tests/test_killswitch_late_stage_gate.py
```

Per-file comparison (each file on an empty DB) — run on the parent commit and on your branch, then diff the failing test ids:

```bash
for f in tests/test_*.py; do
  docker exec telebot-review-pg psql -q -U telebot -d telebot -c \
    "DO \$\$ DECLARE r record; BEGIN FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP EXECUTE 'TRUNCATE ' || quote_ident(r.tablename) || ' RESTART IDENTITY CASCADE'; END LOOP; END \$\$;" >/dev/null
  $UVR python -m pytest -q -p no:cacheprovider -rfE "$f" | grep -E '^(FAILED|ERROR) ' | sed -E 's/ - .*//'
done | LC_ALL=C sort > failing.txt
```

Baseline after the test-infrastructure fix: full suite `489 passed, 8 skipped, 1 xfailed, 0 failed`; per file: 0 failures. (Before: 103 failed + 22 errors in the full run, 19 failed + 22 errors per file.)

Stop the database afterwards: `docker stop telebot-review-pg`.
