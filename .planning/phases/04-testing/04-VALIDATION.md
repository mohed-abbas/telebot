---
phase: 4
slug: testing
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 0.24+ |
| **Config file** | pyproject.toml [tool.pytest.ini_options] |
| **Quick run command** | `python -m pytest tests/ -x -q --timeout=10` |
| **Full suite command** | `python -m pytest tests/ -v --timeout=30` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q --timeout=10`
- **After every plan wave:** Run `python -m pytest tests/ -v --timeout=30`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| TBD | TBD | 1 | TEST-01 | infra | `pip install -r requirements-dev.txt && pytest --version` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | TEST-02 | unit | `pytest tests/test_mt5_connector.py -v` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | TEST-03 | integration | `pytest tests/test_trade_manager.py -v` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | TEST-04 | async | `pytest tests/test_async_concurrency.py -v` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | TEST-05 | regression | `pytest tests/test_signal_parser.py -v` | ❌ W0 | ⬜ pending |

---

## Wave 0 Requirements

- [ ] `requirements-dev.txt` with pytest, pytest-asyncio, pytest-mock, pytest-cov
- [ ] `tests/conftest.py` with DB fixtures, mock connectors, test accounts
- [ ] `pyproject.toml` with pytest configuration

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real Telegram signal samples | TEST-05 | User provides data | User pastes real signals into test fixtures |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
