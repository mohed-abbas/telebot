---
phase: 6
slug: staged-entry-execution
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-19
updated: 2026-04-19
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | `pytest.ini` (existing) |
| **Quick run command** | `pytest tests/ -x --ff -q -m "not slow"` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~90 seconds (quick), ~5 minutes (full) |

---

## Sampling Rate

- **After every task commit:** Run quick command
- **After every plan wave:** Run full suite
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-T0 | 01 | 1 | STAGE-01, STAGE-03, STAGE-09 | — | Test scaffolds collect without syntax errors; RED state confirmed | unit | `pytest tests/test_staged_db.py tests/test_signal_parser_text_only.py tests/test_correlator.py --collect-only -q` | tests/test_staged_db.py, tests/test_signal_parser_text_only.py, tests/test_correlator.py, tests/conftest.py | ⬜ pending |
| 06-01-T1 | 01 | 1 | STAGE-09 (schema) | T-06-01, T-06-02, T-06-03 | staged_entries DDL + UNIQUE(mt5_comment) + signal_daily_counted idempotency | unit+integration | `pytest tests/test_staged_db.py -v` | db.py, models.py, tests/test_staged_db.py | ⬜ pending |
| 06-01-T2 | 01 | 1 | STAGE-01, STAGE-03 | T-06-05 | Text-only parser + one-to-one correlator + bot wiring | unit | `pytest tests/test_signal_parser_text_only.py tests/test_correlator.py -v` | signal_parser.py, signal_correlator.py, bot.py, tests/test_signal_parser_text_only.py, tests/test_correlator.py | ⬜ pending |
| 06-02-T1 | 02 | 2 | STAGE-02, STAGE-05, STAGE-09 | T-06-08, T-06-09, T-06-10, T-06-13 | Default-SL reject + dup-guard bypass + 1-signal-1-slot + per-symbol cap + mt5_comment attribution | integration | `pytest tests/test_staged_safety_hooks.py tests/test_staged_attribution.py -v` | trade_manager.py, tests/test_staged_safety_hooks.py, tests/test_staged_attribution.py | ⬜ pending |
| 06-02-T2 | 02 | 2 | STAGE-02, STAGE-04 | T-06-13, T-06-14 | compute_bands + in-zone-at-arrival + correlated follow-up DB inserts + equal-split sizing | unit+integration | `pytest tests/test_staged_executor.py -v` | trade_manager.py, tests/test_staged_executor.py | ⬜ pending |
| 06-03-T1 | 03 | 2 | SET-03 | T-06-15, T-06-16, T-06-17, T-06-18, T-06-19 | CSRF + hard caps 422 + two-step modal + audit rollback via confirm path | integration (route) | `pytest tests/test_settings_form.py -v` | dashboard.py, tests/test_settings_form.py | ⬜ pending |
| 06-03-T2 | 03 | 2 | SET-03 | — | Template compile + UI-SPEC conformance (grep spot-check in plan) | compile | `python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('templates')); [env.get_template(t) for t in ['settings.html','partials/account_settings_tab.html','partials/settings_audit_timeline.html','partials/settings_confirm_modal.html']]"` | templates/settings.html, templates/partials/account_settings_tab.html, templates/partials/settings_audit_timeline.html, templates/partials/settings_confirm_modal.html | ⬜ pending |
| 06-04-T1 | 04 | 3 | STAGE-04, STAGE-07 | T-06-23, T-06-24, T-06-25, T-06-27, T-06-30, T-06-38 | _zone_watch_loop cadence + _trading_paused mid-tick + pre-flight re-check + idempotency probe + kill-switch drain order + D-16 stage-1-exit cascade | integration | `pytest tests/test_staged_safety_hooks.py -v -k "zone_watch or emergency_close or resume_trading or cascade or stage1_closed"` | executor.py, tests/test_staged_safety_hooks.py | ⬜ pending |
| 06-04-T2 | 04 | 3 | STAGE-06 | T-06-25, T-06-26 | Reconnect reconciliation by comment prefix + stale-no-match abandonment | integration | `pytest tests/test_staged_safety_hooks.py -v -k "reconnect"` | executor.py, tests/test_staged_safety_hooks.py | ⬜ pending |
| 06-05-T1 | 05 | 3 | STAGE-08 | T-06-31, T-06-32, T-06-35 | SSE payload extension + /staged route + /partials/pending_stages polling fallback + X-Accel-Buffering preserved | integration (SSE) | `pytest tests/test_pending_stages_sse.py -v` | dashboard.py, tests/test_pending_stages_sse.py | ⬜ pending |
| 06-05-T2 | 05 | 3 | STAGE-08 | — | Template compile + price-flash JS helper + UI-SPEC conformance (grep spot-check in plan) | compile | `python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('templates')); [env.get_template(t) for t in ['staged.html','partials/pending_stages.html','overview.html']]"` | templates/staged.html, templates/partials/pending_stages.html, templates/overview.html, static/js/htmx_basecoat_bridge.js | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Stubs that MUST exist before any execute wave. All of these are created by **Plan 01 Task 0** (the plan's first task — not a shared pre-wave). Plan 02/04/05 tasks extend these files in place rather than creating them.

- [x] `tests/test_signal_parser_text_only.py` — stubs for STAGE-01 (text-only "now" parser). Owner: 06-01-T0.
- [x] `tests/test_correlator.py` — stubs for STAGE-03 (two-signal correlation, window, one-to-one). Owner: 06-01-T0.
- [x] `tests/test_staged_db.py` — stubs for staged_entries DDL round-trip, idempotency UNIQUE on mt5_comment. Owner: 06-01-T0.
- [ ] `tests/test_staged_executor.py` — full test set (stubs not needed; Plan 02 depends on Plan 01 so its helpers exist). Owner: 06-02-T2.
- [ ] `tests/test_staged_safety_hooks.py` — created by 06-02-T1 (default-SL + dup-guard tests); extended by 06-04-T1/T2 (zone-watch + D-16 cascade + kill-switch + reconnect tests).
- [ ] `tests/test_staged_attribution.py` — Owner: 06-02-T1.
- [ ] `tests/test_settings_form.py` — Owner: 06-03-T1.
- [ ] `tests/test_pending_stages_sse.py` — Owner: 06-05-T1.
- [x] `tests/conftest.py` — fixtures: add `staged_entries` + `signal_daily_counted` to TRUNCATE list; `seeded_signal` fixture if not present. Owner: 06-01-T0.

The Plan-01 Wave-0 stubs set the RED baseline for Plan-01-T1/T2. Plans 02–05 own the creation of their own test files as the FIRST action of their first task (Nyquist rule — no test-free task ships).

*Reuse existing pytest-asyncio session-scoped event loop per `.planning/codebase/TESTING.md`.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Visual parity of SET-03 form with UI-SPEC | SET-03 | Visual regression not in CI yet | Open `/settings`, compare to `06-UI-SPEC.md` screenshots; tab switching, modal open/close, audit timeline render |
| Live SSE pending-stages panel under real kill-switch | STAGE-07, STAGE-08 | Requires real trading thread + MT5 bridge | Start bot, inject text-only + follow-up, trigger kill switch, verify UI goes to "cancelled" within 2s |
| MT5 comment round-trip on production bridge | STAGE-06 (D-24/D-25) | Research Assumption A1 — bridge source unverified | Open a staged fill, reconnect bridge, verify `get_positions` returns identical `comment` field |
| Price-flash on `data-price-cell` tick changes | STAGE-08 (UI-SPEC) | Client-side rendering + DOM timing not in unit tests | Open `/staged` with active sequences and a real MT5 connection; observe 150ms indigo ring flash on price cells as bid/ask ticks |
| Stage-1-exit cascade under live MT5 | STAGE-04 (D-16) | Requires real SL/TP or manual close on broker side to trigger externally | Fire a full staged sequence; close stage 1 manually via MT5 terminal; verify remaining stages transition to `cancelled_stage1_closed` on next 10s tick |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (every task row in the map has a command)
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 90s (quick command is ~90s; per-task commands are targeted subsets <30s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
