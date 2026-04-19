---
status: partial
phase: 06-staged-entry-execution
source: [06-VERIFICATION.md]
started: 2026-04-20T12:00:00Z
updated: 2026-04-20T12:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Text-only signal opens exactly 1 market position with SL != 0
expected: Send 'Gold buy now' to bot; exactly one position opens per enabled account with a valid SL; staged_entries row created with status=filled; no duplicate on re-send within dup-guard window
result: [pending]

### 2. Correlated follow-up arms N-1 pending stages; stages fire as price enters bands
expected: After text-only (stage 1 filled), send structured follow-up with entry_zone + SL + TP; N-1 rows appear in staged_entries as awaiting_zone; as price enters each band the zone-watch loop fires additional positions
result: [pending]

### 3. Kill switch drains all pending stages before closing positions; resume never un-cancels
expected: With pending stages present, toggle kill switch; staged_entries rows transition to cancelled BEFORE positions are closed; resume trading leaves cancelled rows as cancelled
result: [pending]

### 4. MT5 reconnect reconciles positions by idempotency comment
expected: Simulate reconnect while stage is in-flight; _sync_positions matches position by comment 'telebot-{signal_id}-s{n}'; no duplicate trade log entry; abandoned stages become abandoned_reconnect after signal_max_age_minutes
result: [pending]

### 5. Dashboard /staged shows live pending stages with price flash on update
expected: Navigate to /staged; pending stages panel renders correctly; price cells flash indigo when SSE pushes updates; empty-state shown when no pending stages
result: [pending]

### 6. Settings form validates hard caps and applies only to future signals
expected: Set max_stages=11 → rejected; set risk_value=5.1 → rejected; valid change shows confirmation modal with 'This applies to signals received AFTER you confirm'; confirm applies; signals already in flight use previous settings
result: [pending]

## Summary

total: 6
passed: 0
issues: 0
pending: 6
skipped: 0
blocked: 0

## Gaps
