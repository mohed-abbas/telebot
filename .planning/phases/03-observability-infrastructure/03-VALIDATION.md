---
phase: 3
slug: observability-infrastructure
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Inline Python AST checks + shell commands (pytest is Phase 4) |
| **Quick run command** | `python -c "import ast; [ast.parse(open(f).read()) for f in ['signal_parser.py','dashboard.py','bot.py','db.py']]"` |
| **Full suite command** | Same as quick (no test framework yet) |
| **Estimated runtime** | ~2 seconds |

---

## Sampling Rate

- **After every task commit:** Run inline Python verification from task `<automated>` block
- **After every plan wave:** Verify all modified files parse without syntax errors
- **Before `/gsd:verify-work`:** Full verification must pass
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01/T1 | 01 | 1 | OBS-01, OBS-04 | code check | inline Python AST + grep | N/A | ⬜ pending |
| 03-01/T2 | 01 | 1 | OBS-01 | code check | inline Python grep | N/A | ⬜ pending |
| 03-01/T3 | 01 | 1 | OBS-02 | file check | test -f docs/server-messages.md | N/A | ⬜ pending |
| 03-02/T1 | 02 | 1 | OBS-03, ANLYT-01 | code check | inline Python AST | N/A | ⬜ pending |
| 03-02/T2 | 02 | 1 | ANLYT-01 | file check | inline Python template check | N/A | ⬜ pending |
| 03-03/T1 | 03 | 2 | INFRA-01 | code check | inline Python AST | N/A | ⬜ pending |
| 03-03/T2 | 03 | 2 | INFRA-03, INFRA-04 | file check | test -f nginx/telebot.conf | N/A | ⬜ pending |
| 03-03/T3 | 03 | 2 | INFRA-02 | file check | test -f docs/telethon-eval.md | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*No test framework setup needed — Phase 3 uses inline verification. Full test infrastructure is Phase 4 scope.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Server message documentation accuracy | OBS-02 | Content review | Read docs/server-messages.md, verify it matches actual bot behavior |
| Telethon evaluation accuracy | INFRA-02 | Content review | Read docs/telethon-eval.md, verify findings are current |
| Docker network connectivity | INFRA-03 | Requires VPS | Deploy to VPS, verify bot connects to shared PostgreSQL via data-net |
| Nginx proxy + HTTPS | INFRA-04 | Requires VPS + domain | Deploy nginx config, verify HTTPS access to dashboard |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
