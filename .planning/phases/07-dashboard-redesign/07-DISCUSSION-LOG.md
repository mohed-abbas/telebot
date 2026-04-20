# Phase 7: Dashboard redesign - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-20
**Phase:** 07-dashboard-redesign
**Areas discussed:** Mobile navigation, Positions drilldown, Analytics deep-dive, Trade history filters, SEED-001 (settings UX), Restyle approach

---

## Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Mobile navigation | How should the fixed sidebar collapse on phones? Slide-over drawer vs hamburger vs bottom nav. | ✓ |
| Positions drilldown | How to show fill history + per-stage SL/TP? Inline accordion row, modal overlay, or separate detail page. | ✓ |
| Analytics deep-dive | Time-range filter UI (tabs/dropdown/picker) + per-source drill-down pattern. | ✓ |
| Trade history filters | Filter bar design, multi-field combination logic, filter persistence across sessions. | ✓ |

**User's choice:** All four areas selected

---

## Mobile Navigation

### Q1: How should the sidebar behave on mobile screens?

| Option | Description | Selected |
|--------|-------------|----------|
| Slide-over drawer (Recommended) | Hamburger icon in header triggers a slide-in panel from the left. Familiar pattern, keeps full nav hierarchy visible when open. | ✓ |
| Bottom tab bar | Fixed 5-tab bar at bottom (Overview, Positions, History, Analytics, More). iOS-native feel but limits nav items. | |
| Collapsible hamburger | Hamburger triggers an inline dropdown menu in the header area. Simpler but takes up vertical space when open. | |
| You decide | Claude picks the best pattern based on Basecoat primitives and dashboard complexity. | |

**User's choice:** Slide-over drawer

### Q2: Where should the hamburger trigger live, and when should it appear?

| Option | Description | Selected |
|--------|-------------|----------|
| Sticky header bar under md (Recommended) | A thin header with hamburger + page title appears below md breakpoint (~768px). Always visible when scrolling. | ✓ |
| Floating action button | A FAB in bottom-left corner toggles the drawer. Less common for nav but keeps viewport clean. | |
| Top-left corner, non-sticky | Hamburger in top-left that scrolls with page. Simpler but user must scroll up to navigate. | |

**User's choice:** Sticky header bar under md

---

## Positions Drilldown

### Q1: How should the positions drilldown display fill history and per-stage details?

| Option | Description | Selected |
|--------|-------------|----------|
| Inline accordion (Recommended) | Click a row to expand an inline panel showing fill history, stages, SL/TP. No page navigation, stays in context. | ✓ |
| Modal overlay | Click row opens a centered modal with full details. Good for complex data but interrupts flow. | |
| Side panel (drawer) | Click row slides in a right-side panel with details. Keeps table visible but narrower detail space. | |
| You decide | Claude picks based on data density and Basecoat patterns. | |

**User's choice:** Inline accordion

### Q2: What data should the expanded row show?

| Option | Description | Selected |
|--------|-------------|----------|
| Fill history (Recommended) | Timestamp, price, and lot size for each stage fill (stage 1, stage 2, etc.) | ✓ |
| Per-stage SL/TP | SL and TP levels at time of each fill, showing any modifications | ✓ |
| Current P/L breakdown | Live unrealized P/L for this position, updated on SSE tick | ✓ |
| Signal attribution | Link to originating signal (source, timestamp, raw text) for traceability | ✓ |

**User's choice:** All four data points selected

---

## Analytics Deep-Dive

### Q1: How should the time-range filter be presented?

| Option | Description | Selected |
|--------|-------------|----------|
| Pill tabs (Recommended) | Horizontal tabs: 7d | 30d | 90d | All. Fast one-click switching, common dashboard pattern. | ✓ |
| Dropdown select | A single dropdown with preset ranges + optional custom. Compact but requires extra click. | |
| Date picker | Two date inputs for custom start/end. Maximum flexibility but heavier for quick checks. | |
| You decide | Claude picks based on Basecoat's tab/select primitives. | |

**User's choice:** Pill tabs

### Q2: How should per-source analytics drill-down work?

| Option | Description | Selected |
|--------|-------------|----------|
| Clickable table rows (Recommended) | Add a 'Source' column to the breakdown table; clicking a row filters all metrics to that source. | ✓ |
| Separate source cards | One card per signal source showing win rate, profit factor, avg stages. Click to expand details. | |
| Tabs per source | Horizontal tabs at top, one per source. Switches the entire page view to that source's data. | |
| Filter dropdown | A dropdown to select source; all metrics update to show only that source's data. | |

**User's choice:** Clickable table rows

### Q3: What per-source metrics should be visible in the breakdown table?

| Option | Description | Selected |
|--------|-------------|----------|
| Win rate + Profit factor (Recommended) | The two core performance metrics from DASH-04 requirements | ✓ |
| Avg stages filled | Average number of staged fills per signal — shows zone-hit effectiveness | ✓ |
| Total trades / Net P/L | Volume and absolute return per source | ✓ |
| Best/Worst trade | Highlight the single best and worst outcome per source | ✓ |

**User's choice:** All four metric categories

---

## Trade History Filters

### Q1: Where should the filter controls live on the trade history page?

| Option | Description | Selected |
|--------|-------------|----------|
| Inline filter bar (Recommended) | Horizontal bar above the table with dropdowns for account, source, symbol, date range. Always visible. | ✓ |
| Collapsible filter panel | A 'Filters' button expands a panel above the table. Saves space when not filtering. | |
| Side filter drawer | Filters live in a right-side panel, table fills remaining width. Good for many filters. | |
| You decide | Claude picks based on filter count and typical usage. | |

**User's choice:** Inline filter bar

### Q2: Should filter selections persist across page loads?

| Option | Description | Selected |
|--------|-------------|----------|
| URL query params (Recommended) | Filters encode in URL (?account=X&symbol=Y). Shareable, survives refresh, no extra storage. | ✓ |
| Session storage | Filters saved in browser session. Survives navigation but not tab close. | |
| No persistence | Filters reset on each page load. Simplest but requires re-selecting each visit. | |
| You decide | Claude picks based on dashboard UX patterns. | |

**User's choice:** URL query params

---

## SEED-001 (Settings UX Polish)

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, fold it in (Recommended) | Add toasts for save/error feedback, inline help text per field, and operator-friendly labels. Addresses Phase 6 UAT feedback. | ✓ |
| No, defer to v1.2 | Settings form works functionally; polish can wait until after VPS UAT. | |
| Partial — toasts only | Wire toast feedback for save/error but skip help text and copywriting pass. | |

**User's choice:** Yes, fold it in

---

## Restyle Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Incremental (Recommended) | Restyle one page at a time; compat shim stays until all pages done. Lower risk, easier review. | ✓ |
| Big-bang | Restyle all pages in one plan; remove compat shim at the end. Faster but higher risk. | |
| You decide | Claude picks based on page count and dependency graph. | |

**User's choice:** Incremental

---

## Claude's Discretion

- Exact Basecoat component choices (tabs, accordion, drawer implementations)
- Loading skeleton design during data fetches
- Empty state illustrations and copy
- Table-to-card transformation rules on `sm` breakpoint
- SSE reconnection UI

## Deferred Ideas

- WebSocket market-data streaming — v1.2
- Signal-source auto-disable — analytics first, enforcement later
- Custom date picker for analytics — if operators request it
- Bulk settings apply / copy-from-account — v1.2
- Trade-to-signal deep-link from history — nice-to-have
