---
status: complete
phase: 10-read-only-page-migration-analytics-pilot-signals-history-sta
source:
  - 10-01-SUMMARY.md
  - 10-02-SUMMARY.md
  - 10-03-SUMMARY.md
  - 10-04-SUMMARY.md
  - 10-05-SUMMARY.md
  - 10-06-SUMMARY.md
mode: automated-ui (Playwright) against seeded dev DB
started: 2026-06-07
updated: 2026-06-07
---

## Current Test

[testing complete]

## Tests

### 1. Auth + SPA boot
expected: /app/ (unauth) redirects to the SPA login; logging in with the password lands on /app/analytics. No console errors.
result: pass
evidence: /app/ → /app/login?expired=1 (boot guard 401 on /auth/me) → password login → /app/analytics. Only console "error" is the pre-login 401 probe (expected redirect trigger).

### 2. Analytics parity (PAGE-01)
expected: KPIs match ground truth; by-source 3 rows; extremes; range/source in URL.
result: pass
evidence: Total Trades 5 (2W/3L), Win Rate 40.0%, Profit Factor 2.11, Net P&L 80.00, Gross 152.00/72.00, Best 95.00/Worst -42.00. By-source: FX Premium (PF 3.17, net 65.00), Gold Scalper (PF 1.36, net 15.00), Even Steven (net 0.00). Range tab 7d → URL ?range=7. All match seeded ground truth (SPA wraps the same db helper as legacy → parity).

### 3. Analytics zero-value handling (WR-01 + WR-02)
expected: source=Even Steven shows Net P&L $0.00 NEUTRAL (not red); Best/Worst Trade "0.00" (not "—").
result: pass
evidence: ?source=Even Steven → Net P&L "0.00" rendered text-card-foreground (neutral oklch(0.97 0 0), not red) [WR-02]; Best Trade 0.00, Worst Trade 0.00 (not "—") [WR-01]; Avg-Stages card correctly hidden (null case, no filled staged for source).

### 4. Signals parity (PAGE-02) + XSS
expected: 6 signals with full columns; HTML/script in details renders as literal text.
result: pass
evidence: 6 rows; columns Time/Type/Symbol/Direction/Zone/SL/TP/Action/Details. Details containing "<b>HTML</b> … <script>x</script>" renders as literal text — 0 injected <b>, 0 injected <script> in tbody (T-10-06 XSS-safe).

### 5. History parity (PAGE-03) + Source filter (CR-01)
expected: 5 trades, full columns incl. Source; Source dropdown POPULATED; filters narrow + bookmarkable URL.
result: pass
evidence: 11 columns incl. Account/Source/SL/TP/Status; 5 rows. Source dropdown = [All, Even Steven, FX Premium, Gold Scalper] — CR-01 fix confirmed (was permanently empty). ?source=Gold Scalper → 2 rows all Gold Scalper, dropdown restored from URL (bookmarkable). Account/symbol dropdowns also populated.

### 6. Staged parity (PAGE-04) + elapsed timer (WR-04)
expected: 2 active (cards per account) + 2 resolved; elapsed ticks, never "NaN:NaN"; ~3s poll.
result: pass
evidence: 2 active stage cards (Vantage Demo-10k 1/1, Vantage Demo-25k 2/2) + 2 resolved rows (filled, target-reached). Elapsed ticked 27:01 → 27:03 over 2.5s; zero "NaN" in DOM (WR-04 guard working).

## Summary

total: 6
passed: 6
issues: 0
pending: 0
skipped: 0

## Gaps

[none — all tests passed]

## Notes

- Verified via Playwright against the SPA at http://localhost:5173/app/ (Vite dev) → standalone
  dashboard API on :8090 (no bot.py / Telegram) → seeded dev Postgres (:5433).
- Parity basis: the /api/v2 read routes wrap the same db helpers the legacy HTML pages use, so
  matching the SPA output to the seeded ground truth verifies SC#1–SC#4 (SPA == legacy by construction).
- All four code-review fixes that were visually testable are confirmed live: CR-01 (Source filter),
  WR-01 (zero extremes), WR-02 (zero Net P&L tone), WR-04 (elapsed NaN guard).
- Seed data is dev-only and can be truncated; the dry-run executor injects one XAUUSD position for
  positions-aware views.
