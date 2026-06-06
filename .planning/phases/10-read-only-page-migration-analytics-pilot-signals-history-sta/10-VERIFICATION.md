---
phase: 10-read-only-page-migration-analytics-pilot-signals-history-sta
verified: 2026-06-06T12:00:00Z
status: human_needed
score: 10/12
overrides_applied: 0
human_verification:
  - test: "Open /app/analytics and legacy /analytics on the same live DB simultaneously. Compare KPI values field-by-field: total trades, win rate, profit factor, net P&L, gross profit, gross loss, best/worst trade extremes, and each by-source row. Click a by-source row and confirm ?source= appears in the URL and the data re-queries. Apply a source filter and confirm the Avg-Stages card appears; clear the filter and confirm it disappears (Pitfall 3). Switch range tabs (7d/30d/90d/All) and confirm numbers update."
    expected: "All KPI numbers, by-source rows, and extremes match the legacy page exactly. URL filter round-trips work. Avg-Stages card only visible with an active source filter."
    why_human: "Golden-number comparison requires a live DB with real trade data. SPA and legacy page must be open side-by-side. Programmatic verification cannot confirm numeric parity against a live running instance."
  - test: "Open /app/signals and legacy /signals on the same live DB. Compare all columns: Time, Type (verify label map — OPEN/OPEN (NOW)/CLOSE/PARTIAL/MOD SL/MOD TP), Symbol, Direction, Zone, SL, TP, Action, Details. Confirm Details renders as plain text, not HTML."
    expected: "All columns match legacy output. Type labels match the legacy map exactly. No HTML tags visible in Details cells."
    why_human: "SC#5 golden-number comparison requires live data. Label correctness and XSS safety require visual inspection."
  - test: "Open /app/history and legacy /history on the same live DB. Compare all columns including the D-12 additions (SL, TP, Status, Source). Apply each of the 5 filters (account, source, symbol, from_date, to_date) and confirm AND-logic filtering. Deep-link /app/history?account=X&symbol=Y, reload the page, and confirm filters are restored and results match. Change a filter and confirm rows do not flicker (keepPreviousData)."
    expected: "All columns match legacy. Filters are URL-bookmarkable and restore on reload. No row flicker when changing a filter. AND-logic: all returned rows match all active filter values."
    why_human: "Bookmarkable filter restore and flicker-absence are runtime behaviors requiring a live browser session."
  - test: "Open /app/stages and legacy /staged on the same live DB. Compare active stage cards: account, symbol, direction, filled/total counts, target band, current price. Observe an active card for at least 10 seconds and confirm the Elapsed timer ticks smoothly per-second (not in 3-second poll jumps). Compare resolved rows including Status label mapping. Confirm /app/ redirects to /app/analytics."
    expected: "Active cards match legacy output. Elapsed ticks per-second (D-06). Resolved status labels map correctly (e.g. 'Kill-switch drain' for cancelled_by_kill_switch). /app/ redirects to analytics pilot. Note: the SPA shows CORRECT filled/total/distance values; legacy renders these BLANK (D-13 known parity exception)."
    why_human: "Per-second elapsed smoothness requires watching a live card. Golden-number comparison of card values requires a live DB with active staged entries."
---

# Phase 10: Read-Only Page Migration Verification Report

**Phase Goal:** The four read-only pages (analytics, signals, history, staged-entries) reach SPA parity in ascending pipeline-validation order — analytics as the read-only pilot proving the full API+SPA+auth+nginx stack, then signals, history (with URL-bookmarkable filters + keepPreviousData), and staged-entries (live polling + elapsed-time). Each verified against its live legacy page before that legacy route is eligible for decommission.
**Verified:** 2026-06-06
**Status:** human_needed (automated checks pass; SC#1/SC#5 golden-number comparison deferred to live-DB human gate per context)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | GET /api/v2/analytics returns by_source[] with per-source net_pnl_display, best/worst, win_rate, profit_factor (D-01 full parity) | VERIFIED | `api/analytics.py`: `by_source=by_source` wired; `by_source` built from `data.get("by_source", [])` with `money_display()` twins; 9 `money_display` calls in analytics.py |
| 2 | GET /api/v2/analytics returns extremes, avg_stages, sources (previously discarded) | VERIFIED | `sources = await db.get_analytics_sources()` confirmed in analytics.py; `extremes=` and `avg_stages=` kwargs in Analytics() return; schemas carry `AnalyticsBySource` + `AnalyticsExtremes` classes |
| 3 | avg_stages is non-null only when a source filter is active (Pitfall 3) | VERIFIED | `avg_stages passed through unchanged (data.get("avg_stages"))` in analytics.py; AnalyticsView guards with `data.avg_stages ? (...)` conditional — confirmed in source |
| 4 | GET /api/v2/stages active rows carry started_at (ISO-8601 + UTC offset) from raw created_at (Pitfall 4 fix) | VERIFIED | `api/stages.py`: zip pattern `zip(active, raw_active)` confirmed; `out["started_at"] = ts_machine(created_at)` at line 44; D-13 keys `filled_count`/`total_stages` absent |
| 5 | GET /api/v2/signals surfaces entry_zone_low/high (+_display), sl/tp (+_display), details, source_name | VERIFIED | `api/schemas.py`: `entry_zone_low: float | None = None` confirmed; `details: str | None = None` bare; `api/signals.py`: `price_display` count >= 5 (zone/sl/tp); no `details_display` or `source_name_display` |
| 6 | GET /api/v2/history surfaces sl/tp (+_display), status, source_name (D-12) | VERIFIED | `api/schemas.py`: `status: str | None = None`, `source_name: str | None = None` in HistoryTrade region; `api/history.py`: `source_name` present; fix commit `a9c9ade` also addressed date-filter binding bug |
| 7 | GET /api/v2/history round-trips all 5 filter params with AND logic | VERIFIED | `HistoryView.tsx`: `queryKey: ["history", filters]`; `useUrlFilters<{account,source,symbol,from_date,to_date}>` confirmed; `history/filter-options` populated dropdowns; `from_date`/`to_date` both present; `test_history_contract.py` tests filter AND-logic |
| 8 | SPA analytics page: KPIs + range tabs + by-source DataTable + URL filters + states + no polling | VERIFIED | `AnalyticsView.tsx`: `useUrlFilters` + `api/v2/analytics` wired; `refetchInterval` absent; `avg_stages` truthy-guarded; DataTable + Loading + Empty + ErrorPanel all imported and used; `total_profit_display`/`gross_profit_display`/`gross_loss_display` rendered; range tabs write `?range=`; by-source rows write `?source=` on click |
| 9 | SPA signals page: legacy columns, type-label map, XSS-safe details rendering, no polling | VERIFIED | `SignalsView.tsx`: `OPEN (NOW)` label present; `api/v2/signals` wired; `refetchInterval` count == 0; `details ?? raw_text` rendered as React text child with `title=` tooltip; no `dangerouslySetInnerHTML` |
| 10 | SPA history page: legacy columns including D-12 additions, URL-bookmarkable 5-field filters, keepPreviousData, no polling | VERIFIED | `HistoryView.tsx`: `sl_display`/`tp_display`/`status`/`source_name` columns in DataTable; `useUrlFilters` drives query key; `refetchInterval` count == 0; global `placeholderData: keepPreviousData` confirmed in `queryClient.ts` |
| 11 | SPA staged-entries page: live polling 3s, card-per-account, useElapsed off server epoch, correct filled/total, resolved table with status_label map | VERIFIED | `StagedView.tsx`: `refetchInterval: 3000` present; `useElapsed(s.started_at)` wired; `s.filled`/`s.total` (not `filled_count`/`total_stages`); `"Kill-switch drain"` status_label present; band/price _display strings used |
| 12 | SPA output verified equal to live legacy page field-by-field for all four pages (SC#5) | HUMAN NEEDED | Code-level must-haves satisfied; golden-number comparison on live DB is inherently a runtime/human step — deferred to live-DB verification gate per context note |

**Score:** 11/12 truths verified (1 deferred to human gate)

Note: SC#1 ("numbers matching legacy /analytics on live data") and SC#5 (per-page golden-number verification before cutover) are classified as human_needed per the orchestrator context. All code-level prerequisites for those checks are VERIFIED.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `api/schemas.py` | AnalyticsBySource + AnalyticsExtremes; widened Analytics; widened Signal + HistoryTrade | VERIFIED | `class AnalyticsBySource` (1), `class AnalyticsExtremes` (1); `by_source: list[AnalyticsBySource]`; `entry_zone_low` + `details: str | None`; `status`/`source_name` bare on HistoryTrade; no `win_rate_display`/`profit_factor_display`/`details_display`/`status_display` |
| `api/analytics.py` | Route surfacing by_source/extremes/avg_stages/sources | VERIFIED | `sources = await db.get_analytics_sources()` no longer discarded; `by_source=`/`extremes=`/`avg_stages=` in Analytics() return; 9 `money_display` calls; no `:.Nf` literals |
| `api/stages.py` | _enrich_active widened with started_at; zip pattern | VERIFIED | `zip(active, raw_active)` pattern present; `started_at` count >= 4; `ts_machine`/`ts_display` twins; no `filled_count`/`total_stages`/`distance_to_band` |
| `api/signals.py` | _enrich_signal with zone/sl/tp/details/source_name | VERIFIED | `price_display` count >= 5; `source_name` bare; `details` bare |
| `api/history.py` | _enrich_trade with sl/tp/status/source_name; date-filter bug fixed | VERIFIED | `source_name` present; `sl`/`tp` price twins; date-filter binding bug fixed in commit `a9c9ade` |
| `tests/test_analytics_contract.py` | Wave-0 contract test for analytics (5 tests) | VERIFIED | 5 `def test_` functions; asserts by_source/extremes/avg_stages/sources keys; orchestrator confirms: 6 passed, 7 skipped, 0 errors |
| `tests/test_stages_contract.py` | Contract test for started_at chain (3 tests) | VERIFIED | 3 `def test_` functions; started_at assertion; Pitfall-4 invariant; D-13 key correctness |
| `tests/test_signals_contract.py` | Contract test for widened signal fields (2 tests) | VERIFIED | 2 `def test_` functions; price _display twin assertions |
| `tests/test_history_contract.py` | Contract test for history columns + 5-param filter (3 tests) | VERIFIED | 3 `def test_` functions; D-12 column assertions; 5-param AND-logic filter |
| `frontend/src/components/data/DataTable.tsx` | Shared column-driven table (Phase 11 inherits) | VERIFIED | Exists; `Column<Row>` with `cell`, `align?`, `mono?`, `sign?`; no `toFixed`/`Intl.NumberFormat` in file |
| `frontend/src/components/state/Loading.tsx` | Skeleton rows state primitive | VERIFIED | Exists; `animate-pulse` divs; `role="status"` |
| `frontend/src/components/state/Empty.tsx` | Empty state panel | VERIFIED | Exists |
| `frontend/src/components/state/ErrorPanel.tsx` | Inline error + Retry (D-11) | VERIFIED | `onRetry` prop present; no `toast` from sonner import |
| `frontend/src/lib/useUrlFilters.ts` | useSearchParams-backed URL filter helper | VERIFIED | `useSearchParams` confirmed; generic over `Record<string,string>` keys |
| `frontend/src/lib/useElapsed.ts` | Per-second ticking elapsed hook off server ISO epoch | VERIFIED | `setInterval`/`clearInterval`/`Date.parse` all confirmed |
| `frontend/src/routes/AnalyticsView.tsx` | PAGE-01 analytics pilot at /app/analytics | VERIFIED | `useUrlFilters` + `api/v2/analytics` + DataTable + states + no `refetchInterval`; `avg_stages ?` guard; gross/extremes _display renders |
| `frontend/src/routes/SignalsView.tsx` | PAGE-02 signals page | VERIFIED | `OPEN (NOW)` type-label; `api/v2/signals`; no `dangerouslySetInnerHTML`; no `refetchInterval` |
| `frontend/src/routes/HistoryView.tsx` | PAGE-03 history page with URL filter bar | VERIFIED | `useUrlFilters`; `history/filter-options`; `from_date`/`to_date`; `sl_display`/`tp_display`/`status`/`source_name` in columns; no `refetchInterval` |
| `frontend/src/routes/StagedView.tsx` | PAGE-04 staged page (active cards + resolved table + polling) | VERIFIED | `refetchInterval: 3000`; `useElapsed(s.started_at)`; `s.filled`/`s.total` correct keys; `"Kill-switch drain"` status_label; no `toFixed`/`filled_count`/`total_stages` |
| `frontend/src/routes/router.tsx` | All 4 page routes mounted under boot guard; index -> /analytics | VERIFIED | paths `analytics`/`signals`/`history`/`stages` all present; `<Navigate to="/analytics" replace/>` index |
| `frontend/src/components/shell/Sidebar.tsx` | All 4 pages active NavLinks; Positions/Settings disabled | VERIFIED | `NAV_ENTRIES` carries `to:` fields for analytics/history/signals/stages; Positions/Settings have no `to:` field (rendered as `aria-disabled` spans via generic branch logic) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `api/analytics.py` | `db.get_analytics_sources()` | `sources = await db.get_analytics_sources()` | WIRED | No longer discarded; confirmed in file |
| `api/analytics.py` | `api/formatting.py money_display` | `money_display()` calls on net_pnl/best/worst twins | WIRED | 9 `money_display` calls confirmed |
| `api/stages.py list_stages` | `db.get_pending_stages() raw created_at` | `zip(active, raw_active)` plumbing | WIRED | Pattern confirmed; `out["started_at"] = ts_machine(created_at)` at line 44 |
| `api/stages.py _enrich_active` | `api/formatting.py ts_machine` | `started_at = ts_machine(raw["created_at"])` | WIRED | `ts_machine` count >= 4 in stages.py |
| `api/signals.py _enrich_signal` | `api/formatting.py price_display` | price `_display` twins on zone/sl/tp | WIRED | `price_display` count >= 5 in signals.py |
| `api/history.py _enrich_trade` | `get_filtered_trades` row keys sl/tp/status/source_name | map already-returned columns onto HistoryTrade | WIRED | `source_name` and `status` confirmed in history.py |
| `AnalyticsView.tsx` | `/api/v2/analytics` | `useQuery queryKey ["analytics", filters], queryFn api(...)` | WIRED | `api(\`/api/v2/analytics${...}\`)` at line 178 |
| `AnalyticsView.tsx` | `useUrlFilters` | range/source filter state from URL drives query key | WIRED | `useUrlFilters` import + usage confirmed |
| `router.tsx` | `AnalyticsView` | `{ path: "analytics", element: <AnalyticsView/> }` child | WIRED | `path: "analytics"` confirmed in router.tsx line 43 |
| `StagedView.tsx` | `/api/v2/stages` | `useQuery refetchInterval: 3000` | WIRED | `refetchInterval` + `api/v2/stages` both confirmed |
| `StagedView.tsx` | `useElapsed(started_at)` | client timer off server epoch (D-06) | WIRED | `const elapsed = useElapsed(s.started_at)` at line 124 |
| `HistoryView.tsx` | `/api/v2/history + /api/v2/history/filter-options` | `useUrlFilters` drives query key | WIRED | Both endpoints + `from_date`/`to_date` confirmed |
| `SignalsView.tsx` | `/api/v2/signals + DataTable` | `useQuery` snapshot through shared table | WIRED | `api/v2/signals` + DataTable import confirmed |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `AnalyticsView.tsx` | `data` (Analytics) | `api(/api/v2/analytics)` → `analytics.py` → `db.get_analytics_with_filters()` | Yes — db query chain confirmed in analytics.py; no static returns | FLOWING |
| `StagedView.tsx` | `data.active[]` / `data.resolved[]` | `api(/api/v2/stages)` → `stages.py` → `db.get_pending_stages()` / `db.get_recently_resolved_stages()` | Yes — real db queries; `zip(active, raw_active)` for started_at; no hardcoded empty arrays in the happy path | FLOWING |
| `HistoryView.tsx` | `trades[]` | `api(/api/v2/history)` → `history.py` → `db.get_filtered_trades()` | Yes — parameterized async query; date-filter binding bug fixed in a9c9ade | FLOWING |
| `SignalsView.tsx` | `signals[]` | `api(/api/v2/signals)` → `signals.py` → `db.get_recent_signals(100)` (`SELECT *`) | Yes — db SELECT; `_enrich_signal` maps all widened fields | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `npm run build` exits 0 | Confirmed by orchestrator context: "frontend `npm run build` (tsc -b && vite build) exits 0 on the merged tree" | exit 0, 1925 modules bundled | PASS (orchestrator-confirmed) |
| Bot core byte-for-byte unchanged | `git diff --stat 707fe18 HEAD -- executor.py trade_manager.py db.py mt5_connector.py` | Empty output | PASS |
| All 18 task commits present | `git log --oneline` grep of all commit hashes | 18/18 found | PASS |
| No debt markers (TBD/FIXME/XXX) in phase files | grep on all phase-modified files | Zero matches | PASS |
| `api/analytics.py` has no `:.Nf` literals | grep for `:.2f\|:.1f` in analytics.py | Zero matches | PASS |

### Probe Execution

No explicit probe scripts declared for Phase 10. The contract test suite serves as the probe layer. Per orchestrator context:

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| `tests/test_analytics_contract.py` | `pytest tests/test_analytics_contract.py -x` (Python 3.12 + dev Postgres) | 6 passed, 7 skipped, 0 errors | PASS |
| `tests/test_stages_contract.py` | `pytest tests/test_stages_contract.py -x` (Python 3.12 + dev Postgres) | Included in 6 passed, 7 skipped total | PASS |
| `tests/test_signals_contract.py` | `pytest tests/test_signals_contract.py -x` (Python 3.12 + dev Postgres) | Included in 6 passed, 7 skipped total | PASS |
| `tests/test_history_contract.py` | `pytest tests/test_history_contract.py -x` (Python 3.12 + dev Postgres) | Included in 6 passed, 7 skipped total | PASS |

Note: 7 skips are empty-DB conditional branches (e.g. `test_source_filtered_call_is_well_formed` skips when no analytics sources seeded). Per orchestrator context, these are intentional and not failures.

Host-level pytest was not run here. The orchestrator ran the full suite in the Python 3.12 + dev-Postgres container, which is the correct environment. The pre-existing `tests/test_api_contract.py` (Phase 8) conftest event-loop harness bug is documented in `deferred-items.md` and is NOT a Phase 10 regression.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| PAGE-01 | 10-01, 10-04 | Analytics page (win rate, profit factor, per-source deep-dive) reaches SPA parity | SATISFIED | `api/analytics.py` by_source/extremes/avg_stages/sources wired; `AnalyticsView.tsx` renders full parity; contract test green |
| PAGE-02 | 10-03, 10-05 | Signals page reaches parity | SATISFIED | `api/signals.py` zone/sl/tp/details/source_name widened; `SignalsView.tsx` renders all legacy columns with type-label map |
| PAGE-03 | 10-03, 10-05 | History page reaches parity including trade-history filters | SATISFIED | `api/history.py` sl/tp/status/source_name widened + date-filter bug fixed; `HistoryView.tsx` URL-bookmarkable 5-field filter bar; `keepPreviousData` global |
| PAGE-04 | 10-02, 10-06 | Staged-entries page reaches parity (pending stages per account) | SATISFIED | `api/stages.py` started_at plumbed via zip; `StagedView.tsx` 3s poll + useElapsed + correct filled/total + resolved status_label map |

All 4 requirements claimed by this phase are satisfied at the code level. PAGE-05 through PAGE-08, SUX-01..04, and CUT-01..03 are correctly mapped to later phases (11 and 12) in REQUIREMENTS.md — no orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | — | — | — | No TBD/FIXME/XXX/HACK/PLACEHOLDER found in any phase-modified file |

The one notable deviation: `tests/test_signals_contract.py` and `tests/test_history_contract.py` were initially written using the TestClient pattern and then re-authored post-wave-2 to the `httpx.ASGITransport` single-loop harness (commit `a9c9ade`). This is documented in `deferred-items.md` and is resolved — not a stub or blocker.

### Human Verification Required

#### 1. Analytics Golden-Number Parity (SC#1 + SC#5)

**Test:** Open `/app/analytics` and legacy `/analytics` simultaneously on the same live DB. Compare all KPI values (total trades, win rate, profit factor, net P&L, gross profit, gross loss, best trade, worst trade) and all by-source table rows field-by-field. Verify range tab switching updates numbers. Click a by-source row and confirm `?source=<name>` appears in the URL and data re-queries. Apply a source filter and verify the Avg-Stages card appears; clear it and confirm the card disappears.
**Expected:** All numbers match the legacy page exactly on the same DB snapshot. URL filter round-trips work correctly.
**Why human:** Golden-number comparison requires a live DB with real trade data and a side-by-side visual inspection. The SPA renders server `_display` strings exactly — parity is a function of the DB contents at verification time.

#### 2. Signals Golden-Number Parity (SC#2 + SC#5)

**Test:** Open `/app/signals` and legacy `/signals` on the same live DB. Compare all columns including Type labels (verify `OPEN (NOW)` appears correctly for `open_text_only` signals), Zone values, SL/TP prices, Action, and Details text.
**Expected:** All columns match legacy. Type labels match the legacy map. Details text renders as plain text without HTML artifacts.
**Why human:** Column-by-column match on live signal data requires runtime inspection.

#### 3. History Golden-Number Parity + Bookmarkable Filters + No Flicker (SC#3 + SC#5)

**Test:** Open `/app/history` and legacy `/history` on the same live DB. Compare all 11 columns including the D-12 additions (SL, TP, Status, Source). Apply account, source, and symbol filters and confirm AND-logic results. Deep-link `/app/history?account=X&symbol=Y`, reload, and confirm filters restore and results match. Change a filter and watch rows — confirm no flicker (previous data stays until new data arrives).
**Expected:** Full column match. Filters restore on reload (bookmarkable). No row flicker on filter change.
**Why human:** Flicker absence and filter bookmark restoration require a live browser session with real data.

#### 4. Staged-Entries Golden-Number Parity + Per-Second Elapsed + Polling (SC#4 + SC#5)

**Test:** Open `/app/stages` and legacy `/staged` on the same live DB. Compare active stage cards (symbol, direction, account, filled/total, target band, current price). Watch an active card for at least 10 seconds and confirm Elapsed increments per-second rather than in 3-second jumps. Compare resolved rows and verify status labels (e.g. "Kill-switch drain" for `cancelled_by_kill_switch`). Confirm `/app/` redirects to `/app/analytics`. Document the D-13 parity exception: SPA shows CORRECT filled/total/distance; legacy shows BLANK (known field-name bug).
**Expected:** Cards match legacy field-for-field (except D-13 parity exception where SPA is more correct). Elapsed ticks smoothly per-second. Status labels match. `/app/` redirects correctly.
**Why human:** Per-second elapsed smoothness requires live observation over time. Golden-number comparison requires active staged entries in the DB.

### Gaps Summary

No automated-verification gaps. All code-level must-haves are VERIFIED:
- All 4 API endpoints widened with correct field discipline (money/price _display twins, strings bare, ratios bare per D-14)
- All 4 contract test files exist and are substantive (2-5 tests each; 6 passed, 7 skipped in the Python 3.12 container)
- All 4 SPA pages built and wired to live API endpoints with correct primitives
- All 4 pages registered in router.tsx and activated in Sidebar.tsx
- Bot core (executor.py/trade_manager.py/db.py/mt5_connector.py) byte-for-byte unchanged
- Frontend build exits 0
- No debt markers in any phase-modified file

Phase status is **human_needed** exclusively because SC#1/SC#5 require a human golden-number comparison of SPA output vs. the live legacy page on the same DB — this is a runtime verification step that cannot be performed programmatically.

---

_Verified: 2026-06-06T12:00:00Z_
_Verifier: Claude (gsd-verifier)_
