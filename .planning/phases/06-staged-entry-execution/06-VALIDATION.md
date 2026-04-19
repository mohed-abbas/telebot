---
phase: 6
slug: staged-entry-execution
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-19
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

*Populated by `gsd-planner` — each plan task must map to a row here with an automated command or a Wave 0 stub.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | STAGE-01..09, SET-03 | TBD | TBD | unit/integration | TBD | TBD | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Stubs the planner should ensure exist before any execute wave:

- [ ] `tests/test_signal_parser_text_only.py` — stubs for STAGE-01 (text-only "now" parser)
- [ ] `tests/test_correlator.py` — stubs for STAGE-03 (two-signal correlation, window, one-to-one)
- [ ] `tests/test_staged_executor.py` — stubs for STAGE-02, STAGE-04 (stage-1 default SL, zone-watcher band fire, in-zone-at-arrival)
- [ ] `tests/test_staged_safety_hooks.py` — stubs for STAGE-05, STAGE-06, STAGE-07 (duplicate-guard bypass, reconnect reconciliation, kill-switch drain)
- [ ] `tests/test_staged_attribution.py` — stubs for STAGE-09 (signal_id join; daily-limit + per-symbol cap accounting per D-18/D-19)
- [ ] `tests/test_staged_db.py` — stubs for `staged_entries` DDL round-trip, idempotency UNIQUE on `mt5_comment`
- [ ] `tests/test_settings_form.py` — stubs for SET-03 (tabs, dangerous-change modal, hard caps, audit rollback)
- [ ] `tests/test_pending_stages_sse.py` — stubs for STAGE-08 (SSE payload extension, empty state, cancelled-visibility)
- [ ] `tests/conftest.py` — fixtures: `mock_mt5_connector` with comment round-trip, `staged_entry_factory`, `frozen_settings_snapshot`, `kill_switch_state`

*Reuse existing pytest-asyncio session-scoped event loop per `.planning/codebase/TESTING.md`.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Visual parity of SET-03 form with UI-SPEC | SET-03 | Visual regression not in CI yet | Open `/settings`, compare to `06-UI-SPEC.md` screenshots; tab switching, modal open/close, audit timeline render |
| Live SSE pending-stages panel under real kill-switch | STAGE-07, STAGE-08 | Requires real trading thread + MT5 bridge | Start bot, inject text-only + follow-up, trigger kill switch, verify UI goes to "cancelled" within 2s |
| MT5 comment round-trip on production bridge | STAGE-06 (D-24/D-25) | Research Assumption A1 — bridge source unverified | Open a staged fill, reconnect bridge, verify `get_positions` returns identical `comment` field |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
