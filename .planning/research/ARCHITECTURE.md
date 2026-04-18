# Architecture Research — v1.1 Integration

**Domain:** MT5 trade-execution bot (FastAPI + HTMX dashboard, Telethon handler, multi-account MT5 bridge)
**Researched:** 2026-04-18
**Confidence:** HIGH (read of existing `executor.py`, `trade_manager.py`, `bot.py`, `dashboard.py`, `db.py`, `models.py`, `risk_calculator.py`, `templates/`, `accounts.json`)
**Scope:** How the four v1.1 features (staged entries, per-account settings in DB, dashboard redesign, login form) slot into the existing single-process ASGI topology without regressing kill switch, reconnect/position-sync, or daily limits.

---

## 1. Existing Architecture (v1.0) — the substrate we're extending

### System overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                      Single Python process (bot.py)                   │
│                      asyncio event loop                               │
├──────────────────────────────────────────────────────────────────────┤
│  Telethon                 FastAPI (uvicorn on same loop)             │
│  NewMessage handler       Dashboard routes (Jinja + HTMX + SSE)      │
│     │                         │                                       │
│     │ parse_signal()           │                                      │
│     ▼                          ▼                                      │
│  signal_parser        dashboard._verify_auth (HTTPBasic)             │
│     │                          │                                      │
│     └──────────┬───────────────┘                                     │
│                ▼                                                      │
│          Executor (owns lifecycle)                                   │
│          ├─ is_accepting_signals()  (gate: _trading_paused,          │
│          │                           _reconnecting set)              │
│          ├─ execute_signal()        (shuffle + stagger + per-acct)   │
│          ├─ _heartbeat_loop         (30s, MT5 ping → reconnect)      │
│          ├─ _cleanup_loop           (60s, expired pending orders)    │
│          ├─ _reconnect_account      (backoff + _sync_positions)      │
│          └─ emergency_close         (kill switch)                    │
│                │                                                      │
│                ▼                                                      │
│          TradeManager (handle_signal → open/close/modify)            │
│          ├─ self.connectors: dict[name → MT5Connector]               │
│          ├─ self.accounts:   dict[name → AccountConfig]              │
│          └─ self.cfg:        GlobalConfig                            │
│                │                                                      │
│                ▼                                                      │
│          MT5Connector per account (gRPC or direct) ───► MT5 bridge   │
├──────────────────────────────────────────────────────────────────────┤
│  PostgreSQL via asyncpg pool (db.py module-global _pool)             │
│    signals · trades · daily_stats · pending_orders                   │
└──────────────────────────────────────────────────────────────────────┘
```

### Key invariants v1.1 must not break

1. **Single shared event loop.** Dashboard is launched inside `bot.py:main` as `asyncio.create_task(uvicorn.Server(…).serve())`. The Telethon handler, all Executor background tasks, and all dashboard routes share state via direct object references (`_executor`, `_notifier` in `dashboard.py:27-30`). No IPC, no queue. New v1.1 components must stay in-process for the same reason.
2. **Signal-gate triad.** `Executor.is_accepting_signals()` returns False if `_trading_paused` OR all connectors are in `_reconnecting`. This is the single source of truth for "should we execute?" and it's called in `bot.py:308` **before** `executor.execute_signal`. Anything that opens positions — including staged-entry follow-ups — MUST pass through this gate.
3. **Daily-limit counters live in Postgres, not memory.** `daily_stats` is read per-account per-execution (`trade_manager.py:168-175`). Staged follow-ups are new executions and must increment the same counters and respect the same ceilings.
4. **Position sync after reconnect (REL-02).** `Executor._sync_positions` runs inside `_reconnect_account` before removing the account from `_reconnecting`. Any v1.1 state that tracks "what the bot thinks is open" (zone watchers, staged-entry progress) must either be sync-reconcilable from MT5 or gracefully tolerate being told "reality differs."
5. **In-memory config.** `TradeManager.accounts` is a dict built once at startup from `accounts.json` (`bot.py:94-108`). Today it's immutable at runtime. v1.1 introduces mutation, which is a behavioral change even if the dataclass layout is preserved.
6. **CSRF model is HTMX-header based.** `_verify_csrf` accepts requests that carry `hx-request` (`dashboard.py:67-74`). Forms rendered outside the HTMX flow — notably an unauthenticated `POST /login` — need a new CSRF story.

---

## 2. Component diff — what's new vs. modified vs. unchanged

| Area | Component | New / Modified / Unchanged | Notes |
|------|-----------|----------------------------|-------|
| DB schema | `account_settings` table | **New** | One row per `account_name`, overrides `accounts.json` |
| DB schema | `staged_entries` table | **New** | Per-signal pending stages with zone + status |
| DB schema | `signals`, `trades`, `daily_stats`, `pending_orders` | Unchanged | No column additions needed |
| DB layer | `db.init_schema()` | **Modified** | Add two `CREATE TABLE IF NOT EXISTS` blocks |
| DB layer | `db.get_account_settings()`, `db.upsert_account_settings()` | **New** helpers | Read/write `account_settings` |
| DB layer | `db.create_staged_entry()`, `db.list_active_stages()`, `db.mark_stage_triggered()`, `db.cancel_stages_for_signal()`, `db.cancel_all_active_stages()` | **New** helpers | CRUD for staged entries |
| Models | `AccountSettings` dataclass | **New** | `risk_mode`, `fixed_lot`, `max_stages`, `stage_allocation`, `max_open_trades`, `risk_percent`, `max_lot_size` (runtime-mutable copies of fields currently on `AccountConfig`) |
| Models | `SignalAction` | Unchanged | Staged entries are derived at execution time, not a new signal type |
| Models | `AccountConfig` | **Effectively frozen** | Fields stay for bootstrap; effective values read via `SettingsStore` |
| Parser | `signal_parser` | Unchanged | Text-only signal handling is an execution change, not a parse change (verify in Phase 1 that "gold buy now" still parses to a valid `SignalAction`) |
| Risk | `risk_calculator.calculate_lot_size` | **Modified (small)** | New branch: if settings says `risk_mode="fixed"`, return `min(fixed_lot, max_lot_size)` |
| Executor | `_zone_watch_loop` | **New** background task | 5-10s cadence, polls price for each active stage, triggers follow-up executions. Launched in `start()`, cancelled in `stop()` alongside heartbeat/cleanup |
| Executor | `_trigger_stage` | **New** helper | Mirrors `_execute_single_account` but uses a pre-computed stage lot and the same daily-limit / reconnect gates |
| Executor | `is_accepting_signals` | Unchanged | Already correct — zone watcher calls it per-stage too |
| Executor | `emergency_close` | **Modified** | After setting `_trading_paused`, call `db.cancel_all_active_stages()` BEFORE closing positions so the watcher can't race |
| TradeManager | `handle_signal` | **Modified** | On OPEN success, if signal qualifies for staging (see §3), persist follow-up stages before returning |
| TradeManager | `_execute_open_on_account` | **Modified (lot sizing)** | Replace direct `acct.risk_percent` / `acct.max_lot_size` reads with a call to `settings_store.effective(name)` |
| TradeManager | daily-limit checks | Unchanged | They already hit the DB, so runtime settings changes propagate naturally |
| Settings layer | `SettingsStore` class | **New** | In-process cache of `AccountSettings` by account, write-through to `account_settings` table, with `.reload(name)` and `.effective(name)` |
| Dashboard | `/login`, `/logout` routes | **New** | GET renders form; POST validates `argon2-cffi`; sets signed session cookie via `SessionMiddleware` |
| Dashboard | `_verify_auth` | **Modified** | Read `request.session["user"]` instead of HTTP Basic; `RedirectResponse("/login?next=…")` on miss |
| Dashboard | `_verify_csrf` | **Modified** | Keep HTMX header check for existing routes; for `/login` POST, use a one-shot hidden token (`session["csrf_pending"]`) generated on GET |
| Dashboard | `/api/settings/{account}` | **New** routes | GET partial row, POST form update → writes DB, calls `settings_store.reload(name)` |
| Dashboard | `/settings` page | **Modified (rewrite)** | Render editable forms (risk mode toggle, fixed-lot input, max-stages, max-open-trades) instead of the read-only table at `templates/settings.html:36-82` |
| Dashboard | existing pages | **Modified (UI-only)** | Swap Tailwind Play CDN + handwritten CSS for Basecoat classes + built `app.css`; logic unchanged |
| Dashboard | `/partials/stages`, `/staged` page | **New** | Live list of active/triggered/cancelled/expired stages |
| Dashboard | SSE `/stream` | **Modified** | Add `staged_entries` payload alongside `positions` and `accounts` |
| Templates | `base.html` | **Modified** | Drop Play CDN; link built `/static/css/app.css`; conditional Basecoat JS bundle |
| Templates | `login.html` | **New** | Login form using Basecoat form primitives |
| Templates | `settings.html` | **Modified** | Editable; per-account form with HTMX `hx-post` |
| Templates | `staged.html` + partial | **New** | Active-stages overview page |
| Config | `settings` (config.py) | **Modified** | Add `DASHBOARD_PASS_HASH`, `SESSION_SECRET`, `SESSION_MAX_AGE`, `ZONE_WATCH_INTERVAL_SECONDS`; keep `DASHBOARD_PASS` as deprecated fallback for one release |
| bot.py | `main()` / `_setup_trading` | **Modified** | Build `SettingsStore` after `db.init_db()` and before `TradeManager(...)`; pass to both `TradeManager` and `Executor`; pass to `init_dashboard()` |
| Docker | Tailwind CLI build step | **New** | Per STACK.md §2 — compile `static/css/app.css` at image build |
| Repo hygiene | `drizzle.config.json` | **Delete** | Stray, unrelated (per STACK.md) |

---

## 3. Staged-entry data flow (the load-bearing feature)

### Staging decision

A signal qualifies for staging when **all three** hold:

1. `signal.type == SignalType.OPEN`
2. `signal.entry_zone` is a real range (`zone_high > zone_low + ε`). A text-only "buy now" without a zone does NOT stage — it executes once, market, done.
3. The account's `AccountSettings.max_stages > 1`.

Staging produces `max_stages` executions total (not `max_stages + 1`). The first stage fills immediately (either market, if price is already in-zone, or a limit at zone-mid under existing v1.0 logic — unchanged). Stages 2..N are persisted with target bands derived from the zone and filled when price re-enters those bands.

### Stage allocation

Per STACK.md §4: `AccountSettings.stage_allocation: list[float]` summing to 1.0 (e.g. `[0.4, 0.3, 0.3]`). Lot for stage `k` = `full_lot × stage_allocation[k]`, where `full_lot` is computed once from current balance and SL distance (same `calculate_lot_size` call used today).

### Happy-path flow

```
Telegram signal "XAU buy 2340-2345 sl 2330 tp 2360"
        │
        ▼
bot.py handler → parse_signal → SignalAction(type=OPEN, zone=(2340,2345),…)
        │
        ▼
Executor.is_accepting_signals() ──► True
        │
        ▼
Executor.execute_signal(signal)
        │
        ├─► per account (shuffled, staggered):
        │     TradeManager._execute_open_on_account(signal, account)
        │          ├─ daily-limit & duplicate checks (unchanged)
        │          ├─ get_price, determine_order_type (unchanged)
        │          ├─ settings_store.effective(account) → AccountSettings
        │          ├─ full_lot = calculate_lot_size(...)  # honors risk_mode
        │          ├─ IF max_stages > 1 AND zone is real:
        │          │     stage_lots = [full_lot * w for w in stage_allocation]
        │          │     open market/limit for stage_lots[0] as today
        │          │     INSERT staged_entries rows for k=1..max_stages-1
        │          │         status='active', target_zone_low/high per band
        │          │ELSE:
        │          │     open as v1.0 (single stage, full_lot)
        │          └─ returns result dict (existing shape)
        │
        ▼
Executor._zone_watch_loop (runs independently, every 5-10s)
        │
        ├─ db.list_active_stages()
        ├─ group by (account, symbol), get_price once per pair
        ├─ for each active stage:
        │    IF self._trading_paused → continue
        │    IF account in self._reconnecting → continue
        │    IF current_price in [target_zone_low, target_zone_high]:
        │         is_accepting_signals() re-check
        │         daily-limit re-check (stages count toward the limit)
        │         stale re-check (price already past TP1?)
        │         Executor._trigger_stage(stage)  # opens the order
        │         db.mark_stage_triggered(stage.id, ticket)
        └─ IF parent trade's TP1 already hit
             → db.cancel_stages_for_signal(signal_id)
```

### Critical cross-cutting interactions

| Cross-cutting concern | Interaction with staged entries | Resolution |
|-----------------------|--------------------------------|------------|
| **Kill switch** | Watcher must not open new stages after `emergency_close` | In `Executor.emergency_close`, FIRST set `_trading_paused=True` (already done), THEN `db.cancel_all_active_stages()`, THEN close positions. Watcher's top-of-loop `if self._trading_paused: continue` is a second line of defense |
| **Reconnect / position sync** | MT5 may already contain a stage that was opened by the watcher before disconnect, or a stage the watcher thinks opened but actually failed | After `_sync_positions`, reconcile: for each active stage on that account, if its last-known ticket appears in MT5 positions → mark `triggered`; if stage is marked `triggered` but ticket absent from positions → mark `reconciled_lost` and alert. Soft reconcile — don't re-open |
| **Daily trade limit** | Stage triggers are real executions | `_trigger_stage` calls the same `get_daily_stat`/`increment_daily_stat` path. Counter is already shared |
| **Daily server-message limit** | Each stage trigger sends an MT5 order → +1 server message | Same path increments `server_messages` |
| **Duplicate-direction check** | `_execute_open_on_account` rejects a new OPEN if account already holds a same-direction position on the symbol | For stages we explicitly BYPASS this check — stages ARE additional positions by design. Gate the bypass on `stage_number > 1` |
| **max_open_trades** | A 3-stage signal on an account with `max_open_trades=3` could fill all slots on one symbol | Enforce per-stage in `_trigger_stage`: if `len(positions) >= max_open_trades`, mark stage `skipped_capacity` and log. No silent cancel — dashboard surfaces it |
| **Stale-signal re-check** | When a stage finally fills (minutes later), price may be past TP1 | `_trigger_stage` runs the same `_check_stale` as v1.0 |
| **Stage expiry** | Zones can sit "active" forever if price never re-enters | Reuse v1.0 `limit_order_expiry_minutes` idea: `staged_entries.expires_at`. `_cleanup_loop` (already running every 60s) can co-own this — mark expired stages `expired` |
| **Concurrent watcher + new signal** | Stage triggering at the same instant as a close signal on the same position | Per-account scoped temp `TradeManager` pattern from v1.0 `_execute_single_account` is preserved for stages — no shared-connector races |

### DB schema additions

```sql
CREATE TABLE IF NOT EXISTS account_settings (
    account_name TEXT PRIMARY KEY,
    risk_mode TEXT NOT NULL DEFAULT 'percent',   -- 'percent' | 'fixed'
    risk_percent DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    fixed_lot DOUBLE PRECISION NOT NULL DEFAULT 0.01,
    max_lot_size DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    max_open_trades INTEGER NOT NULL DEFAULT 3,
    max_stages INTEGER NOT NULL DEFAULT 1,
    stage_allocation JSONB NOT NULL DEFAULT '[1.0]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by TEXT
);

CREATE TABLE IF NOT EXISTS staged_entries (
    id SERIAL PRIMARY KEY,
    signal_id INTEGER REFERENCES signals(id),
    account_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    stage_number INTEGER NOT NULL,
    total_stages INTEGER NOT NULL,
    lot_size DOUBLE PRECISION NOT NULL,
    target_zone_low DOUBLE PRECISION NOT NULL,
    target_zone_high DOUBLE PRECISION NOT NULL,
    sl DOUBLE PRECISION NOT NULL,
    tp DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'active',
      -- 'active' | 'triggered' | 'cancelled' | 'expired' | 'skipped_capacity' | 'reconciled_lost'
    triggered_at TIMESTAMPTZ,
    triggered_ticket BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_staged_entries_active
    ON staged_entries(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_staged_entries_signal
    ON staged_entries(signal_id);
```

Per STACK.md §5, stay on the hand-DDL pattern; defer alembic to v1.2.

---

## 4. Settings propagation — the cache-invalidation subproblem

### Problem

`TradeManager.accounts: dict[name → AccountConfig]` is built once at startup. v1.0 has no mutation path — "restart to change config" is the design. v1.1 introduces a dashboard form that must take effect immediately, including for the zone watcher's in-flight stages.

### Solution: SettingsStore with write-through cache

```
Form POST /api/settings/{name}
        │
        ▼
dashboard.update_settings(name, form)
        │
        ├─ validate (risk_percent in [0.1, 10], stage_allocation sums to 1.0, etc.)
        ├─ db.upsert_account_settings(name, fields, updated_by=user)
        └─ settings_store.reload(name)       # re-read row into in-memory dict
                │
                ▼
          subsequent calls to settings_store.effective(name) see new values
```

`SettingsStore` is a dataclass-plus-dict owned by `bot.py:main`, passed to both `TradeManager` and `Executor`. It's the single reader of `account_settings`. No pub/sub, no invalidation events — `reload(name)` after write is sufficient because we're in one process.

### What settings affect mid-flight

| Setting | Takes effect from | Notes |
|---------|------------------|-------|
| `risk_mode`, `risk_percent`, `fixed_lot` | Next signal execution | Already-placed limit orders keep their sized lot; staged entries already in DB keep their pre-computed `lot_size` |
| `max_lot_size` | Next signal execution | Same — sized before persisting the stage |
| `max_open_trades` | Next signal AND next stage trigger | `_trigger_stage` re-reads via `settings_store.effective()` each cycle |
| `max_stages`, `stage_allocation` | Next signal only | Changing mid-signal would break allocation invariants; stages are planned once at signal time |

**Design rule:** Once a stage row lands in `staged_entries`, its `lot_size` is frozen. Settings changes never retroactively rewrite pending stages — they affect only the NEXT signal. Avoids a whole class of races. Dashboard should make this explicit in the UI copy.

### accounts.json becomes a bootstrap seed

On startup, for each account in `accounts.json`:

1. If no row exists in `account_settings`, INSERT populated from `accounts.json` values.
2. Always load `account_settings`. DB wins on conflict.

Preserves the v1.0 "no breaking changes to accounts.json" constraint.

---

## 5. Login form — layering on without breaking existing routes

### Target state

```
GET  /login   ─► render templates/login.html (CSRF token in session)
POST /login   ─► argon2-cffi verify → session["user"]="admin" → redirect to ?next= or /overview
GET  /logout  ─► session.clear() → redirect /login
every other  ─► _verify_auth reads session["user"]; miss → RedirectResponse("/login?next=<path>")
```

### Middleware ordering

```python
app = FastAPI(…)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,    # ≥32 bytes, hard-fail if missing
    session_cookie="telebot_session",
    max_age=settings.session_max_age,      # e.g. 28800 (8h)
    same_site="lax",
    https_only=True,                        # prod only; toggle via settings
)
app.mount("/static", StaticFiles(...), …)
```

### Route-level changes

- `_verify_auth` is the only dependency injected on pages. Swap body from `HTTPBasic` to `request.session.get("user")`. For HTMX/API routes, raise 401 (HTMX shows toast); for top-level pages, return `RedirectResponse("/login?next=" + urlencode(request.url.path))`.
- `/health` remains auth-free.
- `/login` and `/logout` are auth-free.
- `/stream` (SSE): EventSource sends cookies automatically, so no flow change — just swap the auth dep.

### Login-form CSRF

HTMX header trick doesn't work on the first GET /login (no session yet) and the subsequent POST must be validated. Pattern:

1. GET `/login` generates `csrf = secrets.token_urlsafe(32)`, stores in `session["csrf_pending"]`, renders hidden input.
2. POST `/login` compares form `csrf` to `session["csrf_pending"]` (constant-time), then pops it.
3. Subsequent state-changing requests keep using the existing `_verify_csrf` (HX-Request header check), unchanged.

Keeps the CSRF story cleanly split: login uses token+session, HTMX API routes use header-origin.

### Password migration path

Per STACK.md §3:
- Add env `DASHBOARD_PASS_HASH` (argon2 hash).
- Keep `DASHBOARD_PASS` as fallback for ONE release. On successful login via plaintext env, log one-time WARN.
- Ship `scripts/hash_password.py` that prints the hash for ops.

### What this does NOT break

- All existing routes still go through `_verify_auth` by `Depends`, so swapping the implementation is surgical.
- HTMX header CSRF UNCHANGED for API routes.
- Kill switch, SSE, settings edits all sit behind the same dependency → session replacement applies uniformly.

---

## 6. Dashboard redesign — integration, not a rewrite

Per STACK.md §1–2, the substrate stays **FastAPI + Jinja + HTMX**. Basecoat is a CSS layer + tiny vanilla JS on top.

### Asset pipeline

```
static/css/
├─ input.css            # (new) @tailwind directives + @import basecoat.css
├─ basecoat.css         # (new, vendored) from npm basecoat-css@0.3.3
└─ app.css              # (new, built) output of tailwindcss CLI

static/js/
└─ basecoat.min.js      # (new, vendored) only on pages using interactive comps
```

Dockerfile adds the standalone Tailwind CLI binary and runs the build at image-build time (no node_modules, no npm in runtime image). Templates point at `/static/css/app.css` via the existing `StaticFiles` mount.

### Template migration order

1. `base.html` — drop Play CDN script, add built CSS link. Keep page layout unchanged at first. **Verify every existing page still renders** before touching component markup.
2. Partials (`overview_cards.html`, `positions_table.html`, `kill_switch_preview.html`) — swap handwritten `.card`, `.btn-*`, `.badge-*` for Basecoat equivalents. Most-reused bits.
3. Page shells (`overview.html`, `positions.html`, `history.html`, `signals.html`, `analytics.html`) — layout grids on Basecoat's Tailwind-native utilities.
4. `settings.html` — now editable (see §4), built fresh on the new substrate.
5. `login.html` — new.
6. `staged.html` + partial — new, last.

### Live data paths — reuse, don't rewrite

| Data | Current transport | v1.1 transport |
|------|-------------------|----------------|
| Positions | SSE `/stream` (JSON) + HTMX partial `/partials/positions` | Unchanged — add staged-entry payload to `/stream` |
| Overview cards | HTMX partial `/partials/overview` | Unchanged, restyled |
| Trading status | `/api/trading-status` polled via HTMX | Unchanged |
| Active stages | (none) | **New** HTMX partial `/partials/stages` + SSE payload |

SSE is battle-tested in the codebase; extend its payload, don't introduce a second transport.

### Mobile responsiveness

Basecoat's Tailwind classes give responsive breakpoints for free. The current `base.html` sidebar is fixed-width and always-visible — in v1.1 replace with Basecoat `Sidebar` component (an interactive component that DOES need the vanilla JS bundle) so mobile collapses it.

---

## 7. Recommended build order (dependency-honest)

```
Phase 1 — Settings foundation  (1–2 weeks, NO UI yet)
    ├─ AccountSettings dataclass + SettingsStore cache
    ├─ account_settings table + db helpers
    ├─ bot.py wires SettingsStore before TradeManager
    ├─ TradeManager reads effective settings (not AccountConfig) in
    │    _execute_open_on_account and daily-limit paths
    ├─ risk_calculator: fixed-lot branch
    └─ TESTS: effective() returns DB overrides, bootstrap seed from accounts.json,
              risk_mode='fixed' path correct, kill switch still works

Phase 2 — Staged entries  (2–3 weeks, trickiest)
    ├─ staged_entries table + db helpers
    ├─ Executor._zone_watch_loop + _trigger_stage
    ├─ TradeManager persists stages on multi-stage OPEN
    ├─ emergency_close cancels active stages BEFORE closing positions
    ├─ _reconnect_account reconciles stages with MT5 state
    ├─ _cleanup_loop expires old stages
    └─ TESTS: watcher respects _trading_paused, respects _reconnecting,
              respects daily limits, kill switch cancels stages before close,
              reconnect reconciles, stage lot_size frozen on persist

Phase 3 — UI substrate swap  (1 week, isolated)
    ├─ Dockerfile: Tailwind CLI build stage
    ├─ Vendor Basecoat CSS + JS
    ├─ base.html: swap Play CDN for built css
    ├─ Partials & pages restyled (no logic changes)
    ├─ Delete drizzle.config.json
    └─ TESTS: existing dashboard routes still pass integration suite;
              visual smoke on each page

Phase 4 — Login form  (0.5–1 week, depends on Phase 3 styling)
    ├─ config: SESSION_SECRET, DASHBOARD_PASS_HASH
    ├─ SessionMiddleware, /login, /logout
    ├─ _verify_auth swap + RedirectResponse
    ├─ login.html on Basecoat primitives
    ├─ CSRF token for login POST
    └─ TESTS: redirect on unauth, argon2 verify, logout clears session,
              SSE works with cookie auth, HTMX CSRF unaffected

Phase 5 — Settings UI + stages UI  (1 week, depends on 1, 2, 3)
    ├─ /settings page rewrite (editable forms, HTMX hx-post)
    ├─ /api/settings/{account} → settings_store.reload()
    ├─ /staged page + partial
    ├─ SSE /stream emits stages payload
    └─ TESTS: form validation, settings change takes effect on NEXT signal not
              retroactively on pending stages, live stage list updates
```

### Why this order

- **Phase 1 first** because every later phase needs runtime-mutable settings. Building staged entries (Phase 2) against hardcoded `AccountConfig` would require a second pass to rewire later.
- **Phase 2 before UI for staging** because the server-side behavior must be correct and test-covered before we give operators a button. Live trading on real money.
- **Phase 3 (substrate swap) before Phase 4 (login form)** because the login form must be styled with the same tokens as the rest of the dashboard; doing it in the current hand-rolled CSS means rebuilding it twice.
- **Phase 4 (login) before Phase 5 (settings UI)** because settings-edit is the first truly sensitive dashboard action introduced in v1.1 — it writes to DB state that affects live trading. Doing it behind HTTP Basic and then "upgrading" later is asking for an accidental-prod-change window.
- **Phase 5 last** because it integrates all prior phases: needs SettingsStore (1), staged-entry tables (2), Basecoat components (3), and session auth for sensitive POSTs (4).

Phase 1+2 can overlap partially (DB schema work is similar). Phase 3 can run in parallel with Phase 2 since they touch different files. The serial chain is **1 → 2 → 5** and **3 → 4 → 5**.

---

## 8. Integration points (cross-reference)

### External boundaries (unchanged)

| Service | Integration | v1.1 impact |
|---------|-------------|-------------|
| Telegram (Telethon) | `bot.py` NewMessage handler | None |
| Discord (webhook) | `notifier.py` via httpx | Add stage-triggered notifications, kill-switch-cancels-stages notification |
| MT5 bridge (per account) | `mt5_connector.py` gRPC/direct | None — stages reuse `open_order`, `get_price`, `close_position` |
| PostgreSQL | asyncpg pool in `db.py` | Two new tables, several new helpers |
| nginx | proxy-net | None (same port, same app) |

### Internal boundaries

| Boundary | v1.0 mechanism | v1.1 change |
|----------|----------------|-------------|
| bot.py ↔ Executor | Direct object reference | Unchanged |
| Executor ↔ TradeManager | Per-account scoped TradeManager (race-safe v1.0 pattern) | Unchanged; staged-entry triggers use the same scoping |
| Executor ↔ SettingsStore | — | New: read-only reference; writes go through dashboard → SettingsStore |
| Dashboard ↔ Executor | Module-global `_executor` injected by `init_dashboard` | Unchanged |
| Dashboard ↔ SettingsStore | — | New: module-global injected by `init_dashboard(executor, notifier, settings, settings_store)` |
| TradeManager ↔ SettingsStore | — | New: reference passed in constructor, used in lot sizing and gating |
| Everything ↔ db | Module-global `_pool` | Unchanged |

---

## 9. Anti-patterns to avoid

### AP-1: Spinning up a second process for the zone watcher

**Tempting because:** A dedicated worker feels "cleaner."
**Why wrong:** Would require IPC to read `_trading_paused`, `_reconnecting`, `_last_sync` from Executor. Those are in-memory state. Either we replicate through DB (latency + race window where watcher triggers during a reconnect the Executor already detected) or we build a message bus for four booleans.
**Instead:** Zone watcher is an `asyncio.Task` inside `Executor`, peering with `_heartbeat_loop` and `_cleanup_loop`.

### AP-2: Redis pub/sub for settings invalidation

**Tempting because:** Standard cache-invalidation pattern.
**Why wrong:** Exactly one writer (dashboard) and one reader (same process). A `reload(name)` at the write site is strictly simpler and strictly correct.
**Instead:** Write-through in-process cache. Reload is a direct method call in the same event loop.

### AP-3: Letting the zone watcher bypass `is_accepting_signals()`

**Tempting because:** The stage is a "follow-up" to an already-accepted signal.
**Why wrong:** Between signal time and stage-trigger time, kill switch may have fired or a reconnect started. Stages that ignore the gate will open positions during a paused-trading window. v1.0 spent effort establishing that gate; respect it.
**Instead:** `_trigger_stage` calls `is_accepting_signals()` at the top. Second line of defense: `emergency_close` cancels active stages in DB.

### AP-4: Mutating `AccountConfig` in place on settings changes

**Tempting because:** The dict already exists.
**Why wrong:** `AccountConfig` is used by tests and serialized in a few places; treating it as mutable invites "but what about THIS reader" spelunking. Also `dataclass` without `frozen=True` gives no protection.
**Instead:** `AccountConfig` stays static bootstrap. Runtime-tunable values live in `AccountSettings`. Effective values read via `SettingsStore.effective(name)`.

### AP-5: Keeping HTTPBasic as a fallback alongside session auth

**Tempting because:** "Ship login without breaking existing integrations."
**Why wrong:** Two auth paths double the attack surface and the confusion. Nothing automates HTTPBasic against this dashboard today — the user logs in via browser — so migration is cheap.
**Instead:** Replace HTTPBasic cleanly in one phase. Keep `DASHBOARD_PASS` env as a bootstrap fallback for ONE release (per STACK.md §3) — only transitional concession.

### AP-6: Adding alembic mid-milestone

**Tempting because:** Schema changes are the canonical alembic use case.
**Why wrong:** Per STACK.md §5, DBE-01 (alembic) was explicitly deferred. Introducing it mid-v1.1 drags in a new workflow and test infrastructure for two new tables.
**Instead:** Stay on `CREATE TABLE IF NOT EXISTS` in `db.init_schema()`. Flag alembic as a v1.2 candidate.

---

## 10. Scaling / load considerations

v1.0 is designed for single-user, small number of accounts (1–5), moderate signal rate (<50/day per group). v1.1 keeps the same envelope.

| Dimension | v1.0 load | v1.1 load | Risk |
|-----------|-----------|-----------|------|
| MT5 price fetches per minute | ~2 per account (heartbeat only) | +6–12 per account with zone watcher @ 5–10s cadence, **only when stages are active** | LOW — MT5 bridges handle >1 Hz; adaptive interval keeps idle cost at v1.0 level |
| DB queries per minute | ~20–30 | +~5–10 from stage polling (one `SELECT * FROM staged_entries WHERE status='active'` per loop) | LOW — indexed on `status`; single-row queries otherwise |
| Session cookie verification | N/A | Every dashboard request (~microseconds) | NONE |
| Built CSS size | Play CDN ~350 KB uncompressed per cold load | ~30–50 KB gzipped via built `app.css` | Strictly better |

Watcher cadence is the only dial worth tuning. Recommend 10 s by default, configurable via `GlobalConfig.zone_watch_interval_seconds`.

---

## 11. Confidence & open questions

| Area | Confidence | Basis |
|------|------------|-------|
| Executor zone-watcher placement | HIGH | Direct read of `executor.py` — pattern mirrors `_heartbeat_loop` exactly |
| Staged-entry cross-cutting interactions | HIGH | Read of `emergency_close`, `_reconnect_account`, `_execute_open_on_account` confirms gate points |
| SettingsStore design | HIGH | Single-process app, single writer, no distributed concerns |
| Login form layering | HIGH | Verified via STACK.md and `dashboard.py` dependency structure; SessionMiddleware docs |
| Basecoat template migration cost | MEDIUM | Basecoat is pre-1.0 (v0.3.3 per STACK.md) — might hit rough edges in specific components; mitigated by "vendor + copy" philosophy |
| Stage allocation semantics | MEDIUM | `stage_allocation: list[float]` is a design choice; alternative is "stages share lot equally, user picks count." Recommendation is the former — confirm with user during Phase 2 design |
| Stage target-band derivation | MEDIUM | "Stages 2..N fire as price re-enters the zone" — the exact sub-band split (equal-width? single re-entry?) isn't fully pinned by the feature description. Resolve at Phase 2 kickoff |

### Open questions to resolve before / during each phase

1. **Phase 2 kickoff — BAND SEMANTICS.** How are stage-N target bands computed from the original zone? Equal-width slices? All stages wait for full zone re-entry? Single re-entry triggers all remaining? → User decision, behavioral spec.
2. **Phase 2 kickoff — STAGING TRIGGER MODEL.** PROJECT.md reads "text-only signals open 1 initial position immediately; follow-up signal with zone/SL/TP opens additional positions." That wording suggests a **two-signal correlation** (first text signal = stage 1, second signal with details = stages 2+) rather than STACK.md §4's **single-signal-with-zone model** (one signal, N stages queued from its zone). These are different features architecturally:
   - **Zone-watcher model** (STACK.md §4): one OPEN signal produces N stages; watcher polls price and triggers 2..N as price re-enters bands.
   - **Two-signal correlation model** (PROJECT.md wording): first signal fills stage 1 (market, no zone needed); a second signal "attaches" zone/SL/TP and produces stages 2..N, either executed immediately or queued as limits at zone-mid (reusing v1.0 limit logic).
   
   **This must be resolved before Phase 2 begins.** If two-signal correlation is the intent, `signal_parser` needs a correlation heuristic (same symbol + direction, within N minutes), the zone watcher simplifies or disappears (stages 2..N just become N-1 new OPEN executions on the second signal), and the staged_entries table may not even be necessary — it becomes a parent-ticket column on `trades`. Architecturally simpler, but requires signal-correlation spec. Recommend the orchestrator include this as the #1 question in the discussion phase.
3. **Phase 4 — MULTI-USER?** Single admin is the current model. Multi-user would be a small delta (`account_users` table + password-per-user) but not hinted in PROJECT.md. Confirm single-user.
4. **Phase 5 — AUDIT TRAIL UI.** `account_settings.updated_by` is captured; decide whether to surface "last changed by X at Y" in the settings UI or only log.

---

## Sources

- Existing codebase: `/Users/murx/Developer/personal/telebot/bot.py`, `executor.py`, `trade_manager.py`, `dashboard.py`, `db.py`, `models.py`, `risk_calculator.py`, `templates/`, `accounts.json`
- `/Users/murx/Developer/personal/telebot/.planning/PROJECT.md`
- `/Users/murx/Developer/personal/telebot/.planning/research/STACK.md`

---
*Architecture research for: Telebot v1.1 integration*
*Researched: 2026-04-18*
