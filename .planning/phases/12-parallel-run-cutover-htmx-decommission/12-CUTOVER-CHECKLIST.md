---
status: partial
phase: 12-parallel-run-cutover-htmx-decommission
source: [12-RESEARCH.md, 12-CONTEXT.md]
started: 2026-06-07T00:00:00Z
updated: 2026-06-07T00:00:00Z
---

<!--
D-04 per-page MT5-demo parity sign-off (mirrors 06-HUMAN-UAT.md). One numbered row
per page in D-05 cutover order: analytics (pilot) -> signals -> history -> staged ->
overview -> settings -> positions -> kill-switch. Each row lists the four D-04 parity
items and a dated operator sign-off. Each 12-02 D-01 redirect commit references its row
number; an unsigned row blocks that page's redirect commit. The kill-switch row has NO
legacy GET page — it is verified-then-decommissioned (its sign-off gates the 12-03
Commit-1 deletion of /api/emergency-preview, not a redirect).

Sign-off form: change `result: [pending — sign: YYYY-MM-DD operator]` to the dated
operator name once the live MT5-demo parity check passes for that page.

The four D-04 parity items (verified against the live MT5 demo broker on the VPS):
  (a) SPA data matches legacy on live data
  (b) live-money actions behave correctly against the demo broker
  (c) no console errors
  (d) poll-safe modals/drilldowns (open modal/drilldown survives refetch cycles)
-->

## Current Test

[awaiting human testing]

## Tests

### 1. analytics (pilot) SPA matches legacy on live data
expected: SPA /app/analytics data matches legacy /analytics on live data; live-money actions behave correctly against the demo broker; no console errors; poll-safe modals/drilldowns
result: code complete + guard green locally 2026-06-07; live sign-off DEFERRED to VPS end-to-end acceptance

### 2. signals SPA matches legacy on live data
expected: SPA /app/signals data matches legacy /signals on live data; live-money actions behave correctly against the demo broker; no console errors; poll-safe modals/drilldowns
result: code complete + guard green locally 2026-06-07; live sign-off DEFERRED to VPS end-to-end acceptance

### 3. history SPA matches legacy on live data
expected: SPA /app/history data matches legacy /history on live data; live-money actions behave correctly against the demo broker; no console errors; poll-safe modals/drilldowns
result: code complete + guard green locally 2026-06-07; live sign-off DEFERRED to VPS end-to-end acceptance

### 4. staged SPA matches legacy on live data
expected: SPA /app/staged data matches legacy /staged on live data; live-money actions behave correctly against the demo broker; no console errors; poll-safe modals/drilldowns
result: code complete + guard green locally 2026-06-07; live sign-off DEFERRED to VPS end-to-end acceptance

### 5. overview SPA matches legacy on live data
expected: SPA /app/overview data matches legacy /overview on live data; live-money actions behave correctly against the demo broker; no console errors; poll-safe modals/drilldowns
result: code complete + guard green locally 2026-06-07; live sign-off DEFERRED to VPS end-to-end acceptance

### 6. settings SPA matches legacy on live data
expected: SPA /app/settings data matches legacy /settings on live data; live-money actions behave correctly against the demo broker (settings persist + apply to future signals only); no console errors; poll-safe modals/drilldowns
result: code complete + guard green locally 2026-06-07; live sign-off DEFERRED to VPS end-to-end acceptance

### 7. positions SPA matches legacy on live data
expected: SPA /app/positions data matches legacy /positions on live data; live-money actions behave correctly against the demo broker (close / modify levels / partial-close); no console errors; poll-safe modals/drilldowns
result: code complete + guard green locally 2026-06-07; live sign-off DEFERRED to VPS end-to-end acceptance

### 8. kill-switch verified-then-decommissioned (NO legacy GET page)
expected: SPA kill-switch (/app/emergency) data matches legacy kill_switch_preview on live data; live-money kill-switch action behaves correctly against the demo broker (drains pending stages then closes positions, resume never un-cancels); no console errors; poll-safe modals/drilldowns. NOTE: the kill switch has NO legacy GET page to redirect — this row is verified-then-decommissioned: its sign-off gates the 12-03 Commit-1 deletion of /api/emergency-preview, not a per-page redirect.
result: [pending — sign: YYYY-MM-DD operator]

## Summary

total: 8
passed: 0
issues: 0
pending: 8
skipped: 0
blocked: 0

## Gaps
