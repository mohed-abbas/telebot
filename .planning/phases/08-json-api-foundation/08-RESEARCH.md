# Phase 8: JSON API Foundation - Research

**Researched:** 2026-06-01
**Domain:** FastAPI in-process JSON API (`/api/v2`) over an existing HTMX dashboard; Pydantic v2 serialization; double-submit CSRF; PostgreSQL idempotency for a real-money operation; server-side number/time formatting
**Confidence:** HIGH — every claim is grounded in the actual repo (`dashboard.py`, `db.py`, `mt5_connector.py`, `docker-compose*.yml`, `nginx/`, installed venv) and the prior HIGH-confidence v1.2 research synthesis (`.planning/research/ARCHITECTURE.md`), not generic FastAPI advice.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Idempotency storage (D-01..D-04)**
- **D-01:** Partial-close dedup lives in a **new PostgreSQL table** (e.g. `idempotency_keys`) — NOT in-memory, NOT Redis. Scout confirmed Redis is not wired in either compose file; durability-across-restart wins for a real-money op.
- **D-02:** Idempotency key is **`request_id` alone** (sole PK). Row also stores `account`, `ticket`, `close_volume` so a replay with the SAME id but DIFFERENT params is detectable.
- **D-03:** **Short TTL (~24h)** with cheap periodic age-out cleanup — mirrors the existing `failed_login_attempts` age-out. (Exact TTL value + cleanup mechanism = planner's call within "short, age-out".)
- **D-04:** Table creation uses **additive-only DDL** (no Alembic). New table only — no alteration of existing tables.

**Dual-value JSON field shape (D-05..D-08)**
- **D-05:** **Parallel suffixed fields**, not nested `{raw, display}`. Pattern: `price: 1.2345` + `price_display: "1.23"`. Only price/money-P&L/volume/timestamps get a `_display` twin; plain ints/strings/enums stay bare.
- **D-06:** Machine-precise timestamps are **ISO-8601 with UTC offset**; the `*_display` twin is an **absolute, fixed-timezone** string (NOT relative "3m ago").
- **D-07:** Display timestamps render in **UTC** with an explicit `UTC` marker.
- **D-08:** A **single shared formatter module** (e.g. `api/formatting.py`) owns pip-size-aware price formatting, money formatting, and timestamp formatting; the symbol→digits map lives there; every model's `_display` field routes through it.

**Partial-close contract (D-09..D-11)**
- **D-09:** Request body carries **`close_volume` in absolute lots** (amount to CLOSE, e.g. `0.05`). Server validates `0 < close_volume < pos.volume` and rounds to the symbol lot step.
- **D-10:** `request_id` is **client-supplied** (SPA generates a UUID per partial-close action).
- **D-11:** Duplicate-submit semantics:
  - same `request_id` + **same** params → **replay the cached success (200)**, do NOT touch the broker.
  - same `request_id` + **different** params → reject **409 Conflict**.

**Auth-JSON scope (D-12..D-14)**
- **D-12:** Phase 8 ships the **complete `/api/v2/auth/{login,logout,me,csrf}`** JSON contract now.
- **D-13:** Legacy HTMX `/login` form and its `telebot_login_csrf` cookie stay **untouched and operational in parallel**. The new `telebot_csrf` cookie must **not collide** with `telebot_login_csrf` (`dashboard.py:142`).
- **D-14:** API login **reuses the existing rate-limit** path verbatim (`db.get_failed_login_count(ip, 15) ≥ 5`, `_client_ip()` — `dashboard.py:247-252`) returned as a JSON 429. The nginx `limit_req zone=telebot_login` must also cover `/api/v2/auth/login`.

**CSRF mechanism (D-15..D-16)**
- **D-15:** New API CSRF = readable (`httponly=false`) `telebot_csrf` cookie, `SameSite=Lax`, `Secure`, `path=/`, set on login success and `GET /api/v2/auth/csrf`; SPA echoes it as `X-CSRF-Token`; server compares with `secrets.compare_digest`. The HTMX-era `_verify_csrf` heuristic (`dashboard.py:128-135`) is **replaced for `/api/v2`** by a new dependency — NOT deleted.
- **D-16:** A regression test proving `POST` to any `/api/v2` mutation WITHOUT a valid `X-CSRF-Token` returns `403` is **required before any page goes live**.

### Claude's Discretion
- Router package layout (`api/` package, one module per resource) and the accessor-functions-vs-global-imports technique.
- Error envelope exact shape (recommendation: bare resource on success, enveloped `{error:{code,message,fields?}}` on failure — adopt unless a better fit surfaces).
- Whether to expose `/api/v2` OpenAPI docs internally (`docs_url` scoped).
- Exact `request_id`/idempotency-table column types, the TTL constant, and the cleanup trigger.
- Which existing read helper maps to which Pydantic response model.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope. The SPA itself, login *view*, TanStack Query wiring (Phase 9); legacy HTMX `/login` and legacy `/api/*` HTML route removal (Phase 12); optimistic-update UI discipline (Phase 11) are all explicitly assigned elsewhere.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| API-01 | All dashboard data available via `/api/v2` `APIRouter` with Pydantic models wrapping existing helpers; bot core unmodified | The dict-returning helpers `_get_all_positions()` (`dashboard.py:1401`), `_get_accounts_overview()` (`:1457`), `_enrich_stage_for_ui()` (`:424`), and `db.get_*` exist and return plain dicts — wrap verbatim in Pydantic v2 models. Full read-view inventory in **Standard Stack → Route Inventory**. |
| API-02 | Mutating endpoints return structured `{success, error, ...}` JSON instead of HTML fragments | Current mutations (`dashboard.py:1049-1322`) return `_render_toast_oob(...)` HTML strings. They call `connector.close_position/modify_position` + `db.update_trade_close` directly — port the *calls* unchanged, change only the response shape. **Architecture Patterns → Pattern 2**. |
| API-03 | CSRF on JSON mutations via double-submit cookie (`X-CSRF-Token` echoed from cookie, `compare_digest`), independent of `HX-Request`; login flow preserved; regression-tested | Current `_verify_csrf` (`dashboard.py:128-135`) is the `HX-Request` heuristic to replace for `/api/v2`. The login double-submit pattern already exists (`dashboard.py:237-245`) and uses `_secrets.compare_digest`. **Architecture Patterns → Pattern 3** + **Validation Architecture**. |
| API-04 | Numbers/prices/timestamps formatted server-side, sent display-ready + machine-precise (ISO-8601 + tz); SPA never re-derives precision | Existing pip-size truth lives in `risk_calculator.GOLD_PIP_SIZE` (=0.10) and `trade_manager._pip_size_for_symbol` (`:120`). The XAUUSD quick task (260501-i7u) is the cautionary precedent. **Pitfall 5** + **Don't Hand-Roll**. |
| API-05 | Partial-close switched from percent-of-current to absolute volume + request-id idempotency guard | Current `close_partial` (`dashboard.py:1218-1266`) computes `pos.volume * (percent/100)` — the 75%-double-fire bug. `connector.close_position(ticket, volume=...)` (`mt5_connector.py:742`) already accepts absolute volume. **Architecture Patterns → Pattern 4 (Idempotency)**. |
</phase_requirements>

## Summary

This phase is a **serialization refactor, not a logic rewrite**. Every datum the SPA needs is already computed by in-process helpers in `dashboard.py` that return plain dicts (`_get_all_positions`, `_get_accounts_overview`, `_enrich_stage_for_ui`) or by `db.get_*` coroutines that return `list[dict]`. The dashboard runs **in the same process** as the bot (`init_dashboard()` injects live `_executor`/`_notifier`/`_settings` globals at `dashboard.py:91-96`), so JSON routes call the same live objects with zero IPC. The work is: mount one `APIRouter` at `/api/v2`, wrap the existing helpers in Pydantic v2 models, port the mutation *calls* (not their HTML responses), and add three pieces of genuinely new machinery — a double-submit CSRF dependency, a shared server-side formatter module, and a PostgreSQL-backed idempotency guard for partial-close.

The single most important architectural constraint resolved by this research: **the idempotency table's DDL and its read/write helpers must NOT live in `db.py`**, because `db.py` is on the byte-for-byte-untouched list and `db.py:_create_tables()` (`:78-249`) owns all existing table creation. The new `api/` package must create its own table and own its helpers, using the module-global pool `db._pool` (an *accessor*, not a modification). This is the one place where a naive reading of "additive DDL like Phase 5" would push code into `db.py` and break the hard constraint. The planner must place the idempotency DDL+helpers inside `api/` (e.g. `api/idempotency.py`) and call its `ensure_table()` from the `api/` mount path, not from `db.init_db()`.

Pydantic v2.12.5 and FastAPI 0.115.0 are **already installed** (verified in `.venv`) — no new runtime dependency is required for the core API. `python-multipart` is present (form parsing). No Redis exists in either compose file (verified). The test harness is mature: `fastapi.testclient.TestClient` with a module-scoped app re-import + real Postgres on `localhost:5433` is the established pattern (`tests/test_login_flow.py`), giving a direct path for the curl/pytest contract tests and the mandatory CSRF regression test.

**Primary recommendation:** Build a new `api/` package (`router`, `deps`, `schemas`, `errors`, `formatting`, `idempotency`, + one module per resource: `auth`, `accounts`, `positions`, `history`, `signals`, `stages`, `settings`, `analytics`, `actions`, `meta`). Add exactly **one `include_router` line + a handful of read-only accessor functions** to `dashboard.py`. Wrap existing dict-returning helpers verbatim in Pydantic v2 `response_model`s. Keep all four bot-core files and the MT5 bridge byte-for-byte untouched — they are only ever *called*, never imported-into or edited.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Read serialization (positions, accounts, history, signals, stages, analytics, overview meta) | API / Backend (`api/` package) | — | Computation already done in `dashboard.py` helpers + `db.get_*`; the API only re-shapes their dicts into Pydantic models |
| Number/time formatting (display-ready strings) | API / Backend (`api/formatting.py`) | — | D-08 + Pitfall 5: precision is server-of-truth; SPA must never re-derive. Belongs server-side next to the pip-size constants |
| Mutations (close/modify/partial-close/kill-switch/resume/settings) | API / Backend (`api/actions.py`, `api/settings.py`) | MT5 bridge (called) | Logic exists in current handlers; only response shape changes. Broker calls go through the connector, untouched |
| Auth (login/logout/me/csrf) | API / Backend (`api/auth.py`) | Browser (cookie store) | Session lives in httpOnly `telebot_session`; CSRF token in readable `telebot_csrf` cookie — both set server-side |
| CSRF verification | API / Backend (`api/deps.py`) | Browser (echoes header) | Double-submit: server sets+compares; browser carries cookie and echoes `X-CSRF-Token` |
| Idempotency / dedup of money ops | Database / Storage (`idempotency_keys` table) + API logic (`api/idempotency.py`) | — | D-01: Postgres for durability across restart; logic that reads/writes the row lives in `api/`, not `db.py` |
| Bot-core trade execution | (UNTOUCHED — out of tier scope) | — | Hard constraint: `executor.py`/`trade_manager.py`/`db.py`/`mt5_connector.py` called only, never modified |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | 0.115.0 | `APIRouter(prefix="/api/v2")`, `Depends`, `response_model`, exception handlers | Already the app framework (`dashboard.py:21`); `[VERIFIED: requirements.txt + .venv import]` |
| Pydantic | 2.12.5 | Response models, request-body validation, field-level `Field(...)` | Already installed transitively via FastAPI; v2 (not v1) confirmed via `.venv` import; `[VERIFIED: .venv]` |
| Starlette `SessionMiddleware` | (bundled w/ FastAPI) | `telebot_session` httpOnly cookie auth — reused unchanged | Already wired (`dashboard.py:192-200`); SPA reuses verbatim; `[VERIFIED: dashboard.py]` |
| argon2-cffi (`PasswordHasher`) | 25.1.0 | Password verify in JSON login — reuse `_password_hasher` (`dashboard.py:144`) | Already wired; `[VERIFIED: requirements.txt]` |
| asyncpg | 0.31.0 | Idempotency table I/O via `db._pool.acquire()` | Already the DB driver; pool is a module global (`db.py:18`); `[VERIFIED: db.py]` |
| `secrets` (stdlib) | — | `token_urlsafe(32)` for CSRF token, `compare_digest` for constant-time compare | Already used as `_secrets` (`dashboard.py:13, 239`); `[VERIFIED: dashboard.py]` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `python-multipart` | 0.0.12 | Form parsing — only if any `/api/v2` endpoint accepts form bodies | JSON bodies are preferred for the SPA; settings confirm/validate may read JSON not form. Already installed. `[VERIFIED: requirements.txt]` |
| pytest + pytest-asyncio | 8.3.5 / 0.25.3 | Contract + CSRF regression tests via `TestClient` | All Phase 8 validation. Established harness. `[VERIFIED: requirements-dev.txt]` |
| `fastapi.testclient.TestClient` | (bundled) | Synchronous request testing incl. cookie/header round-trips | Already the pattern (`tests/test_login_flow.py`); `[VERIFIED: tests/]` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Postgres idempotency table | In-memory dict + TTL sweep | Rejected by D-01: lost on restart → a duplicate submit after a crash/redeploy re-hits the broker. Unacceptable for a real-money op. |
| Postgres idempotency table | Redis SETNX | Rejected by D-01: no Redis service in `docker-compose.yml` or `docker-compose.dev.yml` (verified). Adding one is new infra for one operator. |
| Pydantic models | FastAPI returning raw dicts | Loses `response_model` validation + the contract guarantee; the SPA's TS types derive from the documented shape. Use Pydantic. |
| New CSRF dependency | Reuse `_verify_csrf` (`HX-Request`) | Rejected by D-15/Pitfall 2: the SPA cannot send `HX-Request`; the heuristic gives no real protection. Replace for `/api/v2`, keep for legacy. |

**Installation:** No new packages required. Everything is already in `requirements.txt` / `.venv`.

```bash
# Verification performed this session:
.venv/bin/python -c "import fastapi, pydantic; print(fastapi.__version__, pydantic.VERSION)"
# → 0.115.0 2.12.5
```

### Route Inventory — every read view + every mutation (grounded in `dashboard.py`)

**Read views (GET `/api/v2/...`) — each wraps an existing helper, no new query:**

| `/api/v2` route | Backed by (existing, unchanged) | Source line |
|-----------------|----------------------------------|-------------|
| `GET /accounts` | `_get_accounts_overview()` | `dashboard.py:1457` |
| `GET /positions` | `_get_all_positions()` | `dashboard.py:1401` |
| `GET /positions/{account}/{ticket}` (drilldown) | `db.get_position_drilldown(ticket, account)` | `db.py:1199` |
| `GET /history` (+ `account/source/symbol/from_date/to_date` query) | `db.get_filtered_trades(...)` | `db.py:500` |
| `GET /history/filter-options` | `db.get_trade_filter_options()` | `db.py:477` |
| `GET /signals` | `db.get_recent_signals(100)` | `db.py:572` |
| `GET /stages` (active + resolved) | `db.get_pending_stages()` + `db.get_recently_resolved_stages(50)` + `_enrich_stage_for_ui` | `db.py:1057,1144`; `dashboard.py:424` |
| `GET /analytics` (+ `range/source` query) | `db.get_analytics_with_filters(...)` + `db.get_analytics_sources()` | `db.py:647,786` |
| `GET /settings` | `SettingsStore.effective(name)` + `db.get_settings_audit(name,50)` | `dashboard.py:686,558`; `db.py:937` |
| `GET /overview` (meta aggregate) | composes accounts + positions + top-5 stages + flags (`_settings.trading_enabled`, `_executor._trading_paused`) | `dashboard.py:311-332` |
| `GET /trading-status` | `_executor._trading_paused`, `list(_executor._reconnecting)` | `dashboard.py:1325-1331` |
| `GET /emergency/preview` | `_get_all_positions()` + `connector.get_pending_orders()` | `dashboard.py:1274-1298` |

**Mutations (POST `/api/v2/...`) — each ports the broker/DB calls, returns JSON not HTML:**

| `/api/v2` route | Ports the logic of | Source line | New for Phase 8 |
|-----------------|--------------------|-------------|------------------|
| `POST /auth/login` | argon2 verify + rate-limit + session set | `dashboard.py:229-290` | JSON shape + `telebot_csrf` set |
| `POST /auth/logout` | `request.session.clear()` | `dashboard.py:293-298` | JSON shape |
| `GET /auth/me` | `request.session.get("user")` | (new) | returns `{user}` or 401 |
| `GET /auth/csrf` | issue/refresh `telebot_csrf` | (new) | double-submit token endpoint |
| `POST /positions/{account}/{ticket}/close` | `connector.close_position(ticket)` + `db.update_trade_close` | `dashboard.py:1049-1068` | JSON envelope |
| `POST /positions/{account}/{ticket}/levels` (modify SL/TP) | `connector.modify_position(ticket, sl, tp)` | `dashboard.py:1141-1215` | JSON envelope |
| `POST /positions/{account}/{ticket}/close-partial` | `connector.close_position(ticket, volume=close_volume)` | `dashboard.py:1218-1266` | **absolute volume + request_id idempotency** |
| `POST /emergency/close` | `_executor.emergency_close()` + notify | `dashboard.py:1301-1310` | model the `results` dict |
| `POST /emergency/resume` | `_executor.resume_trading()` + notify | `dashboard.py:1313-1322` | JSON shape |
| `POST /settings/{account}/validate` | `validate_settings_form(...)` → `{valid,errors,diff,dry_run_text}` | `dashboard.py:632-808` | JSON not HTML modal |
| `POST /settings/{account}` (confirm) | `SettingsStore.update(...)` per changed field | `dashboard.py:811-869` | JSON envelope |
| `POST /settings/{account}/revert` | inverted-diff persist | `dashboard.py:872-914` | JSON envelope |

> Note: the two legacy DEPRECATED endpoints `POST /api/modify-sl` and `POST /api/modify-tp` (`dashboard.py:1071-1128`) are superseded by `modify-levels` and need NOT be ported — the SPA uses the atomic levels endpoint only.

## Package Legitimacy Audit

> No external packages are installed in this phase — the entire API is built on libraries already present in `requirements.txt` and the `.venv`. The legitimacy gate is therefore satisfied by registry-pinned existing dependencies.

| Package | Registry | Already pinned | Source Repo | Disposition |
|---------|----------|----------------|-------------|-------------|
| fastapi==0.115.0 | PyPI | yes (`requirements.txt`) | github.com/fastapi/fastapi | Approved (existing) |
| pydantic==2.12.5 | PyPI | transitive via fastapi (`.venv`) | github.com/pydantic/pydantic | Approved (existing) |
| asyncpg==0.31.0 | PyPI | yes | github.com/MagicStack/asyncpg | Approved (existing) |
| argon2-cffi==25.1.0 | PyPI | yes | github.com/hynek/argon2-cffi | Approved (existing) |
| python-multipart==0.0.12 | PyPI | yes | github.com/Kludex/python-multipart | Approved (existing) |

**Packages removed due to slopcheck [SLOP] verdict:** none (no new installs).
**Packages flagged as suspicious [SUS]:** none.

*slopcheck was not run because Phase 8 installs zero new packages. If the planner later chooses to pin Pydantic explicitly in `requirements.txt`, that pin is the same version already resolved in `.venv` — no new supply-chain surface.*

## Architecture Patterns

### System Architecture Diagram

```
                       ┌──────── shared-nginx (proxy-net) ────────┐
  Browser/curl ─HTTP─▶ │ location /api/  ───────────────▶ uvicorn │   JSON /api/v2
  (SPA in P9)          │ location = /api/v2/auth/login           │   (+ limit_req, D-14)
                       │   (limit_req zone=telebot_login)        │
                       │ location = /login (legacy, untouched)   │
                       │ location /  ────────────────────▶ uvicorn │   legacy HTMX
                       └──────────────────────────────────────────┘
                                            │
        ┌───────────────────────────────────┴────────────────────────────────┐
        │ dashboard.app  (FastAPI — SAME PROCESS as bot.py asyncio main)       │
        │  ├─ SessionMiddleware  telebot_session (httpOnly)   ◀── shared        │
        │  ├─ app.include_router(api_router)   prefix="/api/v2"   ◀── 1 NEW LINE │
        │  │     │                                                              │
        │  │     ├─ deps.py        require_user (reuse _verify_auth 401 branch) │
        │  │     │                 verify_csrf_token (NEW double-submit dep)    │
        │  │     ├─ formatting.py  pip-size/money/ISO-8601 (NEW, single source) │
        │  │     ├─ idempotency.py ensure_table + check/store (NEW, own DDL)    │
        │  │     ├─ auth/accounts/positions/history/signals/stages/             │
        │  │     │   settings/analytics/analytics/actions/meta  (read+mutate)   │
        │  │     └─ errors.py      bare-success / enveloped-error handler       │
        │  └─ legacy HTMX routes (UNTOUCHED — removed page-by-page in P12)      │
        └─────────────────────────────────────────────────────────────────────┘
              │ calls (never modifies)                    │ accessor: db._pool
              ▼                                            ▼
   _executor / connector.* / _get_all_positions()   PostgreSQL (asyncpg)
   _get_accounts_overview() / _enrich_stage_for_ui  ├─ existing tables (db.py owns)
        │                                            └─ idempotency_keys (api/ owns) ◀── NEW
        ▼
   executor.py / trade_manager.py / mt5_connector.py / db.py  — BYTE-FOR-BYTE UNTOUCHED
   MT5 REST bridge (separate svc) — UNTOUCHED
```

Trace the partial-close use case: `curl POST /api/v2/positions/{acct}/{ticket}/close-partial` (body `{close_volume, request_id}` + `X-CSRF-Token`) → `verify_csrf_token` dep → `require_user` dep → `idempotency.check(request_id)` → if replay-match return cached 200; if id-reused-different-params return 409; else → `connector.close_position(ticket, volume=close_volume)` → `idempotency.store(request_id, result)` → JSON envelope.

### Recommended Project Structure

```
api/                         # NEW package — the entire JSON contract
├── __init__.py              # exports api_router = APIRouter(prefix="/api/v2")
├── router.py                # assembles sub-routers via include_router
├── deps.py                  # require_user, verify_csrf_token, get_executor/settings accessors
├── schemas.py               # Pydantic v2 response/request models (parallel _display fields)
├── formatting.py            # D-08: pip-size/money/timestamp single source of truth
├── idempotency.py           # D-01..D-04: own DDL + check/store/ageout (NOT in db.py)
├── errors.py                # bare-success / enveloped-error exception handler
├── auth.py                  # login/logout/me/csrf + telebot_csrf cookie
├── accounts.py
├── positions.py
├── history.py
├── signals.py
├── stages.py
├── settings.py              # validate/confirm/revert as JSON
├── analytics.py
├── actions.py               # close, modify-levels, close-partial, emergency, resume, trading-status
└── meta.py                  # /overview aggregate

dashboard.py                 # MODIFIED minimally: +include_router, +read-only accessors
tests/
├── test_api_contract.py     # NEW: each read route's shape + 401 paths
├── test_api_csrf.py         # NEW: API-03 regression (mutation w/o X-CSRF-Token → 403)
├── test_api_idempotency.py  # NEW: API-05 dedup (replay 200, id-reuse 409)
└── test_api_formatting.py   # NEW: API-04 XAUUSD pip-size + ISO-8601 dual-value
```

### Pattern 1: Accessor functions, not global imports (bot-core isolation)

**What:** `init_dashboard()` rebinds module globals `_executor`/`_notifier`/`_settings` (`dashboard.py:91-96`). `from dashboard import _executor` captures a stale `None` at import time. Expose live objects via accessor functions.
**When to use:** Every `api/` route that needs the live executor/settings/notifier.
**Example:**
```python
# dashboard.py — ADD these (read-only, satisfy "bot core untouched": these are new lines in dashboard.py, NOT in any bot-core file)
def get_executor():       return _executor
def get_notifier():       return _notifier
def get_settings():       return _settings
def get_settings_store(): return _get_settings_store()   # already exists at :686

# api/deps.py
from dashboard import get_executor
def require_executor():
    ex = get_executor()
    if ex is None:
        raise HTTPException(503, "Trading not initialized")
    return ex
```

### Pattern 2: Wrap dict-returning helpers verbatim in `response_model`

**What:** The helpers already return plain dicts; declare a Pydantic model and let FastAPI coerce.
**When to use:** Every read endpoint.
**Example:**
```python
# api/schemas.py
from pydantic import BaseModel
class Position(BaseModel):
    account: str; ticket: int; symbol: str; direction: str
    volume: float; volume_display: str            # D-05 dual value
    open_price: float; open_price_display: str
    sl: float | None; tp: float | None
    profit: float; profit_display: str

# api/positions.py
from dashboard import _get_all_positions
@router.get("/positions", response_model=list[Position])
async def positions(user: str = Depends(require_user)):
    rows = await _get_all_positions()             # dict list — unchanged call
    return [_to_position_model(r) for r in rows]  # add _display fields via formatting.py
```

### Pattern 3: Double-submit CSRF dependency (replaces `HX-Request` for `/api/v2`)

**What:** Set a readable `telebot_csrf` cookie on login + `GET /auth/csrf`; SPA echoes it as `X-CSRF-Token`; compare with `secrets.compare_digest`.
**When to use:** As a `Depends` on every `/api/v2` mutation. (GET reads do not need it.)
**Example:**
```python
# api/deps.py  (verified pattern; mirrors dashboard.py:239 compare_digest use)
import secrets as _secrets
from fastapi import Request, HTTPException
async def verify_csrf_token(request: Request):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        cookie = request.cookies.get("telebot_csrf", "")
        header = request.headers.get("x-csrf-token", "")
        if not cookie or not _secrets.compare_digest(cookie, header):
            raise HTTPException(403, "CSRF token invalid")
```
Cookie set (note: `httponly=False` is what differs from the session cookie; `path="/"` so it covers all `/api/v2`):
```python
resp.set_cookie("telebot_csrf", token, httponly=False, samesite="lax",
                secure=app_settings.session_cookie_secure, path="/")
```

### Pattern 4: PostgreSQL idempotency for partial-close (own DDL, own helpers)

**What:** `request_id`-keyed dedup row stored in a NEW table created by the `api/` package, never by `db.py`.
**When to use:** `close-partial` only (the one non-idempotent money op). Full close is naturally idempotent (second close 404s).
**Example:**
```python
# api/idempotency.py  — uses db._pool as an ACCESSOR; does NOT edit db.py
import db, json
async def ensure_table():                                   # call once at api/ mount
    async with db._pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                request_id   TEXT PRIMARY KEY,
                account      TEXT NOT NULL,
                ticket       BIGINT NOT NULL,
                close_volume DOUBLE PRECISION NOT NULL,
                result       JSONB NOT NULL,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
        await conn.execute("""CREATE INDEX IF NOT EXISTS idx_idempotency_created
                              ON idempotency_keys(created_at)""")   # for age-out

async def check(request_id, account, ticket, close_volume):
    async with db._pool.acquire() as conn:
        row = await conn.fetchrow("SELECT account,ticket,close_volume,result "
            "FROM idempotency_keys WHERE request_id=$1", request_id)
    if row is None:
        return ("new", None)
    same = (row["account"] == account and row["ticket"] == ticket
            and abs(row["close_volume"] - close_volume) < 1e-9)
    return ("replay", json.loads(row["result"])) if same else ("conflict", None)
    # caller maps: new→execute+store, replay→200 cached, conflict→409 (D-11)

async def store(request_id, account, ticket, close_volume, result):
    async with db._pool.acquire() as conn:
        await conn.execute("INSERT INTO idempotency_keys "
            "(request_id,account,ticket,close_volume,result) VALUES ($1,$2,$3,$4,$5) "
            "ON CONFLICT (request_id) DO NOTHING",
            request_id, account, ticket, close_volume, json.dumps(result))

async def age_out(ttl_hours=24):                            # D-03 cheap cleanup
    async with db._pool.acquire() as conn:
        await conn.execute("DELETE FROM idempotency_keys "
            "WHERE created_at < NOW() - make_interval(hours => $1)", ttl_hours)
```
**Race note:** `check`-then-`execute`-then-`store` has a window where two concurrent requests with the same id both read `new`. Mitigate by inserting a placeholder row first (`INSERT ... ON CONFLICT DO NOTHING` returning whether the row was created); if the insert lost the race, treat as replay/conflict. The planner should decide between the simple read-first approach (adequate for a single operator double-clicking, where requests are near-sequential) and the insert-first lock approach (fully concurrency-safe). For a single-operator tool the simple approach is acceptable but the insert-first variant costs little and removes the window — recommend insert-first.

### Pattern 5: Single shared formatter module (D-08, Pitfall 5 structural guard)

**What:** One module owns symbol→digits, pip-size, money, and ISO-8601/UTC-display formatting. Every `_display` field routes through it.
**Example:**
```python
# api/formatting.py
from datetime import timezone
from risk_calculator import GOLD_PIP_SIZE      # = 0.10 (single source, post-260501-i7u)
_SYMBOL_DIGITS = {"XAUUSD": 2}                  # price digits per symbol (extend, never inline)
def price_display(symbol: str, value: float) -> str:
    return f"{value:.{_SYMBOL_DIGITS.get(symbol.upper(), 5)}f}"
def money_display(value: float) -> str:
    return f"{value:,.2f}"
def volume_display(value: float) -> str:
    return f"{value:.2f}"                        # lots, 2 dp (matches close_vol rounding)
def ts_machine(dt) -> str:                       # D-06 machine-precise
    return dt.astimezone(timezone.utc).isoformat()
def ts_display(dt) -> str:                        # D-06/D-07 absolute UTC string
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
```

### Anti-Patterns to Avoid

- **Putting idempotency DDL in `db.py`:** breaks the byte-for-byte constraint. `db.py:_create_tables()` (`:78`) owns existing tables; the new table lives in `api/idempotency.py`. Use `db._pool` as an accessor only.
- **`from dashboard import _executor`:** captures a stale `None`; globals are rebound by `init_dashboard()`. Use accessor functions (Pattern 1).
- **Returning `_render_toast_oob(...)` HTML from JSON routes:** couples API to the view (current `close_partial`/`modify_levels` do this — `dashboard.py:1201,1215,1260`). Return structured JSON; the SPA renders sonner toasts in Phase 11.
- **Re-deriving pip distance / re-rounding volume in JS or in each model:** the XAUUSD class of bug (260501-i7u). One formatter module; the SPA submits the exact server-provided numeric value.
- **Deleting `_verify_csrf` or the `HX-Request` check:** legacy HTMX routes still need it until Phase 12. Add a *new* dependency for `/api/v2`; leave the old one alone.
- **Percent-of-current partial close:** the 75%-double-fire bug. Absolute `close_volume` only (D-09).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Request/response validation | Manual `dict.get` + type checks | Pydantic v2 `response_model` / body models | Already installed; gives the contract + auto-coercion + the SPA's TS source-of-truth |
| Session auth | New token scheme | Existing `SessionMiddleware` + `telebot_session` (`dashboard.py:192`) | httpOnly cookie already works; SPA reuses verbatim; no localStorage tokens (locked) |
| Constant-time token compare | `==` on tokens | `secrets.compare_digest` (already `_secrets`, `dashboard.py:239`) | Timing-attack safe; already the project idiom |
| Rate limiting on login | New limiter | `db.get_failed_login_count` + `_client_ip` (`dashboard.py:147,251`) + nginx `limit_req` | D-14: reuse the exact path; two layers already exist |
| Pip-size / price precision | Per-model `:.2f` literals | `api/formatting.py` routing through `risk_calculator.GOLD_PIP_SIZE` | D-08: one place to fix; the XAUUSD bug came from precision logic in multiple sites |
| Timestamp serialization | `str(dt)` / hand-rolled formats | `dt.astimezone(utc).isoformat()` (machine) + a fixed UTC strftime (display) | D-06/D-07: ISO-8601 with offset is unambiguous; absolute display avoids client-clock drift |
| Absolute-volume close | New broker call | `connector.close_position(ticket, volume=close_volume)` (`mt5_connector.py:742`) | Already accepts an absolute `volume` param; no connector change needed |

**Key insight:** Almost nothing in this phase is genuinely new logic. The only net-new behaviours are (1) the double-submit CSRF dependency, (2) the shared formatter module, and (3) the Postgres idempotency guard. Everything else is *re-shaping existing computation*. Treating any read endpoint as "new business logic" is the trap — it duplicates a helper and risks divergence (e.g. the `_last_positions_by_account` stale-while-revalidate cache at `dashboard.py:43,1434` that masks transient REST blips, which the JSON API inherits for free by calling `_get_all_positions()`).

## Common Pitfalls

### Pitfall 1: Idempotency DDL leaking into `db.py` (breaks the hard constraint)
**What goes wrong:** Following the Phase 5 "additive DDL goes in `_create_tables()`" convention pushes the new table into `db.py`, which is on the byte-for-byte-untouched list.
**Why it happens:** Every existing table is created in `db.py:_create_tables()` (`:78-249`); the obvious place *looks* like `db.py`.
**How to avoid:** Create the table in `api/idempotency.py::ensure_table()`, called from the `api/` mount path (not `db.init_db`). Use `db._pool` as a read-only accessor. CONTEXT D-04's "additive-only DDL" is satisfied — it never says the DDL must live in `db.py`.
**Warning signs:** `git diff db.py` is non-empty after the phase. The verification SC explicitly diffs `db.py`.

### Pitfall 2: CSRF `HX-Request` heuristic silently breaks for the SPA
**What goes wrong:** If the new mutation routes inherit `_verify_csrf`, every SPA POST 403s (no `HX-Request` header) — or, worse, if the check is *deleted* to "fix" it, CSRF protection vanishes.
**Why it happens:** `_verify_csrf` (`dashboard.py:128-135`) is HTMX-coupled; it's the path of least resistance to either keep or delete it.
**How to avoid:** New `verify_csrf_token` dependency (Pattern 3) on `/api/v2` mutations; leave `_verify_csrf` on legacy routes. Cookie name `telebot_csrf` ≠ `telebot_login_csrf` (D-13; collision check is SC#3).
**Warning signs:** A mutation works with `HX-Request` set but 403s with a valid `X-CSRF-Token`; or a POST with neither succeeds.

### Pitfall 3: Partial-close percent-of-current double-fire (the 75% trap)
**What goes wrong:** Two 50% partial-closes close 50% then 50%-of-remainder = 75% total. `close_partial` computes `pos.volume * (percent/100)` from *live* volume (`dashboard.py:1251`).
**Why it happens:** Percent is inherently relative to current volume; a replay compounds.
**How to avoid:** Absolute `close_volume` (D-09) + `request_id` dedup (D-10/D-11). A replay of the same absolute amount under the same id is a no-op (cached 200), never a second broker call.
**Warning signs:** Trade history shows two partial closes for one operator action; closed volume ≠ the confirmed amount.

### Pitfall 4: Cookie `path` / `httponly` mismatch
**What goes wrong:** If `telebot_csrf` is set with `path=/login` (copying the legacy login cookie) it won't be sent to `/api/v2`; if set `httponly=True` the SPA's JS can't read it to echo the header.
**Why it happens:** The legacy `CSRF_COOKIE` is `httponly=True, path="/login"` (`dashboard.py:169-176`) — a tempting copy target.
**How to avoid:** `telebot_csrf` must be `httponly=False, path="/"` (D-15). It is NOT a session credential (grants nothing alone), so readable is safe.
**Warning signs:** CSRF always 403 (cookie not sent) or the SPA cannot read the token.

### Pitfall 5: Number/timestamp formatting drifting to the client (XAUUSD precedent)
**What goes wrong:** A price shown at FX precision instead of XAUUSD's 2-dp, or a lot volume re-rounded in JS producing `0.30000000000000004`, or a submitted volume the broker rejects. This project already shipped the XAUUSD pip-size bug (260501-i7u) when precision lived in multiple places.
**Why it happens:** Moving rendering to the SPA invites duplicating Python precision logic in JS.
**How to avoid:** Server-side dual-value (D-05): `value` (machine-precise) + `value_display` (server-formatted string) per price/money/volume/time field, all via `api/formatting.py` (D-08). The SPA renders `*_display` and submits the bare numeric.
**Warning signs:** SPA price/lot differs from the bot log; broker rejects "invalid volume"; pip distance mismatch.

### Pitfall 6: Stale-global capture from `dashboard.py`
**What goes wrong:** `from dashboard import _executor` binds `None` (the import-time value before `init_dashboard()` runs).
**Why it happens:** The globals are rebound, not mutated in place.
**How to avoid:** Accessor functions (Pattern 1).
**Warning signs:** Every `/api/v2` route 503s "Trading not initialized" even when the bot is running.

## Runtime State Inventory

> Phase 8 is **additive/greenfield within the presentation layer** — it adds a new package, new endpoints, and one new table. It is NOT a rename/refactor/migration of existing runtime state. The relevant inventory is therefore "what new runtime state does this phase introduce, and what existing state must it leave untouched."

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | NEW `idempotency_keys` table (created by `api/idempotency.py`, not `db.py`). No existing stored data is renamed or migrated. | Additive DDL via `ensure_table()`; periodic age-out (D-03). |
| Live service config | No external service config embeds new identifiers. nginx `limit_req zone=telebot_login` must be **extended** (additive `location = /api/v2/auth/login`) — config edit, not state. | nginx config addition (D-14) — flagged for Phase 9/deploy; not a Phase-8 code task but document it. |
| OS-registered state | None — verified: no Task Scheduler / systemd / pm2 names change; the bot is one container started by docker-compose. | None. |
| Secrets/env vars | None new. Reuses `SESSION_SECRET`, `DASHBOARD_PASS_HASH`, `SESSION_COOKIE_SECURE`, `DATABASE_URL` (all in `config.py:48-50`). The `telebot_csrf` token is generated at runtime, not stored as a secret. | None. |
| Build artifacts | New `api/` package must be `COPY`'d into the image. The current Dockerfile does `COPY *.py *.json ./` (per ARCHITECTURE.md:377) which copies top-level `.py` but **NOT a subpackage directory**. | Dockerfile must add `COPY api/ ./api/` (additive) — flag for the planner; a missed package = ImportError at boot. |

**Bot-core untouchability (verified mapping):**
- **Bot core (must show empty `git diff`):** `executor.py`, `trade_manager.py`, `db.py`, `mt5_connector.py`, and `mt5-rest-server/` (the MT5 REST bridge).
- **Presentation/serialization layer (where Phase 8 writes):** new `api/` package + minimal additions to `dashboard.py` (accessors + `include_router` + optional idempotency-table bootstrap call). `dashboard.py` is explicitly NOT on the untouched list (it's the file that shrinks to wiring in Phase 12).
- **Confirmed:** `db._pool` is a module global (`db.py:18`) readable from `api/` without editing `db.py`. The connector's `close_position(ticket, volume=...)` already accepts absolute volume (`mt5_connector.py:742`) — no connector edit needed for API-05.

## Code Examples

### Mount the router (the entire `dashboard.py` change, plus accessors)
```python
# dashboard.py — near app creation (after app = FastAPI(...), dashboard.py:188)
from api import api_router            # NEW package
app.include_router(api_router)        # api_router = APIRouter(prefix="/api/v2")

# Bootstrap the idempotency table once (cannot go in db.init_db — that's bot core)
@app.on_event("startup")              # or fold into the existing lifespan (dashboard.py:180)
async def _api_startup():
    from api.idempotency import ensure_table
    await ensure_table()

# Read-only accessors so api/ never imports rebindable globals (Pattern 1)
def get_executor():       return _executor
def get_notifier():       return _notifier
def get_settings():       return _settings
def get_settings_store(): return _get_settings_store()
```
> Note: FastAPI 0.115 still supports `@app.on_event("startup")`; the project already uses the `lifespan` context manager (`dashboard.py:180-185`) — prefer adding the `ensure_table()` call inside `lifespan` to match the existing pattern and avoid the deprecated event hook. `[CITED: dashboard.py:180]`

### Auth login (JSON) — reuses the verbatim argon2 + rate-limit path
```python
# api/auth.py
@router.post("/auth/login")
async def login(body: LoginIn, request: Request):
    cookie = request.cookies.get("telebot_csrf", "")
    if not cookie or not _secrets.compare_digest(cookie, body.csrf_token):
        raise HTTPException(403, "CSRF token invalid")
    ip = _client_ip(request)                                   # dashboard.py:147
    if await db.get_failed_login_count(ip, minutes=15) >= 5:   # D-14, dashboard.py:251
        raise HTTPException(429, "rate_limited")
    try:
        _password_hasher.verify(app_settings.dashboard_pass_hash, body.password)
    except VerifyMismatchError:
        await db.log_failed_login(ip, request.headers.get("user-agent",""))
        raise HTTPException(401, "invalid_credentials")
    request.session["user"] = "admin"                          # dashboard.py:283
    await db.clear_failed_logins(ip)
    resp = JSONResponse({"user": "admin"})
    resp.set_cookie("telebot_csrf", _secrets.token_urlsafe(32),
                    httponly=False, samesite="lax",
                    secure=app_settings.session_cookie_secure, path="/")
    return resp
```

### Idempotent partial-close (the API-05 core)
```python
# api/actions.py
@router.post("/positions/{account}/{ticket}/close-partial")
async def close_partial(account: str, ticket: int, body: PartialCloseIn,
                        user=Depends(require_user), _csrf=Depends(verify_csrf_token)):
    ex = require_executor()
    conn = ex.tm.connectors.get(account) or _abort(404, "account not found")
    pos = next((p for p in await conn.get_positions() if p.ticket == ticket), None)
    if not pos: raise HTTPException(404, "position no longer open")
    cv = round(body.close_volume, 2)                            # symbol lot step
    if not (0 < cv < pos.volume): raise HTTPException(422, "close_volume out of range")
    state, cached = await idempotency.check(body.request_id, account, ticket, cv)
    if state == "replay": return cached                         # D-11: cached 200
    if state == "conflict": raise HTTPException(409, "request_id reused with different params")
    result = await conn.close_position(ticket, volume=cv)       # absolute volume, D-09
    payload = {"ok": result.success, "closed_volume": cv,
               "closed_volume_display": volume_display(cv),
               "error": None if result.success else result.error}
    await idempotency.store(body.request_id, account, ticket, cv, payload)
    return payload
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `@app.on_event("startup")` | `lifespan` async context manager | FastAPI ≥0.93 | Project already uses `lifespan` (`dashboard.py:180`); add `ensure_table()` there, not via the deprecated hook |
| Pydantic v1 `.dict()`/`Config` | Pydantic v2 `.model_dump()`/`model_config` | Pydantic 2.0 | v2.12.5 installed — use v2 idioms; `orm_mode`→`from_attributes`, but here we coerce from dicts so plain `BaseModel` suffices |
| Percent-of-current partial close | Absolute `close_volume` + request-id | This phase (API-05) | Eliminates the 75%-double-fire class |
| `HX-Request` CSRF heuristic | Double-submit `telebot_csrf` + `X-CSRF-Token` | This phase (API-03) | Real protection; SPA-compatible |

**Deprecated/outdated (do not port):**
- `POST /api/modify-sl`, `POST /api/modify-tp` (`dashboard.py:1071-1128`) — explicitly DEPRECATED in-code; superseded by `modify-levels`. The SPA uses the atomic levels endpoint only.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Dockerfile `COPY *.py` does not include the new `api/` subpackage dir, so an explicit `COPY api/ ./api/` is needed | Runtime State Inventory | If wrong-direction (already copied), a redundant COPY is harmless; if missed, ImportError at container boot. Low risk — verifiable by reading the actual Dockerfile during planning. `[ASSUMED — inferred from ARCHITECTURE.md:377 quote; the real Dockerfile was not opened this session]` |
| A2 | `XAUUSD` price displays at 2 decimal places; other symbols default to 5 | formatting.py / Pitfall 5 | A wrong digit count mis-displays prices. XAUUSD-2dp is consistent with `risk_calculator`/`signal_parser` `:.2f` usage, but the symbol→digits map is a design choice the operator should confirm if non-XAUUSD symbols are ever traded. `[ASSUMED]` |
| A3 | Single-operator concurrency means the simple read-first idempotency check is adequate (insert-first recommended but not strictly required) | Pattern 4 | A genuine concurrent double-submit in the read-first window could double-fire. Mitigated by recommending insert-first; planner decides. `[ASSUMED — single-operator usage model from PROJECT.md]` |
| A4 | `app_settings.session_cookie_secure` is the correct flag for the `telebot_csrf` `Secure` attribute (same as session cookie) | Pattern 3 | If a different secure flag is intended, cookie may not be set over HTTP in dev. Reuses the exact flag the session + legacy-CSRF cookies use (`dashboard.py:174,198`). Low risk. `[VERIFIED: dashboard.py:174,198]` |

## Open Questions

1. **Idempotency concurrency model (read-first vs insert-first)**
   - What we know: single operator; D-11 semantics are fixed (replay-200 / conflict-409).
   - What's unclear: whether to pay the tiny cost of insert-first to fully close the check-then-act window.
   - Recommendation: insert-first (`INSERT ... ON CONFLICT DO NOTHING`, branch on rows-affected). Costs one statement, removes the race entirely.

2. **Settings validate/confirm body format: JSON vs form**
   - What we know: `validate_settings_form()` (`dashboard.py:632`) takes a `dict` (currently from `request.form()`).
   - What's unclear: whether the SPA submits JSON (preferred) or `application/x-www-form-urlencoded`.
   - Recommendation: accept a JSON body (a Pydantic model), convert to the dict shape `validate_settings_form` expects. `python-multipart` is present either way.

3. **`docs_url` scoping for `/api/v2`** (Claude's discretion)
   - What we know: app has `docs_url=None` (`dashboard.py:188`).
   - Recommendation: optional; a separate `FastAPI(docs_url=...)` sub-app or a scoped OpenAPI route is low-value for one operator. Defer (matches REQUIREMENTS.md "Future Requirements").

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| FastAPI | All `/api/v2` routes | ✓ | 0.115.0 | — |
| Pydantic v2 | Response/request models | ✓ | 2.12.5 | — |
| asyncpg + Postgres | Idempotency table, all `db.get_*` | ✓ | 0.31.0 / pg16 (dev compose `:5433`) | — |
| argon2-cffi | JSON login verify | ✓ | 25.1.0 | — |
| python-multipart | Form bodies (if used) | ✓ | 0.0.12 | JSON bodies (no multipart needed) |
| Redis | (NOT used — D-01 chose Postgres) | ✗ | — | Postgres `idempotency_keys` (the chosen path) |
| pytest + TestClient + dev Postgres | Contract/CSRF/idempotency tests | ✓ | 8.3.5 | tests `pytest.skip` if Postgres absent (conftest pattern) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** Redis is intentionally absent; Postgres is the locked replacement (D-01).

## Validation Architecture

> nyquist_validation: no explicit `false` found in config context — treat as enabled. The phase goal explicitly demands "curl/pytest-testable", so the validation surface is first-class.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3.5 + pytest-asyncio 0.25.3 (`asyncio_mode = "auto"`, `loop_scope = "session"`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `.venv/bin/python -m pytest tests/test_api_csrf.py tests/test_api_idempotency.py -x` |
| Full suite command | `.venv/bin/python -m pytest -m "not integration"` (and full incl. integration when Postgres up) |
| Test client | `fastapi.testclient.TestClient` with module-scoped app re-import (`tests/test_login_flow.py` pattern) |
| Live DB | dev Postgres at `localhost:5433` (`docker-compose.dev.yml`); conftest `db_pool` fixture skips if absent |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| API-01 | Each read route returns valid Pydantic-modeled JSON (200) with expected keys | contract | `pytest tests/test_api_contract.py -x` | ❌ Wave 0 |
| API-01 | `git diff` shows zero change to `executor.py/trade_manager.py/db.py/mt5_connector.py` + bridge | guard | `git diff --exit-code executor.py trade_manager.py db.py mt5_connector.py mt5-rest-server/` | ❌ Wave 0 (script) |
| API-02 | Each mutation returns a `{success/error}` JSON envelope, never HTML | contract | `pytest tests/test_api_contract.py::test_mutations_return_json -x` | ❌ Wave 0 |
| API-03 | **Regression:** POST to any `/api/v2` mutation WITHOUT valid `X-CSRF-Token` → 403 | regression | `pytest tests/test_api_csrf.py -x` | ❌ Wave 0 (REQUIRED before go-live, D-16) |
| API-03 | Valid `X-CSRF-Token` matching `telebot_csrf` cookie → mutation proceeds; cookie name ≠ `telebot_login_csrf` | regression | `pytest tests/test_api_csrf.py::test_valid_token_passes -x` | ❌ Wave 0 |
| API-04 | XAUUSD position returns `open_price` (raw float) + `open_price_display` ("2800.00", 2dp); timestamp returns ISO-8601+offset + absolute-UTC display | contract | `pytest tests/test_api_formatting.py -x` | ❌ Wave 0 |
| API-05 | Same `request_id` + same params → second submit replays cached 200, broker called once | regression | `pytest tests/test_api_idempotency.py::test_replay -x` | ❌ Wave 0 |
| API-05 | Same `request_id` + different params → 409 | regression | `pytest tests/test_api_idempotency.py::test_conflict -x` | ❌ Wave 0 |
| API-05 | `close_volume` outside `(0, pos.volume)` → 422; absolute (not percent) semantics | contract | `pytest tests/test_api_idempotency.py::test_volume_validation -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/test_api_*.py -x` (the new API suite)
- **Per wave merge:** `.venv/bin/python -m pytest -m "not integration"` + the bot-core `git diff --exit-code` guard
- **Phase gate:** full suite green (incl. the DB-backed idempotency + CSRF regression tests with dev Postgres up) before `/gsd:verify-work`; the CSRF regression (D-16) is a hard gate.

### Wave 0 Gaps
- [ ] `tests/test_api_contract.py` — read-route shapes + mutation-returns-JSON (API-01, API-02). Needs a `TestClient` app fixture that injects a stub/dry-run `_executor` via `init_dashboard()` so `_get_all_positions()` returns deterministic rows without a live MT5 bridge.
- [ ] `tests/test_api_csrf.py` — the mandatory CSRF regression (API-03, D-16).
- [ ] `tests/test_api_idempotency.py` — replay/conflict/validation against dev Postgres (API-05).
- [ ] `tests/test_api_formatting.py` — XAUUSD dual-value + ISO-8601 (API-04).
- [ ] A bot-core diff-guard (a tiny script or a pytest that shells `git diff --exit-code` over the four files + `mt5-rest-server/`).
- [ ] Shared fixture: a `DryRunConnector`-backed executor stub wired through `init_dashboard()` so contract tests don't need a live broker (extend conftest; the `DryRunConnector` already exists, `mt5_connector.py:165`).

## Security Domain

> security_enforcement: not set to `false` in available config → treat as enabled. This phase is squarely a security surface (auth + CSRF + a real-money mutation).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | argon2 verify (reused, `dashboard.py:263`); per-IP rate limit (`db.get_failed_login_count` + nginx `limit_req`) |
| V3 Session Management | yes | Starlette `SessionMiddleware`, httpOnly `telebot_session`, `SameSite=Lax`, `Secure` config-driven — reused unchanged |
| V4 Access Control | yes | `require_user` dependency on every authed route (reuses `_verify_auth` 401 branch, `dashboard.py:112`) |
| V5 Input Validation | yes | Pydantic v2 body models; `close_volume` range check `(0, pos.volume)`; settings hard-caps via `validate_settings_form` |
| V6 Cryptography | yes (token compare) | `secrets.compare_digest` for CSRF; `secrets.token_urlsafe(32)` for token generation — never hand-rolled |
| V13 API Security | yes | Versioned `/api/v2`; double-submit CSRF on state-changing methods; structured error envelope (no stack leakage) |

### Known Threat Patterns for FastAPI JSON API + session cookies

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| CSRF on money mutations | Spoofing/Tampering | Double-submit `telebot_csrf` + `X-CSRF-Token` + `compare_digest` (D-15); `SameSite=Lax` defense-in-depth |
| Replay / double-fire of partial-close | Tampering | `request_id` idempotency in Postgres (D-01); absolute volume (D-09) |
| Credential brute force | Spoofing | argon2 (slow hash) + 5/15min per-IP lockout + nginx `limit_req` on `/api/v2/auth/login` (D-14) |
| XSS token theft | Information Disclosure | Session cookie stays httpOnly; `telebot_csrf` is readable but grants nothing alone (not a session credential) |
| Stack-trace / detail leakage | Information Disclosure | Enveloped error handler returns `{error:{code,message}}`, not raw `detail`/traceback |
| Cross-origin cookie misuse | Spoofing | Same-origin (one nginx host); no CORS; `credentials: same-origin` |

## Sources

### Primary (HIGH confidence — codebase, read this session)
- `dashboard.py` (full read) — `_verify_auth:99`, `_verify_csrf:128`, `CSRF_COOKIE:142`, login `:229-298`, mutations `:1049-1322`, `close_partial:1218`, helpers `_get_all_positions:1401`, `_get_accounts_overview:1457`, `_enrich_stage_for_ui:424`, `validate_settings_form:632`, lifespan `:180`, app `:188`
- `db.py` — `_pool:18`, `init_db:57`, `_create_tables:78-249` (owns all existing DDL), `failed_login` helpers `:979-1004`, read helpers `:477-1199`
- `mt5_connector.py` — `close_position(ticket, volume=...):142/742`, `Position`/`OrderResult` dataclasses `:33-52`
- `trade_manager.py:120` — `_pip_size_for_symbol` (XAUUSD = 0.10); `risk_calculator.py:22-23` — `GOLD_PIP_SIZE`/`GOLD_PIP_VALUE_PER_LOT`
- `docker-compose.yml` / `docker-compose.dev.yml` — confirmed **no Redis** (basis for D-01); dev Postgres `:5433`
- `requirements.txt` + `.venv` import — FastAPI 0.115.0, Pydantic 2.12.5, asyncpg 0.31.0, argon2-cffi 25.1.0, python-multipart 0.0.12
- `nginx/telebot.conf:36` + `limit_req_zones.conf:9` — `zone=telebot_login` (extend for `/api/v2/auth/login`)
- `tests/conftest.py`, `tests/test_login_flow.py`, `tests/test_db_schema.py` — TestClient + dev-Postgres + schema-assert patterns

### Primary (HIGH confidence — prior v1.2 research synthesis)
- `.planning/research/ARCHITECTURE.md` §1 (JSON API design), §2 (SPA auth on session cookies) — the most directly applicable design doc; grounded in this same codebase
- `.planning/research/PITFALLS.md` — Pitfall 2 (CSRF), Pitfall 3 (idempotency, "75% trap"), Pitfall 7 (XAUUSD formatting)
- `.planning/quick/260501-i7u-.../260501-i7u-SUMMARY.md` — the XAUUSD pip-size bug precedent (Pitfall 5 evidence)

### Secondary (MEDIUM confidence)
- `.planning/REQUIREMENTS.md` §API (API-01..05) + Open Questions 1 & 4; `.planning/ROADMAP.md` Phase 8 success criteria; `.planning/STATE.md` Blockers/Concerns (Pitfalls 1-5)

### Tertiary (LOW confidence)
- None — no unverified WebSearch claims were used; this phase is entirely codebase-grounded.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every library verified present in `.venv` / `requirements.txt`; versions confirmed by direct import
- Architecture: HIGH — route inventory, helper reuse, and the idempotency-DDL-placement constraint all traced to exact source lines; corroborated by prior HIGH-confidence ARCHITECTURE.md
- Pitfalls: HIGH — each pitfall maps to a specific current code line and (for Pitfall 5) a shipped bug
- Idempotency design: HIGH (storage locked D-01; Postgres absence verified) / MEDIUM (concurrency model is the one genuine open choice — A3/OQ1)

**Research date:** 2026-06-01
**Valid until:** 2026-07-01 (stable — in-process FastAPI + an established codebase; no fast-moving external deps. Re-verify only if FastAPI/Pydantic are upgraded.)
