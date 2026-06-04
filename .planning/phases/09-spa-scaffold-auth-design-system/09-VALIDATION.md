---
phase: 9
slug: spa-scaffold-auth-design-system
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-04
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Backend: `pytest` (existing — `tests/test_api_csrf.py` etc.). Frontend: **none yet** — Phase 9 is a scaffold; the SC#5 proof is a browser/manual check by design (D-08). `npm run build` is the de-facto type+compile gate. |
| **Config file** | Existing repo `pytest` config; no frontend test runner in Phase 9 scope. |
| **Quick run command** | `pytest tests/ -k "static or app_mount or spa" -x` + `cd frontend && npm run build` |
| **Full suite command** | `pytest tests/ -x` + `cd frontend && npm run build` |
| **Estimated runtime** | ~30 seconds (backend suite) + ~10–20s frontend build |

---

## Sampling Rate

- **After every task commit:** Run `cd frontend && npm run build` (catches Vite/Tailwind/TS breakage fast); add `pytest tests/ -k spa -x` once Wave-0 serving tests exist.
- **After every plan wave:** Run `pytest tests/ -x` (full backend suite — bot core + Phase 8 API untouched) + `cd frontend && npm run build`.
- **Before `/gsd:verify-work`:** Full backend suite green; all five SC manually verified in a browser.
- **Max feedback latency:** ~50 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 09-XX-XX | TBD | 0 | SPA-01 | — | `/app/` and deep-link `/app/login` return SPA `index.html`; `/api/v2/trading-status` still returns JSON (mount didn't shadow API) | integration | `pytest tests/test_spa_serving.py -x` | ❌ W0 | ⬜ pending |
| 09-XX-XX | TBD | — | SPA-01 | — | No Node binary in runtime image | smoke/manual | `docker run … sh -c 'command -v node' ` returns nonzero | ❌ W0 (CI/manual) | ⬜ pending |
| 09-XX-XX | TBD | — | SPA-02 | — | No `tailwind.config.js`; build succeeds on Tailwind v4 | build/smoke | `test ! -f frontend/tailwind.config.js && (cd frontend && npm run build)` | ❌ W0 | ⬜ pending |
| 09-XX-XX | TBD | — | SPA-02 | — | shadcn Card/Input/Button render opaque dark-palette tokens | manual (browser) | Visual check — opaque + correct palette | manual | ⬜ pending |
| 09-XX-XX | TBD | — | SPA-03 | T (auth) | Cold login succeeds; `localStorage` empty of auth tokens; sends `X-CSRF-Token` + `credentials:same-origin` | manual (browser devtools) | Log in, then `Object.keys(localStorage)` has no session/token | manual (server side ✅ via `tests/test_api_csrf.py`) | ⬜ pending |
| 09-XX-XX | TBD | — | SPA-04 | — | Expired session → single redirect to `/app/login`, no loop | manual (browser) | Clear session cookie, trigger authed query, confirm one redirect | manual | ⬜ pending |
| 09-XX-XX | TBD | — | SPA-05 | — | Polling probe runs ≥2 refetch cycles without clobbering an open input/modal | manual (browser) — **headline SC** | Type in probe input, watch ≥2 refetch ticks, confirm text intact | manual | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*Task IDs are placeholders — the planner assigns real IDs; this map binds each SPA requirement to its proof type.*

---

## Wave 0 Requirements

- [ ] `tests/test_spa_serving.py` — asserts `/app/` and deep-link `/app/login` both return the SPA `index.html` (200, HTML), and `/api/v2/trading-status` still returns JSON (mount didn't shadow the API). Covers SPA-01 + Pitfall 1 (the `StaticFiles(html=True)` deep-link 404 trap).
- [ ] No frontend test runner required for Phase 9 — the SC are browser-verifiable by design. An optional single Vitest "renders `<App/>` without crashing" is not load-bearing.
- [ ] Build-as-test: `cd frontend && npm run build` is the de-facto type+compile gate (TS strict catches API-shape drift).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| shadcn components render opaque dark-palette tokens | SPA-02 | Visual/render correctness can't be asserted in a serving test | Render Card/Input/Button; confirm opaque backgrounds + correct `#252542`/`#1a1a2e`/`#0f0f1a` mapping |
| Cold login + no localStorage tokens | SPA-03 | Browser cookie/storage state; httpOnly cookie not JS-visible | Log in through SPA; devtools → Application → confirm `telebot_session` httpOnly cookie set and `localStorage` has no auth token |
| Single global 401 redirect, no loop | SPA-04 | Requires a live expired-session browser flow | Clear session cookie, trigger an authed query, confirm exactly one redirect to `/app/login` |
| Deep-link reload resolves to shell | SPA-01 | Hard-reload behavior (also covered by serving test, but confirm in browser) | Navigate to `/app/login`, press F5, confirm shell loads (not 404) |
| Polling probe ≥2 cycles without clobbering input | SPA-05 | The headline structural proof — server-state vs form-state split | Type in probe input, leave focused, watch ≥2 `refetchInterval` ticks (~3s each), confirm typed text intact |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies (manual SC explicitly enumerated above per D-08)
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify (`npm run build` covers every frontend task)
- [ ] Wave 0 covers all MISSING references (`tests/test_spa_serving.py`)
- [ ] No watch-mode flags
- [ ] Feedback latency < 50s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
