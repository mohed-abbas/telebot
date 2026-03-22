# Phase 2: Reliability - Research

**Researched:** 2026-03-22
**Domain:** MT5 reconnection, kill switch, execution correctness, position safety
**Confidence:** HIGH

## Summary

Phase 2 transforms the bot from a fragile single-connection system into a resilient trading engine that recovers from MT5 disconnections, provides emergency controls, and ensures execution correctness. The primary technical challenges are: (1) implementing a heartbeat/reconnect loop for MT5 connections via the mt5linux RPyC bridge, (2) coordinating signal handling during reconnection to prevent stale-data execution, (3) building a kill switch that reliably closes all positions AND cancels all pending orders, and (4) fixing several execution correctness bugs in trade_manager.py.

The codebase is well-structured for these changes. The MT5Connector abstraction layer, existing notifier methods, and asyncio task patterns in bot.py/executor.py provide clean integration points. The main risk is the mt5linux RPyC layer -- when the RPyC connection drops, it raises EOFError which must be caught and handled at every MT5 call site. The heartbeat implementation should use MT5's `terminal_info()` call (which returns a `connected` property and `ping_last` latency) rather than raw RPyC pings, since we care about MT5-to-broker connectivity, not just RPyC-to-Wine connectivity.

**Primary recommendation:** Implement heartbeat as a separate asyncio task in executor.py that calls `terminal_info()` every 30s per connector. On failure, set a `reconnecting` flag, notify Discord, then enter exponential backoff reconnect loop. Signal handler in bot.py checks `executor.is_accepting_signals()` before dispatching.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Kill switch behavior**: Confirm first before closing -- show summary of open positions and pending orders, require user confirmation before executing emergency close. Global scope only -- one button kills all accounts (no per-account granularity). After activation: close all positions, cancel all pending orders, pause executor. Re-enable via dashboard toggle with clear "TRADING PAUSED" state banner. Always send Discord alert (#alerts) on both activation and re-enable -- `notify_kill_switch()` already exists in notifier.py.
- **Reconnection behavior**: Drop signals during reconnect with Discord alert ("Signal skipped -- MT5 reconnecting") -- do not queue or replay. Exponential backoff: 1s, 2s, 4s, 8s... up to 60s max between reconnect attempts. Unlimited retries -- keep trying forever with backoff; Discord alerts keep user informed. Heartbeat every 30s -- check MT5 connection health via ping. After reconnect: full position sync from MT5 before accepting new signals. Set `reconnecting` flag that signal handler checks before processing.
- **Daily limit warnings**: Warnings appear in both dashboard and Discord #alerts. Warn at 80% threshold (e.g., 24/30 trades). Dashboard shows per-account counter: "Trades: 12/30" with color coding (green/yellow/red). `notify_daily_limit()` already exists in notifier.py for Discord alerts.

### Claude's Discretion
- Zone-based SELL boundary fix (EXEC-01): exact fix approach, test cases
- Stale signal double-check (EXEC-02): implementation location in execution flow
- SL/TP modification validation (EXEC-03): what constitutes "valid" for each direction
- Pending order cleanup race fix (REL-04): retry queue implementation details
- Database archival mechanism (DB-03): archive format, retention period logic
- Dashboard endpoint structure for kill switch (POST /emergency-close)
- Heartbeat implementation: separate asyncio task vs. integrated into executor loop
- Position reconciliation algorithm after reconnect

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| REL-01 | MT5 heartbeat check (30s), auto-reconnect with exponential backoff, Discord alerts on disconnect/restore | Heartbeat via `terminal_info().connected`, RPyC EOFError handling, backoff pattern documented below |
| REL-02 | After reconnect, full position sync before accepting signals; stale state via last_sync_time | Reconnecting flag pattern, position reconciliation algorithm documented below |
| REL-03 | Dashboard kill switch: close all positions, cancel all pending orders, pause executor, manual re-enable | Two-step confirm-then-execute pattern, endpoint structure, HTMX integration documented |
| REL-04 | Pending order cleanup verifies MT5 state before cancel; distinguishes filled vs failed; retries | MT5 `orders_get()` for state check, retry with backoff for failed cancellations |
| EXEC-01 | Zone-based SELL boundary fix; extracted into testable functions | Current bug analysis and fix approach documented |
| EXEC-02 | Stale signal check runs again immediately before order placement | TOCTOU analysis and re-check insertion point documented |
| EXEC-03 | SL/TP modifications validate direction before sending to MT5 | Validation rules per direction documented |
| EXEC-04 | Dashboard shows daily trade limit per account with warnings approaching limit | 80% threshold, color coding, existing template integration documented |
| DB-03 | Database archival: trades >3 months to CSV; maintenance command | asyncpg COPY protocol, archive function design documented |
</phase_requirements>

## Standard Stack

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | 0.31.0 | PostgreSQL async client | Already migrated in Phase 1; pool supports COPY for archival |
| FastAPI | 0.115.0 | Dashboard REST + HTMX | Already in use; POST endpoints for kill switch |
| httpx | 0.28.1 | HTTP client for Discord webhooks | Already in use via notifier.py |
| Jinja2 | 3.1.4 | Dashboard templates | Already in use; extend for kill switch UI |

### Supporting (no new dependencies needed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncio (stdlib) | 3.x | Background tasks, event coordination | Heartbeat loop, reconnect backoff, signal gating |
| datetime/csv (stdlib) | 3.x | Archival to CSV | DB-03 archive mechanism |
| logging (stdlib) | 3.x | Structured event logging | Reconnect events, kill switch audit trail |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled backoff | `tenacity` or `backoff` library | Adding a dependency for ~20 lines of code; not worth it for this use case since we need custom reconnect logic with flag management |
| Separate heartbeat process | Integrated asyncio task | Separate process adds IPC complexity; asyncio task is sufficient for single-process bot |

**No new pip packages needed.** All Phase 2 work uses existing dependencies plus stdlib.

## Architecture Patterns

### Recommended Changes to Existing Structure
```
(existing files, modified)
mt5_connector.py     # Add ping() method, reconnect(), handle EOFError
executor.py          # Add heartbeat loop, kill switch, trading_paused flag, reconnecting flag
trade_manager.py     # Fix zone logic (EXEC-01), add stale re-check (EXEC-02), SL/TP validation (EXEC-03), fix cleanup race (REL-04)
dashboard.py         # Add kill switch endpoints (GET preview + POST execute), daily limit display
bot.py               # Wire heartbeat task, gate signal dispatch on executor state
db.py                # Add archive functions, reconnect event logging
notifier.py          # Already complete -- just wire existing methods
templates/           # Update overview_cards.html for limits, add kill switch UI
```

### Pattern 1: Heartbeat + Reconnect Loop (REL-01, REL-02)

**What:** A dedicated asyncio task that periodically checks MT5 connection health and triggers reconnection when failures are detected.

**When to use:** Always running as a background task alongside the cleanup loop.

**Architecture:**
```python
# In executor.py — Executor class

class Executor:
    def __init__(self, trade_manager, global_config, notifier):
        self.tm = trade_manager
        self.cfg = global_config
        self.notifier = notifier
        self._trading_paused = False      # Kill switch flag
        self._reconnecting: set[str] = set()  # Account names currently reconnecting
        self._last_sync: dict[str, float] = {}  # account -> timestamp of last sync
        self._heartbeat_task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None

    def is_accepting_signals(self) -> bool:
        """Check if executor can process new signals."""
        if self._trading_paused:
            return False
        # Accept if at least one account is connected and not reconnecting
        for name, conn in self.tm.connectors.items():
            if conn.connected and name not in self._reconnecting:
                return True
        return False

    async def _heartbeat_loop(self) -> None:
        """Check MT5 connection health every 30s."""
        while True:
            try:
                await asyncio.sleep(30)
                for acct_name, connector in self.tm.connectors.items():
                    if acct_name in self._reconnecting:
                        continue  # Already reconnecting
                    alive = await connector.ping()
                    if not alive:
                        # Connection lost — start reconnect
                        asyncio.create_task(
                            self._reconnect_account(acct_name, connector)
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Heartbeat error: %s", exc)

    async def _reconnect_account(self, acct_name, connector) -> None:
        """Reconnect a single account with exponential backoff."""
        self._reconnecting.add(acct_name)
        await self.notifier.notify_connection_lost(acct_name, "Heartbeat failed")

        delay = 1.0
        max_delay = 60.0

        while True:
            await asyncio.sleep(delay)
            try:
                await connector.disconnect()
                success = await connector.connect()
                if success:
                    # Full position sync before accepting signals
                    await self._sync_positions(acct_name, connector)
                    self._reconnecting.discard(acct_name)
                    self._last_sync[acct_name] = time.time()
                    await self.notifier.notify_connection_restored(acct_name)
                    logger.info("%s: Reconnected and synced", acct_name)
                    return
            except Exception as exc:
                logger.error("%s: Reconnect attempt failed: %s", acct_name, exc)

            delay = min(delay * 2, max_delay)
```

**Key design decisions:**
- `_reconnecting` is a set of account names, not a single bool -- allows per-account reconnection
- Signal handler checks `is_accepting_signals()` which returns True if ANY account is available
- Per-account reconnect runs as its own task so heartbeat loop continues checking other accounts
- Password was cleared after initial connect (SEC-04) -- reconnect needs the password stored in config, so reconnect must use `create_connector()` with the original credentials, OR the connector must retain credentials for reconnect. Since password is cleared, reconnect should call `disconnect()` + `connect()` on the existing connector object, but connect() will fail because password is empty. **This is a critical design issue -- see Open Questions.**

### Pattern 2: Kill Switch Two-Step (REL-03)

**What:** Dashboard GET endpoint returns position/order summary for confirmation, POST endpoint executes the emergency close.

**Design:**
```python
# In dashboard.py

@app.get("/api/emergency-preview", response_class=HTMLResponse)
async def emergency_preview(request: Request, user: str = Depends(_verify_auth)):
    """Show what kill switch will do before executing."""
    positions = await _get_all_positions()
    pending_orders = await _get_all_pending_orders()
    return templates.TemplateResponse("partials/kill_switch_preview.html", {
        "request": request,
        "positions": positions,
        "pending_orders": pending_orders,
        "position_count": len(positions),
        "order_count": len(pending_orders),
    })

@app.post("/api/emergency-close")
async def emergency_close(user: str = Depends(_verify_auth)):
    """Execute emergency close: close all positions, cancel all orders, pause executor."""
    if not _executor:
        raise HTTPException(status_code=503, detail="Trading not initialized")

    results = await _executor.emergency_close()
    if _notifier:
        await _notifier.notify_kill_switch(activated=True)
    return {"status": "killed", "results": results}

@app.post("/api/resume-trading")
async def resume_trading(user: str = Depends(_verify_auth)):
    """Re-enable trading after kill switch."""
    if not _executor:
        raise HTTPException(status_code=503, detail="Trading not initialized")

    _executor.resume_trading()
    if _notifier:
        await _notifier.notify_kill_switch(activated=False)
    return {"status": "resumed"}
```

**HTMX integration:** Kill switch button triggers `hx-get="/api/emergency-preview"` to load confirmation modal. Confirm button triggers `hx-post="/api/emergency-close"`. The "TRADING PAUSED" banner uses `hx-get` polling to check `_executor._trading_paused` state.

### Pattern 3: Signal Gating in bot.py

**What:** Before dispatching signals to executor, check if trading is active.

```python
# In bot.py handler

if signal:
    if executor and settings.trading_enabled:
        if not executor.is_accepting_signals():
            # Trading paused or all accounts reconnecting
            if executor._trading_paused:
                logger.info("Signal ignored — kill switch active")
            else:
                logger.info("Signal skipped — MT5 reconnecting")
                if notifier:
                    await notifier.notify_alert(
                        f"SIGNAL SKIPPED (reconnecting): {signal.symbol} {signal.direction.value if signal.direction else ''}"
                    )
        else:
            results = await executor.execute_signal(signal)
            if notifier:
                await notifier.notify_execution(signal, results)
```

### Pattern 4: Pending Order Cleanup Race Fix (REL-04)

**What:** Before cancelling an expired order, verify its current state on MT5.

```python
# In trade_manager.py — cleanup_expired_orders()

async def cleanup_expired_orders(self) -> list[dict]:
    expired = await db.get_expired_pending_orders()
    results = []
    for order in expired:
        acct_name = order["account_name"]
        connector = self.connectors.get(acct_name)
        if not connector or not connector.connected:
            continue

        # REL-04: Check MT5 state before cancelling
        mt5_orders = await connector.get_pending_orders(order["symbol"])
        mt5_tickets = {o["ticket"] for o in mt5_orders}

        if order["ticket"] not in mt5_tickets:
            # Order no longer pending on MT5 — check if it filled
            positions = await connector.get_positions(order["symbol"])
            filled = any(
                p.comment and str(order["ticket"]) in p.comment
                for p in positions
            )
            if filled:
                await db.mark_pending_filled(order["ticket"], acct_name)
                logger.info("%s: Expired order #%d was filled", acct_name, order["ticket"])
            else:
                # Order gone but not filled — already cancelled by broker or expired
                await db.mark_pending_cancelled(order["id"])
                logger.info("%s: Expired order #%d already removed from MT5", acct_name, order["ticket"])
            continue

        # Order still pending on MT5 — cancel it
        result = await connector.cancel_pending(order["ticket"])
        if result.success:
            await db.mark_pending_cancelled(order["id"])
        else:
            # Cancel failed — log and retry next cycle
            logger.warning(
                "%s: Failed to cancel order #%d: %s — will retry",
                acct_name, order["ticket"], result.error,
            )
        results.append({...})
    return results
```

**Note:** Detecting "filled" by matching ticket in position comment is imperfect. MT5 does not guarantee the comment carries the original order ticket. A more robust approach: if the pending order is gone from MT5 and a position for the same symbol/direction exists that wasn't there before, mark as filled. The exact heuristic is implementation detail.

### Anti-Patterns to Avoid
- **Queuing signals during reconnect:** User explicitly decided to DROP signals during reconnect, not queue them. Queuing risks stale-data execution cascade (Pitfall #2).
- **Single global `reconnecting` boolean:** Must be per-account. If account A reconnects, account B should still trade.
- **Kill switch that only closes positions:** Must also cancel pending orders (Pitfall #3). Forgetting pending orders leads to phantom fills later.
- **Heartbeat that calls `get_positions()`:** Too heavy for 30s interval across N accounts. Use lightweight `terminal_info()` or `account_info()` instead.
- **Reconnect without `shutdown()` first:** RPyC requires clean disconnect before reconnect. Calling `initialize()` without `shutdown()` first causes resource leaks.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CSV export from PostgreSQL | Row-by-row fetchall + csv.writer | asyncpg `copy_from_query()` with `format='csv'` | 10-100x faster for bulk export; handles escaping correctly |
| Connection health check | Raw socket check to RPyC port | MT5's `terminal_info().connected` via mt5linux | Checks actual MT5-to-broker connectivity, not just RPyC pipe |
| Exponential backoff timing | Custom delay calculation | `min(base * 2**attempt, max_delay)` with attempt counter | Simple formula, no library needed, but don't forget the cap |

**Key insight:** The mt5linux layer (Wine + RPyC) adds complexity. Connection failures can happen at two levels: RPyC connection drop (EOFError) and MT5-to-broker disconnect (terminal_info.connected=false). The heartbeat must detect both.

## Common Pitfalls

### Pitfall 1: Reconnect Without Password (SEC-04 Conflict)
**What goes wrong:** Phase 1 implemented SEC-04 by clearing `self.password = ""` after successful connect. But reconnect needs the password to call `connect()` again. The connector has no password.
**Why it happens:** SEC-04 (clear password from memory) conflicts with REL-01 (auto-reconnect needs password).
**How to avoid:** Store the password in a separate secure attribute that is ONLY used by `connect()`. Or better: re-read the password from the environment variable at reconnect time. The `password_env` field in AccountConfig has the env var name -- use `os.environ.get(acct.password_env)` at reconnect time. This is both secure (password not in connector memory) and functional (can reconnect).
**Warning signs:** Reconnect always fails with "login failed" or empty password error.

### Pitfall 2: RPyC EOFError Not Caught in MT5 Operations
**What goes wrong:** Any MT5 call (get_price, open_order, etc.) can raise EOFError if RPyC connection dropped since last heartbeat. Unhandled EOFError crashes the signal handler.
**Why it happens:** 30s heartbeat interval means up to 30s window where connection is dead but not detected.
**How to avoid:** Wrap all MT5LinuxConnector methods in try/except that catches `(EOFError, ConnectionError, Exception)`. On EOFError, set `self._connected = False` and return error result. The heartbeat will detect and start reconnect.
**Warning signs:** Unhandled exception in trade execution logs; signal processing stops entirely.

### Pitfall 3: Kill Switch Race with Concurrent Signal
**What goes wrong:** Kill switch starts closing positions. Meanwhile, a signal arrives and opens a new position on an account that hasn't been killed yet.
**Why it happens:** Kill switch iterates accounts sequentially. Between closing account A and account B, a signal executes on account B.
**How to avoid:** Set `_trading_paused = True` FIRST, before starting any close operations. The signal gating check in bot.py will reject new signals immediately. Then proceed with position/order cleanup.
**Warning signs:** Position appears after kill switch was pressed.

### Pitfall 4: Daily Limit Warning Floods Discord
**What goes wrong:** At 80% threshold, every subsequent trade sends another "approaching limit" Discord alert. With 6 remaining trades, user gets 6 identical warnings.
**Why it happens:** Warning fires on every trade that exceeds threshold, not just the first crossing.
**How to avoid:** Track "warning already sent today" flag per account (in daily_stats or in-memory). Only send Discord alert on first threshold crossing. Dashboard always shows current count regardless.
**Warning signs:** Discord #alerts flooded with identical limit messages.

### Pitfall 5: Archival Deletes Active Data
**What goes wrong:** Archive query uses date threshold but a 4-month-old trade might still have an open position (pending order that filled late, or position held for months).
**Why it happens:** Archive considers timestamp only, not trade status.
**How to avoid:** Archive only trades with status='closed' AND close_time older than 3 months. Never archive 'opened' or 'pending' status trades regardless of age.
**Warning signs:** Dashboard shows missing trades; open position has no corresponding trade record.

### Pitfall 6: Stale Re-Check TOCTOU Window (EXEC-02)
**What goes wrong:** Even with the re-check before order placement, the price can still move between re-check and `order_send()`. The re-check reduces but doesn't eliminate the window.
**Why it happens:** Network latency to MT5 terminal is non-zero. Price is always slightly stale.
**How to avoid:** Accept that the window exists but is now measured in milliseconds instead of seconds. The re-check catches the common case (signal received 10s ago, price moved significantly). Don't add more checks -- diminishing returns.
**Warning signs:** None needed -- this is accepted residual risk.

## Code Examples

### MT5Connector.ping() Implementation
```python
# In mt5_connector.py — MT5LinuxConnector class

async def ping(self) -> bool:
    """Check if MT5 connection is alive. Returns True if healthy."""
    if not self._mt5:
        return False
    try:
        info = self._mt5.terminal_info()
        if info is None:
            return False
        return bool(info.connected)
    except (EOFError, ConnectionError, OSError) as exc:
        logger.warning("%s: Ping failed: %s", self.account_name, exc)
        self._connected = False
        return False
    except Exception as exc:
        logger.error("%s: Unexpected ping error: %s", self.account_name, exc)
        self._connected = False
        return False
```

For DryRunConnector:
```python
async def ping(self) -> bool:
    """Dry-run connector is always alive."""
    return self._connected
```

### MT5LinuxConnector Reconnect-Safe Method Wrapper
```python
# In mt5_connector.py — add to all MT5LinuxConnector methods

async def get_price(self, symbol: str) -> tuple[float, float] | None:
    if not self._mt5 or not self._connected:
        return None
    try:
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return (tick.bid, tick.ask)
    except (EOFError, ConnectionError, OSError):
        # RPyC connection dropped
        self._connected = False
        return None
    except Exception as exc:
        logger.error("%s: get_price failed: %s", self.account_name, exc)
        return None
```

### Zone Logic Fix (EXEC-01)
```python
# In trade_manager.py — extract into named functions

def is_price_in_buy_zone(current_price: float, zone_low: float, zone_high: float) -> bool:
    """BUY: execute market if price is at or below zone high."""
    return current_price <= zone_high

def is_price_in_sell_zone(current_price: float, zone_low: float, zone_high: float) -> bool:
    """SELL: execute market if price is at or above zone low.

    Note: zone_low is the acceptable minimum for selling.
    At exactly zone_low, we still execute market because price is
    within the zone boundary (inclusive).
    """
    return current_price >= zone_low

def determine_order_type(
    direction: Direction,
    current_price: float,
    zone_low: float,
    zone_high: float,
) -> tuple[bool, float]:
    """Determine market vs limit order and the limit price.

    Returns: (use_market: bool, limit_price: float)

    BUY zones:  price <= zone_high -> market, else buy_limit at zone_mid
    SELL zones: price >= zone_low  -> market, else sell_limit at zone_mid
    """
    zone_mid = (zone_low + zone_high) / 2

    if direction == Direction.SELL:
        if is_price_in_sell_zone(current_price, zone_low, zone_high):
            return True, 0.0
        else:
            return False, zone_mid
    else:  # BUY
        if is_price_in_buy_zone(current_price, zone_low, zone_high):
            return True, 0.0
        else:
            return False, zone_mid
```

The current SELL logic (`current_price >= zone_low`) is actually correct for the stated semantics ("sell high, zone is the acceptable area"). The fix for EXEC-01 is primarily about: (1) extracting into testable functions, (2) documenting the boundary behavior, and (3) adding comprehensive test cases for edge prices (at zone_low, at zone_high, between, outside).

### SL/TP Validation (EXEC-03)
```python
# In trade_manager.py — add before modify_position calls

def validate_sl_for_direction(direction: str, open_price: float, new_sl: float) -> bool:
    """Validate that SL makes sense for position direction.

    BUY: SL must be below open_price (we lose if price drops)
    SELL: SL must be above open_price (we lose if price rises)
    """
    if new_sl <= 0:
        return False
    if direction == "buy":
        return new_sl < open_price
    elif direction == "sell":
        return new_sl > open_price
    return False

def validate_tp_for_direction(direction: str, open_price: float, new_tp: float) -> bool:
    """Validate that TP makes sense for position direction.

    BUY: TP must be above open_price (we profit if price rises)
    SELL: TP must be below open_price (we profit if price drops)
    """
    if new_tp <= 0:
        return False
    if direction == "buy":
        return new_tp > open_price
    elif direction == "sell":
        return new_tp < open_price
    return False
```

### Stale Re-Check Before Order Placement (EXEC-02)
```python
# In trade_manager.py — _execute_open_on_account(), right before the Execute block

    # ── EXEC-02: Re-check stale immediately before order ────────────
    price_data_recheck = await connector.get_price(signal.symbol)
    if price_data_recheck is None:
        return {"account": name, "status": "failed", "reason": "Cannot get price for re-check"}
    bid_recheck, ask_recheck = price_data_recheck
    current_recheck = bid_recheck if signal.direction == Direction.SELL else ask_recheck
    stale_recheck = self._check_stale(signal, current_recheck)
    if stale_recheck:
        logger.info("%s: Stale on re-check — %s", name, stale_recheck)
        return {"account": name, "status": "skipped", "reason": f"Stale (re-check): {stale_recheck}"}

    # ── Execute ─────────────────────────────────────────────────────
```

### Database Archival (DB-03)
```python
# In db.py — new archive functions

import csv
import io
from pathlib import Path

async def archive_old_trades(archive_dir: str, months: int = 3) -> dict:
    """Archive closed trades older than N months to CSV files.

    Returns: {"archived_count": int, "file_path": str}
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
    archive_path = Path(archive_dir)
    archive_path.mkdir(parents=True, exist_ok=True)

    filename = f"trades_archive_{cutoff.strftime('%Y%m%d')}.csv"
    filepath = archive_path / filename

    async with _pool.acquire() as conn:
        # Export to CSV using COPY protocol (fast)
        count_row = await conn.fetchval(
            "SELECT COUNT(*) FROM trades WHERE status='closed' AND close_time < $1",
            cutoff,
        )

        if count_row == 0:
            return {"archived_count": 0, "file_path": ""}

        # Use copy_from_query for efficient CSV export
        result = await conn.copy_from_query(
            "SELECT * FROM trades WHERE status='closed' AND close_time < $1 ORDER BY id",
            cutoff,
            output=str(filepath),
            format='csv',
            header=True,
        )

        # Delete archived rows
        await conn.execute(
            "DELETE FROM trades WHERE status='closed' AND close_time < $1",
            cutoff,
        )

    return {"archived_count": count_row, "file_path": str(filepath)}
```

### Daily Limit Display with Color Coding (EXEC-04)
```html
<!-- In templates/partials/overview_cards.html — replace daily trades line -->

{% set limit = 30 %}
{% set pct = (a.daily_trades / limit * 100) if limit > 0 else 0 %}
<div class="text-slate-400">Trades</div>
<div class="text-right font-mono text-sm
    {% if pct >= 100 %}text-red-400 font-bold
    {% elif pct >= 80 %}text-yellow-400
    {% else %}text-green-400{% endif %}">
    {{ a.daily_trades }} / {{ limit }}
</div>
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No reconnect (restart bot) | Heartbeat + auto-reconnect with backoff | Phase 2 | Bot survives MT5 disconnections |
| No kill switch (use MT5 terminal) | Dashboard kill switch with confirm | Phase 2 | Emergency controls accessible remotely |
| Single stale check at signal receipt | Double-check before order placement | Phase 2 | Reduced TOCTOU window for stale signals |
| Pending cleanup blindly cancels | Check MT5 state first, distinguish filled/failed | Phase 2 | No more false "cancelled" for filled orders |

**Deprecated/outdated:**
- SQLite db.py: Fully replaced by asyncpg in Phase 1. No sqlite3 references remain.
- Global asyncio.Lock for DB: Removed in Phase 1 with connection pool migration.

## Open Questions

1. **Password availability for reconnect**
   - What we know: SEC-04 clears `self.password = ""` after connect. Reconnect needs password.
   - What's unclear: Whether re-reading from env var at reconnect time is acceptable, or if we need a different approach.
   - Recommendation: Re-read from env var at reconnect time using `os.environ.get(acct.password_env)`. This keeps password out of connector memory between uses. The MT5LinuxConnector needs access to the AccountConfig or the password_env name. Add `password_env` parameter to connector constructor, and a `_get_password()` method that reads from env. Modify `connect()` to accept an optional password parameter for reconnect.

2. **Heartbeat and RPyC blocking**
   - What we know: mt5linux calls are synchronous (RPyC over Wine). The `async def connect()` in MT5LinuxConnector is async in signature but blocks the event loop during `self._mt5.initialize()` and `self._mt5.login()`.
   - What's unclear: Whether 30s heartbeat `terminal_info()` call blocks the event loop noticeably.
   - Recommendation: `terminal_info()` is a lightweight call (no trade execution). Blocking should be <100ms. If it becomes an issue, wrap in `asyncio.to_thread()`. For Phase 2, the direct call is acceptable -- optimize only if latency observed.

3. **Kill switch confirmation in HTMX**
   - What we know: Dashboard uses HTMX for live updates. Kill switch needs two-step confirm.
   - Recommendation: Use HTMX modal pattern: button triggers `hx-get="/api/emergency-preview"` to load a confirmation dialog into a modal div. The dialog shows position/order counts and a red "CONFIRM CLOSE ALL" button that triggers `hx-post="/api/emergency-close"`. This keeps it server-rendered, consistent with existing HTMX patterns.

4. **Max daily trades limit source for dashboard**
   - What we know: Settings page hardcodes "/ 30" and "/ 500". The actual limits come from GlobalConfig.
   - Recommendation: Pass `max_daily_trades_per_account` from GlobalConfig to the dashboard context so the threshold and display use the same value. The 80% warning calculation also needs this value.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (not yet in requirements.txt -- Phase 4 concern) |
| Config file | none -- no pytest.ini or pyproject.toml |
| Quick run command | `python -m pytest test_trade_manager.py -x` |
| Full suite command | `python -m pytest -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REL-01 | Heartbeat detects disconnect, reconnect with backoff | manual-only | N/A (requires MT5 terminal) | No |
| REL-02 | Position sync after reconnect, signals blocked during reconnect | unit | `python -m pytest test_executor.py::test_reconnect_blocks_signals -x` | No (Wave 0) |
| REL-03 | Kill switch closes positions, cancels orders, pauses trading | unit | `python -m pytest test_executor.py::test_kill_switch -x` | No (Wave 0) |
| REL-04 | Cleanup distinguishes filled vs failed, retries | unit | `python -m pytest test_trade_manager.py::test_cleanup_race -x` | No (Wave 0) |
| EXEC-01 | Zone logic boundary conditions | unit | `python -m pytest test_trade_manager.py::test_zone_boundaries -x` | No (Wave 0) |
| EXEC-02 | Stale re-check before order placement | unit | `python -m pytest test_trade_manager.py::test_stale_recheck -x` | No (Wave 0) |
| EXEC-03 | SL/TP validation per direction | unit | `python -m pytest test_trade_manager.py::test_sl_tp_validation -x` | No (Wave 0) |
| EXEC-04 | Daily limit display and warning threshold | manual-only | N/A (visual dashboard check) | No |
| DB-03 | Archival exports closed trades >3mo to CSV | unit | `python -m pytest test_db.py::test_archive -x` | No (Wave 0) |

### Sampling Rate
- **Per task commit:** `python -m pytest test_trade_manager.py -x` (existing + new tests)
- **Per wave merge:** `python -m pytest -x` (full suite)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `test_executor.py` -- covers REL-02, REL-03 (kill switch, reconnect signal blocking)
- [ ] `test_trade_manager.py` -- extend existing file for EXEC-01, EXEC-02, EXEC-03, REL-04
- [ ] `test_db.py` -- covers DB-03 (archival)
- [ ] Test fixtures need updating: current tests use sync sqlite3 `init_db()` which is pre-Phase-1. Tests need async fixtures with asyncpg and a test PostgreSQL database (or mock the pool).

**Note:** Full test infrastructure (pytest in requirements, conftest.py, async fixtures) is a Phase 4 concern. Phase 2 tests should use the minimal inline approach -- directly instantiate DryRunConnector and test the logic without DB calls where possible. For DB-dependent tests, they may need to be deferred to Phase 4 or use a test PostgreSQL instance.

## Sources

### Primary (HIGH confidence)
- MQL5 Python Integration docs (https://www.mql5.com/en/docs/python_metatrader5) -- terminal_info() properties, connection checking
- MQL5 terminal_info docs (https://www.mql5.com/en/docs/python_metatrader5/mt5terminalinfo_py) -- `connected` and `ping_last` properties confirmed
- RPyC Protocol docs (https://rpyc.readthedocs.io/en/latest/api/core_protocol.html) -- `Connection.ping()`, `closed` property, EOFError behavior
- asyncpg API docs (https://magicstack.github.io/asyncpg/current/api/index.html) -- `copy_from_query()` for CSV export, pool management
- RPyC GitHub issues (#265, #258, #424) -- EOFError handling patterns for connection drops

### Secondary (MEDIUM confidence)
- Codebase analysis of mt5_connector.py, executor.py, trade_manager.py, dashboard.py, bot.py -- direct code inspection
- .planning/codebase/CONCERNS.md, .planning/research/PITFALLS.md -- pre-existing project analysis
- GitHub lucas-campagna/mt5linux -- confirmed RPyC architecture, no built-in reconnect

### Tertiary (LOW confidence)
- Community patterns for asyncio heartbeat loops -- general patterns, not specific to mt5linux
- FastAPI two-step confirmation pattern -- no standard library pattern found; HTMX modal is ad-hoc but well-established in HTMX community

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies, all existing libraries
- Architecture: HIGH -- heartbeat/reconnect is well-understood asyncio pattern; code examples verified against actual codebase
- Pitfalls: HIGH -- derived from actual codebase analysis and documented concerns
- Kill switch: HIGH -- straightforward FastAPI + HTMX pattern, existing notifier methods
- Zone logic fix (EXEC-01): MEDIUM -- current logic may actually be correct; needs test cases to confirm boundary behavior
- Password reconnect issue: HIGH -- confirmed conflict between SEC-04 and REL-01, solution identified
- RPyC connection handling: MEDIUM -- based on RPyC docs and issues, not mt5linux-specific testing

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable domain, no library version changes expected)
