---
phase: 10-read-only-page-migration-analytics-pilot-signals-history-sta
reviewed: 2026-06-06T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - api/analytics.py
  - api/history.py
  - api/schemas.py
  - api/signals.py
  - api/stages.py
  - frontend/src/components/data/DataTable.tsx
  - frontend/src/components/shell/AppShell.tsx
  - frontend/src/components/shell/Sidebar.tsx
  - frontend/src/components/state/Empty.tsx
  - frontend/src/components/state/ErrorPanel.tsx
  - frontend/src/components/state/Loading.tsx
  - frontend/src/lib/useElapsed.ts
  - frontend/src/lib/useUrlFilters.ts
  - frontend/src/routes/AnalyticsView.tsx
  - frontend/src/routes/HistoryView.tsx
  - frontend/src/routes/SignalsView.tsx
  - frontend/src/routes/StagedView.tsx
  - frontend/src/routes/router.tsx
findings:
  critical: 1
  warning: 6
  info: 4
  total: 11
status: resolved
resolved_commit: 6838123
---

> **RESOLUTION (commit `6838123`):** All 11 findings fixed and verified — backend
> `py_compile` clean, frontend `tsc -b && vite build` exit 0, contract suite
> 6 passed / 7 skipped / 0 errors. CR-01 regression-guarded in
> `test_history_contract.py`; WR-04 behavior change reflected in
> `test_stages_contract.py`. WR-01 was fixed in `db.get_analytics_with_filters`
> (read-only analytics aggregator only — the trading path stayed byte-for-byte
> untouched).

# Phase 10: Code Review Report

**Reviewed:** 2026-06-06
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

Read-only page-migration phase: four SPA pages (Analytics, History, Signals, Stages)
backed by `/api/v2/*` read routes plus shared frontend primitives. The "twin discipline"
(server `_display` strings, raw ratios) is consistently observed across the API routes,
and the frontend renders all money/price cells from `_display` strings with no client-side
re-rounding. SQL filter params in `db.get_filtered_trades`/`get_analytics_with_filters`
are properly parameterized via asyncpg `$n` (verified — no injection in the filter path).
The Details/raw_text XSS surface (T-10-06) is correctly handled as React text children.

However, there is one **BLOCKER**: the History "Source" filter dropdown is permanently
empty because the API route drops the `sources` list — a parity regression that breaks a
documented filter (D-05). Several WARNINGs concern truthiness coercion that silently
corrupts legitimate `0.0` values (best/worst-trade extremes, zero net P&L tone, zero
avg-stages card), and a non-null contract violation in the stages elapsed timer.

## Critical Issues

### CR-01: History Source filter dropdown is permanently empty (sources dropped by route)

**File:** `api/history.py:101-113`, `api/schemas.py:109-114`, `frontend/src/routes/HistoryView.tsx:59-64,266-269`
**Issue:** `db.get_trade_filter_options()` returns `{accounts, symbols, sources}` (db.py:493-497),
but the `history_filter_options` route maps only `accounts`/`symbols`/`directions` onto the
`FilterOptions` schema — and the schema itself has **no `sources` field** at all
(schemas.py:109-114 declares `accounts`, `symbols`, `directions` only). The `sources` list
the DB computed is silently discarded.

Meanwhile the frontend `FilterOptions` interface (HistoryView.tsx:59-64) declares
`sources: string[]`, and the Source `<FilterSelect>` is fed `options?.sources ?? []`
(HistoryView.tsx:267). Since the server never sends `sources`, this is always `undefined`
→ `[]`, so the Source dropdown only ever shows the "All" option. Users cannot filter
history by source — a documented D-05 filter is non-functional. This is a parity
regression against the legacy `history_table.html` page.

(Note the inverse mismatch too: the schema/route emit `directions: []` which the frontend
type does not consume — dead field on one side, missing field on the other.)

**Fix:** Add `sources` to the schema and pass it through in the route:
```python
# api/schemas.py
class FilterOptions(BaseModel):
    accounts: list[str] = []
    symbols: list[str] = []
    sources: list[str] = []
    directions: list[str] = []

# api/history.py
return FilterOptions(
    accounts=opts.get("accounts", []),
    symbols=opts.get("symbols", []),
    sources=opts.get("sources", []),
    directions=[],
)
```

## Warnings

### WR-01: Zero-valued best/worst extremes silently become None (`if x else None` truthiness)

**File:** `api/analytics.py:74-77,87-89` (consuming `db.py:741-742,780-781`)
**Issue:** The analytics route's None-guards (`money_display(best) if best is not None else None`)
are correct, but the upstream `db.get_analytics_with_filters` collapses a legitimate
`pnl == 0.0` extreme to `None` via `float(row["best_trade"]) if row["best_trade"] else None`.
A break-even trade that is the single best/worst trade in the window will render as "—"
instead of "0.00". The route's `is not None` guard is the *right* pattern; the DB helper
uses falsy-coercion and is the actual defect. db.py is the deliberately-untouched bot core,
so this cannot be fixed in db.py — but the route should normalize: treat a returned `None`
that the schema permits as acceptable, OR (preferred) document that zero extremes are a
known display gap. Flagging because the API layer is the contract boundary that the SPA
trusts.
**Fix:** If db.py is off-limits, add a route-level note/test asserting the zero-extreme gap;
otherwise change the DB helper to `... if row["best_trade"] is not None else None`. Same
issue affects `profit_factor` (`if profit_factor`) and `avg_stages` (`if ... avg_stages`)
in db.py — a profit_factor of exactly... (PF can't be 0 with gp>0) — focus on extremes.

### WR-02: Zero net P&L renders red instead of neutral

**File:** `frontend/src/routes/AnalyticsView.tsx:310`
**Issue:** `tone={data.total_profit > 0 ? "green" : "red"}` colors a break-even
account (net P&L exactly 0.00) **red**, signaling a loss where there is none. The
KpiCard already supports a `"neutral"` tone (line 116-124) which is the correct
treatment for zero.
**Fix:**
```tsx
tone={data.total_profit > 0 ? "green" : data.total_profit < 0 ? "red" : "neutral"}
```

### WR-03: Avg-Stages card hidden when avg_stages is legitimately 0

**File:** `frontend/src/routes/AnalyticsView.tsx:344`
**Issue:** `{data.avg_stages ? (...) : null}` uses truthiness, so a real
`avg_stages === 0` (a filtered source whose filled stages average to zero) hides the
card entirely, indistinguishable from the all-source `null` case. The comment claims
this is "Pitfall 3," but Pitfall 3 is about `null` (no source filter), not `0`. When a
source IS selected and the computed average rounds to 0, the card should still show "0.00".
**Fix:** Distinguish null from zero:
```tsx
{filters.source && data.avg_stages != null ? ( ... ) : null}
```

### WR-04: `useElapsed` violates its non-null `started_at` contract → NaN-derived "00:00"

**File:** `frontend/src/routes/StagedView.tsx:50,124`, `api/stages.py:42-46`, `frontend/src/lib/useElapsed.ts:24`
**Issue:** The `ActiveStage` TS interface declares `started_at: string` (non-nullable),
and `StageCard` calls `useElapsed(s.started_at)` unconditionally. But `_enrich_active`
(stages.py:42-46) only sets `started_at` **if** the raw `created_at` is a `datetime`;
if the raw row lacks a usable `created_at`, the key is absent. The route response is an
untyped `dict` (no Pydantic model on `/stages`), so nothing enforces presence. The SPA
then does `Date.parse(undefined)` → `NaN`; `Math.max(0, Math.floor((now - NaN)/1000))`
→ `Math.max(0, NaN)` → `NaN`, and `padStart` on `NaN` produces garbage like
`"NaN:NaN"`. The clamp does not catch NaN.
**Fix:** Guard `useElapsed` against unparseable input, and/or make `started_at` nullable
in the type with a fallback in the card:
```ts
const start = Date.parse(startedAtIso);
const secs = Number.isFinite(start) ? Math.max(0, Math.floor((now - start) / 1000)) : 0;
```

### WR-05: `/api/v2/stages` returns an untyped dict — no response_model contract

**File:** `api/stages.py:60-75`
**Issue:** Every other read route declares `response_model=` (Analytics, list[HistoryTrade],
list[Signal]), giving the SPA a validated, documented contract. `/stages` returns a bare
`dict` with `response_model` omitted, so the `active`/`resolved` shapes are unvalidated and
unenforced. This is how WR-04's missing `started_at` slips through, and it means any drift
in `_enrich_stage_for_ui` / `get_recently_resolved_stages` silently changes the API shape.
**Fix:** Declare Pydantic models (`ActiveStage`, `ResolvedStage`, `StagesPayload`) mirroring
the SPA interfaces and set `response_model=StagesPayload`, making `started_at: str | None`
explicit so WR-04 is caught at the boundary.

### WR-06: AppShell sidebar swallows nav clicks via outer onClick

**File:** `frontend/src/components/shell/AppShell.tsx:49-57`
**Issue:** The sidebar wrapper has `onClick={() => setDrawerOpen(false)}` on the `<div>`
that contains `<Sidebar/>`. On desktop (md+) the drawer is irrelevant, but this handler
still fires on **every** click inside the sidebar, including NavLinks and the Sign-out
button — it runs `setDrawerOpen(false)` (a harmless no-op on desktop) on each. More
importantly, on mobile a tap on a NavLink both navigates AND closes the drawer via this
bubbled handler, which is the desired behavior — but the same bubbling means the Sign-out
button's async handler races the drawer-close re-render. Low severity, but the
broad-bubble onClick on a structural wrapper is fragile; intent (close-on-nav) should be
explicit, not a side effect of every descendant click.
**Fix:** Move drawer-close to the NavLink/onNavigate handlers, or scope it to backdrop +
explicit nav, rather than the wrapping container.

## Info

### IN-01: `format"` ratio helpers duplicated across views (DirectionBadge ×3)

**File:** `frontend/src/routes/HistoryView.tsx:85-99`, `SignalsView.tsx:83-97`, `StagedView.tsx:95-109`
**Issue:** `DirectionBadge` is copy-pasted verbatim (identical BUY/SELL tone logic) into
three route files. Drift risk if the tone tokens or the "—" fallback change.
**Fix:** Extract to a shared `components/data/DirectionBadge.tsx` and import in all three.

### IN-02: `inputClass = selectClass` alias adds no value

**File:** `frontend/src/routes/HistoryView.tsx:102-104`
**Issue:** `const inputClass = selectClass;` — `FilterDate` uses `inputClass` which is
literally `selectClass`. The alias implies a divergence that does not exist; if date
inputs ever need distinct styling this silently couples them.
**Fix:** Use `selectClass` directly in `FilterDate`, or give the date input its own
class string if/when it should differ.

### IN-03: `GOLD_PIP_SIZE` imported only to be re-exported (noqa F401)

**File:** `api/formatting.py:22`
**Issue:** `from risk_calculator import GOLD_PIP_SIZE  # noqa: F401` is imported but never
used; the docstring says it is "single-sourced even though current display formatting
derives digits from `_SYMBOL_DIGITS`." It is dead within this module.
**Fix:** Remove the import (and the noqa) until it is actually consumed, or wire price
precision to it so the single-source claim is real.

### IN-04: `_parse_range` swallows invalid input as "all time" silently

**File:** `api/analytics.py:25-33`
**Issue:** A malformed `?range=abc` or `?range=-5` is silently coerced to `None` (all time)
rather than rejected. Not a security issue (no injection — the value is `int()`-coerced
before reaching SQL), but a client bug (typo in the range param) produces an unexpected
all-time result with no signal. Acceptable for a read endpoint; noted for awareness.
**Fix (optional):** Return HTTP 422 for non-empty non-numeric `range`, or document the
fallback as intentional.

---

_Reviewed: 2026-06-06_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
