---
phase: 10
slug: read-only-page-migration-analytics-pilot-signals-history-sta
status: secured
threats_total: 18
threats_closed: 18
threats_open: 0
register_authored_at_plan_time: true
asvs_level: 2
created: 2026-06-07
---

# SECURITY.md — Phase 10 (Read-Only Page Migration: Analytics Pilot, Signals, History, Staged)

**Audited:** 2026-06-07
**ASVS Level:** 2
**Block-on:** high
**Register origin:** authored at plan time (`register_authored_at_plan_time: true`) — each declared mitigation VERIFIED against current source; no scan for net-new threats.

**Result: SECURED — 18/18 threats closed.**

---

## Trust boundaries (from register)

- Authenticated browser/SPA → `GET /api/v2/{analytics,stages,signals,history}` (session cookie, same-origin)
- URL filter params → query keys
- Signal `details` / `raw_text` → DOM

---

## Threat verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-10-01 | Information Disclosure | mitigate | CLOSED | `api/analytics.py:52` route signature `_user: str = Depends(require_user)`; `require_user` raises 401 if no session (`api/deps.py:43-52`) |
| T-10-02 | Tampering (SQLi) | accept | CLOSED | `range` int-coerced + 422 on malformed in `_parse_range` (`api/analytics.py:25-45`); `source_name` parameterized asyncpg `$n` (`db.py:668-671`). `range_days` interpolated only through `int(range_days)` (`db.py:666, 757`) — matches declared "int()-coerced" mitigation. Accepted-risk entry logged below. |
| T-10-03 | Information Disclosure | mitigate | CLOSED | `api/stages.py:67` `Depends(require_user)` |
| T-10-04 | Tampering | accept | CLOSED | `api/stages.py` is serialization-only (`_enrich_active`/`_enrich_resolved`/`zip`); no query construction added. Accepted-risk entry logged below. |
| T-10-05 | Tampering (SQLi) | accept | CLOSED | All 5 history params bound as asyncpg `$n` in `db.get_filtered_trades` (`db.py:526-549`); `from_date`/`to_date` typed `date` and FastAPI-parsed (`api/history.py:79-80`). Accepted-risk entry logged below. |
| T-10-06 | Tampering/Info (reflected XSS) | mitigate | CLOSED | `details`/`raw_text` returned as plain JSON strings (`api/signals.py:33-56`); rendered as React text children (`SignalsView.tsx:129-136`); zero `dangerouslySetInnerHTML` across `frontend/src` (grep, no matches) |
| T-10-07 | Information Disclosure | mitigate | CLOSED | `api/signals.py:61` and `api/history.py:81,102` both `Depends(require_user)` |
| T-10-08 | Spoofing | mitigate | CLOSED | `api()` uses `credentials: "same-origin"`, never reads session cookie, sends no token from storage (`http.ts:46-59`); 401 → single global redirect on both QueryCache + MutationCache (`queryClient.ts:42-60`) |
| T-10-09 | Tampering | accept | CLOSED | SPA sends only known keys `range`/`source` (`AnalyticsView.tsx:174-178`); server coerces/parameterizes (T-10-02). Accepted-risk entry logged below. |
| T-10-10 | Information Disclosure | mitigate | CLOSED | All money fields render server `_display` strings; only `win_rate`/`profit_factor` (ratios, D-14 exempt) and `avg_stages` (count) use `toFixed` (`AnalyticsView.tsx:88,94,358`). No `toFixed`/`parseFloat`/`Number()` on any money/price field |
| T-10-11 | Tampering/Info (reflected XSS) | mitigate | CLOSED | Details cell is React text child (`SignalsView.tsx:129-136`); no `dangerouslySetInnerHTML` in SignalsView (grep) |
| T-10-12 | Tampering (SQLi) | accept | CLOSED | Server parameterizes all 5 (`db.py:526-549`); SPA passes only `FILTER_KEYS` (`HistoryView.tsx:74-80,161-164`). Accepted-risk entry logged below. |
| T-10-13 | Spoofing | mitigate | CLOSED | Same-origin httpOnly cookie via `api()` (`http.ts:55-59`); 401 → global redirect (`queryClient.ts:42-46`) |
| T-10-14 | Information Disclosure | mitigate | CLOSED | Signals/history money/price render `_display` strings only; no numeric reformatting in `SignalsView.tsx`/`HistoryView.tsx` (grep clean) |
| T-10-15 | Spoofing | mitigate | CLOSED | Stages poll uses `api()` (`StagedView.tsx:149`) → same-origin cookie + 401 global redirect |
| T-10-16 | Information Disclosure | mitigate | CLOSED | `band_*`/`current_price` render `_display` strings only (`StagedView.tsx:128,133`); the one client computation is the elapsed duration (`useElapsed.ts`), server still owns the epoch (`started_at`) — declared exemption |
| T-10-17 | Denial of Service | accept | CLOSED | `refetchInterval: 3000` (`StagedView.tsx:152`); `refetchIntervalInBackground: false` inherited (`queryClient.ts:56`); single-operator tool. Accepted-risk entry logged below. |
| T-10-SC | Tampering (supply chain) | accept/n-a | CLOSED | `frontend/package.json` has zero Phase-10 commits (last touch Phase 09-01); shadcn CLI source-gen path deliberately NOT exercised — range tabs/filters built as plain styled native controls (10-04/10-05 SUMMARY). Zero new runtime deps. Accepted-risk entry logged below. |

---

## Inherited mitigations relied upon (verified present)

- **Session gate** — `require_user` (`api/deps.py:43-52`): 401 (no redirect) when session `user` absent. Applied to every Phase-10 route entry point (analytics, stages, signals, history, filter-options).
- **CSRF double-submit** — `verify_csrf_token` (`api/deps.py:55-66`): guards only state-changing methods. Phase 10 routes are all GET (read-only), so CSRF is not on the read path, but the wrapper is present and the SPA echoes `X-CSRF-Token` on mutations (`http.ts:51-53`).
- **Global 401 redirect** — single `onAuthError` wired on BOTH QueryCache and MutationCache `onError` (`queryClient.ts:62-71`), with login-path loop-break.

---

## Accepted risks log

| ID | Risk | Rationale (verified in code) |
|----|------|------------------------------|
| T-10-02 | analytics `range`/`source` tampering (SQLi) | `range` int-coerced (422 on malformed); `source_name` asyncpg `$n` parameterized. `range_days` reaches SQL only via `int()`. |
| T-10-04 | stages read query tampering | No new query construction — serialization-only widening. |
| T-10-05 | history 5-filter SQLi | All 5 params asyncpg `$n`; dates FastAPI-parsed to `date`. |
| T-10-09 | analytics URL-param tampering | SPA sends only known keys; server coerces/parameterizes. |
| T-10-12 | history filter SQLi | Server parameterizes all 5; SPA passes known keys only. |
| T-10-17 | 3s-poll DoS | Single-operator tool; background polling paused on hidden tab; 3s matches legacy cadence. |
| T-10-SC | supply-chain (npm/pip) | Zero new runtime deps; shadcn CLI copies vetted source (not a dep) and was not exercised. |

---

## Unregistered flags

None. `## Threat Flags` (10-01-SUMMARY.md) and `## Threat Surface` (10-02/03/05-SUMMARY.md) report no new endpoints, auth paths, query construction, trust boundaries, or runtime dependencies. All implementation-time notes map to existing register IDs (T-10-SC for the shadcn-CLI-avoided choices in 10-04/10-05).

---

## Corroborating artifacts (independently re-verified, not relied on as sole evidence)

- `10-REVIEW.md` (commit 6838123): SQLi clean, XSS clean, `_display` twin discipline observed.
- `10-UAT.md`: live XSS render-as-literal-text + 401-before-login redirect confirmed.
