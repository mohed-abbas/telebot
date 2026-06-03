---
phase: 08-json-api-foundation
reviewed: 2026-06-03T18:09:07Z
depth: standard
files_reviewed: 26
files_reviewed_list:
  - Dockerfile
  - api/__init__.py
  - api/accounts.py
  - api/actions.py
  - api/analytics.py
  - api/auth.py
  - api/deps.py
  - api/errors.py
  - api/formatting.py
  - api/history.py
  - api/idempotency.py
  - api/meta.py
  - api/positions.py
  - api/router.py
  - api/schemas.py
  - api/settings.py
  - api/signals.py
  - api/stages.py
  - dashboard.py
  - tests/_bot_core_diff_guard.py
  - tests/conftest.py
  - tests/test_api_contract.py
  - tests/test_api_csrf.py
  - tests/test_api_formatting.py
  - tests/test_api_idempotency.py
  - tests/test_api_settings.py
findings:
  critical: 1
  warning: 6
  info: 4
  total: 11
status: issues_found
---

# Phase 8: Code Review Report

**Reviewed:** 2026-06-03T18:09:07Z
**Depth:** standard
**Files Reviewed:** 26
**Status:** issues_found

## Summary

Phase 8 layers a versioned `/api/v2` JSON surface over the existing HTML dashboard. The deferred-import discipline is consistently applied and effective, the double-submit CSRF guard is correctly constant-time and cookie-non-colliding, parameterized SQL is used throughout the new idempotency table, and bot-core untouchability is mechanized by a diff guard. Read routes are uniformly session-gated.

The dominant concern is **money-mutation safety in the partial-close idempotency path**. The validation step that runs *before* the idempotency check reads the position's *current* volume, which a successful prior partial-close has already shrunk. This causes a legitimate retry — the exact scenario the `request_id` guard exists to protect — to be rejected with 422 instead of replaying the cached 200, defeating idempotency precisely when it matters. There is a secondary in-flight-replay window that can return an empty `{}` envelope. A handful of warnings concern the global error handler reshaping legacy HTML-route exceptions despite docstrings claiming otherwise, plus minor robustness gaps. The existing idempotency test suite does not cover the retry-after-shrink case, so the bug ships green.

## Critical Issues

### CR-01: Partial-close range check runs before the idempotency gate, breaking replay after the position has shrunk

**File:** `api/actions.py:185-203`
**Issue:** In `close_partial`, the order of operations is:
1. fetch live positions and read `pos.volume` (line 187-190),
2. validate `0 < cv < pos.volume` → 422 if out of range (line 192-194),
3. **then** call `idempotency.check(...)` (line 197).

A successful partial close shrinks the position's volume (confirmed in `mt5_connector.py:362-372`: `volume=round(pos.volume - volume, 2)`). When a client retries a request whose original execution succeeded but whose 200 was never received (network drop, double-click, gateway timeout — the canonical idempotency trigger), the retry now sees the *shrunk* `pos.volume`. If the original `cv` is `>=` the remaining volume, the range check fails and returns **422 before the idempotency cache is ever consulted**. The cached 200 is never replayed.

Concrete failure: position opens at 0.30, client requests `close_volume=0.25` (`request_id=R`). First call succeeds, position shrinks to 0.05, but the response is lost. Client retries `{close_volume: 0.25, request_id: R}`. The route sees `pos.volume=0.05`, evaluates `0 < 0.25 < 0.05` → False → 422 "out of range". The idempotency guard the whole rewrite (D-09/D-10/D-11) was built to provide is silently bypassed for any partial close larger than the residual volume. The SPA, having lost the first response, now believes the close failed — inviting a manual re-attempt against live money.

`tests/test_api_idempotency.py::test_replay` does not catch this because it uses `close_volume=0.10` of a 0.30 position, leaving 0.20 > 0.10 so the range check still passes on replay. The bug only manifests when `cv >= remaining`.

**Fix:** Consult the idempotency cache *before* the live-volume range check, so a known `request_id` replays unconditionally. Only run the range validation on the `new` path:

```python
connector = _connector_or_404(account)
cv = round(body.close_volume, 2)

# Idempotency gate FIRST — a known request_id replays regardless of current volume.
state, cached = await idempotency.check(body.request_id, account, ticket, cv)
if state == "replay":
    return cached
if state == "conflict":
    raise HTTPException(status_code=409, detail="request_id reused with different params")

# state == "new": now validate against the live position.
positions = await connector.get_positions()
pos = next((p for p in positions if p.ticket == ticket), None)
if pos is None:
    raise HTTPException(status_code=404, detail="Position no longer open")
if not (0 < cv < pos.volume):
    raise HTTPException(status_code=422, detail="close_volume out of range")

result = await connector.close_position(ticket, volume=cv)
payload = { ... }
await idempotency.store(body.request_id, account, ticket, cv, payload)
return payload
```

Note: moving `check` first means a `new` request_id is claimed before validation; if the subsequent range check 422s, the placeholder row remains and a corrected retry with the *same* request_id would then conflict/replay an empty result. To avoid poisoning the key on a validation failure, either (a) validate `cv > 0` and resolve the position *before* claiming the key while still consulting the cache first, or (b) have `store`/a cleanup delete the placeholder when the mutation is not executed. Add a regression test where `cv >= remaining-after-first-close` and assert the replay returns the cached 200 (not 422).

## Warnings

### WR-01: In-flight retry can replay an empty `{}` envelope (placeholder result returned as success)

**File:** `api/idempotency.py:60-100`, `api/actions.py:197-215`
**Issue:** `check` claims the `request_id` by inserting a row with `result = '{}'` and returns `"new"`. The caller then performs the broker close and only afterwards calls `store` to write the real payload. Between the claim and the `store`, the row exists with an empty-object result. A concurrent retry (double-click, client auto-retry) during this window finds the row, matches params, and returns `("replay", {})`. The route returns HTTP 200 with body `{}` — no `ok`, no `success`, no `closed_volume`. The SPA cannot distinguish this from a successful close and may render success while the original broker call is still in flight, or surface a malformed result. This is a real (if narrow) money-mutation correctness window on a single-user dashboard where rapid double-submits are plausible.

**Fix:** Distinguish "claimed but not yet stored" from "completed". Options: (a) store a sentinel/`status` field in the placeholder and, on replay with an empty/pending result, return 409 or a 425-style "in progress" rather than a bare `{}`; or (b) only treat a row as a replayable success when `result != '{}'`, otherwise treat as conflict/retry-later. At minimum, the route should guard: `if state == "replay" and not cached: raise HTTPException(409, "request in progress")`.

### WR-02: Global exception handlers reshape legacy HTML-route errors despite docstring claiming they are untouched

**File:** `api/errors.py:49-64, 83-87`; `dashboard.py:220`
**Issue:** `register_error_handlers` installs handlers for `HTTPException` and `StarletteHTTPException` **app-wide**, not scoped to `/api/v2`. For non-api paths the handler returns `JSONResponse(content={"detail": exc.detail})`. This changes legacy behavior: a 404 (or any raised `HTTPException`) on an HTML page route now returns an `application/json` body instead of Starlette's default `text/plain` "Not Found", and `_verify_auth`'s redirect `HTTPException(303, headers={"Location": ...})` (`dashboard.py:142`) now emits a 303 `JSONResponse` with body `{"detail": null}`. The 303+Location still redirects in browsers, so auth flow is not broken, but the module docstring ("these handlers only reshape responses on the /api/v2 prefix; other paths fall back to FastAPI defaults") is false — every HTML route's error responses are now JSON-shaped. This is a behavioral regression risk for any HTML/HTMX consumer that inspects error bodies or content-type.

**Fix:** Either return Starlette's genuine default for non-api paths (re-raise / delegate to `starlette.exceptions.http_exception`) instead of synthesizing a JSON body, or — cleaner — gate registration so the custom handler only applies under `/api/v2` and falls through to FastAPI's installed defaults otherwise. The current `_is_api_v2` early-return path still builds a `JSONResponse`, which is the regression; make it return a plain/HTML response matching prior behavior.

### WR-03: `confirm_settings` 422-rejects valid edits whenever any settings field is omitted from the JSON body

**File:** `api/settings.py:193, 239`; `dashboard.py:702-713`
**Issue:** The ported `validate_settings_form` (`dashboard.py:664`) is not partial-update tolerant: it unconditionally parses `risk_mode`, `risk_value`, and every key in `_SETTINGS_HARD_CAPS_INT` (`max_stages`, `default_sl_pips`, `max_daily_trades`) from the form, appending an error for any that is missing or non-coercible (`int(form.get(field, ""))` raises on `""`). The legacy HTML form always submitted all fields, so this never surfaced. The JSON contract passes `dict(body.values)` straight through (`api/settings.py:193`), so a SPA that PATCHes a single field (e.g. `{"values": {"max_stages": "4"}}`) will be rejected with errors on every omitted field — and on `confirm` that becomes an opaque 422 "Re-validation failed" (`api/settings.py:242`). The JSON API thus silently requires the client to echo the complete settings set on every mutation.

**Fix:** Either document and enforce full-object semantics in the schema (make `SettingsValidateIn.values`/`SettingsConfirmIn.values` a typed model with all required fields so the contract rejects partial bodies explicitly with field-level errors), or merge `body.values` over the current effective values before validating, so omitted fields default to their persisted values: `merged = {f: str(getattr(current, f)) for f in _SETTINGS_FIELDS}; merged.update(body.values)`.

### WR-04: `confirm_settings` re-validation 422 returns an opaque message and discards per-field errors

**File:** `api/settings.py:240-242`
**Issue:** On confirm, if server re-validation fails the route raises `HTTPException(422, detail="Re-validation failed")`, discarding the structured `errors` list it just computed. A client that passed `validate` but trips `confirm` (e.g. due to WR-03 partial-body semantics, or a TOCTOU change in effective settings) receives no field-level detail, making the failure undiagnosable from the API. The `validate` endpoint returns rich `{valid, errors}`; `confirm` should not regress to a bare string.

**Fix:** Return the same enveloped field errors as `validate`, e.g. raise with `detail` carrying `{e.field: e.message for e in errors}` (the validation handler in `api/errors.py` already supports a `fields` envelope), or return a `MutationResult`/`SettingsValidateResult` with `valid=False, errors=...` and an appropriate status.

### WR-05: `position_drilldown` returns the raw DB dict without session-gated price-precision guarantees and mutates the helper's dict in place

**File:** `api/positions.py:62-75`
**Issue:** Two issues: (1) The route mutates `pos` (a sub-dict of the value returned by `db.get_position_drilldown`) in place by assigning `pos["entry_price_display"]` etc. If that helper ever returns a cached/shared object, the mutation leaks across requests; defensively the route should copy before enriching, as `api/stages.py` correctly does (`out = dict(stage)`). (2) Unlike every other read route, this endpoint returns an unvalidated free-form `dict` rather than a Pydantic model, so the `_display` enrichment is silently skipped whenever the column names differ (the `if "entry_price" in pos` guards fail closed to no display field), producing an inconsistent contract the SPA cannot rely on. This is a robustness/consistency gap, not a crash.

**Fix:** Copy the position dict before enriching (`pos = dict(detail.get("position") or {})` then write back into a fresh `detail`), and consider modeling the drilldown response so missing display twins are detectable.

### WR-06: `emergency_preview` swallows all connector exceptions silently, masking broker/bridge failures

**File:** `api/meta.py:62-66`
**Issue:** The pending-orders loop wraps `connector.get_pending_orders()` in `except Exception: pass`, silently dropping any error (timeout, bridge down, auth failure). The kill-switch *preview* is the operator's last look before closing live positions; under-reporting pending orders because a connector quietly errored gives a false sense of scope. The legacy handler (`dashboard.py:1316-1322`) had the same swallow, so this is a faithful port — but it is a money-adjacent observability gap worth surfacing rather than silencing.

**Fix:** Log the exception (at minimum `logger.warning`) and/or signal partial-data in the response (e.g. a `degraded: true` / per-account error flag) so the operator knows the preview is incomplete rather than authoritative.

## Info

### IN-01: Discarded DB round-trip in analytics route

**File:** `api/analytics.py:47`
**Issue:** `await db.get_analytics_sources()` is called and its result discarded — the comment says it is "surfaced for the SPA filter control" but nothing in the response uses it. This is a dead call costing a DB round-trip per request.
**Fix:** Remove the call, or actually include the sources in the `Analytics` response if the SPA needs them.

### IN-02: `SettingsValidateIn.account` / `SettingsConfirmIn.account` are accepted but never used

**File:** `api/schemas.py:239-247`; `api/settings.py:172-173, 223-224`
**Issue:** The validate/confirm/revert handlers key entirely off the `{account_name}` path param; the body's `account` field is ignored. A client sending `{"account": "other"}` against `/settings/acctA` has its body `account` silently dropped. This is a harmless-but-confusing redundant field and a potential source of client confusion (which one wins?).
**Fix:** Drop `account` from the request bodies, or validate that `body.account == account_name` and 422 on mismatch.

### IN-03: `MutationResult.success` is `Optional[bool]` defaulting to `None`, producing tri-state success semantics

**File:** `api/schemas.py:256-261`; `api/settings.py:253, 305`
**Issue:** Settings confirm/revert return `MutationResult(ok=True, success=True)` while `close` returns `success=result.success`; the schema default leaves `success` nullable, so consumers must handle `true`/`false`/`null`. A tri-state success flag invites client branching bugs.
**Fix:** Make `success` non-optional with a definite default, or drop the `ok`/`success` duplication to a single boolean across all mutation envelopes.

### IN-04: `revert_settings` defensive 422 branch is documented as unreachable but raised anyway

**File:** `api/settings.py:297-299`
**Issue:** The comment states "A prior value should always re-validate" yet the code raises a 422 on the guarded branch. If it truly cannot happen this is dead defensive code; if it can (e.g. a hard cap was lowered after the original change was persisted, so the old value now exceeds the new cap), the 422 message "Revert failed re-validation" leaves the operator unable to undo a change — a usability trap on a safety-critical control.
**Fix:** Decide the contract: if reverting must always be possible, bypass cap re-validation for reverts (the value was previously legitimate); if not, return the specific field error so the operator understands why undo is blocked.

---

_Reviewed: 2026-06-03T18:09:07Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
