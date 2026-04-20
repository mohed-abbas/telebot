# Phase 7: Dashboard redesign - Context

**Gathered:** 2026-04-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Restyle every dashboard view on Basecoat components, make the layout mobile-responsive, and add richer drilldowns and filters — with zero regressions on any v1.0/v1.1 functionality.

**Delivers:**
- DASH-01: Every existing view rendered with Basecoat components
- DASH-02: Mobile-responsive layout with slide-over nav
- DASH-03: Positions drilldown with fill history
- DASH-04: Per-source analytics deep-dive + time-range filter
- DASH-05: Trade history filters by account, source, symbol, date range
- SEED-001: Settings UX polish (toasts, inline help, copywriting)

**Out of this phase:**
- New features beyond the DASH-* requirements
- WebSocket market-data streaming (v1.2 nice-to-have)
- Signal-source auto-disable (analytics first, enforcement later)

</domain>

<decisions>
## Implementation Decisions

### Mobile navigation (DASH-02)
- **D-01:** Slide-over drawer triggered by hamburger icon. Drawer slides in from left when opened.
- **D-02:** Sticky header bar appears below `md` breakpoint (~768px) with hamburger + page title. Header remains visible when scrolling.
- **D-03:** Desktop sidebar (fixed, 224px width) unchanged above `md`. Mobile gets the drawer; no bottom tab bar.

### Positions drilldown (DASH-03)
- **D-04:** Inline accordion pattern — clicking a position row expands an inline panel below it showing details. No modal, no page navigation.
- **D-05:** Expanded panel shows:
  - Fill history (timestamp, price, lot size for each stage fill)
  - Per-stage SL/TP levels at time of fill
  - Current P/L (live, updated on SSE tick)
  - Signal attribution (link to originating signal: source, timestamp, raw text)
- **D-06:** Accordion toggle preserves table context — user can compare multiple expanded rows.

### Analytics deep-dive (DASH-04)
- **D-07:** Time-range filter uses horizontal pill tabs: `7d | 30d | 90d | All`. One-click switching, no dropdown.
- **D-08:** Per-source drill-down via clickable table rows. A "Source" column is added to the breakdown table; clicking a row filters all metrics to that source.
- **D-09:** Per-source metrics shown:
  - Win rate + Profit factor (core metrics)
  - Avg stages filled (zone-hit effectiveness)
  - Total trades / Net P/L (volume and return)
  - Best/Worst trade (highlight extremes)

### Trade history filters (DASH-05)
- **D-10:** Inline filter bar above the table. Horizontal row with dropdowns for: account, source, symbol, date range. Always visible.
- **D-11:** Filter combination is AND logic (account=X AND symbol=Y narrows results).
- **D-12:** URL query params for persistence (`?account=X&symbol=Y&from=2026-04-01`). Shareable, survives refresh.

### Settings UX polish (SEED-001)
- **D-13:** Toast notifications for save success, validation errors, and revert confirmation. Wires Basecoat `toast` primitive into HTMX response pattern.
- **D-14:** Inline help text per field. Describes what the field controls, units, recommended range, and footguns (e.g., "max_stages=10 with risk_value=3% can put 30% at risk").
- **D-15:** Copywriting pass — rewrite labels, placeholders, and modal text for operator legibility. Replace engineer-speak with outcome descriptions.

### Restyle approach
- **D-16:** Incremental restyle — one page at a time. Phase 5 compat shim stays until all pages are done, then removed in a final cleanup task.
- **D-17:** Restyle order (suggested): base.html (mobile nav) → overview → positions → history → analytics → settings → signals → staged. Login already uses Basecoat.

### Claude's Discretion
- Exact Basecoat component choices (tabs, accordion, drawer implementations)
- Loading skeleton design during data fetches
- Empty state illustrations and copy
- Table-to-card transformation rules on `sm` breakpoint
- SSE reconnection UI (existing pattern acceptable)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & milestone scope
- `.planning/REQUIREMENTS.md` §Dashboard Redesign (DASH-01..05) — the 5 requirements this phase delivers
- `.planning/ROADMAP.md` Phase 7 — goal + 5 success criteria
- `.planning/PROJECT.md` §Current Milestone — v1.1 milestone intent and safety bar

### Prior-phase handoffs
- `.planning/phases/05-foundation/05-CONTEXT.md` — UI substrate decisions (Tailwind v4, Basecoat vendoring, compat shim, HTMX bridge)
- `.planning/phases/06-staged-entry-execution/06-CONTEXT.md` — Pending-stages panel (D-32..D-36), settings form (D-26..D-31), SSE payload extension

### Seeds
- `.planning/seeds/SEED-001-settings-ux-polish.md` — toasts, inline help, copywriting (folded into Phase 7 scope)

### Codebase intel
- `dashboard.py` — FastAPI app with all routes; SSE stream at lines 988-1042
- `templates/base.html` — current fixed sidebar (no mobile nav); restyle target
- `templates/analytics.html` — current analytics page (no time filter, no per-source drill-down)
- `templates/positions.html` — current positions table (no drilldown)
- `templates/history.html` — current trade history (no filters)
- `templates/settings.html` — per-account tabs form (restyle + toast/help wiring)
- `static/vendor/basecoat/` — Basecoat v0.3.3 vendored (tabs, dialog, toast, accordion primitives)

### External docs (verify during research)
- Basecoat UI v0.3.3 — `https://basecoatui.com/` (drawer, accordion, toast, tabs components)
- HTMX patterns — `https://htmx.org/examples/` (SSE swap, OOB swap for toasts)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `static/vendor/basecoat/` — Basecoat CSS + JS already vendored (Phase 5)
- `static/js/htmx_basecoat_bridge.js` — HTMX afterSwap re-init for Basecoat (Phase 5 UI-05)
- `dashboard.py:asset_url()` — content-hashed CSS resolver (Phase 5 UI-04)
- `dashboard.py:_enrich_stage_for_ui()` — stage enrichment pattern (reuse for drilldown)
- `templates/partials/pending_stages.html` — existing partial pattern (model for drilldown panels)
- `templates/partials/settings_confirm_modal.html` — two-step modal pattern (model for toast trigger)

### Established Patterns
- HTMX polling (`hx-trigger="every 3s"`) on positions/overview
- SSE stream at `/stream` with named events (`event: pending_stages`)
- `hx-swap="innerHTML"` for partial updates
- Jinja2 `{% extends "base.html" %}` + `{% block content %}` structure
- `page` variable for nav-active highlighting

### Integration Points
- `templates/base.html` — add mobile nav drawer + sticky header below `md`
- `templates/positions.html` — add accordion drilldown rows
- `templates/analytics.html` — add time-range tabs + source column + row click handler
- `templates/history.html` — add filter bar + URL param handling
- `templates/settings.html` — add toast triggers + help text
- `dashboard.py` — add query param parsing for history filters; possibly new `/api/analytics` endpoint for filtered data

</code_context>

<specifics>
## Specific Ideas

- **"One page at a time."** Incremental restyle with compat shim staying until all pages are done. Reduces risk and makes reviews easier.
- **"Mobile = phone monitoring on the go."** Slide-over drawer is the most familiar pattern for operators checking trades from their phone. No bottom tab bar — keeps it simple.
- **"Inline accordion keeps context."** Operators often want to compare two positions. Inline expansion lets them open multiple rows without losing table context.
- **"Pill tabs for quick time switching."** 7d/30d/90d/All covers 95% of use cases. No need for a date picker.
- **"Toasts for feedback."** Save success, validation errors, and revert confirmations should be immediately visible at viewport level — not buried in the form.

</specifics>

<deferred>
## Deferred Ideas

- **WebSocket market-data streaming** — Current HTMX polling + SSE is sufficient for v1.1; streaming is a v1.2 nice-to-have.
- **Signal-source auto-disable** — Analytics first (this phase), enforcement logic later.
- **Custom date picker for analytics** — Pill tabs cover common cases; custom range can be added if operators request it.
- **Bulk settings apply / copy-from-account** — v1.2 dashboard polish.
- **Trade-to-signal deep-link from history** — Nice-to-have if time permits; otherwise v1.2.

</deferred>

---

*Phase: 07-dashboard-redesign*
*Context gathered: 2026-04-20*
