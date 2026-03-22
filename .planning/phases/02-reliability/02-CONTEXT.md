# Phase 2: Reliability - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

MT5 reconnection, kill switch, execution correctness, and position safety. The bot recovers from MT5 disconnections without losing state, and trading execution is correct and safe.

Requirements: REL-01, REL-02, REL-03, REL-04, EXEC-01, EXEC-02, EXEC-03, EXEC-04, DB-03

</domain>

<decisions>
## Implementation Decisions

### Kill switch behavior
- **Confirm first** before closing — show summary of open positions and pending orders, require user confirmation before executing emergency close
- Global scope only — one button kills all accounts (no per-account granularity)
- After activation: close all positions, cancel all pending orders, pause executor
- Re-enable via **dashboard toggle** with clear "TRADING PAUSED" state banner
- **Always send Discord alert** (#alerts) on both activation and re-enable — `notify_kill_switch()` already exists in notifier.py

### Reconnection behavior
- **Drop signals during reconnect** with Discord alert ("Signal skipped — MT5 reconnecting") — do not queue or replay
- **Exponential backoff**: 1s, 2s, 4s, 8s... up to 60s max between reconnect attempts
- **Unlimited retries** — keep trying forever with backoff; Discord alerts keep user informed
- **Heartbeat every 30s** — check MT5 connection health via ping
- After reconnect: full position sync from MT5 before accepting new signals
- Set `reconnecting` flag that signal handler checks before processing

### Daily limit warnings
- Warnings appear in **both dashboard and Discord #alerts**
- Warn at **80% threshold** (e.g., 24/30 trades)
- Dashboard shows **per-account counter**: "Trades: 12/30" with color coding (green/yellow/red)
- `notify_daily_limit()` already exists in notifier.py for Discord alerts

### Claude's Discretion
- Zone-based SELL boundary fix (EXEC-01): exact fix approach, test cases
- Stale signal double-check (EXEC-02): implementation location in execution flow
- SL/TP modification validation (EXEC-03): what constitutes "valid" for each direction
- Pending order cleanup race fix (REL-04): retry queue implementation details
- Database archival mechanism (DB-03): archive format, retention period logic
- Dashboard endpoint structure for kill switch (POST /emergency-close)
- Heartbeat implementation: separate asyncio task vs. integrated into executor loop
- Position reconciliation algorithm after reconnect

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Execution layer
- `executor.py` — Multi-account orchestration, stagger delays, cleanup loop. Kill switch flag and reconnection awareness needed here.
- `trade_manager.py` — Zone-based execution (lines 289-316), stale signal check (lines 267-287), SL/TP modification (lines 389-452), pending order cleanup (lines 456-479)
- `mt5_connector.py` — Base connector class with `connect()`, `get_positions()`. Heartbeat and auto-reconnect needed here.

### Notification layer
- `notifier.py` — Already has `notify_kill_switch()`, `notify_connection_lost()`, `notify_connection_restored()`, `notify_daily_limit()`. Wire these to new functionality.

### Dashboard
- `dashboard.py` — FastAPI endpoints. Needs kill switch POST endpoint and daily limit display.

### Concerns driving this phase
- `.planning/codebase/CONCERNS.md` — Pending order race condition, zone SELL logic, missing reconnect, missing kill switch
- `.planning/research/PITFALLS.md` — Reconnect cascade risk, kill switch orphaned orders, TOCTOU in stale check

### Phase 1 changes (now in codebase)
- `db.py` — Now uses asyncpg connection pool (Phase 1 migration). All db functions are async with PostgreSQL syntax.
- `config.py` — Hardened with DATABASE_URL, MT5_MAGIC_NUMBER, strict validation.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `notifier.py:notify_kill_switch()` — Already implemented, just needs to be called when kill switch activates/deactivates
- `notifier.py:notify_connection_lost()` / `notify_connection_restored()` — Already implemented for Discord alerts
- `notifier.py:notify_daily_limit()` — Already implemented for limit warnings
- `executor.py:cleanup_expired_orders()` — Background task loop (every 60s), can be extended with heartbeat

### Established Patterns
- Background tasks via `asyncio.create_task()` in bot.py — use same pattern for heartbeat loop
- `MT5Connector` base class with `connect()`/`disconnect()` — extend with `ping()` or `is_alive()` method
- `executor.execute_signal()` checks `connector.connected` before executing — extend with `reconnecting` flag check

### Integration Points
- `bot.py` — Wire heartbeat task startup alongside existing background tasks
- `dashboard.py` — Add POST /emergency-close endpoint
- `executor.py` — Add `trading_paused` flag, check before signal execution
- `trade_manager.py` — Zone logic extraction, stale re-check before order_send

</code_context>

<specifics>
## Specific Ideas

- Kill switch confirmation shows position count and pending order count before executing
- "TRADING PAUSED" banner should be prominent in dashboard — can't be missed
- Reconnection events logged to database audit trail for post-incident review

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-reliability*
*Context gathered: 2026-03-22*
