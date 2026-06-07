---
phase: 11
slug: live-money-pages-settings
status: verified
threats_open: 0
asvs_level: 1
created: 2026-06-07
---

# Phase 11 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Frontend-only phase (React 19 + Vite + TanStack Query + react-hook-form + zod). No backend files changed — server-side enforcement (CSRF 403, idempotency replay) lives in Phase 8 and is exercised by its tests; this phase verifies the client correctly wires into those guarantees.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| npm registry → build | Third-party package code enters the bundle at install (supply-chain) | Dependency source code |
| browser → /api/v2 mutations | Untrusted client requests cross into live-money + settings operations | Close / modify / partial-close / kill-switch / settings payloads + CSRF token |
| client retry → partial-close | A retried close could double-fire and close the wrong volume | `close_volume` + idempotency `request_id` |
| operator input → zod schema → server caps | Settings field values cross form → client validation (UX-only) → authoritative server re-validation | Risk-shaping settings values |
| background poll → open modal/drilldown | A 3s refetch could clobber typed SL/TP/lots if state were shared | Operator-typed input (local React state) |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-11-SC | Tampering | npm installs (react-hook-form, zod, @hookform/resolvers) | mitigate | 11-01 blocking human checkpoint verified packages genuine; `package.json` scripts have no install/postinstall hooks (`package.json:5-12`) | closed |
| T-11-01 | Elevation of Privilege | settingsSchema.ts client caps | accept | zod is UX-only defense-in-depth; server `validate_settings_form` re-validates authoritatively (422) | closed |
| T-11-02 | Information disclosure | footgun.ts | accept | Pure presentation calc off two bare numerics; no server internals/PII | closed |
| T-11-03 | Spoofing/Tampering | every mutation hook | mitigate | All hooks call `api()` → `X-CSRF-Token` double-submit echoed (`http.ts:51-53`); zero raw `fetch(` | closed |
| T-11-04 | Tampering | usePartialClose double-fire | mitigate | Absolute `close_volume` + stable `request_id` reused on retries; 409 on id-reuse-diff-params surfaced (`usePartialClose.ts:47-75`) | closed |
| T-11-05 | Repudiation/Integrity | useClose/useLevels/usePartialClose | mitigate | No optimistic `setQueryData`; UI derives from server-confirmed `invalidateQueries` | closed |
| T-11-06 | Information disclosure | mutation onError toasts | mitigate | Toast copy only from `errorMessage()` typed envelope (`ErrorPanel.tsx:27-36`) | closed |
| T-11-07 | Tampering/Integrity | PositionsView row Close | mitigate | Row clears only in onSuccess via `invalidateQueries`; no optimistic write | closed |
| T-11-08 | Tampering | EditPositionDialog partial-close | mitigate | Absolute lots + `request_id`; no percent; zod `0<value<volume`; **CR-01 fix** rounds-first/guards/submits same rounded value (`EditPositionDialog.tsx:107-115,143`) | closed |
| T-11-09 | DoS/UX-integrity | open Edit modal + drilldown under poll | mitigate | Modal/drilldown in local React state outside polling subtree (SC#3) | closed |
| T-11-10 | Spoofing | all three position mutations | mitigate | Routed through `api()` (CSRF); **WR-02 fix** `encodeURIComponent` on path params | closed |
| T-11-11 | Information disclosure | mutation error toasts | mitigate | `errorMessage()` only; 409 fixed operator-safe string | closed |
| T-11-12 | Elevation of Privilege | SettingsForm zod caps | mitigate | zod mirrors server caps (`makeSettingsSchema`); server re-validates (422); **CR-02 fix** `key={account}` remount (`SettingsView.tsx:115`) | closed |
| T-11-13 | Tampering | validate/confirm/revert | mitigate | All via `api()` → `X-CSRF-Token` (`useSettingsMutations.ts:59,72,89`) | closed |
| T-11-14 | Information disclosure | footgun (inline + confirm) | accept | Pure client calc off two bare numerics; Pitfall-5-safe | closed |
| T-11-15 | Integrity | validate 200-on-invalid handling | mitigate | Page branches on `data.valid` (Pitfall 7) — never silently confirms (`SettingsView.tsx:163-174`) | closed |
| T-11-16 | Information disclosure | rejection/error toasts | mitigate | Typed server errors map / `errorMessage()` only | closed |
| T-11-17 | Tampering | CONFIRM CLOSE ALL | mitigate | Two-step preview→confirm + disabled-while-pending; no optimistic state (`KillSwitchView.tsx:83,135-157`) | closed |
| T-11-18 | Spoofing | emergency close/resume | mitigate | Both via `api()` → `X-CSRF-Token` (`useEmergency.ts:33,44`) | closed |
| T-11-19 | DoS (operator error) | confirm when nothing to close | mitigate | Confirm hidden when both counts == 0 (`KillSwitchView.tsx:112`) | closed |
| T-11-20 | UX-integrity | Overview modal/drilldown under poll | mitigate | Reuses PositionsView local-state-outside-poll mechanism (SC#3) | closed |
| T-11-21 | Tampering | Overview-initiated mutations | mitigate | Same `api()`/useMutation hooks (CSRF-echoed, server-confirmed, no optimistic); kill-switch is a `<Link>` | closed |
| T-11-22 | Information disclosure | account cards / positions render | accept | Reads only server `*_display` data; only client calc is dimensionless `marginPct` ratio (Pitfall-5-exempt) | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-11-01 | T-11-01 | Client zod caps are UX-only; the server `validate_settings_form` is the authoritative gate (422 on re-breach). A bypassed client cap cannot persist out-of-cap settings. | operator | 2026-06-07 |
| AR-11-02 | T-11-02, T-11-14 | `footgun()` is a pure presentation calc off two bare numerics already on the page — no server internals, no money/price/PII. | operator | 2026-06-07 |
| AR-11-03 | T-11-22 | Overview renders only server `*_display` twins; the sole client number is a dimensionless margin-used ratio (documented Pitfall-5-exempt category). | operator | 2026-06-07 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-06-07 | 23 | 23 | 0 | gsd-security-auditor (opus) |

---

## Hardening Follow-ups (non-blocking)

| ID | Ref | Note |
|----|-----|------|
| HF-11-01 | T-11-SC | `frontend/package.json` uses caret ranges (`^7.77.0`, `^4.4.3`, `^5.4.0`), not exact-pinned versions. The load-bearing mitigation (genuine packages + no postinstall) is confirmed; exact pinning + a lockfile-integrity gate is an optional supply-chain hardening step. Does not block at `block_on: high`. |

## Runtime Confirmation (tracked in 11-HUMAN-UAT.md, not open threats)

These client mitigations are correctly wired but their end-to-end runtime enforcement is server-side (Phase 8) and needs the live MT5 demo to observe: CSRF 403 rejection, partial-close 409 idempotency replay, SC#1 broker-round-trip row clear, SC#3 modal-survives-poll, kill-switch broker close, settings account isolation, opaque-render, npm-registry legitimacy. Tracked as human-verification items 1–10.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-06-07
