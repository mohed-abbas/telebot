---
phase: 12
slug: parallel-run-cutover-htmx-decommission
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-07
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Sourced from `12-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio (httpx `ASGITransport` over `app`); vitest (frontend) |
| **Config file** | `tests/conftest.py` (session-scoped event loop + asyncpg pool); `frontend/` vitest via `package.json` |
| **Quick run command** | `pytest tests/test_cutover_redirects.py tests/test_spa_serving.py -x` |
| **Full suite command** | `pytest tests/ -x && cd frontend && npm run build && npx vitest run` |
| **Estimated runtime** | ~60–120 seconds (backend suite); SPA build adds ~30s |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_cutover_redirects.py -x` (CUT-02 commits) or `python -c "import dashboard" && python -c "import api"` (CUT-03 teardown commits)
- **After every plan wave:** Run `pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite + `npm run build` + `vitest run` must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

> Task IDs are assigned by the planner (step 8). The Requirement → automated-command
> mapping below is fixed by research; the planner binds each command to a concrete task.

| Requirement | Behavior | Test Type | Automated Command | File Exists |
|-------------|----------|-----------|-------------------|-------------|
| CUT-01 | `/api/v2` not shadowed by `/app` mount (precedence) | integration | `pytest tests/test_spa_serving.py::test_api_not_shadowed_by_spa_mount -x` | ✅ |
| CUT-02 | Legacy page returns 303 → `/app/<page>` after cutover | integration | `pytest tests/test_cutover_redirects.py -x` | ❌ W0 |
| CUT-02 | Unauth hit bounces to `/app/login` (post Pitfall-4 repoint) | integration | `pytest tests/test_cutover_redirects.py::test_unauth_redirects_to_app_login -x` | ❌ W0 |
| CUT-02 | Per-page parity vs MT5 demo (data match, live-money correct, no console errors, poll-safe) | manual (operator) | `12-CUTOVER-CHECKLIST.md` dated sign-off | ❌ W0 (doc) |
| CUT-03 | Deleted routes 404 / app boots / `/health` 200 / `/app/` 200 | integration | `pytest tests/test_post_teardown.py -x` | ❌ W0 |
| CUT-03 | No dangling imports; `api/` keeps its 6 helpers; image builds | smoke | `python -c "import dashboard" && python -c "import api"` + `docker build .` | ✅ (cmds) |
| CUT-03 | SPA still builds (no shared CSS/asset broke) | smoke | `cd frontend && npm run build` | ✅ |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_cutover_redirects.py` — assert each legacy page route returns 303 to its `/app/<page>` target (CUT-02), parameterized over the D-05 page list; assert unauth → `/app/login`
- [ ] `tests/test_post_teardown.py` — assert deleted routes 404 + surviving routes (`/health`, `/app/`, `/api/v2/*`, `/` → 303 `/app/`) + `import api` resolves (the 6-helper guard)
- [ ] `.planning/phases/12-parallel-run-cutover-htmx-decommission/12-CUTOVER-CHECKLIST.md` — one row per page (D-04/D-05 order) mirroring `06-HUMAN-UAT.md`, parity items + dated operator sign-off
- [ ] No new test framework install — pytest + vitest already present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Per-page MT5-demo parity (SPA numbers == legacy on live data; live-money actions confirmed against demo broker; no console errors; poll-safe modals/drilldowns) | CUT-02 | Requires a live MT5-demo session + operator eyes on real data; cannot be asserted in CI | Per page, in D-05 order: open legacy + `/app/<page>`, compare values on live data, exercise live-money actions against demo, check console, sign `12-CUTOVER-CHECKLIST.md` row before committing the page's 303 redirect |
| 7-day live bake clean + explicit operator GO | CUT-03 | A real future obligation (D-07/D-08) — wall-clock bake window, not a runnable check | After full cutover, legacy stays dormant/reachable; operator confirms no regression across 7 days of live trading, then gives explicit go-ahead to run the CUT-03 teardown plan |

---

## Validation Sign-Off

- [ ] All CUT-02/CUT-03 tasks have an `<automated>` verify or a Wave 0 dependency
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers `test_cutover_redirects.py`, `test_post_teardown.py`, and the checklist doc
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
