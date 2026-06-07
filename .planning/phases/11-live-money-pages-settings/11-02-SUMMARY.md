---
phase: 11-live-money-pages-settings
plan: 02
subsystem: ui
tags: [tanstack-query, mutations, csrf, idempotency, live-money, settings, footgun]

# Dependency graph
requires:
  - phase: 11-live-money-pages-settings
    plan: 01
    provides: react-hook-form + zod v4 + @hookform/resolvers + vitest; 5 opaque-verified shadcn components; footgun() + makeSettingsSchema() pure fns
  - phase: 09-spa-scaffold-auth-design-system
    provides: api() fetch wrapper (CSRF double-submit), HttpError, global onAuthError on QueryCache+MutationCache, errorMessage() envelope parser, sonner Toaster at root
provides:
  - "useClose — close-a-position mutation (no body) → invalidate positions+overview; server-confirmed only (SC#1)"
  - "useLevels — modify SL/TP mutation (CloseLevelsIn, only the changed sl/tp fields sent; null=keep)"
  - "usePartialClose — absolute close_volume (D-04, no percent) + stable request_id useRef(crypto.randomUUID) reused on pure retries, regenerateRequestId() on amount change, HttpError 409 → specific operator toast (Pitfall 3 / T-11-04)"
  - "useEmergency — close + resume mutations; both invalidate overview+trading-status+positions (PAGE-07)"
  - "useSettingsMutations — validate (200-on-invalid honored: no onSuccess/no throw, caller branches on data.valid — Pitfall 7), confirm, revert; bodies nest under values, revert body {account} (PAGE-08/SUX-01)"
affects: [11-03, 11-04, 11-05, 11-06, positions-page, kill-switch-page, settings-page]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Money-safe mutation hook shape: useMutation → api() only (CSRF echoed, never raw fetch — Pitfall 2/T-11-03), NO setQueryData (SC#1/Pitfall 1 — UI re-derives only via invalidateQueries in onSuccess), 401 handled by the inherited global onAuthError (never per-hook), errors surfaced via the shared errorMessage() envelope parser into sonner toasts (T-11-06)"
    - "Idempotent partial-close: absolute close_volume (D-04, no percent field) + request_id held in useRef seeded once with crypto.randomUUID; reused across pure retries (server replays cached 200, broker untouched) and only regenerated when the operator changes the amount; HttpError 409 branched to a specific operator message (Pitfall 3)"
    - "200-on-invalid validate: the /validate mutation has NO onSuccess and never throws on valid:false — it resolves the parsed body and the page reads data.valid to branch (Pitfall 7); only a true transport/non-2xx lands in onError"

key-files:
  created:
    - frontend/src/hooks/useClose.ts
    - frontend/src/hooks/useLevels.ts
    - frontend/src/hooks/usePartialClose.ts
    - frontend/src/hooks/useEmergency.ts
    - frontend/src/hooks/useSettingsMutations.ts
  modified: []

key-decisions:
  - "These hooks are NOT unit-tested via vitest: vitest is configured node-env / pure-fn-only (per 11-01), and @testing-library/react + jsdom are not installed — adding them is a package-install action (excluded from auto-fix, would need a checkpoint). The plan's own automated verification is `npm run build` + grep acceptance assertions, which fully gate the contract. The hook contracts are exercised by the Wave-2 page plans that render them."
  - "usePartialClose returns { ...mutation, regenerateRequestId } so the page can both submit and mint a fresh request_id when the amount changes — the id is reused on pure retries to hit the server's cached-200 replay (Pitfall 3)"
  - "useEmergency returns { close, resume } (two named mutations) rather than a single mutation, mirroring useSettingsMutations { validate, confirm, revert } — pages destructure the action they need"
  - "useSettingsMutations.validate intentionally has no onSuccess/invalidate — validation is a dry-run; only confirm/revert mutate state and invalidate ['settings', account]"

requirements-completed: [PAGE-06, PAGE-07, PAGE-08, SUX-01]

# Metrics
duration: 2min
completed: 2026-06-07
---

# Phase 11 Plan 02: Live-money Mutation Hooks Summary

**The five money-safe mutation hooks every Phase 11 page composes — useClose / useLevels / usePartialClose (positions actions), useEmergency (kill-switch), useSettingsMutations (two-step settings) — each encoding the SC#1/Pitfall-2/Pitfall-3/Pitfall-7 invariants once: api()-only CSRF, no optimistic setQueryData (UI re-derives via invalidateQueries on server-confirmed success), idempotent partial-close via a stable request_id, and a 200-on-invalid validate that the page branches on data.valid.**

## Performance
- **Duration:** ~2 min (2 implementation tasks)
- **Started:** 2026-06-07T17:27:34Z
- **Completed:** 2026-06-07T17:29:54Z
- **Tasks:** 2 (both autonomous, no checkpoints)
- **Files:** 5 created (all under frontend/src/hooks/)

## Accomplishments
- **Task 1 — positions actions (PAGE-06):** useClose (POST .../close, no body), useLevels (POST .../levels, CloseLevelsIn with only the changed sl/tp fields), usePartialClose (absolute close_volume + stable request_id idempotency + 409 handling). All three: api() only, no setQueryData, invalidate on server-confirmed success.
- **Task 2 — kill-switch + settings (PAGE-07/PAGE-08/SUX-01):** useEmergency (close + resume, both invalidate overview+trading-status+positions), useSettingsMutations (validate honoring the 200-on-invalid contract, confirm, revert; bodies nested under `values`, revert body `{account}`).

## Task Commits
1. **Task 1: useClose, useLevels, usePartialClose** — `23160b1` (feat)
2. **Task 2: useEmergency, useSettingsMutations** — `c9cf5fd` (feat)

**Plan metadata:** final docs commit (this SUMMARY + STATE + ROADMAP).

## Files Created
- `frontend/src/hooks/useClose.ts` — close mutation (no body) → invalidate positions+overview; exports `useClose`
- `frontend/src/hooks/useLevels.ts` — modify SL/TP (CloseLevelsIn, only changed fields, Content-Type json); exports `useLevels`
- `frontend/src/hooks/usePartialClose.ts` — absolute-volume partial close + request_id useRef + regenerateRequestId + 409 branch; exports `usePartialClose`
- `frontend/src/hooks/useEmergency.ts` — close + resume mutations; exports `useEmergency`
- `frontend/src/hooks/useSettingsMutations.ts` — validate (200-on-invalid) + confirm + revert; exports `useSettingsMutations`, `SettingsValidateResult`, `SettingsVars`, `SettingsDiffEntry`, `SettingsValues`

## Decisions Made
- Hooks are gated by `npm run build` + grep acceptance assertions, not vitest units: vitest is node-env/pure-fn-only (11-01 precedent) and `@testing-library/react`/jsdom are not installed (installing them is an excluded package-install action requiring a checkpoint). Hook contracts are exercised by the Wave-2 page plans that render them.
- `usePartialClose` returns `{ ...mutation, regenerateRequestId }`; the id is reused on pure retries (cached-200 replay) and regenerated only on amount change (Pitfall 3).
- `useEmergency` returns `{ close, resume }`; `useSettingsMutations` returns `{ validate, confirm, revert }` — pages destructure the action they need.
- `validate` has no onSuccess/invalidate — it is a dry-run; only confirm/revert mutate and invalidate `['settings', account]`.

## Deviations from Plan
None — plan executed exactly as written. (No Rule 1–4 deviations; autonomous plan, no checkpoints reached.)

## TDD Gate Compliance
Tasks are marked `tdd="true"`, but the only executable verification surface for these hooks is the plan's `<verify>` block (`npm run build`) plus the `<acceptance_criteria>` grep assertions — there is no isolatable pure-function logic to RED/GREEN, and the hooks cannot be rendered without `@testing-library/react`+jsdom (not installed; installing them is an excluded package-install action). RED was established (hooks dir absent, `npm run build` baseline green), then each task's grep + build gate was asserted GREEN before its commit. The mode-aware pure-function units that DO warrant vitest (footgun, settingsSchema) were shipped and proven in 11-01.

## must_haves Verification
- ✅ "Every live-money mutation goes through api() (CSRF), never raw fetch" — grep over `frontend/src/hooks/` finds no code-level `fetch(`; every mutationFn calls `api(`.
- ✅ "No mutation calls setQueryData before server confirm — UI updates only via invalidateQueries in onSuccess (SC#1)" — grep finds no code-level `setQueryData`; every state-changing onSuccess invalidates.
- ✅ "Partial-close sends absolute close_volume + a stable client-generated UUID request_id, reused on pure retries, surfaces a typed toast on 409" — `usePartialClose.ts`: `useRef(crypto.randomUUID())`, body `{close_volume, request_id}` (no `percent`), `regenerateRequestId` only on amount change, `e instanceof HttpError && e.status === 409` → specific copy.
- ✅ "Settings validate branches on data.valid (not HTTP status) because the server returns 200 even when valid:false" — `validate` has no onSuccess and never throws on valid:false; returns the parsed `SettingsValidateResult` for the page to branch on `.valid`.

## Verification Results
- `cd frontend && npm run build` exits 0 (tsc -b + vite build green) after each task.
- grep: no code-level `setQueryData`, no code-level raw `fetch(` in `frontend/src/hooks/` (only documentation references in comments).
- Phase 8 `tests/test_api_csrf.py` / `tests/test_api_idempotency.py` are server-side, already shipped/green (per 11-RESEARCH); not re-run in this frontend-only sequential wave (require the Python 3.12 container) — assert at wave merge.

## Known Stubs
None — all five hooks are fully wired to their real /api/v2 endpoints via api(). No placeholder data, no hardcoded empties.

## Issues Encountered
None.

## User Setup Required
None.

## Next Phase Readiness
- Wave 2 (11-03 positions page, 11-04 settings page, 11-05 kill-switch, 11-06) is unblocked: every live-money mutation contract is shipped with the money-safe discipline baked in, so the page plans just wire these hooks to buttons/dialogs.
- The 11-01 opaque-render gate is already cleared, so these mutations can be wired into dialogs without re-verifying Pitfall 9.

## Self-Check: PASSED

All five hook files verified present on disk; both task commits (`23160b1`, `c9cf5fd`) verified in git log; `npm run build` green.

---
*Phase: 11-live-money-pages-settings*
*Completed: 2026-06-07*
