# Project Research Summary

**Project:** Telebot v1.2 — React/Vite dashboard rewrite
**Domain:** Internal single-operator live-money trading control surface (React 19 + Vite SPA over same-origin FastAPI JSON API)
**Researched:** 2026-06-01
**Confidence:** HIGH

## Executive Summary

This is a substrate migration, not a product expansion. The goal is to replace a FastAPI + HTMX + Jinja2 dashboard with a React 19 + Vite SPA, eliminating a well-understood class of refresh-race bugs (input clobbering, flicker, broken modal mounting) that recurred throughout v1.1. The rewrite is bounded to parity plus one deliberate upgrade — SEED-001 settings UX — and must leave the bot core (executor, trade_manager, db, mt5_connector) completely untouched. All four research streams agree on this scope discipline: adding trading capability or new analytics here is an explicit anti-feature.

The recommended approach builds in four phases: (A) JSON API foundation, curl/pytest-testable before any UI exists; (B) SPA scaffold with auth, CSRF, design tokens, and TanStack Query wired up but no pages yet; (C) page-migration waves from lowest to highest risk — analytics pilot first, live-money mutation pages last; (D) parallel-run cutover with page-by-page HTMX decommission gated on MT5-demo-verified parity. The parallel-run architecture is structurally reversible at every step: legacy and SPA run simultaneously behind the same nginx instance sharing the same session cookie, and rolling back a page is one nginx edit.

The two dominant risks are both about the live-money mutation surface. First, optimistic UI updates must not be used on close/modify/partial-close/kill-switch — UI must only change state after the server confirms success from the MT5 connector, not on user intent. Second, the HTMX-coupled CSRF mechanism (HX-Request header check) will silently break for the SPA, and the naive fix is to delete the check entirely; the correct fix is to replace it with a proper double-submit cookie (X-CSRF-Token header) and add a regression test before any page goes live. Both must be established as conventions in Phase B before Phase C begins, so every migration wave inherits them.

---

## Key Findings

### Recommended Stack

All versions verified against npm registry on 2026-06-01. shadcn/ui now defaults to Tailwind v4 + React 19 — this is a hard compatibility boundary. Using Tailwind v3 in the SPA produces broken styling and OKLCH color mismatches. The backend already vendors Tailwind v4.2.2 CLI, so alignment is natural; the SPA uses @tailwindcss/vite (the Vite plugin form) instead of the standalone CLI. Vite 8 is the current supported line; Vite 7 is end-of-life. No tailwind.config.js, no postcss.config.js — v4 configuration lives entirely in CSS via @theme tokens.

TanStack Query v5 is the structural fix for the input-clobber bug: server state lives in a cache, form/UI state lives in React local state, and background refetch via refetchInterval never touches an open input or modal. This is an architectural guarantee, not a workaround. placeholderData: keepPreviousData replaces the existing _last_positions_by_account stale-while-revalidate hack. react-hook-form with uncontrolled inputs provides the same guarantee on the form side.

**Core technologies:**

| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| react / react-dom | 19.2.7 | UI runtime | Locked. Eliminates HTMX refresh-race bug class. |
| vite | 8.0.16 | Build tool + dev server | Current stable line; Vite 7 unsupported. Static dist/ — no Node runtime in prod. |
| @vitejs/plugin-react | 6.0.2 | React Fast Refresh + JSX | v6 pairs with Vite 8; Oxc-based (Babel-free, faster). |
| tailwindcss + @tailwindcss/vite | 4.3.0 | Styling | Locked. Mandatory for shadcn; backend already on v4. No tailwind.config.js. |
| shadcn CLI | 4.10.0 | Component scaffolding | Owns source in src/components/ui/; targets Tailwind v4 + React 19 by default. |
| @tanstack/react-query | 5.100.14 | Server-state + live polling | The structural fix. refetchInterval + placeholderData: keepPreviousData. |
| react-router-dom | 7.16.0 | Client-side routing | Declarative mode (createBrowserRouter) for 9-view flat SPA. |
| react-hook-form + zod + @hookform/resolvers | 7.77.0 + 4.4.3 + 5.4.0 | Forms + validation | Uncontrolled inputs (refetch-immune); zod mirrors server hard-caps for instant feedback. |
| sonner | 2.0.7 | Toast notifications | shadcn current default; replaces hand-rolled _render_toast_oob OOB-swap hack. |
| recharts | 3.8.1 | Charting (analytics only) | shadcn Chart wrapper; React 19 peer dep verified. Defer install to analytics wave. |
| typescript | 6.0.3 | Type safety | Catches API-shape drift between FastAPI JSON layer and SPA at compile time. |

**What NOT to use:** Next.js/Remix (Node runtime in prod), Tailwind v3 (shadcn incompatibility), Redux/Zustand for server data (double-caches server state), Axios (native fetch sufficient), localStorage/JWT tokens (XSS risk, locked decision), WebSocket (no bidirectional need), SSE for v1.2 (polling meets one-operator needs).

### Expected Features

This is a parity rewrite. Nearly everything is P1 — prioritization is about ordering, not dropping features. The one scope expansion is SEED-001 settings UX, which rides the rewrite at no additional blast-radius cost.

**Must have — parity (table stakes):**
- All 9 views re-implemented: overview, positions, history, signals, staged, settings, analytics, login, root redirect
- Live positions/overview refresh with no input/modal clobbering (TanStack Query refetchInterval + local form-state separation)
- Close / modify SL+TP / partial close with confirm dialog, disabled-while-pending, pending row state, rollback on error, sonner toast
- Two-step kill switch (preview count -> confirm) with resume; confirm disabled-while-pending
- Position drilldown (fill history, signal attribution, live P/L) — per-row expanded state immune to background refetch
- History and analytics filters reflected in URL (React Router search params)
- Settings: per-account tabs, two-step confirm with diff + dry-run, audit timeline, revert, zod mirror of server hard-caps, sonner toasts, per-field help/tooltips, SEED-001 copywriting
- Session-cookie auth, double-submit CSRF on all mutations, global 401 -> login redirect
- Responsive desktop table + mobile card layouts on all list pages
- TRADING PAUSED banner; DRY-RUN/LIVE/DISABLED status indicators

**Should have — UX upgrades riding the rewrite:**
- Viewport-level error toasts on broker rejections (biggest safety gain; replaces 12px inline span)
- isFetching subtle refresh indicator without full-table flicker
- disabled={isPending} on all destructive buttons (prevents double-fire)
- Bookmarkable filtered history/analytics URLs
- Live compounded-exposure warning in settings (risk_value x max_stages) — prevents 30%-per-signal footgun

**Defer to v2+:**
- New analytics, new trading capability, signal-log filtering, fixing v1.1 staged-data approximations, SSE/WebSocket push, multi-user/roles

**Two highest-complexity pages:**
- Positions — live table + 4 destructive actions + drilldown + edit modal; canonical no-clobber test surface
- Settings — SEED-001 forms + zod + dynamic per-account/mode caps + two-step confirm + audit + revert + toasts + tooltips

### Architecture Approach

The dashboard already runs in-process with the bot (init_dashboard() injects live _executor/_settings/_notifier). JSON routes call the same live objects with zero IPC — "don't touch bot core" is trivially satisfied because the JSON API is purely a serialization change: wrap the existing dict-returning helpers in Pydantic v2 response models. No logic moves, no new imports land in executor.py, trade_manager.py, db.py, or mt5_connector.py.

The JSON API mounts as APIRouter(prefix="/api/v2") added to the existing app in one line. Auth reuses the telebot_session httpOnly cookie unchanged; _verify_auth already 401s on /api/-prefixed paths. CSRF replaces the HTMX-coupled HX-Request check with a double-submit cookie: a non-httpOnly telebot_csrf cookie the SPA reads and echoes as X-CSRF-Token header, verified server-side with secrets.compare_digest.

nginx during parallel-run: /api/ proxies to uvicorn, /app/ serves the SPA bundle with try_files .../app/index.html fallback, and / continues proxying all legacy HTMX routes to uvicorn. The catch-all fallback must NOT be try_files during parallel-run or it swallows still-HTMX routes, the API, SSE, and /login. Recommended serving mechanism for v1.2: uvicorn StaticFiles mount at /app (simpler, no Docker volume change).

**Major components:**

| Component | Responsibility | Status |
|-----------|---------------|--------|
| api/ package (~10 modules) | JSON contract: auth, positions, accounts, history, signals, stages, analytics, settings, actions, meta | New |
| api/schemas.py | Pydantic v2 response models wrapping existing dict helpers | New |
| api/deps.py | require_user (reuses _verify_auth 401 branch), verify_csrf_token (double-submit) | New |
| frontend/ Vite project | React 19 SPA: 9 views, TanStack Query, shadcn/ui, Tailwind v4, react-hook-form | New |
| dashboard.py | Legacy HTMX routes (shrinks to nothing in Phase D); receives include_router + accessor functions | Modified |
| nginx/telebot.conf | + /app/ SPA location; + /api/v2/auth/login rate-limit; SSE block preserved until HTMX gone | Modified |
| Dockerfile | + Node spa-build stage; + COPY --from=spa-build; Tailwind CLI stage removed in Phase D | Modified |
| Bot core | executor, trade_manager, db, mt5_connector — untouched | Untouched |

### Critical Pitfalls

1. **No optimistic updates on money operations** — onSuccess (server-confirmed) is the only trigger that clears/updates UI for close/modify/partial-close/kill-switch. An optimistic clear before broker confirmation leaves the operator believing a position is closed when it is still live. Use useMutation with row/modal in pending state until onSuccess; onError keeps the modal open with typed values preserved and surfaces result.error inline.

2. **CSRF will silently break for the SPA** — _verify_csrf requires HX-Request header; the SPA cannot send it; the naive fix is deleting _verify_csrf. Replace with double-submit telebot_csrf cookie + X-CSRF-Token header using secrets.compare_digest. Add a regression test asserting POST without the header returns 403 before any page goes live.

3. **Partial close is non-idempotent at the server** — close_partial computes pos.volume * percent/100 from live volume, so a double-fire closes 50% then 50%-of-remainder = 75% total. Fix: switch to absolute target volume + a client request-id for server-side deduplication. disabled={isPending} is the minimum mitigation.

4. **nginx try_files catch-all must NOT cover the whole origin during parallel-run** — the SPA catch-all applies only to the /app/ prefix. The proxy_buffering off / proxy_read_timeout 86400s SSE directives must be preserved until HTMX overview/staged are decommissioned.

5. **Number formatting and precision must stay server-side** — XAUUSD pip-size has already bitten this project (quick task 260501-i7u). The JSON API must return both display-ready formatted strings and machine-precise numeric values. The SPA submits the exact server-provided numeric value for mutations, never a re-rounded JS value. Timestamps: ISO-8601 with UTC offset; date-range filtering stays server-side.

---

## Implications for Roadmap

All four research streams converge on the same four-phase structure. The ordering is dependency-driven: JSON API gates everything; auth/CSRF conventions must precede page migration; read-only pages validate the pipeline safely; live-money pages come last and are decommissioned only after MT5-demo-verified parity.

### Phase A: JSON API Foundation

**Rationale:** Everything else is blocked on this. The computation already exists in dashboard.py helpers; this is only a serialization change. Must be independently testable via curl/pytest before any UI exists.

**Delivers:**
- api/ package with APIRouter(prefix="/api/v2") mounted on the existing app (one line in dashboard.py)
- All read endpoints wrapped in Pydantic v2 response models (accounts, positions, history, signals, stages, analytics, overview meta)
- All mutation endpoints returning structured JSON, not toast HTML (close, modify-levels, close-partial, emergency preview/close, resume, trading-status)
- deps.py: require_user + verify_csrf_token (double-submit cookie + X-CSRF-Token, secrets.compare_digest)
- auth.py: JSON login/logout/me/csrf + telebot_csrf non-httpOnly cookie
- Standardized error envelope: bare resource on success, {error: {code, message, fields}} on failure
- Timestamp contract: ISO-8601 with UTC offset + configured display zone in every response
- Number contract: display-ready formatted strings + machine-precise numeric values in every response
- Accessor functions in dashboard.py (get_executor(), get_settings(), get_notifier()) so api/ never imports rebindable globals
- Regression test: POST to any mutation without X-CSRF-Token returns 403

**Bot core:** Zero imports changed in executor/trade_manager/db/mt5_connector
**Avoids:** CSRF breakage (Pitfall 4), number precision (Pitfall 7), timezone bugs (Pitfall 8)
**Research flag:** Standard patterns — no additional research needed.

---

### Phase B: SPA Scaffold + Auth + Design System

**Rationale:** Establishes the conventions every page migration wave inherits. Auth, CSRF header injection, 401 redirect, QueryClient defaults, and design tokens must be in place before any page is built.

**Delivers:**
- frontend/ Vite 8 + React 19 + Tailwind v4 (@tailwindcss/vite) + shadcn init at correct versions
- Dark palette tokens (#252542/#1a1a2e/#0f0f1a) as @theme CSS variables in src/index.css
- Fetch wrapper (relative URLs, credentials: "same-origin", X-CSRF-Token on mutations, throws HttpError(status) on non-2xx)
- QueryClient with global QueryCache/MutationCache onError: 401 -> window.location.assign("/app/login")
- Login view (JSON POST /api/v2/auth/login; reads/submits telebot_csrf cookie)
- /app/me boot guard (SPA calls GET /api/v2/auth/me on startup; 401 -> login)
- App shell + createBrowserRouter under /app/*; vite.config.ts with base: "/app/", @tailwindcss/vite plugin, @/ alias, dev proxy (/api, /login, /logout -> FastAPI)
- uvicorn StaticFiles mount at /app (or nginx alias — must be locked here per Open Question 3)
- Verify gate: login works in vite dev with cookie intact; authed shell renders; expired session redirects to login exactly once

**Avoids:** Dev proxy/401 loop (Pitfall 3), CSRF dropped (Pitfall 4), Tailwind/shadcn version mismatch (Pitfall 9), Vite base path (Pitfall 10)
**Research flag:** Standard patterns — no additional research needed.

---

### Phase C: Page Migration Waves

**Rationale:** Ordered by blast radius — lowest to highest. Each wave: implement fetch hook + view + verify against the live legacy page before proceeding. The "no optimistic updates on money ops" and disabled={isPending} conventions from Phase B apply to every mutation surface.

**Wave C1 — Analytics (read-only pilot):**
/app/analytics — useQuery, recharts via shadcn Chart, range/source filter state in URL search params. No mutations, no live-money risk. Validates the full API + SPA + auth + nginx pipeline. Cut over only after numbers verified against /analytics on live data.

**Wave C2 — Read-only pages:**
/app/signals (on-mount fetch, LOW complexity), /app/history (filter state in URL, queryKey: ['history', filters], placeholderData: keepPreviousData), /app/staged (live refetchInterval: 2000-3000, elapsed timer display). Verify against legacy page numbers before decommissioning each.

**Wave C3 — Live polling pages:**
/app/overview (composes positions table + stages card + kill-switch entry + TRADING PAUSED banner, refetchInterval: 3000) and /app/positions (full positions table, per-row drilldown state, edit-levels modal, 3s polling). Shared components built here (positions table, pending-stages card, edit-levels modal) reused by overview. Canonical no-clobber verification: open drilldown + wait two refetch cycles; open edit-levels modal + wait two cycles; verify state unaffected.

**Wave C4 — Live-money mutation pages + settings:**
Full destructive action surface (close, modify SL/TP, partial close with absolute volume + request-id, kill switch confirm). /app/settings (SEED-001: zod mirror of hard-caps, dynamic caps per risk_mode + max_lot_size per account, two-step confirm rendering diff JSON from POST .../validate, audit timeline, revert, sonner toasts, per-field tooltips, live compounded-exposure computation). Each must pass MT5-demo broker-reject QA and the "looks-done-but-isn't" checklist before HTMX twin is decommissioned.

**Avoids:** Optimistic-clear (Pitfall 1), double-fire (Pitfall 2), stale cache (Pitfall 6), float/precision (Pitfall 7), timezone (Pitfall 8), parallel-run drift (Pitfall 11)
**Research flags:**
- C4 (partial-close idempotency): storage mechanism needs a decision before C4 planning (Open Question 4)
- C4 (partial-close API shape): switching from percent to absolute-volume changes the endpoint signature; needs an explicit design note before coding

---

### Phase D: Parallel-Run Cutover + HTMX Decommission

**Rationale:** Final gate is MT5-demo-verified parity, not "looks done." Decommissioning is one route deletion per page, each gated on a short parity checklist.

**Delivers:**
- Per page: legacy HTMX route deleted + template removed + optional 301 redirect from /page to /app/page
- After all pages cut: /stream SSE endpoint deleted; nginx proxy_buffering off / proxy_read_timeout 86400s removed
- Legacy Tailwind CLI Dockerfile stage removed; templates/ directory removed
- Legacy /login decommissioned after JSON login is the sole path; telebot_login_csrf cookie decommissioned
- dashboard.py reduced to wiring (accessors + include_router + shared middleware)

**Decommission gate per page:** SPA numbers match legacy page on live data; destructive actions verified against MT5 demo; CSRF regression test passes; HTMX twin kept until gate is cleared.
**Avoids:** nginx catch-all breaking live routes (Pitfall 5), premature decommission (Pitfall 11)
**Research flag:** No research needed — discipline is the constraint.

---

### Phase Ordering Rationale

- Phase A must precede all others: every page depends on the JSON API contract; the contract also locks number-formatting and timestamp conventions that prevent precision bugs project-wide.
- Phase B must precede Phase C: auth, CSRF, 401 handling, and QueryClient defaults are inherited by every page; building them after 9 pages exist means fixing across 9 views.
- Phase C waves ordered read-only -> live-data -> live-money to minimize blast radius. Analytics pilot validates the full stack integration in the safest possible context.
- Positions (C3) and Settings (C4) are the two HIGH-complexity pages; they land in the later waves deliberately. Building shared components in C3 means Overview in C3 composes them. Settings in C4 gets the fully-established mutation safety pattern.
- Phase D is last: parallel-run is the safety mechanism for the entire migration; decommissioning removes it page-by-page only after each page passes the demo gate.

### Research Flags

**Phases needing deeper planning research:**
- Phase A — idempotency storage (Open Question 4): needs a concrete decision before Phase A coding
- Phase C4 — partial-close API shape change: needs an explicit design note before coding

**Phases with standard, well-documented patterns (skip research-phase):**
- Phase A: FastAPI APIRouter + Pydantic v2 + double-submit CSRF
- Phase B: Vite 8 + React 19 + Tailwind v4 + TanStack Query scaffold
- Phase C1-C2: pure useQuery + URL filter state
- Phase D: nginx config edits + file deletion

---

## Open Questions the Roadmapper Must Resolve

1. **Exact CSRF cookie and header names** — ARCHITECTURE.md proposes telebot_csrf (cookie, non-httpOnly) + X-CSRF-Token (header). Must be locked before Phase A deps.py is written so the Phase B fetch wrapper and the Phase A regression test agree. Verify against dashboard.py:128-135 and config.py for any existing cookie names that must not collide.

2. **SPA URL strategy: /app/ subpath vs whitelisted legacy-path redirects** — ARCHITECTURE.md recommends /app/ subpath. This drives vite.config.ts base, the nginx location /app/ block, all createBrowserRouter route paths, and the redirect strategy for legacy paths. Must be locked at Phase B scaffold start; changing it later requires rebuilding the bundle and rewriting nginx.

3. **Serving mechanism: uvicorn StaticFiles mount vs nginx alias + volume** — ARCHITECTURE.md recommends uvicorn StaticFiles (simpler, no Docker volume change). Determines how the Dockerfile COPY --from=spa-build step lands and what the nginx /app/ block does. Must be decided before Dockerfile and nginx config are modified in Phase B.

4. **Idempotency storage for money-op deduplication** — In-memory dict (simple, lost on restart), Redis (already on VPS — check docker-compose.yml for existing telebot/Redis wiring), or PostgreSQL (no new dependency). Affects actions.py design in Phase A. The choice determines whether idempotency keys survive a process restart during an in-flight request.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against npm registry 2026-06-01. shadcn v4/React 19 compatibility verified against official shadcn docs. Version compatibility matrix (shadcn/Tailwind, plugin-react/Vite, resolvers/zod) verified. |
| Features | HIGH | Derived directly from dashboard.py routes + templates + SEED-001 seed doc. TanStack Query v5 patterns verified via Context7. |
| Architecture | HIGH | Grounded in actual repo (dashboard.py, bot.py, nginx/telebot.conf, Dockerfile, config.py). In-process coupling verified at bot.py:409-420. Auth/CSRF/401 branch logic verified in dashboard.py:99-135. |
| Pitfalls | HIGH/MEDIUM | FastAPI/auth/nginx/Vite specifics: HIGH (verified against this codebase). Live-money optimistic-update failure modes: MEDIUM (synthesized from codebase behavior + TanStack Query official defaults — sound reasoning, not empirically tested yet). |

**Overall confidence:** HIGH

### Gaps to Address

- **Idempotency storage** (Open Question 4): check docker-compose.yml for existing telebot/Redis wiring before committing. If Redis is already in-network, it is the cleanest choice with no new infrastructure.
- **Exact v1.0 CSRF cookie name** (Open Question 1): dashboard.py:142 uses telebot_login_csrf for the login form. Verify the proposed telebot_csrf API mutation cookie does not collide with any existing cookie before Phase A.
- **_verify_auth path-prefix check**: the existing code branches on /api/ prefix. Confirm /api/v2/ is caught by this check (it should be, as a prefix match) so Phase A routes automatically get 401 behavior without server changes.

---

## Sources

### Primary (HIGH confidence)
- dashboard.py (1,510 lines) — all routes, auth logic (_verify_auth, _verify_csrf), mutation endpoints, helpers (_get_all_positions, _get_accounts_overview, _enrich_stage_for_ui), _last_positions_by_account stale cache, _render_toast_oob, validate_settings_form, _SETTINGS_HARD_CAPS_INT
- bot.py:409-420 — init_dashboard(), in-process coupling of live objects
- nginx/telebot.conf — existing proxy + SSE directives + login rate-limit
- Dockerfile — existing multi-stage build (Tailwind CLI stage)
- config.py — session_cookie_secure, timezone, SessionMiddleware config
- .planning/PROJECT.md v1.2 section — locked stack decisions, parallel-run strategy, anti-Next.js/anti-localStorage rationale
- .planning/seeds/SEED-001-settings-ux-polish.md — toasts, inline help, copywriting requirements; hard-cap source-of-truth
- npm registry (2026-06-01) — exact latest versions for all SPA dependencies
- https://ui.shadcn.com/docs/tailwind-v4 — shadcn defaults to Tailwind v4; v3 backward-compatible only for existing apps
- https://ui.shadcn.com/docs/installation/vite — Vite + Tailwind v4 setup
- https://vite.dev/releases — Vite 8 current stable; v7 unsupported
- https://tanstack.com/query/latest/docs/framework/react/guides/polling — refetchInterval semantics
- https://tanstack.com/query/latest/docs/framework/react/guides/important-defaults — staleTime:0, refetchOnWindowFocus, mutations do not auto-invalidate
- https://fastapi.tiangolo.com/tutorial/bigger-applications/ — APIRouter + include_router + response_model

### Secondary (MEDIUM confidence)
- Double-submit-cookie CSRF for cookie-auth SPAs — OWASP CSRF cheat-sheet pattern; consistent with this codebase's existing double-submit on /login
- TanStack Query QueryCache/MutationCache global onError 401 handler — documented pattern verified via Context7
- https://github.com/tailwindlabs/tailwindcss/discussions/17137 — Tailwind v4 + Radix transparent dropdown/select regression; documented workaround exists

### Memory context
- project_lot_semantics.md — fixed_lot risk_value is TOTAL across max_stages, not per-trade (operator-confirmed 2026-05-01); SEED-001 settings copywriting must not contradict this

---

*Research completed: 2026-06-01*
*Ready for roadmap: yes*
