# Phase 9: SPA Scaffold + Auth + Design System - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-04
**Phase:** 9-spa-scaffold-auth-design-system
**Areas discussed:** Serving & URL strategy, Scaffold ambition, SC#5 polling proof, Design tokens & shadcn set

---

## URL strategy

| Option | Description | Selected |
|--------|-------------|----------|
| /app/ subpath | SPA at /app/*, legacy keeps /overview etc. untouched; clean parallel-run, try_files fallback; Vite base '/app/'. | ✓ |
| Root with path whitelist | SPA at /, whitelist legacy paths; more disruptive, higher cutover risk. | |

**User's choice:** /app/ subpath (research recommendation)
**Notes:** Drives Vite `base` + client router under `/app/*`. Resolves Open Question 2.

---

## Serving mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| uvicorn StaticFiles | app.mount('/app', StaticFiles(..., html=True)); no volume wiring, one fewer moving part; per-asset Python cost negligible at 1 operator. | ✓ |
| nginx alias from shared volume | location /app/ { alias ...; } via shared-nginx at /home/murx/shared; fastest, matches topology but needs volume wiring + deploy copy. | |

**User's choice:** uvicorn StaticFiles (research recommendation)
**Notes:** Chosen despite operator's existing shared nginx, to avoid volume + deploy-copy coupling. Resolves Open Question 3.

---

## Scaffold ambition

| Option | Description | Selected |
|--------|-------------|----------|
| Full shell w/ nav skeleton | Login + auth guard + app shell with sidebar nav showing disabled placeholder links for future pages; Phase 10 slots pages into ready routes. | ✓ |
| Minimal (login + probe only) | Login + 401 guard + one probe; nav/routing built in Phase 10 with first real page. | |

**User's choice:** Full shell with nav skeleton (research-aligned)
**Notes:** Smoother handoff to the page-migration phases.

---

## SC#5 polling proof

| Option | Description | Selected |
|--------|-------------|----------|
| Real endpoint probe | Poll a live Phase-8 read endpoint (trading-status/overview-meta) on the shell with a deliberate open input/modal during refetch; probe removed in Phase 10. | ✓ |
| Throwaway dev-only probe | Synthetic counter endpoint; isolated but proves nothing about the real API path. | |

**User's choice:** Real endpoint probe (research recommendation)
**Notes:** Proves the actual data path; widget is throwaway, deleted when Phase 10 adds real pages.

---

## Design tokens

| Option | Description | Selected |
|--------|-------------|----------|
| Semantic tokens | Dark palette → shadcn semantic roles (--background, --card, --primary, --destructive...) via @theme; components theme automatically; destructive ready for Phase 11. | ✓ |
| Raw color tokens | Three hex values as named tokens applied manually; shadcn won't auto-theme. | |

**User's choice:** Semantic tokens (research/standard shadcn pattern)
**Notes:** `--destructive` included up front so Phase 11 live-money buttons inherit it.

---

## shadcn set

| Option | Description | Selected |
|--------|-------------|----------|
| Just what the shell needs | Install button/input/label/card/sonner now; later pages add components via CLI as needed. | ✓ |
| Baseline kit upfront | Broad set installed now; some may go unused / need re-theming. | |

**User's choice:** Just what the shell needs (lean)
**Notes:** Keeps Phase 9 lean; avoids unused components.

---

## Claude's Discretion

- `frontend/` internal layout, TS config, lint/format setup.
- Which specific Phase-8 read endpoint backs the D-08 probe.
- Exact `staleTime`, retry policy, per-view `refetchInterval` values (within research frame).
- Precise semantic-token hex→role assignments and derived shades.
- Nav skeleton links disabled vs hidden-until-built.
- Pinned minor/patch versions (majors locked).

## Deferred Ideas

None — discussion stayed within phase scope. Live-money UI, optimistic-update discipline,
react-hook-form + zod, and the actual pages remain assigned to Phases 10–11; legacy-route /
SSE / Tailwind-CLI removal remains Phase 12.
</content>
