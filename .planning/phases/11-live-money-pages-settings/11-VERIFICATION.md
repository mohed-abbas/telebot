---
phase: 11-live-money-pages-settings
verified: 2026-06-07T20:30:00Z
status: human_needed
score: 14/14 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Positions page — SC#1 close clears row only after server 200"
    expected: "Row disappears from the table only after a confirmed 200 from /positions/{account}/{ticket}/close; a forced network failure or 500 keeps the row present with the error toast shown"
    why_human: "Requires a live MT5 demo connection; cannot verify broker-round-trip behaviour by static code inspection"
  - test: "Positions page — Edit modal + drilldown survive ≥2 background refetch cycles (SC#3)"
    expected: "Type an SL or lots value in the Edit modal; 6+ seconds pass (≥2 polls); the typed value remains unchanged and the modal stays open"
    why_human: "Requires a running SPA with live polling; cannot simulate the 3s refetch race in static analysis"
  - test: "Partial-close — 409 toast on id-reuse-different-params"
    expected: "If the same request_id is submitted with a different close_volume, the server returns 409 and the SPA shows 'That close already ran or the amount changed — refresh and retry.'"
    why_human: "Requires live idempotency storage (Phase 8 test_api_idempotency covers the server side, but the full client→server round-trip needs the demo)"
  - test: "Kill switch — CONFIRM CLOSE ALL closes ALL live positions on the MT5 demo"
    expected: "After clicking Emergency Kill Switch → CONFIRM CLOSE ALL, all open demo positions are closed at the broker, the positions count drops to 0, and the TRADING PAUSED banner appears"
    why_human: "Requires a live MT5 demo broker session; behaviour at the broker cannot be verified by code inspection"
  - test: "Kill switch — Resume Trading re-enables live signals"
    expected: "After clicking Resume Trading on the kill-switch page, trading-status.paused becomes false, the PAUSED banner disappears, and the bot processes the next incoming signal"
    why_human: "Requires a live MT5 demo + running bot process"
  - test: "Settings — Save success, validation rejection, and revert each surface a sonner toast (SUX-01)"
    expected: "Save → 'Settings saved for {account}.'; cap breach → 'Couldn't save: {first error}'; revert → 'Reverted last change for {account}.'"
    why_human: "Requires a running SPA against the live server with actual settings mutations; toast display cannot be verified by static inspection"
  - test: "Settings — Account isolation: switching accounts resets form to the correct account's values"
    expected: "After the CR-02 fix (key={account}), switching from account A to account B shows B's values in the form; stashed review state from A is cleared; confirming B's form persists only B's values"
    why_human: "Requires a multi-account setup with the running SPA; the key={account} remount cannot be verified as correctly resetting RHF defaults without a runtime check"
  - test: "CSRF 403 rejection: a mutation without the X-CSRF-Token cookie is rejected with 403"
    expected: "A POST to any live-money endpoint (close, levels, partial-close, emergency, settings) made without the CSRF cookie returns HTTP 403"
    why_human: "Phase 8 test_api_csrf covers the server; the end-to-end browser → api() → server chain requires a live environment to confirm the cookie echoing is wired correctly at runtime"
  - test: "Package legitimacy gate (T-11-SC): react-hook-form, zod, @hookform/resolvers are genuine official packages"
    expected: "npmjs.com confirms: react-hook-form (github.com/react-hook-form), zod v4 (github.com/colinhacks/zod), @hookform/resolvers (rhf org); none added a postinstall script"
    why_human: "Supply-chain verification requires human inspection of npm registry + official repos; cannot be confirmed by code inspection"
  - test: "Pitfall-9 opaque-render: dialog and select components render opaque on the dark brand background"
    expected: "Opening the Edit position dialog and a shadcn select over the dark brand background shows no transparent / see-through background"
    why_human: "Visual rendering cannot be verified by static code inspection"
---

# Phase 11: Live Money Pages + Settings — Verification Report

**Phase Goal:** The highest-blast-radius surfaces — overview, positions (4 destructive actions), the two-step kill switch, and the SEED-001 settings page — reach SPA parity using the money-safe mutation discipline established in Phase 9: the UI changes state only after the server confirms success, every mutation carries CSRF, destructive buttons are disabled-while-pending, and client-side zod validation mirrors the server hard caps.
**Verified:** 2026-06-07T20:30:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Every live-money mutation goes through api() (CSRF auto-echoed), never raw fetch | ✓ VERIFIED | All 5 hooks call `api(` exclusively; grep of hooks/ + routes finds zero raw `fetch(` calls; `encodeURIComponent` on all path params (WR-02 fix confirmed) |
| 2 | No mutation calls setQueryData before server confirm — UI updates only via invalidateQueries in onSuccess | ✓ VERIFIED | grep of hooks/ + routes/ + components/positions/ + components/settings/ returns only comment occurrences of "setQueryData" — zero live call sites |
| 3 | Partial-close sends absolute close_volume + a stable UUID request_id; 409 branch surfaces specific toast | ✓ VERIFIED | usePartialClose.ts:61 sends `close_volume`/`request_id`; lines 73-75 branch on `HttpError && e.status === 409` with the exact operator message |
| 4 | Settings validate branches on data.valid (not HTTP status); 200-on-invalid does not fire onError | ✓ VERIFIED | useSettingsMutations.ts: `validate` mutationFn returns the body; onError is only for transport failures; SettingsView.tsx:164 branches on `result.valid` |
| 5 | Positions page polls GET /api/v2/positions every ~3s with DataTable at parity | ✓ VERIFIED | PositionsView.tsx: useQuery key `["positions"]`, refetchInterval 3000; columns Account|Symbol|Direction|Volume|Entry|SL|TP|P&L|Actions; 304 lines substantive |
| 6 | Close (InlineConfirm+useClose), Edit (EditPositionDialog), Partial-close, Levels are all disabled-while-pending | ✓ VERIFIED | InlineConfirm: ✓ button `disabled={pending}`; EditPositionDialog: `disabled={levels.isPending}` and `disabled={partial.isPending}`; KillSwitchView: `disabled={close.isPending}` |
| 7 | CR-01 fix: partial-close rounds first, guards against rounded value, submits the same rounded value | ✓ VERIFIED | EditPositionDialog.tsx:107-115 rounds to `closeRounded` first, `closeValid = closeRounded < position.volume`, submits `closeVolume: closeRounded` |
| 8 | CR-02 fix: AccountSettings remounts on account switch via key={account} | ✓ VERIFIED | SettingsView.tsx:115 has `key={account}` on `<AccountSettings>` |
| 9 | WR-01 fix: trading-status uses keepPreviousData; fail-safe TRADING STATUS UNAVAILABLE banner | ✓ VERIFIED | KillSwitchView.tsx:78 and OverviewView.tsx:252 both use `placeholderData: keepPreviousData`; OverviewView.tsx:266,318 renders degraded banner on `statusUnknown` |
| 10 | Kill switch two-step flow: preview → CONFIRM CLOSE ALL (hidden when nothing to close); Resume while paused | ✓ VERIFIED | KillSwitchView.tsx: `nothingToClose` guard (line 112) hides confirm; `armed` state gates step-2; Resume shown only when `paused` (line 172) |
| 11 | Settings: zod caps mirror server (percent ≤5.0, fixed_lot ≤ max_lot_size, ints 1-10/1-500/1-100); max_open_trades excluded | ✓ VERIFIED | settingsSchema.ts: superRefine enforces both mode caps; SettingsFormValues interface excludes max_open_trades; 15 vitest tests pass including max_open_trades passthrough |
| 12 | Footgun is mode-aware: percent multiplies, fixed_lot does NOT | ✓ VERIFIED | footgun.ts: percent branch computes `riskValue * maxStages`; fixed_lot branch returns `riskValue` unchanged; 4 vitest tests confirm both branches (percent 2×4=8; fixed_lot 0.4 not 1.6) |
| 13 | Overview: TRADING PAUSED banner, per-account cards, positions table, pending stages, kill-switch entry; index resolves to Overview | ✓ VERIFIED | OverviewView.tsx: 4 useQuery calls with refetchInterval; "TRADING PAUSED" conditional render (line 312); router.tsx index element `<OverviewView/>` |
| 14 | Positions and Settings are live nav links in sidebar; emergency route is reachable | ✓ VERIFIED | Sidebar.tsx: NAV_ENTRIES has `to: "/positions"` and `to: "/settings"`; router.tsx routes "positions", "emergency", "settings"; OverviewView has Link to="/emergency" |

**Score:** 14/14 truths verified

### Deferred Items

None. All phase items are either verified or routed to human_verification.

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/lib/footgun.ts` | Mode-aware compounded-exposure pure function | ✓ VERIFIED | Exports `footgun`; percent branch multiplies; fixed_lot branch does not |
| `frontend/src/lib/footgun.test.ts` | Pitfall-6 regression unit | ✓ VERIFIED | 4 tests covering percent-multiplies and fixed_lot-does-not contract |
| `frontend/src/lib/settingsSchema.ts` | Mode-aware zod cap schema factory | ✓ VERIFIED | Exports `makeSettingsSchema`; superRefine enforces both mode caps; no max_open_trades rule |
| `frontend/src/lib/settingsSchema.test.ts` | SUX-03 cap-mirror unit | ✓ VERIFIED | 11 tests; percent cap, fixed_lot per-account cap, int bounds, max_open_trades passthrough |
| `frontend/vitest.config.ts` | Vitest runner with @/ alias | ✓ VERIFIED | Exists; resolves `@/` alias; `npm test` runs vitest; 15 tests pass |
| `frontend/src/components/ui/dialog.tsx` | shadcn dialog | ✓ VERIFIED | Present; consumed by EditPositionDialog, ConfirmDiffDialog, AuditTimeline |
| `frontend/src/components/ui/tooltip.tsx` | shadcn tooltip | ✓ VERIFIED | Present; consumed by SettingsForm per-field help |
| `frontend/src/components/ui/select.tsx` | shadcn select | ✓ VERIFIED | Present; consumed by SettingsForm risk_mode and SettingsView account selector |
| `frontend/src/components/ui/badge.tsx` | shadcn badge | ✓ VERIFIED | Present |
| `frontend/src/components/ui/popover.tsx` | shadcn popover | ✓ VERIFIED | Present |
| `frontend/src/hooks/useClose.ts` | Close mutation → invalidate positions | ✓ VERIFIED | api() POST; onSuccess invalidates ["positions"] + ["overview"]; no setQueryData; encodeURIComponent on params |
| `frontend/src/hooks/useLevels.ts` | Modify SL/TP mutation | ✓ VERIFIED | api() POST with optional body fields; onSuccess invalidates ["positions"] + ["overview"] |
| `frontend/src/hooks/usePartialClose.ts` | Absolute-volume partial-close + request_id + 409 | ✓ VERIFIED | useRef(crypto.randomUUID()); close_volume absolute (no percent); 409 branch with specific message |
| `frontend/src/hooks/useEmergency.ts` | Emergency close + resume mutations | ✓ VERIFIED | Both invalidate ["overview","trading-status","positions"]; toasts wired; no setQueryData |
| `frontend/src/hooks/useSettingsMutations.ts` | validate/confirm/revert (validate 200-on-invalid) | ✓ VERIFIED | validate resolves body; onError only on transport failure; confirm invalidates ["settings",account]; revert body is {account} only |
| `frontend/src/routes/PositionsView.tsx` | PAGE-06 positions table + actions | ✓ VERIFIED | 304 lines; useQuery refetchInterval 3000; InlineConfirm+useClose; EditPositionDialog; PositionDrilldown; read failure → inline ErrorPanel |
| `frontend/src/components/positions/EditPositionDialog.tsx` | Combined modal: two independent submits | ✓ VERIFIED | 295 lines; contains "Remaining after"; references useLevels + usePartialClose; CR-01 fix (round-first guard); no percent field |
| `frontend/src/components/positions/InlineConfirm.tsx` | Two-click destructive confirm | ✓ VERIFIED | armed state; ✓ disabled={pending}; ✕ resets to idle; no window.confirm |
| `frontend/src/components/positions/PositionDrilldown.tsx` | Fill history + P/L + signal drilldown | ✓ VERIFIED | Reads /api/v2/positions/{account}/{ticket}; renders _display twins; fill_history + signal block |
| `frontend/src/routes/KillSwitchView.tsx` | PAGE-07 two-step kill-switch | ✓ VERIFIED | 185 lines; "CONFIRM CLOSE ALL" on destructive button; nothingToClose guard; keepPreviousData; Resume shown while paused |
| `frontend/src/components/settings/SettingsForm.tsx` | rhf+zod form with inline footgun + tooltips | ✓ VERIFIED | zodResolver(makeSettingsSchema); footgun() live inline; amber AlertTriangle; max_open_trades read-only; "Review changes" submit |
| `frontend/src/components/settings/ConfirmDiffDialog.tsx` | Diff table + dry_run_text verbatim + restated footgun | ✓ VERIFIED | footgun() called; dryRunText rendered verbatim; Confirm disabled={pending}; "Go back" preserves form |
| `frontend/src/components/settings/AuditTimeline.tsx` | Audit table + single "Revert last change" | ✓ VERIFIED | timestamp_display used; no audit_id anywhere in file; useSettingsMutations.revert({account}) only |
| `frontend/src/routes/SettingsView.tsx` | PAGE-08 two-step flow end-to-end | ✓ VERIFIED | 232 lines; useQuery ["settings",account]; branches on result.valid (Pitfall 7); key={account} on AccountSettings (CR-02); inline ErrorPanel on read failure |
| `frontend/src/routes/OverviewView.tsx` | PAGE-05 overview landing surface | ✓ VERIFIED | 367 lines; 4 useQuery with refetchInterval; "TRADING PAUSED" conditional; statusUnknown degraded indicator; PositionsView embedded |
| `frontend/src/routes/router.tsx` | All 4 Phase-11 routes + index → overview | ✓ VERIFIED | Index element `<OverviewView/>`; routes "overview","positions","emergency","settings" all present |
| `frontend/src/components/shell/Sidebar.tsx` | Positions + Settings live nav links | ✓ VERIFIED | NAV_ENTRIES: `to:"/positions"` and `to:"/settings"` present; Overview `to:"/"` |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `frontend/src/hooks/*.ts` | `frontend/src/lib/http.ts api()` | all mutationFns call api(), never raw fetch | ✓ WIRED | All 5 hooks confirmed; grep finds zero `fetch(` in hooks |
| `frontend/src/hooks/usePartialClose.ts` | POST /api/v2/positions/{account}/{ticket}/close-partial | body {close_volume, request_id} | ✓ WIRED | Lines 60-63: `close_volume: closeVolume`, `request_id: requestIdRef.current` |
| `frontend/src/routes/PositionsView.tsx` | `frontend/src/hooks/useClose.ts` | row Close button disabled-while-pending | ✓ WIRED | `useClose()` called at page level; `close.isPending` scoped per-row |
| `frontend/src/components/positions/EditPositionDialog.tsx` | `frontend/src/hooks/{useLevels,usePartialClose}.ts` | two independent submits | ✓ WIRED | Both hooks imported and wired to distinct submit handlers |
| `frontend/src/routes/PositionsView.tsx` | GET /api/v2/positions | useQuery refetchInterval 3000 | ✓ WIRED | queryKey ["positions"], refetchInterval 3000 |
| `frontend/src/components/settings/SettingsForm.tsx` | `frontend/src/lib/settingsSchema.ts` | zodResolver(makeSettingsSchema(values.max_lot_size)) | ✓ WIRED | Line 78: `zodResolver(makeSettingsSchema(values.max_lot_size))` |
| `frontend/src/components/settings/SettingsForm.tsx` | `frontend/src/lib/footgun.ts` | inline live recompute | ✓ WIRED | Line 104: `footgun(mode, riskValue, maxStages)` |
| `frontend/src/routes/SettingsView.tsx` | `frontend/src/hooks/useSettingsMutations.ts` | validate/confirm/revert | ✓ WIRED | `useSettingsMutations()` destructured; validate.mutate called in handleReview; confirm.mutate in handleConfirm |
| `frontend/src/routes/KillSwitchView.tsx` | GET /api/v2/emergency/preview | useQuery preview | ✓ WIRED | queryKey ["emergency-preview"], queryFn fetches /api/v2/emergency/preview |
| `frontend/src/routes/KillSwitchView.tsx` | `frontend/src/hooks/useEmergency.ts` | close + resume mutations | ✓ WIRED | `useEmergency()` called; close.mutate() on CONFIRM CLOSE ALL; resume.mutate() on Resume Trading |
| `frontend/src/routes/OverviewView.tsx` | GET /api/v2/overview + /trading-status + /positions + /stages | 4 useQuery with refetchInterval 3000 | ✓ WIRED | All 4 queryKeys present; each has refetchInterval 3000 |
| `frontend/src/routes/router.tsx` | OverviewView / PositionsView / KillSwitchView / SettingsView | child routes + index → overview | ✓ WIRED | index element `<OverviewView/>`; paths "overview","positions","emergency","settings" all import and render the correct views |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `PositionsView.tsx` | `data` (Position[]) | useQuery → api("/api/v2/positions") → server | Yes — fetches from the server; `refetchInterval 3000` continuously refreshes | ✓ FLOWING |
| `KillSwitchView.tsx` | `preview.data` (EmergencyPreview) | useQuery → api("/api/v2/emergency/preview") | Yes — fetches live counts from the server | ✓ FLOWING |
| `SettingsView.tsx/AccountSettings` | `data` (SettingsPayload) | useQuery(["settings",account]) → api() | Yes — per-account server values feed rhf defaultValues | ✓ FLOWING |
| `OverviewView.tsx` | `overview.data`, `tradingStatus.data`, `stages.data` | 3 useQuery calls → api() | Yes — all three pull from real server endpoints | ✓ FLOWING |
| `SettingsForm.tsx` | `values` prop | drilled from SettingsPayload.values | Yes — bare server values; `defaultValues` passed directly | ✓ FLOWING |
| `ConfirmDiffDialog.tsx` | `diff`, `dryRunText` | validate result from POST /validate | Yes — server-generated diff + dry_run_text verbatim | ✓ FLOWING |
| `AuditTimeline.tsx` | `audit` prop | drilled from SettingsPayload.audit | Yes — real server audit rows; sorted newest-first | ✓ FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `cd frontend && npm run build` exits 0 (tsc strict) | `npm run build` | Build succeeded; 2026 modules transformed | ✓ PASS |
| `npx vitest run` passes all tests | `npx vitest run` | 2 test files, 15 tests passed | ✓ PASS |
| footgun percent mode multiplies (2×4=8) | vitest assertion | `"4 entries at 2% risks up to 8% per signal."` | ✓ PASS |
| footgun fixed_lot does NOT multiply (0.4,4 → no 1.6) | vitest assertion | `"This sizes up to 0.4 total lots per signal across 4 entries."` | ✓ PASS |
| settingsSchema rejects percent risk_value > 5.0 | vitest assertion | `safeParse({risk_value:6.0}).success === false` | ✓ PASS |
| settingsSchema rejects fixed_lot risk_value > max_lot_size | vitest assertion | `safeParse({risk_value:0.9}, maxLotSize=0.5).success === false` | ✓ PASS |
| settingsSchema does NOT cap max_open_trades | vitest assertion | `safeParse({max_open_trades:9999}).success === true` | ✓ PASS |

---

### Probe Execution

No conventional probe scripts found for this phase (`scripts/*/tests/probe-*.sh` absent). Phase 11 is a frontend-only phase; the automated proof is `npm run build` (tsc strict) + `npx vitest run`.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| PAGE-05 | 11-06 | Overview page at parity with live polling | ✓ SATISFIED | OverviewView.tsx: 4 useQuery polls; TRADING PAUSED banner; account cards; positions (embedded PositionsView); pending stages; kill-switch entry; /app index resolves here |
| PAGE-06 | 11-03 | Positions page with safe live-money actions | ✓ SATISFIED | PositionsView.tsx + EditPositionDialog + InlineConfirm + PositionDrilldown: server-confirmed only, no optimistic, disabled-while-pending, absolute lots, request_id idempotency |
| PAGE-07 | 11-05 | Emergency kill switch two-step preview→confirm | ✓ SATISFIED | KillSwitchView.tsx: preview read; two-step armed flow; CONFIRM CLOSE ALL disabled-while-pending; hidden when nothing to close; Resume while paused |
| PAGE-08 | 11-04 | Settings page: per-account form, diff-confirm, audit, revert | ✓ SATISFIED | SettingsView + SettingsForm + ConfirmDiffDialog + AuditTimeline: two-step validate→confirm; CR-02 key={account} account isolation |
| SUX-01 | 11-04 | Viewport sonner toasts for save/rejection/revert | ✓ SATISFIED | All hooks surface toasts in onSuccess/onError; SettingsView.tsx branches validate result for toast vs modal |
| SUX-02 | 11-04 | Per-field tooltips with units, recommended range, footgun | ✓ SATISFIED | SettingsForm.tsx: every NumberField wrapped in FieldLabel with Tooltip; inline amber footgun live |
| SUX-03 | 11-01, 11-04 | Client zod caps mirror server hard-caps | ✓ SATISFIED | settingsSchema.ts: percent ≤5.0, fixed_lot ≤ max_lot_size, ints bounded 1-10/1-500/1-100; 11 vitest assertions |
| SUX-04 | 11-04 | Copywriting: DB-column names → operator mental models | ✓ SATISFIED | SettingsForm: "Risk calculation", "Per-trade risk (%)", "Maximum entries per signal", "Default stop-loss (pips)", "Daily trade limit", "Maximum open trades" |

All 8 requirement IDs from plans 11-01 through 11-06 verified. No orphaned requirements.

---

### Code Review Blocker Resolution

Both blockers from 11-REVIEW.md were fixed in commit `481134d` (confirmed in git log):

| Finding | Fix | Verification |
|---------|-----|-------------|
| **CR-01** — partial-close rounds up past open volume → full close | `closeRounded = roundToStep(closeNum)` before guard; `closeValid = closeRounded < position.volume`; submits `closeVolume: closeRounded` | EditPositionDialog.tsx:107-115,143 — round-first guard confirmed |
| **CR-02** — settings form + review state not reset on account switch | `key={account}` on `<AccountSettings>` | SettingsView.tsx:115 confirmed |
| **WR-01** — failed trading-status fetch silently hides PAUSED banner | `placeholderData: keepPreviousData` + `statusUnknown` degraded indicator | KillSwitchView.tsx:78, OverviewView.tsx:252,266,318 confirmed |
| **WR-02** — path params interpolated without encoding | `encodeURIComponent` on account + ticket in all 4 hooks + PositionDrilldown + SettingsView | 8 call sites confirmed |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| OverviewView.tsx | 178 | `marginPct.toFixed(1)` | ℹ️ Info | Legitimate: a dimensionless percentage ratio (margin/balance), explicitly documented as Pitfall-5-exempt in the file header — not a money re-format |
| OverviewView.tsx | 360 | `key={\`${s.account_name}-${s.symbol}-${i}\`}` | ℹ️ Info | Deferred as IN-03 in 11-REVIEW.md; no money impact; index included in the key defeats stable keying on re-order |
| PositionDrilldown.tsx | 231 | `raw_text.slice(0, 500)` | ℹ️ Info | Deferred as IN-04 in 11-REVIEW.md; no security/money impact; cosmetic truncation without ellipsis |
| EditPositionDialog.tsx | 248-253 | `regenerateRequestId()` on every keystroke | ⚠️ Warning | Deferred as WR-03 in 11-REVIEW.md; keystroke-fragile idempotency — a pure retry after re-typing the same amount may mint a new id, turning a safe cached-200 replay into a new broker operation; non-blocking for phase goal |
| EditPositionDialog.tsx | 267-274 | InlineConfirm stays armed after partial-close error | ⚠️ Warning | Deferred as WR-04 in 11-REVIEW.md; a second ✓ click after a failed partial-close re-fires immediately; combined with WR-03 this is a double-fire risk on the partial-close path; non-blocking per review |
| SettingsForm.tsx | 208-211 | "Review changes" button not disabled while validate.isPending | ⚠️ Warning | Deferred as WR-05 in 11-REVIEW.md; a double-click submits validate twice; non-destructive (dry-run) but can stack toasts |
| useEmergency.ts | 33-41 | close success toast may overstate on partial failure | ℹ️ Info | Deferred as IN-01 in 11-REVIEW.md; ok/results not inspected; "All positions closed" shown even when only some accounts succeeded |

No TBD, FIXME, or XXX debt markers found in any phase-11 modified file.

---

### Human Verification Required

Items requiring operator testing on a live MT5 demo environment or running SPA:

#### 1. SC#1 — Row clears only after server 200 (positions close)

**Test:** On the Positions page with the demo bot connected, close a position. Observe the table.
**Expected:** The row disappears only after the server returns a 2xx from /close. Forcing a network failure keeps the row; the error toast appears.
**Why human:** Requires a live broker round-trip; cannot be verified by static inspection.

#### 2. SC#3 — Edit modal + drilldown survive background refetch

**Test:** Open the Edit Position modal or a drilldown. Wait 6+ seconds (≥2 poll cycles). Continue typing.
**Expected:** The modal stays open; typed SL/TP/lots values are unchanged; no collapse or reset.
**Why human:** Requires a running SPA with the 3s polling active.

#### 3. Partial-close 409 idempotency toast

**Test:** Submit a partial-close, then reuse the same request_id with a different close_volume (e.g. via devtools replay).
**Expected:** The server returns 409 and the SPA shows "That close already ran or the amount changed — refresh and retry."
**Why human:** Requires the live idempotency store (Phase 8); cannot simulate at the HTTP layer statically.

#### 4. Kill switch — CONFIRM CLOSE ALL at the broker

**Test:** With open demo positions, navigate to the kill switch, click Emergency Kill Switch, then CONFIRM CLOSE ALL.
**Expected:** All MT5 demo positions are closed, positions count drops to 0, TRADING PAUSED banner appears on Overview.
**Why human:** Requires a live MT5 demo session.

#### 5. Kill switch — Resume Trading re-enables signals

**Test:** After the kill switch fires, click Resume Trading on the kill-switch page.
**Expected:** trading-status.paused becomes false, PAUSED banner disappears, next incoming signal is processed.
**Why human:** Requires a live MT5 demo and running bot process.

#### 6. Settings toasts — SUX-01 success/rejection/revert

**Test:** (a) Change a settings value and confirm → "Settings saved for {account}." toast; (b) enter risk_value > 5% in percent mode → "Couldn't save: …" rejection toast; (c) click Revert last change → "Reverted last change for {account}." toast.
**Expected:** All three toast variants fire correctly.
**Why human:** Requires a running SPA against the server with real settings mutations.

#### 7. Settings account isolation — CR-02 runtime check

**Test:** With two accounts, edit account A's settings (open the confirm dialog). Switch to account B. Confirm that B's form shows B's values, not A's, and that clicking Confirm Change updates only B.
**Expected:** Account isolation: the CR-02 `key={account}` remount correctly resets rhf defaults and all local review state.
**Why human:** The `key` prop cannot be verified as correctly triggering remount and rhf reset without runtime observation.

#### 8. CSRF 403 rejection (end-to-end browser→server)

**Test:** Attempt any live-money POST (close, modify levels, confirm settings) with the X-CSRF-Token cookie deleted via devtools.
**Expected:** Server returns HTTP 403. The api() wrapper and Phase 8 test_api_csrf cover the server side; this confirms the browser→api() chain works end-to-end.
**Why human:** Requires a live browser + server session.

#### 9. Package legitimacy gate — T-11-SC

**Test:** Verify npmjs.com for react-hook-form (official repo github.com/react-hook-form), zod v4 (github.com/colinhacks/zod), @hookform/resolvers (rhf org). Confirm none added a postinstall script.
**Expected:** All three packages are the genuine official packages from trusted authors.
**Why human:** Supply-chain verification requires human inspection of the npm registry; cannot be automated by code inspection.

#### 10. Pitfall-9 opaque-render — dialog and select

**Test:** Open the Edit position dialog and a settings account selector against the dark brand background (#1a1a2e / #0f0f1a).
**Expected:** Both components render with an opaque background — no transparency, correct dark-brand colors.
**Why human:** Visual rendering cannot be verified by static code inspection.

---

### Gaps Summary

No blocking gaps. All code-level must-haves are VERIFIED:

- Money-safe mutation discipline implemented across all surfaces (no setQueryData, api() CSRF, disabled-while-pending, invalidateQueries only)
- Both code-review blockers (CR-01 partial-close rounding, CR-02 cross-account settings leak) fixed and verified in commit 481134d
- WR-01 (fail-safe PAUSED banner) and WR-02 (path-param encoding) also fixed in the same commit
- Vitest proves footgun mode-awareness and zod cap mirrors (15 tests pass)
- tsc strict build exits 0 (2026 modules, no type errors)
- All 8 requirement IDs (PAGE-05..08, SUX-01..04) are satisfied by substantive implementation
- Four lower warnings (WR-03..06) and four info items deferred as documented in 11-REVIEW.md; none block the phase goal

The 10 human_verification items are runtime/live-broker behaviors that cannot be proven by static code inspection. The code structure correctly implements every invariant they test; confirmation requires operator execution on the MT5 demo.

---

_Verified: 2026-06-07T20:30:00Z_
_Verifier: Claude (gsd-verifier)_
