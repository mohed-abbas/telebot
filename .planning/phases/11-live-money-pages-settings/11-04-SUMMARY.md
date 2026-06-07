---
phase: 11-live-money-pages-settings
plan: 04
subsystem: ui
tags: [react-hook-form, zod, settings, footgun, two-step-flow, audit, revert, csrf]

# Dependency graph
requires:
  - phase: 11-live-money-pages-settings
    plan: 01
    provides: react-hook-form + zod v4 + @hookform/resolvers + vitest; 5 opaque-verified shadcn components (dialog/tooltip/select/badge/popover); footgun() + makeSettingsSchema() pure fns
  - phase: 11-live-money-pages-settings
    plan: 02
    provides: useSettingsMutations() — validate (200-on-invalid honored) / confirm / revert
  - phase: 10-read-only-page-migration
    provides: DataTable, ErrorPanel/errorMessage, Loading/Empty, api() CSRF wrapper, StagedView read/branch precedent, history filter-options accounts[]
provides:
  - "SettingsForm — rhf+zod per-account form whose defaultValues are the bare server values; mode-aware risk_value label + inline amber footgun; per-field tooltips; read-only max_open_trades; 'Review changes' CTA (does NOT persist)"
  - "ConfirmDiffDialog — diff table + verbatim server dry_run_text + restated mode-aware footgun; 'Confirm change'/'Saving…' (disabled-while-pending); 'Go back' preserves typed values"
  - "AuditTimeline — audit[] newest-first via DataTable (timestamp_display); single 'Revert last change' (latest-only, no per-row id) → confirm → useSettingsMutations.revert"
  - "SettingsView — PAGE-08 page wiring load → review (validate, branch on data.valid) → confirm-diff → confirm → refetch; per-account selector; /app/settings route registered"
affects: [settings-page, live-money-mutations]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "First react-hook-form form in the repo: useForm({ resolver: zodResolver(makeSettingsSchema(values.max_lot_size)), defaultValues: bare server values }); field markup mirrors LoginView (Label + Input + role=alert), select via setValue(shouldValidate)"
    - "Two-step settings flow (D-05) BRANCHES ON data.valid in the validate mutation's per-call onSuccess (Pitfall 7 — server returns 200 even when valid:false), never on HTTP status; invalid → rejection toast, valid → confirm modal with server diff + dry_run_text"
    - "Footgun rendered mode-aware in BOTH places (inline-while-editing in SettingsForm, restated in ConfirmDiffDialog) off footgun(mode, risk_value, max_stages) — amber treatment, fixed_lot does NOT multiply (Pitfall 6)"
    - "Revert is a single latest-only action carrying {account} only — no per-row identifier (RESEARCH OQ1); adding one would need a new endpoint (boundary violation)"
    - "dry_run_text rendered VERBATIM (Pitfall 5) — never recomputed client-side"

key-files:
  created:
    - frontend/src/components/settings/SettingsForm.tsx
    - frontend/src/components/settings/ConfirmDiffDialog.tsx
    - frontend/src/components/settings/AuditTimeline.tsx
    - frontend/src/routes/SettingsView.tsx
  modified:
    - frontend/src/routes/router.tsx

key-decisions:
  - "Account list sourced from the existing GET /api/v2/history/filter-options (accounts: string[]) and defaults to the first account — no new endpoint, per the plan's planner-discretion clause"
  - "validate/confirm branch logic lives in per-call mutate(onSuccess) handlers in SettingsView (not in the hook) so the page owns the data.valid branch (Pitfall 7) while the hook stays a dumb dry-run"
  - "SettingsFormValues (concrete interface, no index signature) is spread into a plain object literal ({ ...values }) at the mutate call sites so it satisfies the hook's SettingsValues = Record<string, unknown> contract without widening the form type"
  - "AuditTimeline owns its own revert confirm Dialog + calls useSettingsMutations.revert directly (the success/error toast is hook-owned); SettingsView passes only account + audit"

requirements-completed: [PAGE-08, SUX-01, SUX-02, SUX-03, SUX-04]

# Metrics
duration: 8min
completed: 2026-06-07
---

# Phase 11 Plan 04: Settings Page Summary

**The per-account Settings page (PAGE-08) shipped end-to-end: a react-hook-form + zod form whose defaultValues are the bare server values, with mode-aware zod caps (makeSettingsSchema) and a live amber compounded-exposure footgun (no multiply in fixed_lot — Pitfall 6), the uniform two-step validate→confirm-diff→confirm flow that branches on data.valid (Pitfall 7) and renders the server dry_run_text verbatim with the footgun restated, plus an audit timeline with a single latest-only "Revert last change" — all save/rejection/revert states surfaced as sonner toasts (SUX-01).**

## Performance
- **Duration:** ~8 min (3 implementation tasks)
- **Tasks:** 3 (all autonomous, no checkpoints)
- **Files:** 4 created, 1 modified

## Accomplishments
- **Task 1 — SettingsForm (SUX-02/03/04):** first rhf form in the repo. `useForm(zodResolver(makeSettingsSchema(values.max_lot_size)))` with defaults = bare server values; risk_mode shadcn select re-labels risk_value (percent → "Per-trade risk (%)" / fixed_lot → "Total lot size") and recomputes the footgun on switch; per-field tooltips carry units + range + server cap; inline amber `AlertTriangle` footgun (NOT destructive, NOT cyan); `max_open_trades` rendered read-only and excluded from the editable/submitted set; primary CTA "Review changes" → `onReview(values)` (does not persist).
- **Task 2 — ConfirmDiffDialog + AuditTimeline (D-05/D-06):** confirm modal renders the validate diff table (Field | old → new), the server `dry_run_text` verbatim (Pitfall 5), and the footgun restated mode-aware; "Confirm change"/"Saving…" disabled-while-pending; "Go back" preserves typed values. Audit timeline renders `audit[]` newest-first via DataTable using `timestamp_display`, with a single "Revert last change" (latest-only, no per-row id) → confirm → `useSettingsMutations.revert`.
- **Task 3 — SettingsView (PAGE-08, SUX-01, Pitfall 7):** `useQuery(["settings", account])` with StagedView's Loading/ErrorPanel branch order (read failure → inline ErrorPanel, not a toast); per-account selector from history filter-options; "Review changes" → validate, **branch on data.valid** → invalid `toast.error("Couldn't save: {first error}")` / valid opens ConfirmDiffDialog with server diff + dry_run_text; Confirm → confirm mutation → invalidate `["settings", account]` + close modal. `/app/settings` route registered.

## Task Commits
1. **Task 1: SettingsForm** — `ff7b8ae` (feat)
2. **Task 2: ConfirmDiffDialog + AuditTimeline** — `e4a08ac` (feat)
3. **Task 3: SettingsView route + router** — `94b9ccd` (feat)

**Plan metadata:** this SUMMARY commit (docs).

## Files Created/Modified
- `frontend/src/components/settings/SettingsForm.tsx` — rhf+zod form, mode-aware inline footgun + tooltips, read-only max_open_trades, "Review changes" CTA
- `frontend/src/components/settings/ConfirmDiffDialog.tsx` — diff table + verbatim dry_run_text + restated footgun; Confirm disabled-while-pending
- `frontend/src/components/settings/AuditTimeline.tsx` — newest-first audit DataTable (timestamp_display) + single latest-only revert
- `frontend/src/routes/SettingsView.tsx` — PAGE-08 page wiring the two-step flow + per-account selector
- `frontend/src/routes/router.tsx` — registered the `/app/settings` route (PAGE-08)

## Decisions Made
- Account list reuses GET /api/v2/history/filter-options (`accounts: string[]`), defaulting to the first — no new endpoint (planner-discretion clause).
- The data.valid branch (Pitfall 7) lives in SettingsView's per-call `mutate(onSuccess)` handlers, keeping `useSettingsMutations.validate` a dumb dry-run.
- `SettingsFormValues` is spread into an object literal at the mutate call sites to satisfy the hook's `Record<string, unknown>` values contract without widening the form type.
- AuditTimeline owns its revert confirm Dialog and calls the hook directly (toast is hook-owned); SettingsView passes only `account` + `audit`.

## Deviations from Plan
None — plan executed exactly as written. (No Rule 1–4 deviations.)

**Environment note (not a plan deviation):** the worktree shipped without `frontend/node_modules`. To run the plan's `npm run build` / `npx vitest run` gates, the already-installed (and lockfile-locked from 11-01) `node_modules` from the main checkout was symlinked into the worktree. No package was installed, added, or modified; the lockfile is untouched and `node_modules` is gitignored (not committed). This is an environment restore, not the excluded package-install action.

## TDD Gate Compliance
Tasks are marked `tdd="true"`, but — exactly as established in 11-02 — these are React components that cannot be vitest-rendered (jsdom + @testing-library/react are not installed; installing them is an excluded package-install action requiring a checkpoint). The executable verification surface for each task is therefore the plan's `<verify>` block (`npm run build`) plus the `<acceptance_criteria>` grep assertions, which were asserted GREEN before each commit. The load-bearing pure-function logic this page consumes (footgun, settingsSchema) carries its own vitest units, shipped + proven in 11-01 and re-run green here (2 files / 15 tests).

## Verification Results
- `cd frontend && npm run build` exits 0 after each task (final build: tsc -b + vite build green; only the pre-existing >500 kB chunk-size advisory, out of scope).
- `npx vitest run src/lib/settingsSchema.test.ts src/lib/footgun.test.ts` → 2 files / 15 tests passed (the caps + footgun this page consumes).
- grep: `footgun(` present in BOTH SettingsForm.tsx and ConfirmDiffDialog.tsx; NO `audit_id` (or any per-row id) anywhere in `frontend/src/components/settings/`.
- grep: SettingsView branches on `result.valid` (not HTTP status — Pitfall 7); invalid → `toast.error("Couldn't save: …")`; valid → opens ConfirmDiffDialog; confirm success invalidates `["settings", account]`; read failure → inline ErrorPanel.
- Server-side `tests/test_api_settings.py` / `tests/test_settings_form.py` are Python-container suites (Python 3.12) already shipped/green per 11-RESEARCH; not re-run in this frontend-only worktree — assert at wave merge.
- MANUAL (deferred to wave merge): Save → success toast; cap-breach → rejection toast; revert → revert toast (SUX-01).

## must_haves Verification
- ✅ Settings loads per-account values via GET /api/v2/settings/{account} into a react-hook-form whose defaultValues are the bare server values — `SettingsView` useQuery → `SettingsForm` defaultValues = `data.values`.
- ✅ Every change runs validate → confirm-diff → confirm (D-05); validate branches on data.valid (Pitfall 7) not HTTP status — `handleReview` reads `result.valid`.
- ✅ Compounded-exposure footgun inline-while-editing AND restated in the confirm modal, mode-aware (percent multiplies; fixed_lot does not) — `footgun()` in both SettingsForm and ConfirmDiffDialog.
- ✅ Client zod caps mirror the server via makeSettingsSchema(values.max_lot_size) — `zodResolver(makeSettingsSchema(values.max_lot_size))`.
- ✅ Save success / validation rejection / revert each surface a sonner toast (SUX-01); revert is a single 'Revert last change' CSRF mutation (no audit_id) — confirm/revert toasts hook-owned; rejection toast in handleReview; revert body `{account}`.

## Known Stubs
None — the page is fully wired to the real /api/v2/settings/{account} (read), /validate, /{account} (confirm), /revert endpoints via `useSettingsMutations` + `api()`. No placeholder data, no hardcoded empties.

## Threat Flags
None — no new security-relevant surface beyond the plan's `<threat_model>`. All mutations route through `api()` (CSRF echoed); the page branches on data.valid so an out-of-cap value is surfaced as a rejection toast, never silently confirmed (T-11-15); toast copy comes only from the typed server errors map / errorMessage() (T-11-16); the client zod caps are defense-in-depth mirroring the server (T-11-12).

## Issues Encountered
- Initial build failed on `useMemo` unused (noUnusedLocals) and `SettingsFormValues` not assignable to the hook's `Record<string, unknown>` values type. Fixed inline (removed the import; spread the form values into an object literal at both mutate call sites). Not tracked as a deviation — these were in-task type fixes before the task's first commit.

## User Setup Required
None.

## Next Phase Readiness
- The Settings page is wave-complete and route-registered at `/app/settings`. It is the sole consumer of the Wave-0 footgun + settingsSchema pure fns and the Wave-1 settings mutation hooks — all now exercised by a real page.
- The shared opaque-render gate (11-01) was already cleared; both new dialogs (ConfirmDiffDialog, the revert confirm in AuditTimeline) reuse the verified shadcn Dialog.

## Self-Check: PASSED

All 4 created files + the modified router verified present on disk; all 3 task commits (`ff7b8ae`, `e4a08ac`, `94b9ccd`) verified in git log; final `npm run build` green; vitest units green (2 files / 15 tests).

---
*Phase: 11-live-money-pages-settings*
*Completed: 2026-06-07*
