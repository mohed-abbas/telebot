# Feature Research — Telebot v1.1

**Domain:** Automated MT5 trading bot (Telegram signal execution) + single-admin ops dashboard
**Researched:** 2026-04-18
**Confidence:** HIGH on staged-entry mechanics (derived from existing `trade_manager.py` + standard signal-copier patterns), HIGH on admin-dashboard / auth / settings-page patterns (well-established UI conventions), MEDIUM on broader "what pro signal copiers do" (drawn from Telethon copier projects and MT5 EA conventions; not a consumer product category with public benchmarks).

---

## How to read this file

The orchestrator-defined quality gate requires categorization by **the 4 target areas**, not a single global table-stakes list. So the file is **four nested feature landscapes** — one per target area. Each area has its own Table Stakes / Differentiators / Anti-Features breakdown, its own dependencies on existing v1.0 behavior, and its own complexity rating.

Target areas:

1. **Staged-Entry Execution** — the core new trading capability
2. **Per-Account Settings Page** — runtime-editable per-account tunables
3. **Dashboard Redesign** — shadcn/Basecoat + Tailwind + mobile-responsive rewrite of `templates/`
4. **Proper Login Form** — styled HTML login replacing `HTTPBasic` prompt

A cross-area MVP prioritization and feature-dependency graph sit at the bottom.

---

## 1. Staged-Entry Execution

**Complexity:** HIGH
**Why HIGH:** New async loop (`_zone_watch_loop`) in `executor.py`, two new DB tables (`account_settings`, `staged_entries`), non-trivial interaction surface with the kill switch, reconnect/sync path, daily limits, and stale-signal check. The feature is architecturally simple but *operationally* rich — every v1.0 safety check has to extend into the stage-fill path, or we reintroduce a regression class v1.0 already closed.

### Mental model

The v1.0 executor makes **one** trade decision per signal: market-fill if price is in the zone at the moment of receipt, otherwise a single `buy_limit`/`sell_limit` at the zone midpoint, or skip if stale. v1.1 splits a single signal into **N stages**:

- **Stage 0 (immediate):** if the signal is a text-only "Gold buy now" (no zone, no SL, no TP), open 1 position at market using the account's risk_mode to size it, with no SL/TP yet attached. This is the "don't miss the move" stage.
- **Stages 1..N (pending):** when the follow-up signal arrives with the full zone+SL+TP, queue up to `max_stages - 1` additional stages, each gated on a **price-in-zone event**. A zone watcher loop monitors the live price and fires the stage when the condition is met.
- **Correlation:** the immediate text-only signal and the follow-up detailed signal need to be tied to the same trade idea. Matching by (symbol, direction, most-recent-within-N-minutes) is the standard approach; the zero-width-zone placeholder from a text-only signal (`entry_zone = (price, price)`, seen in `signal_parser._build_open_signal` for the single-price fallback) can be promoted to a full zone when the follow-up arrives.

### Table Stakes (what the user already expects to work)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Immediate market fill for text-only "Gold buy now" | The user's explicit v1.1 ask — today these signals are dropped because no SL/TP is present | MEDIUM | Signal parser already has `_RE_OPEN_SINGLE` for "Gold buy 2150"; needs a new `_RE_OPEN_NOW` branch that accepts no price at all. `SignalAction.sl` becomes optional; `trade_manager._handle_open` must allow SL-less opens for stage 0 only |
| Follow-up signal promotes text-only stage 0 into a full signal | Standard behavior in Telegram signal groups: analyst posts "Gold buy now" then posts the zone/SL/TP 30s–5min later | HIGH | Requires a short correlation window (configurable, e.g. 10 min) and a `signals.parent_signal_id` / `staged_entries.parent_ticket` linkage. When the detailed signal arrives, attach its SL/TP to stage 0's open position via `modify_position` |
| Per-signal configurable max positions (e.g. 1 initial + 4 fills = 5) | User's explicit v1.1 ask | LOW-MEDIUM | Per-account `max_stages` (replaces/augments `max_open_trades` semantically: `max_open_trades` remains a hard ceiling across all sources; `max_stages` is the cap for a single signal's fan-out) |
| Percentage-of-equity OR fixed-lot risk mode | User's explicit v1.1 ask | LOW | `risk_calculator.calculate_lot_size` gains a `risk_mode` branch; "fixed" mode returns `min(fixed_lot, max_lot_size)` without the SL-distance math. When `risk_mode == "fixed"` and no SL is known (stage 0), this is the only viable sizing |
| Stage-level lot allocation | Users expect 20%/20%/20%/20%/20% or similar weighting rather than "5 full-size positions" | MEDIUM | `stage_allocation: list[float]` per account (default `[1.0]` for non-staged legacy behavior, `[0.2, 0.2, 0.2, 0.2, 0.2]` for 5-stage equal). Each stage uses its slice of the overall risk budget or fixed-lot allocation |
| Pending stages visible on the dashboard | If the user can't see "2 of 5 stages filled, 3 pending at zone 4978–4982," the feature is invisible | MEDIUM | New `partials/staged_entries_table.html`; HTMX-refreshed |
| Stage cancellation when kill switch fires | Hard-locked expectation for live-money bots: emergency stop means everything, including queued intent | LOW | `executor.emergency_close()` already cancels pending MT5 orders; add "mark all `staged_entries` WHERE status='pending' AS cancelled" in the same transaction |
| Stage cancellation when daily limit reached mid-fan-out | If stage 3 of 5 would breach `max_daily_trades_per_account`, skip stage 3 onward rather than partial-fill and leave a phantom | LOW | `trade_manager._execute_open_on_account`'s existing daily-limit check runs per stage automatically if each stage fill re-enters that code path; must mark remaining stages `skipped_daily_limit` explicitly for audit |
| Per-stage stale re-check (EXEC-02 behavior preserved) | v1.0 requires the second stale check immediately before `open_order`; staged entry has N open_orders, each needs it | LOW | `_check_stale` runs per stage fill. If fill-time stale is detected (price already past TP1), the stage is dropped (status `stale`) and the remaining pending stages also dropped (a stale signal does not become unstale) |
| Stage cancellation when initial position hits SL | If stage 0 stops out before the fill-zone stages trigger, the analyst's thesis is broken; don't keep filling into a losing idea | MEDIUM | When a position tied to `signal_id` closes at loss (SL hit), mark all `staged_entries` for that `signal_id` WHERE status='pending' AS cancelled. Requires position-close → signal-id reverse lookup, already available via `trades.signal_id` |
| Reconnect reconciliation for pending stages | After MT5 reconnect (v1.0 REL-02 path), pending stages for accounts that were offline must either resume monitoring or be cancelled — they cannot be silently abandoned | HIGH | Extend `_sync_positions` to also reload `staged_entries WHERE account=? AND status='pending'`; if the referenced parent ticket no longer exists on MT5, drop the pending stages (status `orphaned`) |
| Audit trail per stage | Users need to reconstruct "why did we open 5 positions?" for post-mortems, broker disputes, and tuning | LOW | Each stage insert includes `parent_signal_id`, `stage_number`, `trigger_event` (immediate / price-in-zone / manual-fill), `fired_at`, `fill_ticket`. All stages log through existing `log_signal` / `log_trade` patterns |

### Differentiators (nice-to-have, genuine upside)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Adaptive zone reshape on update signals | If the analyst posts "New zone: 4975–4979," move unfilled pending stages to the new zone rather than holding stale ones | MEDIUM | Parser already recognizes `_RE_SL_UPDATE`; a companion `_RE_ZONE_UPDATE` plus updating `staged_entries.target_zone_low/high` closes the loop |
| Trailing activation of later stages | Stage 3 only becomes "armed" once stage 2 has filled — avoids filling stage 3 on a fast spike-through that misses stage 2 | MEDIUM | Prefix-ordering constraint on the zone watcher; each stage has a `requires_stage: int\|null` |
| Per-stage SL/TP jitter independence | Each stage gets its own jittered SL/TP using the existing `calculate_sl_with_jitter` / `calculate_tp_with_jitter` — makes execution footprint less robotic across stages | LOW | Reuse existing jitter functions per stage; already matches v1.0 humanization philosophy |
| Stage dry-run preview in dashboard | Before live rollout, show "if this signal had come in, we would have opened at ..." for the last N parsed signals | MEDIUM | Uses `DryRunConnector` path; ops confidence boost only — defer if time-constrained |
| Per-account stage enable toggle | An account on a risk-averse profile can have `max_stages = 1` (legacy behavior) while another runs full staged entry | LOW | Falls out of the per-account settings table for free |

### Anti-Features (commonly conflated, explicitly NOT building)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Martingale / averaging-down on losing positions** | Superficially looks like staged entry — "open more as price goes against us" | This is not what staged entry is. Staged entry fills **pre-declared** zones from a **single signal**. Averaging down on losses is how accounts blow up. This must be called out to the requirement writer so no one slips it in as a "logical extension" | Staged entry fills the zone *the analyst posted*. If price leaves the zone without filling remaining stages, the stages expire — they do NOT chase |
| **Grid trading / auto-ladder independent of signal** | "Let the bot ladder in every N pips regardless of signal" | Defeats the signal-copier's purpose; introduces infinite-loss tail risk; has nothing to do with Telegram signals | Strict 1:1 between analyst signals and stages. No bot-initiated ladders |
| **Dynamic max_stages based on confidence/score** | Analyst confidence scoring from signal text | High complexity (NLP / ML), low reliability, user explicitly scoped this as config-per-account, not dynamic | `max_stages` is a per-account flat config value. Period |
| **Auto-increase risk after winning streak** | "Let it run when hot" | Classic gambler's-fallacy trap; incompatible with "real money, safety first" posture | Fixed risk per trade regardless of recent outcome. User can adjust `risk_percent` manually in the settings page if they want |
| **Partial fills via reducing lot under insufficient margin** | Broker rejected stage 3 due to margin — try again at 0.5× | Silent behavior divergence from the signal; audit nightmare | If a stage's `open_order` fails, mark it `failed_margin`, surface in dashboard, do NOT retry at reduced lot |
| **Cross-signal stage merging** | "This new 'Gold buy' signal is similar to the last one, fold it into the open staged set" | Opacity; correlation errors will entangle unrelated trade ideas | Each signal owns its own `signal_id` and its own stage set. They never merge. Dedup is the existing "already have a {direction} position open" check |
| **Retry pending stages across bot restarts without reconciliation** | "Persist stages forever, fire whenever price re-enters" | A bot restart might be hours or days later; market state is unrelated; phantom fills on old ideas | On bot start, load pending stages but run each through `_check_stale` using the *current* price and the signal's *original* TP1 — stages that are no longer valid get cancelled, not re-armed |

### Dependencies on existing v1.0 capabilities (mechanical hooks — be specific)

| v1.0 mechanism | How staged entry consumes it | Failure mode if skipped |
|----------------|------------------------------|-------------------------|
| `Executor._trading_paused` (kill switch flag, `executor.py:34`) | Zone-watcher loop must check this flag **before every stage fill**, not just at signal receipt. `emergency_close` must also flip all pending `staged_entries` to `cancelled` | Kill switch fires, user thinks all exposure is gone; zone watcher fires 10s later and opens a new position. Safety regression |
| `Executor._reconnecting` set (`executor.py:35`) | Before firing a stage on account X, check `acct_name not in self._reconnecting`. Reuse existing `is_accepting_signals()` as the gate | Stage fires while connector is mid-reconnect → `open_order` fails or double-submits |
| `Executor._sync_positions` after reconnect (REL-02) | Must be extended to also reconcile `staged_entries`: if parent ticket not on MT5, orphan the stages | Phantom stage fills against a position that no longer exists |
| `TradeManager._check_stale` + `EXEC-02` re-check | Runs per stage fill immediately before `open_order` (same pattern as `_execute_open_on_account` lines 246–255) | Stage fires after price has already blown through TP1 — trade instantly at loss |
| `self.cfg.max_daily_trades_per_account` + `db.get_daily_stat` | Checked per stage fill in the existing code path (trade_manager.py:168–172). Each stage fill counts as 1 toward the daily limit | Staged entry silently bypasses the daily cap; `EXEC-04` dashboard warnings become inaccurate |
| `acct.max_open_trades` check (trade_manager.py:181–184) | Must count **filled + pending** stages against this ceiling, not just open MT5 positions, or the ceiling gets blown during a slow fan-out | Position count overshoot; margin pressure |
| `determine_order_type` zone logic (trade_manager.py:47–68, EXEC-01) | Each stage's fill decision uses identical market-vs-limit logic. Can stay as pure function; zone watcher calls it per stage | Divergent execution between legacy single-stage and staged paths |
| Duplicate-direction check (trade_manager.py:187–190) | Must be **disabled** for follow-up stages of the same signal — otherwise stage 1 blocks stages 2–N. Must still fire for a *different* signal attempting the same direction | Stages 2–N silently skipped — feature non-functional |
| SL/TP direction validation (`validate_sl_for_direction`, EXEC-03) | Runs per stage at the point the detailed signal's SL is applied (to stage 0 via `modify_position`, and at open for stages 1..N) | SL applied in wrong direction |
| `DryRunConnector` price feed | Zone watcher uses `connector.get_price` for both live and dry-run; dry-run's `set_simulated_price` path already exercised in `_execute_open_on_account` | Dry-run fidelity loss |
| `notifier.notify_execution` | Called per stage, not per signal. Discord gets "Stage 2/5 filled at 4980.50" | Silent fills; user can't tell what happened |

### Design outputs needed before requirement phase

- Decision: text-only → follow-up correlation window duration (suggest **10 minutes**, configurable global)
- Decision: default `stage_allocation` when user configures `max_stages: 5` but doesn't specify allocation (suggest **equal split**)
- Decision: how the dashboard surfaces stages (column in positions? separate "Pending stages" panel? — suggest **separate panel on Overview**)

---

## 2. Per-Account Settings Page

**Complexity:** MEDIUM
**Why MEDIUM:** Single new DB table, 4–6 CRUD endpoints in the same style as `modify_sl` / `modify_tp` / `close_partial` in `dashboard.py:224–299`, one new Jinja template, small number of HTMX forms. The complexity is in the guardrails (bounds-checking, audit trail, dangerous-change confirmation), not the plumbing.

### Mental model

Today, `accounts.json` is the sole source of per-account tunables (`risk_percent`, `max_lot_size`, `max_open_trades`, `enabled`). v1.1 keeps that file as the **bootstrap/seed** layer and adds a DB table `account_settings` that overrides it at runtime. UI edits write to DB; the `TradeManager` reads from DB (falling back to `accounts.json` values if no override exists). Bot restart does not lose settings — DB wins.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Edit risk_mode (percent vs fixed) per account | User's explicit v1.1 ask — paired with the staged-entry risk_mode feature | LOW | Radio button / select; persists to `account_settings.risk_mode` |
| Edit risk_percent (when mode=percent) | Already in `accounts.json`, needs UI | LOW | Numeric input with server-side clamp `0.1 ≤ x ≤ 3.0` (hard ceiling — see anti-features) |
| Edit fixed_lot (when mode=fixed) | User's explicit v1.1 ask | LOW | Numeric input with server-side clamp `0.01 ≤ x ≤ min(2.0, max_lot_size)` |
| Edit max_open_trades | Already in `accounts.json` as `max_open_trades`, needs UI | LOW | Integer input, clamp `1 ≤ x ≤ 10` |
| Edit max_stages (new, from staged entry) | Required for staged entry to be user-tunable | LOW | Integer input, clamp `1 ≤ x ≤ 5`. `1` = legacy one-shot behavior |
| Edit max_daily_trades_per_account | Currently global (`GlobalConfig.max_daily_trades_per_account`); users want per-account override | LOW | Integer input, clamp `1 ≤ x ≤ 100`. DB override takes precedence over global config at check time |
| Enable / disable account toggle | `enabled` already exists in `accounts.json`, but toggling requires container restart today | LOW | Same pattern; executor re-reads `enabled` on every signal anyway via `self.accounts.get(acct_name)` — make sure the in-memory cache is invalidated on write |
| Hard server-side bounds on every field | Real money; can't rely on client-side validation | LOW | FastAPI Pydantic validators; reject with 400 + reason (HTMX error panel) |
| Audit log of every change | Real money; needs "who changed what when" for post-mortems even with a single admin | LOW | Append-only `settings_audit` table: `(timestamp, account, field, old_value, new_value, actor)`. Actor is always "admin" for now but field is there for future |
| Confirmation step on dangerous changes | Matches v1.0's two-step kill-switch pattern (REL-03 confirmation philosophy) | LOW | Dangerous = raising risk_percent > 1.5%, raising max_stages beyond prior value, raising max_lot_size. Two-click "are you sure?" like kill switch |
| Changes take effect on next signal, not retroactively | User expectation — don't resize my open positions when I bump risk % | LOW | By construction: the settings are read at trade-open time. In-flight positions are untouched. Document this in the UI: "Changes apply to new trades only." |
| Read-only view of non-editable fields | User wants to see server, login, password_env (without the secret) as context | LOW | Rendered but disabled inputs; security rationale in a help tooltip |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| "Recent changes" mini-timeline on the settings page | Ops confidence — see at a glance "risk_percent on demo-1 was 2.0% → 1.5% 10 minutes ago" | LOW | Reuses `settings_audit` table, last 20 entries, per account |
| Bulk-apply to multiple accounts | When the user has 4 accounts and wants to set `risk_mode=fixed` on all of them, one checkbox beats 4 forms | MEDIUM | "Apply this change to: [] demo-1 [] demo-2 [] live-1 [] live-2"; still respects per-account bounds and still generates 1 audit entry per account |
| Diff-from-seed view | "Which fields on this account differ from `accounts.json`?" — useful when troubleshooting "is the runtime config what I set?" | LOW | Computed on render: iterate seed vs override, highlight deltas |
| Copy settings from account X to account Y | Reduces manual error when provisioning a new account | LOW | Dropdown "Copy from..." → confirm → audit |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Editing server / login / password_env from the UI** | "It's another account field, why not?" | Credentials and broker endpoints belong in env / seed config, not in an ops UI. Any leak of login or server-pattern from DB is bad. `password_env` is an indirection — the secret itself is in env — but editing it at runtime invites pointing at the wrong env var silently | Stays in `accounts.json` / env. Read-only in UI. Change requires container restart (audit event: container restart timestamp already logged) |
| **Removing the hard server-side bounds to "let the user do what they want"** | Power user requests | One typo at 3 AM (typing `30` instead of `3.0` into risk_percent) blows an account. Bounds are non-negotiable | Hard-coded ceilings in the Pydantic validator. If the user genuinely needs 5% risk, they edit `config.py` and container-restart — treating that as a friction-by-design rather than a bug |
| **Retroactive resize of open positions on risk change** | "I changed my mind — apply new risk to current trades too" | Violates the "changes don't modify open positions" expectation; opens the door to "oops, I halved all my open SLs" | Settings apply to new trades only. To modify an open position, use the existing modify_sl / modify_tp / close_partial UI |
| **Live broker-credential test ("Test connection" button that takes a new password inline)** | Onboarding shortcut | Reintroduces plaintext password in an HTTP request body — defeats SEC-04; adds a new attack surface | Credentials stay env-side; the existing heartbeat loop surfaces connection status |
| **Custom per-account signal source routing / filter rules** | "Only apply Telegram group X to account Y" | Out of scope for v1.1. Every account currently gets every signal. Routing logic multiplies the testable combinations | Future milestone. Document as out-of-scope |
| **Importing / exporting settings as JSON in the UI** | "Back up my config" | The DB is already the backup; `accounts.json` is the seed; duplicate export path creates drift and secret-leakage risk | `pg_dump` is the backup story; document in ops notes |
| **Free-text comments per account** | "Let me annotate why I set risk=2% on this one" | Scope creep; unbounded text in an ops UI grows until it becomes a liability | Defer; if truly needed, add a single `notes: str` field with a length cap as a differentiator, not MVP |

### Dependencies on v1.0

- **Existing `_verify_csrf` HTMX-header CSRF pattern in `dashboard.py`** — every POST to `/api/settings/{account}` uses the same guard. Identical to how `modify_sl` is already guarded
- **`SEC-03` env-validation discipline extends to settings-page startup** — fail fast if DB schema version mismatches (once DBE-01 lands), or if migration of `account_settings` fails
- **Notifier (`notifier.py`)** — dangerous settings changes (risk raised, trades-per-day raised) emit a Discord alert so the user gets a record out-of-band
- **Existing `AccountConfig` dataclass (`models.py`)** — gains a method `effective()` that merges seed + DB override; the rest of the code reads `acct.effective().risk_percent` instead of `acct.risk_percent`. Minimal call-site churn
- **`db.py` init** — adds a hand-written `CREATE TABLE IF NOT EXISTS account_settings` (matches v1.0 pattern since DBE-01/alembic is deferred per STACK.md)

---

## 3. Dashboard Redesign

**Complexity:** HIGH
**Why HIGH:** Every template in `templates/` touches (8 files: `base.html`, `overview.html`, `positions.html`, `history.html`, `signals.html`, `analytics.html`, `settings.html`, `partials/*`). Tailwind build pipeline added to the Dockerfile (STACK.md §2). Basecoat CSS/JS vendored into `static/`. Every HTMX partial updated to the new component language. The **functional** change is small; the **surface** change is the whole dashboard.

### Mental model

STACK.md has already decided the substrate (Basecoat on HTMX + Jinja, Tailwind v3.4 standalone CLI, no SPA). This section is about **what the dashboard should do**, not what it's built with. Redesign = visual parity with shadcn/ui aesthetics **plus** the richer information density the user asked for ("richer positions/trades drilldowns; analytics upgrades") **plus** mobile responsiveness, which `templates/base.html:42–44` currently doesn't support (fixed 224px sidebar, `ml-56` main content — breaks below ~700px).

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Mobile-responsive layout (breakpoints: sm/md/lg) | User's explicit v1.1 ask; fixed sidebar currently breaks on phones | MEDIUM | Sidebar collapses to a hamburger / Basecoat Sidebar component under `md`; main content becomes full-width. Tables become card lists under `sm` (see "responsive tables" below) |
| Responsive tables → cards below `sm` | Standard pattern for admin dashboards; tables don't work on phones | MEDIUM | Each row renders as a Basecoat Card with label/value pairs below ~640px. Reuse across positions, history, signals, analytics |
| All v1.0 dashboard functionality preserved | Zero regression: kill switch (REL-03), daily limit colors (EXEC-04), TRADING PAUSED banner, modify SL/TP, partial close, analytics (ANLYT-01) | MEDIUM | Bit-for-bit parity on the interactive surface; only the visual layer changes. Every existing HTMX endpoint keeps its contract |
| shadcn-style design tokens via Basecoat CSS variables | User's explicit v1.1 ask; removes the `<style>` block in `base.html:21–40` and replaces with token usage | LOW | Colors, spacing, radii come from Basecoat. Dark mode (already `class="dark"`) is first-class |
| Positions table drilldown: click to expand row | User asked for "richer positions/trades drilldowns" | MEDIUM | Row-click opens a Basecoat Dialog or inline accordion showing: full signal raw text, signal timestamps, all TPs, stage info (once staged entry ships), current unrealized P&L breakdown, account context |
| Trade history drilldown | Same pattern as positions drilldown | MEDIUM | Inline row expansion showing the full signal chain that led to the trade + any modifications (SL updates, partial closes) |
| Analytics drilldown: per-source / per-symbol breakdowns | User asked for "analytics upgrades" | MEDIUM | Current analytics page shows global win-rate and profit-factor. Extend with: win-rate grouped by (source_group, symbol); top 5 best and worst sources; rolling 7-day/30-day performance |
| Pending stages visible in UI | Staged entry depends on this (§1) | MEDIUM | New partial in Overview: "Pending stages" panel below "Open positions" |
| Per-account drilldown on Overview cards | Today each account card shows balance/equity; user wants click-through to that account's recent trades | LOW | Click the card → navigate to `/positions?account=X` and `/history?account=X` (existing pages with a new filter query param) |
| Loading / empty / error states that match the aesthetic | shadcn has well-known patterns; the v1.0 dashboard uses ad-hoc "No accounts configured" centered text | LOW | Basecoat Alert component + skeleton rows during HTMX loading |
| Keyboard accessibility + ARIA on all interactive elements | Baseline accessibility; Basecoat already handles most of this | LOW | Verify dialog / dropdown / tabs with keyboard only |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Command palette (`Cmd/Ctrl+K`) | Power-user navigation: "jump to settings," "close all positions for X," "show last signal" | MEDIUM | Basecoat has a Command / Combobox component. Ops productivity boost |
| Toast notifications for HTMX action results | Right now, modify SL success is invisible unless user sees the row refresh. Toast = immediate feedback | LOW | Basecoat Toast + `HX-Trigger` response header from the server emits a named event the toast subscribes to |
| Dark/light toggle | Current dashboard is dark-only; a daylight-hours light variant is small | LOW | Basecoat tokens flip based on `class="dark"` vs `class=""` on `<html>`; toggle persists via `localStorage` |
| Sidebar collapse on desktop | Power-user preference for max content area | LOW | Basecoat Sidebar supports collapsed variant |
| Per-account color tag in tables | User runs 2–4 accounts; visual disambiguation in the combined positions table | LOW | Account color stored in `account_settings.color` (from §2); applied as a left-border on rows |
| Sticky header + scroll-preserving HTMX swaps | Long tables on analytics / history; user scrolls and a 3s refresh yanks them back to top | LOW | `hx-swap="innerHTML scroll:preserve"` + sticky table header |
| Live-updating P&L sparkline per account | Overview card becomes glanceable at a distance | MEDIUM | CSS-only sparkline from the last N equity samples; no chart library |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **SPA rewrite to React/Vue/Nuxt** | shadcn's native home is React | STACK.md §1 already rejected this (new build toolchain, new container, weeks of integration, CORS/auth, unnecessary for a read-heavy admin UI). Mentioned here so the requirement writer doesn't re-open the debate | Basecoat CSS + HTMX; stay on the existing substrate |
| **WebSocket live-update streams** | "Real-time position updates without 3s polling" | Adds a long-lived connection per client, new state on the server, subject to the same single-admin scope — 3s HTMX polling is adequate and battle-tested in v1.0 | HTMX polling stays. Only promote to SSE/WebSocket if a specific pain point emerges |
| **Candlestick / OHLC charts on positions or analytics** | "Can I see the price action around my entries?" | Major chart library (lightweight-charts, chart.js) adds build complexity, bundle size, and a whole category of bugs; we'd need price-bar data we don't currently have; browser-side charting for a multi-user ops dashboard is a solved problem done by other tools (TradingView) | Keep tables. Link out to the user's preferred chart tool via URL template if desired |
| **Public / shareable dashboard links** | "Let me share my bot's performance with friends" | Multi-user auth surface we're deliberately not building (§4 is single-admin); exposes PII (balances, trade history) | Out of scope. User runs their own bot instance |
| **Rich-text notes per trade / position** | "Let me annotate trades" | Same reasoning as settings-page "free-text comments" anti-feature — scope creep | Defer. Small single-line `notes` field if truly demanded, not an editor |
| **Drag-and-drop dashboard customization (reorder widgets)** | "I want overview cards in my order" | High UX cost; no payoff for single-admin; introduces localStorage state that desyncs across browsers | Fixed layout. If a future user base demands this, revisit |
| **Theming beyond light/dark** | "Custom color palettes" | shadcn tokens define a canonical set; fighting them costs a lot for cosmetic gain | Light/dark only |
| **Notifications badge in the sidebar for Discord alerts** | "Show me what the alerts webhook sent" | Duplicates Discord's job; requires storing-and-rendering a duplicate notification channel | Discord webhook stays the source of truth; link to the channel from a small icon in the header |
| **Embedded TradingView widget on overview** | "See the chart next to my positions" | Third-party script in the dashboard's security context; defeats the "minimize surface" discipline; makes the auth guard look porous | Out of scope |

### Dependencies on v1.0

- **Every existing dashboard endpoint in `dashboard.py`** — URLs and response shapes stay stable; only the templates change. This keeps the HTMX round-trip contract intact
- **`_verify_csrf` HTMX header check** — unchanged; all forms must continue to submit via `hx-post` so the `HX-Request` header is present
- **`SEC-02` `DASHBOARD_PASS` enforcement** — no change (and §4 layers the login form on top)
- **Tailwind build pipeline addition per STACK.md §2** — Dockerfile gains a build stage downloading the standalone CLI; `static/css/app.css` becomes a build artifact; the old `<script src="https://cdn.tailwindcss.com">` in `base.html:7` is removed as part of this milestone's first phase
- **Basecoat CSS + JS vendored into `static/`** — per STACK.md §1, pinned to v0.3.3; not hot-loaded from jsDelivr
- **`templates/base.html:7` current Play-CDN Tailwind is a production blocker** — this redesign is the moment to remove it. Documented in STACK.md §2

### Design outputs needed before requirement phase

- Decision: mobile sidebar pattern (hamburger slide-over vs bottom nav) — suggest **slide-over hamburger** for parity with shadcn
- Decision: drilldown pattern (Dialog modal vs inline accordion) — suggest **inline accordion** for positions/history (preserves table context) and **Dialog** for analytics grouped views
- Decision: sparkline in/out of MVP — suggest **out of MVP**, differentiator

---

## 4. Proper Login Form

**Complexity:** MEDIUM
**Why MEDIUM:** One new middleware, two new env vars (`SESSION_SECRET`, `DASHBOARD_PASS_HASH`), one new template (`login.html`), a password-migration path from plaintext `DASHBOARD_PASS` to the hashed form. Small new surface; every bit has to be right because it's the front door to an app that manages real money.

### Mental model

STACK.md has decided the stack (Starlette SessionMiddleware + argon2-cffi; no fastapi-users, no JWT). This section is about **what the login UX should be**, not how it's built. The v1.0 basic-auth prompt works but (a) can't be themed with the dashboard, (b) can't log out cleanly, (c) re-prompts every browser restart, (d) exposes credentials in every request's `Authorization` header. v1.1 replaces it with a form → cookie model.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Styled `/login` page using the Basecoat form/card components | User's explicit v1.1 ask | LOW | Username field can be fixed to `admin` (single-admin model) or hidden entirely and only accept password. Suggest **password only**, matches `DASHBOARD_PASS` semantics |
| Login form uses the dashboard's design tokens | Part of "styled UX replacing basic-auth prompt" | LOW | Trivially satisfied once §3 is in place |
| Successful login sets a signed session cookie | Per STACK.md §3 | LOW | `SessionMiddleware` with `https_only=True`, `same_site="lax"`, `max_age=28800` (8h) |
| "Remember me" checkbox extends `max_age` to 30 days | Admin-dashboard convention; single user, own machine | LOW | Two cookie-max-age options; the 30-day option must be an explicit opt-in, default is the 8h session |
| Failed login rate-limiting | Without it, any attacker can brute-force the password to exhaustion | MEDIUM | In-memory per-IP counter: after 5 failures in 5 minutes, reject subsequent attempts for 15 minutes with a generic error. Use `slowapi` only if an existing rate-limit library is already in the stack; otherwise a 20-line in-process implementation suffices. **Confirmation needed: no rate-limit lib currently in requirements.txt.** |
| Generic error message on failed login | "Invalid credentials" — never "wrong password" vs "unknown user"; avoids account enumeration | LOW | Single error string regardless of failure reason |
| Logout button that clears the session | Opposite of "can't log out" complaint with basic-auth | LOW | `/logout` endpoint clears the session and redirects to `/login`. Visible in the sidebar footer |
| Password hashed at rest using argon2 | Per STACK.md §3; Passlib is unmaintained | LOW | `argon2.PasswordHasher`. One-shot script `scripts/hash_password.py` to produce the `DASHBOARD_PASS_HASH` env value |
| Backwards-compat: auto-upgrade plaintext `DASHBOARD_PASS` on first successful login | User's existing env var still works during the migration window | LOW | If `DASHBOARD_PASS_HASH` is unset but `DASHBOARD_PASS` matches the submitted password, hash it on the fly, log a one-time warning "rotate DASHBOARD_PASS to DASHBOARD_PASS_HASH and unset the plaintext," accept the login. Remove this branch in v1.2 |
| CSRF protection on `/login` POST | Same standard as every other state-changing endpoint | LOW | `_verify_csrf` already checks `HX-Request` header; login form uses `hx-post="/login"` so the header is naturally present |
| Session-expiry redirect to `/login?next=<path>` | User was 20 minutes into analytics, cookie expired, next click sends them to login, and a successful login returns them to where they were | LOW | Existing `_require_auth` dependency returns a redirect with `next=` encoded |
| Startup failure if `SESSION_SECRET` is unset or < 32 bytes | Matches SEC-02 pattern (fail fast on missing required secret) | LOW | Pydantic validator in `config.py`; 32-byte minimum |
| Clear error UI for lockout | User at attempt 6 needs to know why it's not working and when to retry | LOW | "Too many attempts. Try again in 13m 42s." with a countdown |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Last-login timestamp displayed post-auth | "You last logged in from 1.2.3.4 on 2026-04-17 22:14" — quick tripwire for unauthorized access | LOW | One row `session_log(timestamp, ip, user_agent, outcome)` per login attempt; overview sidebar shows last successful |
| Session list with individual revocation | "These 2 browsers are signed in; revoke this one" | MEDIUM | Server-side session store keyed by session id; revoke = delete row. Overkill for single-admin unless the user explicitly wants it. Suggest **defer to v1.2** |
| Passkey / WebAuthn option | Strictly stronger than a password; supported in every modern browser | HIGH | Significant library add (`webauthn` package); excellent security upgrade but scope-creep for v1.1. Suggest **v1.2 or later** |
| Remember-device as an alternative to "remember me" cookie TTL | Device fingerprint → 30-day trust | MEDIUM | Defer — redundant with remember-me for single-admin |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **User registration / signup flow** | "What if I add another admin?" | v1.1 is explicitly single-admin. Registration requires email, verification flow, duplicate-handling — all out of scope | Out of scope. If a second admin is ever needed, it's an env-var provisioning step |
| **Password reset / "forgot password" flow** | Standard web app pattern | Requires email delivery infra, tokens, reset templates. For single-admin with env-var provisioning, the reset path is "SSH into the VPS, run the hash-password script, update env, restart container" | Documented ops procedure. No in-app reset |
| **2FA / TOTP** | Stronger security | Meaningful library add; TOTP apps, QR-code rendering, backup codes, recovery flow. Passkey (differentiator, deferred) is the modern alternative if the user wants a second factor | Defer. Strong password + rate limit + short session + HTTPS is adequate for single-admin in v1.1 |
| **JWT / bearer tokens** | "Stateless auth" | Per STACK.md §3: session cookies are simpler and safer for this use case (server-side secret, no client-held claims, revocable by secret rotation). JWTs add token rotation / expiry UX / refresh tokens | SessionMiddleware cookies |
| **OAuth (Google / GitHub sign-in)** | "Why manage passwords at all" | Requires an OAuth app registration, callback URLs, token storage. For a personal bot running on a personal VPS, this is a lot of config for a benefit (no password to remember) that "remember me" already solves | Out of scope. STACK.md §3 explicitly rejects |
| **Role-based access (viewer vs admin)** | "Let me give my broker read-only access to the dashboard" | Introduces the entire user/role/permission matrix; anti-pattern for single-admin scope | Out of scope |
| **SSO (SAML / OIDC provider)** | Enterprise auth | Wildly out of scope | Out of scope |
| **CAPTCHA on login** | "Defense-in-depth against brute force" | Rate-limiting already defeats brute force at the IP level; CAPTCHA hurts real users and adds a third-party dependency | Rate-limit is enough. CAPTCHA revisited only if bots become a real problem in ops logs |
| **IP allowlist built into the app** | "Only allow my home IP to log in" | The nginx reverse-proxy layer (INFRA-04) is the correct place to enforce network-level allowlists, not the Python app | Document as an nginx snippet the user can paste if desired |
| **Displaying last password / password hint** | Older UX pattern | Unsafe; security anti-pattern | Never |
| **Auto-login via URL token in a bookmarklet** | "Fast access" | Tokens-in-URLs leak via history, referrer headers, logs | Never. Remember-me cookie is the fast-access pattern |

### Dependencies on v1.0

- **`SEC-02` "fail-fast on missing secrets" discipline** extends to `SESSION_SECRET` (required, ≥32 bytes) and to either `DASHBOARD_PASS` or `DASHBOARD_PASS_HASH` (at least one must be present during the migration window; `DASHBOARD_PASS_HASH` only after migration completes)
- **Existing `_verify_csrf` HTMX-header CSRF guard** (`dashboard.py`) — login POST uses `hx-post`, header is naturally set; no new CSRF primitive needed
- **Existing `_require_auth` dependency in `dashboard.py:47–64`** — replaced end-to-end with a session-based dependency that checks the cookie and redirects on miss. Every route that currently depends on basic-auth gets the new dependency
- **INFRA-04 nginx reverse proxy with HTTPS** — the session cookie's `https_only=True` flag depends on HTTPS being terminated at nginx. Already in place; no change needed
- **INFRA-01 graceful-shutdown ASGI lifecycle** — SessionMiddleware is stateless (cookie-based), so a restart doesn't invalidate sessions unless `SESSION_SECRET` is rotated. Consistent with current shutdown behavior

### Design outputs needed before requirement phase

- Decision: username field visible or hidden (suggest **hidden, password-only**, matches single-admin model)
- Decision: where the password-rotation helper lives (suggest **`scripts/hash_password.py`**, runs standalone with `python scripts/hash_password.py` — prompts for password, prints the hash to stdout, never logs it)
- Decision: whether to gate `/login` itself behind the rate limit (suggest **yes**, per-IP, same counter as failed-login lockout)

---

## Cross-Area Feature Dependencies

```
staged entry (§1)
    ├──requires──> per-account settings (§2)
    │                  (risk_mode, fixed_lot, max_stages are per-account config)
    │
    ├──requires──> kill switch (v1.0 REL-03) to extend to pending stages
    ├──requires──> reconnect sync (v1.0 REL-02) to reconcile orphan stages
    ├──requires──> daily-limit check (v1.0 EXEC-04) per stage fill
    ├──requires──> stale re-check (v1.0 EXEC-02) per stage fill
    └──enhances──> dashboard (§3)
                       (dashboard needs a "Pending stages" panel)

per-account settings (§2)
    ├──requires──> dashboard (§3) for the UI
    │              (but the API endpoints can land first,
    │               and the form is an independent template)
    └──requires──> login (§4) to protect the settings POSTs
                       (it does today via basic-auth; the trade is
                        basic-auth → session auth with zero functional change)

dashboard redesign (§3)
    ├──requires──> Tailwind build pipeline migration (STACK.md §2)
    │              (Play-CDN → standalone CLI; v1.0 production blocker)
    ├──requires──> Basecoat CSS + JS vendored (STACK.md §1)
    └──enables──> prettier settings page (§2), prettier login (§4)

login form (§4)
    ├──requires──> argon2-cffi (STACK.md §3)
    ├──requires──> SESSION_SECRET env var (new)
    ├──requires──> Tailwind build (STACK.md §2) to style the login page
    └──conflicts──> "keep basic-auth indefinitely"
                       (login form replaces basic-auth, not augments it)
```

### Dependency notes

- **Staged entry requires per-account settings to exist as a concept** — the settings schema (`risk_mode`, `fixed_lot`, `max_stages`, `stage_allocation`) must be defined before the executor code can read them. But the **runtime UI** for editing those settings can ship after. So staged entry can use DB-level defaults in phase 1 and gain UI editability in phase 2 without rework
- **Dashboard redesign and login form share the same CSS substrate** — the Tailwind build migration and the Basecoat vendoring are prerequisites for both; doing them in a shared foundation phase avoids two separate rollouts of the toolchain
- **Per-account settings POSTs are already protected in v1.0 via basic-auth** — §4 upgrades the protection mechanism but does not introduce new protection. The settings-page feature is not *blocked* by the login form landing first, but users see a visibly inconsistent UX if the settings page ships before the login form (basic-auth prompt over a styled page)

---

## MVP Definition

### Launch With (v1.1 release candidate)

Ruthlessly minimum — all explicit user asks + safety-critical pieces.

- [ ] **Staged entry — core mechanic** (immediate stage 0 on text-only signals; pending stages on follow-up; per-account `max_stages`; percentage/fixed risk mode) — §1 table stakes through "audit trail per stage." **Essential because it is the primary v1.1 ask.**
- [ ] **Staged entry — all v1.0-safety hooks wired** (kill switch cancels stages, reconnect reconciles stages, daily-limit counts stages, stale re-check per stage, SL-hit cancels remaining stages). **Essential because shipping the feature without these is a safety regression.**
- [ ] **Per-account settings — core fields with server-side bounds** (`risk_mode`, `risk_percent`, `fixed_lot`, `max_stages`, `max_open_trades`, `max_daily_trades_per_account`, enable/disable, audit log). **Essential because staged entry requires it and the user explicitly asked for runtime editability.**
- [ ] **Per-account settings — dangerous-change confirmation + audit log visible in UI.** **Essential because real money.**
- [ ] **Dashboard redesign — Tailwind build migration** (remove `cdn.tailwindcss.com` from `base.html:7`, add standalone CLI to Dockerfile). **Essential because v1.0 currently ships a dev-mode CDN script in production.**
- [ ] **Dashboard redesign — Basecoat substrate applied across all templates, mobile responsive, zero functional regression.** **Essential because it's the explicit user ask and blocks settings page + login form from feeling polished.**
- [ ] **Dashboard redesign — pending-stages panel on Overview, positions/history row drilldowns, per-source analytics breakdown.** **Essential because these are the "richer drilldown" asks.**
- [ ] **Login form — styled form, session cookie, logout, rate-limited failed attempts, argon2 hash, backwards-compat fallback to plaintext env, SESSION_SECRET required at startup.** **Essential because it's the explicit user ask and removes the production-ugly basic-auth prompt.**

### Add After Validation (v1.1.x / v1.2)

Features worth adding once the core lands and we've run a week of live trading on it.

- [ ] **Staged entry — adaptive zone reshape on update signals** — trigger: 3+ instances of analyst updating zones mid-setup observed in production
- [ ] **Staged entry — trailing activation** — trigger: observed fast spike-through missing intermediate stages
- [ ] **Per-account settings — bulk apply, copy settings, diff-from-seed** — trigger: user reports annoyance provisioning a 4th account
- [ ] **Dashboard — command palette, toast notifications, light mode, P&L sparkline** — trigger: user requests or clear UX gain observed
- [ ] **Login — last-login timestamp display** — trigger: landed for free once session logging exists
- [ ] **DBE-01 alembic migration tooling** — per STACK.md §5, promote to v1.2 as a focused data-layer milestone after v1.1 adds 2–3 tables with hand-written DDL

### Future Consideration (v2+)

Deferred to validate real demand.

- [ ] **Passkey / WebAuthn** — higher security, significant library work, revisit if the user's threat model escalates
- [ ] **Session management UI with revocation** — relevant only if multi-device usage becomes a pattern
- [ ] **Role-based access / read-only viewer role** — relevant only if a second user ever uses the dashboard
- [ ] **Candlestick charts** — not a fit for an ops dashboard; TradingView is the right tool
- [ ] **Dashboard customization / widget reorder** — zero payoff for single-admin
- [ ] **WebSocket live updates** — HTMX polling is adequate; revisit only on a specific pain point

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Staged entry — immediate market fill on text-only | HIGH | MEDIUM | P1 |
| Staged entry — follow-up promotes stage 0 to SL/TP | HIGH | HIGH | P1 |
| Staged entry — kill-switch / reconnect / stale / daily-limit wiring | HIGH | MEDIUM | P1 |
| Staged entry — per-stage audit trail | MEDIUM | LOW | P1 |
| Staged entry — adaptive zone reshape | MEDIUM | MEDIUM | P2 |
| Staged entry — trailing activation | MEDIUM | MEDIUM | P2 |
| Per-account settings — core CRUD with bounds | HIGH | LOW | P1 |
| Per-account settings — audit log + dangerous-change confirm | HIGH | LOW | P1 |
| Per-account settings — bulk apply / copy / diff | LOW | LOW | P2 |
| Dashboard — Tailwind build migration | HIGH (de-risk) | LOW | P1 |
| Dashboard — Basecoat substrate + mobile responsive | HIGH | HIGH | P1 |
| Dashboard — row drilldowns + pending-stages panel | HIGH | MEDIUM | P1 |
| Dashboard — per-source analytics breakdown | MEDIUM | MEDIUM | P1 |
| Dashboard — command palette, toasts, light mode | MEDIUM | LOW–MEDIUM | P2 |
| Dashboard — sparkline on overview | LOW | MEDIUM | P3 |
| Login — form + session cookie + logout | HIGH | LOW | P1 |
| Login — rate limiting + lockout UI | HIGH | MEDIUM | P1 |
| Login — argon2 hash + env migration path | HIGH | LOW | P1 |
| Login — last-login timestamp | LOW | LOW | P2 |
| Login — session revocation / passkey / 2FA | LOW | HIGH | P3 |

**Priority key:** P1 = must have for v1.1; P2 = defer to v1.1.x once core lands; P3 = future consideration (v2+).

---

## Competitor / Prior-Art Feature Comparison

Published MT5 signal copiers with visible behavior:

| Feature | Typical MT5 signal copier EA (commercial) | "Telegram to MT5" Python projects (GitHub) | Our approach |
|---------|-------------------------------------------|--------------------------------------------|--------------|
| Staged entry on text-only signals | Rare; most require full SL/TP or they drop the signal | Rare; most drop the signal | Explicit first-class support with strong safety wiring |
| Per-account runtime settings UI | Common (each EA has an Inputs tab per chart) | Rare; most are config-file only | First-class, DB-backed, with audit |
| Martingale mode as a toggle | Common but dangerous | Occasional | **Explicitly rejected** as anti-feature |
| Web admin dashboard | Rare; EAs live inside MT5's terminal window | Some have it; quality varies | First-class, shadcn-styled, mobile responsive |
| Session-cookie login over basic-auth | Varies | Often omitted entirely (bots ship with no auth) | First-class, argon2, rate-limited |
| Multi-account execution with staggered delays | Rare | Rare | Already in v1.0; preserved |
| Kill switch that cancels pending orders and pauses | Rare | Rare | Already in v1.0; extended to pending stages in v1.1 |

Note: there is no dominant consumer product category here with clean public feature matrices — MT5 signal copiers are a fragmented ecosystem of EAs sold on MQL5.com, bespoke VPS services, and GitHub projects of varying maturity. The comparison above is directional rather than authoritative.

---

## Confidence Assessment

| Area | Level | Basis |
|------|-------|-------|
| Staged-entry feature breakdown + v1.0 hooks | HIGH | Mechanics derived directly from reading `trade_manager.py`, `executor.py`, `risk_calculator.py`, `signal_parser.py`. Every dependency I list points to a specific line or named function in the existing code |
| Staged-entry martingale anti-feature call-out | HIGH | This is the single most common "logical extension" that blows up signal-copier accounts; flagging it is not speculative |
| Per-account settings feature set | HIGH | Standard admin-dashboard CRUD. Fields are determined by what `AccountConfig` and `GlobalConfig` already carry + the new staged-entry knobs |
| Dashboard redesign feature set | MEDIUM-HIGH | Substrate decisions already fixed in STACK.md; what to *do* with the redesigned surface is best-practice ops-dashboard design. Mobile responsiveness + drilldowns + per-source analytics are industry standard |
| Login form feature set | HIGH | Classic single-admin auth form feature list; every choice is defensible against STACK.md §3's already-made stack decisions |
| Competitor comparison table | MEDIUM | MT5 signal-copier space is fragmented; generalizations above are directional. Not a competitive-intelligence-grade survey |

## Gaps / Open Questions

- **Signal-correlation window for text-only → follow-up** (§1) — suggest 10 minutes; user/orchestrator should confirm before phase definition
- **Dashboard mobile sidebar pattern** — suggest slide-over hamburger; minor UX call the phase plan can confirm
- **Rate-limit library vs inline implementation for login** (§4) — no rate-limit lib in current requirements; suggest inline to keep dependency count flat (consistent with v1.0 "minimize new dependencies")
- **Username field on login form** — suggest hidden; orchestrator should confirm
- **Whether to promote DBE-01 (alembic) into v1.1** — STACK.md §5 recommends deferring to v1.2; surfaced again here because v1.1 adds 2+ tables and the pressure is real

---

*Feature research defined: 2026-04-18 for milestone v1.1.*
