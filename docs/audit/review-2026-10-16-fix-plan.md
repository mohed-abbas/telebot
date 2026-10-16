# Code Review 2026-10-16 — Fix Plan

Fix plan for the 15 issues found by the 2026-10-16 code review of the audit-remediation series (`93ec594..0b74ffd`). The visual report is `telebot-code-review-2026-10-16.html` at the repo root; finding numbers (#1–#15) below match it.

Each batch is meant to be picked up on its own, from any machine: the entries say where the problem is, how it breaks, how to fix it and what to test. Line numbers are approximate (as of `7de138f`) — search by function name.

## Status

| Batch | Findings | State |
|---|---|---|
| 1 — quick wins | #4, #2, #8, #14, #15 | **Done** — `7de138f` (+ follow-up commit for test cleanup and constants) |
| 2 — stage tracking | #1, #5, #10, #6, #11 | To do |
| 3 — harder fixes | #3, #13, #12, #7, #9 | To do |
| 4 — minor items | ~10 small items | To do |
| Test infrastructure | broken pool / event loop in the suite | To do — recommended **before** batch 2 |

## Working rules for every batch

- One commit per batch, after the tests below pass. Push when the batch is done.
- Add a regression test per finding (they exist for batch 1 — copy their style: fakes for executor-only logic, the `tm_with_store` / `priced_connector` fixtures for DB-backed flows).
- Run a code review of the batch diff at `high` effort before committing; `max` is overkill for a batch this size.
- Compare test results **per file**, against a baseline taken on the parent commit (see "How to test"). The full-suite run is not usable as a signal until the test-infrastructure item is fixed.

---

## Test infrastructure (do this first)

**Problem.** A full `pytest` run reports ~100 failures, almost all `asyncpg InterfaceError: cannot perform operation: another operation is in progress` and `Task ... attached to a different loop`. The session-scoped `db_pool` is created on the session loop, then used from other loops (the dashboard `TestClient` runs its own loop in a thread via anyio), which breaks the pool for every later test. Running each file on its own still leaves 19 failures + 22 errors (mostly the API/dashboard tests), so real regressions are easy to miss.

**Already fixed (follow-up commit):** `clean_tables` truncated `idempotency_keys`, a table only the dashboard lifespan creates, so its single `TRUNCATE` always failed and the error was swallowed — no table was ever cleaned. `db_pool` now creates that table; that alone took the per-file failures from 32 to 19.

**Fix ideas.**
- Give the API tests (TestClient) their own pool/loop, or make `db_pool` function-scoped for them; or drive the app with `httpx.AsyncClient(transport=ASGITransport(app))` on the session loop instead of `TestClient`.
- Stop `clean_tables` from swallowing every exception (log or fail loudly).
- Then get the per-file failures to zero and add a CI job so the suite stays green.

---

## Batch 2 — stage tracking

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

## Batch 3 — harder fixes

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

## Batch 4 — minor items

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

Baseline after the batch-1 follow-up commit: 19 failed + 22 errors per file (all pre-existing), 447 passed. Files still failing: `test_api_contract`, `test_api_settings`, `test_api_csrf`, `test_api_idempotency`, `test_concurrency`, `test_post_teardown`, `test_rate_limit`, `test_rest_api_connector` (2 `connect()` tests), `test_rest_api_integration`, `test_trade_manager` (2).

Stop the database afterwards: `docker stop telebot-review-pg`.
