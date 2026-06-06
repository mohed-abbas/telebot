# Phase 10: Read-only Page Migration (analytics pilot → signals → history → staged) - Pattern Map

**Mapped:** 2026-06-06
**Files analyzed:** 14 (5 backend modified, 9 frontend new)
**Analogs found:** 14 / 14

This phase has NO unmatched files. Every new/modified file copies a shipped Phase-8
(backend) or Phase-9 (frontend) sibling that already does the same job correctly. The
backend widenings are additive serialization only (no query work); the frontend pages
slot into the inherited shell + QueryClient + http wrapper.

## File Classification

### Backend — read-only serialization widenings (Python / FastAPI)

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `api/schemas.py` (widen `Analytics` D-01) | model | request-response | existing `Position`/`HistoryTrade` dual-value `*_display` models in same file | exact |
| `api/schemas.py` (widen `Signal` D-12) | model | request-response | `Position` (`*_display` price twins) + existing `Signal` | exact |
| `api/schemas.py` (widen `HistoryTrade` D-12) | model | request-response | existing `HistoryTrade` self (add `sl`/`tp`/`status`/`source_name`) | exact |
| `api/analytics.py` (widen route D-01) | route | request-response | self (existing summary mapping) + `api/history.py._enrich_trade` | exact |
| `api/signals.py` (widen `_enrich_signal` D-12) | route | request-response | self + `api/history.py._enrich_trade` price-twin pattern | exact |
| `api/history.py` (widen `_enrich_trade` D-12) | route | request-response | self (add `sl`/`tp`/`status`/`source_name` to existing mapper) | exact |
| `api/stages.py` (`_enrich_active` + `started_at` D-09) | route | request-response | self `_enrich_resolved` (`ts_machine`/`ts_display` on `created_at`) | exact |
| `api/formatting.py` | utility | transform | (no change — reuse `money_display`/`price_display`/`ts_machine`/`ts_display`) | call-site only |

### Frontend — SPA pages + shared primitives (React 19 + TanStack Query v5 + react-router 7)

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `frontend/src/routes/AnalyticsView.tsx` (PAGE-01) | route/page | request-response (snapshot) | `frontend/src/routes/ProbeView.tsx` (useQuery pattern) | role-match |
| `frontend/src/routes/SignalsView.tsx` (PAGE-02) | route/page | request-response (snapshot) | `ProbeView.tsx` + `DataTable` | role-match |
| `frontend/src/routes/HistoryView.tsx` (PAGE-03) | route/page | request-response (snapshot + URL filters) | `ProbeView.tsx` + `useUrlFilters` | role-match |
| `frontend/src/routes/StagedView.tsx` (PAGE-04) | route/page | polling (~3s) + client timer | `ProbeView.tsx` (`refetchInterval:3000`) | exact (polling) |
| `frontend/src/components/data/DataTable.tsx` (D-10) | component | transform | RESEARCH §"Code Examples" + AppShell/Sidebar Tailwind-token conventions | role-match |
| `frontend/src/components/state/{Loading,Empty,ErrorPanel}.tsx` (D-10/D-11) | component | n/a | Sidebar/AppShell token + lucide-react usage; sonner reserved for actions | role-match |
| `frontend/src/lib/useUrlFilters.ts` (D-02/D-05) | hook | transform | RESEARCH Pattern 1 (react-router 7 `useSearchParams`) | role-match |
| `frontend/src/lib/useElapsed.ts` (D-06) | hook | event-driven (interval) | RESEARCH Pattern 2 + ProbeView local-state isolation | role-match |
| `frontend/src/routes/router.tsx` + `Sidebar.tsx` (wire-in) | config | n/a | self (add route children; flip FUTURE_LINKS span → NavLink) | exact |

---

## Pattern Assignments — Backend

### `api/schemas.py` — widen `Analytics` (D-01) (model, request-response)

**Analog:** the `Position` model and the existing dual-value rule already in this file.

**Dual-value `_display` convention** (`api/schemas.py:39-51`, the `Position` model — copy this twin shape exactly):
```python
class Position(BaseModel):
    ...
    volume: float
    volume_display: str
    open_price: float
    open_price_display: str
    ...
    profit: float
    profit_display: str
```

**Module-level rule to obey** (`api/schemas.py:6-9`):
> D-05 dual-value rule: ONLY price/money/volume/timestamp fields get a parallel `_display`
> twin (a pre-computed string from api/formatting.py). ints / strings / enums / bools stay bare.
> Schemas only DECLARE the `_display` fields — the route fills them.

**Existing `Analytics` to widen** (`api/schemas.py:146-157`): currently flat summary only.
Per D-01/D-14 add nested models and ratio-stay-raw fields:
```python
class AnalyticsBySource(BaseModel):
    source_name: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float | None = None       # ratio → NO _display (D-14)
    profit_factor: float | None = None  # ratio → NO _display (D-14)
    net_pnl: float
    net_pnl_display: str                 # money → _display (money_display)
    best_trade: float | None = None
    best_trade_display: str | None = None
    worst_trade: float | None = None
    worst_trade_display: str | None = None

class AnalyticsExtremes(BaseModel):
    best_trade: float | None = None
    best_trade_display: str | None = None
    worst_trade: float | None = None
    worst_trade_display: str | None = None

# Analytics gains:
#   by_source: list[AnalyticsBySource] = []
#   extremes: AnalyticsExtremes
#   avg_stages: float | None = None
#   sources: list[str] = []
```
`win_rate`/`profit_factor` stay raw — mirrors the existing route which does NOT add a `win_rate_display` (D-14).

---

### `api/schemas.py` — widen `Signal` (D-12) (model, request-response)

**Analog:** `Position` price-twin shape (`schemas.py:46-47`) for the `sl`/`tp` price fields.

**Existing `Signal`** (`api/schemas.py:113-121`) drops `entry_zone_low/high`, `sl`, `tp`, `details`, `source_name`. Add (price fields get `price_display` twins, `details`/`source_name` are bare strings):
```python
class Signal(BaseModel):
    ...                                  # keep existing fields
    entry_zone_low: float | None = None
    entry_zone_low_display: str | None = None
    entry_zone_high: float | None = None
    entry_zone_high_display: str | None = None
    sl: float | None = None
    sl_display: str | None = None
    tp: float | None = None
    tp_display: str | None = None
    details: str | None = None           # bare string (NOT _display)
    source_name: str | None = None       # bare string
```

---

### `api/schemas.py` — widen `HistoryTrade` (D-12) (model, request-response)

**Analog:** the existing `HistoryTrade` self (`schemas.py:83-99`) — it already has the
`open_price`/`open_price_display` price-twin and the `opened_at`/`opened_at_display`
timestamp-twin shapes. Add the same shape for `sl`/`tp`, plus bare `status`/`source_name`:
```python
class HistoryTrade(BaseModel):
    ...                                  # keep existing fields
    sl: float | None = None
    sl_display: str | None = None
    tp: float | None = None
    tp_display: str | None = None
    status: str | None = None            # bare (t.status)
    source_name: str | None = None       # bare (COALESCE(s.source_name,'Unknown'))
```

---

### `api/analytics.py` — widen `get_analytics` route (D-01) (route, request-response)

**Analog:** self (the existing summary mapping, `analytics.py:49-65`) plus the
`api/history.py._enrich_trade` per-row money/price formatting pattern.

**Existing money-twin call-site pattern** (`api/analytics.py:53-64` — copy this `money_display()` usage):
```python
return Analytics(
    ...
    total_profit=net_pnl,
    total_profit_display=money_display(net_pnl),
    gross_profit=gross_profit,
    gross_profit_display=money_display(gross_profit),
    gross_loss=gross_loss,
    gross_loss_display=money_display(gross_loss),
)
```

**The discard to fix** (`api/analytics.py:45-47`) — currently calls `get_analytics_sources()`
and throws the result away:
```python
# get_analytics_sources() is wrapped here so the source-filter dropdown shares
# this route's single round-trip; surfaced for the SPA filter control.
await db.get_analytics_sources()   # ← CAPTURE this into `sources` instead of discarding
```

**Widening shape:** capture `sources = await db.get_analytics_sources()`; map
`data["by_source"]` → `list[AnalyticsBySource]` running `money_display()` on `net_pnl`/
`best_trade`/`worst_trade` twins (skip `_display` for `win_rate`/`profit_factor`); map
`data["extremes"]` → `AnalyticsExtremes` with `money_display()` twins; pass `avg_stages`
through (it is `None` on the all-source view — Pitfall 3: SPA renders the Avg-Stages card
only when a source filter is active).

---

### `api/signals.py` — widen `_enrich_signal` (D-12) (route, request-response)

**Analog:** self (`signals.py:22-36`) + `api/history.py._enrich_trade` price-twin pattern.

**Existing mapper to extend** (`api/signals.py:27-36`): add price `_display` twins via
`price_display(symbol, val)` (guard `None`) for `entry_zone_low/high`, `sl`, `tp`; pass
`details`/`source_name` through bare. Import `price_display` alongside the existing
`ts_display, ts_machine` import (`signals.py:16`). The query already returns all columns
(`db.get_recent_signals` does `SELECT *`).

**Type-label map** the SPA reproduces client-side (RESEARCH §3, `signals.html:31-46`):
`open→OPEN`, `open_text_only→OPEN (NOW)`, `close→CLOSE`, `close_partial→PARTIAL`,
`modify_sl→MOD SL`, `modify_tp→MOD TP`, else raw `signal_type`.

---

### `api/history.py` — widen `_enrich_trade` (D-12) (route, request-response)

**Analog:** self (`history.py:34-62`) — already the canonical per-row money + price +
timestamp twin mapper. Copy its `price_display`/`money_display`/`_ts_pair` usage for the
new `sl`/`tp` price twins; map `status` and `source_name` bare:
```python
# existing pattern to mirror (history.py:52-53,57):
open_price_display=price_display(symbol, open_price),
profit_display=money_display(profit),
# add:
sl=..., sl_display=price_display(symbol, sl) if sl is not None else None,
tp=..., tp_display=price_display(symbol, tp) if tp is not None else None,
status=row.get("status"),
source_name=row.get("source_name") or "Unknown",
```
`get_filtered_trades` already returns `t.sl, t.tp`, `t.status`, and
`COALESCE(s.source_name,'Unknown')` (RESEARCH §4 / A1 — operator confirmed full parity in D-12).

---

### `api/stages.py` — `_enrich_active` + `started_at` (D-09) (route, request-response)

**Analog:** the sibling `_enrich_resolved` IN THE SAME FILE (`stages.py:39-47`) — it already
applies `ts_machine`/`ts_display` to a `created_at` datetime. Copy that timestamp-twin shape:
```python
def _enrich_resolved(row: dict) -> dict:
    out = dict(row)
    for key in ("created_at", "filled_at"):
        val = row.get(key)
        if isinstance(val, datetime):
            out[key] = ts_machine(val)
            out[f"{key}_display"] = ts_display(val)
    return out
```

**Pitfall 4 (CRITICAL — the one non-trivial plumbing detail):** `_enrich_stage_for_ui`
(`dashboard.py:567-581`) returns a dict that does NOT include `created_at` — it drops the
raw timestamp after computing the `elapsed` string. The current call chain is:
```python
# stages.py:57 — enriched dict has NO created_at:
active = [dashboard._enrich_stage_for_ui(s, positions) for s in raw_active]
...
"active": [_enrich_active(s) for s in active],   # `s` here lacks created_at
```
The raw `created_at` lives only in `raw_active[i]` (`db.get_pending_stages()` SELECTs it —
verified). Source `started_at` from the RAW row, not the enriched dict — e.g. zip raw+enriched:
```python
"active": [_enrich_active(enriched, raw)
           for enriched, raw in zip(active, raw_active)],
```
and in `_enrich_active` add `started_at = ts_machine(raw["created_at"])` (ISO-8601 + UTC
offset) — optionally `started_at_display = ts_display(raw["created_at"])`. Keep the existing
`band_low`/`band_high`/`current_price` `_display` twins (`stages.py:32-35`).

**Staged active field-name correction (D-13):** surface the enriched dict's REAL keys
`filled`/`total`/`distance_str` (NOT the legacy template's `filled_count`/`total_stages`/
`distance_to_band` which never resolve — documented legacy blank-cell bug). The SPA renders
the correct values; this is a documented parity exception, do NOT replicate the blanks.

**Resolved-stages `status_label`:** map client-side from `_RESOLVED_STATUS_LABELS`
(`dashboard.py:489-497`) — pure presentation strings, not money/price:
`cancelled_by_kill_switch→"Kill-switch drain"`, `cancelled_stage1_closed→"Stage 1 exited"`,
`cancelled_target_reached→"Target/SL reached"`, `abandoned_reconnect→"Abandoned (reconnect)"`,
`failed→"Failed"`, `capped→"Capped"`, `filled→"Filled"`.

---

### `api/formatting.py` — call-site only (no new code)

Reuse verbatim — the ONE place formatting lives (`formatting.py:6-9`, "never inline a
`:.Nf` literal in a route/model"):
- `money_display(value)` (`formatting.py:35-37`) → analytics `net_pnl`/extremes twins.
- `price_display(symbol, value)` (`formatting.py:29-32`) → signals zone/sl/tp + history sl/tp.
- `ts_machine(dt)` (`formatting.py:45-47`) → staged `started_at` (ISO-8601 + UTC offset).
- `ts_display(dt)` (`formatting.py:50-52`) → optional `started_at_display`.

---

## Pattern Assignments — Frontend

### `frontend/src/routes/{Analytics,Signals,History,Staged}View.tsx` (route/page)

**Analog:** `frontend/src/routes/ProbeView.tsx` — the canonical `useQuery` + `api()` page.

**useQuery + api() pattern** (`ProbeView.tsx:38-42` — copy for every page; only staged keeps the interval):
```typescript
const { data, dataUpdatedAt, isError } = useQuery<TradingStatus>({
  queryKey: ["trading-status"],
  queryFn: () => api("/api/v2/trading-status") as Promise<TradingStatus>,
  refetchInterval: 3000,   // STAGED ONLY (D-07). Analytics/Signals/History: OMIT (D-03).
});
```

**Per-page polling rules (verified against `queryClient.ts:53-60`, inherited defaults
`placeholderData: keepPreviousData`, `refetchIntervalInBackground:false`, `staleTime:1000`,
`retry:false`):**
- **StagedView:** add `refetchInterval: 3000` (D-07) — background pause is free via the
  inherited `refetchIntervalInBackground:false`. Same as ProbeView's interval.
- **Analytics/Signals/History:** add NO `refetchInterval` (D-03). `refetchOnWindowFocus` is
  TanStack v5 default `true` (queryClient does not disable it). Manual Refresh (D-04) = a
  button calling `refetch()`. `keepPreviousData` (global) gives flicker-free filter changes.

**Server-state / form-state isolation (Pitfall 5 + ProbeView's load-bearing lesson,
`ProbeView.tsx:44-46`):** never initialize local UI state from `data`; render only server
`_display` strings in cells, never `.toFixed()`/`Intl.NumberFormat`.

**queryKey derives from the URL filter object** so a URL change auto-refetches:
`["analytics", filters]`, `["history", filters]`, `["signals"]`, `["stages"]`.

---

### `frontend/src/components/data/DataTable.tsx` (D-10) (component, transform)

**Analog:** RESEARCH §"Code Examples" (the column-driven hand-rolled table — NO
`@tanstack/react-table`, not installed) + AppShell/Sidebar Tailwind-token conventions.

**Token conventions to match** (from `Sidebar.tsx`/`AppShell.tsx`): `bg-card`, `border`,
`text-muted-foreground`, `hover:bg-muted/30`, `font-mono` for numerics, `text-right` for
numeric columns, color-by-sign `text-green-*`/`text-red-*` for P&L (matches ProbeView's
status-color discipline — accent cyan reserved, never used for data). Sticky header
`sticky top-0`. The `cell` prop receives the server `_display` string (Pitfall 5 — no client formatting).

**Consumers:** signals table, history table, analytics Performance-by-Source table, recently-
resolved stages table. (Staged-active uses cards, not the table — D-08.)

---

### `frontend/src/components/state/{Loading,Empty,ErrorPanel}.tsx` (D-10/D-11)

**Analog:** Sidebar/AppShell border-token + lucide-react icon usage (`AppShell.tsx:13`
imports `Menu, X` from `lucide-react`); sonner toast usage in `Sidebar.tsx:15,42` is the
ACTION-feedback case to contrast against.

- **Loading:** skeleton rows (shadcn `skeleton`); driven by `isPending`.
- **Empty:** icon + copy panel; driven by `data.length === 0`.
- **ErrorPanel (D-11):** inline panel in the page body (NOT a sonner toast — toast is
  reserved for action feedback per `Sidebar.tsx:42` logout failure). Message from
  `HttpError.body` (`{error:{code,message}}` envelope, `http.ts:64`) + a Retry button calling
  `refetch()`. `401` never reaches this panel — the inherited global `onAuthError`
  (`queryClient.ts:42-48`) hard-navs to `/app/login?expired=1` first.

---

### `frontend/src/lib/useUrlFilters.ts` (D-02/D-05) (hook, transform)

**Analog:** RESEARCH Pattern 1 — react-router 7 `useSearchParams` (already installed,
react-router-dom 7.17; same router as `router.tsx`). URL is the source of truth; `replace:true`
on filter edits, `push` on by-source row-click navigation. Shared by Analytics (`range`,
`source`) and History (`account`, `source`, `symbol`, `from_date`, `to_date`).

```typescript
import { useSearchParams } from "react-router-dom";
export function useUrlFilters<T extends Record<string, string>>(
  keys: readonly (keyof T & string)[],
) {
  const [params, setParams] = useSearchParams();
  const filters = Object.fromEntries(keys.map((k) => [k, params.get(k) ?? ""])) as T;
  const setFilter = (patch: Partial<T>, opts?: { push?: boolean }) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v as string); else next.delete(k);
    }
    setParams(next, { replace: !opts?.push });
  };
  return { filters, setFilter };
}
```

---

### `frontend/src/lib/useElapsed.ts` (D-06) (hook, event-driven)

**Analog:** RESEARCH Pattern 2 + ProbeView's interval discipline (`ProbeView.tsx:38-42` uses
a 3s server poll; this is a 1s client interval). Pitfall-5-EXEMPT: a relative duration off a
server epoch is not money/price re-rounding (D-06). Epoch is the server `started_at` from the
D-09 widening.

```typescript
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

---

### `frontend/src/routes/router.tsx` + `Sidebar.tsx` (wire-in) (config)

**Analog:** self.

- **router.tsx** (`router.tsx:29-37`): add four route children under the `/` (`<App/>` boot
  guard) alongside the existing `index: <ProbeView/>`. ProbeView is throwaway (its banner says
  "removed in Phase 10") — leave the index or swap to Analytics per planner's call (Overview is
  Phase 11; Open Question 2).
- **Sidebar.tsx** (`Sidebar.tsx:21-28,87-99`): flip the matching `FUTURE_LINKS` entries from a
  disabled `<span aria-disabled>` to an active `<NavLink>` (copy the live "Overview" `<NavLink>`
  block at `Sidebar.tsx:69-83`, including the `isActive` cyan-accent class). Labels already match
  legacy: Trade History / Signal Log / Analytics / Pending Stages.

---

## Shared Patterns

### Server-side formatting (Pitfall 5)
**Source:** `api/formatting.py` (`money_display`/`price_display`/`ts_machine`/`ts_display`).
**Apply to:** all four backend widenings (render twins server-side) + all SPA table/card cells
(render `_display` strings only; the `useElapsed` duration is the sole client-computed value).

### Dual-value `_display` rule (Phase-8 D-05)
**Source:** `api/schemas.py:6-9` module docstring + `Position` model.
**Apply to:** every widened schema — money/price/volume/timestamp get a `_display` twin; ints/
strings/enums/bools (incl. `win_rate`/`profit_factor` ratios per D-14, and `details`/`status`/
`source_name`) stay bare.

### Inherited QueryClient defaults (Phase-9 D-09)
**Source:** `frontend/src/lib/queryClient.ts:50-61`.
**Apply to:** all four pages — `placeholderData: keepPreviousData` (flicker-free filters),
`refetchIntervalInBackground:false` (staged poll pauses on hidden tab), `staleTime:1000`,
`retry:false`. Staged adds `refetchInterval:3000`; the others add nothing.

### Single fetch wrapper + global 401 (Phase-9 D-04/D-06)
**Source:** `frontend/src/lib/http.ts:46-74` (`api()`, `HttpError`) + `queryClient.ts:42-48`
(`onAuthError`).
**Apply to:** every queryFn (`api("/api/v2/<route>?...")`). GETs need NO CSRF header (read-only
phase — `http.ts:51` only attaches `X-CSRF-Token` on mutating methods). `401` → global redirect;
all other errors → ErrorPanel.

### Inline error, not toast (D-11)
**Source:** contrast with `Sidebar.tsx:42` (sonner toast = action feedback only).
**Apply to:** all four pages' `isError` branch → `<ErrorPanel onRetry={refetch}/>` in the body.

---

## No Analog Found

None. Every file has a shipped Phase-8 (backend) or Phase-9 (frontend) analog in the codebase.

---

## Metadata

**Analog search scope:** `api/` (schemas, analytics, signals, history, stages, formatting),
`frontend/src/{lib,routes,components/shell}`, `dashboard.py` (enrichment + status-label map),
legacy `templates/` (parity column sets — line refs in RESEARCH.md).
**Files scanned:** 11 source files read (8 backend, 6 frontend incl. shell, 1 dashboard section).
**Pattern extraction date:** 2026-06-06
