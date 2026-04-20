# Phase 7: Dashboard Redesign - Research

**Researched:** 2026-04-20
**Domain:** Dashboard UI (Basecoat CSS + HTMX + Jinja2), Mobile-Responsive Patterns, Component Integration
**Confidence:** HIGH

## Summary

Phase 7 restyles the entire dashboard using Basecoat v0.3.3 CSS primitives already vendored in Phase 5. The stack is Python/FastAPI + Jinja2 + HTMX with SSE for real-time updates. No React, no SPA, no additional dependencies.

The phase involves incremental page-by-page conversion starting with base.html (mobile nav), then each dashboard page in sequence. Core patterns: Basecoat sidebar for mobile drawer, native HTML `<details>` for accordion drilldowns, Basecoat tabs for analytics time filter, HTMX OOB swaps for toast notifications, and URL query params for filter persistence.

**Primary recommendation:** Execute D-17 restyle order exactly (base.html -> overview -> positions -> history -> analytics -> settings -> signals -> staged). Each page conversion should be a discrete task that can be verified independently, keeping the compat shim active until all pages are complete.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Slide-over drawer triggered by hamburger icon. Drawer slides in from left when opened.
- **D-02:** Sticky header bar appears below `md` breakpoint (~768px) with hamburger + page title. Header remains visible when scrolling.
- **D-03:** Desktop sidebar (fixed, 224px width) unchanged above `md`. Mobile gets the drawer; no bottom tab bar.
- **D-04:** Inline accordion pattern -- clicking a position row expands an inline panel below it showing details. No modal, no page navigation.
- **D-05:** Expanded panel shows: Fill history (timestamp, price, lot size for each stage fill), Per-stage SL/TP levels at time of fill, Current P/L (live, updated on SSE tick), Signal attribution (link to originating signal: source, timestamp, raw text)
- **D-06:** Accordion toggle preserves table context -- user can compare multiple expanded rows.
- **D-07:** Time-range filter uses horizontal pill tabs: `7d | 30d | 90d | All`. One-click switching, no dropdown.
- **D-08:** Per-source drill-down via clickable table rows. A "Source" column is added to the breakdown table; clicking a row filters all metrics to that source.
- **D-09:** Per-source metrics shown: Win rate + Profit factor, Avg stages filled, Total trades / Net P/L, Best/Worst trade
- **D-10:** Inline filter bar above the table. Horizontal row with dropdowns for: account, source, symbol, date range. Always visible.
- **D-11:** Filter combination is AND logic (account=X AND symbol=Y narrows results).
- **D-12:** URL query params for persistence (`?account=X&symbol=Y&from=2026-04-01`). Shareable, survives refresh.
- **D-13:** Toast notifications for save success, validation errors, and revert confirmation. Wires Basecoat `toast` primitive into HTMX response pattern.
- **D-14:** Inline help text per field. Describes what the field controls, units, recommended range, and footguns.
- **D-15:** Copywriting pass -- rewrite labels, placeholders, and modal text for operator legibility.
- **D-16:** Incremental restyle -- one page at a time. Phase 5 compat shim stays until all pages are done, then removed in a final cleanup task.
- **D-17:** Restyle order (suggested): base.html (mobile nav) -> overview -> positions -> history -> analytics -> settings -> signals -> staged. Login already uses Basecoat.

### Claude's Discretion
- Exact Basecoat component choices (tabs, accordion, drawer implementations)
- Loading skeleton design during data fetches
- Empty state illustrations and copy
- Table-to-card transformation rules on `sm` breakpoint
- SSE reconnection UI (existing pattern acceptable)

### Deferred Ideas (OUT OF SCOPE)
- WebSocket market-data streaming -- Current HTMX polling + SSE is sufficient for v1.1
- Signal-source auto-disable -- Analytics first, enforcement later
- Custom date picker for analytics -- Pill tabs cover common cases
- Bulk settings apply / copy-from-account -- v1.2 dashboard polish
- Trade-to-signal deep-link from history -- Nice-to-have if time permits
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DASH-01 | Every existing dashboard view restyled using Basecoat components; zero regressions | Basecoat primitives available for all needed components (sidebar, tabs, dialog, toast, badge, btn, table, field). Compat shim migration pattern established. |
| DASH-02 | Mobile-responsive layout with slide-over nav for small screens | Basecoat `.sidebar` component with `aria-hidden` toggle provides mobile drawer. CSS handles left-slide animation. Sticky header via standard Tailwind `fixed` positioning. |
| DASH-03 | Positions view supports inline drilldown showing fill history, current P/L, per-stage SL/TP | Native HTML `<details>` element with CSS animation (already in basecoat.css). SSE `sse-swap` updates P/L live. Data joins: staged_entries.signal_id -> signals, trades.signal_id -> signals. |
| DASH-04 | Analytics view supports per-source deep-dive and time-range filter | HTMX partial swap for time filter. New db query `get_analytics_by_source(range, source)`. Pill tabs via Basecoat `.tabs` pattern. Clickable rows with `hx-get`. |
| DASH-05 | Trade history view supports filters by account, source, symbol, date range | Inline filter bar with Basecoat field/select primitives. HTMX `hx-get` with query params. FastAPI route reads `request.query_params`. URL persistence via standard browser behavior. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Mobile drawer toggle | Browser/Client | -- | `aria-hidden` toggle via JS event dispatch; no server involvement |
| Position drilldown expansion | Browser/Client | -- | Native `<details>` element handles open/close state client-side |
| Analytics time filter | Frontend Server (SSR) | Browser/Client | HTMX fetches filtered data from server; server renders partial HTML |
| Trade history filters | Frontend Server (SSR) | Browser/Client | Server applies WHERE clauses; browser manages URL params |
| Toast notifications | Browser/Client | Frontend Server | Server returns OOB swap fragment; browser Basecoat JS handles display/dismiss |
| SSE price updates | Frontend Server | Browser/Client | Server pushes via EventSource; browser swaps partial HTML |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Basecoat CSS | 0.3.3 | shadcn-aesthetic components | Already vendored in Phase 5; CSS-only primitives work with Jinja2 |
| HTMX | 2.0.4 | Hypermedia interactions | Existing stack; SSE extension already configured |
| Tailwind CSS | 4.2.2 | Utility-first CSS | Phase 5 established; standalone CLI build |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| htmx-sse extension | (bundled) | Server-Sent Events | Real-time P/L updates in drilldown panels |
| None new | -- | -- | No new dependencies required |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Native `<details>` accordion | Alpine.js accordion | Native element has built-in CSS animations in Basecoat; simpler |
| HTMX OOB swap for toasts | JavaScript toast library | OOB keeps server as single source of truth; no client state |
| URL query params | localStorage filters | URL params are shareable/bookmarkable; superior UX |

**Installation:**
```bash
# No new packages required - all dependencies from Phase 5
```

**Version verification:** [VERIFIED: codebase inspection] Basecoat v0.3.3 vendored at `/static/vendor/basecoat/`, HTMX 2.0.4 from CDN in base.html, Tailwind v4.2.2 standalone CLI in Dockerfile.

## Architecture Patterns

### System Architecture Diagram

```
User Request
     |
     v
+------------------+
|  FastAPI Router  | -- GET /history?account=X&symbol=Y
+------------------+
     |
     +--> Query Params Parsed
     |
     v
+------------------+
|   db.py Query    | -- WHERE account=$1 AND symbol=$2
+------------------+
     |
     v
+------------------+
| Jinja2 Template  | -- Render HTML partial or full page
+------------------+
     |
     v
+------------------+
|  HTMX Response   | -- innerHTML swap or OOB swap
+------------------+
     |
     v
+------------------+
| Basecoat JS      | -- Re-init components via MutationObserver
+------------------+
```

### Mobile Navigation Flow

```
Hamburger Click
     |
     v
document.dispatchEvent(
  CustomEvent('basecoat:sidebar')
)
     |
     v
Basecoat sidebar JS:
- Set aria-hidden="false"
- Remove inert attribute
- Show backdrop overlay
     |
     v
Link Click or Backdrop Click
     |
     v
aria-hidden="true" (auto-close on mobile)
```

### Recommended Project Structure
```
templates/
├── base.html              # Sidebar + mobile nav + toaster container
├── partials/
│   ├── toaster.html       # hx-preserve toaster for OOB swaps
│   ├── position_drilldown.html  # Accordion panel content
│   ├── analytics_table.html     # Time-filtered analytics partial
│   └── history_table.html       # Filtered trade history partial
└── [page].html            # Full page templates extending base.html
```

### Pattern 1: Mobile Slide-Over Drawer
**What:** Basecoat sidebar with hamburger toggle below `md` breakpoint
**When to use:** Main navigation on mobile devices
**Example:**
```html
<!-- Source: https://basecoatui.com/components/sidebar/ -->
<aside class="sidebar" id="main-sidebar" aria-hidden="true">
  <nav aria-label="Main navigation">
    <section class="scrollbar">
      <div role="group">
        <ul>
          <li><a href="/overview" {% if page == 'overview' %}aria-current="page"{% endif %}>Overview</a></li>
          <!-- more links -->
        </ul>
      </div>
    </section>
  </nav>
</aside>
<main>
  <!-- Sticky header (mobile only) -->
  <header class="md:hidden fixed top-0 left-0 right-0 bg-sidebar border-b border-sidebar-border h-12 flex items-center px-4 z-30">
    <button class="btn-icon-ghost" onclick="document.dispatchEvent(new CustomEvent('basecoat:sidebar'))">
      <!-- hamburger SVG -->
    </button>
    <span class="ml-3 font-semibold">{{ page_title }}</span>
  </header>
  <div class="md:pt-0 pt-12"><!-- content --></div>
</main>
```

### Pattern 2: Inline Accordion Drilldown
**What:** Native `<details>` element with Basecoat collapsible styles
**When to use:** Position row expansion showing fill history
**Example:**
```html
<!-- Source: Basecoat collapsible CSS in basecoat.css lines 463-480 -->
<tr>
  <td colspan="9">
    <details>
      <summary class="flex items-center cursor-pointer py-2">
        <span class="font-semibold">{{ p.symbol }}</span>
        <span class="ml-auto text-muted-foreground text-sm">Expand</span>
      </summary>
      <div class="p-4 bg-muted/50 rounded-lg mt-2">
        <!-- Fill history table, P/L, signal attribution -->
        <div data-price-cell hx-get="/partials/position_pnl/{{ p.ticket }}"
             hx-trigger="sse:positions" hx-swap="innerHTML">
          {{ p.profit }}
        </div>
      </div>
    </details>
  </td>
</tr>
```

### Pattern 3: HTMX Toast via OOB Swap
**What:** Server includes toast fragment with `hx-swap-oob` in response
**When to use:** Settings save success/error feedback
**Example:**
```html
<!-- In base.html - preserved toaster container -->
<div id="toaster" class="toaster" hx-preserve="true"></div>

<!-- Server response includes OOB fragment -->
<div hx-swap-oob="beforeend:#toaster">
  <div class="toast" data-category="success" data-duration="4000">
    <div class="toast-content">
      <svg><!-- checkmark --></svg>
      <section><h2>Settings saved</h2></section>
    </div>
  </div>
</div>
<!-- Primary content follows -->
```

### Pattern 4: URL Param Filter Persistence
**What:** Filters encoded in URL query params, HTMX preserves on swap
**When to use:** Trade history filters
**Example:**
```html
<!-- Filter bar -->
<form hx-get="/history" hx-target="#history-table" hx-push-url="true" hx-trigger="change from:select">
  <select name="account">
    <option value="">All accounts</option>
    {% for a in accounts %}
    <option value="{{ a.name }}" {% if filters.account == a.name %}selected{% endif %}>{{ a.name }}</option>
    {% endfor %}
  </select>
  <!-- more filters -->
</form>

<!-- FastAPI route -->
@app.get("/history")
async def history_page(
    request: Request,
    account: str = "",
    source: str = "",
    symbol: str = "",
    from_date: str = "",
    to_date: str = "",
):
    # Build WHERE clauses from params
    filters = {"account": account, "source": source, ...}
    trades = await db.get_filtered_trades(**filters)
```

### Anti-Patterns to Avoid
- **Hand-rolling accordion JS:** Use native `<details>` + Basecoat CSS. The collapsible animation is built-in.
- **Client-side filter state:** Store in URL params, not JavaScript variables. Server is source of truth.
- **Separate toast API endpoint:** Use OOB swap pattern instead. One response, multiple DOM updates.
- **React-style component imports:** This is Jinja2/HTMX. Use `{% include %}` and partials.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Mobile drawer | Custom slide-over JS | Basecoat `.sidebar` + event | Handles aria, backdrop, auto-close on nav |
| Accordion open/close | Alpine.js x-show | Native `<details>` element | CSS animation in basecoat.css; zero JS |
| Tab switching | Custom JS tabs | Basecoat `.tabs` + HTMX | Keyboard nav, ARIA, styled |
| Toast display | setTimeout chains | Basecoat `.toast` + OOB swap | Auto-dismiss, pause on hover, accessible |
| Filter URL sync | history.pushState manual | HTMX `hx-push-url="true"` | Browser back/forward works automatically |

**Key insight:** Basecoat v0.3.3 provides all UI primitives needed. The HTMX + OOB swap pattern handles multi-element updates without client state. Native HTML elements (`<details>`, `<dialog>`) with Basecoat CSS provide animations without JS complexity.

## Common Pitfalls

### Pitfall 1: Accordion State Lost on Polling Refresh
**What goes wrong:** Positions table refreshes every 3s via `hx-trigger="every 3s"`, closing all expanded `<details>` elements.
**Why it happens:** HTMX innerHTML swap replaces the entire table including open state.
**How to avoid:** Use `hx-preserve` on the accordion container OR switch positions drilldown to SSE-only updates (not polling) OR track open ticket IDs client-side and restore after swap.
**Warning signs:** Users complain accordion keeps closing while they read.

### Pitfall 2: Toast Container Cleared on Page Navigation
**What goes wrong:** Navigating pages removes in-flight toasts.
**Why it happens:** Full page swap replaces the toaster div.
**How to avoid:** Add `hx-preserve="true"` to the toaster container. Ensure every page template includes the same `<div id="toaster">`.
**Warning signs:** Toast appears briefly then vanishes on navigation.

### Pitfall 3: Basecoat Components Not Initialized After HTMX Swap
**What goes wrong:** Sidebar, tabs, or toasts stop working after partial swap.
**Why it happens:** Basecoat JS initializes on DOMContentLoaded; HTMX swaps don't trigger it.
**How to avoid:** Phase 5 already solved this with `htmx_basecoat_bridge.js` calling `basecoat.initAll()` on `htmx:afterSwap`. Verify bridge is loaded.
**Warning signs:** Dropdown menus don't open; tabs don't switch.

### Pitfall 4: Mobile Header Z-Index Collision
**What goes wrong:** Sticky mobile header appears behind modals or dropdowns.
**Why it happens:** Basecoat dialogs use `z-50`; header needs lower z-index than modals.
**How to avoid:** Use `z-30` for sticky header; Basecoat modals use `z-50` by default.
**Warning signs:** Dialog backdrop doesn't cover header.

### Pitfall 5: Analytics Source Column Missing Data
**What goes wrong:** "Source" column shows empty or "undefined" values.
**Why it happens:** `signals` table doesn't currently store Telegram channel/group name.
**How to avoid:** The `raw_text` or `details` column may contain source hints; alternatively, need schema update to add `source_name` column. Check Phase 6 STAGE-09 for how attribution is tracked.
**Warning signs:** Per-source drill-down shows all trades under "Unknown".

### Pitfall 6: Filter Form Submits on Every Keystroke
**What goes wrong:** Typing in date input triggers multiple server requests.
**Why it happens:** `hx-trigger="change"` fires on each character.
**How to avoid:** Use `hx-trigger="change from:select, change delay:500ms from:input"` to debounce text inputs.
**Warning signs:** Excessive network requests in devtools; UI feels laggy.

## Code Examples

Verified patterns from official sources:

### Basecoat Sidebar Toggle (Mobile Drawer)
```javascript
// Source: https://basecoatui.com/components/sidebar/ [CITED]
// Toggle sidebar open/closed
document.dispatchEvent(new CustomEvent('basecoat:sidebar', {
  detail: { id: 'main-sidebar', action: 'open' }
}));
// Without id: toggles first sidebar found
document.dispatchEvent(new CustomEvent('basecoat:sidebar'));
```

### HTMX OOB Toast Pattern
```html
<!-- Source: https://htmx.org/attributes/hx-swap-oob/ [CITED] -->
<!-- Server response with OOB toast -->
<div>Primary content here</div>
<div hx-swap-oob="beforeend:#toaster">
  <div class="toast" data-category="success">
    <div class="toast-content">
      <section><h2>Saved!</h2></section>
    </div>
  </div>
</div>
```

### HTMX SSE Named Event Swap
```html
<!-- Source: https://htmx.org/extensions/sse/ [CITED] -->
<div hx-ext="sse"
     sse-connect="/stream"
     sse-swap="pending_stages">
  <!-- Initial content replaced when pending_stages event arrives -->
</div>
```

### Native Details Accordion with Basecoat Styling
```html
<!-- Source: Basecoat basecoat.css lines 463-480 [VERIFIED: codebase] -->
<details>
  <summary class="inline-flex items-center cursor-pointer">
    Click to expand
  </summary>
  <div class="p-4">
    <!-- Expanded content -->
  </div>
</details>
<!-- CSS handles block-size animation automatically -->
```

### Basecoat Pill Tabs for Time Filter
```html
<!-- Source: Basecoat basecoat.css lines 1151-1170 [VERIFIED: codebase] -->
<div class="tabs">
  <div role="tablist">
    <button role="tab" aria-selected="true">7d</button>
    <button role="tab" aria-selected="false">30d</button>
    <button role="tab" aria-selected="false">90d</button>
    <button role="tab" aria-selected="false">All</button>
  </div>
  <div role="tabpanel">
    <!-- Content for active tab -->
  </div>
</div>
```

### Responsive Table-to-Card (Tailwind)
```html
<!-- Source: https://tailkits.com/blog/tailwind-responsive-tables/ [CITED] -->
<!-- Table on md+, card list on mobile -->
<div class="hidden md:block">
  <table class="table"><!-- standard table --></table>
</div>
<div class="md:hidden space-y-4">
  {% for row in data %}
  <div class="card p-4">
    <div class="flex justify-between">
      <span class="font-semibold">{{ row.symbol }}</span>
      <span class="{% if row.pnl >= 0 %}profit{% else %}loss{% endif %}">{{ row.pnl }}</span>
    </div>
    <!-- Stacked fields -->
  </div>
  {% endfor %}
</div>
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Tailwind v3 CDN | Tailwind v4 standalone CLI | Phase 5 | CSS build in Docker, no CDN |
| Custom button styles | Basecoat `.btn-*` variants | Phase 5 | Consistent styling, accessible |
| HTTPBasic auth | Session + login form | Phase 5 | Real auth flow with CSRF |
| Manual component init | MutationObserver + bridge | Phase 5 | Components survive HTMX swaps |

**Deprecated/outdated:**
- Tailwind Play CDN script: Removed in Phase 5 (UI-01). Use standalone CLI build.
- HTTPBasic prompt: Replaced by `/login` form (AUTH-01).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | signals.source_name or equivalent column exists for per-source analytics | Phase Requirements DASH-04 | Analytics will show "Unknown" for all sources; need schema migration |
| A2 | staged_entries join to trades via signal_id provides full drilldown data | Pattern 2 | Drilldown panel missing fill history; need different query path |

**If this table has items:** The planner should verify A1 (source column existence) and A2 (data joins) before creating drilldown/analytics tasks.

## Open Questions

1. **Source Attribution Column**
   - What we know: trades.signal_id links to signals; signals table has raw_text but no explicit source_name column
   - What's unclear: How to extract Telegram channel name for per-source analytics
   - Recommendation: Check if details column stores channel info, or extend signals table with source_name in a schema task

2. **Accordion State Preservation**
   - What we know: Positions table polls every 3s; `<details>` open state will reset on innerHTML swap
   - What's unclear: Whether to use `hx-preserve`, SSE-only updates, or client-side state restoration
   - Recommendation: Use `hx-preserve` on the tbody containing accordions, or switch to SSE-only updates for positions

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + playwright (for E2E browser tests if needed) |
| Config file | pytest.ini |
| Quick run command | `pytest tests/test_dashboard.py -v` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DASH-01 | All pages render with Basecoat classes | E2E/visual | Manual browser inspection | Manual |
| DASH-02 | Mobile drawer opens/closes | E2E/browser | Playwright test (Wave 0) | Wave 0 |
| DASH-03 | Position drilldown shows fill history | Integration | `pytest tests/test_dashboard.py::test_position_drilldown -x` | Wave 0 |
| DASH-04 | Analytics filters by time range | Integration | `pytest tests/test_dashboard.py::test_analytics_time_filter -x` | Wave 0 |
| DASH-05 | Trade history filters persist in URL | E2E | Playwright test | Wave 0 |

### Sampling Rate
- **Per task commit:** Visual inspection + existing test suite green
- **Per wave merge:** Full pytest + browser smoke test
- **Phase gate:** All pages restyled, no regressions, compat shim removed

### Wave 0 Gaps
- [ ] `tests/test_dashboard.py::test_mobile_drawer` -- covers DASH-02
- [ ] `tests/test_dashboard.py::test_position_drilldown` -- covers DASH-03
- [ ] `tests/test_dashboard.py::test_analytics_time_filter` -- covers DASH-04
- [ ] `tests/test_dashboard.py::test_history_filters_url_params` -- covers DASH-05

*(Wave 0 tests can be added as first tasks if not already present)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (Phase 5 handles) | Session auth already implemented |
| V3 Session Management | no (Phase 5 handles) | SessionMiddleware with signed cookie |
| V4 Access Control | yes (unchanged) | `_verify_auth` dependency on all routes |
| V5 Input Validation | yes | Server-side filter param validation |
| V6 Cryptography | no | -- |

### Known Threat Patterns for HTMX + Jinja2

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| XSS via filter param reflection | Tampering | Jinja2 auto-escapes by default; verify `|safe` not used on user input |
| CSRF on filter forms | Tampering | HTMX sends HX-Request header; `_verify_csrf` already checks it |
| Open redirect via `next` param | Spoofing | Already validated in Phase 5 login (only allows relative paths) |

## Sources

### Primary (HIGH confidence)
- [Basecoat UI Sidebar](https://basecoatui.com/components/sidebar/) - sidebar HTML structure, JavaScript API, mobile drawer behavior
- [Basecoat UI Installation](https://basecoatui.com/installation/) - component list, JS initialization methods
- [HTMX hx-swap-oob](https://htmx.org/attributes/hx-swap-oob/) - OOB swap syntax, toast notification pattern
- [HTMX SSE Extension](https://htmx.org/extensions/sse/) - sse-connect, sse-swap, named events
- Codebase: `static/vendor/basecoat/basecoat.css` - verified component styles
- Codebase: `static/js/htmx_basecoat_bridge.js` - HTMX afterSwap re-init pattern

### Secondary (MEDIUM confidence)
- [Toasts with HTMX](https://yarlson.dev/blog/htmx-toast/) - OOB swap toast pattern with auto-dismiss
- [Ben Nadel hx-preserve](https://www.bennadel.com/blog/4790-using-hx-preserve-to-persist-elements-across-swaps-in-htmx.htm) - preserving toaster across swaps
- [Tailkits Responsive Tables](https://tailkits.com/blog/tailwind-responsive-tables/) - table-to-card transformation pattern

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries already vendored/configured in Phase 5
- Architecture: HIGH - patterns documented in official sources and verified in codebase
- Pitfalls: MEDIUM - based on HTMX/Basecoat documentation and common patterns

**Research date:** 2026-04-20
**Valid until:** 2026-05-20 (stable stack, no moving targets)
