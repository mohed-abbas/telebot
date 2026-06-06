# Deferred Items — Phase 09

Out-of-scope discoveries logged during execution (not fixed; pre-existing or
outside the current plan's blast radius).

## Pre-existing test-suite failures when PostgreSQL is unavailable

- **Discovered during:** Plan 09-02 full-suite verification (`pytest tests/`).
- **Symptom:** 71 failed + 19 errors with `AttributeError: 'NoneType' ...` on
  DB-backed tests when no PostgreSQL is reachable at the configured
  `TEST_DATABASE_URL` (localhost:5433).
- **Confirmed pre-existing:** Checking out the pre-plan-02 baseline (commit
  9bbe2b0) and running the same suite yields the identical 71 failed / 19 error
  count. Files like `tests/test_settings_form.py` pass fully (12/12) when run in
  isolation — the failures are cross-file fixture-ordering contamination once a
  session-scoped DB pool is absent, not logic regressions.
- **Plan-02 impact:** None. The three new `tests/test_spa_serving.py` tests skip
  cleanly without a DB (they depend on the `api_app` fixture which `pytest.skip`s
  on DB absence). Passed count rose 260 -> 263 (the 3 new serving tests); zero
  new failures introduced.
- **Disposition:** Out of scope for Plan 09-02 (serving substrate, presentation
  layer only). Resolve by running the suite against a live PostgreSQL
  (`docker compose -f docker-compose.dev.yml up -d`), or address the DB-absent
  fixture-isolation behaviour in a dedicated test-infra task.
- [09-03 Task 2] Pre-existing eslint react-refresh/only-export-components error in frontend/src/components/ui/button.tsx:64 (shadcn-generated buttonVariants export). Out of scope for plan 09-03 (Plan 01 artifact); does not affect build. Common to fix by exporting buttonVariants from a separate file, or disabling the rule for shadcn ui/.
