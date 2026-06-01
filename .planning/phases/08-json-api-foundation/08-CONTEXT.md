# Phase 8: JSON API Foundation - Context

**Gathered:** 2026-06-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Wrap `dashboard.py`'s existing in-process helpers in a versioned `/api/v2` JSON
contract — **the computation already exists; only the response shape changes.**

In scope:
1. **Read API** — every read view (accounts/overview, positions, history, signals,
   stages, analytics, overview-meta) retrievable via `GET /api/v2/...` returning
   Pydantic-modeled JSON wrapping the existing helpers (`_get_all_positions`,
   `_get_accounts_overview`, `db.get_*`, etc.).
2. **Mutation API** — every mutation (close, modify-levels, partial-close,
   kill-switch preview/confirm, resume, settings validate/confirm/revert) returns
   a structured `{success|error}` JSON envelope instead of an HTML fragment.
3. **Auth API** — the full `/api/v2/auth/{login,logout,me,csrf}` JSON contract.
4. **CSRF** — double-submit cookie (`telebot_csrf`, readable) echoed via
   `X-CSRF-Token`, `secrets.compare_digest`; regression-tested.
5. **Dual-value serialization** — every numeric/price/time field returned
   display-ready (server-formatted string) **and** machine-precise (raw numeric;
   times as ISO-8601 + UTC offset).
6. **Idempotent partial-close** — switch percent → absolute lots-to-close with a
   `request_id` guard.

**Out of this phase (hard boundary):**
- ANY change to the bot core — `executor.py`, `trade_manager.py`, `db.py`,
  `mt5_connector.py` — and the MT5 REST bridge. `git diff` must show these
  byte-for-byte untouched. (DB *additions* — a new idempotency table via additive
  DDL — are allowed; the constraint is on the bot-core code modules, consistent
  with the v1.2 "presentation layer only" decision.)
- The React/Vite SPA itself, login *view*, TanStack Query wiring → Phase 9
  (Phase 8 ships the contract the SPA *consumes*, not the SPA).
- Removing the legacy HTMX `/login` form or legacy `/api/*` HTML routes → Phase 12.
- Optimistic-update UI discipline → Phase 11 (a UI concern; Phase 8 only makes
  the operations idempotent so the UI *can* be safe).

</domain>

<decisions>
## Implementation Decisions

### Idempotency storage (Open Question 4 — RESOLVED)
- **D-01:** Partial-close dedup lives in a **new PostgreSQL table** (e.g.
  `idempotency_keys`), NOT in-memory and NOT Redis. **Scout confirmed Redis is not
  wired in either `docker-compose.yml` / `docker-compose.dev.yml`** — so the choice
  was in-memory vs Postgres, and durability-across-restart wins for a real-money op.
  A duplicate submit after a crash/redeploy must still dedup correctly.
- **D-02:** The idempotency key is **`request_id` alone** (sole primary key). One
  `request_id` = one logical operation. The row also stores `account`, `ticket`,
  and `close_volume` so a replay with the SAME id but DIFFERENT params is
  detectable (see D-09).
- **D-03:** **Short TTL (~24h)** with a cheap periodic age-out cleanup — mirrors the
  existing `failed_login_attempts` age-out pattern. Covers the realistic
  retry/double-fire/crash-redeploy window without unbounded growth. (Exact TTL
  value and cleanup mechanism = planner's call within "short, age-out".)
- **D-04:** Table creation uses **additive-only DDL** (consistent with the v1.0/v1.1
  no-Alembic, hand-written additive-migration convention). New table only — no
  alteration of existing tables.

### Dual-value JSON field shape (API-04)
- **D-05:** **Parallel suffixed fields**, not nested `{raw, display}` objects.
  Pattern: `price: 1.2345` + `price_display: "1.23"`. Only fields that need
  formatting (price, money/P&L, volume, timestamps) get a `_display` twin; plain
  ints/strings/enums stay bare. Flat, grep-able, minimal Pydantic models. The SPA
  reads `*_display` for render and the bare field for any submit.
- **D-06:** Machine-precise timestamps are **ISO-8601 with UTC offset**; the
  `*_display` twin is an **absolute, fixed-timezone** string (NOT relative
  "3m ago"). Deterministic, no client-clock dependency. The SPA may still derive
  relative time from the raw ISO field later, but the contract stays absolute.
- **D-07:** Display timestamps render in **UTC** with an explicit `UTC` marker.
  Unambiguous, matches the raw field's offset, aligns with how broker/trading
  timestamps are reasoned about. No TZ-config dependency introduced.
- **D-08:** A **single shared formatter module** (e.g. `api/formatting.py`) owns
  pip-size-aware price formatting, money formatting, and timestamp formatting; the
  symbol→digits map lives there; every model's `_display` field routes through it.
  Rationale: the XAUUSD pip-size class of bug (quick task 260501-i7u) came from
  precision logic living in multiple places — one module = one place to fix and test.

### Partial-close contract (API-05)
- **D-09:** Request body carries **`close_volume` in absolute lots** (the amount to
  CLOSE, e.g. `0.05`) — not a percent, not the target-remaining volume. Server
  validates `0 < close_volume < pos.volume` and rounds to the symbol lot step.
  Directly eliminates the percent-of-current double-fire bug (the 75% trap,
  Pitfall 3).
- **D-10:** `request_id` is **client-supplied** (the SPA generates a UUID per
  partial-close action).
- **D-11:** Duplicate-submit semantics:
  - same `request_id` + **same** params → **replay the cached success (200)**, do
    NOT touch the broker (true idempotency — a legitimate network retry just
    succeeds).
  - same `request_id` + **different** params → reject **409 Conflict** (client bug /
    id reuse; never close a different amount under a reused id).

### Auth-JSON scope (phase-boundary clarification)
- **D-12:** Phase 8 ships the **complete `/api/v2/auth/{login,logout,me,csrf}`
  JSON contract** now — alongside the CSRF infra it must build anyway. Phase 8 ⇒
  the whole curl-testable API; Phase 9 ⇒ the SPA that consumes it. Clean boundary.
- **D-13:** The legacy HTMX `/login` form and its `telebot_login_csrf` cookie stay
  **untouched and operational in parallel** (removed only in Phase 12). The new
  `telebot_csrf` cookie must **not collide** with `telebot_login_csrf`
  (`dashboard.py:142`).
- **D-14:** API login **reuses the existing rate-limit** path verbatim
  (`db.get_failed_login_count(ip, 15) ≥ 5`, `_client_ip()` — `dashboard.py:247-252`)
  and returns it as a JSON envelope (429). The nginx `limit_req` zone that today
  covers `/login` must be extended to also cover `/api/v2/auth/login` (planner +
  Phase 9/deploy note).

### CSRF mechanism (locked by API-03 + v1.2 research — recorded for downstream)
- **D-15:** New API CSRF = readable (`httponly=false`) `telebot_csrf` cookie,
  `SameSite=Lax`, `Secure`, `path=/`, set on login success and `GET /api/v2/auth/csrf`;
  SPA echoes it as `X-CSRF-Token`; server compares with `secrets.compare_digest`.
  The HTMX-era `_verify_csrf` "`HX-Request` header present" heuristic
  (`dashboard.py:128-135`) is **replaced for `/api/v2`** by a new dependency — NOT
  deleted (legacy HTMX routes keep their check until decommissioned in Phase 12).
- **D-16:** A regression test proving `POST` to any `/api/v2` mutation WITHOUT a
  valid `X-CSRF-Token` returns `403` is **required before any page goes live**
  (Pitfall 2; Phase 8 SC#3).

### Claude's Discretion (planner/researcher decides)
- Router package layout (`api/` package, one module per resource: `auth.py`,
  `positions.py`, `settings.py`, …) and the accessor-functions-vs-global-imports
  technique for keeping the bot core's globals out of the new package.
- Error envelope exact shape (v1.2 ARCHITECTURE.md recommends **bare resource on
  success, enveloped `{error:{code,message,fields?}}` on failure** — adopt unless a
  better fit surfaces).
- Whether to expose `/api/v2` OpenAPI docs internally (`docs_url` scoped).
- Exact `request_id`/idempotency-table column types, the TTL constant, and the
  cleanup trigger (within D-03's "short, age-out").
- Which existing read helper maps to which Pydantic response model.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & milestone scope
- `.planning/REQUIREMENTS.md` §API — JSON API Layer (API-01..API-05) — the 5
  requirements this phase delivers; also §Open Questions 1 & 4 (CSRF cookie name
  collision; idempotency storage — now resolved here).
- `.planning/ROADMAP.md` Phase 8 — goal + 5 success criteria + Research flag.
- `.planning/PROJECT.md` §Current Milestone + §Key Decisions — "FastAPI dashboard
  → JSON API; bot core untouched", "keep httpOnly session-cookie auth, same-origin".
- `.planning/STATE.md` §Blockers/Concerns — Pitfalls 1–5 (esp. Pitfall 2 CSRF,
  Pitfall 3 partial-close idempotency, Pitfall 5 server-side formatting) and the
  Phase 8 prep todos (cookie-name collision; `/api/v2` → 401 branch confirmation).

### v1.2 research synthesis (HIGH confidence — primary design source)
- `.planning/research/ARCHITECTURE.md` §1 (JSON API design — `/api/v2` mount,
  new `api/` package, accessors, Pydantic v2 models, error envelope), §2 (auth for
  SPA on session cookies — login flow, 401 detection, CSRF double-submit). **Most
  detailed and directly applicable doc for this phase.**
- `.planning/research/PITFALLS.md` — Pitfall 1 (no optimistic updates), Pitfall 2
  (CSRF `HX-Request` breaks for SPA — replace, don't delete), Pitfall 3
  (partial-close non-idempotent percent double-fire), Pitfall 5 (server-side
  number/time formatting; XAUUSD pip-size).
- `.planning/research/SUMMARY.md` — executive summary + must-mitigate pitfalls.
- `.planning/research/STACK.md` — locked v1.2 stack (Pydantic v2, FastAPI APIRouter).
- `.planning/research/FEATURES.md` — JSON API layer feature breakdown.

### Codebase intel & grounding (current system)
- `dashboard.py:99-125` — `_verify_auth`: already 401s on `/api/`-prefixed paths,
  so `/api/v2` inherits the 401 branch (no auth-redirect change). Resolves the
  "confirm `/api/v2` hits the 401 branch" prep todo.
- `dashboard.py:128-135` — legacy `_verify_csrf` (`HX-Request` heuristic) to be
  superseded for `/api/v2` (D-15), kept for legacy routes.
- `dashboard.py:142` — `CSRF_COOKIE = "telebot_login_csrf"` (the name the new
  `telebot_csrf` must not collide with).
- `dashboard.py:1218-1266` — current `close_partial` (percent-of-`pos.volume`); the
  exact code path API-05 replaces with absolute volume + idempotency.
- `dashboard.py` route inventory (`@app.get/post` lines 205-1339) — the ~31
  endpoints whose response shape this phase mirrors into `/api/v2`.
- `.planning/codebase/ARCHITECTURE.md`, `CONVENTIONS.md`, `STACK.md` — existing
  layering, async/DB-helper conventions, and v1.0 stack baseline the `api/` package
  must follow.
- Prior context: `.planning/phases/05-foundation/05-CONTEXT.md` D-14 (login CSRF
  double-submit, path=`/login` only), D-15 (`SessionMiddleware` / `SESSION_SECRET`),
  D-17 (`failed_login_attempts` 5/15min lockout the API login reuses).
- `docker-compose.yml` / `docker-compose.dev.yml` — confirmed **no Redis service**
  (basis for D-01).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_get_all_positions()`, `_get_accounts_overview()`, `db.get_*` helpers
  (`dashboard.py`): wrap their existing dict output in Pydantic models verbatim —
  the computation is done, only serialization is new.
- `_verify_auth` (`dashboard.py:99-125`): reuse as the `/api/v2` auth dependency;
  its `/api/`-prefix → 401 branch is exactly what the SPA needs.
- Rate-limit primitives `db.get_failed_login_count` + `_client_ip`
  (`dashboard.py:147-152, 247-252`): reuse unchanged for `/api/v2/auth/login`.
- argon2 `PasswordHasher` + `SessionMiddleware` (`dashboard.py:144, 192-200`):
  the JSON login sets the same `telebot_session` httpOnly cookie.
- `failed_login_attempts` age-out pattern (Phase 5 D-17): template for the
  idempotency-table TTL cleanup (D-03).

### Established Patterns
- Additive-only hand-written DDL (no Alembic) — the new idempotency table follows it.
- DB is the runtime source of truth (Phase 5 D-23/D-24).
- Server-side formatting discipline (Pitfall 5 / quick task 260501-i7u) — the
  shared formatter module (D-08) is the structural enforcement of this.

### Integration Points
- New `api/` package mounted via `app.include_router(APIRouter(prefix="/api/v2"))`
  near app creation in `dashboard.py`; bot core modules import-untouched.
- New `telebot_csrf` cookie coexists with `telebot_login_csrf`; new CSRF dependency
  guards `/api/v2` mutations only.
- nginx `limit_req` zone (existing, covers `/login`) extended to
  `/api/v2/auth/login`.

</code_context>

<specifics>
## Specific Ideas

- **"Bot core stays byte-for-byte untouched."** The non-negotiable safety anchor:
  a `git diff` on `executor.py` / `trade_manager.py` / `db.py` / `mt5_connector.py`
  and the MT5 bridge must be empty. New code lives in a new `api/` package + a new
  idempotency table.
- **"One place formats numbers."** The XAUUSD pip-size bug already bit this project
  once; the single shared formatter module is the deliberate guard so it can't
  recur across pages.
- **"A retry must just succeed."** Partial-close idempotency is designed around the
  legitimate-network-retry case: same request_id + same params replays the cached
  200, never re-hits the broker, never closes a fraction-of-a-fraction.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (Auth-JSON placement and CSRF
mechanism were boundary clarifications, not new capabilities; the SPA, login view,
and legacy-route removal remain explicitly assigned to Phases 9/11/12.)

</deferred>

---

*Phase: 8-json-api-foundation*
*Context gathered: 2026-06-01*
