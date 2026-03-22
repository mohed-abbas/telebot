---
phase: 1
slug: foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio |
| **Config file** | pytest.ini or pyproject.toml (Wave 0 creates if missing) |
| **Quick run command** | `python -m pytest tests/ -x -q --timeout=10` |
| **Full suite command** | `python -m pytest tests/ -v --timeout=30` |
| **Estimated runtime** | ~5 seconds |

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
| TBD | TBD | TBD | SEC-01 | unit | `pytest tests/test_db.py -k field_whitelist` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SEC-02 | unit | `pytest tests/test_config.py -k dashboard_creds` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SEC-03 | unit | `pytest tests/test_config.py -k env_validation` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SEC-04 | manual | See manual verifications | N/A | ⬜ pending |
| TBD | TBD | TBD | DB-01 | integration | `pytest tests/test_db.py -k asyncpg` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DB-02 | unit | `pytest tests/test_db.py -k utc_timestamp` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DB-04 | unit | `pytest tests/test_config.py -k magic_number` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_db.py` — stubs for DB-01, DB-02, SEC-01
- [ ] `tests/test_config.py` — stubs for SEC-02, SEC-03, DB-04
- [ ] `tests/conftest.py` — shared fixtures (test database, mock env)
- [ ] `requirements-dev.txt` — pytest, pytest-asyncio, pytest-mock

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| MT5 passwords cleared from memory | SEC-04 | Requires runtime memory inspection | After MT5 init, inspect connector object attributes; verify password field is empty string |
| Bot refuses to start with missing env vars | SEC-03 | Requires process startup verification | Run bot with missing TG_API_ID, verify SystemExit with clear error message |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
