# Phase 12: Parallel-run Cutover + HTMX Decommission - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-07
**Phase:** 12-parallel-run-cutover-htmx-decommission
**Areas discussed:** Cutover switch mechanism, Verification gate & order, Rollback / bake period, Decommission scope (CUT-03)

---

## Cutover switch mechanism

### How a verified page flips legacy → SPA

| Option | Description | Selected |
|--------|-------------|----------|
| Per-page backend redirect | Change each legacy route to `RedirectResponse('/app/<page>', 303)`, one commit per page; rollback = revert that commit; nginx untouched | ✓ |
| Per-page nginx rewrite | `location = /<page> { return 302 /app/<page>; }` per page; splits state onto VPS config + needs reload | |
| Flip-root-only at the end | Leave legacy reachable; only change / → /app/ once all verified (big-bang) | |

**User's choice:** Per-page backend redirect.
**Notes:** Cleanest page-by-page reversibility; rollback is a single `git revert`.

### When root `/` flips to /app/

| Option | Description | Selected |
|--------|-------------|----------|
| After all pages verified | Keep / → /overview until every page cut over, then flip / → /app/ last | ✓ |
| First (with overview) | Flip / → /app/ as soon as overview verified | |

**User's choice:** After all pages verified.

---

## Verification gate & order

### Does Phase 12 perform the outstanding Phase 10/11 MT5-demo UAT?

| Option | Description | Selected |
|--------|-------------|----------|
| Phase 12 owns the UAT | Each page's MT5-demo parity check is a task in this phase; passing it unblocks that page's redirect | ✓ |
| Assume UAT done upstream | Treat Phase 10/11 UAT as a precondition completed before Phase 12 | |

**User's choice:** Phase 12 owns the UAT.
**Notes:** The UAT is still open in STATE.md and nothing else schedules it; folding it into the cutover gate gives one "verified → cut over" place.

### Verification evidence

| Option | Description | Selected |
|--------|-------------|----------|
| Per-page checklist doc + sign-off | `12-CUTOVER-CHECKLIST.md` with parity items + dated operator sign-off per page | ✓ |
| Commit message attestation only | Verification captured inline in each redirect commit message | |

**User's choice:** Per-page checklist doc + sign-off.

### Cutover order

| Option | Description | Selected |
|--------|-------------|----------|
| Read-only first, live-money last | analytics → signals → history → staged → overview → settings → positions → kill-switch | ✓ |
| Operator-driven order | No fixed sequence; decided during execution | |

**User's choice:** Read-only first, live-money last.

---

## Rollback / bake period

### When does CUT-03 teardown happen?

| Option | Description | Selected |
|--------|-------------|----------|
| Live bake period, then teardown | Legacy stays deployed (dormant) after cutover; delete only after clean live run | ✓ |
| Teardown in same run | Delete the HTMX stack immediately after all pages verified | |

**User's choice:** Live bake period, then teardown.

### What ends the bake?

| Option | Description | Selected |
|--------|-------------|----------|
| Time + clean-run condition | N days no regression + explicit operator go-ahead | ✓ |
| Operator go-ahead only | No fixed duration | |
| N/A — same-run teardown | — | |

**User's choice:** Time + clean-run condition.

### Bake duration

| Option | Description | Selected |
|--------|-------------|----------|
| 7 days clean | One week live trading, no regression, then go-ahead | ✓ |
| 14 days clean | Two weeks, more conservative | |
| 3 days clean | Short smoke window | |

**User's choice:** 7 days clean.

---

## Decommission scope (CUT-03)

### dashboard.py fate after teardown

| Option | Description | Selected |
|--------|-------------|----------|
| Survives, HTML routes stripped | Keep app factory + /api/v2 + SPA mount + auth + /health + / → /app/; delete HTML routes, /stream, Jinja setup, asset_url/manifest | ✓ |
| Split into a module | Extract surviving code into app.py, retire dashboard.py name | |

**User's choice:** Survives, HTML routes stripped.
**Notes:** Lowest churn; bot.py import unchanged.

### Teardown commit structure

| Option | Description | Selected |
|--------|-------------|----------|
| Grouped by concern | ~4 reviewable commits: routes/SSE · templates+Basecoat · Dockerfile Stage 1 + CSS-CLI + nginx SSE · HTMX tests | ✓ |
| Single sweep commit | One big "CUT-03: decommission HTMX stack" commit | |

**User's choice:** Grouped by concern.

---

## Claude's Discretion

- Whether CUT-01 needs any code change or is satisfied by existing Phase-9 routing.
- Exact columns of the per-page `12-CUTOVER-CHECKLIST.md`.
- Full CUT-03 deletion inventory (every template, route line, vendor asset, asset_url/manifest call site, HTMX test).
- Whether SPA login fully replaces legacy `/login` (delete template; keep auth POST/session).
- Classification of `/api/emergency-preview`, `/partials/*`, `/api/trading-status` HTML endpoints under deletion (verify nothing in /app calls them).
- Redirect status-code nuance per page (303 fine for GET pages).

## Deferred Ideas

None — discussion stayed within phase scope. dashboard.py rename/split considered and rejected.
