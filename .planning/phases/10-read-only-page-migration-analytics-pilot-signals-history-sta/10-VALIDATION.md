---
phase: 10
slug: read-only-page-migration-analytics-pilot-signals-history-sta
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-06
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `10-RESEARCH.md` §Validation Architecture (HIGH confidence, codebase-verified 2026-06-06).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework (backend)** | pytest (existing `tests/` suite; Phase 8 added read-contract tests) |
| **Framework (frontend)** | None — no vitest/jest config, no `test` script in `frontend/package.json`. Frontend validation = `npm run build` (type-check + bundle) + manual parity gates. Do NOT add a runner this phase (NEW dep → Package Legitimacy Gate; not justified for a single-operator tool). |
| **Config file** | repo `pytest`/conftest (existing); run inside the Python 3.12 container (per project memory — local env differs) |
| **Quick run command** | `pytest tests/test_<route>_contract.py -x` (the route being widened) |
| **Full suite command** | `pytest -q` (in the 3.12 container) |
| **Estimated runtime** | ~quick: a few seconds per contract file; full: existing suite runtime |

---

## Sampling Rate

- **After every task commit:** Run the relevant `pytest tests/test_<route>_contract.py -x` (backend widenings) + `cd frontend && npm run build` (type-check + bundle) for frontend tasks.
- **After every plan wave:** Run full `pytest -q` (3.12 container) + `npm run build` + the `toFixed`/`Intl.NumberFormat` grep guard.
- **Before `/gsd:verify-work`:** Full suite green AND the four golden-number parity checks pass against the live legacy twin (SC#5).
- **Max feedback latency:** ~quick-test seconds per commit.

---

## Per-Task Verification Map

> Plan/task IDs are TBD until plans are written; this maps phase requirements → the verifying check. The planner must attach an `<automated>` (or Wave-0 dependency) to each backend task and a build/manual gate to each frontend task.

| Requirement | Behavior | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|------------|-----------------|-----------|-------------------|-------------|--------|
| PAGE-01 | `/api/v2/analytics` returns `by_source[]` (incl. `net_pnl_display`), `extremes`, `sources`, `avg_stages` | — / V4 (session-gated read) | route stays `Depends(require_user)` | contract (pytest) | `pytest tests/test_analytics_contract.py -x` | ❌ W0 | ⬜ pending |
| PAGE-01 | by-source money `_display` == `money_display(net_pnl)`; `win_rate`/`profit_factor` stay raw (D-14) | — | render `_display`, no re-round | contract | `pytest tests/test_analytics_contract.py -x` | ❌ W0 | ⬜ pending |
| PAGE-01 | `avg_stages` present ONLY when a source filter is active (mirror legacy `{% if avg_stages %}`) | — | — | contract | `pytest tests/test_analytics_contract.py -x` | ❌ W0 | ⬜ pending |
| PAGE-02 | `/api/v2/signals` surfaces `entry_zone_low/high`, `sl(+_display)`, `tp(+_display)`, `details`, `source_name` (D-12) | V5 (input/XSS) | render `details`/`raw_text` as text children, never `dangerouslySetInnerHTML` | contract | `pytest tests/test_signals_contract.py -x` | ❌ W0 (extend) | ⬜ pending |
| PAGE-03 | `/api/v2/history` round-trips all 5 filter params (`account/source/symbol/from_date/to_date`, AND logic) | V5 (SQLi) | parameterized asyncpg `$n` (verified `db.py:526-568`) | contract | `pytest tests/test_history_contract.py -x` | ⚠️ partial (Phase-8; extend) | ⬜ pending |
| PAGE-03 | history schema surfaces widened `sl`/`tp`/`status`/`source_name` (D-12) | — | `_display` for sl/tp prices | contract | `pytest tests/test_history_contract.py -x` | ⚠️ partial (extend) | ⬜ pending |
| PAGE-04 | `/api/v2/stages` active rows carry `started_at` (ISO-8601 + offset) sourced from the **raw** `created_at`, not the enriched dict (Pitfall 4) | — | — | contract | `pytest tests/test_stages_contract.py -x` | ❌ W0 | ⬜ pending |
| PAGE-04 | staged active surfaces correct `filled`/`total`/`distance` (D-13 — fixes legacy blank-cell bug) | — | — | contract | `pytest tests/test_stages_contract.py -x` | ❌ W0 | ⬜ pending |
| PAGE-01..04 | SPA renders only server `_display` strings — no client re-rounding (Pitfall 5) | — | — | grep guard | `grep -rn "toFixed\|Intl.NumberFormat" frontend/src/routes frontend/src/components/data` (expect none in cells) | guard | ⬜ pending |
| PAGE-03 | filter state survives a URL deep-link reload (bookmarkable, D-05) | — | — | manual (parity gate) | load `/app/history?account=X&symbol=Y`, reload, filters intact | manual | ⬜ pending |
| PAGE-04 | elapsed ticks per-second between 3s polls; epoch = server `started_at` (D-06) | — | — | manual (parity gate) | observe a card ≥10s; elapsed increments smoothly, not in 3s jumps | manual | ⬜ pending |
| PAGE-01..04 (SC#5) | SPA numbers === live legacy numbers | — | — | golden-number parity | capture both pages on the same DB snapshot; compare displayed values field-by-field | manual gate | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_analytics_contract.py` — PAGE-01 (by_source / `_display` / extremes / sources / avg_stages-only-when-source)
- [ ] `tests/test_signals_contract.py` — PAGE-02 (the D-12 widened fields exist + price `_display`)
- [ ] `tests/test_stages_contract.py` — PAGE-04 (`started_at` present + ISO-8601 + survives the enrichment chain — Pitfall 4; correct `filled`/`total`/`distance` — D-13)
- [ ] Extend the existing Phase-8 history contract test for PAGE-03 widened columns (D-12 confirmed) + 5-param round-trip
- [ ] No frontend test runner — rely on `npm run build` type-check + manual parity gates (do NOT install vitest this phase)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| SPA numbers === live legacy numbers (the cutover-readiness gate) | PAGE-01..04 / SC#5 | Requires a live DB snapshot + visual field-by-field comparison against the running legacy page | For each page: open SPA `/app/<page>` and legacy `/<page>` against the same DB; compare every displayed value. Document the known legacy staged blank-cell bug (D-13) as an explicit accepted exception — SPA shows correct values, legacy is buggy. |
| Bookmarkable filter deep-link | PAGE-03 (history), PAGE-01 (analytics) | URL/router behavior, not a unit assertion | Deep-link with query params, reload, confirm filters + results restore |
| Smooth per-second elapsed tick | PAGE-04 | Time-based UI behavior between polls | Watch a staged card ≥10s; elapsed increments every second, not in 3s poll jumps |

---

## Validation Sign-Off

- [ ] All backend tasks have an `<automated>` pytest contract verify or a Wave 0 dependency
- [ ] Sampling continuity: no 3 consecutive tasks without an automated verify (frontend tasks use `npm run build`)
- [ ] Wave 0 covers all ❌ MISSING contract-test references
- [ ] No watch-mode flags (one-shot `-x` runs)
- [ ] Golden-number parity gate defined for all four pages (SC#5)
- [ ] `nyquist_compliant: true` set in frontmatter once the above hold

**Approval:** pending
