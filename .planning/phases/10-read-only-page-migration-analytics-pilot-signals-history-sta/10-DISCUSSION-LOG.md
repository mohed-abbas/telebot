# Phase 10: Read-only Page Migration (analytics pilot → signals → history → staged) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-06
**Phase:** 10-read-only-page-migration-analytics-pilot-signals-history-sta
**Areas discussed:** Analytics API gap, Analytics filters, Live vs snapshot freshness, Staged elapsed-time, Shared table + states, Error/refresh states

---

## Analytics API gap

| Option | Description | Selected |
|--------|-------------|----------|
| Extend /analytics to full parity | Widen Analytics schema + endpoint to surface by_source[], extremes, avg_stages, sources list the db already computes. One round-trip, mirrors legacy 1:1. | ✓ |
| Split into 2 endpoints | Keep /analytics summary-only, add separate /analytics/by-source + /analytics/sources. More REST-granular, two round-trips. | |
| Trim SPA analytics scope | Ship only summary KPIs; drop per-source deep-dive. Fails SC#1, needs roadmap amendment. | |

**User's choice:** Extend /analytics to full parity
**Notes:** Read-only widening; db layer already computes by_source/extremes/avg_stages and the endpoint already awaits get_analytics_sources() and discards it. Satisfies SC#1 literally with least surface area.

---

## Analytics filters

| Option | Description | Selected |
|--------|-------------|----------|
| URL filters, all-time default | range + source in URL query params (bookmarkable), default all-time/no source (matches legacy), source-row click sets ?source=. Same helper as history. | ✓ |
| URL filters, 30-day default | Same URL filters, default to 30-day range. Diverges from legacy default. | |
| Local state only | Analytics filters in component state, only history gets URL filters. Two filter conventions. | |

**User's choice:** URL filters, all-time default
**Notes:** Consistent with SC#3 history filters; one shared URL-sync helper across analytics + history.

---

## Live vs snapshot freshness

| Option | Description | Selected |
|--------|-------------|----------|
| Only staged polls | Staged polls (live in-flight view); analytics/signals/history fetch-on-mount + refetch-on-focus, no background interval. Matches legacy, lightest load. | ✓ |
| Staged + signals poll | Staged and signals poll on interval; analytics/history snapshot. More live-feel for signal feed. | |
| All pages poll | Every page gets a background refetchInterval. Maximally fresh, more DB load for little gain. | |

**User's choice:** Only staged polls
**Notes:** keepPreviousData still prevents flicker on filter changes; snapshot pages get a manual Refresh control (see States).

---

## Staged elapsed-time

| Option | Description | Selected |
|--------|-------------|----------|
| Client ticking timer, 3s poll | Server provides start timestamp; SPA computes smooth per-second elapsed client-side. Data polls ~3s. Relative duration off server epoch isn't the Pitfall-5 ban class. | ✓ |
| Server *_display, 2s poll | Server sends preformatted elapsed string, renders verbatim, updates on poll (~2s). Jumps every 2s, polls twice as often. | |
| Server *_display, 5s poll | Same server string, poll every 5s. Lightest, but looks stale for a live view. | |

**User's choice:** Client ticking timer, 3s poll
**Notes:** Requires read-only enrichment of /stages active payload to carry a machine start-timestamp (legacy only emits a server `elapsed` string at pending_stages.html:33).

---

## Shared table + states

| Option | Description | Selected |
|--------|-------------|----------|
| Shared primitives, pilot-first | Build reusable DataTable + Loading(skeleton)/Empty/Error trio during the pilot. Tables for signals/history/resolved + analytics by-source; cards for staged-active. Phase 11 inherits. | ✓ |
| Extract after 2nd page | Build analytics + signals bespoke first, extract shared components once duplication is visible. | |
| Per-page bespoke | Each page builds its own table/states; nothing for Phase 11 to inherit. | |

**User's choice:** Shared primitives, pilot-first
**Notes:** SC explicitly says Phase 11 inherits shared list/table patterns; pilot is where they're proven.

---

## Error/refresh states

| Option | Description | Selected |
|--------|-------------|----------|
| Inline error + refresh button | Failed fetch renders inline error panel (msg + Retry) in page body; snapshot pages get a manual Refresh button. 401 still via global onAuthError. | ✓ |
| Toast error + refresh button | Errors via sonner toast, page keeps last-good data. Less prominent on cold-load failure. | |
| Inline error, no manual refresh | Inline panel but no Refresh button; rely on refetch-on-focus. | |

**User's choice:** Inline error + refresh button
**Notes:** A read-only page that failed to load should show its own failure state, not just flash a toast.

---

## Claude's Discretion

- Exact column sets/ordering per table (match legacy templates as parity reference).
- DataTable API surface and shared component/hook locations in `frontend/src`.
- Exact staleTime/refetchInterval numbers within the frame (staged ~3s; others no interval).
- Which shadcn components each page pulls in via the CLI.
- Precise shape of the analytics schema widening (by_source row fields, extremes, sources).
- Precise field name for the staged active start-timestamp + optional _display twin.
- Client ticking-timer implementation (shared useElapsed hook vs per-card).
- Parity-verification mechanics (side-by-side vs golden-number capture).

## Deferred Ideas

None — discussion stayed within phase scope. Live-money pages, mutation/CSRF-on-write discipline, settings, and react-hook-form/zod validation remain Phase 11; legacy-route / SSE / Tailwind-CLI removal remains Phase 12.
