---
phase: 09-spa-scaffold-auth-design-system
plan: 01
subsystem: ui
tags: [react, vite, typescript, tailwindcss, shadcn, radix-ui, sonner, design-system]

# Dependency graph
requires:
  - phase: 08-json-api-foundation
    provides: "/api/v2 JSON contract + double-submit CSRF + server-side number/timestamp formatting that the SPA consumes (data layer wired in Plans 03/04)"
provides:
  - "Greenfield frontend/ Vite 8 + React 19 + TypeScript SPA that builds with `npm run build`"
  - "Vite base:/app/ so built asset URLs resolve under the nginx /app/ subpath (D-01)"
  - "Tailwind v4 wired via @tailwindcss/vite with NO tailwind.config.js (D-10)"
  - "Dark brand palette (#0f0f1a/#1a1a2e/#252542 + cyan accent) mapped to shadcn semantic roles in src/index.css via @theme inline (D-10)"
  - "Minimal shadcn component set — button, input, label, card, sonner — rendering opaque dark colors (D-11)"
  - "vite.config.ts dev proxy /api → 8090 keeping the telebot_session cookie same-origin in dev (D-12)"
affects: [09-02-static-serving, 09-03-auth, 09-04-app-shell, phase-10-page-migration, phase-11-live-money-pages]

# Tech tracking
tech-stack:
  added:
    - "react 19.2.7 / react-dom 19.2.7"
    - "vite 8.0.16 / @vitejs/plugin-react 6.0.2"
    - "typescript 6.0.3"
    - "tailwindcss 4.3.0 / @tailwindcss/vite 4.3.0"
    - "shadcn CLI 4.x (build-time only — copies source into src/components/ui/)"
    - "class-variance-authority 0.7.1 / clsx 2.1.1 / tailwind-merge 3.6.0 / lucide-react 1.17.0"
    - "radix-ui 1.4.3 (unified umbrella package)"
    - "sonner 2.0.7"
  patterns:
    - "Tailwind v4 token model: brand roles in .dark block + @theme inline mapping, no config file"
    - "Vite base:/app/ subpath build for nginx-mounted SPA"
    - "Dev /api proxy with changeOrigin:false to preserve same-origin session cookie"
    - "shadcn React 19 components use ref-as-prop (no forwardRef)"

key-files:
  created:
    - "frontend/package.json"
    - "frontend/vite.config.ts"
    - "frontend/tsconfig.json, frontend/tsconfig.app.json, frontend/tsconfig.node.json"
    - "frontend/index.html"
    - "frontend/components.json"
    - "frontend/src/index.css"
    - "frontend/src/main.tsx"
    - "frontend/src/App.tsx"
    - "frontend/src/lib/utils.ts"
    - "frontend/src/components/ui/{button,input,label,card,sonner}.tsx"
  modified: []

key-decisions:
  - "Kept the rolldown native binding out of package.json (Vite 8 resolves it transitively; pinning it caused install noise)"
  - "Dropped TS baseUrl — the @/* path alias resolves without it on TS 6 / Vite, avoiding a redundant root reference"
  - "Rejected the shadcn nova preset extras (tw-animate-css, next-themes, bundled webfonts) — Phase 9 is dark-by-default with no theme toggle and a system font stack"
  - "Used the unified radix-ui umbrella package (1.4.3) rather than per-primitive @radix-ui/* packages, per current shadcn output"
  - "Pinned sonner Toaster theme=\"dark\" so toasts match the dark-by-default brand field"

patterns-established:
  - "Pattern 1: Tailwind v4 brand tokens live in src/index.css (.dark + @theme inline) — never a tailwind.config.js"
  - "Pattern 2: SPA builds under base:/app/ to match the dashboard uvicorn mount path"
  - "Pattern 3: dev /api proxy targets 8090 with changeOrigin:false for same-origin cookies"

requirements-completed: [SPA-01, SPA-02]

# Metrics
duration: ~15min
completed: 2026-06-06
---

# Phase 09 Plan 01: SPA Scaffold + Tailwind v4 Brand Tokens + shadcn Component Set Summary

**Greenfield Vite 8 + React 19 + TypeScript SPA scaffolded under base:/app/ with Tailwind v4 (no config file), the dark brand palette mapped to shadcn @theme semantic roles, and the 5-component minimal set (button/input/label/card/sonner) rendering opaque dark colors.**

## Performance

- **Duration:** ~15 min (across initial executor + continuation finalization)
- **Completed:** 2026-06-06
- **Tasks:** 3 (2 auto + 1 blocking human-verify checkpoint — approved)
- **Files modified:** ~17 (frontend scaffold + tokens + components)

## Accomplishments
- Buildable `frontend/` Vite 8 + React 19 + TypeScript project (`npm run build` exits 0, emits `dist/index.html` with assets under `/app/assets/`).
- Vite configured with `base:"/app/"`, `react()` + `tailwindcss()` plugins, `@`→`./src` alias, and a single `/api` dev proxy to `http://localhost:8090` (`changeOrigin:false`).
- Tailwind v4 wired with NO `tailwind.config.js`; brand palette mapped into the `.dark` block and `@theme inline` (background #0f0f1a, card #1a1a2e, muted #252542, cyan `--primary`, red `--destructive` themed-but-unused), plus `--font-sans`/`--font-mono` tokens.
- shadcn initialized on the v4 base; the exact D-11 minimal set installed (button, input, label, card, sonner) — React 19 ref-as-prop, no forwardRef.
- Human-verify checkpoint (Task 3) approved: components render opaque dark brand colors, lockfile clean. Throwaway verification harness reverted from `App.tsx` (back to the trivial `<div>Telebot</div>` placeholder); real app shell lands in Plan 04.

## Task Commits

1. **Task 1: Scaffold frontend/ — Vite 8 + React 19 + TS, base /app/, dev proxy, @ alias** - `c8c8af7` (feat)
2. **Task 2: Tailwind v4 brand tokens + shadcn init + 5-component set** - `5d8e741` (feat)
3. **Task 3: human-verify checkpoint** - approved; throwaway `App.tsx` harness was uncommitted and reverted to the committed placeholder (no new commit — working tree already matched committed state c8c8af7).

**Plan metadata:** committed with this SUMMARY (docs: complete plan).

## Files Created/Modified
- `frontend/vite.config.ts` - base:/app/, react()+tailwindcss(), @ alias, /api proxy to 8090
- `frontend/src/index.css` - Tailwind v4 import + .dark brand tokens + @theme inline mapping + font tokens
- `frontend/components.json` - shadcn config (cssVariables true, Tailwind v4)
- `frontend/src/lib/utils.ts` - cn() helper (clsx + tailwind-merge)
- `frontend/src/components/ui/{button,input,label,card,sonner}.tsx` - minimal shadcn set
- `frontend/src/App.tsx` - trivial `<div>Telebot</div>` placeholder (shell lands in Plan 04)
- `frontend/index.html` - root `<html class="dark">` dark-by-default
- `frontend/package.json`, `tsconfig*.json`, `main.tsx`, `vite-env.d.ts` - scaffold

## Decisions Made
- Kept the rolldown native binding out of `package.json` (Vite 8 resolves it transitively; explicit pin produced install noise).
- Dropped TS `baseUrl` — the `@/*` alias resolves without it on TS 6, avoiding a redundant root reference.
- Rejected shadcn nova preset extras (tw-animate-css, next-themes, bundled webfonts) — Phase 9 is dark-by-default with no theme toggle and uses a system font stack.
- Used the unified `radix-ui` umbrella package (1.4.3) rather than per-primitive `@radix-ui/*` packages, matching current shadcn output.
- Pinned sonner `Toaster theme="dark"` so toasts match the dark brand field.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] rolldown native binding kept out of package.json**
- **Found during:** Task 1 (scaffold)
- **Issue:** Explicitly pinning the rolldown native binding produced install noise; Vite 8 resolves it transitively.
- **Fix:** Left the binding out of `package.json`; relied on transitive resolution.
- **Files modified:** frontend/package.json
- **Verification:** `npm run build` exits 0.
- **Committed in:** c8c8af7 (Task 1 commit)

**2. [Rule 3 - Blocking] Dropped TS baseUrl**
- **Found during:** Task 1 (tsconfig alias setup)
- **Issue:** Plan called for `baseUrl:"."`, but on TS 6 the `@/*` paths alias resolves without it; the extra field was redundant.
- **Fix:** Configured `paths` `@/*`→`./src/*` without `baseUrl`.
- **Files modified:** frontend/tsconfig.json, frontend/tsconfig.app.json
- **Verification:** `tsc -b` (part of `npm run build`) passes; `@` imports resolve.
- **Committed in:** c8c8af7 (Task 1 commit)

**3. [Rule 1 - Bug/Correctness] Rejected shadcn nova preset extras**
- **Found during:** Task 2 (shadcn init)
- **Issue:** The shadcn flow offered preset extras (tw-animate-css, next-themes, bundled webfonts) not needed for a dark-by-default, no-toggle, system-font Phase 9.
- **Fix:** Declined those extras; kept the install minimal.
- **Files modified:** frontend/package.json, frontend/components.json
- **Verification:** Lockfile reviewed at human-verify checkpoint — no surprise packages.
- **Committed in:** 5d8e741 (Task 2 commit)

**4. [Rule 1 - Correctness] radix-ui unified umbrella package**
- **Found during:** Task 2 (component install)
- **Issue:** Current shadcn output references the unified `radix-ui` package rather than per-primitive `@radix-ui/*` packages.
- **Fix:** Used `radix-ui` 1.4.3 as the single dependency.
- **Files modified:** frontend/package.json
- **Verification:** Components build and render; build exits 0.
- **Committed in:** 5d8e741 (Task 2 commit)

**5. [Rule 1 - Correctness] sonner Toaster pinned theme="dark"**
- **Found during:** Task 2 (sonner install)
- **Issue:** Default sonner theme follows system; the SPA is dark-by-default, so toasts could mismatch the brand field.
- **Fix:** Pinned `<Toaster theme="dark" />`.
- **Files modified:** frontend/src/components/ui/sonner.tsx
- **Verification:** Renders dark at the human-verify checkpoint.
- **Committed in:** 5d8e741 (Task 2 commit)

---

**Total deviations:** 5 auto-fixed (2 blocking, 3 correctness). All within the locked stack — no architectural change, no new top-level dependency beyond the shadcn-prescribed set.
**Impact on plan:** All adjustments preserve the D-01/D-10/D-11/D-12 intent and keep the build green. No scope creep.

## Issues Encountered
- Continuation cleanup: the prior executor left a throwaway Card/Input/Label/Button verification harness in `App.tsx` (uncommitted) for the human-verify checkpoint. After approval, `App.tsx` was reverted to the committed trivial placeholder; because the harness was never committed, the revert restored the working tree to the committed state (no new commit required). Background Vite dev server stopped.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Foundation ready: buildable SPA, brand tokens, and primitives are in place for Plan 02 (static serving under /app/), Plan 03 (auth), and Plan 04 (app shell + providers/router).
- No blockers. Data layer (QueryClientProvider / RouterProvider) and boot guard intentionally deferred to Plans 03/04.

## Self-Check: PASSED

All 10 claimed files exist; both task commits (c8c8af7, 5d8e741) present in git history.

---
*Phase: 09-spa-scaffold-auth-design-system*
*Completed: 2026-06-06*
