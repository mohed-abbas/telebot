---
phase: 05-foundation
plan: 01
subsystem: data-layer
tags: [phase-5, data-layer, settings, audit, asyncpg, postgres, set-01, set-02, set-04, set-05]
requirements: [SET-01, SET-02, SET-04, SET-05]
requirements_addressed: [SET-01, SET-02, SET-04, SET-05]

dependency_graph:
  requires:
    - v1.0 PostgreSQL schema (signals, trades, daily_stats, pending_orders)
    - asyncpg connection pool pattern in db.py
    - AccountConfig dataclass in models.py (unchanged — seed-only)
  provides:
    - 4 new tables: accounts, account_settings, settings_audit, failed_login_attempts
    - SettingsStore class with load_all / reload / effective / snapshot / update
    - AccountSettings frozen(slots=True) dataclass for Phase 6 snapshots
    - db.update_account_setting (whitelisted + audited write path)
    - db.{get_failed_login_count, log_failed_login, clear_failed_logins} for Plan 04
  affects:
    - bot.py::_setup_trading — now seeds DB and builds SettingsStore at boot
    - trade_manager.py — risk reads route through SettingsStore when attached

tech_stack:
  added:
    - "CHECK constraints on account_settings columns (range validation at DB layer)"
    - "dataclasses.replace() as the Phase 6 snapshot mechanism (frozen + slots)"
  patterns:
    - "Field whitelist before f-string SQL interpolation (mirrors _DAILY_STAT_FIELDS, SEC-01)"
    - "INSERT audit row + UPDATE target in single asyncpg conn.transaction() (atomic audit)"
    - "INSERT ... ON CONFLICT DO NOTHING for idempotent boot seed"
    - "Attribute-style dependency injection (tm.settings_store = store) to avoid constructor churn"

key_files:
  created:
    - path: settings_store.py
      lines: 92
      purpose: "In-process cache over account_settings ⋈ accounts with update-through + snapshot."
    - path: tests/test_db_schema.py
      lines: 61
      purpose: "SET-02 column + CHECK constraint verification."
    - path: tests/test_settings.py
      lines: 52
      purpose: "Audit-per-write, whitelist-blocks-injection, orphan + failed_login helpers."
    - path: tests/test_settings_store.py
      lines: 73
      purpose: "SettingsStore.effective frozen contract + cache invalidation on update."
    - path: tests/test_seed_accounts.py
      lines: 89
      purpose: "Seed idempotency, DB-wins-over-JSON, orphan detection, multi-account mapping."
  modified:
    - path: db.py
      lines: 675
      purpose: "4 new CREATE TABLE IF NOT EXISTS blocks, 2 indexes, _ACCOUNT_SETTINGS_FIELDS whitelist, 8 helpers (upsert/update/get/failed-login)."
    - path: models.py
      lines: 124
      purpose: "Added AccountSettings frozen(slots=True) dataclass."
    - path: bot.py
      lines: 458
      purpose: "_setup_trading seeds accounts + account_settings, logs orphans (D-25), builds and attaches SettingsStore to TradeManager."
    - path: trade_manager.py
      lines: 630
      purpose: "Module-level _effective() helper; TradeManager.settings_store attribute; 4 AccountConfig reads migrated to SettingsStore-via-_effective."
    - path: tests/conftest.py
      lines: 139
      purpose: "clean_tables TRUNCATE extended to 4 new tables; seeded_account fixture added."
    - path: tests/test_trade_manager.py
      lines: 224
      purpose: "3 new tests cover SettingsStore-wins, no-SettingsStore fallback, and fixed_lot mode fallback."

decisions:
  - "D-24 DB-wins policy enforced via INSERT ... ON CONFLICT DO NOTHING in seed path; verified by test_db_wins_over_json_default."
  - "D-25 orphan handling: surfaced via logger.warning; never auto-deleted (accounts row may still carry audit history or positions)."
  - "D-27 SettingsStore is optional on TradeManager — None fallback keeps v1.0 unit tests green without requiring a DB pool."
  - "D-29 audit + update inside one conn.transaction() — partial writes impossible; old_value captured before UPDATE."
  - "D-32 effective() returns frozen + slots AccountSettings so Phase 6 can call dataclasses.replace() for cheap per-stage snapshots."
  - "fixed_lot mode: risk_value carries the lot; trade_manager falls back to AccountConfig.risk_percent so calculate_lot_size keeps percent-of-equity semantics. Phase 6 branches here for a dedicated fixed-lot execution path."

metrics:
  duration: "~45 min (continuation — prior executor completed RED + partial GREEN for Task 1)"
  completed_date: "2026-04-19"
  tasks_completed: 3
  commits: 6
---

# Phase 5 Plan 1: Data Layer Summary

Built the v1.1 data layer — 4 additive PostgreSQL tables, a SettingsStore
abstraction that makes the DB the runtime source of truth for per-account
config, idempotent seed-from-JSON at boot, and migration of the 4 v1.0
`AccountConfig` reads in `trade_manager.py` to go through
`SettingsStore.effective()`. DDL is additive (no ALTER on v1.0 tables),
writes are atomically audited, and the read surface is a frozen dataclass
(`AccountSettings`) sized for Phase 6's `dataclasses.replace()`
snapshot-at-signal-receipt pattern.

## Commits

| Commit    | Message                                                                   |
| --------- | ------------------------------------------------------------------------- |
| `29a70b8` | test(05-01): add failing tests for accounts/settings schema + audit + failed_login |
| `5ed3bc8` | feat(05-01): add accounts/settings schema + helpers + AccountSettings dataclass |
| `0e018b9` | test(05-01): add failing tests for SettingsStore + seed idempotency       |
| `ecbf3f6` | feat(05-01): add SettingsStore + wire accounts.json seed in bot.py        |
| `cfbe8be` | test(05-01): add failing tests for trade_manager → SettingsStore migration |
| `f88b527` | feat(05-01): migrate trade_manager to SettingsStore.effective() for risk reads |

TDD gate sequence observed for every task: RED (`test(...)`) → GREEN
(`feat(...)`). No refactor commits needed (code landed clean on green).

## Files Created

- `settings_store.py` — 92 lines. Single `SettingsStore` class.
  - `load_all()` — warm cache from a single JOIN query (accounts ⋈ account_settings).
  - `reload(name)` — refresh one cache entry (or evict if row vanished).
  - `effective(name)` — returns the frozen AccountSettings from cache (no DB I/O).
  - `snapshot(name)` — `dataclasses.replace()` on effective() → fresh instance
    for Phase 6 stage persistence.
  - `update(name, field, value, actor)` — write-through to
    `db.update_account_setting()` then `reload(name)`.

- `tests/test_db_schema.py` — 5 tests. Verifies SET-02 columns and CHECK constraints.
- `tests/test_settings.py` — 5 tests. Audit writes, whitelist injection block,
  old_value chain, orphan, failed_login.
- `tests/test_settings_store.py` — 6 tests. Frozen contract, KeyError on
  unknown, snapshot equality, cache invalidation, audit row, load_all shape.
- `tests/test_seed_accounts.py` — 4 tests. Idempotency, DB-wins-over-JSON,
  orphan detection, multi-account per-account risk mapping (regression guard).

## Files Modified

### db.py (+228 lines)

- 4 new `CREATE TABLE IF NOT EXISTS` blocks: `accounts`, `account_settings`
  (with CHECK constraints on `risk_mode`, `risk_value`, `max_stages`,
  `default_sl_pips`, `max_daily_trades`), `settings_audit`, `failed_login_attempts`.
- 2 new indexes: `idx_settings_audit_account_ts`, `idx_failed_login_ip_ts`.
- `_ACCOUNT_SETTINGS_FIELDS` frozenset + `_validate_account_settings_field()`
  (mirrors existing `_DAILY_STAT_FIELDS` / `_validate_field` pattern at db.py:21-33).
- 8 new helpers:
  - `upsert_account_if_missing` / `upsert_account_settings_if_missing`
    (INSERT ... ON CONFLICT DO NOTHING; returns True iff a new row was inserted).
  - `get_account_settings` (JOIN account_settings + accounts).
  - `get_all_accounts` (alphabetical list of account names).
  - `update_account_setting` — whitelisted-field write; audit INSERT then UPDATE
    wrapped in `conn.transaction()`; audit is written with `old_value` captured
    from `account_settings` immediately before the UPDATE.
  - `get_orphan_accounts(seeded_names)` — names in `accounts` NOT in the list.
  - `get_failed_login_count` / `log_failed_login` / `clear_failed_logins`
    (consumed by Plan 04 login hardening).

### models.py (+19 lines)

```python
@dataclass(frozen=True, slots=True)
class AccountSettings:
    account_name: str
    risk_mode: str        # "percent" | "fixed_lot"
    risk_value: float     # percent of equity OR fixed lot size
    max_stages: int
    default_sl_pips: int
    max_daily_trades: int
    max_open_trades: int  # carried from accounts table
    max_lot_size: float   # carried from accounts table
```

`AccountConfig` (v1.0 JSON-parse dataclass) kept unchanged — it remains the
seed source.

### bot.py (+52 lines)

- Import `SettingsStore` alongside other trading imports.
- After `await db.init_db(...)`, loop over `accts_raw`:
  - Call `db.upsert_account_if_missing(...)` with every AccountConfig field
    from JSON. Returns True only for brand-new inserts.
  - On fresh insert: call `db.upsert_account_settings_if_missing` with
    `risk_value=raw["risk_percent"]` so the account's own risk mapping seeds
    correctly (fixed in Task 2 per multi-account regression guard).
  - On existing account: call `db.upsert_account_settings_if_missing` with
    defaults so a partial earlier boot (accounts inserted but settings not) is
    self-healing.
- `db.get_orphan_accounts(seeded_names)` → `logger.warning(... D-25 ...)` per orphan.
- After `tm = TradeManager(...)`: `SettingsStore(db_pool=db._pool)` →
  `load_all()` → `tm.settings_store = settings_store`.

### trade_manager.py (+34, -5 lines)

- New module-level helper `_effective(tm, acct)` returns
  `(risk_percent, max_lot_size, max_open_trades)`:
  - Prefers `SettingsStore.effective(acct.name)` when `tm.settings_store` is set.
  - When `risk_mode == "fixed_lot"`, `risk_percent` falls back to
    `acct.risk_percent` so `calculate_lot_size` keeps percent-of-equity math.
  - Catches `KeyError` from cache miss → falls back to AccountConfig
    (v1.0 unit tests do not construct a SettingsStore).
- `TradeManager.__init__` adds `self.settings_store = None` (attribute-style
  DI so Task 2 can assign without a constructor change).
- 4 AccountConfig field reads replaced in `_execute_open_on_account`:
  - max-open-trades check (line 182-183 pre-migration).
  - `calculate_lot_size(risk_percent=..., max_lot_size=...)` (line 226, 228
    pre-migration).

### tests/conftest.py

- `clean_tables` TRUNCATE extended to include `settings_audit`,
  `account_settings`, `accounts`, `failed_login_attempts` (child-before-parent
  order, RESTART IDENTITY CASCADE).
- New `seeded_account` fixture: creates `test-acct` with default settings row.

## Verification Command Transcripts

### Task 1 (schema + helpers)
```
$ pytest tests/test_db_schema.py tests/test_settings.py -x --tb=short
...
collected 10 items
tests/test_db_schema.py .....                                            [ 50%]
tests/test_settings.py .....                                             [100%]
============================== 10 passed in 0.40s ==============================
```

### Task 2 (SettingsStore + seed)
```
$ pytest tests/test_settings_store.py tests/test_seed_accounts.py -x --tb=short
...
collected 10 items
tests/test_settings_store.py ......                                      [ 60%]
tests/test_seed_accounts.py ....                                         [100%]
============================== 10 passed in 0.33s ==============================
```

### Task 3 (trade_manager migration) + no regressions
```
$ pytest tests/test_trade_manager.py tests/test_settings.py tests/test_settings_store.py \
         tests/test_seed_accounts.py tests/test_risk_calculator.py tests/test_db_schema.py
...
collected 50 items
tests/test_trade_manager.py ................                             [ 32%]
tests/test_settings.py .....                                             [ 42%]
tests/test_settings_store.py ......                                      [ 54%]
tests/test_seed_accounts.py ....                                         [ 62%]
tests/test_risk_calculator.py ..............                             [ 90%]
tests/test_db_schema.py .....                                            [100%]
============================== 50 passed in 1.31s ==============================
```

### Plan-relevant full sweep (92 tests)
```
$ pytest tests/test_db_schema.py tests/test_settings.py tests/test_settings_store.py \
         tests/test_seed_accounts.py tests/test_trade_manager.py tests/test_risk_calculator.py \
         tests/test_signal_parser.py --tb=short
...
============================== 92 passed in 1.78s ==============================
```

## Grep Acceptance Criteria Check

```
$ grep -c "CREATE TABLE IF NOT EXISTS accounts\b" db.py               → 1
$ grep -c "CREATE TABLE IF NOT EXISTS account_settings" db.py          → 1
$ grep -c "CREATE TABLE IF NOT EXISTS settings_audit" db.py            → 1
$ grep -c "CREATE TABLE IF NOT EXISTS failed_login_attempts" db.py     → 1
$ grep -c "_ACCOUNT_SETTINGS_FIELDS" db.py                             → 3 (≥ 2 required)
$ grep -c "def update_account_setting" db.py                           → 1
$ grep -c "INSERT INTO settings_audit" db.py                           → 1
$ grep -c "ALTER TABLE" db.py                                          → 0 (additive-only, Pitfall 17)
$ grep -c "class AccountSettings" models.py                            → 1
$ grep -c "class SettingsStore" settings_store.py                      → 1
$ grep -c "def effective" settings_store.py                            → 1
$ grep -c "def snapshot" settings_store.py                             → 1
$ grep -c "upsert_account_if_missing" bot.py                           → 1
$ grep -c "SettingsStore" bot.py                                       → 3 (import + construct + assign)
$ grep -c "D-25" bot.py                                                → 1
$ grep -c "_effective(self, acct)" trade_manager.py                    → 2 (max_open check + lot calc)
$ grep -c "self.settings_store" trade_manager.py                       → 1
```

All grep criteria satisfied except one minor deviation (see below).

## Deviations from Plan

### Minor — Pre-existing `AccountConfig` import in risk_calculator.py

**Rule:** Scope — NOT auto-fixed.
**Plan acceptance criterion:** `grep -c "AccountConfig" risk_calculator.py` returns 0.
**Actual:** returns 1 (the `from models import AccountConfig, Direction` line at
risk_calculator.py:14 pre-exists on `ec33620`).
**Resolution:** Not modified. The plan instructed `Do NOT modify risk_calculator.py`
and the import pre-dates this plan. `risk_calculator.py` does not READ any
AccountConfig attribute — the import is unused in the public surface.
Task 3's contract (all risk/lot reads route through SettingsStore) is still met.
Noted here so the verifier knows the mismatch is intentional. Fixing the stale
import belongs in a future cleanup pass, not this plan.

### Task 1 continuation note

The prior executor committed `test(05-01)` (29a70b8) for Task 1 RED then was
interrupted after adding `db.py` changes (whitelist + 4 DDL blocks + 8
helpers) without committing them. This executor inspected the uncommitted diff
against the plan's RESEARCH §DDL, confirmed it was complete and correct,
added the missing `models.AccountSettings` dataclass, ran the Task 1 tests
green, and committed as `5ed3bc8 feat(05-01)`.

### Cross-file test-suite flake (pre-existing, NOT a regression)

Running `pytest tests/` in full produces 14 failures tied to an asyncpg event
loop contention bug (`cannot perform operation: another operation is in
progress`) that affects `test_trade_manager.py`, `test_trade_manager_integration.py`,
and `test_rest_api_integration.py`. Verified via `git stash` of this plan's
changes that the same 14 failures exist on the parent commit `ec33620`. Our
additions increase the count to 18 only because the test_settings.py suite
becomes a victim of the same cross-file fixture issue when run AFTER the
broken tests (the tests themselves all pass when run in isolation or in
natural collection order up to test_rest_api_integration.py). Out of scope
for this plan; logged for a future TESTING infra pass.

## AccountSettings Dataclass Signature (Phase 6 / Phase 7 reference)

```python
from models import AccountSettings

# Import and use from SettingsStore:
settings: AccountSettings = store.effective("account-name")

# Fields:
settings.account_name       # str
settings.risk_mode          # "percent" | "fixed_lot"
settings.risk_value         # float — percent-of-equity OR fixed lot size
settings.max_stages         # int — staged entry count (1..10)
settings.default_sl_pips    # int — fallback SL distance (1..10000)
settings.max_daily_trades   # int — per-account daily trade cap (1..1000)
settings.max_open_trades    # int — carried from accounts table (v1.0)
settings.max_lot_size       # float — carried from accounts table (v1.0)

# frozen=True + slots=True → dataclasses.replace(settings) produces a
# cheap copy, suitable as a per-stage snapshot (Phase 6 SET-05).
```

## Threat Register Mitigations

| Threat ID | Mitigation                                                                     | Verified by                                                             |
| --------- | ------------------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| T-5-06    | audit INSERT + UPDATE inside one `conn.transaction()`                          | `test_audit_per_field_write`, `test_settings_audit_captures_old_value`  |
| T-5-07    | never DELETE on JSON-missing rows; `get_orphan_accounts` → logger.warning     | `test_orphan_reported_when_json_lacks_account`, grep `D-25` in bot.py   |
| T-5-SQLi  | whitelist before f-string interpolation in `update_account_setting`           | `test_field_whitelist_blocks_injection`                                 |

## Known Stubs

None. All code paths are wired and exercised by tests.

## Self-Check: PASSED

- [x] `db.py` contains all 4 CREATE TABLE IF NOT EXISTS blocks
- [x] `settings_store.py` exists with SettingsStore class
- [x] `models.py` contains AccountSettings frozen(slots=True) dataclass
- [x] `bot.py` seeds DB + builds SettingsStore before TradeManager
- [x] `trade_manager.py` has `_effective()` helper + `self.settings_store` attribute
- [x] All 6 commits exist in the worktree's git log
- [x] 50/50 plan-relevant tests pass
- [x] 92/92 plan + v1.0-regression tests pass (in isolation)
- [x] `.planning/STATE.md` NOT modified (orchestrator territory)
- [x] `.planning/ROADMAP.md` NOT modified (orchestrator territory)
