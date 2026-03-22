---
phase: 2
slug: reliability
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio |
| **Config file** | pyproject.toml or pytest.ini (from Phase 4 — not yet created) |
| **Quick run command** | `python -m pytest tests/ -x -q --timeout=10` |
| **Full suite command** | `python -m pytest tests/ -v --timeout=30` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run inline Python AST checks (same as Phase 1)
- **After every plan wave:** Verify key patterns via grep/Python scripts
- **Before `/gsd:verify-work`:** Full verification must pass
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | REL-01 | code check | grep for heartbeat loop + backoff | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | REL-02 | code check | grep for position sync after reconnect | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | REL-03 | code check | grep for kill switch endpoint + trading_paused flag | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | REL-04 | code check | grep for order state check before cancel | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | EXEC-01 | code check | grep for extracted zone functions | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | EXEC-02 | code check | grep for double stale check | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | EXEC-03 | code check | grep for SL/TP direction validation | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | EXEC-04 | code check | grep for daily limit display in dashboard | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DB-03 | code check | grep for archival function | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*No test framework setup needed — Phase 2 uses inline verification (same as Phase 1). Full test infrastructure is Phase 4.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Kill switch closes all positions | REL-03 | Requires running MT5 with positions | Open positions in dry-run, press kill switch, verify all closed |
| Reconnection after MT5 disconnect | REL-01 | Requires simulating network failure | Kill MT5 Wine process, verify bot reconnects and Discord alerts fire |
| Dashboard shows daily trade count | EXEC-04 | Visual verification | Open dashboard, execute trades, verify counter updates |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
