# Architecture Research — v1.2 React/Vite SPA ↔ FastAPI Integration

**Domain:** Single-operator live-trading control dashboard; SPA front-end over an existing in-process FastAPI app
**Researched:** 2026-06-01
**Confidence:** HIGH (grounded in the actual codebase; transport/auth patterns verified against TanStack Query + FastAPI docs)

---

## TL;DR Recommendations

1. **JSON API:** Mount a new `APIRouter` at `/api/v2`, kept in a new `api/` package separate from `dashboard.py`. Reuse the existing `_get_all_positions()` / `_get_accounts_overview()` / `db.*` helpers verbatim — wrap their dict output in Pydantic v2 response models. **Zero imports change in `executor.py` / `trade_manager.py` / `db.py` / `mt5_connector.py`.**
2. **Auth:** Keep the `telebot_session` httpOnly cookie. Login becomes `POST /api/v2/auth/login` returning JSON + `Set-Cookie`. SPA detects auth failure via a **global TanStack Query `QueryCache.onError` 401 handler → redirect to login**. CSRF stays double-submit but the cookie becomes **readable (`httponly=false`) so the SPA can echo it in an `X-CSRF-Token` header**.
3. **Same-origin nginx:** `/api/` → uvicorn (JSON). `/app/` → SPA static bundle with `try_files … /app/index.html` fallback. `/` and legacy page paths (`/overview`, `/positions`, …) → uvicorn (legacy HTMX) **until each is decommissioned**. No CORS, no second origin.
4. **Live data:** **Keep polling via TanStack Query `refetchInterval: 3000`.** Do not introduce WebSocket. SSE is optional and low-value for one operator; polling is simpler, survives reconnects for free, and the 3s cadence already matches the current UX. (See rationale.)
5. **Build/deploy:** Add a **Node build stage** to the existing multi-stage Dockerfile that runs `vite build` and emits to `/app/static/app/`. Serve that directory. Cut over **page-by-page** by flipping the operator's entry/nav per page from HTMX → SPA. Analytics first (read-only pilot).

---

## Current System (grounded)

```
                          ┌────────────── shared-nginx (proxy-net) ──────────────┐
   Browser ──HTTPS──▶     │  location = /login   (rate-limited) ─┐                │
                          │  location /          ────────────────┴─▶ telebot:8080 │
                          └───────────────────────────────────────────────────────┘
                                                                       │
                                            ┌──────────────────────────┴───────────────┐
                                            │  bot.py (asyncio main)                     │
                                            │  └─ uvicorn.Server(dashboard.app)  ◀── SAME PROCESS
                                            │       ├─ ~31 routes, mostly HTMLResponse    │
                                            │       ├─ SessionMiddleware (telebot_session)│
                                            │       ├─ Jinja2 templates/ + static/css     │
                                            │       └─ imports executor, db, notifier ────┼──▶ TRADING CORE
                                            └────────────────────────────────────────────┘     (executor.py,
                                                          │                                      trade_manager.py,
                                                          ▼                                      mt5_connector.py)
                                            PostgreSQL (asyncpg, data-net)
                                            MT5 REST bridge (separate FastAPI svc) — UNAFFECTED
```

**Critical facts the design must respect (from `dashboard.py`):**

| Fact | Source | Implication |
|------|--------|-------------|
| Dashboard runs **in the same process** as the bot; `init_dashboard()` injects live `_executor`/`_notifier`/`_settings` | `dashboard.py:91`, `bot.py:409-420` | JSON routes can call the SAME live objects — no IPC, no second service. |
| Auth = `request.session["user"]` via Starlette `SessionMiddleware`, cookie `telebot_session`, 30-day, `same_site=lax`, `https_only` config-driven | `dashboard.py:192-200`, `283` | SPA reuses this cookie verbatim. No token store needed. |
| `_verify_auth` already branches: `/api/`-prefixed or `hx-request` → **401**; page routes → **303 redirect** | `dashboard.py:99-125` | The 401 branch is exactly what the SPA needs — reuse it. |
| CSRF today = "POST must carry `HX-Request` header" (`_verify_csrf`) + login double-submit cookie `telebot_login_csrf` | `dashboard.py:128-135`, `142`, `237-245` | SPA can't send `HX-Request`; needs a real double-submit token instead. |
| Computation already lives in helpers returning **plain dicts** (`_get_all_positions`, `_get_accounts_overview`, `_enrich_stage_for_ui`, all `db.get_*`) | `dashboard.py:1401-1510` etc. | JSON layer is a **serialization refactor**, not a logic rewrite. |
| Mutations call `connector.close_position` / `modify_position` and `db.update_trade_close` directly | `dashboard.py:1049-1266` | These move into JSON routes **unchanged**; only the response shape (HTML→JSON) changes. |
| SSE `/stream` exists (2s tick, emits pre-rendered HTML + JSON) | `dashboard.py:1339-1393` | The HTML-partial half dies with HTMX. JSON half could be repurposed, but polling is recommended instead. |

---

## Target System Overview

```
                ┌───────────────────── shared-nginx (proxy-net) ─────────────────────┐
                │  location /api/        ─────────────────────────▶ telebot:8080      │  JSON API (/api/v2)
                │  location = /login     (rate-limit) ────────────▶ telebot:8080      │  legacy login (until cut)
   Browser ─────│  location /app/        ─▶ try_files $uri /app/index.html (STATIC)   │  React SPA bundle
                │  location /            ─────────────────────────▶ telebot:8080      │  legacy HTMX (shrinking)
                │  location = /stream    ─────────────────────────▶ telebot:8080      │  legacy SSE (until cut)
                └────────────────────────────────────────────────────────────────────┘
                                                          │
                       ┌──────────────────────────────────┴──────────────────────────┐
                       │ dashboard.app (FastAPI, same process as bot)                  │
                       │   ├─ SessionMiddleware (telebot_session)  ◀── shared by both  │
                       │   ├─ app.include_router(api_v2_router)   prefix="/api/v2" NEW │
                       │   │     ├─ auth.py     (login/logout/me, JSON + Set-Cookie)   │
                       │   │     ├─ positions.py, accounts.py, history.py, signals.py, │
                       │   │     │   stages.py, settings.py, analytics.py, actions.py   │
                       │   │     └─ deps.py     (require_user, verify_csrf_token)        │
                       │   └─ legacy HTMX routes (untouched, removed page-by-page)      │
                       └───────────────────────────────────────────────────────────────┘
                                                          │  (same live objects, unchanged calls)
                                                          ▼
                                       executor / trade_manager / db / mt5_connector  — UNTOUCHED
```

The SPA static bundle is served directly from a directory baked into the image (`/app/static/app/`), so there is **no Node runtime in production** (satisfies the locked "Vite SPA over Next.js / minimize dependencies" decision).

---

## 1. JSON API Design

### Mount strategy — `/api/v2`, new package, bot core untouched

Create an `api/` package and attach it to the existing app with **one line** in `dashboard.py`:

```python
# dashboard.py (near app creation)
from api import api_router          # NEW package
app.include_router(api_router)      # api_router = APIRouter(prefix="/api/v2")
```

- **Why `/api/v2`:** the legacy mutation routes already live under `/api/` (`/api/close/...`, `/api/emergency-close`, …). Versioning at `/api/v2` avoids collision and signals "JSON contract" vs the legacy `/api/*` HTML responses. The legacy `/api/*` routes stay until their pages are cut over, then get deleted.
- **Why a new package, not in `dashboard.py`:** `dashboard.py` is 1,510 lines mixing Jinja, OOB-toast HTML builders, and logic. The JSON layer should be clean. Keep `dashboard.py` as the legacy file that shrinks to nothing as cutover completes.
- **Bot-core safety:** every JSON route imports only `db`, the injected `_executor`/`_settings` accessors, and the existing helper functions. **No new import lands in `executor.py`, `trade_manager.py`, `mt5_connector.py`, `db.py`.** The dangerous code is only ever *called*, never *modified*.

`init_dashboard()` stashes the live objects as module globals. Expose them to the `api/` package via accessor functions (not `from dashboard import _executor`, which is fragile because the globals are rebound):

```python
# dashboard.py — add accessors so api/ never imports rebindable globals
def get_executor():       return _executor
def get_settings():       return _settings
def get_notifier():       return _notifier
def get_settings_store(): return _get_settings_store()
```

### Resource grouping (one router module per resource)

| Router module | Routes (GET unless noted) | Backed by (existing) |
|---------------|---------------------------|----------------------|
| `auth.py` | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `GET /auth/csrf` | `db.get_failed_login_count`, argon2, session |
| `accounts.py` | `/accounts` (overview cards) | `_get_accounts_overview()` |
| `positions.py` | `/positions`, `/positions/{account}/{ticket}` (drilldown) | `_get_all_positions()`, `db.get_position_drilldown` |
| `history.py` | `/history` (+ filter query params), `/history/filter-options` | `db.get_filtered_trades`, `db.get_trade_filter_options` |
| `signals.py` | `/signals` | `db.get_recent_signals` |
| `stages.py` | `/stages` (active + resolved) | `db.get_pending_stages`, `db.get_recently_resolved_stages`, `_enrich_stage_for_ui` |
| `settings.py` | `/settings`, `POST /settings/{account}/validate`, `POST /settings/{account}` (confirm), `POST /settings/{account}/revert` | `SettingsStore`, `validate_settings_form`, `db.get_settings_audit` |
| `analytics.py` | `/analytics` (+ range/source query) | `db.get_analytics_with_filters`, `db.get_analytics_sources` |
| `actions.py` | `POST /positions/{account}/{ticket}/close`, `.../levels` (modify SL/TP), `.../close-partial`, `GET /emergency/preview`, `POST /emergency/close`, `POST /emergency/resume`, `GET /trading-status` | `connector.*`, `_executor.emergency_close`, `db.update_trade_close` |
| `meta.py` | `/overview` aggregate (accounts + positions + top-5 stages + flags) for the overview page's single fetch | composes the above helpers |

**Settings two-step flow:** today it returns HTML modal fragments (`settings_confirm_modal.html`). In the SPA this becomes pure data: `POST .../validate` returns `{ valid, errors[], diff[], dry_run_text }`; the React modal renders that JSON; `POST .../{account}` (confirm) persists. The server-side hard-cap validator `validate_settings_form()` is reused **verbatim** — it already returns `(parsed, errors)` not HTML.

### Pydantic v2 response models

Put models in `api/schemas.py`. Wrap the existing dict-returning helpers — do not re-query.

```python
# api/schemas.py
from pydantic import BaseModel

class Position(BaseModel):
    account: str
    ticket: int
    symbol: str
    direction: str
    volume: float
    open_price: float
    sl: float | None
    tp: float | None
    profit: float

class AccountOverview(BaseModel):
    name: str
    connected: bool
    enabled: bool
    balance: float
    equity: float
    open_trades: int
    total_profit: float
    daily_trades: int
    max_daily_trades: int
    daily_limit_pct: float
    # … mirror the dict keys produced in _get_accounts_overview()

class OverviewResponse(BaseModel):
    accounts: list[AccountOverview]
    positions: list[Position]
    pending_stages: list[Stage]
    trading_enabled: bool
    dry_run: bool
    trading_paused: bool
```

Routes declare `response_model=` so FastAPI validates + documents (re-enable `docs_url` scoped for `/api/v2` if useful internally):

```python
@router.get("/positions", response_model=list[Position])
async def positions(user: str = Depends(require_user)):
    return await _get_all_positions()   # dict list coerces into Position[]
```

### Error envelope

FastAPI's default error shape is `{"detail": ...}`. **Standardize** so the SPA has one parse path. Add an app-level exception handler that wraps `HTTPException` and validation errors:

```python
# api/errors.py
# 2xx success → bare resource
# 4xx/5xx     → { "error": { "code": str, "message": str, "fields"?: {field: msg} } }
```

Recommendation: **bare resources on success, enveloped errors on failure.** This keeps `response_model` clean (no `{data: …}` wrapper noise) while giving the SPA a single `if (res.error)` branch. The settings validator's per-field errors map naturally to `error.fields`.

Action endpoints that can partially fail (emergency close across N accounts) return a structured result, not a toast string — e.g. `{ closed: [...], failed: [{account, ticket, error}] }`. Today `emergency_close_endpoint` already returns the raw `results` dict (`dashboard.py:1307`); just model it.

---

## 2. Auth for an SPA on Session Cookies

**Keep everything that works; change only the response shape and the CSRF mechanism.**

### Login flow (JSON)

```
POST /api/v2/auth/login
  body: { "password": "...", "csrf_token": "<echo of telebot_csrf cookie>" }
  ── argon2 verify (reuse dashboard.py:262-280) ──▶ on success:
     request.session["user"] = "admin"      # same as dashboard.py:283
     Set-Cookie: telebot_session=...  (httpOnly, SameSite=Lax, Secure)   # SessionMiddleware
  ◀── 200 { "user": "admin" }
      401 { "error": { "code": "invalid_credentials", ... } }
      429 { "error": { "code": "rate_limited", ... } }   # reuse db.get_failed_login_count
```

The existing rate-limit (`db.get_failed_login_count(ip, 15) ≥ 5 → 429`) and `_client_ip()` logic port over unchanged. The nginx `limit_req zone=telebot_login` block must also cover `/api/v2/auth/login`.

### How the SPA detects unauthenticated state

- **App boot:** SPA calls `GET /api/v2/auth/me`. `200 {user}` → render app; `401` → redirect to login view.
- **Mid-session expiry:** any query/mutation returning 401 triggers a **global TanStack Query handler** that redirects. Verified pattern:

```ts
// queryClient.ts — verified against TanStack Query QueryCache docs
const onAuthError = (error: unknown) => {
  if (error instanceof HttpError && error.status === 401) {
    window.location.assign("/app/login");   // hard nav clears in-memory state
  }
};
export const queryClient = new QueryClient({
  queryCache:    new QueryCache({    onError: onAuthError }),
  mutationCache: new MutationCache({ onError: onAuthError }),
});
```

The fetch wrapper throws `HttpError(status)` on non-2xx so both caches see it. This reuses `_verify_auth`'s existing `/api/`→401 branch (`dashboard.py:112`) — **no server change needed**, since `/api/v2` is `/api/`-prefixed and already hits the 401 path.

### Keeping the cookie httpOnly + SameSite

- `telebot_session` stays **`httpOnly`** (JS never reads it — defeats XSS token theft). `SameSite=Lax` is correct for a same-origin SPA. `Secure` stays config-driven (`session_cookie_secure`) for dev/test. **No change to `SessionMiddleware` config** (`dashboard.py:192-200`).
- SPA + API are **same-origin** (one nginx host), so the cookie is sent automatically with `fetch(url, { credentials: "same-origin" })`. No CORS, no `Access-Control-Allow-Credentials`.

### CSRF on JSON mutations (double-submit, adapted from HTMX)

The HTMX-era CSRF check (`_verify_csrf`: "POST must carry `HX-Request`") **cannot work for the SPA** and was always a weak proxy. Replace with a proper **double-submit cookie**:

1. On login success (and on `GET /api/v2/auth/csrf`), set a **non-httpOnly** cookie `telebot_csrf` = random token, `SameSite=Lax`, `Secure`, `path=/`.
2. SPA reads `telebot_csrf` and echoes it as header `X-CSRF-Token` on every mutating request.
3. Server dependency compares header vs cookie with `secrets.compare_digest`; 403 on mismatch.

```python
# api/deps.py
async def verify_csrf_token(request: Request):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        cookie = request.cookies.get("telebot_csrf", "")
        header = request.headers.get("x-csrf-token", "")
        if not cookie or not secrets.compare_digest(cookie, header):
            raise HTTPException(403, "CSRF token invalid")
```

**Why safe:** SameSite=Lax already blocks most cross-site POST vectors; double-submit adds defense-in-depth, and the readable token is *not* a session credential (it grants nothing alone). Standard SPA-with-cookies pattern, strictly stronger than the current `HX-Request` heuristic.

> Distinct from the legacy login CSRF (`telebot_login_csrf`, `path=/login`, httpOnly form token, `dashboard.py:142`) which protects the *legacy login form* and stays while legacy login lives. The new `telebot_csrf` protects *API mutations*. They coexist; `telebot_login_csrf` is removed when legacy login is decommissioned.

---

## 3. Same-Origin nginx Routing (parallel-run)

One host, four `location` classes. Order matters (most-specific first).

```nginx
server {
    listen 443 ssl http2;
    server_name dashboard.YOURDOMAIN.com;
    # … ssl + security headers unchanged …

    # 1) JSON API → uvicorn
    location /api/ {
        proxy_pass http://telebot:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 1b) login rate-limit also guards the JSON login
    location = /api/v2/auth/login {
        limit_req zone=telebot_login burst=5 nodelay;
        limit_req_status 429;
        proxy_pass http://telebot:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 2) SPA static bundle → SPA-router fallback to index.html
    location /app/ {
        alias /usr/share/nginx/telebot-spa/;   # if served by nginx (option a)
        try_files $uri $uri/ /app/index.html;
    }

    # 3) legacy login rate-limit (until decommissioned)
    location = /login {
        limit_req zone=telebot_login burst=5 nodelay;
        limit_req_status 429;
        proxy_pass http://telebot:8080;
        # … headers …
    }

    # 4) everything else (legacy HTMX pages + /stream + /static + /health) → uvicorn
    location / {
        proxy_pass http://telebot:8080;
        # … headers …
        proxy_buffering off;          # keep for /stream while SSE lives
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_read_timeout 86400s;
    }
}
```

**Routing decisions:**

- **SPA lives under `/app/`** (not `/`) so legacy `/overview`, `/positions`, etc. keep working untouched during parallel-run. The SPA client-router uses `/app/*` paths. `try_files … /app/index.html` makes deep-links and refreshes resolve to the SPA shell instead of 404.
- **Serving mechanism — two options:**
  - **(a) nginx serves from a shared volume** (`location /app/ { alias …; }`): no proxy hop, fastest; matches the existing `/home/murx/shared` topology but requires wiring a volume into `shared-nginx`.
  - **(b) uvicorn serves it** via `app.mount("/app", StaticFiles(directory="static/app", html=True))`: simpler (no volume change), one fewer moving part; every asset hits Python but that's negligible at one operator. **Recommended for v1.2.** With (b), nginx needs only the `location /` proxy and the SPA is reachable at `/app/`.
- **CORS:** none. Same scheme/host/port for SPA + API ⇒ cookies flow automatically.
- **Cutover knob:** migrating a page changes *nothing in nginx for that page* — the SPA already owns `/app/<page>`. Cutover = "make the SPA the operator's entry point for that page, then delete the legacy route." For a hard redirect (`/analytics` → `/app/analytics`) add a per-path `return 301` (or FastAPI redirect) when the legacy route is removed.

---

## 4. Live Data Transport — Recommendation: keep polling

**Recommendation: TanStack Query `refetchInterval: 3000` per live view. Do NOT add WebSocket. SSE optional but not recommended for v1.2.**

| Option | Pros | Cons | Fit for single-operator live-money tool |
|--------|------|------|------------------------------------------|
| **Polling (TanStack Query)** ✅ | Trivial; auto-pauses on hidden tab (`refetchIntervalInBackground:false`); reconnect free; same data path as one-shot fetches; matches current 3s UX; no server fan-out state | A request every 3s per open view (negligible for 1 user) | **Best.** One operator, one browser. The herd cost polling "solves badly" doesn't exist here. |
| **SSE** | Push, lower latency; `/stream` plumbing exists | Server holds a long-lived generator per client; `/stream` emits HTML (must be reworked to pure JSON); reconnect/auth-expiry handling adds code; needs `proxy_buffering off` | Marginal. 3s→2s push is imperceptible for monitoring. Adds moving parts for ~zero operator benefit. |
| **WebSocket** | Bidirectional, lowest latency | Connection lifecycle, WS auth handshake, reconnect/backoff, message protocol, nginx upgrade config; overkill for read-mostly UI | **Reject.** No bidirectional need; mutations are plain POSTs. |

**Rationale (verified against TanStack Query docs):** `refetchInterval` supports a static interval *and* a function form that can stop/slow polling based on state (e.g. stop when hidden, back off on error). With `staleTime`, the operator gets near-live numbers with cache-dedup and automatic retry. The dynamic-interval capability lets overview poll fast (3s) while history/analytics poll slowly or not at all.

```ts
useQuery({
  queryKey: ["overview"],
  queryFn: fetchOverview,
  refetchInterval: 3000,
  refetchIntervalInBackground: false,   // pause when the operator's tab is hidden
});
```

**Migration note:** the legacy SSE `/stream` stays alive only as long as the HTMX overview/staged pages exist. Once those pages are cut over, delete `/stream` and remove `proxy_buffering off` / `proxy_read_timeout 86400s` from nginx (they exist solely for SSE) — a final cutover cleanup item, not a blocker.

The existing `_last_positions_by_account` stale-while-revalidate cache (`dashboard.py:43, 1434`) that masks transient REST blips should be **kept** — it lives in `_get_all_positions()` and benefits the JSON API identically (prevents the positions list blinking to empty on a single failed poll). TanStack Query's `placeholderData: keepPreviousData` complements this client-side.

---

## 5. Build / Deploy & Cutover

### Vite build in the multi-stage Dockerfile

Add a Node build stage. The existing Tailwind-CLI stage is **removed** once the last HTMX page is gone (Tailwind moves into Vite via `@tailwindcss/vite`); during parallel-run **both coexist**.

```dockerfile
# ── Stage A: SPA build (NEW) ───────────────────────────────
FROM node:22-slim AS spa-build
WORKDIR /spa
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # vite build → /spa/dist

# ── Stage 1: legacy Tailwind CSS build (UNCHANGED, until HTMX gone) ──
FROM debian:bookworm-slim AS css-build
# … existing stage verbatim …

# ── Stage 2: runtime (MODIFIED) ────────────────────────────
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py *.json ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY scripts/ ./scripts/
COPY --from=css-build /build/static/css/app.*.css ./static/css/
COPY --from=css-build /build/static/css/manifest.json ./static/css/
COPY --from=spa-build  /spa/dist/ ./static/app/          # NEW: SPA bundle
RUN mkdir -p /app/data
EXPOSE 8080
CMD ["python", "-u", "bot.py"]
```

- `frontend/` is a new top-level dir (Vite project: `index.html`, `src/`, `vite.config.ts`, `package.json`). Set Vite `base: "/app/"` so asset URLs resolve under the nginx prefix.
- If serving via uvicorn (option b): add `app.mount("/app", StaticFiles(directory=str(BASE_DIR/"static"/"app"), html=True))` in `dashboard.py`. `html=True` gives the index.html fallback for client-side routes.
- **No production Node runtime** — `node` exists only in the build stage; the runtime image stays `python:3.12-slim`. Honors the locked decision.
- **Dev workflow:** `npm run dev` (Vite dev server, HMR) with a proxy in `vite.config.ts` forwarding `/api` → the dev container (`localhost:8090` per `docker-compose.dev.yml`). Cookies stay same-origin because Vite proxies the API under the same dev origin.

### Page-by-page cutover mechanism

The non-negotiable constraint (live-money controls must never regress) is satisfied because **legacy and SPA run simultaneously**; flip pages one at a time, roll back instantly.

```
Operator entry today:  /overview (HTMX)
During parallel-run:   /overview (HTMX) AND /app/overview (SPA) both live
Cutover of a page  =   verify SPA page vs MT5 demo → make it the linked entry → delete legacy route
Rollback           =   re-add legacy route / re-link old nav (git revert one file)
```

**Pilot: analytics** (read-only, no live-money action) → lowest blast radius. Build `/app/analytics`, verify numbers match `/analytics`, then it's "cut over." Live-money pages (position actions, settings, kill switch) come last, each verified against the MT5 demo before its legacy twin is removed.

**Decommission gate per page:** delete the legacy route + template only after its SPA twin passes MT5-demo verification. Kill switch and position-action endpoints are the final, most-scrutinized cutovers.

### Suggested build order (dependency-aware)

```
Phase A — JSON API foundation        (no UI; fully testable with curl/pytest)
  1. api/ package + APIRouter mounted at /api/v2 (one line in dashboard.py)
  2. deps.py: require_user (reuse _verify_auth's 401 branch), verify_csrf_token
  3. auth.py: login/logout/me/csrf (JSON) + telebot_csrf cookie
  4. read routers wrapping existing helpers: accounts, positions, history,
     signals, stages, analytics, meta/overview → Pydantic models
  5. action routers (close, modify-levels, close-partial, emergency, resume,
     trading-status) → JSON results, NOT toast HTML
  6. error-envelope exception handler
  ▸ Gate: pytest covers each route's shape + 401/403 paths. Bot core untouched.

Phase B — SPA scaffold + auth + design system
  7. frontend/ Vite + React 19 + Tailwind (+ @tailwindcss/vite) + shadcn/ui
  8. dark palette tokens (#252542 / #1a1a2e / #0f0f1a) → Tailwind theme
  9. fetch wrapper (HttpError, X-CSRF-Token, credentials:same-origin)
 10. QueryClient with global 401 → /app/login; login view; /app/me boot guard
 11. app shell + client router under /app/*; serve via uvicorn mount (or nginx /app/)
  ▸ Gate: can log in, see authed shell, 401 redirects work.

Phase C — page migration waves (each: fetch hook + view + verify vs legacy)
 12. analytics (PILOT, read-only)            ← cut over first
 13. signals, history (read-only)
 14. overview + positions list (live polling 3s)
 15. staged (live polling)
 16. settings (validate→confirm two-step modal as JSON)
 17. live-money actions: close, modify SL/TP, partial close, KILL SWITCH (last)
  ▸ Gate per page: SPA numbers/actions verified vs MT5 demo before legacy twin deleted.

Phase D — parallel-run cutover + HTMX decommission
 18. delete legacy routes/templates page-by-page as each twin is verified
 19. remove SSE /stream + nginx SSE directives once overview/staged are SPA
 20. remove legacy Tailwind CLI Dockerfile stage + templates/ + legacy /login
  ▸ Gate: only SPA + JSON API remain; dashboard.py reduced to wiring.
```

---

## New vs Modified Components

| Component | New / Modified / Untouched | Notes |
|-----------|---------------------------|-------|
| `api/` package (router, schemas, deps, errors, auth, per-resource modules) | **NEW** | The JSON contract; ~10 small modules |
| `frontend/` Vite + React SPA | **NEW** | shadcn/ui, Tailwind, TanStack Query, 9 views |
| `dashboard.py` | **MODIFIED** | +`include_router`, +`get_executor/settings/notifier` accessors, +optional `app.mount("/app")`; legacy routes deleted in Phase D |
| `Dockerfile` | **MODIFIED** | +Node `spa-build` stage; +`COPY --from=spa-build`; Tailwind stage removed in Phase D |
| `nginx/telebot.conf` | **MODIFIED** | +`location /app/` (option a), +`/api/v2/auth/login` rate-limit; SSE directives removed in Phase D |
| `nginx/limit_req_zones.conf` | **UNTOUCHED** | zone reused for JSON login |
| `config.py` SessionMiddleware settings | **UNTOUCHED** | cookie config reused as-is |
| `vite.config.ts` dev proxy | **NEW** | `/api` → dev container for same-origin cookies in dev |
| `executor.py`, `trade_manager.py`, `mt5_connector.py`, `db.py` | **UNTOUCHED** | called, never modified — blast radius confined to presentation |
| MT5 REST bridge | **UNTOUCHED** | separate service |
| `_verify_auth` 401 branch, `validate_settings_form`, `_get_all_positions`, `_get_accounts_overview`, `_enrich_stage_for_ui` | **REUSED** | called by JSON routes, logic unchanged |

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Storing the session in `localStorage`
**Why bad:** Reintroduces the XSS-token-theft risk the httpOnly cookie avoids; PROJECT.md explicitly rejects it.
**Instead:** httpOnly `telebot_session` cookie, same-origin, `credentials: "same-origin"`.

### Anti-Pattern 2: Returning toast HTML strings from JSON action routes
**Why bad:** Legacy action routes return `_render_toast_oob(...)` HTML (`dashboard.py:1201,1215`). Carrying that into the JSON API couples the API to the view.
**Instead:** Return structured results (`{ok, message}` or `{closed, failed}`); the SPA renders sonner toasts client-side.

### Anti-Pattern 3: Keeping the `HX-Request` CSRF check for the SPA
**Why bad:** A heuristic the SPA can't satisfy and that gives no real protection.
**Instead:** Double-submit `telebot_csrf` cookie + `X-CSRF-Token` header with `compare_digest`.

### Anti-Pattern 4: Re-querying / re-deriving data in JSON routes
**Why bad:** Duplicates logic already in `_get_*` helpers; risks divergence (e.g. the stale-while-revalidate cache).
**Instead:** Wrap the existing dict-returning helpers in `response_model`.

### Anti-Pattern 5: Adding WebSocket for a read-mostly single-operator UI
**Why bad:** Connection-lifecycle, WS auth handshake, reconnect-backoff for zero latency benefit at one user.
**Instead:** TanStack Query polling; SSE only if a measured need appears.

### Anti-Pattern 6: Cutting over live-money pages first
**Why bad:** Maximum blast radius on the one thing that must never regress.
**Instead:** Analytics pilot → read-only pages → live-money actions last, each verified vs MT5 demo.

---

## Scalability / Risk Notes (right-sized for a single operator)

| Concern | Assessment |
|---------|------------|
| Polling load | 1 operator × few views × 3s = trivial; no fan-out problem |
| Same-process coupling | Already the case in v1.0; JSON layer doesn't worsen it — bot core unimported |
| Asset serving via uvicorn (option b) | Acceptable at this scale; switch to nginx `alias` (option a) only if latency observed |
| Session-expiry mid-action | Global 401 handler redirects; in-flight mutation fails cleanly with 401 envelope |
| Rollback | Every cutover is one route/nav edit; legacy twin stays until verified |

---

## Sources

- Codebase (HIGH): `dashboard.py`, `bot.py:405-421`, `Dockerfile`, `nginx/telebot.conf`, `nginx/limit_req_zones.conf`, `docker-compose*.yml`, `config.py`, `.planning/codebase/ARCHITECTURE.md`, `.planning/PROJECT.md`
- TanStack Query — `QueryCache`/`MutationCache` global `onError`, `refetchInterval` (static + function form), `refetchIntervalInBackground` (HIGH, Context7 `/tanstack/query`): https://tanstack.com/query/latest/docs/framework/react/guides/polling
- FastAPI `APIRouter` + `include_router` + `response_model` + dependency-based auth/CSRF (HIGH, consistent with installed `fastapi==0.115.0`): https://fastapi.tiangolo.com/tutorial/bigger-applications/
- Double-submit-cookie CSRF for cookie-auth SPAs (MEDIUM, established pattern; consistent with OWASP CSRF cheat-sheet guidance)
