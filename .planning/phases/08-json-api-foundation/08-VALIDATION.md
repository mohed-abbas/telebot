---
phase: 8
slug: json-api-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-01
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `08-RESEARCH.md` → Validation Architecture (HIGH confidence).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.5 + pytest-asyncio 0.25.3 (`asyncio_mode = "auto"`, `loop_scope = "session"`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `.venv/bin/python -m pytest tests/test_api_*.py -x` |
| **Full suite command** | `.venv/bin/python -m pytest -m "not integration"` (add integration when dev Postgres up) |
| **Test client** | `fastapi.testclient.TestClient` with module-scoped app re-import (`tests/test_login_flow.py` pattern) |
| **Live DB** | dev Postgres at `localhost:5433` (`docker-compose.dev.yml`); conftest `db_pool` fixture skips if absent |
| **Estimated runtime** | ~15 seconds (unit/contract); idempotency + CSRF regression add ~5s with dev Postgres |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest tests/test_api_*.py -x`
- **After every plan wave:** Run `.venv/bin/python -m pytest -m "not integration"` **plus** the bot-core diff guard `git diff --exit-code executor.py trade_manager.py db.py mt5_connector.py mt5-rest-server/`
- **Before `/gsd:verify-work`:** Full suite green (incl. DB-backed idempotency + CSRF regression with dev Postgres up). The CSRF regression (D-16) is a **hard gate** — no mutation route ships without it.
- **Max feedback latency:** ~20 seconds

---

## Per-Task Verification Map

> Task IDs are assigned by the planner. Rows below are keyed by requirement and resolve to the named test files; the planner must map each row to the concrete task that produces it.

| Requirement | Behavior | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|------------|-----------------|-----------|-------------------|-------------|--------|
| API-01 | Each read route returns Pydantic-modeled JSON (200) with expected keys | — | N/A | contract | `pytest tests/test_api_contract.py -x` | ❌ W0 | ⬜ pending |
| API-01 | `git diff` shows zero change to bot core + MT5 bridge | — | bot core untouched | guard | `git diff --exit-code executor.py trade_manager.py db.py mt5_connector.py mt5-rest-server/` | ❌ W0 | ⬜ pending |
| API-02 | Each mutation returns `{success|error}` JSON envelope, never HTML | — | no HTML/stack leakage | contract | `pytest tests/test_api_contract.py::test_mutations_return_json -x` | ❌ W0 | ⬜ pending |
| API-03 | POST to any `/api/v2` mutation WITHOUT valid `X-CSRF-Token` → 403 | T-8 CSRF | double-submit + `compare_digest` | regression | `pytest tests/test_api_csrf.py -x` | ❌ W0 | ⬜ pending |
| API-03 | Valid `X-CSRF-Token` matching `telebot_csrf` cookie passes; name ≠ `telebot_login_csrf` | T-8 CSRF | no cookie-name collision | regression | `pytest tests/test_api_csrf.py::test_valid_token_passes -x` | ❌ W0 | ⬜ pending |
| API-04 | XAUUSD position returns raw `open_price` + `open_price_display` (2dp); time as ISO-8601+offset + display | — | server-side formatting only | contract | `pytest tests/test_api_formatting.py -x` | ❌ W0 | ⬜ pending |
| API-05 | Same `request_id` + same params → second submit replays cached 200, broker called once | T-8 Replay | idempotent money op | regression | `pytest tests/test_api_idempotency.py::test_replay -x` | ❌ W0 | ⬜ pending |
| API-05 | Same `request_id` + different params → 409 | T-8 Replay | conflict detection | regression | `pytest tests/test_api_idempotency.py::test_conflict -x` | ❌ W0 | ⬜ pending |
| API-05 | `close_volume` outside `(0, pos.volume)` → 422; absolute (not percent) semantics | — | input validation | contract | `pytest tests/test_api_idempotency.py::test_volume_validation -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_api_contract.py` — read-route shapes + mutation-returns-JSON (API-01, API-02)
- [ ] `tests/test_api_csrf.py` — mandatory CSRF regression (API-03, D-16) — **hard gate**
- [ ] `tests/test_api_idempotency.py` — replay / conflict / volume-validation against dev Postgres (API-05)
- [ ] `tests/test_api_formatting.py` — XAUUSD dual-value + ISO-8601 (API-04)
- [ ] Bot-core diff guard — script or pytest shelling `git diff --exit-code` over the four core files + `mt5-rest-server/`
- [ ] Shared fixture: `DryRunConnector`-backed executor stub wired through `init_dashboard()` so contract tests run without a live broker (extend `tests/conftest.py`; `DryRunConnector` already exists at `mt5_connector.py:165`)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live partial-close double-fire on a real position closes exactly once | API-05 | Final confidence needs a real MT5 position; automated test uses DryRunConnector | On VPS staging: open a small position, fire two identical partial-close requests with the same `request_id`, confirm broker shows one fill and the second returns the cached envelope |
| curl of a live `/api/v2` read endpoint returns display-ready + machine-precise XAUUSD values | API-04 | Confirms real broker tick formatting end-to-end | `curl -s --cookie-jar` an authed session, GET the positions endpoint for a live XAUUSD position, eyeball pip-sized `*_display` vs raw numeric |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (the 4 named test files + diff guard + fixture)
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
