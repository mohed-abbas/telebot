# Phase 10: Read-only Page Migration (analytics pilot → signals → history → staged) - Research

**Researched:** 2026-06-06
**Domain:** React 19 + TanStack Query v5 SPA pages over a shipped FastAPI `/api/v2` JSON contract; two read-only API serialization widenings; shared SPA table/state primitives
**Confidence:** HIGH (grounded in the actual codebase — every claim below is read from current source, not training data)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Extend `/api/v2/analytics` to full legacy parity (read-only). Widen the `Analytics` schema + route to surface `by_source[]` (per-source: trades, W/L, win_rate, profit_factor, net_pnl + `_display`, best/worst), `extremes`, `avg_stages`, and the `sources` list — single round-trip. Money/number fields follow the Phase-8 dual-value `*_display` rule; SPA renders `_display`, never re-rounds (Pitfall 5).
- **D-02:** Analytics filter state lives in the URL (`?range=&source=`), bookmarkable — same URL-sync convention as history (D-05), one shared helper across both pages. Default load = all-time, no source filter. Clicking a Performance-by-Source row sets `?source=<name>` (re-query).
- **D-03:** Only the staged page polls (background `refetchInterval`). Analytics/signals/history do NOT background-poll — fetch-on-mount + `refetchOnWindowFocus`. `keepPreviousData` still prevents flicker on filter/range changes.
- **D-04:** Snapshot pages (analytics/signals/history) carry a manual Refresh control.
- **D-05:** History filter state in the URL (bookmarkable) with `keepPreviousData`. Filters from `GET /api/v2/history/filter-options` (accounts, symbols, sources; `directions` returns empty — not a distinct filter). Map to `GET /api/v2/history` params: `account`, `source`, `symbol`, `from_date`, `to_date`. Same URL-sync helper as D-02.
- **D-06:** Elapsed-time is a client-side ticking timer derived from a server start-timestamp (ISO/UTC), counting up per-second between polls. Relative duration off a server epoch — NOT re-rounding of server money/prices, so consistent with Pitfall 5.
- **D-07:** Staged data polls every ~3s via TanStack `refetchInterval`; only the elapsed duration ticks client-side. Polling only — no SSE/WebSocket (ARCHITECTURE §4 / anti-pattern 5).
- **D-08:** Staged-active renders as card-per-account (legacy `partials/pending_stages.html` shape); recently-resolved renders in the shared table (D-10). `/stages` returns `{active[], resolved[]}`.
- **D-09:** Read-only enrichment: the `/api/v2/stages` active payload must surface a machine start-timestamp (ISO/UTC) so the D-06 client timer has an epoch. Same widening category as D-01 (extend `_enrich_active` / active-stage shape; resolved rows already carry `created_at`/`filled_at` machine + `_display` twins).
- **D-10:** Build shared primitives during the pilot: one reusable `DataTable` (sticky header, column alignment, mono numerics, color-by-sign for P&L) + a standard `Loading` (skeleton) / `Empty` / `Error` state trio. Tables: signals, history, recently-resolved stages, analytics by-source. Cards: staged-active. Phase 11 inherits.
- **D-11:** Error state = inline panel (message + Retry button) in the page body, NOT a transient toast. `401` still handled by the inherited global `onAuthError` redirect (Phase 9 D-06) — unchanged.

### Claude's Discretion

- Exact column sets / ordering for each table — match legacy templates as parity reference.
- Exact `DataTable` API surface (props, sorting if any) and where shared components/hooks live in `frontend/src`.
- Exact `staleTime`/`refetchInterval` numbers within the D-03/D-07 frame (staged ~3s; others = no interval).
- Which shadcn components each page pulls via the CLI (per Phase 9 D-11 — add per-page, keep lean).
- Precise shape of the analytics schema widening (field names for `by_source` rows, `extremes`, `sources`) — follow the Phase-8 dual-value `*_display` convention.
- Precise field name for the staged active start-timestamp (e.g. `created_at` ISO) and its `_display` twin if useful.
- Client ticking-timer implementation detail (shared `useElapsed` hook vs per-card).
- Parity-verification mechanics (side-by-side vs golden-number capture) against the live legacy page.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope. Live-money mutation pages, optimistic-update discipline, CSRF-on-write, settings, and react-hook-form/zod validation → Phase 11. Legacy-route / SSE `/stream` / Tailwind-CLI removal → Phase 12.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PAGE-01 | Analytics page (read-only pilot) reaches parity — win rate, profit factor, per-source deep-dive | §"Analytics widening (D-01)" enumerates the exact `db.get_analytics_with_filters()` shape vs the shipped `Analytics` schema and the legacy `analytics_table.html` column set; §"URL-filter-sync" + §"Shared SPA primitives" supply the page mechanics |
| PAGE-02 | Signals page reaches parity | §"Signals parity gap (NEW finding)" — the shipped `Signal` schema DROPS fields the legacy table renders (zone, sl, tp, details); this is a required read-only schema widening the planner must surface |
| PAGE-03 | History page reaches parity incl. trade-history filters, URL-bookmarkable, `keepPreviousData` | §"URL-filter-sync helper (D-02/D-05)" — `GET /history` + `/history/filter-options` are parity-complete on the backend; §"History parity note" flags two legacy columns (SL/TP) the shipped `HistoryTrade` schema omits |
| PAGE-04 | Staged-entries page reaches parity (pending stages per account) | §"Staged start-timestamp enrichment (D-09)" + §"Ticking elapsed timer (D-06)" + §"Staged active field-name reconciliation (NEW finding)" — the enriched-active shape uses keys the legacy template does NOT match |
</phase_requirements>

## Summary

This is a **code/config-only phase that installs no new external packages** — every dependency the four pages need is already in `frontend/package.json` (React 19.2, TanStack Query 5.101, react-router-dom 7.17, radix-ui 1.4, lucide-react 1.17, Tailwind v4.3). The two API widenings (D-01 analytics, D-09 staged timestamp) are **pure serialization changes** in `api/schemas.py` + `api/analytics.py` + `api/stages.py` — the underlying `db.*` queries already compute everything (`get_analytics_with_filters` returns `by_source`/`extremes`/`avg_stages`; `get_pending_stages` already SELECTs `created_at`). **Zero query work, zero bot-core change.**

The single biggest planning risk this research surfaces is **three latent parity gaps in the shipped Phase-8 read schemas that nobody has hit yet because no SPA page consumed them**: (1) the `Signal` schema drops `entry_zone_low/high`, `sl`, `tp`, `details`, `source_name` that the legacy Signal Log renders; (2) the `HistoryTrade` schema has `sl`/`tp` columns in legacy but the schema omits them (and `get_filtered_trades` *does* return `t.sl, t.tp`); (3) the staged-active enriched dict from `dashboard._enrich_stage_for_ui` emits keys `filled`/`total`/`distance_str`/`elapsed` while the legacy template references `filled_count`/`total_stages`/`distance_to_band` — a pre-existing field-name mismatch meaning the legacy template's "Stages" and "Distance to band" cells render blank/never. The planner must treat these as **read-only schema widenings in the same category as D-01/D-09**, or the SPA pages cannot reach parity with what the legacy *intended* to show.

The second risk is **Pitfall 5 discipline at the table layer**: every numeric the SPA shows must come from a server `_display` string, never a JS `.toFixed()`. The analytics widening must therefore add `_display` twins on `net_pnl`, `best_trade`, `worst_trade` per by-source row and on `extremes` — `win_rate`/`profit_factor` are ratios and stay raw per the Phase-8 D-05 rule (matching how the existing summary route already treats them). The elapsed timer (D-06) is explicitly *exempt* because it is a relative duration computed off a server ISO epoch, not a re-rounding of a server-formatted money/price value.

**Primary recommendation:** Plan analytics first as the pilot that establishes `frontend/src/components/data/DataTable.tsx` + `frontend/src/components/state/{Loading,Empty,ErrorPanel}.tsx` + `frontend/src/lib/useUrlFilters.ts` (one `useSearchParams`-backed helper). Build the D-01 analytics widening + the three latent parity-gap widenings as backend tasks in the SAME phase. Then signals → history → staged reuse the primitives. Verify each page by golden-number capture against the live legacy twin (the numbers are server-formatted identically on both sides, so equality is exact, not eyeballed).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Analytics aggregation (by_source, extremes, avg_stages) | Database (`db.get_analytics_with_filters`) | — | Already computed in SQL; nothing moves to the client |
| Analytics serialization + `_display` formatting | API / Backend (`api/analytics.py` + `api/formatting.py`) | — | Pitfall 5: all number/money formatting is server-side; SPA never re-derives |
| Staged start-epoch for the timer | API / Backend (`api/stages.py` `_enrich_active`) | — | The machine ISO timestamp comes from `get_pending_stages().created_at`; serialized server-side |
| Elapsed-duration ticking (per-second count-up) | Browser / Client (`useElapsed` hook) | — | A relative duration off a server epoch — the ONE display computation legitimately done client-side (D-06) |
| Filter state (URL params ↔ query keys) | Browser / Client (react-router `useSearchParams`) | API (query params) | URL is the source of truth; the query key derives from it; the server filters |
| Data fetching / caching / polling | Browser / Client (TanStack Query) | API (read routes) | Inherited Phase-9 QueryClient; staged polls, others fetch-on-mount |
| Loading / Empty / Error presentation | Browser / Client (state trio) | — | Pure presentation; `401` escalates to the inherited global handler |

## Standard Stack

### Core (ALL ALREADY INSTALLED — no `npm install` this phase)

| Library | Version (verified in `frontend/package.json`) | Purpose | Why Standard |
|---------|--------|---------|--------------|
| react / react-dom | ^19.2.7 | UI runtime | Locked v1.2 stack |
| @tanstack/react-query | ^5.101.0 | Server-state, polling, `keepPreviousData` | Inherited Phase-9 QueryClient defaults |
| react-router-dom | ^7.17.0 | Routing + `useSearchParams` for URL filters | Inherited Phase-9 router (`basename:/app`) |
| radix-ui | ^1.4.3 | shadcn primitive substrate (tabs, select for filters) | Phase-9 unified umbrella package |
| lucide-react | ^1.17.0 | Icons (refresh, empty-state, error) | Already used in AppShell (`Menu`, `X`) |
| tailwindcss / @tailwindcss/vite | ^4.3.0 | Styling, `@theme` tokens | Locked v1.2 stack; no `tailwind.config.js` |
| sonner | ^2.0.7 | Toasts (NOT for page-load errors per D-11; reserved for action feedback) | Inherited Phase-9 Toaster |

### Supporting — shadcn components likely added this phase (via CLI, per Phase-9 D-11)

| Component | Purpose | When to Use |
|-----------|---------|-------------|
| `tabs` | Analytics range pill tabs (7d/30d/90d/all) | Analytics page (mirrors legacy `time-tabs`) |
| `select` | History filter dropdowns (account/source/symbol); analytics source dropdown (mobile) | History + analytics |
| `table` | shadcn table styling primitive UNDER the shared `DataTable` | DataTable base (optional — can style raw `<table>` directly) |
| `skeleton` | Loading-state shimmer rows | `Loading` state component |
| `badge` | BUY/SELL pills, status labels | signals, history, staged |

**Installation:** `npx shadcn@latest add tabs select table skeleton badge` (per-page, keep lean — verify each is needed before adding).

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled `DataTable` over raw `<table>` | `@tanstack/react-table` | react-table is NOT installed and adds a headless-table dep + API surface for sorting/pagination this phase does not need (legacy tables are static, server-sorted). D-10 asks for a *thin* shared component, not a data-grid. **Recommend: hand-rolled DataTable, no react-table.** [VERIFIED: frontend/package.json — react-table absent] |
| `useSearchParams` URL-filter helper | nuqs / query-string lib | nuqs is not installed; react-router 7 `useSearchParams` already covers `?range=&source=` and the 5 history params natively. **Recommend: no new dep.** [VERIFIED: react-router-dom 7.17 installed] |
| Client-side elapsed timer | Server-pushed elapsed string per poll | Server string only updates every ~3s (jumpy). D-06 locks the client timer. |

**Version verification:** All packages above read directly from `/Users/murx/Developer/personal/telebot/frontend/package.json` on 2026-06-06. No registry lookup needed — nothing is being added.

## Package Legitimacy Audit

**Not applicable — this phase installs zero new external packages.** All runtime dependencies are already present in `frontend/package.json` (verified read 2026-06-06). The only additions are shadcn component *source files* generated locally by the shadcn CLI (which copies vetted component code into `frontend/src/components/ui/`, not an npm dependency). No slopcheck run required; no registry surface introduced.

If a planner later decides a primitive genuinely needs a new dep (none identified), the Package Legitimacy Gate must run before that install.

## Concrete Current-State Facts (the planner needs these exact shapes)

### 1. Analytics widening (D-01)

**What `db.get_analytics_with_filters(range_days, source_name)` returns TODAY** (`db.py:647-783`, verified):

```python
{
  "summary": {
    "total_trades": int, "wins": int, "losses": int,
    "win_rate": float | None,        # already a percentage (e.g. 62.5), ROUND(.,1)
    "profit_factor": float | None,   # ROUND(.,2)
    "gross_profit": float, "gross_loss": float, "net_pnl": float,
  },
  "by_source": [                     # ordered by COUNT(*) DESC
    {
      "source_name": str,            # COALESCE(...,'Unknown')
      "total_trades": int, "wins": int, "losses": int,
      "win_rate": float | None,      # percentage, ROUND(.,1)
      "profit_factor": float | None, # ROUND(.,2)
      "net_pnl": float,
      "best_trade": float | None, "worst_trade": float | None,
    }, ...
  ],
  "avg_stages": float | None,        # ONLY non-null when source_name is set (see note)
  "extremes": { "best_trade": float | None, "worst_trade": float | None },
}
```

**What the shipped `Analytics` schema exposes TODAY** (`api/schemas.py:146-157`): ONLY the flat summary — `total_trades, wins, losses, win_rate, profit_factor, total_profit(+_display), gross_profit(+_display), gross_loss(+_display)`. The route (`api/analytics.py`) maps `summary.net_pnl → total_profit`, **calls `await db.get_analytics_sources()` and discards the result** (line 47), and never surfaces `by_source`/`extremes`/`avg_stages`/`sources`.

**Recommended widening** (planner's discretion on exact names — these follow the Phase-8 D-05 dual-value rule, confirmed against `api/formatting.py`):

- Add nested models: `AnalyticsBySource` and `AnalyticsExtremes`.
- `AnalyticsBySource` fields: `source_name: str`, `total_trades: int`, `wins: int`, `losses: int`, `win_rate: float | None` (raw ratio/pct — NO `_display`), `profit_factor: float | None` (raw — NO `_display`), `net_pnl: float` + `net_pnl_display: str` (`money_display`), `best_trade: float | None` + `best_trade_display: str | None`, `worst_trade: float | None` + `worst_trade_display: str | None`.
- `AnalyticsExtremes` fields: `best_trade: float | None` (+ `_display`), `worst_trade: float | None` (+ `_display`).
- `Analytics` gains: `by_source: list[AnalyticsBySource] = []`, `extremes: AnalyticsExtremes`, `avg_stages: float | None = None`, `sources: list[str] = []`.
- Route change: capture `sources = await db.get_analytics_sources()` instead of discarding; populate the new fields; run `money_display()` on each money twin.

**`_display` rule recap (verified against the existing route + D-05):** money fields get `_display`; **`win_rate` and `profit_factor` are ratios → NO `_display` twin** (the existing `api/analytics.py` already follows this — it does NOT add `win_rate_display`). The legacy formats win_rate as `"%.1f"|format(...) + "%"` and PF as `"%.2f"` — the SPA may format these client-side from the raw number **because they are ratios, not money/price** (Pitfall 5 bans re-rounding *money/price* precision; a percentage display is not in that class). If the planner wants zero client formatting at all, add `_display` twins for them too — but that is NOT required and diverges from the shipped summary route's established convention. **Recommend: keep ratios raw, mirror the existing route.**

**Legacy parity column set for the Performance-by-Source table** (`templates/partials/analytics_table.html:80-119`, verified, in order): `Source | Trades | W/L | Win Rate | PF | Net P&L | Best/Worst`. Row is clickable → `?source=<name>` (HTMX `hx-get` → SPA navigates the URL filter). Active source row gets `bg-primary/10`.

**Legacy summary KPI cards** (lines 1-72): four cards — `Total Trades` (+ `W / L` sub-line), `Win Rate` (green ≥50 / red), `Profit Factor` (green >1.0 / red), `Net P&L` (green >0 / red >0). Then a `Profit & Loss` panel: `Gross Profit` (green) / `Gross Loss` (red) / `Best / Worst Trade`. Then `Avg Stages Filled` card **only when `avg_stages` is truthy** (i.e., only when a source is selected — see note).

**NOTE on `avg_stages` (verified `db.py:745-762`):** `avg_stages` is computed **only when `source_name` is provided** (it is `None` for the all-sources view). So the SPA's Avg-Stages card should render only when a source filter is active — exactly matching the legacy `{% if avg_stages %}` guard. The planner should NOT expect avg_stages on the default all-time/all-source load.

### 2. Staged start-timestamp enrichment (D-09)

**What flows TODAY** (verified `api/stages.py` + `dashboard.py:500-581` + `db.py:1057-1079`):

- `db.get_pending_stages()` SELECTs `created_at` (a `TIMESTAMPTZ`) on every active row — **the epoch already exists in the data**.
- `dashboard._enrich_stage_for_ui(stage, positions)` consumes `created_at` to compute a **server-formatted `elapsed` string** (`"MM:SS"` or `"HH:MM:SS"`) — but its returned dict **does NOT include `created_at`** (it drops the raw timestamp; output keys are `account_name, symbol, direction, filled, total, band_low, band_high, current_price, distance_str, elapsed, status`).
- `api/stages.py._enrich_active()` then adds `_display` twins for `band_low`/`band_high`/`current_price` only.

**So the active payload has NO machine timestamp today** — exactly what D-09 calls out. The D-06 client timer needs an epoch.

**Recommended widening** (planner's discretion on name): in `api/stages.py._enrich_active()`, pull the raw `created_at` from the **original `raw_active` stage row** (not the enriched dict, which dropped it) and serialize it via `ts_machine()` → add `started_at: str` (ISO-8601 + UTC offset). Optionally add `started_at_display: str` via `ts_display()` for any non-ticking fallback. **Implementation note:** `list_stages` currently does `active = [dashboard._enrich_stage_for_ui(s, positions) for s in raw_active]` then `_enrich_active(s)` — the raw `created_at` is in `raw_active[i]`, not in the enriched dict. The cleanest change is to zip the raw row with the enriched dict (or have `_enrich_active` take both), so `created_at` survives. This is the one non-trivial plumbing detail in the widening.

The legacy `s.elapsed` string can be kept on the payload for parity-debugging, but the SPA will compute its own ticking value from `started_at`.

### 3. Signals parity gap (NEW finding — must be addressed for PAGE-02)

The legacy `templates/signals.html` table renders these per row: `Time, Type, Symbol, Direction, Zone (entry_zone_low–entry_zone_high), SL, TP, Action, Details (s.details or raw_text[:80])`. The `signals` table (`db.py:82-100`) HAS all these columns, and `db.get_recent_signals(100)` does `SELECT *` so the route receives them.

**BUT the shipped `Signal` schema (`api/schemas.py:113-121`) only declares:** `id, raw_text, signal_type, symbol, direction, action_taken, received_at(+_display)`. It **drops `entry_zone_low`, `entry_zone_high`, `sl`, `tp`, `details`, and `source_name`.** The SPA cannot render the legacy Zone/SL/TP/Details columns from this schema.

**Required action (read-only widening, same category as D-01/D-09):** extend the `Signal` schema + `api/signals.py._enrich_signal` to surface `entry_zone_low`, `entry_zone_high`, `sl`, `tp` (with `_display` price twins via `price_display`), `details: str | None`, and optionally `source_name`. Without this, PAGE-02 cannot reach parity. The planner MUST include this as a backend task. **Confidence: HIGH** (read both the template and the schema directly).

**Legacy `Type` cell mapping** (verified, signals.html:31-46): `open→OPEN`, `open_text_only→OPEN (NOW)`, `close→CLOSE`, `close_partial→PARTIAL`, `modify_sl→MOD SL`, `modify_tp→MOD TP`, else raw `signal_type`. The SPA should reproduce this label map.

### 4. History parity note (minor gap — PAGE-03)

`db.get_filtered_trades()` (`db.py:557-566`) selects `t.sl, t.tp` and the legacy `history_table.html` renders **SL and TP columns**. But the shipped `HistoryTrade` schema (`api/schemas.py:83-99`) has NO `sl`/`tp` fields — and `api/history.py._enrich_trade()` does not map them. Legacy column order: `Time, Account, Source, Symbol, Direction, Entry, SL, TP, Lots, Status, P&L`.

**Action:** to reach strict parity, add `sl`/`tp` (+ `_display` price twins) and `source_name`, `status` to `HistoryTrade` + `_enrich_trade`. `source_name` is already returned by the query (`COALESCE(s.source_name,'Unknown')`) and `status` is `t.status`. The schema currently surfaces neither. **The planner should confirm with the operator whether SL/TP/Status/Source columns are parity-required** — the success criterion is "all trade-history filters" + "parity"; the filters are fully backed, but the *columns* have this gap. Flag as a parity decision. **Confidence: HIGH on the gap; MEDIUM on whether the operator wants every legacy column.** (See Assumptions Log A1.)

### 5. Staged active field-name reconciliation (NEW finding — PAGE-04)

`dashboard._enrich_stage_for_ui` returns keys: `filled`, `total`, `distance_str`, `elapsed`. The legacy `partials/pending_stages.html` references `s.filled_count`, `s.total_stages`, `s.distance_to_band`, `s.elapsed`. **`filled_count`/`total_stages`/`distance_to_band` do not exist on the enriched dict** — meaning the legacy "Stages" cell and "Distance to band" block currently render blank/never in the HTMX page. This is a **pre-existing legacy bug**, not something the SPA must replicate.

**Implication for parity verification:** "parity with the live legacy page" for staged means matching what the legacy *actually shows* (Stages cell is blank today). The SPA can choose to render the CORRECT values from the enriched dict's real keys (`filled`/`total`), which is *better* than legacy — the planner should decide whether "parity" means bug-for-bug or corrected. **Recommend: render the correct `filled`/`total` (the enriched dict has them) and note the legacy bug in the parity check rather than replicating a blank cell.** Surface `filled`, `total`, `band_low(+_display)`, `band_high(+_display)`, `current_price(+_display)`, `distance_str`, `status`, and the new `started_at` on the active payload. (See Assumptions Log A2.)

**Resolved-stages table** (`templates/staged.html:29-69`, verified) column set: `Account, Symbol, Direction, Stage, Status (status_label), Reason (cancelled_reason), Time`. The `status_label` map lives in `dashboard.py:489` (`_RESOLVED_STATUS_LABELS`) — the API does NOT currently apply it (`api/stages.py._enrich_resolved` only adds timestamp twins). **The SPA must either (a) replicate the label map client-side, or (b) the widening adds `status_label` server-side.** Recommend client-side map (it is pure presentation strings, not money/price). Resolved rows already carry `created_at`/`filled_at` machine + `_display` (verified `_enrich_resolved`).

## Architecture Patterns

### System Architecture Diagram

```
 Browser (/app/* SPA)
   │
   │  react-router useSearchParams  ──┐  (?range=&source=  |  account/source/symbol/from_date/to_date)
   │                                  │   URL = source of truth for filter state (D-02/D-05)
   ▼                                  ▼
 useUrlFilters() ──────────► queryKey = ['analytics', {range,source}]  (or ['history', {...}])
   │                                  │
   ▼                                  ▼
 TanStack useQuery (inherited QueryClient: placeholderData=keepPreviousData, staleTime 1000, retry false)
   │                                  │
   │  staged ONLY: refetchInterval ~3000   others: no interval + refetchOnWindowFocus + manual Refresh (D-03/D-04/D-07)
   ▼                                  ▼
 api('/api/v2/<route>?...')  ──HTTP (same-origin, session cookie)──►  FastAPI /api/v2
   │                                                                     │
   │  query states:                                                      ├─ analytics.py  (D-01 widening)
   │   isPending → <Loading/>  (skeleton)                                ├─ signals.py    (parity widening)
   │   isError   → <ErrorPanel onRetry={refetch}/>  (D-11 inline)        ├─ history.py    (parity widening)
   │   data.length===0 → <Empty/>                                        └─ stages.py     (D-09 widening)
   │   success → render                                                       │
   ▼                                                                          ▼
 <DataTable columns rows/>  (signals, history, resolved, by-source)     db.* read helpers (UNCHANGED queries)
 <StageCard/> per active stage  +  useElapsed(started_at) ticking timer       │
   │  renders ONLY *_display strings (Pitfall 5) — never .toFixed()           ▼
   ▼                                                                    PostgreSQL (read-only)
 server-formatted numbers === legacy numbers  → golden-number parity (SC#5)
```

The reader can trace the analytics primary case: URL `?range=30d` → `useUrlFilters` → query key → `api('/api/v2/analytics?range=30')` → server aggregates + formats `_display` → DataTable renders the by-source rows verbatim → operator clicks a row → URL becomes `?range=30d&source=X` → re-query.

### Recommended Project Structure (NEW files this phase)

```
frontend/src/
├── components/
│   ├── data/
│   │   └── DataTable.tsx          # D-10 shared table (sticky header, align, mono, color-by-sign)
│   └── state/
│       ├── Loading.tsx            # skeleton rows (uses shadcn skeleton)
│       ├── Empty.tsx              # empty-state panel (icon + copy)
│       └── ErrorPanel.tsx         # D-11 inline error + Retry button
├── lib/
│   ├── useUrlFilters.ts           # D-02/D-05 single useSearchParams-backed helper
│   └── useElapsed.ts              # D-06 per-second ticking timer off a server ISO epoch
└── routes/
    ├── AnalyticsView.tsx          # PAGE-01 pilot (range tabs + KPIs + by-source DataTable)
    ├── SignalsView.tsx            # PAGE-02
    ├── HistoryView.tsx            # PAGE-03 (filter bar + DataTable)
    └── StagedView.tsx             # PAGE-04 (StageCard per account + resolved DataTable)
```

Wire each into `frontend/src/routes/router.tsx` as children of `App` (the boot guard), and flip the corresponding `Sidebar.FUTURE_LINKS` entry from a disabled `<span>` to an active `<NavLink>` (the labels already match: Trade History / Signal Log / Analytics / Pending Stages). The `ProbeView` is throwaway and is replaced by the real Overview landing in Phase 11 — leave the index route alone or swap to Analytics as the landing per the planner's call.

### Pattern 1: One URL-filter-sync helper (D-02/D-05)

**What:** A `useUrlFilters` hook wrapping react-router 7 `useSearchParams`; reads the typed filter object, writes it back to the URL (replacing history entry on filter change, pushing on explicit navigation like a by-source row click). The query key derives directly from the filter object so a URL change re-queries automatically.

**When to use:** Analytics (`range`, `source`) and History (`account`, `source`, `symbol`, `from_date`, `to_date`). Same helper, different param schema.

```typescript
// frontend/src/lib/useUrlFilters.ts  — Source: react-router 7 useSearchParams + TanStack v5 key-derivation
import { useSearchParams } from "react-router-dom";

export function useUrlFilters<T extends Record<string, string>>(keys: readonly (keyof T & string)[]) {
  const [params, setParams] = useSearchParams();
  const filters = Object.fromEntries(keys.map((k) => [k, params.get(k) ?? ""])) as T;
  const setFilter = (patch: Partial<T>, opts?: { push?: boolean }) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v as string); else next.delete(k);
    }
    setParams(next, { replace: !opts?.push }); // replace on filter edit; push on row-click navigation
  };
  return { filters, setFilter };
}
// queryKey: ['analytics', filters]  → key changes when URL changes → auto refetch, keepPreviousData prevents flicker
```

### Pattern 2: Per-second ticking elapsed timer (D-06) — Pitfall-5-safe

**What:** A `useElapsed(startedAtIso)` hook that sets a 1s interval and returns a formatted `MM:SS` / `HH:MM:SS` duration computed as `now - new Date(startedAtIso)`. The epoch is server-supplied (`started_at` from the D-09 widening); only the *relative duration* is computed client-side.

**Why it does NOT violate Pitfall 5:** Pitfall 5 bans the SPA re-deriving server **money/price precision** (the XAUUSD pip class of bug). A wall-clock duration is neither money nor price — it has no broker-precision semantics; it is a UI affordance over a server timestamp. The server still owns the epoch; the client merely animates the delta. The CONTEXT.md locks this reading (D-06).

```typescript
// frontend/src/lib/useElapsed.ts — Source: standard setInterval pattern; epoch from server ISO (D-09)
import { useEffect, useState } from "react";
export function useElapsed(startedAtIso: string): string {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const secs = Math.max(0, Math.floor((now - Date.parse(startedAtIso)) / 1000));
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`
    : `${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`;
}
```
**Discretion (D):** a single shared hook is fine; one interval per card is acceptable for the small number of active stages. A single page-level interval broadcasting `now` via context is a micro-optimization not worth the complexity for a single-operator tool.

### Pattern 3: Polling strategy maps cleanly onto inherited defaults (D-03/D-07)

**Verified against `frontend/src/lib/queryClient.ts`:** the QueryClient already sets `placeholderData: keepPreviousData`, `refetchIntervalInBackground: false`, `staleTime: 1000`, `retry: false`. Per-query needs:

- **Staged:** add `refetchInterval: 3000` on its `useQuery` (D-07). Background polling auto-pauses on a hidden tab (inherited `refetchIntervalInBackground:false`). [VERIFIED: queryClient.ts]
- **Analytics / Signals / History:** add nothing for polling. Add `refetchOnWindowFocus: true` per-query if D-03's window-focus refetch is wanted (note: TanStack's default is already `true`, so this may be implicit — verify the project hasn't globally disabled it; queryClient.ts does NOT set `refetchOnWindowFocus`, so the v5 default `true` applies). Manual Refresh (D-04) = a button calling `refetch()`. [VERIFIED: TanStack v5 default refetchOnWindowFocus=true]
- **`keepPreviousData`** is already global → flicker-free filter/range changes for free on all pages (D-03/D-05). [VERIFIED: queryClient.ts + TanStack v5 migration: `placeholderData: keepPreviousData` IS the v5 replacement for the removed `keepPreviousData: true`]

### Pattern 4: Inline error panel, not toast (D-11)

**What:** On `isError`, render `<ErrorPanel message={...} onRetry={refetch}/>` in the page body. A failed read leaves a visible, retryable failure state — not a flashed toast over an empty body. `401` never reaches this panel because the inherited global `onAuthError` (queryClient.ts) hard-navigates to `/app/login?expired=1` first. Use the `HttpError.status`/`HttpError.body` (the `{error:{code,message}}` envelope) for the message; fall back to a generic string. Toasts (sonner) stay reserved for *action* feedback (Phase 11 mutations + the Phase-9 logout failure).

### Anti-Patterns to Avoid

- **Client `.toFixed()` on money/price.** Always render the server `_display` string (Pitfall 5). The ONLY client number computation allowed is the elapsed *duration* (D-06).
- **Background-polling analytics/signals/history.** D-03 forbids it; legacy never polled them. Only staged gets `refetchInterval`.
- **Storing filter state in React state instead of the URL.** D-02/D-05 lock the URL as source of truth (bookmarkable). React state would break deep-links and the by-source-row→`?source=` navigation.
- **Introducing SSE/WebSocket for staged.** ARCHITECTURE §4 anti-pattern 5 + D-07: polling only. The legacy `/stream` SSE is Phase-12 teardown, not Phase-10 surface.
- **Adding `@tanstack/react-table` or a query-string lib.** Not installed; not needed; violates the "keep lean" Phase-9 D-11 discipline.
- **Replicating the legacy staged field-name bug.** Render correct `filled`/`total` from the enriched dict's real keys.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Number/money/time formatting | A JS formatter in the SPA | Server `_display` strings via `api/formatting.py` | Pitfall 5; single source of precision truth; XAUUSD already bit this project |
| Filter↔URL sync | A bespoke history-pushState layer | react-router 7 `useSearchParams` | Already installed; handles encoding, back/forward |
| Flicker-free refetch | Manual "keep old rows while loading" | Inherited `placeholderData: keepPreviousData` | Already global in queryClient.ts (v5-correct) |
| Background-poll pause on hidden tab | `visibilitychange` listener | Inherited `refetchIntervalInBackground: false` | Already global |
| 401 redirect | Per-page 401 handling | Inherited global `onAuthError` | Already wired on QueryCache + MutationCache |
| Loading skeletons | Per-page ad-hoc spinners | The shared `Loading` trio component (D-10) | Phase 11 inherits; consistency |

**Key insight:** Almost everything hard about these pages is already solved by the Phase-8 server contract and the Phase-9 QueryClient/http/router. Phase 10's real work is (a) the four small read-only schema widenings, (b) the three shared SPA primitives, and (c) wiring four thin page components. Resist re-solving formatting, polling, auth, or URL state.

## Common Pitfalls

### Pitfall 1: Schema drops fields the legacy page renders (the silent parity killer)
**What goes wrong:** Building the SPA page straight off the shipped `Signal`/`HistoryTrade` schemas yields a page MISSING legacy columns (signals: Zone/SL/TP/Details; history: SL/TP/Status/Source), and parity verification fails late.
**Why it happens:** Phase 8 schemas were summary-shaped; no SPA consumed them, so the gaps were invisible.
**How to avoid:** Treat the signals + history schema widenings as first-class backend tasks (same category as D-01/D-09). Diff each legacy template's rendered fields against the schema BEFORE building the page.
**Warning signs:** A column in the legacy template has no corresponding schema field.

### Pitfall 2: Re-deriving money precision client-side
**What goes wrong:** SPA shows `1234.5` where legacy shows `1,234.50`, or XAUUSD price at wrong dp.
**Why it happens:** Pulling the raw numeric and `.toFixed()`-ing it instead of the `_display` twin.
**How to avoid:** Render `_display` only. The raw numeric is for sorting/logic, never display.
**Warning signs:** Any `.toFixed`, `Intl.NumberFormat`, or template-literal numeric formatting in a page/table cell.

### Pitfall 3: `avg_stages` assumed always present
**What goes wrong:** SPA renders an Avg-Stages card showing `null`/`0` on the all-sources view.
**Why it happens:** `db` only computes `avg_stages` when `source_name` is set (verified `db.py:745-762`).
**How to avoid:** Render the card only when a source filter is active (mirror legacy `{% if avg_stages %}`).

### Pitfall 4: Staged timestamp lost in the enrichment chain
**What goes wrong:** The D-09 widening adds `started_at` but it comes out `None` because `_enrich_stage_for_ui` already dropped `created_at` before `_enrich_active` runs.
**Why it happens:** The enriched dict (input to `_enrich_active`) does not carry `created_at`; only the raw `get_pending_stages()` row does.
**How to avoid:** Source `started_at` from the RAW stage row (zip raw+enriched, or pass both), not from the enriched dict.
**Warning signs:** `started_at` serializes to null while `elapsed` (computed from the same `created_at`) is populated.

### Pitfall 5: Window-focus refetch assumption
**What goes wrong:** D-03 expects analytics/signals/history to `refetchOnWindowFocus`, but a future global change disables it.
**Why it happens:** `queryClient.ts` does not explicitly set `refetchOnWindowFocus` (relies on v5 default `true`).
**How to avoid:** Either rely on the verified v5 default or set it explicitly per-query for the three snapshot pages. Verify behavior in the parity check.

## Code Examples

### DataTable column-driven API (D-10) — hand-rolled, no react-table
```tsx
// frontend/src/components/data/DataTable.tsx — column-driven, renders _display strings, color-by-sign
type Align = "left" | "right";
export interface Column<Row> {
  header: string;
  cell: (row: Row) => React.ReactNode;   // caller passes the _display string here
  align?: Align;                          // numerics → "right"
  mono?: boolean;                         // tabular numerics
  sign?: (row: Row) => number;            // optional: color cell green/red by sign of this value
}
export function DataTable<Row>({ columns, rows }: { columns: Column<Row>[]; rows: Row[] }) {
  return (
    <div className="rounded-lg border bg-card overflow-x-auto">
      <table className="w-full text-sm">
        <thead><tr className="border-b bg-muted/50 sticky top-0">
          {columns.map((c) => (
            <th key={c.header} className={`px-4 py-3 font-medium text-muted-foreground ${c.align==="right"?"text-right":"text-left"}`}>{c.header}</th>
          ))}
        </tr></thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b hover:bg-muted/30">
              {columns.map((c) => {
                const s = c.sign?.(row);
                const tone = s===undefined ? "" : s>0 ? "text-green-400" : s<0 ? "text-red-400" : "";
                return <td key={c.header} className={`px-4 py-3 ${c.mono?"font-mono":""} ${c.align==="right"?"text-right":""} ${tone}`}>{c.cell(row)}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

### Staged: card-per-account + ticking elapsed (D-06/D-08)
```tsx
// inside StagedView — active stages render as cards; resolved render in <DataTable/>
function StageCard({ s }: { s: ActiveStage }) {
  const elapsed = useElapsed(s.started_at);   // server epoch from D-09 widening
  return (
    <div className="rounded-lg border bg-card p-4">
      {/* symbol + BUY/SELL badge + account */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        <Field label="Stages">{s.filled}/{s.total}</Field>
        <Field label="Target Band"><span className="font-mono">{s.band_low_display} – {s.band_high_display}</span></Field>
        <Field label="Current Price"><span className="font-mono">{s.current_price_display ?? "—"}</span></Field>
        <Field label="Elapsed"><span className="font-mono">{elapsed}</span></Field>
      </div>
    </div>
  );
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `keepPreviousData: true` | `placeholderData: keepPreviousData` (imported fn) | TanStack Query v5 | Already adopted in queryClient.ts — no action; do NOT reintroduce the v4 option |
| `refetchInterval: (data, query) => ...` | `refetchInterval: (query) => ...` (no data arg) | TanStack Query v5 | Staged uses a constant `3000`, so unaffected; relevant only if a dynamic interval is added |
| HTMX `hx-get` + `hx-push-url` for filters | react-router `useSearchParams` URL sync | This phase | Same UX (bookmarkable filters), client-owned |
| SSE `/stream` + `hx-trigger every 5s` for staged | TanStack `refetchInterval: 3000` polling | This phase | SSE teardown deferred to Phase 12; SPA never connects to `/stream` |

**Deprecated/outdated:**
- `keepPreviousData` as a boolean option — removed in v5 (project already migrated). [CITED: tanstack.com migrating-to-v5]

## Runtime State Inventory

Not a rename/refactor/migration phase — greenfield SPA pages + additive serialization. Omitted per the research format (no stored-data/service-config/OS-state/secret/build-artifact renames involved). The API widenings are additive fields only; no existing data key, collection, or env var changes.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The operator wants the legacy History SL/TP/Status/Source columns at parity (schema currently omits SL/TP/Status; query returns source/status) | §"History parity note" | If not wanted, the history widening is smaller; if wanted and skipped, PAGE-03 fails parity. Confirm in discuss/plan. |
| A2 | "Parity" for staged means rendering the *correct* `filled`/`total` (not replicating the legacy template's blank-cell field-name bug) | §"Staged active field-name reconciliation" | If bug-for-bug parity is required, the SPA should leave the cell blank — unlikely but worth confirming. |
| A3 | Keeping `win_rate`/`profit_factor` raw (no `_display` twin) and formatting them client-side as percentages/ratios is acceptable (matches the shipped summary route; they are not money/price) | §"Analytics widening" | If the operator wants ALL numbers server-formatted, add `_display` twins for these too. Low risk — mirrors existing convention. |

## Open Questions

1. **Should the four legacy routes' decimal formatting for prices be reproduced exactly?**
   - What we know: legacy uses `"%.2f"` literally for band/entry/price cells; the API `price_display` uses `_SYMBOL_DIGITS` (XAUUSD=2, default 5). For XAUUSD these agree; for a 5-dp FX symbol the API would show 5dp where legacy hard-coded 2dp.
   - What's unclear: whether any non-XAUUSD symbol appears in staged/history live data (the bot is gold-focused).
   - Recommendation: render the API `_display` (correct per-symbol precision); if a parity diff appears on a 5-dp symbol, it is the *legacy* that was wrong (the XAUUSD pip bug class). Note in the parity check.

2. **Landing route after analytics ships:** keep `ProbeView`/Overview as index, or make Analytics the index?
   - Recommendation: leave the index alone (Overview is Phase 11); add the four pages at their own paths and enable the Sidebar links. Planner's call.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node/npm (dev + Docker build stage) | Vite build of new pages | ✓ (Phase 9 Dockerfile node:22-slim build stage; local dev) | node 22 | — |
| shadcn CLI (`npx shadcn@latest add ...`) | Generating tabs/select/table/skeleton/badge component source | ✓ (used in Phase 9) | latest | hand-author the component (radix-ui already installed) |
| Running FastAPI `/api/v2` (dev proxy → :8090) | Live data for the pages + parity checks | ✓ (Phase 8 shipped; Phase 9 dev proxy) | — | — |
| Postgres with live trade/signal/stage data | Golden-number parity vs legacy | ✓ on VPS / dev DB | — | parity check needs non-empty data; empty DB → verify empty-state instead |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** shadcn CLI — every component can be hand-authored over the installed `radix-ui` umbrella if the CLI is unavailable. Per Memory: local dashboard/SPA verification should run the SPA standalone (not the full `bot.py`) to avoid a Telegram session conflict; tests need a Python 3.12 container.

## Validation Architecture

> nyquist_validation is `true` in `.planning/config.json` — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework (backend) | pytest (existing `tests/` suite; Phase 8 added contract tests e.g. `test_*contract*`) |
| Framework (frontend) | None detected — no vitest/jest config in `frontend/`; no `test` script in `frontend/package.json` |
| Config file (backend) | repo `pytest`/conftest (existing); run inside Python 3.12 container per Memory |
| Quick run command | `pytest tests/test_api_read_endpoints* -x` (extend the Phase-8 read-contract test) |
| Full suite command | `pytest -q` (in the 3.12 container) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PAGE-01 | `/api/v2/analytics` returns `by_source[]` with `net_pnl_display`, `extremes`, `sources`, `avg_stages` | contract (pytest) | `pytest tests/test_analytics_contract.py -x` | ❌ Wave 0 |
| PAGE-01 | by-source money `_display` matches `money_display(net_pnl)`; win_rate/PF stay raw | contract | same file | ❌ Wave 0 |
| PAGE-02 | `/api/v2/signals` surfaces `entry_zone_low/high`, `sl(+_display)`, `tp(+_display)`, `details` | contract | `pytest tests/test_signals_contract.py -x` | ❌ Wave 0 (extend existing) |
| PAGE-03 | `/api/v2/history` round-trips all 5 filter params (AND logic) and surfaces sl/tp/status/source if added | contract | `pytest tests/test_history_contract.py -x` | ⚠️ partial (Phase 8 test exists; extend) |
| PAGE-04 | `/api/v2/stages` active rows carry `started_at` (ISO-8601 + offset) sourced from the raw `created_at` | contract | `pytest tests/test_stages_contract.py -x` | ❌ Wave 0 |
| PAGE-01..04 | SPA renders only `_display` strings (no client re-rounding) | manual + grep guard | `grep -rn "toFixed\|Intl.NumberFormat" frontend/src/routes frontend/src/components/data` (expect none in cells) | guard |
| PAGE-03 | Filter state survives a URL deep-link reload (bookmarkable) | manual (parity gate) | load `/app/history?account=X&symbol=Y`, reload, filters intact | manual |
| PAGE-04 | Elapsed ticks per-second between 3s polls; epoch is the server `started_at` | manual (parity gate) | observe a card ≥10s; elapsed increments smoothly, not in 3s jumps | manual |
| PAGE-01..04 (SC#5) | SPA numbers === live legacy numbers | golden-number parity | capture both pages on the same DB snapshot; compare displayed values field-by-field | manual gate |

### Sampling Rate
- **Per task commit:** the relevant `pytest tests/test_<route>_contract.py -x` (backend widenings) + `cd frontend && npm run build` (type-check + bundle).
- **Per wave merge:** full `pytest -q` (3.12 container) + `npm run build` + the `toFixed`/`Intl` grep guard.
- **Phase gate:** all contract tests green + the four golden-number parity checks pass against the live legacy twin (SC#5).

### Wave 0 Gaps
- [ ] `tests/test_analytics_contract.py` — covers PAGE-01 (by_source/_display/extremes/sources/avg_stages-only-when-source)
- [ ] `tests/test_signals_contract.py` — covers PAGE-02 (the widened fields exist + price `_display`)
- [ ] `tests/test_stages_contract.py` — covers PAGE-04 (`started_at` present + ISO + survives the enrichment chain — Pitfall 4)
- [ ] Extend the existing Phase-8 history contract test for PAGE-03 widened columns (if A1 confirmed)
- [ ] No frontend test runner exists — frontend validation is via `npm run build` (type-check) + manual parity gates; if the planner wants component tests, vitest install is a Wave-0 prerequisite (NEW dep — would require the Package Legitimacy Gate). Recommend NOT adding it this phase; rely on the type-check + parity gates, consistent with the single-operator-tool discipline.

## Security Domain

> `security_enforcement` is absent from config (`null`) → treated as enabled. This is a read-only phase; the surface is narrow.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (inherited) | httpOnly session cookie; every `/api/v2` read is `Depends(require_user)` (verified in each route); SPA boot guard + global 401 redirect (Phase 9) |
| V3 Session Management | yes (inherited) | `telebot_session` httpOnly cookie; no token in localStorage (Phase 9 SPA-03) |
| V4 Access Control | yes | All four read routes session-gated server-side; no client-trusted auth (Phase 9 T-09-10) |
| V5 Input Validation | yes | Filter params are query strings; `get_filtered_trades` uses **parameterized asyncpg queries** ($1..$n) — verified `db.py:526-568`. NOTE: `get_analytics_with_filters` interpolates `range_days` via `int(range_days)` (coerced to int — safe) and `int(limit)` similarly; `source_name` IS parameterized. The SPA must pass only the known filter keys. |
| V6 Cryptography | no (no new crypto) | — |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via filter params | Tampering | Parameterized asyncpg ($n) for string params; `int()` coercion for numeric interpolation (both verified in `db.py`) — read-only routes add NO new query construction |
| Reflected XSS via raw_text/details in signals | Tampering/Info | React escapes by default; render `details`/`raw_text` as text children, NEVER `dangerouslySetInnerHTML` |
| Session fixation / token theft | Spoofing | httpOnly cookie (inherited); SPA never reads it; no localStorage token |
| CSRF | Tampering | Not applicable to GET reads (no mutations this phase); the double-submit machinery is inherited but unused by read pages |

**Key security note for the planner:** because this phase is GET-only, no CSRF token is needed on its requests (the http wrapper only attaches `X-CSRF-Token` on POST/PUT/PATCH/DELETE — verified `frontend/src/lib/http.ts`). Do not add mutation surface; that is Phase 11.

## Sources

### Primary (HIGH confidence — read from the live codebase 2026-06-06)
- `api/analytics.py`, `api/schemas.py`, `api/formatting.py`, `api/stages.py`, `api/history.py`, `api/signals.py` — shipped Phase-8 read contract
- `db.py` (get_analytics_with_filters:647, get_analytics_sources:786, get_filtered_trades:500, get_pending_stages:1057, get_recently_resolved_stages:1144, signals DDL:82) — query shapes
- `dashboard.py` (_enrich_stage_for_ui:500, _RESOLVED_STATUS_LABELS:489, staged_page:589) — legacy enrichment + status labels
- `templates/{analytics.html, partials/analytics_table.html, signals.html, history.html, partials/history_table.html, staged.html, partials/pending_stages.html}` — parity column sets + field references
- `frontend/src/lib/{http.ts, queryClient.ts}`, `frontend/src/routes/router.tsx`, `frontend/src/components/shell/{AppShell,Sidebar}.tsx`, `frontend/src/App.tsx`, `frontend/package.json` — inherited Phase-9 conventions + installed deps
- `.planning/phases/10-.../10-CONTEXT.md` (D-01..D-11), `.planning/REQUIREMENTS.md` (PAGE-01..04), `.planning/ROADMAP.md` (Phase 10 SC), `.planning/STATE.md` (Pitfalls), `.planning/research/ARCHITECTURE.md` §4

### Secondary (MEDIUM confidence — verified against official docs)
- TanStack Query v5 migration: `keepPreviousData` removed → `placeholderData: keepPreviousData`; `refetchInterval` signature drops the data arg — [CITED: tanstack.com/query/latest/docs/framework/react/guides/migrating-to-v5] (confirms the inherited queryClient.ts pattern is current)

### Tertiary (LOW confidence)
- None — every claim is grounded in source or official docs.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — read directly from `frontend/package.json`; nothing new added.
- API widening shapes (D-01/D-09 + the 3 latent gaps): HIGH — read the db queries, the schemas, and the templates side by side.
- Architecture/patterns: HIGH — grounded in the inherited Phase-9 files; TanStack v5 pattern confirmed against official migration docs.
- Pitfalls: HIGH — Pitfalls 1, 3, 4, 5 are codebase-verified facts (schema gaps, avg_stages conditionality, the enrichment-chain timestamp drop, the field-name mismatch).
- Operator-intent assumptions (A1/A2/A3): MEDIUM — flagged for confirmation in the Assumptions Log.

**Research date:** 2026-06-06
**Valid until:** 2026-07-06 (stable — internal codebase facts; TanStack v5 is the locked version)
