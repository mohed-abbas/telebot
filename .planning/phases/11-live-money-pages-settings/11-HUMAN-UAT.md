---
status: partial
phase: 11-live-money-pages-settings
source: [11-VERIFICATION.md]
started: 2026-06-07T20:35:00Z
updated: 2026-06-07T20:35:00Z
---

## Current Test

[awaiting human testing — run on the VPS with the MT5 demo + running SPA]

## Tests

### 1. Positions — close clears row only after server 200 (SC#1)
expected: Row disappears from the table only after a confirmed 200 from `/positions/{account}/{ticket}/close`; a forced network failure or 500 keeps the row present with the error toast shown.
result: [pending]

### 2. Positions — Edit modal + drilldown survive ≥2 background refetch cycles (SC#3)
expected: Type an SL or lots value in the Edit modal; 6+ seconds pass (≥2 polls); the typed value remains unchanged and the modal stays open.
result: [pending]

### 3. Partial-close — 409 toast on id-reuse-different-params
expected: Submitting the same `request_id` with a different `close_volume` returns 409 and the SPA shows "That close already ran or the amount changed — refresh and retry."
result: [pending]

### 4. Partial-close — CR-01 guard rejects round-up-to-full (regression)
expected: On a 1.00-lot position, typing `0.998` (or any value that rounds up to the full open volume) is rejected by the Close lots guard — it does NOT submit a full close through the partial endpoint. A genuine partial (e.g. 0.50) still works and "Remaining after" reflects the rounded value.
result: [pending]

### 5. Kill switch — CONFIRM CLOSE ALL closes ALL live positions on the MT5 demo
expected: After Emergency Kill Switch → CONFIRM CLOSE ALL, all open demo positions close at the broker, the positions count drops to 0, and the TRADING PAUSED banner appears.
result: [pending]

### 6. Kill switch — Resume Trading re-enables live signals
expected: After Resume Trading, `trading-status.paused` becomes false, the PAUSED banner disappears, and the bot processes the next incoming signal.
result: [pending]

### 7. Settings — Save / validation-rejection / revert each surface a sonner toast (SUX-01)
expected: Save → "Settings saved for {account}."; cap breach → "Couldn't save: {first error}"; revert → "Reverted last change for {account}."
result: [pending]

### 8. Settings — account isolation: switching accounts resets the form (CR-02 runtime)
expected: After the `key={account}` fix, switching from account A to account B shows B's values; stashed review state from A is cleared; confirming B's form persists only B's values onto B.
result: [pending]

### 9. CSRF — a mutation without the X-CSRF-Token cookie is rejected 403
expected: A POST to any live-money endpoint (close, levels, partial-close, emergency, settings) made without the CSRF cookie returns HTTP 403 (Phase 8 `test_api_csrf` covers the server; this confirms the browser → `api()` → server echo is wired at runtime).
result: [pending]

### 10. Pitfall-9 opaque-render — dialog and select render opaque on the dark brand background
expected: Opening the Edit position dialog and a shadcn select over the dark brand background shows no transparent / see-through background. (Orchestrator pre-verified this via Playwright on a throwaway harness during 11-01; re-confirm in the real pages.)
result: [pending]

> Note: package legitimacy (T-11-SC) was verified during the 11-01 checkpoint — react-hook-form, zod v4 (colinhacks), and @hookform/resolvers confirmed genuine with no install hooks. Re-confirm only if desired.

## Summary

total: 10
passed: 0
issues: 0
pending: 10
skipped: 0
blocked: 0

## Gaps
