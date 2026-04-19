---
phase: 06
plan: 01
subsystem: staged-entry-foundation
tags: [phase-6, db, parser, correlator, tdd]
requires: []
provides: [staged_entries-table, signal_daily_counted-table, SignalType.OPEN_TEXT_ONLY, SignalCorrelator, 9-db-helpers]
affects: [db.py, models.py, signal_parser.py, signal_correlator.py, bot.py, tests/conftest.py]
tech_added:
  patterns:
    - additive-ddl-in-init-schema
    - asyncio-lock-guarded-in-memory-cache
    - line-anchored-regex-with-word-boundaries
    - one-to-one-pairing-with-most-recent-wins
    - on-conflict-do-nothing-returning-idempotency
key_files:
  created:
    - signal_correlator.py
    - tests/test_staged_db.py
    - tests/test_signal_parser_text_only.py
    - tests/test_correlator.py
    - .planning/phases/06-staged-entry-execution/06-01-SUMMARY.md
  modified:
    - db.py
    - models.py
    - signal_parser.py
    - bot.py
    - tests/conftest.py
decisions:
  - "[06-01] Text-only recognizer anchored with ^...$ and \\b..\\b to enforce D-02 no-numerics at regex level — priced 'now' messages still route to _RE_OPEN first"
  - "[06-01] UNIQUE constraint on staged_entries.mt5_comment enforces D-25 idempotency at schema level (T-06-01 mitigation)"
  - "[06-01] get_pending_stages LIMIT coerced via int() before f-string interpolation (T-06-02 mitigation)"
  - "[06-01] SignalCorrelator uses a single asyncio.Lock for the whole orphan dict — correctness over throughput at the expected <10 signals/min rate"
  - "[06-01] Orphan eviction is lazy (runs on every register/pair), not periodic — avoids a background task for Phase 6 v1.1"
metrics:
  duration_minutes: 12
  tasks_completed: 3
  files_touched: 9
  completed_date: 2026-04-20
---

# Phase 06 Plan 01: Data Foundation + Text-Only Parser + Correlator Summary

## Overview

One-liner: Phase 6 foundation — additive DDL for `staged_entries` (UNIQUE `mt5_comment`, JSONB `snapshot_settings`, composite index) and `signal_daily_counted` (PK-based idempotency), 9 async DB helpers, `SignalType.OPEN_TEXT_ONLY` + `StagedEntryRecord`, line-anchored "now" parser branch, and an asyncio-safe `SignalCorrelator` wired onto `TradeManager` at startup.

## What Was Built

### Tables (db.py)

```sql
-- staged_entries (D-37..D-39)
CREATE TABLE IF NOT EXISTS staged_entries (
    id                 SERIAL PRIMARY KEY,
    signal_id          INTEGER NOT NULL REFERENCES signals(id),
    stage_number       INTEGER NOT NULL,
    account_name       TEXT NOT NULL REFERENCES accounts(name),
    symbol             TEXT NOT NULL,
    direction          TEXT NOT NULL CHECK (direction IN ('buy','sell')),
    zone_low           DOUBLE PRECISION NOT NULL,
    zone_high          DOUBLE PRECISION NOT NULL,
    band_low           DOUBLE PRECISION NOT NULL,
    band_high          DOUBLE PRECISION NOT NULL,
    target_lot         DOUBLE PRECISION NOT NULL,
    snapshot_settings  JSONB NOT NULL,
    mt5_comment        TEXT NOT NULL UNIQUE,    -- T-06-01 mitigation
    mt5_ticket         BIGINT,
    status             TEXT NOT NULL DEFAULT 'awaiting_zone',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    filled_at          TIMESTAMPTZ,
    cancelled_reason   TEXT
);
CREATE INDEX IF NOT EXISTS idx_staged_entries_active
    ON staged_entries(status, account_name, signal_id);

-- signal_daily_counted (D-18 idempotency)
CREATE TABLE IF NOT EXISTS signal_daily_counted (
    signal_id     INTEGER NOT NULL REFERENCES signals(id),
    account_name  TEXT NOT NULL REFERENCES accounts(name),
    date          DATE NOT NULL DEFAULT CURRENT_DATE,
    PRIMARY KEY (signal_id, account_name, date)
);
```

### DB Helpers (db.py)

| Helper | Purpose | D-ref |
|--------|---------|-------|
| `create_staged_entries(rows)` | Bulk insert; returns ids in order | D-37 |
| `update_stage_status(id, status, mt5_ticket=, cancelled_reason=)` | Status mutation; sets `filled_at=NOW()` when status='filled' | D-37 |
| `get_pending_stages(account_name=, limit=)` | Rows in `awaiting_followup` / `awaiting_zone` | D-36 |
| `get_active_stages()` | `awaiting_zone` only (polling helper) | D-23 |
| `drain_staged_entries_for_kill_switch()` → count | Terminal-cancel all pending | D-21 |
| `cancel_unfilled_stages_for_signal(signal_id, reason)` → count | Stage-1 exit cascade | D-16 |
| `get_recently_resolved_stages(limit=50)` | For `/staged` "Recently resolved" | D-36 |
| `mark_signal_counted_today(signal_id, account_name)` → bool | ON CONFLICT DO NOTHING RETURNING idempotency | D-18 |
| `get_stage_by_comment(mt5_comment)` | Reconcile/idempotency probe | D-25 |

### Models (models.py)

- `SignalType.OPEN_TEXT_ONLY = "open_text_only"` (enum value, not a bool flag)
- `StagedEntryRecord` frozen+slotted dataclass mirroring the `staged_entries` schema
- `GlobalConfig.correlation_window_seconds: int = 600` (D-04 default)
- `GlobalConfig.signal_max_age_minutes: int = 30` (Research Q2 default, for Plan 04)

### SignalCorrelator (signal_correlator.py)

```python
class SignalCorrelator:
    def __init__(self, window_seconds: int = 600) -> None: ...
    async def register_orphan(self, signal_id: int, symbol: str, direction: str) -> None
    async def pair_followup(self, symbol: str, direction: str) -> int | None
```

Guarantees:
- **D-05 (most-recent wins):** `list.pop()` from the tail of the per-(symbol,direction) list.
- **D-06 (one-to-one):** paired orphan is evicted from the list immediately; a second `pair_followup` returns `None`.
- **D-07 (window expiry):** lazy `_evict_expired(key)` runs on every mutation; no background task required.
- **Thread safety:** single `asyncio.Lock` guards all state.

### Parser (signal_parser.py)

New `_RE_OPEN_TEXT_ONLY` regex, line-anchored (`^...$`) with `\b(?:now|asap|immediate)\b` so any trailing digit or extra token forces a miss → priced "Gold sell now 4978 - 4982" keeps routing through `_RE_OPEN`. Dispatch branch 8 emits `SignalType.OPEN_TEXT_ONLY` with `entry_zone=None`, `sl=None`, `tps=[]`.

### Bot wiring (bot.py)

In `_setup_trading`, after `tm.settings_store = settings_store`:

```python
from signal_correlator import SignalCorrelator
correlator = SignalCorrelator(
    window_seconds=global_config.correlation_window_seconds,
)
tm.correlator = correlator
```

Attached BEFORE the Telegram handler is installed, so the very first parsed signal has a correlator to read.

## Commits

| Task | Commit | Subject |
|------|--------|---------|
| T0 (RED scaffolds) | `d836466` | `test(06-01): add Phase 6 Wave-0 scaffolds for staged_entries, correlator, text-only parser` |
| T1 (DDL + helpers + models) | `6d1206e` | `feat(06-01): staged_entries + signal_daily_counted tables, 9 DB helpers, StagedEntryRecord` |
| T2 (parser + correlator + bot) | `eb1bb65` | `feat(06-01): OPEN_TEXT_ONLY parser + SignalCorrelator module + bot.py wiring` |

## Test Results

**17 new tests green + 42 pre-existing parser tests green (59 total).**

| Suite | Tests | Status |
|-------|-------|--------|
| `tests/test_staged_db.py` | 6 | green |
| `tests/test_signal_parser_text_only.py` | 5 | green |
| `tests/test_correlator.py` | 6 | green |
| `tests/test_signal_parser.py` (regression) | 42 | green |

Run: `pytest tests/test_signal_parser_text_only.py tests/test_correlator.py tests/test_staged_db.py tests/test_signal_parser.py -v` → `59 passed in 5.41s`.

## TDD Gate Compliance

- **RED gate (T0):** `d836466` — all new tests collect; run exits with `ImportError` (signal_correlator missing), `AttributeError` (`db.create_staged_entries`, `SignalType.OPEN_TEXT_ONLY`). RED confirmed.
- **GREEN gate (T1):** `6d1206e` — DB helpers + enum/dataclass turn `test_staged_db.py` green and fix the `OPEN_TEXT_ONLY` AttributeError (but parser tests still fail because the regex isn't wired).
- **GREEN gate (T2):** `eb1bb65` — parser branch + correlator module turn the remaining 11 tests green.

Sequence `test → feat → feat` observed in `git log`.

## Key Decisions (Claude's Discretion)

1. **Regex shape (`^\s*...\s*$` + `\b...\b`):** line-anchored rather than using a trailing lookahead. This is the simplest way to enforce D-02 (no numerics in text-only match) without a secondary negative lookahead. Alternative (negative lookahead for `\d`) was more surgical but harder to read; the anchored form mirrors the existing `_RE_OPEN` idiom and passes all 5 unit tests.
2. **Correlator lock granularity:** single `asyncio.Lock` covering the whole orphan dict, not per-key locks. At the realistic <10 signals/min rate there is no contention; the tighter per-key model was over-engineered.
3. **Lazy GC instead of periodic sweep:** `_evict_expired(key)` runs on every `register_orphan` / `pair_followup`. No background task required — which matches Phase 5's "do not add background loops we don't need" posture. T-06-05 mitigation is still satisfied because expired orphans are dropped before the dict can grow.
4. **`get_pending_stages` LIMIT interpolation:** coerced via `int(limit)` before f-string interpolation (T-06-02 mitigation). All other params use asyncpg `$1` binding.
5. **`seeded_signal` fixture kept local to `tests/test_staged_db.py`:** matches existing per-file fixture idioms (cf. `test_signal_parser.py`). Promoting to `conftest.py` can wait until a second file needs it.

## Deviations from Plan

None — plan executed exactly as written. All 3 tasks landed, 17 new tests green, zero regression on the 42 pre-existing parser tests.

## Threat Model Compliance

| Threat ID | Disposition | Landed Mitigation |
|-----------|-------------|-------------------|
| T-06-01 (Tampering, mt5_comment) | mitigate | `UNIQUE` on `staged_entries.mt5_comment` in DDL |
| T-06-02 (Injection, LIMIT) | mitigate | `int(limit)` coercion before f-string interpolation in `get_pending_stages` |
| T-06-03 (Repudiation, daily-limit burn) | mitigate | PK `(signal_id, account_name, date)` + `ON CONFLICT DO NOTHING RETURNING` in `mark_signal_counted_today` |
| T-06-04 (Info disclosure, snapshot_settings) | accept | Operator-internal, no PII |
| T-06-05 (DoS, orphan dict growth) | mitigate | Lazy window-based eviction on every register/pair call |
| T-06-06 (EoP, tm.correlator) | accept | Same-process trust model |
| T-06-07 (Spoofing, text-only source) | accept | Upstream Telegram whitelist |

## Self-Check: PASSED

Files verified:
- signal_correlator.py — FOUND
- tests/test_staged_db.py — FOUND
- tests/test_signal_parser_text_only.py — FOUND
- tests/test_correlator.py — FOUND

Commits verified in `git log`:
- d836466 — FOUND
- 6d1206e — FOUND
- eb1bb65 — FOUND

Acceptance greps (spot-check):
- `CREATE TABLE IF NOT EXISTS staged_entries` in db.py — present
- `idx_staged_entries_active` in db.py — present
- `OPEN_TEXT_ONLY` in models.py — present
- `class StagedEntryRecord` in models.py — present
- 9 `async def` helpers for staged_entries in db.py — present
- `SignalCorrelator` + `asyncio.Lock` in signal_correlator.py — present
- `tm.correlator` in bot.py — present
