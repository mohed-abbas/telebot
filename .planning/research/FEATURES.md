# Feature Research — Telebot v1.2 (React/Vite dashboard rewrite)

**Domain:** Internal single-operator live-money trading dashboard (React 19 + Vite SPA rewrite of an existing HTMX dashboard — rewrite to parity + settings-UX upgrade)
**Researched:** 2026-06-01
**Confidence:** HIGH (per-page behavior derived directly from the current `dashboard.py` + templates; cross-cutting React patterns verified against TanStack Query v5 docs via Context7)

> **Framing.** This is a substrate migration, not a product expansion. "Features" here = the per-page behaviors the new SPA must reproduce, plus the cross-cutting state/mutation patterns that structurally eliminate the HTMX refresh-race bug class, plus the SEED-001 settings-UX upgrade. The bot core (signal parsing, MT5 execution, correlation, staged-entry logic) is untouched. Every behavior below maps to an existing endpoint in `dashboard.py`; the new dependency is the **JSON API contract** (each HTML-fragment endpoint must expose a JSON shape).

---

## The HTMX pain class (what the rewrite must structurally kill)

The current dashboard polls partials on a fixed interval and swaps server-rendered HTML into the live DOM:

- `/overview`: `#overview-cards` and `#positions-table` each `hx-get … hx-trigger="every 3s" hx-swap="innerHTML"`
- `/positions`: `#positions-full` polls every 3s
- `/staged`: SSE `sse-swap` + 5s polling fallback
- `/history`, `/analytics`: filter changes swap a table partial via `hx-push-url`

**Why it breaks:** the polled `innerHTML` swap destroys and recreates DOM subtrees. If an operator has focus in an input, an open `<details>` drilldown, or an inline result span, the tick clobbers it — flicker, lost typing, broken modal mounting. The current code works around this with brittle patches:

- Modals are mounted in a **separate `#modal-root` div outside the polled container** (`edit_levels_modal.html`, overview/positions templates) so SL/TP/% inputs survive ticks — exactly the fragility the rewrite removes.
- `_get_all_positions()` keeps a **last-good per-account cache** (`_last_positions_by_account`) purely to stop the 3s poll blinking to "no positions" on a transient REST failure (poor-man's stale-while-revalidate).
- `#toaster` carries `hx-preserve="true"` so toasts survive swaps.

**The React fix (the whole point of the milestone):** server-state lives in a cache (TanStack Query), components re-render from immutable data, and React reconciliation only patches changed nodes. Open inputs and modals live in **local component state / form-state**, which background refetch never touches. The `#modal-root`-outside-the-poll hack, the last-good-cache hack, and `hx-preserve` all disappear — they become free properties of the architecture.

---

## Cross-Cutting Pattern 1 — Live data that NEVER clobbers an input or modal (CRITICAL)

This is the central acceptance criterion. The pattern, verified against TanStack Query v5:

**1. Server-state in TanStack Query; form/UI-state in React local state. They never mix.**
The positions table renders from `useQuery` cache. The SL/TP/% inputs render from `react-hook-form` (or `useState`) inside a modal component. A background refetch updates the query cache → table re-renders; the modal's form state is a different React tree and is structurally untouched. This is the architectural guarantee, not a workaround.

**2. Background polling via `refetchInterval`.**
```ts
useQuery({
  queryKey: ['positions'],
  queryFn: fetchPositions,
  refetchInterval: 3000,          // matches current 3s cadence
  refetchOnWindowFocus: true,     // free freshness when operator returns to tab
  placeholderData: keepPreviousData, // no flicker-to-empty during refetch (replaces the last-good-cache hack)
  structuralSharing: true,        // default; unchanged rows keep identity → React skips re-render
})
```
`placeholderData: keepPreviousData` (v5 — replaces v4 `keepPreviousData: true`) means the table shows the last data while refetching, never blinking to a loading/empty state. `structuralSharing` (default-on) preserves object identity for unchanged rows so React reconciliation is minimal — no flicker.

**3. Mutations pause/cancel refetch so they can't be overwritten.**
On every live-money mutation, `onMutate` calls `await queryClient.cancelQueries({ queryKey: ['positions'] })` so an in-flight 3s refetch can't clobber the optimistic state. (Verified v5 pattern.)

**4. Optimistic update + snapshot + rollback for mutations** (see Pattern 2).

**5. Use `isFetching` (background) vs `isPending` (first load) for indicators.** A subtle "refreshing" dot driven by `isFetching` replaces the current jarring full-table swap. Never gate the table render on `isFetching`.

**Decision — TanStack Query for server-state polling over raw SSE.** The current SSE `/stream` (2s tick, emits pre-rendered HTML) exists mainly to push the pending-stages partial. For a single-operator internal tool, TanStack Query polling is simpler, has built-in caching/dedup/retry/focus-refetch, and removes the SSE+HTMX bridge. **Recommendation:** poll for v1.2 parity (positions 3s, overview 3s, staged 2–3s). Keep SSE as an explicit anti-feature for now (see below) — it is a latency optimization, not parity.

---

## Cross-Cutting Pattern 2 — Destructive / live-money actions (safer than today)

Four destructive surfaces exist today: **close position**, **modify SL/TP**, **partial close**, **kill switch**. Today's UX is thin: `hx-confirm` browser dialogs and a tiny inline result span (`#result-{ticket}`). The rewrite must be *demonstrably safer*. Pattern per action:

1. **Confirmation appropriate to blast radius.**
   - Close / partial close / modify: shadcn `AlertDialog` with the position summary (account, symbol, direction, volume, P&L) restated — richer than today's `hx-confirm` one-liner.
   - Kill switch: **two-step preview → confirm** (preserve current behavior). Step 1 fetches a preview (count of positions + pending orders, exactly like `/api/emergency-preview`); step 2 is a deliberate "CONFIRM CLOSE ALL" with a typed/hold-to-confirm gesture. Never a single click.

2. **Optimistic feedback via `useMutation` (`onMutate`/`onError`/`onSettled`).**
   - `onMutate`: cancel `['positions']` refetch, snapshot cache, optimistically mark the row "closing…" / grey it out.
   - `onError`: roll back to snapshot, surface a **sonner error toast** with the broker error string (`result.error` — the backend already returns it).
   - `onSettled`: `invalidateQueries(['positions'])` to reconcile against truth.

3. **Error toasts at the viewport, not buried inline.** Today a broker rejection lands in a 12px span the operator may not see. Replace with sonner toasts: success ("Closed #12345 on Vantage-Demo"), error ("Broker rejected: invalid stops"). This is the single biggest safety upgrade — failures become impossible to miss.

4. **Disable the trigger while in-flight** (`isPending` → disabled button) so a double-click can't double-close. Today this is `hx-disabled-elt`; in React it's `disabled={mutation.isPending}`.

5. **Modify SL/TP & partial close stay inside one modal, two independent forms** (mirrors `edit_levels_modal.html`: separate SL/TP form and partial-close form so editing one doesn't touch the other). On success the modal closes and a toast fires; on failure the modal **stays open with the error inline and typed values preserved** (current behavior via `_render_edit_modal_with_error`) — trivially correct in React because form-state is local and never re-fetched.

**Note on idempotency / "position no longer open":** the backend already guards against acting on a vanished ticket (returns an alert fragment). The SPA must handle the JSON equivalent: if a mutation 404s/"not open", show an info toast and invalidate positions rather than erroring hard.

---

## Cross-Cutting Pattern 3 — Settings page UX (SEED-001 deliverables)

SEED-001 is folded into this milestone. The current settings flow (`account_settings_tab.html` + two-step `settings_confirm_modal.html` + audit timeline + OOB toasts via `_render_toast_oob`) already has *most* of the data plumbing — SEED-001 is about making it operator-legible and giving it real toasts. Concrete deliverables:

**A. Form-state with react-hook-form + zod (mirroring server hard-caps).**
The server is the source of truth (`validate_settings_form`, `_SETTINGS_HARD_CAPS_INT`). The client zod schema **mirrors** those caps for instant inline feedback but is explicitly cosmetic — the server re-validates on confirm. Caps to mirror (from `dashboard.py:582` + `validate_settings_form`):

| Field | Constraint | Source |
|-------|-----------|--------|
| `risk_mode` | `"percent"` \| `"fixed_lot"` | `validate_settings_form` |
| `risk_value` (percent) | `> 0` and `<= 5.0` | `validate_settings_form` |
| `risk_value` (fixed_lot) | `> 0` and `<= account.max_lot_size` | `validate_settings_form` (per-account!) |
| `max_stages` | int `1–10` | `_SETTINGS_HARD_CAPS_INT` |
| `default_sl_pips` | int `1–500` | `_SETTINGS_HARD_CAPS_INT` |
| `max_daily_trades` | int `1–100` | `_SETTINGS_HARD_CAPS_INT` |

Note `risk_value`'s cap is **mode-dependent and account-dependent** — the zod schema must be dynamic (refine on `risk_mode`, and the API must expose `max_lot_size` per account). Also note the operator-confirmed semantic in memory: for `fixed_lot`, `risk_value` is the TOTAL across `max_stages`, not per-trade — copywriting must not contradict this.

**B. sonner toasts** for save success, validation rejection, and revert confirmation (replaces the hand-rolled `_render_toast_oob` OOB swap). The shadcn ecosystem standard is **sonner** (`<Toaster />` + `toast.success()` / `toast.error()`).

**C. Per-field inline help / tooltips with recommended ranges + footgun warnings.** Some help text already exists in `account_settings_tab.html` — formalize and complete it. Required per field:

| Field | Operator-legible label | Help / units | Recommended range | Footgun warning |
|-------|------------------------|--------------|-------------------|-----------------|
| `risk_mode` | "Risk calculation" | Percent-of-balance vs exact lot | — | Switching mode re-sizes every future signal |
| `risk_value` | "Per-trade risk (% of balance)" / "Lots per signal (total)" | % when percent; lots when fixed (total across stages) | 0.5%–3% | High % × high max_stages compounds exposure |
| `max_stages` | "Maximum entries per signal" | positions opened per staged signal | 1–10 (live range) | **`max_stages` × `risk_value` = total exposure per signal** (e.g. 10 × 3% = 30% of balance on one bad signal) — surface this computed number live |
| `default_sl_pips` | "Default stop-loss (pips)" | SL for text-only signals pre-zone | 10–500 | Too tight → premature stop-outs |
| `max_daily_trades` | "Daily trade limit" | new signals/day, resets midnight UTC | 1–100 | Too low silently drops valid signals |

Render the compounded-exposure warning **dynamically** as the operator types (the current template already computes `risk_value * max_stages` — keep this, make it live and prominent).

**D. Operator-legible copywriting pass.** Labels = operator mental-models, not DB column names. Keep the existing strong copy: *"Changes apply to the next signal received. In-flight staged sequences use the settings from when they started."* and the confirm-modal line *"This applies to signals received AFTER you confirm."* Consider a small glossary block.

**E. Preserve the two-step dangerous-change confirm + diff dry-run + audit timeline + revert.** This is existing safety behavior, not new scope — reproduce faithfully: validate → diff modal showing old→new + a plain-language dry-run ("A typical signal would size N stages at X% per stage") → confirm → audit row → success toast. Revert re-opens the modal with the inverted diff.

---

## Per-Page Parity Checklist (all 9 views)

Complexity = SPA implementation effort. Every page depends on the **JSON API contract** for its data endpoint(s).

### 1. `root` (`/`) — redirect
- Authenticated → redirect to `/overview`; unauthenticated → `/login`. **Complexity: LOW.** In the SPA this is a router index route + auth guard.

### 2. `login` (`/login`)
- Password-only form (single operator), httpOnly session-cookie auth (argon2 + itsdangerous) — **unchanged backend**.
- Must preserve: CSRF (double-submit cookie today), rate-limit messaging (429 "Too many failed attempts. Try again in 15 minutes."), generic "Invalid credentials.", `next` redirect after login.
- SPA nuance: same-origin cookie auth means **no token in localStorage** (locked decision). On 401 from any API call, redirect to login. CSRF on mutations preserved (custom header / cookie).
- **Complexity: MEDIUM** (auth-guard wiring, CSRF header on all mutations, 401 interceptor, redirect-after-login).

### 3. `overview` (`/overview`)
- Account summary cards per account: connected status dot, enabled, balance, equity, margin, free margin, open trades, total profit, daily trades vs limit with **daily-limit % color coding**, risk %, max lot. (`_get_accounts_overview`.)
- **TRADING PAUSED banner** when kill switch active, with **Resume Trading** button (`/api/resume-trading`).
- **Emergency Kill Switch** entry button → preview → confirm.
- Embedded **open-positions table** (same component as page 4) and **top-5 pending-stages** card (same component as page 5).
- Live: cards + positions refresh 3s; stages 2–3s.
- **Complexity: MEDIUM** (composes positions + stages components; kill-switch flow; live polling).

### 4. `positions` (`/positions`)
- Full positions table across all accounts: account, symbol, direction (BUY/SELL badge), volume, entry, SL, TP, P&L (color by sign). (`positions_table.html`.)
- Per-row actions: **Close** (confirm), **Edit** (opens SL/TP + partial-close modal).
- **Row drilldown** (expandable): fill history (stage/time/lots/band/SL-at-fill/status), live current P/L, signal attribution (source, time, type, raw text). Today multiple drilldowns can be open at once (`hx-trigger="toggle once"`) — preserve; in React this is per-row `expanded` local state, immune to refetch.
- Responsive: desktop table + mobile card list (preserve both).
- Empty state: "No open positions."
- Live: 3s background refetch that **must not collapse open drilldowns or clobber the open modal** — this page is the canonical test of Cross-Cutting Pattern 1.
- **Complexity: HIGH** (live table + optimistic mutations + drilldown state + modal; all 4 destructive actions touch here).

### 5. `staged` (`/staged`) — Pending Stages
- Active sequences list: symbol, direction badge, account, stages filled/total, target band (low–high), current price, elapsed timer, distance-to-band (signed pips, color). (`_enrich_stage_for_ui`, `pending_stages.html`.)
- "Recently resolved" collapsible table: account, symbol, direction, stage, status (human label via `_RESOLVED_STATUS_LABELS`), cancel reason, time. Read-only.
- Live: 2–3s refetch. **Read-only — no destructive actions.** Lower risk.
- Empty state: "No pending stages."
- Known v1.1 approximations carried in data (filled-count is next-to-fire, not grouped count; current_price may be `—`) — **reproduce as-is; do not "fix" in the rewrite** (anti-feature).
- **Complexity: MEDIUM** (timers/derived display; read-only so no mutation complexity).

### 6. `signals` (`/signals`) — Signal Log
- Last 100 signals: time, type (OPEN / OPEN(NOW) / CLOSE / PARTIAL / MOD SL / MOD TP — color-coded), symbol, direction badge, zone (low–high), SL, TP, action taken (executed/staged/skipped/failed — color-coded), details/raw-text truncation.
- Desktop table + mobile cards. Read-only.
- Live: current page does **not** auto-refresh signals (static 100). Parity = on-mount fetch; optionally a manual refresh or modest `refetchInterval`. Do not add filtering (not present today → anti-feature).
- Empty state: "No signals yet."
- **Complexity: LOW** (read-only table).

### 7. `history` (`/history`) — Trade History
- Filter bar: account, source, symbol dropdowns + from/to date inputs; **Apply**, **Clear All**; "Showing filtered results" indicator. (`history.html`.)
- Filtered trades table: time, account, source, symbol, direction, entry, SL, TP, lots, status (color), P&L. Desktop + mobile.
- Filters reflected in **URL** (`hx-push-url` today → React Router search params, so a filtered view is shareable/bookmarkable/back-button-correct).
- Filter options come from `db.get_trade_filter_options`; trades from `db.get_filtered_trades`.
- SPA pattern: `useQuery({ queryKey: ['history', filters] })` — changing filters changes the key → automatic refetch + cache per filter combo; `placeholderData: keepPreviousData` for smooth filter transitions (verified v5 pattern). Read-only.
- Empty state: "No trades match filters."
- **Complexity: MEDIUM** (filter-state ↔ URL sync; query-key-driven refetch).

### 8. `analytics` (`/analytics`)
- Summary cards: total trades (W/L), win rate (color ≥50%), profit factor (color >1.0), net P&L. (`analytics_table.html`.)
- P&L breakdown: gross profit, gross loss, best/worst trade.
- Time-range tabs: 7d / 30d / 90d / All. Source filter via clickable source rows (and clear-filter chip). Both reflected in URL.
- "Avg stages filled" card when a source is selected.
- Per-source table: source, trades, W/L, win rate, PF, net P&L, best/worst — rows clickable to filter.
- Read-only, no live-money actions → **designated low-risk pilot page for the parallel-run cutover** (per PROJECT.md).
- Empty state: "No closed trades in this time range."
- **Complexity: MEDIUM** (range/source filter state ↔ URL; clickable-row filtering). Good first migration target.

### 9. `settings` (`/settings`)
- Per-account **tabs**; each tab = the SEED-001 form (Cross-Cutting Pattern 3) + audit timeline.
- Replace the inline `onclick` tab JS (flagged IN-05 in code review) with shadcn `Tabs`.
- Two-step confirm modal with diff + dry-run; confirm persists + writes audit row; success toast; modal closes. Revert from audit timeline re-opens modal with inverted diff.
- Validation errors: inline per-field (red) **and** an error toast at viewport.
- **Complexity: HIGH** (forms + zod mirror + dynamic per-account/per-mode caps + two-step confirm + audit + revert + toasts + tooltips + copywriting — this is where SEED-001 lands and where most net-new UX effort goes).

---

## Feature Landscape

### Table Stakes (must reach parity — non-negotiable)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| All 9 views re-implemented | Rewrite-to-parity mandate | HIGH (aggregate) | Page-by-page cutover behind nginx |
| Live positions/overview refresh w/o clobbering inputs/modals | The bug the milestone exists to kill | HIGH | TanStack Query + local form-state separation (Pattern 1) |
| Close / modify SL+TP / partial close with confirm + error toast | Live-money safety must not regress | HIGH | useMutation optimistic + rollback + sonner (Pattern 2) |
| Two-step kill switch (preview → confirm) + Resume | Existing emergency control | MEDIUM | Preserve two-step; harden confirm gesture |
| Position drilldown (fill history, signal attribution, live P/L) | Operator audit need | MEDIUM | Per-row local expand state, refetch-immune |
| History filters reflected in URL | Shareable/bookmarkable filtered views | MEDIUM | React Router search params + query-key |
| Analytics range/source filtering | Existing perf analysis | MEDIUM | Cutover pilot (read-only) |
| Settings: per-account tabs, two-step confirm, diff dry-run, audit, revert | Existing safety + auditability | HIGH | Reproduce faithfully |
| Settings: zod mirror of server hard-caps | Instant feedback; server still authoritative | MEDIUM | Caps table above; dynamic on risk_mode + max_lot_size |
| Settings: sonner toasts (save/error/revert) | SEED-001 #1, #2 | LOW | Replaces OOB toast hack |
| Settings: per-field help, recommended ranges, footgun warnings | SEED-001 #3 | MEDIUM | Live compounded-exposure warning |
| Settings: operator-legible copywriting | SEED-001 #4 | LOW | Labels = mental models, not DB columns |
| Session-cookie auth, CSRF on mutations, 401→login | Security parity (locked) | MEDIUM | No localStorage token; same-origin |
| Responsive desktop table / mobile card layouts | Present on every list page today | MEDIUM | Reproduce both breakpoints |
| Empty states per list page | Present today | LOW | Reuse existing copy |
| TRADING PAUSED + DRY-RUN/LIVE/DISABLED status indicators | Operator situational awareness | LOW | Sidebar status dot + banner |
| Daily-limit % color coding on overview | Existing risk signal | LOW | Carry color thresholds |

### Differentiators (UX upgrades that are *in scope* because they ride the rewrite)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Viewport-level error toasts on broker rejections | Failures impossible to miss vs today's 12px span | LOW | Biggest real safety gain; sonner |
| Optimistic row states ("closing…") with rollback | Snappier, clearer than HTMX swap | MEDIUM | useMutation onMutate/onError |
| `isFetching` subtle refresh indicator (no full-table flicker) | Calm live updates vs jarring swaps | LOW | Don't gate render on it |
| Live compounded-exposure warning in settings | Prevents the 30%-on-one-signal footgun | LOW | Compute risk_value × max_stages as typed |
| Disable action buttons while mutation in-flight | Prevents accidental double-close | LOW | disabled={isPending} |
| Bookmarkable filtered history/analytics URLs | Operator workflow convenience | LOW | Free with router search params |

### Anti-Features (explicitly OUT of scope — parity-only milestone)

| Feature | Why Tempting | Why Problematic Here | Instead |
|---------|--------------|----------------------|---------|
| New analytics (equity curve, drawdown, new metrics) | "While we're rewriting…" | Scope creep; changes blast radius beyond presentation | Reproduce existing analytics only |
| New trading capability (new order types, bulk actions, scale-in UI) | Powerful | Touches live-money path the milestone vows not to regress | None — backend untouched |
| Signal-log filtering / search | Seems natural | Not present today; not parity | Defer to a future milestone |
| Fixing v1.1 data approximations (staged filled-count, current_price `—`) | Looks like a bug | Backend behavior, not frontend; out of milestone scope | Reproduce as-is; flag separately |
| Keeping/expanding SSE `/stream` for push updates | "Real-time" appeal | Adds SSE+bridge complexity; polling meets a 1-operator tool's needs | TanStack Query `refetchInterval`; revisit SSE only if latency proves insufficient |
| WebSocket layer | Modern | Backend has no WS; out of scope; over-engineered for one operator | Polling |
| localStorage / JWT auth tokens | Common SPA pattern | Explicitly rejected (XSS risk); breaks CSRF model | httpOnly session cookie, same-origin (locked) |
| Global client state lib (Redux/Zustand) for server data | Habit | Server-state belongs in TanStack Query; double-caching causes the exact stale/clobber bugs being killed | TanStack Query for server-state; local state for UI |
| Multi-user / roles / per-user settings | "Future-proofing" | Single operator; YAGNI | None |
| Optimistic updates on settings confirm | Consistency | Settings changes are deliberate + two-step-gated; optimism adds risk for no felt benefit | Pessimistic: confirm → server → toast → refetch |

---

## Feature Dependencies

```
JSON API contract (refactor dashboard.py endpoints → JSON)
    └──required by──> ALL 9 pages (every page's data + every mutation)

SPA scaffold + session-cookie auth + CSRF interceptor + 401→login guard
    └──required by──> every authenticated page and mutation

TanStack Query setup (QueryClient, polling config, structuralSharing)
    └──required by──> overview, positions, staged (live pages)
    └──enhances────> history, analytics (cache per filter combo)

useMutation optimistic+rollback pattern + sonner Toaster
    └──required by──> close, modify SL/TP, partial close, kill switch, settings confirm/revert

shadcn primitives: Tabs, AlertDialog/Dialog, Tooltip, Sonner, Form (rhf+zod)
    └──required by──> settings (Tabs/Form/Tooltip), destructive actions (AlertDialog), all toasts (Sonner)

Positions table + drilldown + edit-levels modal (shared components)
    └──used by──> overview (embedded) AND positions (full page)

Pending-stages card component
    └──used by──> overview (top-5) AND staged (full list)
```

### Dependency Notes
- **JSON API contract gates everything** — it must be the first phase. The computation already exists in `dashboard.py`; only response shape changes. Each page's parity work is blocked until its endpoint returns JSON.
- **Auth + CSRF + 401 interceptor is foundational** — every mutation needs the CSRF header; every query needs the 401→login behavior. Build once in the scaffold phase.
- **Shared components (positions table, pending-stages card, edit modal)** appear on multiple pages — build once, compose. Migrating `positions` effectively unlocks `overview`'s embedded table.
- **Analytics is the safe pilot** — read-only, no mutations, no live polling pressure; ideal first cutover to validate the API+SPA+auth+nginx pipeline before touching live-money pages.

---

## MVP Definition (= parity, since this is a rewrite)

### Launch With (v1.2 — full parity is the bar)
- [ ] JSON API for all data + mutation endpoints — *gates everything*
- [ ] SPA scaffold: routing, session-cookie auth guard, CSRF header, 401→login, design tokens (`#252542`/`#1a1a2e`/`#0f0f1a`)
- [ ] TanStack Query polling + `placeholderData: keepPreviousData` + structuralSharing — *the bug fix*
- [ ] All 9 pages at parity (per-page checklist above)
- [ ] Destructive-action pattern (confirm + optimistic + rollback + error toast) on all 4 live-money surfaces — *safety must not regress*
- [ ] SEED-001 settings UX (zod mirror, sonner, tooltips/ranges/footguns, copywriting) — *the one upgrade in scope*
- [ ] Parallel-run cutover behind nginx, analytics first

### Add After Validation (deliberately deferred)
- [ ] Re-evaluate SSE/WebSocket push — *trigger: only if 3s polling latency proves insufficient in live VPS UAT*
- [ ] Decommission deprecated `/api/modify-sl` and `/api/modify-tp` endpoints — *trigger: after confirming no external callers (modal uses `/api/modify-levels`)*

### Future Consideration (out of this milestone)
- [ ] New analytics / signal filtering / bulk actions — *only after a new milestone explicitly scopes them*
- [ ] Fixing v1.1 staged-data approximations — *backend work; separate item*

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| JSON API contract | HIGH | MEDIUM | P1 |
| Auth + CSRF + 401 guard scaffold | HIGH | MEDIUM | P1 |
| TanStack Query no-clobber polling | HIGH | MEDIUM | P1 |
| Positions page (table + drilldown + edit modal + mutations) | HIGH | HIGH | P1 |
| Destructive-action safe pattern (confirm/optimistic/rollback/toast) | HIGH | MEDIUM | P1 |
| Kill switch two-step | HIGH | MEDIUM | P1 |
| Settings page + SEED-001 UX | HIGH | HIGH | P1 |
| Overview (composes positions + stages + kill switch) | HIGH | MEDIUM | P1 |
| Analytics (pilot) | MEDIUM | MEDIUM | P1 (first cutover) |
| History (filters + URL) | MEDIUM | MEDIUM | P1 |
| Staged (read-only live) | MEDIUM | MEDIUM | P1 |
| Signals (read-only) | MEDIUM | LOW | P1 |
| Login + root redirect | HIGH | LOW–MEDIUM | P1 |
| Viewport error toasts | HIGH | LOW | P1 (rides destructive pattern) |
| SSE/WebSocket push | LOW | HIGH | P3 (anti-feature for now) |

**Priority key:** P1 = required for parity cutover · P2 = should-have when possible · P3 = defer / out of scope. Because this is a parity rewrite, nearly everything is P1 — prioritization is about *ordering* (API → scaffold → analytics pilot → live-money pages → settings), not about dropping features.

---

## Sources

- `dashboard.py` (current 9 routes + ~31 endpoints; validators; `_get_all_positions` last-good cache; `_render_toast_oob`; kill-switch preview/confirm) — HIGH
- `templates/` + `templates/partials/` (per-page structure, modal-outside-poll pattern, settings form/help, two-step confirm, audit timeline, responsive table/card layouts) — HIGH
- `.planning/PROJECT.md` v1.2 milestone section + Key Decisions (locked stack, cutover strategy, auth model, anti-Next.js/anti-localStorage decisions) — HIGH
- `.planning/seeds/SEED-001-settings-ux-polish.md` (toasts, inline help, copywriting; hard-cap source-of-truth breadcrumb) — HIGH
- MEMORY: `project_lot_semantics.md` (fixed_lot risk_value = TOTAL across max_stages — copywriting constraint) — HIGH
- TanStack Query v5 docs via Context7 (`/tanstack/query`): optimistic updates (`onMutate`/`onError`/`onSettled`, `cancelQueries`, `setQueryData`, `invalidateQueries`), `placeholderData: keepPreviousData` (v5 migration from `keepPreviousData`), `refetchInterval`, `refetchOnWindowFocus`, `structuralSharing`, `isFetching` vs `isPending` — HIGH

---
*Feature research for: React/Vite live-money trading dashboard rewrite (v1.2, parity + SEED-001)*
*Researched: 2026-06-01*
