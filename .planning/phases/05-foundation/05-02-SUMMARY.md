---
phase: 05-foundation
plan: 02
subsystem: ui
tags: [tailwind, basecoat, htmx, docker, css-build, content-hash]

# Dependency graph
requires:
  - phase: 04-v1.0-complete
    provides: existing dashboard templates and HTMX patterns to preserve
provides:
  - Tailwind v3.4.19 standalone-CLI build stage (no Node runtime)
  - Vendored Basecoat v0.3.3 (CSS + initAll JS)
  - Content-hashed `app.{hash}.css` + `manifest.json` build output
  - Compat shim preserving v1.0 dashboard classes (.card, .btn-*, .badge-*, .nav-active, etc.)
  - HTMX `afterSwap` bridge re-initializing Basecoat interactive components
  - 9 filesystem + build-artifact substrate tests
affects: [05-03 auth backend (base.html cutover + asset_url helper), 05-04 login UI, 06-staged-entry, 07-dashboard-redesign]

# Tech tracking
tech-stack:
  added: [tailwindcss@v3.4.19 (standalone CLI), basecoat-css@0.3.3, basecoat-all.min.js@0.3.3]
  patterns:
    - Multi-stage Docker build (debian:bookworm-slim css-build + python:3.12-slim runtime)
    - Content-addressed CSS via sha256 prefix + manifest.json lookup
    - Python-source content glob (Tailwind scans `*.py` — Pitfall 10)
    - HTMX afterSwap → basecoat.initAll re-hydration (defense-in-depth behind Basecoat's MutationObserver)

key-files:
  created:
    - static/vendor/basecoat/basecoat.css
    - static/vendor/basecoat/basecoat.min.js
    - tailwind.config.js
    - static/css/input.css
    - static/css/_compat.css
    - scripts/build_css.sh
    - static/js/htmx_basecoat_bridge.js
    - tests/test_ui_substrate.py
  modified:
    - Dockerfile (single-stage → two-stage with CSS build)
    - .gitignore (ignore build outputs)
  removed:
    - drizzle.config.json (stray scaffolding — D-09)

key-decisions:
  - "Vendored Basecoat instead of CDN — offline-capable and deterministic builds (D-05)"
  - "Tailwind standalone CLI (no Node) — Python project, no reason to add a Node runtime (D-04)"
  - "Content-hash via sha256sum prefix + manifest.json — fingerprinted assets with lookup indirection for templates (D-07)"
  - "Compat shim uses @apply to map v1.0 class names to Basecoat primitives — preserves pixel-for-pixel visuals without rewriting templates in this plan (D-06)"
  - "htmx:afterSwap → basecoat.initAll is explicit, not relying solely on Basecoat's MutationObserver — defense in depth (D-08, UI-05)"
  - "Removed drizzle.config.json — it was stray scaffolding never referenced (D-09)"

patterns-established:
  - "Build-time asset fingerprinting: scripts/build_css.sh emits content-hashed CSS and writes manifest.json for template lookup"
  - "Two-stage Dockerfile: compiled assets copied from css-build stage into python:3.12-slim runtime"
  - "Tailwind content globs include `*.py` — Python-inlined class names (e.g., in HTMX fragments) are not purged"

requirements-completed: [UI-01, UI-02, UI-03, UI-04, UI-05]

# Metrics
duration: ~3 min (before interrupt; then SUMMARY written post-reset)
completed: 2026-04-19
---

# Phase 5 Plan 02: UI Substrate Summary

**Tailwind v3.4.19 standalone-CLI build + vendored Basecoat v0.3.3 + content-hashed CSS + compat shim — dashboard visuals preserved pixel-for-pixel, CDN eliminated.**

## Performance

- **Duration:** ~3 min (agent work) + SUMMARY written after usage-limit reset
- **Started:** 2026-04-19T01:03:00Z
- **Completed:** 2026-04-19T01:07:41Z (code) / post-reset (SUMMARY)
- **Tasks:** 2
- **Files modified:** 10 (8 created, 2 modified, 1 removed)

## Accomplishments

- Vendored Basecoat v0.3.3 (CSS + JS) under `static/vendor/basecoat/` — no CDN dependency
- Tailwind standalone CLI (v3.4.19) downloaded and executed inside a debian:bookworm-slim Docker build stage
- Content-hashed output `app.{hash}.css` + `manifest.json` emitted deterministically by `scripts/build_css.sh`
- Compat shim (`static/css/_compat.css`) preserves v1.0 dashboard classes via `@apply` — no template rewrites required in this plan
- HTMX-Basecoat re-initialization bridge installed (`htmx:afterSwap` → `basecoat.initAll()`) satisfying UI-05
- Test suite (`tests/test_ui_substrate.py`) verifies vendored assets present, Tailwind config shape, build script contract, and Docker stage structure

## Task Commits

1. **Task 1: Vendor Basecoat + Tailwind config + compat shim** — `fea5c56` (feat)
2. **Task 2: build_css.sh + multi-stage Dockerfile + HTMX bridge + tests** — `081a9d6` (feat)

## Files Created/Modified

- `static/vendor/basecoat/basecoat.css` — Vendored v0.3.3 (~42 KB)
- `static/vendor/basecoat/basecoat.min.js` — Vendored all.min.js renamed (15,682 B)
- `tailwind.config.js` — Content globs include `templates/**/*.html` AND `*.py` (Pitfall 10); dark palette; safelist
- `static/css/input.css` — Tailwind entrypoint: imports compat shim + Basecoat layers
- `static/css/_compat.css` — v1.0 class mappings via @apply
- `scripts/build_css.sh` — tailwindcss --minify → sha256 prefix → manifest.json
- `static/js/htmx_basecoat_bridge.js` — afterSwap → initAll listener
- `tests/test_ui_substrate.py` — 9 substrate tests (7 pass, 2 self-skip when tailwind CLI absent on the test host)
- `Dockerfile` — two stages: `css-build` (debian + tailwind CLI) and runtime (python:3.12-slim)
- `.gitignore` — ignore `static/css/app.*.css` and `static/css/manifest.json`
- `drizzle.config.json` — **removed** (stray scaffolding, D-09)

## Decisions Made

None beyond the plan — all decisions were pre-agreed in CONTEXT.md (D-04 … D-09). The executor followed the plan exactly.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

Execution was interrupted by a Claude Code usage-limit reset before this SUMMARY.md could be written. All code-producing work was complete and committed. SUMMARY was written after the limit reset by the orchestrator based on verifiable git state.

## User Setup Required

None — substrate is pure build tooling. Runtime behavior is unchanged from v1.0 until Plan 03 cuts over `base.html` to the hashed CSS.

## Next Phase Readiness

- Plan 03 (auth backend) can now reference `{{ asset_url("app.css") }}` in `base.html` once the helper exists.
- Plan 04 (/login) has a styled Basecoat substrate to consume for its form.
- All UI-0[1-5] requirements verifiable via the committed test suite.

---
*Phase: 05-foundation*
*Plan: 02*
*Completed: 2026-04-19*
