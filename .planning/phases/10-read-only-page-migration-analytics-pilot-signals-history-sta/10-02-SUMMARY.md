---
phase: 10-read-only-page-migration-analytics-pilot-signals-history-sta
plan: 02
subsystem: api
tags: [api, stages, serialization, timestamps, page-04]
requires:
  - "api/stages.py list_stages (Phase 08 Plan 03)"
  - "api/formatting.py ts_machine/ts_display (Phase 08 Plan 01)"
  - "db.get_pending_stages() raw created_at (TIMESTAMPTZ)"
provides:
  - "GET /api/v2/stages active rows carry machine started_at (ISO-8601 + UTC offset)"
  - "started_at_display human twin on active rows"
affects:
  - "SPA staged page client-side elapsed timer (D-06) — now has a server epoch (PAGE-04)"
tech-stack:
  added: []
  patterns:
    - "Raw-row plumbing via zip(active, raw_active) so a dropped field survives an enrichment chain (Pitfall 4)"
    - "ts_machine/ts_display _display-twin shape reused from _enrich_resolved"
key-files:
  created:
    - "tests/test_stages_contract.py"
  modified:
    - "api/stages.py"
decisions:
  - "started_at sourced from the RAW get_pending_stages() created_at, not the enriched dict (which drops it after building `elapsed`) — Pitfall 4"
  - "D-13: active rows surface real filled/total/distance_str keys; legacy blank-cell filled_count/total_stages NOT introduced"
  - "Live HTTP contract layer skips on asyncpg InterfaceError (event-loop bound outside the project Python 3.12 test container); deterministic _enrich_active unit tests carry the started_at proof DB-free"
metrics:
  duration: "12min"
  completed: "2026-06-06"
  tasks: 2
  files: 2
---

# Phase 10 Plan 02: Stages `started_at` Read-Only Enrichment Summary

Widened `GET /api/v2/stages` ACTIVE rows with a server `started_at` (ISO-8601 + UTC offset, D-09) sourced from the RAW `get_pending_stages().created_at` so the SPA's client-side elapsed timer (D-06) has a server epoch to count from — bot core byte-for-byte untouched.

## What Was Built

- **`api/stages.py` — `_enrich_active(stage, raw)` widened (Task 1):** the function now receives BOTH the enriched display dict AND the raw `get_pending_stages()` row. When `raw["created_at"]` is a `datetime`, the output gains `started_at = ts_machine(created_at)` (ISO-8601 + UTC offset) and `started_at_display = ts_display(created_at)`, mirroring the `_enrich_resolved` timestamp-twin shape. Existing `band_low`/`band_high`/`current_price` `_display` twins are preserved unchanged.
- **`api/stages.py` — `list_stages` zip (Task 1):** the active comprehension now zips the enriched dicts with their positionally-aligned raw rows — `[_enrich_active(enriched, raw) for enriched, raw in zip(active, raw_active)]` — so the raw `created_at` survives to `_enrich_active`. This is the Pitfall-4 fix: `_enrich_stage_for_ui` (dashboard.py) DROPS `created_at` after computing its `elapsed` string, so the timestamp lives ONLY in the raw row.
- **`tests/test_stages_contract.py` (Task 2):** new contract test in two layers:
  1. **Pure unit tests on `_enrich_active`** (no DB) — prove `started_at`/`started_at_display` are plumbed from the raw `created_at` (ISO+offset), band/price twins survive, the Pitfall-4 invariant holds (populated `elapsed` ⇒ populated `started_at`), and D-13 key correctness (real `filled`/`total`; no legacy `filled_count`/`total_stages`). These are the deterministic RED→GREEN driver and run without Postgres.
  2. **Live HTTP contract** (`session_client` + `_login` reused from `test_api_contract.py`) — asserts 200, `active`/`resolved` keys, and the started_at/Pitfall-4/D-13 invariants on every active row. Skips cleanly when the DB-backed `api_app` fixture is unavailable in the current host env.

## TDD Cycle

- **RED** (`9bafae6`): test asserting `_enrich_active(enriched, raw)` adds `started_at` — failed with `TypeError: _enrich_active() takes 1 positional argument but 2 were given`.
- **GREEN** (`4fc8510`): widened `_enrich_active` + zipped raw rows in `list_stages` — 2 unit tests pass.
- **Test refinement** (`567db6f`): fixture-level skip guard for the live HTTP layer so `-x` stays green outside the project's Python 3.12 test container.

No REFACTOR commit — the GREEN implementation is minimal and clean.

## Verification

- `pytest tests/test_stages_contract.py -x` → `2 passed, 1 skipped`, exit 0.
- `api/stages.py` acceptance: `grep -c started_at` = 4 (≥2), `zip(active, raw_active)` matches, `grep -c ts_machine` = 4 (≥2), zero `filled_count|total_stages|distance_to_band` matches.
- `git diff --stat executor.py trade_manager.py db.py mt5_connector.py dashboard.py` (vs base `707fe18`) → empty: bot core + legacy dashboard untouched. Only `api/stages.py` + the new test changed.

## Deviations from Plan

None — plan executed exactly as written.

## Environment Note

This host runs Python 3.14 with the dependency venv present but Postgres reachable only intermittently and the conftest `api_app` fixture's `asyncio.get_event_loop().run_until_complete` pattern conflicts with the TestClient loop (asyncpg `InterfaceError: another operation is in progress`). Per the project's local-verification constraint, the DB-backed contract suite is designed to run green inside the Python 3.12 test container; the deterministic `_enrich_active` unit tests prove the `started_at` plumbing DB-free here, and the live HTTP layer skips cleanly (same behaviour as the existing `test_api_contract.py`, which skips 24 in this env). The live layer will exercise the full route when run in the proper container.

## Threat Surface

No new surface. `GET /api/v2/stages` stays `Depends(require_user)` (T-10-03 mitigated); no new query construction (`get_pending_stages()` unchanged — T-10-04 accept); zero new dependencies (T-10-SC n/a). This is a serialization-only widening adding one timestamp field.

## Self-Check: PASSED

- `api/stages.py` — FOUND (modified, contains `started_at` + `zip(active, raw_active)`)
- `tests/test_stages_contract.py` — FOUND (created)
- Commit `9bafae6` (RED) — present
- Commit `4fc8510` (GREEN) — present
- Commit `567db6f` (test refinement) — present
