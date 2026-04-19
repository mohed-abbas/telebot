# Phase 6: staged-entry-execution — Pattern Map

**Mapped:** 2026-04-19
**Files analyzed:** 20 (8 extended + 12 new)
**Analogs found:** 20 / 20

This document tells the planner *which existing file each new/extended file should copy from*. Every pattern reference includes the source file and line numbers so plans can quote the analog verbatim. The codebase has already established a clean layered async pattern (Telegram → parser → TradeManager → Executor → MT5 connector → db) with asyncpg pool, frozen dataclasses, Jinja + HTMX templates, Basecoat UI compat-shim, and pytest-asyncio fixtures — Phase 6 follows all of it.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `signal_parser.py` (extend) | parser | transform | `signal_parser.py::_RE_OPEN` + `_build_open_signal` | self (extend) |
| `signal_correlator.py` (NEW) | correlator / state | event-driven, in-memory window | `executor.py::Executor._reconnecting` (set with asyncio guards) | role-match |
| `models.py` (extend) | model | data-definition | `models.py::SignalType`, `AccountSettings` | self (extend) |
| `db.py` (extend — DDL + helpers) | db | CRUD | `db.py::_create_tables`, `log_pending_order`, `mark_pending_filled`, `update_account_setting` | self (extend) |
| `executor.py` (extend — `_zone_watch_loop`, drain, reconcile) | executor / scheduler | polling / event-driven | `executor.py::_heartbeat_loop`, `_cleanup_loop`, `_sync_positions`, `emergency_close` | exact |
| `trade_manager.py` (edits at :215, :263-270, :168-172, :289) | orchestrator | request-response | `trade_manager.py::_execute_open_on_account` | self (extend) |
| `bot.py` (wire correlator + zone-watcher startup) | entrypoint | bootstrap | `bot.py::_setup_trading` (SettingsStore wiring) | self (extend) |
| `dashboard.py` (+ `/settings/{account}` POST, `/staged` GET, SSE payload) | route | request-response + streaming | `dashboard.py::sse_stream`, `emergency_preview`, `modify_sl` | self (extend) |
| `templates/settings.html` (REWRITE) | template | render | `templates/overview.html` + `templates/partials/kill_switch_preview.html` (card + modal pattern) | role-match |
| `templates/staged.html` (NEW) | template | render | `templates/overview.html` (page shell) | role-match |
| `templates/partials/pending_stages.html` (NEW) | template | render / SSE swap | `templates/partials/positions_table.html` | exact |
| `templates/partials/account_settings_tab.html` (NEW) | template | render | `templates/partials/overview_cards.html` (card layout) | role-match |
| `templates/partials/settings_audit_timeline.html` (NEW) | template | render | `templates/partials/positions_table.html` (table) | role-match |
| `templates/overview.html` (edit — insert partial include) | template | render | `templates/overview.html` existing `{% include "partials/positions_table.html" %}` | self (extend) |
| `tests/test_signal_parser_text_only.py` (NEW) | test | unit | `tests/test_signal_parser.py::TestOpenSignalsZone` | exact |
| `tests/test_correlator.py` (NEW) | test | unit | `tests/test_settings_store.py` (module-level pytestmark, pytest-asyncio fixtures) | role-match |
| `tests/test_staged_executor.py` (NEW) | test | integration | `tests/test_trade_manager_integration.py::PricedDryRunConnector` | exact |
| `tests/test_staged_safety_hooks.py` (NEW) | test | integration | `tests/test_trade_manager_integration.py` + `tests/test_settings.py` audit checks | role-match |
| `tests/test_staged_attribution.py` (NEW) | test | integration | `tests/test_settings.py::test_audit_per_field_write` | role-match |
| `tests/test_staged_db.py` (NEW) | test | unit + db | `tests/test_settings.py`, `tests/test_db_schema.py` | exact |
| `tests/test_settings_form.py` (NEW) | test | route / integration | `tests/test_settings.py` + `tests/test_login_flow.py` | role-match |
| `tests/test_pending_stages_sse.py` (NEW) | test | integration (streaming) | `tests/test_settings.py` (FastAPI async test) | role-match |

---

## Pattern Assignments

### `signal_parser.py` — add text-only "now" recognizer (D-01/D-02)

**Analog:** `signal_parser.py` itself — add a new `_RE_OPEN_TEXT_ONLY` that runs AFTER `_RE_OPEN` so existing follow-up shape (with numerics) wins.

**Existing regex block (copy structure)** — `signal_parser.py:29-46`:
```python
# New trade: "Gold sell now 4978 - 4982" or "XAUUSD BUY 2150-2155"
_RE_OPEN = re.compile(
    r"(?P<symbol>gold|xauusd|xau/?usd|xau)\s+"
    r"(?P<direction>buy|sell)\s+"
    r"(?:now\s+)?"
    r"(?P<price1>[\d]+(?:\.[\d]+)?)\s*[-–—]\s*(?P<price2>[\d]+(?:\.[\d]+)?)",
    re.IGNORECASE,
)
```

**Priority dispatch pattern to extend** — `signal_parser.py:134-216`:
```python
def parse_signal(text: str) -> SignalAction | None:
    """...Priority order:
    1. Close all  2. Partial close  3. SL to breakeven  4. SL update
    5. TP update  6. New trade (zone or single price)"""
    # ...
    # ── 6. New trade (zone entry) ──
    open_match = _RE_OPEN.search(stripped)
    if open_match:
        return _build_open_signal(open_match, stripped, text, zone=True)
    # ── 7. New trade (single price fallback) ──
    open_single = _RE_OPEN_SINGLE.search(stripped)
    if open_single:
        return _build_open_signal(open_single, stripped, text, zone=False)
```

**Action:** Insert a new step 8 *after* step 7 (lower priority than `_RE_OPEN_SINGLE` — research §RESEARCH.md rank 8). The new `_RE_OPEN_TEXT_ONLY` matches `{symbol} {buy|sell} now` with the `now` keyword and rejects if any price digit appears in the remaining text (confirm text-only per D-02). Build with `SignalType.OPEN_TEXT_ONLY` and `entry_zone=None, sl=None, tps=[]`.

**Signal-like fallback preserved** — `signal_parser.py:214-215` (`is_signal_like` + logger.warning) stays as final branch.

---

### `signal_correlator.py` (NEW) — in-memory orphan dict (D-04..D-07)

**Analog:** `executor.py::Executor._reconnecting` (a `set[str]` protected by asyncio task scheduling) and `settings_store.py::SettingsStore` (async methods, logger pattern, KeyError raise-on-unknown).

**Imports pattern** (copy from `settings_store.py:1-20`):
```python
"""In-memory orphan-signal correlator for Phase 6 staged entries.

Tracks pending text-only signals per (symbol, direction) within a configurable
window. Follow-up signals are paired to the most-recent orphan one-to-one.
DB is the durable record via staged_entries.signal_id (D-07).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from models import Direction, SignalAction, SignalType

logger = logging.getLogger(__name__)
```

**State-container pattern** (mirror `Executor.__init__` style — `executor.py:27-38`):
```python
class SignalCorrelator:
    def __init__(self, window_seconds: int = 600):
        self._window = window_seconds
        self._orphans: dict[tuple[str, str], list[_PendingOrphan]] = {}
        self._lock = asyncio.Lock()
```

**Logger + warning idiom** (copy from `executor.py:160` / `signal_parser.py:248`):
```python
logger.info("Correlator: registered orphan signal_id=%d %s %s",
            signal_id, symbol, direction)
logger.warning("Correlator: no orphan matched for %s %s — treating as standalone OPEN",
               symbol, direction)
```

**Window-expiry helper** — model on `executor.py::_cleanup_loop` body (`executor.py:280-292`) but synchronous (called at every `register`/`pair`): iterate, drop entries where `time.time() - created_at > self._window`.

**Pair-up returns `signal_id | None`.** Follow-up callers branch on it: `if pair_id is not None: _handle_correlated_followup(signal, pair_id)` else `_handle_open(signal)` (v1.0 fallback per D-05).

---

### `models.py` — add `SignalType.OPEN_TEXT_ONLY` + optional `StagedEntryRecord`

**Analog:** `models.py::SignalType` (line 8-13) and `models.py::AccountSettings` (lines 74-91).

**Enum extension** — `models.py:8-13`:
```python
class SignalType(Enum):
    OPEN = "open"
    MODIFY_SL = "modify_sl"
    MODIFY_TP = "modify_tp"
    CLOSE = "close"
    CLOSE_PARTIAL = "close_partial"
```

**Action:** Add `OPEN_TEXT_ONLY = "open_text_only"` (research §Alternatives Considered: enum value preferred over a bool flag; existing switch statements in `trade_manager.py::handle_signal` extend cleanly).

**Frozen dataclass pattern to copy** — `models.py:74-91`:
```python
@dataclass(frozen=True, slots=True)
class AccountSettings:
    """Frozen per-account runtime settings — DB source of truth (Phase 5, D-27/D-32)."""
    account_name: str
    risk_mode: str
    risk_value: float
    # ...
```

**`StagedEntryRecord` (optional)** — same `frozen=True, slots=True` pattern for DB-row mapping. Keep all fields from D-37 (`id`, `signal_id`, `stage_number`, `account_name`, `symbol`, `direction`, `zone_low`, `zone_high`, `band_low`, `band_high`, `target_lot`, `snapshot_settings: dict | str` (JSONB), `mt5_comment`, `mt5_ticket: int | None`, `status`, `created_at: datetime`, `filled_at: datetime | None`, `cancelled_reason: str | None`).

---

### `db.py` — `staged_entries` DDL + helpers (D-37..D-39)

**Analog:** `db.py::_create_tables` (lines 77-209), `log_pending_order` (348-380), `get_expired_pending_orders` (383-390), `mark_pending_filled` (401-407), `update_account_setting` (607-633).

**DDL pattern** — `db.py:128-148` (pending_orders + index) is the closest shape:
```python
await conn.execute("""
    CREATE TABLE IF NOT EXISTS pending_orders (
        id SERIAL PRIMARY KEY,
        signal_id INTEGER REFERENCES signals(id),
        account_name TEXT NOT NULL,
        ticket BIGINT NOT NULL,
        symbol TEXT NOT NULL,
        order_type TEXT NOT NULL,
        volume DOUBLE PRECISION,
        price DOUBLE PRECISION,
        sl DOUBLE PRECISION,
        tp DOUBLE PRECISION,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at TIMESTAMPTZ NOT NULL,
        status TEXT DEFAULT 'active'
    )
""")
await conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_pending_orders_status
    ON pending_orders(status)
""")
```

**Additive discipline** — `db.py::_create_tables` uses `CREATE TABLE IF NOT EXISTS` everywhere and adds new indexes as separate `conn.execute` calls. `staged_entries` follows the same shape. Recommended index (Claude's discretion — RESEARCH §Open Questions): `CREATE INDEX IF NOT EXISTS idx_staged_entries_active ON staged_entries(status, account_name, signal_id)`.

**Insert-returning-id pattern** — `db.py::log_pending_order:364-380`:
```python
async def log_pending_order(...) -> int:
    """...Returns the order ID."""
    return await _pool.fetchval(
        """INSERT INTO pending_orders
           (signal_id, account_name, ticket, symbol, order_type,
            volume, price, sl, tp, expires_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
           RETURNING id""",
        signal_id, account_name, ticket, symbol, order_type,
        volume, price, sl, tp, expires_at,
    )
```

Use this exact shape for `db.create_staged_entries(rows: list[dict]) -> list[int]` (bulk insert in one `_pool.executemany` or a single `VALUES (...), (...), ...` with `RETURNING id`).

**Status-mutation pattern** — `db.py::mark_pending_cancelled:393-398`:
```python
async def mark_pending_cancelled(order_id: int) -> None:
    await _pool.execute(
        "UPDATE pending_orders SET status='cancelled' WHERE id=$1", order_id,
    )
```

Use for `update_stage_status(stage_id: int, status: str, mt5_ticket: int | None = None, cancelled_reason: str | None = None)`. Add optional `filled_at=NOW()` when `status == 'filled'`.

**Bulk-update with `WHERE status IN (...)`** — model on the existing pattern. For `drain_staged_entries_for_kill_switch()`:
```python
await _pool.execute(
    "UPDATE staged_entries SET status='cancelled_by_kill_switch', cancelled_reason='kill_switch' "
    "WHERE status IN ('pending','awaiting_followup','awaiting_zone')"
)
```

**Daily-count idempotency (D-18)** — copy the `ON CONFLICT ... DO UPDATE` + `RETURNING` pattern from `db.py::upsert_account_if_missing:552-564`:
```python
row = await conn.fetchrow(
    """INSERT INTO accounts (...) VALUES (...)
       ON CONFLICT (name) DO NOTHING RETURNING name""", ...,
)
return row is not None
```

For `mark_signal_counted_today(signal_id, account) -> bool`: create a new `signal_daily_counted (signal_id, account_name, date)` table (or re-use `staged_entries`-composite-unique). Use `INSERT ... ON CONFLICT DO NOTHING RETURNING` to return `True` iff this is the first write. Research §Q9 recommends a dedicated single-row table; planner chooses.

**Transaction-wrapped audit pattern** — `db.py::update_account_setting:607-633` (for settings-form POST handler):
```python
field = _validate_account_settings_field(field)  # whitelist BEFORE sql
async with _pool.acquire() as conn:
    async with conn.transaction():
        old_value = await conn.fetchval(
            f"SELECT {field}::TEXT FROM account_settings WHERE account_name=$1", account_name,
        )
        await conn.execute(
            """INSERT INTO settings_audit
               (account_name, field, old_value, new_value, actor)
               VALUES ($1, $2, $3, $4, $5)""",
            account_name, field, old_value, str(new_value), actor,
        )
        await conn.execute(
            f"UPDATE account_settings SET {field}=$1, updated_at=NOW() WHERE account_name=$2",
            new_value, account_name,
        )
```

Phase 6 `/settings/{account}` POST uses `SettingsStore.update()` which already calls this helper — no new DB code needed for the settings-form path; only new helpers for `staged_entries`.

---

### `executor.py` — `_zone_watch_loop`, drain before close, reconcile on reconnect

**Analog:** `executor.py::_heartbeat_loop` (142-165), `_cleanup_loop` (280-292), `emergency_close` (221-271), `_sync_positions` (208-217), `start` (50-61), `stop` (63-79).

**Peer-task loop pattern** — `executor.py:142-165` (exact shape for `_zone_watch_loop`):
```python
async def _heartbeat_loop(self) -> None:
    """Check MT5 connection health every 30s."""
    while True:
        try:
            await asyncio.sleep(30)
            for acct_name, connector in self.tm.connectors.items():
                if acct_name in self._reconnecting:
                    continue
                if self._trading_paused:
                    continue
                # ... per-account work ...
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Heartbeat loop error: %s", exc)
```

**Start/stop lifecycle** — `executor.py:50-79` (add `_zone_watch_task` alongside):
```python
async def start(self) -> None:
    # ...
    self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
    logger.info("Executor started — cleanup + heartbeat loops running")

async def stop(self) -> None:
    # ...
    for task in (self._cleanup_task, self._heartbeat_task):  # ← add _zone_watch_task
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
```

**Kill-switch drain-first pattern** — `executor.py::emergency_close:221-231`:
```python
async def emergency_close(self) -> dict:
    """Kill switch: close all positions, cancel all pending, pause trading.
    Sets _trading_paused FIRST to prevent new signals during close."""
    self._trading_paused = True  # Block new signals IMMEDIATELY
    logger.warning("KILL SWITCH ACTIVATED — closing all positions and cancelling orders")

    closed_positions = 0
    # ...
```

**D-21 edit:** insert `await db.drain_staged_entries_for_kill_switch()` immediately after `self._trading_paused = True` (line 226) and BEFORE the `for acct_name, connector in self.tm.connectors.items():` position-close loop at line 234. Bump the return dict with `"drained_stages": N`.

**Reconnect reconcile pattern** — `executor.py::_sync_positions:208-217`:
```python
async def _sync_positions(self, acct_name: str, connector) -> None:
    """Full position sync from MT5 after reconnect (REL-02)."""
    try:
        positions = await connector.get_positions()
        logger.info("%s: Position sync — %d open position(s)", acct_name, len(positions))
    except Exception as exc:
        logger.error("%s: Position sync failed: %s", acct_name, exc)
```

**D-24 edit:** extend body to (a) `pending_stages = await db.get_pending_stages(acct_name)` (b) build `{stage.mt5_comment: stage for stage in pending_stages}` (c) iterate `positions` and mark any matching-comment stage as `filled` with `mt5_ticket=pos.ticket` (d) iterate pending stages whose comment has no MT5 position AND whose parent signal is older than `signal.max_age_minutes` → `abandoned_reconnect`. The MT5 comment round-trip is confirmed live by `mt5_connector.py:676` (POSTs `"comment"`) and `mt5_connector.py:654` (reads `p.get("comment", "")` on GET positions).

**Comment key format** (D-24 idempotency): `f"telebot-{signal_id}-s{stage_number}"`. Matches the v1.0 pattern used by `trade_manager.py:298,312` (`comment="telebot"`).

---

### `trade_manager.py` — three precise edits + stage-aware extension

**Analog:** `trade_manager.py::_execute_open_on_account:183-373` (the load-bearing path every stage re-uses).

#### Edit 1 — D-23 duplicate-direction bypass (`trade_manager.py:213-217`)

Current:
```python
# ── Check duplicate (same direction already open) ───────────────
for pos in positions:
    if pos.direction == signal.direction.value:
        reason = f"Already have a {signal.direction.value} position open on {signal.symbol}"
        return {"account": name, "status": "skipped", "reason": reason}
```

**Edit:** wrap the equality check so same-`signal_id` stages bypass. Thread `signal_id` (already known at caller) and check `pos.comment.startswith(f"telebot-{signal_id}-s")`. The `Position` dataclass already carries `comment` (mt5_connector.py:60 + the REST connector at line 654 populates it).

#### Edit 2 — D-08 non-zero SL hard-reject on text-only stage 1 (after `trade_manager.py:263-270`)

Current jitter block:
```python
jittered_sl = calculate_sl_with_jitter(
    signal.sl, self.cfg.sl_tp_jitter_points, signal.direction,
)
```

**Edit:** BEFORE the `open_order` call at line 292, add:
```python
if jittered_sl <= 0.0:
    reason = "Refusing to submit sl=0.0 — default_sl_pips must yield non-zero SL (D-08)"
    logger.error("%s: %s", name, reason)
    return {"account": name, "status": "failed", "reason": reason}
```

Log-then-fail uses the existing `logger.error("%s: %s", name, reason)` idiom from `trade_manager.py:165,197,283`.

#### Edit 3 — D-18 signal-id-aware daily-limit increment (`trade_manager.py:168-172, 289`)

Current pre-check:
```python
trade_count = await db.get_daily_stat(name, "trades_count")
if trade_count >= self.cfg.max_daily_trades_per_account:
    # ... skip ...
```

Current increment (line 318):
```python
if result.success:
    await db.increment_daily_stat(name, "trades_count")
```

**Edit:** replace the unconditional `increment_daily_stat` with the D-18 helper:
```python
if result.success:
    first_fill = await db.mark_signal_counted_today(signal_id, name)
    if first_fill:
        await db.increment_daily_stat(name, "trades_count")
```

Stages 2..N of a correlated sequence hit `first_fill=False` and do NOT burn a daily-limit slot.

#### Stage-aware callsite (for `_zone_watch_loop._fire_stage`)

The zone-watcher fires stages via a new private `_execute_stage_on_account(stage_row, acct, connector)` — it re-uses 80% of `_execute_open_on_account` (lot-sizing via `_effective`, pre-flight stale-recheck, order-type selection). Snapshot lives on `stage_row["snapshot_settings"]` per D-30/D-15 — do NOT re-read `SettingsStore` mid-sequence.

---

### `bot.py` — wire correlator + zone-watcher startup

**Analog:** `bot.py::_setup_trading:46-230` (SettingsStore wiring at lines 178-183 is the exact template).

**Extension points:**
```python
# After: tm.settings_store = settings_store
# ADD:
from signal_correlator import SignalCorrelator
correlator = SignalCorrelator(window_seconds=global_config.correlation_window_seconds)
tm.correlator = correlator

# Executor already spawns heartbeat + cleanup in .start() — zone-watcher
# joins the list inside executor.py itself; no change to bot.py startup
# beyond attaching the correlator.
```

**Telegram handler dispatch** — `bot.py:354-381` (branch in the handler):
```python
signal = parse_signal(text)
if signal:
    # ...
    if executor and settings.trading_enabled:
        if not executor.is_accepting_signals():
            # ... existing paused/reconnecting skip ...
        else:
            try:
                results = await executor.execute_signal(signal)
```

**No change needed** — the correlator is a TradeManager-internal concern entered at `tm.handle_signal(signal)` (line 137). The branch on `signal.type == SignalType.OPEN_TEXT_ONLY` OR the "does this OPEN correlate?" lookup happens inside `_handle_open` (or a new `_handle_text_only_open`). `bot.py`'s event handler stays unchanged.

---

### `dashboard.py` — `/settings/{account}` POST, `/staged` GET, SSE payload extension

**Analog:** `dashboard.py::modify_sl:410-431` (form POST with CSRF + auth), `emergency_preview:493-517` (GET that renders a partial), `sse_stream:558-582` (the SSE endpoint).

**Form POST handler skeleton** — `dashboard.py:410-431`:
```python
@app.post("/api/modify-sl/{account_name}/{ticket}", response_class=HTMLResponse)
async def modify_sl(
    account_name: str, ticket: int, request: Request,
    user: str = Depends(_verify_auth), _csrf=Depends(_verify_csrf),
):
    """Modify SL on a position."""
    if not _executor:
        raise HTTPException(status_code=503, detail="Trading not initialized")

    form = await request.form()
    new_sl = float(form.get("sl", 0))
    if new_sl <= 0:
        return HTMLResponse('<span class="text-red-400">Invalid SL</span>')
    # ...
```

**D-31 edit:** `/settings/{account}` POST uses the same `Depends(_verify_auth) + _csrf=Depends(_verify_csrf)` pair. The `_verify_csrf` at `dashboard.py:108-115`:
```python
async def _verify_csrf(request: Request):
    """CSRF protection: reject state-changing requests without a custom header.
    HTMX sends HX-Request automatically."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        if not request.headers.get("hx-request"):
            raise HTTPException(status_code=403, detail="Forbidden")
```

— this is the D-31 HTMX-header pattern the settings form uses (no double-submit-cookie; that's login-only per `_verify_csrf` + `CSRF_COOKIE` being scoped `path="/login"` at line 156).

**Settings form flow** (D-26/D-27/D-28):
1. `GET /settings` already exists (line 334) — extend to load per-account tabs.
2. `POST /settings/{account_name}` validates hard caps (D-29) server-side. On fail → 422 with re-rendered form partial. On pass → render modal HTML via `templates.TemplateResponse("partials/settings_confirm_modal.html", ...)`.
3. `POST /settings/{account_name}/confirm` calls `SettingsStore.update(...)` — already writes audit row inside the DB transaction (db.py:617-633). Returns fresh tabs partial with audit row prepended.
4. `POST /settings/{account_name}/revert` takes `audit_id`, reads the old_value, calls the same confirm path with the inverted diff.

**Page GET skeleton** — `dashboard.py:334-343` (extend `settings_page`):
```python
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: str = Depends(_verify_auth)):
    accounts_data = await _get_accounts_overview()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "accounts": accounts_data,
        # + per-account effective settings + audit log for each
        "page": "settings",
    })
```

Add a sibling `GET /staged`:
```python
@app.get("/staged", response_class=HTMLResponse)
async def staged_page(request: Request, user: str = Depends(_verify_auth)):
    active = await db.get_pending_stages()
    resolved = await db.get_recently_resolved_stages(limit=50)
    return templates.TemplateResponse("staged.html", {
        "request": request, "active": active, "resolved": resolved, "page": "staged",
    })
```

**SSE payload extension** — `dashboard.py:558-582` (exact pattern to extend):
```python
@app.get("/stream")
async def sse_stream(request: Request, user: str = Depends(_verify_auth)):
    """Server-Sent Events stream for real-time updates."""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                positions = await _get_all_positions()
                accounts = await _get_accounts_overview()
                # ADD (D-34):
                pending_stages = await db.get_pending_stages(limit=5)
                data = json.dumps({
                    "positions": positions,
                    "accounts": accounts,
                    "pending_stages": pending_stages,  # ← new
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                yield f"data: {data}\n\n"
            except Exception as exc:
                logger.error("SSE error: %s", exc)
            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

**Pitfall 18 guard** — `X-Accel-Buffering: no` is already set (line 581). Preserve.

---

### Templates

All templates extend `templates/base.html` (the Basecoat + HTMX scaffolding is at `base.html:1-45`):
```html
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <link rel="stylesheet" href="{{ asset_url('app.css') }}">
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <script defer src="/static/vendor/basecoat/basecoat.min.js"></script>
    <script defer src="/static/js/htmx_basecoat_bridge.js"></script>
</head>
<body class="min-h-screen flex">
  <nav class="w-56 ..."> <!-- sidebar --> </nav>
  <main class="ml-56 flex-1 p-6">
    {% block content %}{% endblock %}
  </main>
</body>
```

#### `templates/settings.html` (REWRITE for SET-03)

**Analog for the page shell:** current `templates/settings.html:1-83` (extends base, uses `.card p-6` and a `<table>` with compat-shim default styling).

**Analog for the modal:** `templates/partials/kill_switch_preview.html:1-37` (Basecoat modal shape with `<h3>` + stats + confirm/cancel buttons) — mirrors the D-27 two-step confirmation pattern.

**Basecoat tabs primitive** (D-26) — instantiated per UI-SPEC dimensions. Use `<button role="tab">` / `<div role="tabpanel">`. Tabs are a thin wrapper around HTMX: tab clicks swap the tab panel with `hx-get="/partials/settings_tab/{account}"`.

**Page structure:**
```html
{% extends "base.html" %}
{% block content %}
<div class="mb-6">
    <h2 class="text-2xl font-semibold">Settings</h2>
    <p class="text-slate-500 text-sm mt-1">Per-account runtime configuration. Changes apply to the next signal received — in-flight staged sequences are unaffected.</p>
</div>

<div role="tablist" class="mb-4 border-b border-dark-700">
  {% for a in accounts %}
    <button role="tab" class="px-4 py-2 text-sm font-semibold ...">{{ a.name }}</button>
  {% endfor %}
</div>

{% for a in accounts %}
  <div role="tabpanel" id="tab-{{ a.name }}" class="card p-6">
    {% include "partials/account_settings_tab.html" %}
  </div>
{% endfor %}

<div id="modal-root"></div>
{% endblock %}
```

#### `templates/partials/account_settings_tab.html` (NEW)

**Analog:** `templates/partials/overview_cards.html:1-63` (card layout) + the form idiom from `templates/partials/positions_table.html:55-60` (`<form hx-post="..." hx-target="..." hx-swap="...">`).

**Structure:**
```html
<form hx-post="/settings/{{ a.name }}"
      hx-target="#modal-root"
      hx-swap="innerHTML">
  <div class="space-y-4">
    <label class="label">Risk mode
      <select name="risk_mode" class="input">
        <option value="percent">percent</option>
        <option value="fixed_lot">fixed_lot</option>
      </select>
      <p class="text-xs text-slate-500">"percent" sizes each order as % of equity; "fixed_lot" uses a fixed lot size.</p>
    </label>
    <!-- ... 4 more fields per UI-SPEC copywriting table ... -->
    <button class="btn btn-primary" type="submit">Save settings</button>
  </div>
</form>

{# audit timeline #}
<h3 class="text-lg font-semibold mt-6 mb-4">Change history</h3>
{% include "partials/settings_audit_timeline.html" %}
```

#### `templates/partials/settings_audit_timeline.html` (NEW)

**Analog:** `templates/partials/positions_table.html:1-80` (default `<table>` from `_compat.css` + HTMX button idiom).

**Revert button pattern:**
```html
<button class="btn btn-blue"
        hx-post="/settings/{{ account }}/revert?audit_id={{ row.id }}"
        hx-target="#modal-root"
        hx-swap="innerHTML">
  Revert change
</button>
```

#### `templates/staged.html` (NEW)

**Analog:** `templates/overview.html:1-49` (page shell + `{% include %}` pattern).

**Structure:**
```html
{% extends "base.html" %}
{% block content %}
<div class="mb-6">
    <h2 class="text-2xl font-semibold">Pending Stages</h2>
    <p class="text-slate-500 text-sm mt-1">Live view of in-flight staged entry sequences. Auto-refreshes every 2 seconds.</p>
</div>

<h3 class="text-lg font-semibold mb-4">Active sequences</h3>
<div hx-ext="sse" sse-connect="/stream" sse-swap="pending_stages"
     hx-get="/partials/pending_stages?all=1" hx-trigger="every 5s"
     hx-on::sse-error="this.classList.add('sse-fallback')">
    {% include "partials/pending_stages.html" %}
</div>

<details class="card p-6 mt-12">
  <summary class="text-lg font-semibold">Recently resolved ({{ resolved|length }})</summary>
  {# resolved table — same shape as active, with status pill column #}
</details>
{% endblock %}
```

#### `templates/partials/pending_stages.html` (NEW)

**Analog:** `templates/partials/positions_table.html:1-80` (exact — same `.card overflow-x-auto` → `<table>` shape, same column-per-field idiom).

**Structure:**
```html
<div class="card overflow-x-auto" role="region" aria-live="polite"
     aria-label="Pending staged entry sequences">
  <table>
    <thead><tr>
      <th>Account</th><th>Symbol</th><th>Direction</th>
      <th>Stages</th><th>Target band</th><th>Current price</th><th>Elapsed</th>
    </tr></thead>
    <tbody>
      {% for s in stages %}
      <tr>
        <td class="font-semibold">{{ s.account_name }}</td>
        <td class="font-mono">{{ s.symbol }}</td>
        <td>
          {% if s.direction == 'buy' %}
            <span class="badge-buy">BUY</span>
          {% else %}
            <span class="badge-sell">SELL</span>
          {% endif %}
        </td>
        <td><span class="font-mono text-sm">{{ s.filled }} / {{ s.total }}</span></td>
        <td class="font-mono">{{ "%.2f"|format(s.band_low) }} – {{ "%.2f"|format(s.band_high) }}</td>
        <td class="font-mono" data-price-cell>
          {{ "%.2f"|format(s.current_price) }}
          <div class="text-xs text-slate-500">{{ s.distance_str }}</div>
        </td>
        <td><span class="font-mono text-xs text-slate-400">{{ s.elapsed }}</span></td>
      </tr>
      {% endfor %}
      {% if not stages %}
      <tr><td colspan="7">
        <div class="empty-state p-8 text-center text-slate-500">
          <div class="text-lg font-semibold">No pending stages</div>
          <p class="text-sm">All signals resolved. New staged sequences will appear here automatically.</p>
        </div>
      </td></tr>
      {% endif %}
    </tbody>
  </table>
</div>
```

Direction badge (`badge-buy`/`badge-sell`) from `_compat.css`.

#### `templates/overview.html` — insert pending-stages partial

**Edit location:** after the "Open Positions" block (`templates/overview.html:43-48`):
```html
<div class="mt-8">
    <h3 class="text-lg font-semibold mb-4">Open Positions</h3>
    <div id="positions-table" hx-get="/partials/positions" hx-trigger="every 3s" hx-swap="innerHTML">
        {% include "partials/positions_table.html" %}
    </div>
</div>
```

Add after:
```html
<div class="mt-8">
    <h3 class="text-lg font-semibold mb-4">
      Pending Stages <span class="text-xs text-slate-500">(showing top 5)</span>
    </h3>
    <div id="pending-stages" hx-ext="sse" sse-connect="/stream" sse-swap="pending_stages">
        {% include "partials/pending_stages.html" %}
    </div>
</div>
```

---

### Tests

All Phase-6 tests follow the existing pytest-asyncio + session-loop + DB-pool fixture pattern.

**Fixture/conftest pattern** — `tests/conftest.py:21-139` is the canonical source:
```python
@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop — asyncpg pool is loop-bound."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def db_pool():
    try:
        await db.init_db(TEST_DATABASE_URL)
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")
    yield db._pool
    await db.close_db()

@pytest.fixture(autouse=True)
async def clean_tables():
    # TRUNCATE ... RESTART IDENTITY CASCADE between tests
```

All Phase-6 DB tests must `TRUNCATE staged_entries` too — add it to the `clean_tables` fixture list (edit to conftest.py is trivial).

**Async-test module marker pattern** — `tests/test_settings_store.py:13`:
```python
pytestmark = pytest.mark.asyncio(loop_scope="session")
```

#### `tests/test_signal_parser_text_only.py`

**Analog:** `tests/test_signal_parser.py::TestOpenSignalsZone` (lines 14-80 in the file).

**Shape to copy** — `tests/test_signal_parser.py:14-37`:
```python
class TestOpenSignalsZone:
    def test_sell_zone_with_multiple_tps(self):
        text = "Gold sell now 4978 - 4982\n\nSL: 4986\n\nTP. 4975\n..."
        s = parse_signal(text)
        assert s is not None
        assert s.type == SignalType.OPEN
        assert s.symbol == "XAUUSD"
        assert s.direction == Direction.SELL
        assert s.entry_zone == (4978.0, 4982.0)
```

**New tests:** `test_text_only_buy_parses`, `test_text_only_sell_parses`, `test_text_only_with_numbers_rejects_to_OPEN` (guard D-02's "no numerics"), `test_text_only_case_insensitive`, `test_now_without_symbol_returns_none`.

#### `tests/test_correlator.py`

**Analog:** `tests/test_settings_store.py` (entire file, lines 1-74) — same pytest-asyncio fixture, same unit-focused assertion style.

**Fixture:**
```python
pytestmark = pytest.mark.asyncio(loop_scope="session")

@pytest_asyncio.fixture
async def correlator():
    return SignalCorrelator(window_seconds=600)
```

**New tests:** `test_register_orphan`, `test_pair_within_window`, `test_pair_most_recent_wins`, `test_pair_one_to_one_cannot_repair`, `test_pair_past_window_returns_none`, `test_pair_wrong_direction_returns_none`.

#### `tests/test_staged_db.py`

**Analog:** `tests/test_settings.py` (lines 1-52) — same pytest-asyncio + `seeded_account` fixture.

**Shape to copy** — `tests/test_settings.py:8-19`:
```python
async def test_audit_per_field_write(db_pool, seeded_account):
    await db.update_account_setting(seeded_account, "risk_value", 2.5)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT field, old_value, new_value, actor FROM settings_audit "
            "WHERE account_name=$1 ORDER BY id", seeded_account,
        )
    assert len(rows) == 1
```

**New tests:** `test_create_staged_entries_returns_ids`, `test_update_stage_status_sets_filled_at`, `test_drain_for_kill_switch_terminal`, `test_get_pending_stages_filters_by_status`, `test_mark_signal_counted_today_idempotent`, `test_reconcile_after_reconnect_matches_by_comment`.

#### `tests/test_staged_executor.py`

**Analog:** `tests/test_trade_manager_integration.py::PricedDryRunConnector` (lines 18-46) — the priced-connector pattern plus real DB + TradeManager.

**Shape to copy** — `tests/test_trade_manager_integration.py:18-56`:
```python
class PricedDryRunConnector(DryRunConnector):
    def __init__(self, *args, prices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._prices = prices or {"XAUUSD": (4980.0, 4981.0)}

    async def get_price(self, symbol):
        return self._prices.get(symbol)

@pytest_asyncio.fixture
async def priced_connector():
    c = PricedDryRunConnector("test-acct", "TestServer", 12345, "pass",
                              prices={"XAUUSD": (4980.0, 4981.0)})
    await c.connect()
    yield c
    await c.disconnect()
```

**New tests:** `test_zone_watch_fires_stage_when_price_enters_band`, `test_zone_watch_skips_when_trading_paused`, `test_zone_watch_preflight_recheck_skips_on_drift`, `test_in_zone_at_arrival_fires_crossed_bands_immediately`, `test_stage_marked_capped_when_max_open_trades_reached`, `test_stage_marked_failed_on_broker_reject_others_continue`.

#### `tests/test_staged_safety_hooks.py`

**Analog:** `tests/test_trade_manager_integration.py` + `tests/test_settings.py::test_audit_per_field_write` (DB verification shape).

**New tests:** `test_emergency_close_drains_staged_before_positions`, `test_resume_does_not_unCancel_drained_stages`, `test_dup_guard_bypass_same_signal_id_different_stage`, `test_dup_guard_still_rejects_unrelated_same_direction`, `test_reconnect_marks_filled_when_comment_exists_on_mt5`, `test_reconnect_marks_abandoned_when_signal_aged_and_no_mt5_position`, `test_default_sl_zero_hard_rejects_text_only`.

#### `tests/test_staged_attribution.py`

**Analog:** `tests/test_settings.py:8-39` (DB state verification style).

**New tests:** `test_every_stage_persists_signal_id`, `test_staged_entries_joins_trades_by_ticket`, `test_one_signal_id_one_daily_slot`.

#### `tests/test_settings_form.py`

**Analog:** `tests/test_settings.py` for DB-side + `tests/test_login_flow.py` for the FastAPI TestClient style (401/303/200 status assertions with HTMX headers).

**Covers:** hard-cap rejections (D-29), modal render on valid change (D-27), confirm writes audit (already covered by test_settings_store but repeat at route layer), revert POST writes a new audit row.

#### `tests/test_pending_stages_sse.py`

**Analog:** SSE tests don't exist yet — build on `tests/test_trade_manager_integration.py`'s DB fixture + a FastAPI TestClient that subscribes to `/stream` and parses one `data: {...}\n\n` chunk.

**New tests:** `test_sse_payload_includes_pending_stages_key`, `test_sse_accel_buffering_header_set`.

---

## Shared Patterns

### Logging
**Source:** every module — canonical idiom from `bot.py:17-24` + per-module `logger = logging.getLogger(__name__)`.
**Apply to:** all new modules.
```python
import logging
logger = logging.getLogger(__name__)

logger.info("Correlator: registered orphan signal_id=%d %s %s", signal_id, symbol, direction)
logger.warning("%s: Default SL computed as 0 — cannot submit", acct_name)
logger.error("Zone watch loop error: %s", exc)
```
Level discipline: `INFO` for milestones (stage fired, kill-switch drained), `WARNING` for operator-attention (orphan no-match, reconnect abandoned), `ERROR` for exceptions. Use `%s` / `%d` formatting — never f-strings inside logger calls (project convention, CONVENTIONS.md §Logging).

### Error Handling
**Source:** `executor.py::_heartbeat_loop:142-165` + `trade_manager.py::_execute_open_on_account:183-373`.
**Apply to:** all new async loops and handlers.
```python
try:
    ...
except asyncio.CancelledError:
    break   # loops
except Exception as exc:
    logger.error("<context>: %s", exc)
    await asyncio.sleep(30)  # back off on unexpected errors inside loops
```
Route handlers use `HTTPException(status_code=..., detail=...)` (dashboard.py:116, 396).

### Async DB access
**Source:** `db.py::_pool.fetchval/fetch/execute`.
**Apply to:** all new DB helpers.
- Acquire a connection only for transactions: `async with _pool.acquire() as conn: async with conn.transaction(): ...` (pattern at `db.py:617-633`).
- Simple single-statement queries go through `_pool.execute(...)`, `_pool.fetchval(...)`, `_pool.fetchrow(...)`, `_pool.fetch(...)` — no explicit acquire (pattern everywhere in db.py).
- Never interpolate user input directly; use `$1`, `$2` placeholders. Column names inside dynamic SQL must pass a whitelist validator (see `db.py::_validate_field` at line 29 + `_validate_account_settings_field` at line 41).

### Auth + CSRF on new dashboard routes
**Source:** `dashboard.py::modify_sl:410-431`.
**Apply to:** all new POST/PUT/DELETE routes (`/settings/{account}`, `/settings/{account}/confirm`, `/settings/{account}/revert`, anything under `/api/`).
```python
@app.post("/settings/{account_name}", response_class=HTMLResponse)
async def settings_post(
    account_name: str, request: Request,
    user: str = Depends(_verify_auth),
    _csrf=Depends(_verify_csrf),
):
    ...
```
GET routes use `Depends(_verify_auth)` only.

### Frozen-dataclass snapshot
**Source:** `settings_store.py::snapshot:80-85` + `models.py::AccountSettings:74-91`.
**Apply to:** stage creation — call `tm.settings_store.snapshot(acct_name)` at correlated-follow-up receipt; persist the `dataclasses.asdict(snapshot)` JSON into `staged_entries.snapshot_settings` per D-15 / D-30. Never re-read `SettingsStore` from the zone-watcher — use the stage's snapshot column.

### MT5 comment idempotency
**Source:** `mt5_connector.py:676` (POST `comment`) + `mt5_connector.py:654` (GET `comment`).
**Apply to:** every stage fill. Format: `f"telebot-{signal_id}-s{stage_number}"`. Replace the current literal `comment="telebot"` at `trade_manager.py:298, 312` with the stage-aware form for the staged path (preserve literal `"telebot"` for unstaged v1.0 opens to avoid regression).

### Template block extension
**Source:** `templates/base.html` + `templates/overview.html:1-3`.
```html
{% extends "base.html" %}
{% block content %}
  <!-- page body -->
{% endblock %}
```
All Phase-6 full-page templates use this.

### Table + badge compat-shim
**Source:** `templates/partials/positions_table.html` (default `<table>`, `.badge-buy`/`.badge-sell`, `.btn btn-red|blue|green`, `.font-mono`).
**Apply to:** pending-stages table, audit timeline, resolved-stages table.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| *none* | — | — | Every new file has a concrete analog in the v1.0+v1.1 codebase. Phase-6 is strictly additive. |

---

## Metadata

**Analog search scope:**
- `/Users/murx/Developer/personal/telebot/` (root — all Python sources)
- `/Users/murx/Developer/personal/telebot/tests/`
- `/Users/murx/Developer/personal/telebot/templates/` and `templates/partials/`
- `/Users/murx/Developer/personal/telebot/.planning/codebase/` (ARCHITECTURE/CONVENTIONS/TESTING)

**Files scanned (read in full or in targeted sections):** 20+
- Core: `bot.py`, `executor.py`, `trade_manager.py`, `signal_parser.py`, `models.py`, `db.py`, `dashboard.py`, `settings_store.py`, `mt5_connector.py`
- Templates: `base.html`, `overview.html`, `settings.html`, `partials/overview_cards.html`, `partials/positions_table.html`, `partials/kill_switch_preview.html`
- Tests: `conftest.py`, `test_signal_parser.py`, `test_settings.py`, `test_settings_store.py`, `test_trade_manager.py`, `test_trade_manager_integration.py`
- Docs: `.planning/codebase/ARCHITECTURE.md`, `CONVENTIONS.md`, `TESTING.md`

**Pattern extraction date:** 2026-04-19

---

## PATTERN MAPPING COMPLETE
