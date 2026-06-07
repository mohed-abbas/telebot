---
phase: 11-live-money-pages-settings
plan: 01
subsystem: ui
tags: [react-hook-form, zod, hookform-resolvers, vitest, shadcn, footgun, settings-validation]

# Dependency graph
requires:
  - phase: 09-spa-scaffold-auth-design-system
    provides: Vite 8 + React 19 + Tailwind v4 + shadcn SPA scaffold, dark-brand @theme tokens, components.json (new-york style)
  - phase: 10-read-only-page-migration
    provides: validated read-only SPA pipeline + shared list/table primitives the live-money pages extend
provides:
  - "react-hook-form ^7.77, zod ^4 (v4 API), @hookform/resolvers ^5 installed as the form/validation stack for every Wave 1/2/3 plan"
  - "vitest runner (the only frontend test-framework gap) + `npm run test` / `vitest run` script"
  - "Five shadcn components (dialog, tooltip, select, badge, popover) — verified opaque on the dark brand background (Pitfall-9 gate)"
  - "footgun() pure fn — mode-aware compounded-exposure copy (percent multiplies, fixed_lot does NOT — Pitfall 6 / D-06/D-07)"
  - "makeSettingsSchema() zod factory mirroring the server validate_settings_form hard caps (SUX-03)"
  - "vitest units for both pure fns (footgun.test.ts, settingsSchema.test.ts)"
affects: [11-02, 11-03, 11-04, 11-05, 11-06, live-money-mutations, settings-page]

# Tech tracking
tech-stack:
  added: [react-hook-form@^7.77, zod@^4, "@hookform/resolvers@^5", vitest]
  patterns:
    - "Pure, vitest-tested presentation/validation utilities in frontend/src/lib/ (footgun, settingsSchema) — no money formatting in the client, mirrors useElapsed precedent"
    - "Mode-aware footgun: percent compounds (risk_value × max_stages), fixed_lot is the TOTAL across stages (no multiply) — single un-branched multiply is the Pitfall-6 bug"
    - "Client zod caps are a factory of the per-account max_lot_size read at runtime; defense-in-depth only (server re-validates — T-11-01 accepted)"

key-files:
  created:
    - frontend/vitest.config.ts
    - frontend/src/components/ui/dialog.tsx
    - frontend/src/components/ui/tooltip.tsx
    - frontend/src/components/ui/select.tsx
    - frontend/src/components/ui/badge.tsx
    - frontend/src/components/ui/popover.tsx
    - frontend/src/lib/footgun.ts
    - frontend/src/lib/footgun.test.ts
    - frontend/src/lib/settingsSchema.ts
    - frontend/src/lib/settingsSchema.test.ts
  modified:
    - frontend/package.json
    - frontend/package-lock.json

key-decisions:
  - "zod v4 (^4.4.3) chosen over v3 — resolver import is `@hookform/resolvers/zod`; superRefine/z.enum/addIssue({code:'custom'}) v4 signatures confirmed at build"
  - "vitest uses default node environment (NOT jsdom) — both units are pure functions; @/ alias resolved from the existing vite config"
  - "footgun fixed_lot branch contains NO `* maxStages` — riskValue is the TOTAL across stages (operator-confirmed 2026-05-01, trade_manager.py:108-117)"
  - "max_open_trades is read-only — deliberately NO zod cap (not in the settings form)"

patterns-established:
  - "Pattern: load-bearing pure fns shipped + unit-proven before any page consumes them, so page plans never re-derive caps or footgun math"
  - "Pattern: opaque-render gate (Pitfall 9) verified once at the foundation before any live-money mutation is wired into a dialog"

requirements-completed: [SUX-02, SUX-03]

# Metrics
duration: 3min
completed: 2026-06-07
---

# Phase 11 Plan 01: Live-money Foundation Summary

**Frontend foundation for the live-money phase: react-hook-form + zod v4 + @hookform/resolvers + vitest installed, five opaque-verified shadcn components (dialog/tooltip/select/badge/popover), and two vitest-proven pure utilities — the mode-aware footgun calc (Pitfall 6) and the mode-aware zod cap schema mirroring the server hard caps (SUX-03).**

## Performance

- **Duration:** 3 min (implementation tasks); checkpoint resolution same day
- **Started:** 2026-06-07T19:02:56Z (Task 1 commit)
- **Completed:** 2026-06-07T19:05:17Z (Task 3 commit) — checkpoint approved later same day
- **Tasks:** 3 implementation tasks + 1 blocking human-verify checkpoint (approved)
- **Files modified:** 12 (10 created, 2 modified)

## Accomplishments
- Installed the Phase 11 form/validation stack: react-hook-form ^7.77, zod ^4 (v4 API), @hookform/resolvers ^5, plus the vitest runner (the only frontend test-framework gap) with a `vitest run` script.
- Added the five shadcn components every later wave consumes (dialog, tooltip, select, badge, popover) and verified them opaque on the dark brand background (Pitfall-9 gate — Playwright-confirmed).
- Shipped `footgun()` — the mode-aware compounded-exposure copy fn (percent multiplies risk_value × max_stages; fixed_lot does NOT, riskValue is the total across stages) — with a vitest unit proving the Pitfall-6 contract.
- Shipped `makeSettingsSchema(maxLotSize)` — a zod factory mirroring `validate_settings_form` caps (percent ≤ 5.0, fixed_lot ≤ per-account max_lot_size, ints 1-10 / 1-500 / 1-100, no cap on read-only max_open_trades) — with a vitest unit covering SUX-03.

## Task Commits

Each task was committed atomically:

1. **Task 1: Install packages, add vitest, add five shadcn components** - `c2b7282` (feat)
2. **Task 2: Footgun pure fn + vitest unit (D-06/D-07, Pitfall 6)** - `0c3438a` (feat) — TDD test+impl folded into one commit
3. **Task 3: Mode-aware zod cap schema + vitest unit (SUX-03)** - `969c46c` (feat) — TDD test+impl folded into one commit

**Plan metadata:** this commit (docs: complete 11-01 plan)

## Files Created/Modified
- `frontend/vitest.config.ts` - Vitest runner config (node env, `@/` alias) — the only frontend test-framework gap closed
- `frontend/src/components/ui/dialog.tsx` - shadcn Dialog (opaque bg-background — Pitfall-9 verified)
- `frontend/src/components/ui/tooltip.tsx` - shadcn Tooltip
- `frontend/src/components/ui/select.tsx` - shadcn Select (opaque bg-popover — Pitfall-9 verified)
- `frontend/src/components/ui/badge.tsx` - shadcn Badge
- `frontend/src/components/ui/popover.tsx` - shadcn Popover
- `frontend/src/lib/footgun.ts` - exports `footgun()`; mode-aware (fixed_lot branch has NO `* maxStages`)
- `frontend/src/lib/footgun.test.ts` - Pitfall-6 regression (percent 2×4→8; fixed_lot 0.4,4 → no "1.6")
- `frontend/src/lib/settingsSchema.ts` - exports `makeSettingsSchema()`; mirrors server caps
- `frontend/src/lib/settingsSchema.test.ts` - SUX-03 cap-mirror unit (percent cap, per-account fixed_lot cap, int bounds)
- `frontend/package.json` - +react-hook-form/zod/@hookform/resolvers deps, +vitest dev dep, +`test` script
- `frontend/package-lock.json` - lockfile for the above

## Decisions Made
- zod v4 (^4.4.3) over v3 — resolver import is `@hookform/resolvers/zod`; v4 `superRefine`/`z.enum`/`addIssue({code:"custom"})` signatures confirmed at build.
- vitest uses the default node environment (not jsdom) — both units are pure functions.
- footgun fixed_lot branch deliberately has no `* maxStages` — riskValue is the TOTAL across stages (operator-confirmed 2026-05-01; trade_manager.py:108-117).
- No zod cap for `max_open_trades` — it is a read-only field, not in the settings form.

## Deviations from Plan
None - plan executed exactly as written.

## Checkpoint Resolution

The final task was a `checkpoint:human-verify` with `gate="blocking-human"` (T-11-SC package legitimacy + Pitfall-9 opaque-render gate). **Resolved — USER RESPONSE: "approved".**

- **Package legitimacy (T-11-SC):** PASS — react-hook-form@7.77.0, zod@4.4.3 (v4), @hookform/resolvers@5.4.0 are the genuine, official packages. None declares a preinstall/install/postinstall hook; install reported 0 vulnerabilities. Matches the RESEARCH audit (no postinstall scripts).
- **Opaque-render gate (Pitfall 9):** PASS — verified via Playwright on a fresh dev server. DialogContent computed bg = `oklch(0.12 0.02 275)` (bg-background, opaque); SelectContent computed bg = `oklch(0.17 0.03 275)` (bg-popover, opaque). Both fully obscured a neon background-bleed test; screenshots confirmed no transparent-popover regression. This gate clears before any later plan wires a live-money mutation into a dialog.

## must_haves Verification

All four `must_haves.truths` satisfied:

- ✅ A JS test runner (vitest) exists and `npx vitest run` executes the two pure-function units — **confirmed: 2 files, 15 tests passed.**
- ✅ The footgun calc multiplies risk_value × max_stages in percent mode and does NOT multiply in fixed_lot mode — **footgun.test.ts green (percent 2×4→8; fixed_lot 0.4,4 → no "1.6").**
- ✅ The zod settings schema rejects percent risk_value > 5.0, fixed_lot risk_value > per-account max_lot_size, and out-of-range ints — **settingsSchema.test.ts green.**
- ✅ shadcn dialog/tooltip/select/badge/popover render opaque on the dark brand background — **Playwright-confirmed (checkpoint resolution above).**

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Wave 1 (11-02 — live-money mutation hooks) is unblocked: the packages, components, and pure utilities it depends on are all shipped and proven.
- The opaque-render gate is cleared, so 11-03/11-04/11-05 may wire live-money mutations into dialogs without re-verifying Pitfall 9.
- footgun + makeSettingsSchema are ready for the settings page (11-04) to consume without re-deriving caps or footgun math.

## Self-Check: PASSED

All 10 created files verified present on disk; all 3 task commits (`c2b7282`, `0c3438a`, `969c46c`) verified in git log; vitest run green (2 files / 15 tests).

---
*Phase: 11-live-money-pages-settings*
*Completed: 2026-06-07*
