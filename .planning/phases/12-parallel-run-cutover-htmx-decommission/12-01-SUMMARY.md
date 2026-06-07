---
phase: 12-parallel-run-cutover-htmx-decommission
plan: 01
subsystem: cutover-guards
tags: [test, cutover, teardown, htmx-decommission, operator-signoff]
requires:
  - tests/conftest.py::api_app (Phase 08 fixture)
  - tests/test_spa_serving.py::test_api_not_shadowed_by_spa_mount (CUT-01 evidence, Phase 09)
provides:
  - tests/test_cutover_redirects.py (CUT-02 per-page redirect guard)
  - tests/test_post_teardown.py (CUT-03 deleted-404 / surviving-200 / import-api guard)
  - .planning/phases/12-.../12-CUTOVER-CHECKLIST.md (D-04 operator parity sign-off)
affects:
  - Plan 12-02 (each D-01 redirect commit turns one cutover-test row green + signs one checklist row)
  - Plan 12-03 (teardown turns the post-teardown guard green)
tech-stack:
  added: []
  patterns:
    - "Reuse conftest api_app fixture via local client(api_app)+TestClient (no in-file env-injection)"
    - "follow_redirects=False + status 303 + exact Location assertion for redirect guards"
    - "deleted-route 404 with 'id=\"root\"' not in body (proves real 404, not SPA catch-all)"
key-files:
  created:
    - tests/test_cutover_redirects.py
    - tests/test_post_teardown.py
    - .planning/phases/12-parallel-run-cutover-htmx-decommission/12-CUTOVER-CHECKLIST.md
  modified: []
decisions:
  - "CUT-01 parallel-run satisfied by existing Phase-9 routing with ZERO code change; evidence is the existing precedence test (confirmed green-or-skipped)"
  - "New guard files are intentionally RED per-row until 12-02/12-03 land; collect-clean is the Wave-0 acceptance bar, not all-green"
  - "kill-switch checklist row is verified-then-decommissioned (no legacy GET page); its sign-off gates /api/emergency-preview deletion, not a redirect"
metrics:
  duration: ~4min
  completed: 2026-06-07
  tasks: 3
  files: 3
---

# Phase 12 Plan 01: Wave-0 Cutover Guards + Operator Sign-off Summary

Establishes the three Wave-0 gates the rest of the phase depends on — a per-page
303-redirect guard (CUT-02), a post-teardown deleted-404/surviving-200 guard
(CUT-03), and a D-05-ordered operator parity checklist (D-04) — and formally
confirms CUT-01 (parallel-run) is already satisfied by Phase-9 routing with no
code change. No production code was touched.

## What Was Built

- **tests/test_cutover_redirects.py** — CUT-02 progress guard. Parametrized over
  the 7 D-05 legacy pages, asserting each `GET /<page>` 303-redirects to
  `/app/<page>` with `follow_redirects=False` + exact `Location`. Plus
  `test_unauth_redirects_to_app_login` asserting an unauth bounce goes to a
  `Location` starting `/app/login`. 8 cases collected; each turns green
  incrementally as 12-02 cuts a page over (the unauth case turns green at 12-03
  Commit 1's `_verify_auth` repoint, RESEARCH Pitfall 4).

- **tests/test_post_teardown.py** — CUT-03 acceptance guard. Asserts deleted
  routes (`/overview`, `/stream`, `/partials/positions`) return a real 404 with
  `'id="root"'` not in the body (proves the SPA catch-all did not swallow them),
  surviving routes serve (`/health` 200, `/app/` 200, `/api/v2/trading-status`
  JSON precedence, `/` → 303 `/app/`), and `test_api_imports_resolve` runs
  `import api` to guard the 6 MUST-SURVIVE dashboard.py helpers.

- **12-CUTOVER-CHECKLIST.md** — D-04 operator sign-off mirroring 06-HUMAN-UAT.md:
  frontmatter (`status: partial`, phase, source, started, updated) → 8 numbered
  rows in D-05 order (analytics pilot → signals → history → staged → overview →
  settings → positions → kill-switch), each carrying the 4 D-04 parity items and
  a dated `result: [pending — sign: YYYY-MM-DD operator]` line → `## Summary`
  tally (total 8, pending 8) → `## Gaps`. The kill-switch row is documented as
  verified-then-decommissioned (no redirect; gates the /api/emergency-preview
  deletion in 12-03).

## CUT-01 Confirmation (parallel-run — zero code change)

CUT-01 (parallel-run: SPA `/app` and legacy HTMX `/` both reachable, `/api/v2`
never shadowed by the `/app` mount) is **already satisfied by existing Phase-9
routing** and required **no code change in this plan** (RESEARCH §CUT-01). The
standing evidence is `tests/test_spa_serving.py::test_api_not_shadowed_by_spa_mount`,
which asserts the /api/v2 router (registered before the /app static mount) wins
precedence. Re-run in this plan it was **SKIPPED** (PostgreSQL absent locally — the
`api_app` conftest fixture pytest.skips) which is the acceptance bar (green-or-skip,
never FAIL). T-12-01 (Spoofing — API/mount precedence) is mitigated by that
standing assertion; no new plumbing was built.

## Verification

- `pytest tests/test_cutover_redirects.py tests/test_post_teardown.py --collect-only -q`
  → **16 items collected, exit 0** (8 cutover + 8 teardown) in a Python-3.12
  container with project deps. Both files collect clean — the Wave-0 bar.
- `pytest tests/test_spa_serving.py::test_api_not_shadowed_by_spa_mount -x`
  → **1 skipped, exit 0** (PostgreSQL absent). Green-or-skip, never FAIL — CUT-01
  precedence intact.
- `grep -v '^#' 12-CUTOVER-CHECKLIST.md | grep -c 'expected:'` → **8** parity rows.

The per-page redirect assertions and the deleted-404 assertions are intentionally
RED right now and go GREEN incrementally as Waves 2/3 land — this is correct and
expected behavior, not a defect.

## Test Environment Note

pytest is not installed on the host (Python 3.14, no project venv) and PostgreSQL
is absent locally. Per project memory, the suite runs in a Python-3.12 container;
collection and the CUT-01 test were executed via
`docker run --rm -v "$PWD":/app python:3.12-slim` with requirements installed,
giving authoritative collect-only and skip results.

## Deviations from Plan

None — plan executed exactly as written. The intended-RED assertions and the
PostgreSQL-absent SKIP are explicitly sanctioned by the plan's acceptance criteria,
not deviations.

## Authentication Gates

None.

## Known Stubs

None. The two test files are standing guards whose RED assertions are intentional
phase-progress markers (documented in each module docstring), not unwired stubs.
The checklist's `[pending — sign: ...]` rows are the designed operator-sign-off
placeholders (D-04), resolved by 12-02/12-03 operator UAT.

## Self-Check: PASSED

- FOUND: tests/test_cutover_redirects.py
- FOUND: tests/test_post_teardown.py
- FOUND: .planning/phases/12-parallel-run-cutover-htmx-decommission/12-CUTOVER-CHECKLIST.md
- FOUND: .planning/phases/12-parallel-run-cutover-htmx-decommission/12-01-SUMMARY.md
- FOUND commit b7e9a88 (test 12-01 cutover redirects)
- FOUND commit 109af05 (test 12-01 post-teardown)
- FOUND commit 789617c (docs 12-01 cutover checklist)
