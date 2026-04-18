# Project Research Summary

**Project:** Telebot v1.1 — "Improved trade executions and UI"
**Domain:** Live-money MT5 trading bot (Telegram signal copier) + single-admin FastAPI/HTMX ops dashboard
**Researched:** 2026-04-18
**Confidence:** HIGH on stack/architecture/pitfalls (all grounded in the actual codebase); MEDIUM on one load-bearing feature question (staging trigger model — see Open Questions).

---

## Executive Summary

Telebot v1.1 bolts four features onto the shipped v1.0 core without a substrate rewrite: (1) **staged-entry execution** to stop missing text-only "Gold buy now" signals, (2) a **per-account runtime settings page** for risk_mode / fixed_lot / max_stages, (3) a **shadcn-styled dashboard redesign** that keeps FastAPI + Jinja + HTMX and adds Basecoat UI + a real Tailwind build, and (4) a **styled login form** replacing the v1.0 HTTPBasic prompt. The substrate question flagged in PROJECT.md resolves cleanly: **no SPA rewrite** — `basecoat-css@0.3.3` gives the shadcn visual language on top of HTMX with a single new Python dependency (`argon2-cffi==25.1.0`).

The recommended approach is to land this milestone as **five dependency-honest phases** (settings foundation → staged entries → UI substrate swap → login form → settings/stages UI), with **Phase 1 (settings foundation)** as the de-risking prerequisite since every later phase reads from a `SettingsStore` abstraction, not from the frozen `AccountConfig` dataclass. The staged-entry phase is the trickiest — it touches every v1.0 safety primitive (kill switch, reconnect/position-sync, daily limits, stale re-check, duplicate-direction guard) and each of those hooks must be explicitly extended, not bypassed.

The safety bar from v1.0 remains the dominant constraint: **real money, no regressions on live trading**. The biggest risk in v1.1 is an orphaned text-only position carrying `sl=0.0` because a follow-up signal never arrived — this is why Pitfall 1 (mandatory default SL + follow-up watchdog timeout + orphan cap) is the single most important requirement to lock into Phase 1/2. The second-biggest risk is behavioural: the duplicate-direction guard in `trade_manager.py:187-190` will silently reject stages 2..N unless it is explicitly signal-id-aware, making the feature look "done" while being broken. Mitigations for all 18 identified pitfalls are enumerated in PITFALLS.md and mapped to phases.

---

## Key Findings

### Recommended Stack

Additions only — the v1.0 core (Python 3.12, FastAPI 0.115, asyncpg, Jinja2, HTMX 2, Telethon 1.42, PostgreSQL 16, Docker) stays in place. See STACK.md for full rationale.

**Core technologies being added:**
- **Basecoat UI (`basecoat-css@0.3.3`, vendored)** — framework-agnostic shadcn/ui visual port; pairs natively with HTMX + Jinja; no SPA rewrite required. MIT-licensed, pre-1.0 but the least-bad substrate option (Basic Components is archived, everything else isn't shadcn).
- **Tailwind CSS v3.4 standalone CLI** — replaces the `cdn.tailwindcss.com` Play-CDN script currently in `templates/base.html:7` (a production blocker in v1.0 that v1.1 must fix). v3 over v4 for migration-risk reduction during an already-large UI phase; v4 migration is a v1.2 candidate.
- **`argon2-cffi==25.1.0`** — password-at-rest hashing for the new login form. Chosen over Passlib (unmaintained, 2020-dormant) and fastapi-users/authlib/JWT (overkill for single-admin).
- **`starlette.middleware.sessions.SessionMiddleware`** (already transitive via FastAPI) — signed-cookie session for the login form. `itsdangerous` is already present transitively. No new auth library.
- **Staged-entry execution + per-account settings** — **zero new Python dependencies**. Pure in-repo code: new `_zone_watch_loop` in `executor.py` mirroring the existing `_heartbeat_loop` pattern, new `SettingsStore` in-process cache, two new hand-written DDL tables (`account_settings`, `staged_entries`).

**Files to delete:** stray `drizzle.config.json` at repo root (unused JS ORM config).

### Expected Features

Feature landscape is organised by the four target areas (FEATURES.md §1–4). The following is an opinionated MVP cut.

**Must have (table stakes — v1.1 launch):**
- **Staged entry core mechanic** — text-only signal opens stage 0 immediately (market, default SL from new `default_text_only_sl_pips` knob — *never* `sl=0.0`); follow-up signal with zone/SL/TP promotes stage 0 and queues stages 1..N; per-account `max_stages`, `risk_mode` (percent|fixed), `stage_allocation`.
- **All v1.0 safety hooks extended to staged paths** — kill switch drains the pending-stages queue *before* closing positions; reconnect reconciles staged_entries against MT5 by comment-based idempotency key; daily-limit and stale re-check fire per stage; duplicate-direction guard bypassed for same-signal stages only.
- **Per-account settings page** — CRUD for risk_mode, risk_percent, fixed_lot, max_open_trades, max_stages, max_daily_trades_per_account, enable/disable; hard server-side bounds; dangerous-change two-step confirmation (mirrors v1.0 kill-switch UX); audit log of every change; "changes apply to next signal only" copy in UI.
- **Dashboard redesign** — Tailwind build migration (remove Play CDN from `base.html:7`); Basecoat substrate across all templates; mobile-responsive layout with collapsible sidebar; pending-stages panel on Overview; positions/history row drilldowns; per-source analytics breakdown. **Zero functional regression** — every existing HTMX endpoint keeps its contract.
- **Login form** — styled `/login` page using Basecoat primitives; signed session cookie via SessionMiddleware (8h default, 30-day "remember me"); logout button; argon2 hash; CSRF via double-submit cookie on `/login` only; rate-limit at nginx + app-level lockout after N failures; `SESSION_SECRET` fail-fast at startup; one-release backwards-compat fallback from `DASHBOARD_PASS` plaintext with startup refusal when both env vars are set post-migration.

**Should have (differentiators, v1.1.x or v1.2):**
- Adaptive zone reshape on update signals (move unfilled stages to new zone).
- Trailing activation of later stages (stage N only arms after stage N-1 fills).
- Settings-page bulk apply / copy-from-account / diff-from-seed view.
- Command palette (Cmd/Ctrl+K), toast notifications, light-mode toggle, per-account color tag.
- Login: last-login timestamp displayed post-auth.

**Defer (v2+ / explicit anti-features):**
- **Martingale / averaging-down / grid trading** — explicitly rejected; these are the failure modes a staged-entry feature is commonly conflated with.
- **Dynamic max_stages from signal confidence scoring** — NLP/ML; out of scope.
- **SPA rewrite to React/Vue/Nuxt** — explicitly rejected by STACK.md §1.
- **WebSocket live updates, candlestick charts, shareable dashboard links** — HTMX polling is adequate; TradingView is the chart tool.
- **User registration, password reset, 2FA, OAuth, SSO, role-based access, passkey/WebAuthn** — all out of scope for single-admin; passkey is the strongest v1.2+ candidate if threat model escalates.
- **DBE-01 alembic migration tooling** — stays deferred to v1.2 per STACK.md §5; v1.1 keeps hand-written DDL with strict additive-only discipline.

### Architecture Approach

Single Python process (`bot.py`), single asyncio event loop, FastAPI + uvicorn launched as a task inside `bot.py:main`. Telethon handler, Executor background tasks, and dashboard routes share state via direct object references (`_executor`, `_notifier` in `dashboard.py:27-30`). v1.1 keeps this topology — no second process, no IPC, no message bus — and adds three new things: a `SettingsStore` in-process cache with write-through to `account_settings`, a new `_zone_watch_loop` asyncio.Task that peers with the existing `_heartbeat_loop` and `_cleanup_loop` inside `Executor`, and a `SessionMiddleware`-fronted login layer that replaces `HTTPBasic` without touching the rest of the route layer.

**Major components (v1.1 delta):**
1. **`SettingsStore`** — single owner of `AccountSettings` lookups; `.effective(name)` merges `accounts.json` bootstrap with DB overrides; `.reload(name)` invalidates the in-memory dict on dashboard POST. Passed to `TradeManager` and `Executor` from `bot.py:main`. `AccountConfig` is effectively frozen and becomes the bootstrap/seed layer; DB wins at runtime.
2. **`Executor._zone_watch_loop` + `_trigger_stage`** — new background task, 10s default cadence (configurable via `GlobalConfig.zone_watch_interval_seconds`); polls MT5 price once per (account, symbol) pair; respects `_trading_paused` AND `_reconnecting` per tick, not only at loop entry; runs daily-limit + stale + max_open_trades checks per fill; uses comment-based idempotency key `telebot-{signal_id}-s{stage}` to survive reconnect without duplicating positions.
3. **`Executor.emergency_close` (modified)** — now calls `db.cancel_all_active_stages()` **before** closing positions, so the watcher can't race a kill-switch window. `_sync_positions` extended to reconcile staged_entries against MT5 by comment.
4. **DB schema additions (hand-written DDL)** — `account_settings` (one row per account, overrides accounts.json), `staged_entries` (per-signal pending stages with zone + status + expires_at), `settings_audit` (append-only change log), `failed_login_attempts` (for lockout). No `ALTER TABLE` on existing v1.0 tables — additive only.
5. **Dashboard auth / UI layer** — `SessionMiddleware` added to the FastAPI app; `_verify_auth` swapped from `HTTPBasic` to session-cookie read with `RedirectResponse("/login?next=…")` on miss; existing `_verify_csrf` HTMX-header check unchanged for authenticated routes; double-submit-cookie CSRF on `/login` only. Templates migrate from Play-CDN Tailwind + handwritten `.card`/`.btn-*` to Basecoat classes + built `static/css/app.css`; new templates: `login.html`, `staged.html` + partial; rewritten: `settings.html` (now editable).

See ARCHITECTURE.md §3 for the staged-entry data-flow diagram and §7 for the full recommended build order.

### Critical Pitfalls

1. **Text-only signal opens an unbounded-risk orphan (Pitfall 1)** — avoid by mandating a default protective SL at stage 0 open (`default_text_only_sl_pips`, e.g. 100), a follow-up watchdog that auto-closes or force-sets heuristic SL/TP after N minutes (default 30), a `(symbol, direction, account, window_seconds)` correlation rule, and a hard `max_orphan_text_only` per-account cap. Never submit `sl=0.0`.
2. **Duplicate-direction guard silently rejects stages 2..N (Pitfall 2)** — `trade_manager.py:187-190` was written to prevent double-filling duplicate signals; staged entries are intentional multiple fills. Tag the call with `signal.staged_entry_id` and skip the guard for same-signal stages; keep it for unrelated same-direction signals.
3. **Kill switch fires mid-stage and leaves a partial state (Pitfall 4)** — `emergency_close` must execute `UPDATE staged_entries SET status='cancelled_by_kill_switch' WHERE status='pending'` **before** closing positions; zone-watcher loop must check `_trading_paused` *inside* each per-stage tick, not only at loop entry; `resume_trading()` must NOT un-cancel the drained rows.
4. **Reconnect produces duplicates or orphaned stages (Pitfall 5)** — use comment-based idempotency keys (`telebot-{signal_id}-s{stage}`); on reconnect, query MT5 by comment before resubmitting; extend `_sync_positions` into a true reconciler against DB `staged_entries`.
5. **Tailwind purge strips classes used in Python-string HTMX responses (Pitfall 10)** — `dashboard.py` has multiple `HTMLResponse(f'<span class="text-green-400">…</span>')` sites; the Tailwind `content` glob must include `./**/*.py` and a safelist must be pinned for the critical status classes; belt-and-suspenders with a CI check grepping the built CSS.

Other must-mitigate pitfalls (see PITFALLS.md for the full 18): daily-limit accounting model for staged fills (Pitfall 3 — needs explicit up-front decision), zone-watcher cadence fills outside the zone on fast-moving instruments (Pitfall 6 — pre-flight price re-check + tolerance band), runtime settings mutation mid-stage gives inconsistent risk (Pitfall 7 — snapshot `AccountSettings` into `staged_entries` row at creation), Basecoat JS loses bindings after HTMX swap (Pitfall 11 — `htmx:afterSwap` re-init hook), stale CSS cached across a live-hours deploy (Pitfall 12 — hashed filename + deploy during market-closed window), login CSRF strategy conflicts with existing HTMX-header CSRF (Pitfall 13 — double-submit-cookie on `/login` only), schema ALTER without alembic (Pitfall 17 — hard rule: additive-only, new tables only, pre-commit lint for `ALTER TABLE`).

---

## Implications for Roadmap

Based on the architecture-honest dependency chain in ARCHITECTURE.md §7 and the pitfall-to-phase mapping in PITFALLS.md, the following five-phase structure is recommended. Phases 1+2 can overlap on DB-schema work; Phase 3 can run in parallel with Phase 2 (they touch different files); the serial chains are **1 → 2 → 5** and **3 → 4 → 5**.

### Phase 1: Settings Foundation (no UI yet)
**Rationale:** Every later phase reads from runtime-mutable settings. Building staged entries against hardcoded `AccountConfig` would require a second pass. Also the cheapest place to lock in the "additive-only schema" discipline (Pitfall 17) and the per-signal settings snapshot mechanism (Pitfall 7).
**Delivers:** `AccountSettings` dataclass + `SettingsStore` write-through cache; `account_settings` + `settings_audit` tables (hand-written DDL); `accounts.json` becomes bootstrap seed; `TradeManager` and `risk_calculator` read effective settings (including new `risk_mode="fixed"` branch); bot.py wires `SettingsStore` before `TradeManager`.
**Addresses (FEATURES.md §2):** "table stakes — per-account settings" backend layer.
**Avoids:** Pitfalls 7 (snapshot mechanism), 9 (JSON-vs-DB authority logged at startup), 17 (additive-only schema discipline established in phase plan).

### Phase 2: Staged Entries (server-side, no UI)
**Rationale:** Server-side behaviour must be correct and test-covered before we give operators a button. This is the trickiest phase — every v1.0 safety primitive must be extended, not bypassed. Must ship behind integration tests before Phase 5 exposes any UI control. **Requires the staging-trigger-model ambiguity to be resolved before kickoff** (see Open Questions).
**Delivers:** `staged_entries` table + DB helpers; `Executor._zone_watch_loop` + `_trigger_stage`; `TradeManager` persists stages on multi-stage OPEN; `emergency_close` drains the queue before closing positions; `_reconnect_account` reconciles stages by comment; `_cleanup_loop` expires old stages; default protective SL at text-only stage 0 open + follow-up watchdog timeout + orphan cap; duplicate-direction guard signal-id-aware.
**Addresses (FEATURES.md §1):** full staged-entry table-stakes set.
**Avoids:** Pitfalls 1 (text-only orphan with no SL), 2 (duplicate-direction guard), 3 (daily-limit accounting — **must be decided in Phase 2 planning**), 4 (kill switch drains queue), 5 (reconnect idempotency), 6 (zone-watcher cadence + pre-flight re-check).

### Phase 3: UI Substrate Swap (isolated, no logic changes)
**Rationale:** Visual layer change that must land before Phase 4 so the login form is styled with the same tokens as the dashboard. Can run in parallel with Phase 2 since files don't overlap. Removes a v1.0 production blocker (Play-CDN Tailwind) as a side effect.
**Delivers:** Dockerfile Tailwind v3.4 standalone CLI build stage; Basecoat CSS + JS vendored to `static/`; `base.html` swaps Play CDN for built `/static/css/app.css`; all partials and pages restyled to Basecoat primitives; mobile-responsive layout; `drizzle.config.json` deleted.
**Uses (STACK.md §1–2):** basecoat-css@0.3.3, Tailwind v3.4 standalone.
**Avoids:** Pitfalls 10 (Tailwind purge — `content` glob must include `./**/*.py` + safelist + CI check), 11 (HTMX `htmx:afterSwap` re-init hook for Basecoat JS), 12 (hashed filenames + market-closed deploy window), 18 (optimistic-UI kill-switch feedback).

### Phase 4: Login Form
**Rationale:** Settings-edit is the first truly sensitive dashboard action introduced in v1.1 — it writes DB state that affects live trading. Shipping it behind HTTPBasic then upgrading later is asking for an accidental-prod-change window. Must land before Phase 5.
**Delivers:** `SESSION_SECRET` + `DASHBOARD_PASS_HASH` config with fail-fast validation; `SessionMiddleware` added to FastAPI app; `/login`, `/logout` routes; `_verify_auth` swapped to session-cookie dependency with `RedirectResponse("/login?next=…")` on miss; `login.html` on Basecoat primitives; double-submit-cookie CSRF on `/login` only; app-level lockout + nginx `limit_req` rate limit; backwards-compat fallback from plaintext `DASHBOARD_PASS` with startup refusal when both env vars are set post-migration; `scripts/hash_password.py` CLI helper.
**Implements:** ARCHITECTURE.md §5 login layering.
**Avoids:** Pitfalls 13 (CSRF strategy split), 14 (session-secret rotation runbook), 15 (plaintext env lingering), 16 (brute-force rate limiting).

### Phase 5: Settings UI + Stages UI
**Rationale:** Integrates all prior phases — needs `SettingsStore` (1), staged_entries (2), Basecoat components (3), session auth for sensitive POSTs (4). Last on the chain.
**Delivers:** `/settings` page rewrite (editable forms, HTMX `hx-post`, dangerous-change confirmations, audit-log timeline, server-side validators, dry-run preview); `/api/settings/{account}` endpoints calling `settings_store.reload(name)` after write; `/staged` page + partial; SSE `/stream` payload extended with staged_entries.
**Addresses:** FEATURES.md §2 UI layer + §3 pending-stages panel on Overview.
**Avoids:** Pitfall 8 (invalid settings values — hard server-side bounds + dry-run preview + audit log + rollback), Pitfall 7 (UI copy makes "next signal only" explicit).

### Phase Ordering Rationale

- **Phase 1 before Phase 2** because staged entries need runtime-mutable `AccountSettings` (risk_mode, fixed_lot, max_stages, stage_allocation) and the snapshot-into-staged_entries mechanism that Phase 1 defines.
- **Phase 2 before Phase 5** because server-side staged-entry behaviour must be correct and test-covered before any UI button can trigger it — real money.
- **Phase 3 before Phase 4** because the login form must use the same design tokens as the rest of the dashboard; styling it twice is wasteful.
- **Phase 4 before Phase 5** because the settings-edit POST is the first truly sensitive dashboard action introduced in v1.1; shipping it behind HTTPBasic and upgrading later is an accidental-prod-change window.
- **Phases 1+2 overlap on DB-schema work** (both define new hand-written DDL tables; shared discipline of additive-only).
- **Phase 3 runs in parallel with Phase 2** — different files, different review surface.

### Research Flags

Phases likely needing deeper research via `/gsd-research-phase` during planning:
- **Phase 2 (staged entries)** — deepest novel-behaviour phase; needs confirmation of: MT5 REST connector price-streaming vs polling support; exact `signal_parser` regex surface for text-only "buy now"; Basecoat v0.3.3 JS re-init API for the pending-stages panel (deferred to Phase 5 in practice). *This phase must run `/gsd-discuss-phase` first to resolve the staging-trigger-model ambiguity — see Open Questions.*
- **Phase 3 (UI substrate swap)** — needs Basecoat-v0.3.3 specific verification of the 6 interactive components' JS init API, exhaustive audit of Tailwind class names in `*.py` HTMLResponse call sites, and deploy-strategy review (hashed filename, market-closed window).

Phases with standard patterns (can skip `/gsd-research-phase`):
- **Phase 1 (settings foundation)** — plain CRUD + in-memory cache; well-trodden.
- **Phase 4 (login form)** — standard FastAPI/Starlette auth pattern already well-documented; STACK.md §3 is authoritative; one open UX question (username visible vs hidden) is a scope call, not research.
- **Phase 5 (settings/stages UI)** — integrates existing pieces; feature work built on established Phase 3 substrate.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Basecoat v0.3.3 install/JS/license verified against primary sources; argon2-cffi 25.1.0 verified on PyPI; Passlib rejection grounded in its own maintenance issue; Tailwind v3 vs v4 is MEDIUM-within-HIGH (both viable; v3 is the migration-risk call) |
| Features | HIGH | Derived from direct read of `trade_manager.py`, `executor.py`, `risk_calculator.py`, `signal_parser.py`, and `dashboard.py`; competitor comparison is directional (MEDIUM) but not load-bearing |
| Architecture | HIGH | Every component boundary points to specific existing code (line ranges in ARCHITECTURE.md §1); SettingsStore design is simple because we're single-process and single-writer |
| Pitfalls | HIGH | All 18 pitfalls anchored to specific code lines or named v1.0 requirements; not a generic list |

**Overall confidence:** HIGH — with one specific, high-stakes ambiguity flagged below that must be resolved before Phase 2 planning begins.

### Gaps to Address

- **Two-signal correlation vs one-signal zone-watcher** — see Open Questions #1. **Blocking for Phase 2.** The user's own words in PROJECT.md are authoritative: two-signal. STACK.md §4 and earlier FEATURES framing described a one-signal-with-N-stages zone-watcher model, which is a different feature architecturally. Resolve via `/gsd-discuss-phase` before Phase 2 planning starts.
- **Daily-limit accounting** — 1 signal = 1 slot (Option A) vs 1 stage = 1 slot (Option B). Must be decided up-front because it changes the DB schema (Option A needs `signal_id` attribution on `daily_stats.trades_count`).
- **Staging-band semantics** — if the zone-watcher model is partially retained, how are stage N target bands derived from the signal's zone (equal slices? full re-entry? single re-entry triggers all)? Belongs in the Phase 2 discussion.
- **Text-only → follow-up correlation window duration** — suggested 10 minutes; user confirmation needed.
- **Default `stage_allocation` when `max_stages=N` is set but allocation is unspecified** — suggested equal split.
- **Username field on login form visible or hidden** — suggested hidden (password-only), matches single-admin model.
- **Tailwind v3 vs v4 final call** — recommended v3.4 for migration-risk reduction; one-line decision; not research.

### Open Questions / Must Resolve Before Planning

1. **[BLOCKING] STAGING TRIGGER MODEL — two-signal correlation vs one-signal zone-watcher.**
   PROJECT.md's milestone goal and the user's original brief describe a **two-signal correlation model**: an initial text-only signal ("Gold buy now") opens 1 immediate market position, then a **follow-up signal** with zone/SL/TP arrives later and opens additional positions as price enters the zone. STACK.md §4 and earlier FEATURES framing described a **one-signal zone-watcher model**: one OPEN signal with a zone produces N stages, a watcher polls price and fires stages 2..N as price enters pre-declared bands. **These are architecturally different features.**
   - Two-signal correlation requires: `signal_parser` correlation heuristic (same symbol + direction, within N minutes), `signals.parent_signal_id` linkage, staged_entries might collapse into a simple parent-ticket column on `trades`, the zone watcher simplifies or disappears (stages 2..N become N-1 new OPEN executions triggered by the follow-up).
   - One-signal zone-watcher requires: full `staged_entries` table, `_zone_watch_loop` polling, per-band target zones, reconnect/kill-switch queue drain semantics.
   - **The user's own words in PROJECT.md are authoritative: two-signal correlation is the intended model.**
   - **Action:** resolve via `/gsd-discuss-phase` before Phase 2 planning starts. This is the #1 blocker for Phase 2.

2. **Tailwind Play CDN in production is a blocker that Phase 3 MUST fix.** `templates/base.html:7` loads `cdn.tailwindcss.com` which Tailwind labels development-only (JIT-compiles classes in-browser on every request). This compounds every UI change we layer on top. Not optional; belongs as the first deliverable of Phase 3.

3. **Basecoat UI (`basecoat-css@0.3.3`, vendored) is the chosen shadcn-substrate for HTMX — no SPA rewrite.** The substrate question flagged in PROJECT.md is resolved. Phase 3 plan should explicitly pin the version and vendor both `basecoat.css` and `basecoat.min.js` into `static/`.

4. **Daily-limit accounting — 1 signal = 1 slot vs 1 stage = 1 slot — is blocking for Phase 1 schema.** Recommendation: Option A (1 signal = 1 slot; stages beyond stage 1 do not increment `daily_stats.trades_count`) — but this requires `signal_id` attribution on the daily-stats increment path. Decide in Phase 1 planning, not later.

5. **Alembic / DBE-01 stays deferred to v1.2.** v1.1 keeps hand-written `CREATE TABLE IF NOT EXISTS` DDL with strict additive-only discipline: no `ALTER TABLE` on tables that existed in v1.0. Pre-commit lint for `ALTER TABLE` recommended. DBE-01 is a v1.2 candidate once v1.1 adds its 3-4 new tables.

---

## Sources

### Primary (HIGH confidence)
- Existing codebase: `bot.py`, `executor.py`, `trade_manager.py`, `dashboard.py`, `db.py`, `models.py`, `risk_calculator.py`, `signal_parser.py`, `config.py`, `templates/*`, `accounts.json`
- `.planning/PROJECT.md` (v1.0 shipped state + v1.1 milestone goal and safety bar)
- `.planning/milestones/v1.0-REQUIREMENTS.md` (REL-01..04, EXEC-01..04, SEC-01..04, DBE-01 deferral)
- [basecoatui.com](https://basecoatui.com/) — Basecoat home, install, component docs
- [github.com/hunvreus/basecoat](https://github.com/hunvreus/basecoat) — v0.3.3 release, license, JS surface
- [argon2-cffi.readthedocs.io](https://argon2-cffi.readthedocs.io/) — 25.1.0 API (hash/verify/check_needs_rehash)
- [pypi.org/project/argon2-cffi/](https://pypi.org/project/argon2-cffi/) — release date, Python-version matrix
- [tailwindcss.com/blog/standalone-cli](https://tailwindcss.com/blog/standalone-cli) — standalone CLI behaviour
- [tailwindcss.com/docs/upgrade-guide](https://tailwindcss.com/docs/upgrade-guide) — v3 to v4 breaking changes
- [fastapi.tiangolo.com/advanced/response-cookies/](https://fastapi.tiangolo.com/advanced/response-cookies/) — cookie docs
- [starlette.dev/middleware/](https://starlette.dev/middleware/) — SessionMiddleware

### Secondary (MEDIUM confidence)
- [news.ycombinator.com/item?id=43971688](https://news.ycombinator.com/item?id=43971688) — Basecoat Show HN context
- [x.com/htmx_org/status/1920526787710497263](https://x.com/htmx_org/status/1920526787710497263) — htmx.org endorsement of Basecoat
- [github.com/basicmachines-co/basic-components](https://github.com/basicmachines-co/basic-components) — archived status confirmation (2026-04-05)
- [github.com/pypi/warehouse/issues/15454](https://github.com/pypi/warehouse/issues/15454) — Passlib maintenance tracking

### Tertiary (LOW confidence — directional only)
- MT5 signal-copier competitor landscape (MQL5.com, scattered GitHub projects) — no dominant public feature matrices; competitor comparison in FEATURES.md is directional, not authoritative

---
*Research completed: 2026-04-18*
*Ready for roadmap: yes — after resolving Open Question #1 via `/gsd-discuss-phase`*
