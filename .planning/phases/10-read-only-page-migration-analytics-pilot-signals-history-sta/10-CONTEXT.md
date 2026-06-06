# Phase 10: Read-only Page Migration (analytics pilot → signals → history → staged) - Context

**Gathered:** 2026-06-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Bring the **four no-live-money pages** to SPA parity, in ascending pipeline-validation
order — **analytics** first as the read-only pilot that proves the full
API + SPA + auth + nginx stack end-to-end, then **signals**, **history** (with
URL-bookmarkable filters), then **staged-entries** (live polling + elapsed-time).
Each page is verified equal to its **live legacy twin** before that legacy route is
eligible for Phase-12 decommission. These pages slot into the ready routes/shell
Phase 9 built (`Sidebar` FUTURE_LINKS enabled in place; labels already mirror legacy:
Trade History / Signal Log / Analytics / Pending Stages).

In scope (PAGE-01..PAGE-04):
1. **Analytics page** — full legacy parity: range tabs, summary KPIs (win rate,
   profit factor, gross P/L, best/worst extremes), the **Performance-by-Source**
   deep-dive table, avg-stages-filled, and a source filter.
2. **Signals page** — parity with the legacy Signal Log.
3. **History page** — parity incl. all trade-history filters, with filter state in
   the URL (bookmarkable) and `keepPreviousData` preventing refetch flicker.
4. **Staged-entries page** — parity: pending stages per account, live polling,
   elapsed-time display.
5. Per-page parity verification against the **live** legacy page before cutover
   readiness (cutover risk is read-only — no live-money action on any of these four).

**Read-only API widenings allowed in this phase** (presentation-layer-safe — no
live-money path, bot core untouched): two reads need enrichment to reach parity —
see D-01 (analytics) and D-09 (staged start-timestamp). These are extensions of
already-shipped Phase-8 read routes, not new mutation surface.

**Out of this phase (hard boundary):**
- ANY live-money page (overview, positions, kill switch) or settings → Phase 11.
- ANY mutation / optimistic-update / CSRF-on-write discipline → Phase 11.
- Removing legacy HTMX routes / SSE `/stream` / legacy Tailwind-CLI stage → Phase 12.
  Legacy dashboard keeps running at `/` in parallel throughout Phase 10.
- ANY change to the bot core (`executor.py`, `trade_manager.py`, `db.py` write
  paths, `mt5_connector.py`, MT5 bridge). The analytics/stages read widenings touch
  only API serialization + read-only db read helpers.

</domain>

<decisions>
## Implementation Decisions

### Analytics page (the pilot)
- **D-01:** **Extend `/api/v2/analytics` to full legacy parity** (read-only). The
  `db.get_analytics_with_filters()` already returns `by_source[]`, `extremes`
  (best/worst), and `avg_stages`; the endpoint also `await`s
  `db.get_analytics_sources()` and **discards** it. Widen the `Analytics` schema +
  route to surface `by_source[]` (per-source: trades, W/L, win_rate, profit_factor,
  net_pnl + `_display`, best/worst), `extremes`, `avg_stages`, and the `sources`
  list — single round-trip, mirrors legacy 1:1. Chosen over a separate
  `/analytics/by-source` endpoint (fewer round-trips, less surface for a single-operator
  tool) and over trimming SPA scope (that would fail SC#1 "per-source deep-dive").
  Money/number fields follow the Phase-8 dual-value `*_display` rule — SPA renders
  `_display`, never re-rounds (Pitfall 5).
- **D-02:** **Analytics filter state lives in the URL** (`?range=&source=`),
  bookmarkable/shareable — the **same URL-sync convention as history (D-05)**, one
  shared helper across both pages. **Default load = all-time, no source filter**
  (matches legacy `current_range`/`current_source` empty defaults). Clicking a row in
  the Performance-by-Source table sets `?source=<name>` (re-query), mirroring the
  legacy clickable-rows behavior.

### Data freshness / polling (per-page, within the inherited D-09 frame)
- **D-03:** **Only the staged page polls.** Staged-entries is the in-flight live view
  and gets a background `refetchInterval`. **Analytics, signals, and history do NOT
  background-poll** — they fetch-on-mount + `refetchOnWindowFocus`, matching legacy
  (those pages were never live-polled; they refetched only on user action). This
  keeps DB load minimal and is truest to current behavior. `keepPreviousData` still
  prevents flicker on filter/range changes.
- **D-04:** **Snapshot pages (analytics/signals/history) carry a manual Refresh
  control**, since they don't poll — the operator can force a refetch without leaving
  and returning to the tab.

### History page
- **D-05:** **Filter state in the URL** (bookmarkable) per SC#3, with
  `keepPreviousData` preventing flicker on refetch. Filters come from the shipped
  `GET /api/v2/history/filter-options` (accounts, symbols, sources; `directions` is
  schema-declared but returns empty — not stored as a distinct filter). Filter params
  map to the shipped `GET /api/v2/history` query params: `account`, `source`,
  `symbol`, `from_date`, `to_date`. (Same URL-sync helper as analytics D-02.)

### Staged-entries page
- **D-06:** **Elapsed-time is a client-side ticking timer** derived from a server
  start-timestamp (ISO/UTC), counting up smoothly per-second between polls. This is a
  relative-duration-off-a-server-epoch, NOT the re-rounding of server money/prices that
  Pitfall 5 bans — so it's consistent with server-side-formatting discipline.
- **D-07:** **Staged data polls every ~3s** via TanStack Query (the page's
  `refetchInterval`); the stage list/status comes from polling, only the elapsed
  duration ticks client-side. (Legacy ran SSE + a 2-5s `hx-trigger` fallback; the SPA
  uses polling only — no SSE/WebSocket per v1.2 research §4 / anti-pattern 5.)
- **D-08:** **Staged-active renders as card-per-account** (the legacy
  `partials/pending_stages.html` shape); the **recently-resolved** list renders in the
  shared table (D-10). The `/stages` route already returns `{active[], resolved[]}`.
- **D-09:** **Read-only enrichment needed:** the `/api/v2/stages` **active** payload
  must surface a **machine start-timestamp (ISO/UTC)** so the D-06 client timer has an
  epoch to count from. Legacy only emits a server-formatted `s.elapsed` string
  (`templates/partials/pending_stages.html:33`) — there is no machine timestamp on
  active stages today. This is the same read-only-widening category as D-01 (extend
  `_enrich_active` / the active-stage shape; resolved rows already carry
  `created_at`/`filled_at` machine + `_display` twins).

### Shared scaffolding (Phase 11 inherits these — SC "shared list/table patterns")
- **D-10:** **Build shared primitives during the pilot:** one reusable **`DataTable`**
  (sticky header, column alignment, mono numerics, color-by-sign for P&L) + a standard
  **`Loading` (skeleton) / `Empty` / `Error`** state trio that every page composes.
  Tables: signals, history, recently-resolved stages, and the analytics
  Performance-by-Source table. Cards: staged-active (D-08). Proven on the pilot, then
  inherited by Phase 11 positions/history. Chosen over extract-after-2nd-page and
  per-page-bespoke because the SC explicitly says Phase 11 inherits these patterns.
- **D-11:** **Error state = inline panel** (message + Retry button) rendered in the
  page body, **not** a transient toast — a read-only page that failed to load should
  show its own failure state, not flash and leave an empty body. (Differs from the
  Phase-9 logout-failure toast, which is an action-feedback case.) `401` is still
  handled by the inherited global `onAuthError` redirect (D-06 of Phase 9) — unchanged.

### Parity scope (resolved post-research — 2026-06-06)
- **D-12:** **Signals + History read schemas need parity widening too** (read-only,
  same category as D-01/D-09). Research found the shipped Phase-8 schemas silently drop
  fields the legacy templates render: `Signal` drops `entry_zone_low/high`, `sl`, `tp`,
  `details`, `source_name`; `HistoryTrade` drops `sl`, `tp`, `status`, `source_name`
  (the underlying `db` queries already return all of these). **Widen both read schemas +
  routes to full legacy parity** so PAGE-02 (signals) and PAGE-03 (history) actually
  match their legacy templates. Operator-confirmed: full legacy parity, not shipped-field
  subset. Follow the Phase-8 dual-value `*_display` rule for money/price fields.
- **D-13:** **Staged page renders the CORRECT values, not the legacy blank-cell bug.**
  Research found a pre-existing legacy bug: `partials/pending_stages.html` references
  `filled_count`/`total_stages`/`distance_to_band` while the enriched dict emits
  `filled`/`total`/`distance_str`, so the live legacy staged page renders BLANK cells
  there. The SPA must surface the real `filled`/`total`/`distance` values. For SC#5
  parity verification, this legacy blank-cell bug is a **documented parity exception**
  (SPA is correct, legacy is buggy) — do NOT replicate the blanks. Operator-confirmed.
- **D-14:** **`win_rate` / `profit_factor` stay raw numeric** (no `_display` twin),
  client-formatted as ratios/percentages — mirroring the already-shipped summary route.
  D-01's dual-value `*_display` rule applies to **money/price** fields (gross P/L,
  net_pnl, best/worst extremes), not these ratio metrics. (Researcher recommendation A3,
  accepted as the discretion default.)

### Claude's Discretion (planner/researcher decides)
- Exact column sets / ordering for each table (signals, history, resolved-stages,
  by-source) — match the legacy templates as the parity reference.
- Exact `DataTable` API surface (props, sorting if any) and where shared
  components/hooks live in `frontend/src`.
- Exact `staleTime`/`refetchInterval` numbers within the D-03/D-07 frame (staged ~3s
  is the target; others = no interval).
- Which shadcn components each page pulls in via the CLI (per D-11 of Phase 9 — add
  per-page, keep lean).
- The precise shape of the analytics schema widening (field names for `by_source`
  rows, `extremes`, `sources`) — follow the Phase-8 dual-value `*_display` convention.
- The precise field name for the staged active start-timestamp (e.g. `created_at` ISO)
  and its `_display` twin if useful.
- Client ticking-timer implementation detail (shared `useElapsed` hook vs per-card).
- Parity-verification mechanics (side-by-side vs golden-number capture) against the
  live legacy page.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & milestone scope
- `.planning/REQUIREMENTS.md` §PAGE — PAGE-01..PAGE-04 (the four read-only pages this
  phase delivers) and any page-parity acceptance notes.
- `.planning/ROADMAP.md` Phase 10 — goal + 5 success criteria + UI hint (analytics
  pilot ordering; per-page parity-before-cutover gate).
- `.planning/PROJECT.md` §Current Milestone (v1.2) + §Key Decisions — locked stack
  (React 19 · Vite · shadcn/ui · Tailwind v4), presentation-layer-only blast radius,
  parallel-run + page-by-page reversible cutover.
- `.planning/STATE.md` §Blockers/Concerns — Pitfall 1 (no optimistic updates — a
  Phase-11 concern, but the read-only discipline holds), Pitfall 5 (server-side
  number/time formatting — SPA reads `*_display`, submits bare numeric; relevant to the
  analytics money fields and the staged elapsed timer's epoch source).

### v1.2 research synthesis (primary design source)
- `.planning/research/ARCHITECTURE.md` §4 (Live data transport — keep polling,
  TanStack Query `refetchInterval` + `refetchIntervalInBackground:false` +
  `keepPreviousData`; no WebSocket/SSE), §"Anti-Patterns to Avoid" (5 = no WebSocket).
- `.planning/research/PITFALLS.md` — Pitfall 5 (server-side formatting), Pitfall 1
  (no optimistic updates).
- `.planning/research/STACK.md` / `FEATURES.md` / `SUMMARY.md` — page-migration feature
  breakdown + locked stack.

### Phase 8 read contract this phase consumes / extends (read-only)
- `.planning/phases/08-json-api-foundation/08-CONTEXT.md` — D-05 dual-value `*_display`
  fields (render `_display`, submit bare), D-06/D-07 ISO+UTC timestamps, the read-route
  envelopes. The analytics (D-01) and staged (D-09) widenings MUST follow these
  conventions.
- `api/analytics.py`, `api/schemas.py` (`Analytics`) — the summary-only schema to widen
  (D-01); `db.get_analytics_with_filters()` already returns `by_source`/`extremes`/
  `avg_stages`, and `db.get_analytics_sources()` exists.
- `api/history.py` — `GET /history` (`account/source/symbol/from_date/to_date`) +
  `GET /history/filter-options` (already complete; back D-05).
- `api/signals.py` — `GET /signals` (`list[Signal]`; already complete).
- `api/stages.py` — `GET /stages` returns `{active[], resolved[]}`; `_enrich_active`
  is where the D-09 machine start-timestamp gets added. `_enrich_stage_for_ui` lives at
  `dashboard.py:456`.

### Legacy parity references (the SPA must match these on live data)
- `templates/analytics.html` + `templates/partials/analytics_table.html` — range tabs,
  summary KPIs, Performance-by-Source table (clickable rows → `?source=`), avg-stages,
  extremes — the analytics parity target.
- `templates/signals.html` — Signal Log parity target.
- `templates/history.html` + `templates/partials/history_table.html` — filter controls
  + history table parity target.
- `templates/staged.html` + `templates/partials/pending_stages.html` — pending-stage
  cards, `{{ s.elapsed }}` render (line 33), empty state copy — staged parity target.

### Phase 9 conventions this phase inherits (do NOT re-decide)
- `.planning/phases/09-spa-scaffold-auth-design-system/09-CONTEXT.md` — D-07 shell +
  router + Sidebar FUTURE_LINKS (enabled in place), D-08 server-state/form-state split,
  D-09 QueryClient defaults (`keepPreviousData`, `refetchIntervalInBackground:false`,
  `staleTime:1000`, `retry:false`, global `onAuthError`), D-10/D-11 design tokens +
  per-page shadcn adds, D-04/D-06 fetch wrapper + global 401.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Phase-8 read routes** — `/api/v2/{analytics,signals,history,history/filter-options,
  stages}` all shipped; signals/history are parity-complete as-is. Analytics + stages
  need read-only widening (D-01, D-09).
- **`db.get_analytics_with_filters()`** already computes `by_source`, `extremes`,
  `avg_stages`; **`db.get_analytics_sources()`** already exists — D-01 is schema/route
  surfacing, not new query work.
- **Phase-9 shell + router** (`frontend/src/routes/router.tsx`,
  `components/shell/{AppShell,Sidebar}.tsx`) — pages slot into ready routes;
  `Sidebar.FUTURE_LINKS` are enabled in place (labels already match legacy).
- **`api()` fetch wrapper + QueryClient defaults** (`frontend/src/lib/{http,queryClient}.ts`)
  — inherited: `keepPreviousData`, no-background-poll-when-hidden, global `onAuthError`.
- **Dual-value `*_display` formatting** (`api/formatting.py`: `money_display`,
  `price_display`, `ts_display`, `ts_machine`) — reuse for the analytics widening.

### Established Patterns
- **Presentation-layer-only blast radius** — read-only API widenings touch API
  serialization + read helpers only; bot core untouched.
- **Parallel-run** — legacy HTMX at `/`, SPA at `/app/`; each page verified vs its live
  legacy twin before it's cutover-eligible (Phase 12 removes legacy).
- **Server-side formatting discipline** (Pitfall 5) — SPA renders `_display`, never
  re-derives precision; the staged elapsed timer is a relative duration off a server
  epoch (not in that ban).

### Integration Points
- Widen `Analytics` schema (`api/schemas.py`) + `get_analytics` route (`api/analytics.py`).
- Enrich `/stages` active payload with a machine start-timestamp (`api/stages.py`
  `_enrich_active`).
- New SPA pages under `frontend/src/routes/*`; shared `DataTable` + state trio under a
  shared components dir; one URL-filter-sync helper shared by analytics + history.

</code_context>

<specifics>
## Specific Ideas

- **"Analytics is the pilot — it must reach FULL legacy parity, not a trimmed KPI
  card."** The per-source deep-dive is the point of SC#1; close the API gap rather than
  shrink the page.
- **"Only staged is live."** Don't add background polling to pages legacy never polled
  — analytics/signals/history are snapshots with a manual Refresh; staged polls ~3s.
- **"Elapsed should tick smoothly."** Client-side ticking timer off a server start
  timestamp, not a jumpy poll-driven string — but the epoch comes from the server
  (requires the D-09 enrichment).
- **"Build the table/state patterns once, on the pilot."** Phase 11 inherits the
  `DataTable` + Loading/Empty/Error trio; prove them here.
- **"Failed read = inline panel, not a toast."** A read-only page with no data shows
  its own failure state with a Retry.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (Live-money mutation pages, optimistic-update
discipline, CSRF-on-write, settings, and react-hook-form/zod validation were referenced
only as the *reason* certain Phase-10 conventions exist — the read-only discipline, the
shared `destructive`-ready tokens, the table patterns Phase 11 reuses — and remain
assigned to Phase 11. Legacy-route / SSE `/stream` / Tailwind-CLI removal remains
Phase 12.)

</deferred>

---

*Phase: 10-read-only-page-migration-analytics-pilot-signals-history-sta*
*Context gathered: 2026-06-06*
