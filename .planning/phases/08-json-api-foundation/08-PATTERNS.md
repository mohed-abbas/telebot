# Phase 8: JSON API Foundation - Pattern Map

**Mapped:** 2026-06-01
**Files analyzed:** 20 (16 new `api/` modules + `dashboard.py` mods + 4 new test files)
**Analogs found:** 19 / 20 (one greenfield: `api/idempotency.py` — no existing analog table; uses `failed_login_attempts` as template)

> Every new file lives in a NEW `api/` package or `tests/`. `dashboard.py` gets minimal additive wiring. The four bot-core files (`executor.py`, `trade_manager.py`, `db.py`, `mt5_connector.py`) and `mt5-rest-server/` are **called only, never edited** — `git diff` must show them empty.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `api/__init__.py` | package init / router export | wiring | `dashboard.py:188` app/router creation | role-match |
| `api/router.py` | router assembler | wiring | `dashboard.py` `@app.get/post` layout | role-match |
| `api/deps.py` | dependency / guard | request-response | `_verify_auth` (`dashboard.py:99`), `_verify_csrf` (`dashboard.py:128`) | exact |
| `api/schemas.py` | Pydantic model | transform | `_get_all_positions` dict shape (`dashboard.py:1438`), `Position`/`OrderResult` dataclasses (`mt5_connector.py:33,42`) | role-match |
| `api/formatting.py` | utility (formatter) | transform | `risk_calculator.GOLD_PIP_SIZE` (`risk_calculator.py:23`); inline `:.2f` at `dashboard.py:1097,1211,1264` | partial (consolidates scattered logic) |
| `api/idempotency.py` | DB-accessor (own DDL) | CRUD / dedup | `failed_login_attempts` DDL (`db.py:204-214`) + helpers (`db.py:979-1005`) | role-match (template) |
| `api/errors.py` | exception handler | request-response | HTML error branches in mutations (`dashboard.py:1067,1166`) | partial |
| `api/auth.py` | route module | request-response | `login_submit` (`dashboard.py:229-290`), `logout` (`:293`) | exact |
| `api/accounts.py` | route module | request-response (read) | `_get_accounts_overview` (`dashboard.py:1457`) | exact |
| `api/positions.py` | route module | request-response (read) | `_get_all_positions` (`dashboard.py:1401`) | exact |
| `api/history.py` | route module | request-response (read) | `db.get_filtered_trades` / `db.get_trade_filter_options` callers | exact |
| `api/signals.py` | route module | request-response (read) | `db.get_recent_signals(100)` callers | exact |
| `api/stages.py` | route module | request-response (read) | `_enrich_stage_for_ui` (`dashboard.py:424`) + `db.get_pending_stages` | exact |
| `api/analytics.py` | route module | request-response (read) | `db.get_analytics_with_filters` callers | exact |
| `api/settings.py` | route module | request-response (CRUD) | `settings_validate/confirm/revert` (`dashboard.py:744,812,873`) | exact |
| `api/actions.py` | route module | request-response (mutate) | `close_position`/`modify_levels`/`close_partial` (`dashboard.py:1049,1141,1218`) | exact |
| `api/meta.py` | route module | request-response (read) | overview composition (`dashboard.py:311-332`, `trading_status:1325`) | role-match |
| `dashboard.py` (MOD) | wiring + accessors | — | `init_dashboard` (`dashboard.py:91`), lifespan (`:180`) | self |
| `tests/test_api_contract.py` | test | — | `tests/test_login_flow.py` (TestClient + app re-import) | exact |
| `tests/test_api_csrf.py` | test | — | `tests/test_login_flow.py` CSRF round-trip | exact |
| `tests/test_api_idempotency.py` | test | — | `tests/test_login_flow.py` + `conftest.py` `db_pool` | exact |
| `tests/test_api_formatting.py` | test | — | `tests/test_login_flow.py` | exact |

---

## Pattern Assignments

### `api/deps.py` (dependency / guard, request-response)

**Analogs:** `_verify_auth` (`dashboard.py:99-125`), `_verify_csrf` (`dashboard.py:128-135`), `_client_ip` (`dashboard.py:147-152`).

**`require_user` — reuse the existing 401 branch verbatim.** `_verify_auth` already 401s on any `/api/`-prefixed path (so `/api/v2` inherits it):
```python
# dashboard.py:108-116  — the branch /api/v2 hits
user = request.session.get("user")
if user:
    return user
if request.headers.get("hx-request") or request.url.path.startswith("/api/"):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
```
The api dependency may simply re-export / delegate to `_verify_auth` via an accessor, OR replicate the session-read + 401 (no redirect branch needed since `/api/v2` never redirects).

**`verify_csrf_token` — NEW double-submit dep, modeled on the legacy compare-digest idiom (NOT the `HX-Request` heuristic).** Replace, do not delete — the legacy `_verify_csrf` stays for HTMX routes. The constant-time compare idiom to copy is from `login_submit`:
```python
# dashboard.py:238-239  — the exact project compare idiom
cookie_token = request.cookies.get(CSRF_COOKIE, "")
if not cookie_token or not _secrets.compare_digest(cookie_token, csrf_token):
```
New dep shape (cookie vs `X-CSRF-Token` header, guard only state-changing methods):
```python
import secrets as _secrets
async def verify_csrf_token(request: Request):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        cookie = request.cookies.get("telebot_csrf", "")
        header = request.headers.get("x-csrf-token", "")
        if not cookie or not _secrets.compare_digest(cookie, header):
            raise HTTPException(403, "CSRF token invalid")
```
> D-13 collision guard: the cookie name MUST be `telebot_csrf`, not `telebot_login_csrf` (`dashboard.py:142`).

**`_client_ip` for rate-limit — reuse verbatim** (`dashboard.py:147-152`): prefers `X-Real-IP`, falls back to `request.client.host`.

**Accessor deps (Pattern 1 — avoid stale-global capture).** `init_dashboard()` rebinds module globals (`dashboard.py:91-96`), so `from dashboard import _executor` captures a stale `None`. Use accessor functions added to `dashboard.py` and a 503 guard mirroring `dashboard.py:1052-1053`:
```python
if not _executor:
    raise HTTPException(status_code=503, detail="Trading not initialized")
```

---

### `api/auth.py` (route module, request-response)

**Analog:** `login_submit` (`dashboard.py:229-290`), `logout` (`dashboard.py:293-298`).

**Login pipeline — port the four steps verbatim, change only the response shape (JSON not HTML):**
```python
# dashboard.py:237-290  — order is load-bearing: CSRF → rate-limit (before argon2 CPU) → verify → session
# 1. double-submit CSRF (secrets.compare_digest)
# 2. ip = _client_ip(request); fail_count = await db.get_failed_login_count(ip, minutes=15); if >= 5 -> 429
# 3. _password_hasher.verify(app_settings.dashboard_pass_hash, password)  (except VerifyMismatchError)
#    on failure: await db.log_failed_login(ip, user_agent=ua)
# 4. success: request.session["user"] = "admin"; await db.clear_failed_logins(ip)
```
Reuse the module-level `_password_hasher` (`dashboard.py:144`) and `app_settings` (`dashboard.py:28`) via accessors — do not re-instantiate `PasswordHasher()`.

**Set the `telebot_csrf` cookie on login success** (Pitfall 4 — `httponly=False`, `path="/"`, contrast the legacy login cookie at `dashboard.py:169-176` which is `httponly=True, path="/login"`):
```python
resp.set_cookie("telebot_csrf", _secrets.token_urlsafe(32),
                httponly=False, samesite="lax",
                secure=app_settings.session_cookie_secure, path="/")
```
**`logout`** ports `request.session.clear()` (`dashboard.py:297`) → returns `{"ok": true}` JSON.
**`/auth/me`** reads `request.session.get("user")` → `{user}` or 401. **`/auth/csrf`** issues/refreshes the cookie (same `set_cookie` as login).

---

### `api/positions.py` + `api/accounts.py` + read routes (route module, request-response read)

**Analogs:** `_get_all_positions` (`dashboard.py:1401-1454`), `_get_accounts_overview` (`dashboard.py:1457-1510`).

**Pattern 2 — wrap the existing dict output verbatim in a `response_model`; add only `_display` twins.** The helper already returns the exact dict the SPA needs (note: stale-while-revalidate cache is inherited for free):
```python
# dashboard.py:1438-1449  — the dict shape api/schemas.py mirrors
{
    "account": acct_name, "ticket": pos.ticket, "symbol": pos.symbol,
    "direction": pos.direction, "volume": pos.volume,
    "open_price": pos.open_price, "sl": pos.sl, "tp": pos.tp, "profit": pos.profit,
}
```
Route shape (call unchanged, map to model adding `_display` fields via `api/formatting.py`):
```python
from dashboard import _get_all_positions  # or via accessor
@router.get("/positions", response_model=list[Position])
async def positions(user: str = Depends(require_user)):
    rows = await _get_all_positions()
    return [_to_position_model(r) for r in rows]
```
The accounts dict shape to mirror is at `dashboard.py:1493-1508` (balance/equity/margin/profit → money `_display`).

---

### `api/schemas.py` (Pydantic model, transform)

**Analogs:** the read-helper dict shapes above + `Position`/`OrderResult` dataclasses (`mt5_connector.py:33-52`):
```python
# mt5_connector.py:33-40
@dataclass
class OrderResult:
    success: bool; ticket: int = 0; price: float = 0.0; volume: float = 0.0; error: str = ""
# mt5_connector.py:42-52
@dataclass
class Position:
    ticket: int; symbol: str; direction: str; volume: float
    open_price: float; sl: float; tp: float; profit: float; comment: str = ""
```
**D-05 dual-value: parallel suffixed fields, not nested objects.** Only price/money/volume/timestamp fields get a `_display` twin (Pydantic v2 `BaseModel`, plain — dicts coerce, no `from_attributes` needed):
```python
class Position(BaseModel):
    account: str; ticket: int; symbol: str; direction: str
    volume: float; volume_display: str
    open_price: float; open_price_display: str
    sl: float | None; tp: float | None
    profit: float; profit_display: str
```

---

### `api/formatting.py` (utility / formatter, transform)

**Analog / source-of-truth:** `risk_calculator.GOLD_PIP_SIZE = 0.10` (`risk_calculator.py:23`). The scattered inline `:.2f` literals this module consolidates: `dashboard.py:1097` (`SL updated to {new_sl:.2f}`), `:1211` (`SL → {sl_to_send:.2f}`), `:1264` (`Closed {close_vol:.2f} lots`). D-08: one module so the XAUUSD pip-size class of bug (quick task 260501-i7u) can't recur.

**D-05/D-06/D-07 — money/volume/price + ISO-8601 machine + absolute-UTC display:**
```python
from datetime import timezone
from risk_calculator import GOLD_PIP_SIZE  # 0.10 — single source
_SYMBOL_DIGITS = {"XAUUSD": 2}             # price digits per symbol; extend here, never inline
def price_display(symbol, value):  return f"{value:.{_SYMBOL_DIGITS.get(symbol.upper(), 5)}f}"
def money_display(value):          return f"{value:,.2f}"
def volume_display(value):         return f"{value:.2f}"          # matches close_vol round(.,2)
def ts_machine(dt):                return dt.astimezone(timezone.utc).isoformat()        # D-06
def ts_display(dt):                return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")  # D-07
```
> `2dp` for volume matches the existing `round(pos.volume * (percent/100), 2)` at `dashboard.py:1251`. The existing UTC-today idiom `db.py:49-51` confirms the project reasons in UTC.

---

### `api/idempotency.py` (DB-accessor, CRUD / dedup)  — GREENFIELD, template-only

**No existing analog table.** Template: the `failed_login_attempts` lifecycle (DDL + age-out helpers).

**CRITICAL (Pitfall 1):** the DDL must NOT go in `db.py` — `db.py:_create_tables()` (`:78`) owns all existing tables and `db.py` is byte-for-byte untouched. Create the table in `api/idempotency.py::ensure_table()`, call it from the `dashboard.py` `lifespan` (`:180`), and use `db._pool` (`db.py:18`) as a **read-only accessor**.

**DDL template** — copy the `CREATE TABLE IF NOT EXISTS` + companion `CREATE INDEX IF NOT EXISTS` shape from `failed_login_attempts`:
```python
# db.py:204-214  — the additive-DDL house style to replicate inside api/idempotency.py
CREATE TABLE IF NOT EXISTS failed_login_attempts (
    id SERIAL PRIMARY KEY, ip_addr TEXT NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_agent TEXT NOT NULL DEFAULT '' )
CREATE INDEX IF NOT EXISTS idx_failed_login_ip_ts ON failed_login_attempts(ip_addr, attempted_at)
```
New table (D-02: `request_id` sole PK; store `account`/`ticket`/`close_volume`/`result` for D-11 conflict detection):
```python
import db, json
async def ensure_table():
    async with db._pool.acquire() as conn:
        await conn.execute("""CREATE TABLE IF NOT EXISTS idempotency_keys (
            request_id TEXT PRIMARY KEY, account TEXT NOT NULL, ticket BIGINT NOT NULL,
            close_volume DOUBLE PRECISION NOT NULL, result JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        await conn.execute("""CREATE INDEX IF NOT EXISTS idx_idempotency_created
            ON idempotency_keys(created_at)""")
```
**Age-out (D-03)** mirrors `get_failed_login_count`'s `make_interval` idiom (`db.py:985`):
```python
# template: db.py:983-986 uses  NOW() - make_interval(mins => $2)
DELETE FROM idempotency_keys WHERE created_at < NOW() - make_interval(hours => $1)
```
**check/store helpers** follow the `async with db._pool.acquire() as conn:` + `fetchrow`/`execute` shape used throughout `db.py:979-1005`. D-11 mapping: `new`→execute+store, `replay`→cached 200, `conflict`→409. Recommend insert-first (`INSERT ... ON CONFLICT DO NOTHING`, branch on rows-affected) to close the check-then-act race (OQ1).

---

### `api/actions.py` (route module, request-response mutate)

**Analogs:** `close_position` (`dashboard.py:1049-1068`), `modify_levels` (`dashboard.py:1141-1215`), `close_partial` (`dashboard.py:1218-1266`), `emergency_close_endpoint` (`:1301`), `resume_trading` (`:1313`), `trading_status` (`:1325`).

**Port the broker/DB CALLS verbatim; change only the response shape (JSON envelope, never `_render_toast_oob` HTML).**

Full close — connector lookup + call + DB write (`dashboard.py:1055-1066`):
```python
connector = _executor.tm.connectors.get(account_name)         # dashboard.py:1055
if not connector: raise HTTPException(404, ...)               # dashboard.py:1057
result = await connector.close_position(ticket)               # dashboard.py:1059
if result.success:
    await db.update_trade_close(ticket, account_name, 0.0, result.price)  # dashboard.py:1061
```
Modify-levels — the position lookup + `_changed` diff + atomic `modify_position(ticket, sl=, tp=)` (`dashboard.py:1159-1203`) ports unchanged; only the toast/modal HTML at `:1201,1205,1215` becomes JSON.

**Partial-close — the API-05 rewrite.** The current handler computes percent-of-live-volume (the 75%-double-fire bug):
```python
# dashboard.py:1251  — REPLACE this percent math
close_vol = round(pos.volume * (percent / 100), 2)
```
New contract (D-09 absolute volume + D-10/D-11 idempotency). The connector already accepts absolute volume — no connector edit:
```python
# mt5_connector.py:742  — already absolute
async def close_position(self, ticket: int, volume: float | None = None) -> OrderResult:
```
New handler skeleton:
```python
cv = round(body.close_volume, 2)                              # lot step
if not (0 < cv < pos.volume): raise HTTPException(422, "close_volume out of range")
state, cached = await idempotency.check(body.request_id, account, ticket, cv)
if state == "replay":   return cached                         # D-11 cached 200, broker untouched
if state == "conflict": raise HTTPException(409, "request_id reused with different params")
result = await conn.close_position(ticket, volume=cv)         # D-09 absolute
payload = {"ok": result.success, "closed_volume": cv,
           "closed_volume_display": volume_display(cv), "error": ... }
await idempotency.store(body.request_id, account, ticket, cv, payload)
return payload
```
**Emergency/resume** already return plain dicts (`dashboard.py:1310` returns `results`; `:1322` returns `{"status": "resumed"}`) — these are the closest-to-done; just model the `results` dict.

> Do NOT port the DEPRECATED `modify-sl`/`modify-tp` (`dashboard.py:1071-1128`) — superseded by `modify-levels`.

---

### `api/settings.py` (route module, CRUD)

**Analogs:** `settings_validate` (`dashboard.py:744`), `settings_confirm` (`:812`), `settings_revert` (`:873`), `validate_settings_form` (`:632`), `_get_settings_store` (`:686`).

**Port the validation core; swap form-dict → Pydantic body.** Current reads `form = dict(await request.form())` then calls `validate_settings_form(form, max_lot_size=...)` (`dashboard.py:759-760`). OQ2 recommendation: accept a JSON body, convert to the same dict shape `validate_settings_form` expects. Reuse the 503/404 guards verbatim:
```python
# dashboard.py:749-755
store = _get_settings_store()
if store is None: raise HTTPException(503, "SettingsStore not initialised")
try:    current = store.effective(account_name)
except KeyError: raise HTTPException(404, f"Unknown account: {account_name}")
```
Return `{valid, errors, diff, dry_run_text}` as JSON instead of the modal/422 partial.

---

### `dashboard.py` (MODIFIED — wiring + accessors only)

**Analogs:** `init_dashboard` globals (`dashboard.py:91-96`), `lifespan` (`:180-185`), app creation (`:188`).

**Three additive changes only** (the file is NOT on the untouched list):
```python
# 1. mount the router (near app = FastAPI(...), dashboard.py:188)
from api import api_router
app.include_router(api_router)            # APIRouter(prefix="/api/v2")

# 2. bootstrap idempotency table inside the EXISTING lifespan (dashboard.py:180) — NOT db.init_db
async def lifespan(app):
    from api.idempotency import ensure_table
    await ensure_table()
    yield

# 3. read-only accessors so api/ never imports rebindable globals (Pattern 1)
def get_executor():       return _executor
def get_notifier():       return _notifier
def get_settings():       return _settings
def get_settings_store(): return _get_settings_store()    # already exists at :686
```

---

### `tests/test_api_*.py` (test)

**Analog:** `tests/test_login_flow.py` (full) + `tests/conftest.py`.

**App fixture — module-scoped env-injection + `sys.modules.pop` + `importlib.import_module` re-import, then `db.init_db` with `pytest.skip` on absence** (`test_login_flow.py:21-51`):
```python
@pytest.fixture(scope="module")
def app(known_hash):
    env = {..., "DATABASE_URL": os.environ.get("TEST_DATABASE_URL",
            "postgresql://telebot:telebot_dev@localhost:5433/telebot"),
           "DASHBOARD_PASS_HASH": known_hash, "SESSION_SECRET": "A"*48,
           "SESSION_COOKIE_SECURE": "false"}
    os.environ.update(env)
    for mod in ("config", "dashboard", "db"): sys.modules.pop(mod, None)
    dashboard = importlib.import_module("dashboard")
    ... asyncio...run_until_complete(db.init_db(env["DATABASE_URL"]))  # pytest.skip on Exception
    yield dashboard.app
```
**TestClient cookie/header round-trip** (`test_login_flow.py:64-88`): `c = TestClient(app)`, assert cookie names, drive POSTs. The CSRF regression test (D-16): GET `/api/v2/auth/csrf` to obtain the `telebot_csrf` cookie, then POST a mutation echoing it as `X-CSRF-Token` (200) vs omitting it (403).
**DryRunConnector stub via `init_dashboard()`:** wire a `DryRunConnector` (`mt5_connector.py:165`, already imported in `conftest.py:13`) so `_get_all_positions()` returns deterministic rows without a live MT5 bridge — extend `conftest.py`.
**DB-backed idempotency tests** use the session-scoped `db_pool` fixture + `clean_tables` autouse (`conftest.py:34-66`) — note `clean_tables` TRUNCATE list must be extended to include `idempotency_keys`.

---

## Shared Patterns

### Authentication (401 guard)
**Source:** `_verify_auth` (`dashboard.py:99-125`) — already 401s on `/api/`-prefix.
**Apply to:** every `/api/v2` route via `require_user` dep.
```python
user = request.session.get("user")
if not user and request.url.path.startswith("/api/"):
    raise HTTPException(401, "Session expired")
```

### CSRF (double-submit)
**Source:** compare idiom `dashboard.py:238-239`; cookie name guard `dashboard.py:142`.
**Apply to:** every `/api/v2` POST/PUT/PATCH/DELETE via `verify_csrf_token` dep. `_secrets.compare_digest(cookie, header)`; cookie `telebot_csrf` (NOT `telebot_login_csrf`), `httponly=False`, `path="/"`.

### Connector / executor access (503 guard + no stale globals)
**Source:** 503 guard `dashboard.py:1052-1053`; connector lookup `dashboard.py:1055-1057`; accessor rationale `dashboard.py:91-96`.
**Apply to:** every route that touches `_executor`.
```python
ex = get_executor()                       # accessor, not `from dashboard import _executor`
if ex is None: raise HTTPException(503, "Trading not initialized")
connector = ex.tm.connectors.get(account_name)
if not connector: raise HTTPException(404, f"Account {account_name} not found")
```

### DB access (pool accessor)
**Source:** `async with db._pool.acquire() as conn:` + `make_interval` idiom (`db.py:979-1005`).
**Apply to:** `api/idempotency.py`. `db._pool` is a read-only accessor; never edit `db.py`.

### Rate-limit reuse (login)
**Source:** `_client_ip` (`dashboard.py:147`) + `db.get_failed_login_count(ip, 15) >= 5` (`dashboard.py:251`) + `db.log_failed_login` / `db.clear_failed_logins`.
**Apply to:** `api/auth.py` login → JSON 429. (D-14: nginx `limit_req zone=telebot_login` extension is a deploy note, not a code task.)

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `api/idempotency.py` | DB-accessor | CRUD/dedup | No existing idempotency/dedup table. Uses `failed_login_attempts` (`db.py:204-214,979-1005`) DDL+helper shape as the template; the `request_id`-PK + JSONB-result design is net-new. |

> `api/errors.py` (enveloped-error handler) has only a partial analog (the inline HTML error branches at `dashboard.py:1067,1166`); the planner should use the RESEARCH.md error-envelope recommendation (`{error:{code,message,fields?}}` on failure, bare resource on success).

---

## Metadata

**Analog search scope:** `dashboard.py` (auth/CSRF/mutations/read-helpers), `db.py` (DDL + failed-login helpers + pool), `mt5_connector.py` (close_position + dataclasses), `risk_calculator.py` (pip-size), `tests/test_login_flow.py` + `tests/conftest.py` (test harness).
**Files scanned:** 7 source + 2 test files (targeted reads; line ranges cited inline).
**Pattern extraction date:** 2026-06-01
