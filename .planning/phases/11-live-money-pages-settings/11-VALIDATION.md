---
phase: 11
slug: live-money-pages-settings
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-07
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `11-RESEARCH.md` §Validation Architecture. Phase 11 adds NO endpoints —
> the Phase 8 pytest contract suite already gates the server side. The new
> automated surface is the zod cap schema + footgun calc as pure-function Vitest units.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Backend: `pytest` (existing). Frontend: `vitest` (NEW — Wave 0; pure-function units) + `npm run build` as the TS/compile gate |
| **Config file** | Backend: `pyproject.toml [tool.pytest.ini_options]`. Frontend: none yet — Wave 0 adds minimal `vitest` config (or `vite` `test` field) |
| **Quick run command** | `cd frontend && npm run build` (per task) |
| **Full suite command** | `pytest tests/ -x && cd frontend && npm run build && npx vitest run` |
| **Estimated runtime** | ~60 seconds (build ~20s, pytest ~30s, vitest units <5s) |

---

## Sampling Rate

- **After every task commit:** Run `cd frontend && npm run build` (fast TS/Tailwind/Vite gate)
- **After every plan wave:** Run `pytest tests/ -x && cd frontend && npm run build && npx vitest run`
- **Before `/gsd:verify-work`:** Full backend suite green; zod + footgun units green; all SC manually verified in browser (live money-path SC on VPS + MT5 demo)
- **Max feedback latency:** ~60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 11-W0-01 | W0 | 0 | SUX-03 | — | zod cap schema mirrors server (percent ≤5.0, fixed_lot ≤ per-account max_lot_size, ints 1-10/1-500/1-100) | unit | `npx vitest run src/lib/settingsSchema.test.ts` | ❌ W0 | ⬜ pending |
| 11-W0-02 | W0 | 0 | SUX-02 | — | footgun: percent compounds ×max_stages; fixed_lot = total (NO multiply) — Pitfall 6 | unit | `npx vitest run src/lib/footgun.test.ts` | ❌ W0 | ⬜ pending |
| 11-PAGE-05 | Overview | — | PAGE-05 | — | positions table + pending-stages + kill-switch entry + PAUSED banner render with correct TS shapes | build/smoke | `cd frontend && npm run build` | ✅ build | ⬜ pending |
| 11-SC03 | Overview/Positions | — | PAGE-05/06 | — | open Edit modal / drilldown survives ≥2 background refetch cycles, typed input intact | manual (browser) | Type SL, leave modal open, watch ≥2×3s polls | manual | ⬜ pending |
| 11-PAGE-06 | Positions | — | PAGE-06 | — | close / modify SL+TP / partial-close server-confirmed only, disabled-while-pending, error toast | manual (browser, MT5 demo) | Click Close; row clears only after 200; forced error keeps modal open | manual | ⬜ pending |
| 11-SC02 | Positions/KillSwitch/Settings | — | PAGE-06/07/08 | — | every mutation rejected 403 without `X-CSRF-Token` | integration (green) | `pytest tests/test_api_csrf.py -x` | ✅ exists | ⬜ pending |
| 11-PAGE-07 | KillSwitch | — | PAGE-07 | — | two-step preview→confirm (confirm disabled-while-pending); partial-close absolute volume + request_id → 409 on id-reuse-diff-params | integration (green) + manual | `pytest tests/test_api_idempotency.py -x`; manual preview→confirm | ✅ exists + manual | ⬜ pending |
| 11-PAGE-08 | Settings | — | PAGE-08, SUX-04 | — | per-account form + two-step validate→confirm-diff + audit timeline + revert; operator-legible copy | build + manual | `cd frontend && npm run build`; manual diff/revert | ✅ build + manual | ⬜ pending |
| 11-SUX-01 | Settings | — | SUX-01 | — | viewport sonner save / rejection / revert toasts | manual (browser) | Save→success; cap-breach→rejection; revert→revert toast | manual | ⬜ pending |
| 11-SETTINGS-API | Settings | — | PAGE-08 | — | validate (200 even when valid:false) / confirm / revert contract honored | integration (green) | `pytest tests/test_api_settings.py -x` | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `frontend` test runner: add `vitest` (+ minimal config or `vite` `test` field) — the only framework gap
- [ ] `frontend/src/lib/settingsSchema.test.ts` — asserts the mode-aware caps match server `validate_settings_form` (percent ≤5.0, fixed_lot ≤ per-account `max_lot_size`, ints `max_stages` 1-10, `default_sl_pips` 1-500, `max_daily_trades` 1-100). Covers SUX-03.
- [ ] `frontend/src/lib/footgun.test.ts` — asserts percent mode multiplies by `max_stages`, fixed_lot mode does NOT. Covers SUX-02 / D-07 / Pitfall 6.
- [ ] No new backend tests needed — Phase 8 contract tests (`test_api_csrf`, `test_api_idempotency`, `test_api_settings`, `test_settings_form`) already cover the server side (no endpoints added).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Server-confirmed-only mutations (no optimistic clear) | SC#1 / PAGE-06 | Requires live broker round-trip + forced-error path; not unit-observable | On MT5 demo: click Close → confirm row clears only after server 200; force a server error → modal stays open with typed values preserved + error toast |
| Poll-safe modal/drilldown survival | SC#3 / PAGE-05,06 | Requires real timer + render lifecycle over ≥2 refetch cycles | Open Edit modal, type an SL value, leave open across ≥2 × ~3s polls → input intact, modal not remounted |
| Kill-switch two-step preview→confirm | SC#4 / PAGE-07 | Live emergency path; confirm-disabled-while-pending is a runtime UI state | On demo: trigger preview → render → confirm (disabled while pending) → resume |
| sonner save / rejection / revert toasts | SUX-01 | Viewport-level toast rendering is visual | Save (success toast); breach a cap (rejection toast); revert (revert-confirmation toast) |

*Live money-path success criteria are gated on a VPS + MT5-demo manual session per project verification policy.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (vitest + 2 unit files)
- [ ] No watch-mode flags (`vitest run`, not `vitest`)
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
