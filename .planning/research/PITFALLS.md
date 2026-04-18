# Pitfalls Research — Telebot v1.1

**Domain:** Live-money MT5 trading bot — adding staged-entry execution, per-account runtime settings, shadcn/Tailwind dashboard redesign, and login form on top of a shipped v1.0.
**Researched:** 2026-04-18
**Confidence:** HIGH — every pitfall below is anchored to a specific line in the current codebase (`executor.py`, `trade_manager.py`, `dashboard.py`, `templates/base.html`) or to a named v1.0 requirement (REL-*, EXEC-*, SEC-*). These are not generic web/trading pitfalls; they are "what will break when these four features are added to *this* bot."

The failure mode we fear most is simple: **an in-flight trade gets stuck in a partial state.** Every pitfall below is a specific mechanism by which that can happen, plus the settings/UI/auth gotchas that compound it.

---

## Critical Pitfalls

### Pitfall 1: Text-only signal opens an unbounded-risk "orphan" position

**What goes wrong:**
Phase 1's staged entry design says a text-only signal like "Gold buy now" opens an initial market position *immediately*, with later stages queued until a follow-up signal carrying zone/SL/TP arrives. If the follow-up never comes (Telegram channel goes quiet, provider forgets, parser misses it), the bot holds an open position on live money with **no SL and no TP** — unbounded loss in either direction and no automatic exit.

**Why it happens:**
- v1.0's `_execute_open_on_account` (`trade_manager.py:263-270`) calls `connector.open_order(..., sl=jittered_sl, tp=jittered_tp or 0.0, ...)`. Passing `sl=0.0` is a legal call against MT5 — the broker will happily accept a protected-only-in-theory trade.
- The natural v1.1 refactor is "if this is the text-only stage, just skip SL/TP until follow-up arrives." That skip is the trap.
- The reliability hardening in v1.0 (heartbeat, reconnect, kill switch) all assume positions have SL and TP set at open.

**How to avoid:**
- **Mandate a default protective SL at text-only-stage open.** Compute it from account setting `default_text_only_sl_pips` (new config knob, e.g. 100 pips); never submit `sl=0.0` for an initial text-only fill.
- **Enforce a follow-up timeout.** When a text-only initial position opens, schedule a watchdog: if no valid follow-up within N minutes (configurable, default 30), either auto-close the position or force-set a conservative SL/TP from heuristics (e.g. SL = 1R from entry based on default_risk, TP = 2R).
- **Require signal correlation rules** to match follow-ups to the initial text-only trade: `(symbol, direction, account, window_seconds)`. Without this, a late zone signal from another symbol could attach to the wrong orphan.
- **Hard cap orphan count per account**: if `account_settings.max_orphan_text_only` is reached, reject further text-only signals until one resolves.

**Warning signs:**
- A position exists in DB with `status="opened"` and `sl=0.0` or `sl=NULL`.
- `staged_entries.status="awaiting_followup"` rows with `age > timeout` and no matching follow-up received.
- Risk exposure per account (sum of max-loss-if-SL-hit) exceeds the account-level cap.

**Phase to address:** **Phase 1 (staged-entry execution)** — this is the single most important pitfall of v1.1 because it directly violates the "real money; no regressions on live trading" safety bar.

---

### Pitfall 2: v1.0 duplicate-direction guard silently rejects staged entries

**What goes wrong:**
A 3-stage signal opens stage 1 successfully. Stages 2 and 3 try to open the same direction on the same symbol and are **silently rejected** by the existing guard at `trade_manager.py:187-190`:

```python
for pos in positions:
    if pos.direction == signal.direction.value:
        reason = f"Already have a {signal.direction.value} position open on {signal.symbol}"
        return {"account": name, "status": "skipped", "reason": reason}
```

Result: the staged-entry feature appears to work but only ever opens stage 1. Indistinguishable from a broken zone watcher unless someone reads the log.

**Why it happens:**
v1.0's guard was written to prevent *duplicate* signals from double-filling the same idea. Staged entries are *intentional* multiple fills of the same idea. The guard has no concept of "this fill is stage N of signal X."

**How to avoid:**
- Tag the existing call site with `signal.is_staged` or check `signal.staged_entry_id` and **skip this guard** when true.
- Introduce a distinct guard: "reject if a non-staged same-direction position is already open for this symbol." This preserves the original intent (anti-duplicate) while permitting staged stacking.
- Integration test must cover: stage-1 open, stage-2 try to open → must succeed; unrelated signal same direction while stages queued → must still be blocked.

**Warning signs:**
- `executed` count per staged signal is always 1 in logs.
- `staged_entries` rows stuck in `pending` state with price in-zone.

**Phase to address:** **Phase 1**.

---

### Pitfall 3: `max_open_trades` and `max_daily_trades_per_account` starve staged entries

**What goes wrong:**
Two existing caps turn a single signal into "most of the daily budget":

- `trade_manager.py:181-184` — `max_open_trades` is a **per-symbol** cap. A 5-stage signal on XAUUSD with `max_open_trades=3` clips stage 4 and 5.
- `trade_manager.py:168-172, 289` — `max_daily_trades_per_account` decrements on every successful `open_order`. Each stage fill increments `trades_count`. A 5-stage signal consumes 5/30 of the daily budget from a single provider message. Subsequent independent signals get dropped mid-afternoon with no user understanding why.

**Why it happens:**
Both caps predate the concept of "N fills = 1 trade idea." They were designed when 1 signal = 1 fill.

**How to avoid:**
- Introduce the concept explicitly: `AccountSettings.max_staged_positions_per_signal` (default = `max_open_trades`) is a *per-signal* cap; `max_open_trades` becomes a per-symbol cap across all signals.
- Decide the daily-limit accounting rule **up front** and document it in `PROJECT.md`:
  - **Option A (recommended):** 1 signal = 1 trade for daily-limit purposes, regardless of stage count. Increment `trades_count` only on stage 1.
  - **Option B:** each fill counts. Simpler, but a single signal can exhaust the daily budget.
- Either way, the roadmap must choose before Phase 1 starts, because it changes the DB schema (Option A needs `signal_id` attribution on `trades_count`).

**Warning signs:**
- Logs show `"Max open trades (N) reached for {symbol}"` while `staged_entries.status="pending"`.
- Daily summary shows one signal consumed >30% of daily budget.

**Phase to address:** **Phase 1** — decision must be made in Phase 1 planning; implementation in Phase 1 execution.

---

### Pitfall 4: Kill switch fires mid-stage and leaves a partial state

**What goes wrong:**
Operator hits the emergency kill switch while a 5-stage signal has 2 stages filled and 3 queued in the zone watcher.

- `executor.py:226` sets `_trading_paused = True` and `emergency_close` closes all open positions (stages 1 and 2 are closed ✓).
- But the **3 queued stages in DB** (`staged_entries.status="pending"`) are untouched. When the operator later calls `resume_trading()`, the zone watcher sees stale `pending` rows and may re-trigger them — *hours after the signal was meant to expire*, possibly at a very different price.
- Worse: the zone-watcher loop only checks `_trading_paused` at iteration entry. A stage whose price-in-zone check passed a microsecond before `_trading_paused` was set can still submit an `open_order` *after* the flag flips, so the kill switch has to re-close a position that was just opened.

**Why it happens:**
v1.0 emergency_close is built around "positions that exist on MT5." Staged entries add a new state — "intent to open a position" — that lives only in DB and is invisible to `emergency_close`.

**How to avoid:**
- `emergency_close` must also execute `UPDATE staged_entries SET status='cancelled_by_kill_switch' WHERE status IN ('pending','awaiting_followup')` **before** closing positions. Order matters: queue must be drained first, else the watcher can open a new position mid-close.
- Zone-watcher loop must check `self._trading_paused` **inside** each per-stage tick, not only at loop entry — between the price-in-zone check and the `open_order` call.
- `resume_trading()` must NOT un-cancel the `cancelled_by_kill_switch` rows. Operator re-creates intent by re-sending the signal.
- Integration test: kick off a 5-stage signal, trip kill switch after stage 2 fills, assert all 5 `staged_entries` rows are `cancelled_by_kill_switch` and no new positions open during or after `emergency_close`.

**Warning signs:**
- After kill-switch + resume, positions appear on MT5 with no corresponding Telegram signal in the last N minutes.
- `staged_entries.status="pending"` exists for signals older than `signal.max_age_minutes`.

**Phase to address:** **Phase 1** — integration with kill switch is non-negotiable.

---

### Pitfall 5: Reconnect mid-stage-sequence causes duplicates or orphaned intents

**What goes wrong:**
MT5 heartbeat fails while stage 2 of 5 is mid-`open_order`. `executor.py` starts reconnect. Three failure modes:

1. **Duplicate fill:** the `open_order` TCP call actually reached the broker and filled, but the response never returned. Telebot marks the stage failed, reconnects, and on retry opens *another* stage 2 position. Two fills, one intended.
2. **Orphaned intent:** reconnect drops signals during reconnection (`executor.py:113-116` — `_execute_single_account` skips disconnected accounts). Stages 3–5 were queued for the reconnecting account; the watcher sees them, skips, moves on. After reconnect, they're still in DB as `pending` — but the price may have moved far past the zone. Do we fill them late, or cancel?
3. **Missed sync:** `_sync_positions` (`executor.py:208-217`) only *logs* the count — it doesn't reconcile DB `staged_entries` against actual MT5 positions. If the broker closed a position during disconnect (e.g. stop-out), DB still says it's open.

**Why it happens:**
v1.0 reconnect was built for "signals are atomic, either delivered or dropped." Staged entries are multi-phase and stateful.

**How to avoid:**
- **Idempotency key on stage fills:** write `staged_entries.comment = f"telebot-{signal_id}-s{stage}"` and on reconnect retry, query MT5 positions/orders for that comment before submitting a new `open_order`. If a position with that comment exists → mark stage as filled, don't re-open.
- **Post-reconnect reconciliation:** extend `_sync_positions` into a true reconciler that reads DB `staged_entries` for the account and checks each against the current MT5 position list by comment. Mark orphaned DB rows `abandoned_reconnect`, alert operator.
- **Explicit policy for stale pending stages after reconnect:** "if reconnect duration > N seconds, cancel all `pending` stages for affected accounts; notify operator." Don't silently fill at stale prices.

**Warning signs:**
- Two MT5 positions with the same `telebot-{sid}-s{n}` comment.
- Reconnect restore notification followed by an `open_order` within 1 second on the just-reconnected account (possible idempotency violation).
- DB `staged_entries.status="pending"` rows whose `signal.created_at` is older than `signal.max_age_minutes`.

**Phase to address:** **Phase 1**.

---

### Pitfall 6: Zone-watcher cadence fires late; fills outside the zone

**What goes wrong:**
The zone watcher polls MT5 prices on a 10s cadence (STACK.md §4 suggestion). On a fast-moving instrument (XAUUSD during US open, BTCUSD), price can enter and exit the entry zone between two polls. The tick at t=10s sees price outside the zone and skips. The tick at t=20s sees price re-enter, fires `open_order` — but the current market is now far past where it briefly was, so the fill lands outside the zone entirely.

**Why it happens:**
The zone is computed from a signal snapshot and treated as a threshold; the watcher's sampling rate is the limiting factor, not the zone width.

**How to avoid:**
- **Use MT5 tick/price streaming if the connector supports it** (MT5 REST server used here may not — confirm in Phase 1). If not, reduce cadence under high-volatility symbols (e.g. 2s for XAU/BTC, 10s for majors).
- **Pre-flight price re-check** immediately before submitting `open_order`: re-fetch bid/ask, verify still within zone, use a small tolerance band (e.g. zone ± 0.5 × zone_width). If outside → skip this tick, re-queue.
- **Record `watcher_trigger_price` and `fill_price` on each stage** and alert when delta exceeds tolerance — lets operators detect latency problems before they become account drawdowns.

**Warning signs:**
- `staged_entries.trigger_price` and `trades.entry_price` diverge by more than (zone_high − zone_low).
- Stage fills cluster immediately after a volatility spike.

**Phase to address:** **Phase 1**.

---

### Pitfall 7: Runtime settings mutation mid-stage produces inconsistent risk

**What goes wrong:**
Operator edits `risk_percent` from 1% to 0.5% via the settings page while a 5-stage signal has stage 2 filled and stages 3–5 pending. Stage 3 fires its `calculate_lot_size` call (`trade_manager.py:224`) and reads the new 0.5% value. Stages 1 and 2 are at the old 1%. The signal now has three different lot sizes across five stages, violating the risk plan for the idea.

**Why it happens:**
`calculate_lot_size` reads `acct.risk_percent` at call time. If the settings page writes into the same `AccountConfig` object (or re-reads from DB per call), the mutation is instantly visible to every in-flight stage.

**How to avoid:**
- **Snapshot `AccountSettings` into the `staged_entries` row at signal receipt**: store `risk_mode`, `risk_percent` (or `fixed_lot`), `max_stages`, `stage_allocation` at creation time. Every stage reads the snapshot, not the live settings object.
- Alternative: immutable `SignalExecutionPlan` object passed between stages, carrying the frozen settings.
- Settings page changes apply only to **new signals received after the mutation**.
- Document this rule in both the settings UI ("changes apply to next signal only") and the audit log.

**Warning signs:**
- Stages of the same `signal_id` have different `lot_size` / `risk_percent` in the DB.

**Phase to address:** **Phase 2 (per-account settings)** — but the snapshot mechanism is implemented in Phase 1 (staged-entries table schema).

---

### Pitfall 8: Settings page lets operator set invalid values that brick the bot

**What goes wrong:**
Operator types `risk_percent = 50` (meant 0.5), saves. Next signal calculates a lot size 100× normal, hits broker `InvalidVolume` error or — worse — submits and blows the account.

Or: `max_open_trades = 0` by typo, blocks all future trades silently.

Or: `risk_mode = "fixed"` without `fixed_lot` set → `calculate_lot_size` returns 0 → all future signals fail.

**Why it happens:**
Text inputs + runtime mutation + real money = any typo is a live incident.

**How to avoid:**
- **Hard caps in server-side validation**, not just client-side: `0 < risk_percent <= 5.0`, `0 < fixed_lot <= max_lot_size`, `1 <= max_open_trades <= 50`, `1 <= max_stages <= 10`. Reject the form with a clear error on any violation.
- **Dry-run preview**: after save, compute and display "if a typical signal arrives now, the lot size would be X — confirm." This catches order-of-magnitude errors.
- **Audit log every change** with before/after values, timestamp, authenticated user. Store in `account_settings_audit` table. Real money demands forensics.
- **Rollback button** on the settings page using the audit log (one-click revert to previous value).

**Warning signs:**
- After a settings save, the next signal has `status="failed"` with `reason=InvalidVolume` or `reason="Calculated lot size is 0"`.

**Phase to address:** **Phase 2**.

---

### Pitfall 9: `accounts.json` vs DB `account_settings` authority confusion

**What goes wrong:**
Per STACK.md: DB wins, `accounts.json` is bootstrap/seed. Operator edits `accounts.json` intending to change risk%, restarts the container. `accounts.json` loads but DB already has a newer row — so the restart appears to have done nothing. Operator restarts again, escalates, confused.

**Why it happens:**
Two sources of truth is a classic operator trap. The intent ("DB wins") is reasonable but invisible at the file-system level.

**How to avoid:**
- **Log the authority resolution at startup**, per account, at INFO:
  ```
  [acct:main] risk_percent: accounts.json=1.0, db=0.5 → effective=0.5 (DB override)
  ```
- **Add a `/settings` page "origin" column**: each field shows whether its value is from `accounts.json` (bootstrap) or DB (override).
- **Document in `README.md`**: "`accounts.json` is a one-time seed. To change settings at runtime, use the dashboard. To reset, use `/api/settings/{account}/reset-to-json`."
- **Provide a reset-to-JSON endpoint** so operators who *want* JSON to win have a path.

**Warning signs:**
- Operator reports "I changed the config file, nothing happened."

**Phase to address:** **Phase 2**.

---

### Pitfall 10: Tailwind purge strips classes used in Python-string HTML responses

**What goes wrong:**
Dashboard HTMX responses embed HTML directly in Python strings — e.g. `dashboard.py:219` returns `HTMLResponse(f'<span class="text-green-400">Closed #{ticket}</span>')`, `dashboard.py:221, 236, 244, 260, 268` likewise. These classes exist only in `.py` source, not `.html` templates.

When Phase 3 switches from `cdn.tailwindcss.com` (no purge — every class available) to the Tailwind standalone CLI with JIT purge, the default `content` glob scans `templates/**/*.html` and misses `*.py` files. The classes get dropped from the built CSS. Result: close-position responses render as **unstyled text** — the "success" green and "failure" red disappear, undermining the visual feedback operators rely on under stress.

**Why it happens:**
The CDN build is silently forgiving; the production build is strict. This is the #1 "works in dev, broken in prod" failure mode of a Tailwind migration.

**How to avoid:**
- **`tailwind.config.js` `content` glob MUST include `.py` files**:
  ```js
  content: ["./templates/**/*.{html,jinja}", "./**/*.py"],
  ```
- **Safelist** the critical status classes explicitly (belt and suspenders):
  ```js
  safelist: ["text-green-400", "text-red-400", "text-yellow-400", "bg-red-500", ...]
  ```
- **CI check**: build the CSS, grep the output for the critical class names. Fail the build if any are missing.
- **Audit all `HTMLResponse(f'...')` call sites** in `dashboard.py` before Phase 3 starts and enumerate the exhaustive class set.

**Warning signs:**
- Post-deploy smoke test: "close position" button shows plain black text instead of green.

**Phase to address:** **Phase 3 (dashboard redesign)**.

---

### Pitfall 11: Basecoat JS components lose their bindings after HTMX swaps DOM

**What goes wrong:**
Basecoat's interactive components (Dropdown Menu, Popover, Select, Sidebar, Tabs, Toast) bind to DOM nodes on page load. When HTMX swaps in new HTML from `/partials/positions` or `/partials/overview`, the *new* nodes have no listeners. Dropdowns appear but don't open; tabs look styled but don't switch.

**Why it happens:**
HTMX swaps innerHTML/outerHTML; any JS that bound to the pre-swap nodes is now bound to dead references.

**How to avoid:**
- Hook `htmx:afterSwap` (and `htmx:afterSettle` for SSE) to re-run Basecoat's init over the swapped subtree:
  ```js
  document.body.addEventListener('htmx:afterSwap', (e) => {
    window.basecoat?.init?.(e.detail.target);  // or equivalent API
  });
  ```
- Confirm the exact init API in Basecoat v0.3.3 docs before Phase 3 (JS surface may differ).
- **Manual regression test after each swap-target change**: toggle a dropdown *inside* a partial, verify it works.

**Warning signs:**
- A component works on initial page load but stops working after the 2s SSE refresh.

**Phase to address:** **Phase 3**.

---

### Pitfall 12: Cache-busting failure during Tailwind CDN→built deploy

**What goes wrong:**
Phase 3 deploys the new Tailwind-built CSS with filename `static/css/app.css`. Operator's browser has the old CDN-era HTML cached; nginx serves the new CSS; result is new layout rendered against old class names (or vice versa). In worst case, the kill-switch button becomes invisible during a market-volatility window.

**Why it happens:**
Deploys during live hours + stable filename + browser caches = stale-asset mismatch for every concurrent operator. Unlike a redesign of a CRUD app, this dashboard is safety-critical — an invisible kill-switch button is an incident.

**How to avoid:**
- **Hashed filename**: `static/css/app.{sha}.css`, referenced from `base.html` via a Jinja global populated at build time (e.g. `{{ static_version }}`).
- **Deploy during market-closed window** (weekend or low-liquidity hour). Add this as a deployment checklist item, not a hope.
- **Force-reload banner**: `base.html` compares a server-sent version to a cookie; if different, displays "Dashboard updated — reload" HTMX banner.
- **Explicit `Cache-Control: no-cache` on HTML responses** (so HTMX fragments re-fetch), while `/static/*` gets long-lived `max-age` with hashed names.

**Warning signs:**
- Post-deploy operator reports "buttons look weird" / "kill switch is hidden."

**Phase to address:** **Phase 3**.

---

### Pitfall 13: Login CSRF strategy conflicts with existing HTMX-header CSRF

**What goes wrong:**
`_verify_csrf` at `dashboard.py:67-74` rejects any POST/PUT/DELETE/PATCH that lacks the `hx-request` header. The login POST is the only endpoint where the user is **not yet authenticated** — they might be:
- submitting via an HTMX `hx-post` (header present) → works,
- submitting via a plain `<form method="POST">` after a session expiry during idle — header **absent** → blocked with 403, user sees a generic error, can't log back in.

Worse: if an attacker-controlled page CAN set custom headers (it can't, normally — that's the whole point of `hx-request`-based CSRF), the "login POST is exempt" exemption must NOT leak into authenticated endpoints.

**Why it happens:**
Single-header CSRF works for an authenticated HTMX SPA; login is the one place where pre-auth form submission must be supported.

**How to avoid:**
- **Double-submit-cookie pattern for login** only: GET `/login` sets a signed CSRF cookie and renders a hidden `<input name="csrf_token">`; POST `/login` verifies they match. Keep HTMX-header CSRF for all authenticated endpoints.
- **Explicitly whitelist** `/login` in `_verify_csrf`, do not generalise the exemption.
- **Render the login form with `hx-post` and fall back to `action="/login" method="POST"`** — HTMX-capable browsers use the header; plain fallback uses the cookie token. Both paths work.
- **Integration test both paths**: HTMX POST succeeds; plain form POST with valid token succeeds; plain form POST without token returns 403.

**Warning signs:**
- Users report "I can't log in after the page was open for a few hours."
- Login POST 403 rate spikes after session expiry windows.

**Phase to address:** **Phase 4 (login form)**.

---

### Pitfall 14: `SESSION_SECRET` rotation logs everyone out mid-action

**What goes wrong:**
Operator rotates `SESSION_SECRET` (good hygiene). Every cookie is invalidated. Any in-flight HTMX POST — `modify-sl`, `close-partial`, `emergency-close` — fails with 401. If the operator was halfway through confirming a kill switch, the confirmation is lost.

**Why it happens:**
Session secret is a global signing key; rotating it is all-or-nothing.

**How to avoid:**
- **Document the rotation runbook**: "Rotation logs out all operators. Do not rotate during active trading hours. Rotate during market-closed window."
- **Support dual-key verification for a grace window** (optional, more code): `SESSION_SECRET` + `SESSION_SECRET_PREV`. Starlette's `SessionMiddleware` does not do this out of the box — would need a small wrapper. Not recommended for v1.1; mention as v1.2 candidate.
- **Alert Discord on session-secret change** so operators know why they were logged out.

**Warning signs:**
- Spike in 401s on authenticated endpoints immediately after a deploy.

**Phase to address:** **Phase 4**.

---

### Pitfall 15: `DASHBOARD_PASS` → `DASHBOARD_PASS_HASH` migration leaves a plaintext credential in env

**What goes wrong:**
STACK.md proposes "keep `DASHBOARD_PASS` for one release as a fallback that is auto-upgraded to the hashed form on first successful login, then remove." Implementation risk: after the first successful login writes the hash into env/config, **the plaintext `DASHBOARD_PASS` is still set in `docker-compose.yml` and the container env**. Future `docker exec env` or a compromised container dumps both.

**Why it happens:**
Auto-upgrade works in memory / in DB but the env var source (`docker-compose.yml`, systemd unit, shell export) is untouched.

**How to avoid:**
- **Startup must refuse to boot when both `DASHBOARD_PASS` and `DASHBOARD_PASS_HASH` are set** after the migration window. Log the exact remediation ("remove `DASHBOARD_PASS` from your env now that the hash is set").
- **Provide an explicit CLI helper** — `python generate_password_hash.py` → prints `DASHBOARD_PASS_HASH=...` → operator pastes into env, removes `DASHBOARD_PASS`, restarts. Explicit is safer than auto.
- **Don't write the hash back into the container env** (can't, anyway); write to DB `app_config.dashboard_pass_hash` so the env-var flow stays declarative.
- **Document the migration in `README.md` and `VPS_DEPLOYMENT_GUIDE.md`** with exact copy-paste steps.

**Warning signs:**
- Both env vars still set two weeks after migration release.
- Hash has never been written to DB on a given deploy.

**Phase to address:** **Phase 4**.

---

### Pitfall 16: No rate limiting on login → brute force risk

**What goes wrong:**
The basic-auth endpoint on v1.0 is lightly protected by the obscurity of the URL and the user/pass prompt. A styled login form is easier to automate against. Without rate limiting, a bot can attempt thousands of passwords per minute. `argon2-cffi` defaults are strong (~500ms/verify), so it's not trivial, but sustained attacks are still feasible at tens of req/s across parallel connections.

**Why it happens:**
FastAPI has no built-in rate limiter. The instinct is "we'll add it later"; later never comes.

**How to avoid:**
- **Rate-limit at nginx** (preferred for v1.1 — already in the stack). Add `limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;` and `limit_req zone=login burst=3 nodelay;` to the nginx server block for `/login`.
- **Also lock the account after N failures** (e.g. 10 failed logins in 15 minutes → 1 hour lockout). Store attempt counts in DB; reset on success.
- **Log every failed login** with IP, user-agent, timestamp for forensics.
- **Never reveal whether it was the username or password that was wrong** ("Invalid credentials," not "No such user").

**Warning signs:**
- Nginx access log shows high `/login` POST volume from a single IP.
- DB `failed_login_attempts` grows unbounded.

**Phase to address:** **Phase 4** (app-level lockout) + **nginx config update** as part of Phase 4 deployment.

---

### Pitfall 17: Schema migration trap — adding columns to existing tables without alembic

**What goes wrong:**
STACK.md recommends deferring alembic and using `CREATE TABLE IF NOT EXISTS` for new tables. This works for `account_settings`, `staged_entries`, `account_settings_audit`, `failed_login_attempts`. It breaks the moment someone proposes "add `stage_number` column to existing `trades` table." `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table; the column is silently missing; ORM reads fail or return NULL.

**Why it happens:**
Mid-milestone pressure to "just add one field" to an existing table.

**How to avoid:**
- **Hard rule for v1.1**: "additive only, new tables only. No `ALTER TABLE` on tables that existed in v1.0."
- **Attach stage metadata in a new `trade_stages` table** with `FK(trade_id)` instead of adding columns to `trades`. One extra JOIN; zero migration risk.
- **Pre-commit lint rule**: grep `ALTER TABLE` in any SQL in the repo; fail if found without an accompanying alembic migration.
- **If an ALTER is truly unavoidable, promote DBE-01 (alembic) into v1.1 before writing the SQL** — don't hand-roll migration code in `init_schema()`.

**Warning signs:**
- Any PR diff containing `ALTER TABLE` in the SQL layer.

**Phase to address:** **Phase 1** (decide the v1.1 schema discipline in Phase 1 plan).

---

### Pitfall 18: SSE stream and HTMX polling race against kill-switch state

**What goes wrong:**
`dashboard.py:372-396` streams position updates every 2s via SSE; `/api/trading-status` is polled by HTMX. Operator clicks "emergency close." In the 2s window between click and the next SSE frame, they see positions still listed and mistakenly think the kill switch failed. They click again; second kill-switch action is a no-op (`_trading_paused` is already True) but may trigger a second "TRADING PAUSED" notification.

With the v1.1 UI overhaul, this confusion is magnified if the redesign changes how status updates render (e.g. Basecoat toast that only triggers on state *change*, not state *value*).

**Why it happens:**
Eventual consistency between action and feedback; users expect instant visual confirmation under stress.

**How to avoid:**
- **Optimistic UI**: on kill-switch click, immediately swap the button region to "Closing… pending confirmation" before the server responds. Then HTMX replaces with the final server-confirmed state.
- **Idempotent kill switch**: already mostly is (`_trading_paused = True` is idempotent); ensure the *notification* doesn't double-fire. Track "already-notified" state per activation.
- **Accelerate SSE cadence during kill-switch window**: send an extra frame immediately on state change. Easiest: have `emergency_close` notify an `asyncio.Event` that the SSE loop awaits instead of pure `sleep(2)`.

**Warning signs:**
- Double "TRADING PAUSED" Discord notifications within seconds.
- Operator reports "I clicked kill switch three times."

**Phase to address:** **Phase 3**.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Use `HTMLResponse(f'<span class="...">...</span>')` from Python to return HTMX fragments | Fast, no template round-trip | Classes invisible to Tailwind purge; styles randomly disappear after build | **Never** in v1.1 — move every such string into a Jinja partial before Phase 3 |
| Skip the `max_orphan_text_only` cap, assume follow-ups always arrive | Simpler Phase 1 | First time a provider "forgets" the follow-up, account has unbounded exposure | Never — hard cap is required |
| Auto-upgrade `DASHBOARD_PASS` to hash on first login, leave env var in place | Zero-downtime migration | Plaintext credential in env indefinitely | Only in the single release window; refuse-to-boot after |
| Poll MT5 every 10s uniformly for zone watcher | Simple implementation | Fills outside zone on volatile symbols | Acceptable for majors; use faster cadence for XAU/BTC |
| Run Tailwind CDN in prod (current v1.0 state) | Zero build tooling | JIT in browser every load; production blocker; compounding debt on top of Basecoat | **Resolved by Phase 3** — cannot continue into v1.2 |
| `ALTER TABLE` without alembic "just this once" | Avoid adding alembic mid-milestone | One missed migration on the VPS = silent data corruption | **Never** — additive-only discipline in v1.1, alembic in v1.2 |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| MT5 REST server + zone watcher | Poll price with no spread awareness; use mid-price for zone check | Use `bid` for SELL, `ask` for BUY entry (matches `trade_manager.py:205`); never mid |
| `emergency_close` + `staged_entries` DB | Only close positions; leave queued stages pending | Drain queue (cancel `staged_entries`) **before** closing positions |
| Reconnect + in-flight `open_order` | Retry naively on reconnect | Use comment-based idempotency keys; check MT5 first |
| HTMX + Basecoat JS | Assume bindings persist after swap | Re-init Basecoat in `htmx:afterSwap` |
| Starlette SessionMiddleware + HTMX | Session expiry during in-flight POST returns 401 silently | HTMX `htmx:responseError` handler → redirect to `/login` |
| Nginx reverse proxy + SSE | Nginx buffers SSE; operator sees updates in bursts | `X-Accel-Buffering: no` header (already set in `dashboard.py:395` — preserve in Phase 3) |
| argon2-cffi + Python 3.12 | Use default params blindly | Default params are fine; call `check_needs_rehash` on each successful verify for future-proofing |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Zone watcher queries all `pending` stages every tick, no index | DB CPU climbs with signal volume | Composite index on `staged_entries(status, account, signal_id)` | ~100 concurrent pending stages |
| SSE loop re-queries all accounts + positions every 2s | MT5 connection load + DB load grows linearly in operators × accounts | Cache account/position snapshot in-memory, invalidate on state change | ~5 concurrent operators |
| Tailwind full rebuild on every container build | Build time grows with template count | Cache `node_modules`-equivalent (the standalone CLI binary + output) between builds; use Docker layer caching on `static/` | ~50 templates |
| Zone watcher polling MT5 for every signal every 10s | API rate limit pressure | Batch price requests across symbols in one call if connector supports; else dedupe per symbol | Many accounts × many open signals |
| `account_settings_audit` never pruned | Table grows forever | Nightly prune rows older than 90 days → CSV archive (mirrors DB-03 pattern) | ~1 year of daily edits |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Logging the submitted password on login failure for "debugging" | Password leak in journalctl | Never log submitted credentials; log only `username + timestamp + ip` |
| Returning different error messages for "user not found" vs "wrong password" | User enumeration | Single generic "Invalid credentials" response; same latency profile (always call `argon2.verify` even on unknown user, with a dummy hash) |
| Putting `SESSION_SECRET` in `docker-compose.yml` checked into git | Cookie forgery on secret leak | Use `.env` (not committed) with `env_file` reference; rotate on any leak |
| Skipping CSRF exemption on login POST and blocking legitimate login | Availability failure | Double-submit-cookie on `/login` only; HTMX-header CSRF elsewhere |
| Settings page accepts numeric inputs as strings without bounds | Live-money incident from typo | Server-side validator with explicit caps; dry-run preview; audit log |
| Exposing audit-log endpoint without auth (common debugging shortcut) | History of operator actions leaked | Same `_verify_auth` dependency as every other endpoint |
| Dashboard writes raw form values into SQL | Partial existing risk already (though asyncpg parameterises) | Use only parameterised queries (current pattern in `db.py`); never f-string into SQL |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| "Save" button on settings with no confirmation of risk-percent impact | Operator changes risk to 50 meaning 0.5 | Preview lot size for a typical signal before save |
| Kill-switch button indistinguishable from close-position button | Panic-click opens close dialog instead of kill switch | Distinct color (red-500 w/ border), distinct location (sticky top of overview), confirmation modal (already in v1.0 — preserve) |
| Login form auto-focuses username even for a password manager fill | Power users hit friction | `autofocus` on username OK; ensure `autocomplete="current-password"` on password field so managers work |
| SSE stream silently dies without reconnect | Operator watches stale data | Client-side HTMX SSE `hx-on::error` → show reconnecting banner; auto-retry |
| New Basecoat/Tailwind design ships with no dark-mode preserving the v1.0 look | Operators trained on v1.0 colours lose muscle memory | Preserve the v1.0 dark colour semantics (green = good, red = bad) while updating layout |
| Settings change doesn't indicate "takes effect on next signal" | Operator assumes change applies to in-flight stages | Inline note next to each field; confirmation toast after save |

## "Looks Done But Isn't" Checklist

- [ ] **Staged entry:** stage-1 opens — verify stages 2+ also open (anti-Pitfall 2).
- [ ] **Staged entry:** stage fills on new signal — verify kill switch mid-stage drains the queue (anti-Pitfall 4).
- [ ] **Staged entry:** stage fills on reconnect — verify idempotency (no duplicates) (anti-Pitfall 5).
- [ ] **Text-only signal:** opens initial position — verify default SL is set and watchdog timer runs (anti-Pitfall 1).
- [ ] **Settings page:** saves to DB — verify audit row written, rollback works (anti-Pitfall 8).
- [ ] **Settings page:** changes apply — verify in-flight stages still use the snapshotted values (anti-Pitfall 7).
- [ ] **Tailwind build:** stylesheet produces — verify ALL classes from `*.py` sources are present in the built CSS, not just templates (anti-Pitfall 10).
- [ ] **HTMX swap:** partial renders — verify dropdowns/tabs inside the swapped partial still function (anti-Pitfall 11).
- [ ] **Deploy:** CSS updates — verify hashed filename and no stale-cache visible to operators (anti-Pitfall 12).
- [ ] **Login:** POST succeeds via HTMX — verify it also succeeds via plain form fallback (anti-Pitfall 13).
- [ ] **Login:** password hashes — verify `DASHBOARD_PASS` plaintext env var is removed post-migration (anti-Pitfall 15).
- [ ] **Login:** works — verify rate limiter + lockout engages at N failures (anti-Pitfall 16).
- [ ] **Daily limits:** count per-signal or per-fill — verify 5-stage signal doesn't exhaust `max_daily_trades_per_account` (anti-Pitfall 3).
- [ ] **Kill switch:** closes positions — verify `staged_entries.status='pending'` rows are also cancelled.
- [ ] **Reconnect:** restores connection — verify DB `staged_entries` is reconciled against MT5 positions by comment.
- [ ] **Schema:** new tables created — verify no `ALTER TABLE` on existing v1.0 tables (anti-Pitfall 17).
- [ ] **Orphan cap:** text-only opens — verify hard cap prevents unbounded stacking when follow-ups are silent.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Orphaned text-only position with no SL (P1) | MEDIUM | Dashboard "emergency apply default SL" button on open positions; per-position force-close |
| Stale `staged_entries.pending` rows after kill switch (P4) | LOW | Manual DB cleanup script; `UPDATE ... SET status='abandoned'`; next tick ignores them |
| Duplicate stage fill on reconnect (P5) | HIGH | Manual close of duplicate on MT5; DB trade log reconciliation; operator re-reads ledger |
| Daily-limit accounting bug (P3) | LOW | Reset `daily_stats.trades_count` for affected account; restore signal processing |
| Mid-stage settings mutation caused wrong lot sizes (P7) | MEDIUM | Close affected signal's remaining stages at market; accept size mismatch in filled stages |
| Invalid settings value bricked new signals (P8) | LOW | Rollback via audit log; restart executor if in-memory caches stale |
| Tailwind purge dropped critical classes (P10) | LOW | Revert deploy; add classes to safelist; rebuild |
| HTMX swap killed Basecoat bindings (P11) | LOW | Hotfix: add `htmx:afterSwap` init hook; redeploy CSS build trivially |
| Stale CSS cached post-deploy (P12) | LOW-MEDIUM | Announce in Discord "hard-reload dashboard"; next deploy hashes filename |
| Login CSRF rejected plain-form fallback (P13) | LOW | Disable `_verify_csrf` on `/login` temporarily; redeploy with double-submit |
| Session secret rotation logged everyone out (P14) | LOW | Operators re-login; in-flight HTMX actions redrive via page reload |
| Plaintext `DASHBOARD_PASS` still in env post-migration (P15) | LOW | Remove from env; restart; rotate the password itself as a precaution |
| Brute-force attempt succeeded (P16) | HIGH | Rotate password; rotate session secret; review audit log; inform user |
| Schema ALTER broke migration (P17) | HIGH | Rollback container; hand-run SQL to add/drop column; tighten pre-commit lint |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1. Text-only orphan with no SL | Phase 1 | Integration test: text-only signal → position opens with non-zero SL; watchdog fires after timeout |
| 2. Duplicate-direction guard blocks staged | Phase 1 | Integration test: 3-stage signal → 3 positions open |
| 3. Daily/per-symbol limits starve stages | Phase 1 | Integration test: 5-stage signal consumes 1 daily-count slot (Option A) |
| 4. Kill switch leaves pending stages | Phase 1 | Integration test: mid-stage kill → all `staged_entries` → cancelled; no post-resume fills |
| 5. Reconnect duplicates/orphans stages | Phase 1 | Integration test: disconnect mid-fill → on reconnect, no duplicate; orphans alerted |
| 6. Zone watcher cadence too slow | Phase 1 | Latency metric: `fill_price − trigger_price` < tolerance band 95% of time |
| 7. Settings mutation mid-stage | Phase 1 (snapshot mechanism) + Phase 2 (UI enforces the rule) | Test: edit settings after stage 1 fills → stage 2 uses original values |
| 8. Invalid settings values | Phase 2 | Test: POST `risk_percent=50` → 422 rejected; preview page blocks save |
| 9. JSON vs DB authority confusion | Phase 2 | Startup log shows effective-value per field; `/settings` shows origin |
| 10. Tailwind purge strips `.py` classes | Phase 3 | CI check: critical class names present in built CSS |
| 11. HTMX swap kills Basecoat bindings | Phase 3 | Manual test: dropdown inside partial still works after SSE refresh |
| 12. Stale CSS cached post-deploy | Phase 3 | Deploy checklist: hashed filename, market-closed window |
| 13. Login CSRF blocks plain-form fallback | Phase 4 | Test: login via HTMX ✓ and via plain form ✓; missing token → 403 |
| 14. Session secret rotation logs out all | Phase 4 | Runbook documented; grace-window support flagged for v1.2 |
| 15. `DASHBOARD_PASS` plaintext lingers | Phase 4 | Startup refuses to boot with both env vars set post-migration |
| 16. No rate limit → brute force | Phase 4 | nginx `limit_req` + app-level lockout; log shows lockout on N failures |
| 17. ALTER TABLE without alembic | Phase 1 | Pre-commit lint blocks; additive-only rule in PLAN |
| 18. SSE vs kill-switch state race | Phase 3 | Kill-switch click → UI flips optimistic state < 200ms; no double notification |

## Sources

- `/Users/murx/Developer/personal/telebot/executor.py` — kill switch, reconnect, heartbeat (lines 81–271)
- `/Users/murx/Developer/personal/telebot/trade_manager.py` — signal flow, daily limits, max-open-trades guard (lines 127–345)
- `/Users/murx/Developer/personal/telebot/dashboard.py` — CSRF, auth, inline HTML classes, SSE (lines 33–396)
- `/Users/murx/Developer/personal/telebot/.planning/research/STACK.md` — v1.1 tech decisions (Basecoat, Tailwind v3 standalone, argon2-cffi, SessionMiddleware)
- `/Users/murx/Developer/personal/telebot/.planning/milestones/v1.0-REQUIREMENTS.md` — REL-01..04, EXEC-01..04, SEC-01..04, DBE-01 deferral
- `/Users/murx/Developer/personal/telebot/.planning/PROJECT.md` — safety bar, constraints (real money, minimise deps, no breaking config changes)
- Tailwind v3 standalone CLI docs (content-glob behaviour and purge semantics)
- Basecoat v0.3.3 install docs (JS component behaviour, re-init story)
- argon2-cffi 25.1.0 docs (verify/check_needs_rehash API, default params)
- Starlette SessionMiddleware docs (cookie signing, secret rotation semantics)

---
*Pitfalls research for: Telebot v1.1 (staged entry + runtime settings + UI redesign + login)*
*Researched: 2026-04-18*
