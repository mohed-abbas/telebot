---
phase: 12-parallel-run-cutover-htmx-decommission
plan: 02
subsystem: cutover-redirects
tags: [cutover, htmx-decommission, redirect, spa, operator-signoff, deploy-at-end]
requires:
  - dashboard.py legacy @app.get page routes (Phase 5/6/7 HTMX pages)
  - /app/<page> SPA routes (Phase 9/10/11)
  - tests/test_cutover_redirects.py (12-01 CUT-02 guard)
  - .planning/phases/12-.../12-CUTOVER-CHECKLIST.md (12-01 D-04 sign-off doc)
provides:
  - dashboard.py 7 legacy page routes 303-redirect to /app/<page>
  - dashboard.py root / flips to /app/ (was /overview)
  - 12-CUTOVER-CHECKLIST.md rows annotated code-complete (live sign-off deferred to VPS)
affects:
  - Plan 12-03 (teardown deletes the now-redirect-only legacy route blocks + repoints _verify_auth to /app/login; turns test_unauth_redirects_to_app_login green)
tech-stack:
  added: []
  patterns:
    - "Per-page route-body swap to RedirectResponse(url='/app/<page>', status_code=303), keeping decorator + signature + Depends(_verify_auth)"
    - "One page per commit (D-01) for one-page git-revert rollback; root flipped LAST (D-02)"
key-files:
  created:
    - .planning/phases/12-parallel-run-cutover-htmx-decommission/12-02-SUMMARY.md
  modified:
    - dashboard.py
    - .planning/phases/12-parallel-run-cutover-htmx-decommission/12-CUTOVER-CHECKLIST.md
decisions:
  - "Deploy-at-end workflow: per-page blocking parity sign-off WAIVED for this run (operator pre-authorized); single live MT5-demo parity sign-off deferred to one end-to-end VPS acceptance at final deploy"
  - "No fabricated operator signatures — each checklist row annotated 'code complete + guard green locally; live sign-off DEFERRED to VPS'; Summary tally records code-complete:8 / live-signed:0"
  - "Kill-switch row (8) is verified-then-decommissioned: no GET page to redirect, no code change in 12-02; its deferred parity sign-off still gates the 12-03 /api/emergency-preview deletion"
metrics:
  duration: ~5min
  completed: 2026-06-07
  tasks: 2
  files: 2
---

# Phase 12 Plan 02: Per-page Cutover Redirects (CUT-02) Summary

Cut the operator from the legacy HTMX dashboard to the React SPA one page at a
time. All 7 legacy `@app.get` page routes now 303-redirect to their `/app/<page>`
equivalents and the root `/` flips to `/app/` as the final commit — each an
independently revertable single commit in D-05 order, with `Depends(_verify_auth)`
preserved on every route so an unauthenticated hit still bounces to login. No
nginx/Dockerfile/template change and no route deletion (legacy stays reachable by
direct URL for the bake window; deletion is 12-03).

## What Was Built

Each legacy page route's `TemplateResponse(...)` body was replaced with
`return RedirectResponse(url="/app/<page>", status_code=303)`, keeping the
`@app.get(..., response_class=HTMLResponse)` decorator, the full function
signature (including filter params on history/analytics), and
`user: str = Depends(_verify_auth)` intact. The `response_class=HTMLResponse`
decorator arg is now cosmetic and left in place (12-03 Commit 1 deletes the route
blocks wholesale).

Cutover order honored (D-05), one page per commit (D-01), root last (D-02):

| # | Route | 303 target | Commit |
|---|-------|------------|--------|
| 1 | GET /analytics | /app/analytics | `5322670` |
| 2 | GET /signals   | /app/signals   | `0cece3d` |
| 3 | GET /history   | /app/history   | `be31662` |
| 4 | GET /staged    | /app/staged    | `3e7fbbd` |
| 5 | GET /overview  | /app/overview  | `9560a45` |
| 6 | GET /settings  | /app/settings  | `22dd45d` |
| 7 | GET /positions | /app/positions | `e303675` |
| 8 | kill-switch (no GET page — verify only) | — (12-03 deletes /api/emergency-preview) | `1bf6f42` (checklist annotation) |
| FINAL | GET / (root) | /app/ (was /overview) | `498114a` |

## Verification

- `pytest tests/test_cutover_redirects.py` in a python:3.12-slim container with
  project deps → **8 skipped, exit 0** (PostgreSQL absent locally; the `api_app`
  conftest fixture `pytest.skip`s — this is the sanctioned green-or-skip bar, never
  FAIL, never collection error). Each per-page case was also run individually as its
  redirect landed: each returned `1 skipped` (green-or-skip), none FAILED.
- `python -m py_compile dashboard.py` → **COMPILE OK**.
- Auth-dep grep: all 8 redirected routes (7 pages + root) retain
  `Depends(_verify_auth)` (history/analytics carry it on a later signature line —
  verified by reading the full signatures). T-12-04 mitigated.
- Redirect-target grep: 8 `RedirectResponse(url="/app...` call sites at the exact
  expected routes, all with `status_code=303`. T-12-05 mitigated.
- Scope check: `git diff --name-only 5322670^..HEAD` shows ONLY `dashboard.py` +
  `12-CUTOVER-CHECKLIST.md` — no nginx/Dockerfile/template change, zero file
  deletions across all 9 commits.
- `git log --oneline` confirms one commit per page in D-05 order, root last, each
  referencing its CHECKLIST row.

### test_unauth_redirects_to_app_login — stays RED until 12-03

`test_unauth_redirects_to_app_login` asserts an unauth GET bounces to
`/app/login`. It remains RED (would fail when Postgres is present) until 12-03
Commit 1 repoints `_verify_auth`'s `Location` header from the legacy `/login` to
`/app/login` (RESEARCH Pitfall 4). This is expected and documented — it is NOT a
regression introduced by this plan. Locally it skips (Postgres absent) like every
other api_app-bound case.

### Legacy pages remain reachable (no deletion)

This plan only swaps route bodies to redirects; it deletes nothing. The legacy
route blocks (and `/login`, templates, nginx SSE block) survive for the 7-day bake
window and are removed in 12-03.

## Deviations from Plan

### [Gating override — operator pre-authorized] Per-page blocking parity sign-off WAIVED; deploy-at-end workflow

The plan specifies a `checkpoint:human-verify gate="blocking"` between the read-only
pages (Task 1) and the live-money pages (Task 2), with each redirect commit gated
on that page's MT5-demo parity row being operator-signed. **The operator chose a
deploy-at-end workflow:** all code is written and verified LOCALLY now, and the
single live MT5-demo parity sign-off happens once, end-to-end, on the VPS at final
deploy. Accordingly:

- **Found during:** plan start (explicit operator override in the execution brief).
- **What changed:** the blocking checkpoint was treated as waived/acknowledged
  (not stopped at); both Task 1 and Task 2 executed fully in one run, in D-05 order,
  one page per commit, root flipped last.
- **Honesty guard:** NO operator signatures were fabricated. Each
  12-CUTOVER-CHECKLIST.md row's `result:` was annotated
  `code complete + guard green locally 2026-06-07; live sign-off DEFERRED to VPS
  end-to-end acceptance` (kill-switch row notes no code change + deferred parity).
  The `## Summary` tally was updated to `code-complete: 8 / live-signed: 0` with an
  explanatory deploy-at-end note, keeping the rows honest.
- **Risk note:** D-05 ordering + root-last (D-02) were still honored, so the
  per-commit revertability and the live-money-last safety ordering are intact; only
  the *timing* of the parity sign-off moved (per-page-now → once-at-VPS-deploy). The
  kill-switch parity sign-off still gates the 12-03 /api/emergency-preview deletion
  and must be performed at VPS acceptance before 12-03 deploys.

No other deviations — the redirect swaps, D-05 order, root-last, auth-dep
preservation, and no-deletion/no-nginx constraints all match the plan exactly.

## Authentication Gates

None.

## Known Stubs

None. The redirect bodies are the intended final state for this plan (the routes
are deleted in 12-03). The CHECKLIST `live sign-off DEFERRED` annotations are the
designed deploy-at-end placeholders, not unwired stubs.

## Threat Flags

None. No new endpoint, auth path, file-access pattern, or schema change was
introduced — only page-route bodies were swapped to redirects. All threat-register
mitigations (T-12-04 auth-dep preserved, T-12-05 exact Location asserted, T-12-06
live-money-last order, T-12-07 root-last) are satisfied.

## Self-Check: PASSED

- FOUND: dashboard.py (8 RedirectResponse(url="/app...) call sites verified)
- FOUND: .planning/phases/12-parallel-run-cutover-htmx-decommission/12-CUTOVER-CHECKLIST.md (8 rows annotated)
- FOUND: .planning/phases/12-parallel-run-cutover-htmx-decommission/12-02-SUMMARY.md
- FOUND commit 5322670 (feat 12 analytics)
- FOUND commit 0cece3d (feat 12 signals)
- FOUND commit be31662 (feat 12 history)
- FOUND commit 3e7fbbd (feat 12 staged)
- FOUND commit 9560a45 (feat 12 overview)
- FOUND commit 22dd45d (feat 12 settings)
- FOUND commit e303675 (feat 12 positions)
- FOUND commit 1bf6f42 (docs 12 kill-switch row + summary)
- FOUND commit 498114a (feat 12 root flip LAST)
</content>
</invoke>
