# Phase 8: JSON API Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-01
**Phase:** 8-json-api-foundation
**Areas discussed:** Idempotency storage, Dual-value JSON shape, Auth-JSON scope, Partial-close contract

---

## Idempotency storage

### Storage mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| PostgreSQL table | Small idempotency_keys table; survives bot restart/redeploy; one extra INSERT/SELECT per mutation. | ✓ |
| In-memory dict | Process-local dict + TTL sweep; zero DDL, fastest; lost on restart so a duplicate after a crash executes. | |
| You decide | Defer to researcher/planner. | |

**User's choice:** PostgreSQL table
**Notes:** Scout confirmed no Redis in either docker-compose file, so the real choice was in-memory vs Postgres. Durability-across-restart wins for a real-money operation.

### Dedup key

| Option | Description | Selected |
|--------|-------------|----------|
| request_id alone | Client-supplied request_id is the sole PK; row also stores account/ticket/target_volume to detect same-id-different-params. | ✓ |
| request_id + account + ticket | Composite key; more defensive but muddies the contract. | |
| You decide | Defer to planner. | |

**User's choice:** request_id alone

### Retention

| Option | Description | Selected |
|--------|-------------|----------|
| Short TTL (~24h) | Covers retry/double-fire/crash-redeploy window; cheap age-out; mirrors failed_login_attempts pattern. | ✓ |
| Keep forever | Never delete (like settings_audit); no cleanup job but unbounded growth. | |
| You decide | Defer to planner. | |

**User's choice:** Short TTL (~24h)

---

## Dual-value JSON shape

### Field shape

| Option | Description | Selected |
|--------|-------------|----------|
| Parallel suffixed fields | price + price_display; flat, grep-able, minimal Pydantic models; only formatted fields get a _display twin. | ✓ |
| Nested {raw, display} object | Each formatted field becomes an object; uniform but verbose, deeper TS types. | |
| You decide | Defer to planner. | |

**User's choice:** Parallel suffixed fields

### Time display format

| Option | Description | Selected |
|--------|-------------|----------|
| Absolute, fixed TZ | Server formats to a fixed timezone; deterministic, no client-clock dependency. | ✓ |
| Relative ("3m ago") | Humanized relative strings; goes stale on render, drifts from viewer clock. | |
| You decide | Defer to planner. | |

**User's choice:** Absolute, fixed TZ

### Formatter location

| Option | Description | Selected |
|--------|-------------|----------|
| Single shared formatter module | One module owns pip-size/money/time formatting; one place to fix and test. | ✓ |
| Per-model inline formatting | Each model formats its own fields; re-derives pip-size rules (how the XAUUSD bug spread). | |
| You decide | Defer to planner. | |

**User's choice:** Single shared formatter module

### Timezone

| Option | Description | Selected |
|--------|-------------|----------|
| UTC | Explicit UTC suffix; unambiguous, matches raw ISO offset, no TZ-config dependency. | ✓ |
| Operator local TZ | More readable but adds tz-config dependency and UTC/broker-log confusion. | |
| You decide | Defer to planner (default UTC). | |

**User's choice:** UTC

---

## Auth-JSON scope

| Option | Description | Selected |
|--------|-------------|----------|
| Build auth JSON in Phase 8 | Ship /auth/login, /logout, /me, /csrf as JSON now; Phase 8 = whole curl-testable API, Phase 9 = SPA that consumes it; legacy /login untouched. | ✓ |
| CSRF infra only; defer login to Phase 9 | Build telebot_csrf machinery + /auth/csrf + /auth/me now; login/logout JSON land in Phase 9. | |
| You decide | Defer to planner. | |

**User's choice:** Build auth JSON in Phase 8
**Notes:** Rate-limit reuse (failed_login_attempts + nginx limit_req covering /api/v2/auth/login) captured as a planner note rather than a separate question.

---

## Partial-close contract

### Duplicate-submit semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Replay cached success 200 | Second identical submit returns the stored first result without touching the broker; true idempotency for retries. | ✓ |
| Reject duplicate with 409 | Second submit returns 409; safe but SPA must special-case 409-as-success. | |
| You decide | Defer to planner. | |

**User's choice:** Replay cached success 200 (same id + different params still → 409, captured in CONTEXT D-11)

### Volume contract

| Option | Description | Selected |
|--------|-------------|----------|
| Volume to CLOSE, absolute lots | Body carries close_volume in absolute lots; validated 0 < v < pos.volume; eliminates percent double-fire. | ✓ |
| Target REMAINING volume, absolute lots | Body carries desired remaining volume; also idempotent but inverts operator mental model. | |
| You decide | Defer to planner. | |

**User's choice:** Volume to CLOSE, absolute lots

---

## Claude's Discretion

- Router package layout (`api/` package, one module per resource) and accessor-vs-global-import technique for keeping bot core untouched.
- Error envelope exact shape (research recommends bare-success / enveloped-error).
- Whether to expose `/api/v2` OpenAPI docs internally.
- Exact idempotency-table column types, TTL constant, cleanup trigger.
- Which read helper maps to which Pydantic response model.

## Deferred Ideas

None — discussion stayed within phase scope.
