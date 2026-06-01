# Pitfalls Research — Telebot v1.2 (React/Vite dashboard rewrite)

**Domain:** React 19 + Vite SPA added over a live-money trading FastAPI backend (Telegram→MT5 bot), replacing an HTMX dashboard via parallel-run + page-by-page cutover behind nginx.
**Researched:** 2026-06-01
**Confidence:** HIGH for the FastAPI/auth/nginx/Vite specifics (verified against this repo's `dashboard.py`, `nginx/telebot.conf`, `config.py`, and current Vite/TanStack/shadcn docs); MEDIUM for the live-money client-state failure modes (synthesized from this codebase's existing behavior + TanStack Query official defaults).

> Scope note: this file replaces the prior (Apr-18) v1.1 PITFALLS.md, which covered the staged-entry *backend* milestone. Those backend pitfalls are unchanged and still tracked in STATE.md. Everything below is about the React-SPA-over-live-trading *migration* only.

---

## Critical Pitfalls

These are the non-negotiables: a destructive action that silently no-ops/double-fires, or an auth/CSRF hole opened by going SPA. Both can lose real money.

### Pitfall 1: Optimistic UI clears a destructive action before the server confirms it

**What goes wrong:**
The "Close", "Modify SL/TP", "Partial close", or "Kill switch" button updates the UI (removes the row, shows "Closed", closes the modal) the instant it is clicked, using TanStack Query's optimistic-update pattern — before the FastAPI endpoint has confirmed the MT5 broker accepted the order. The current backend (`close_position`, `modify_levels`, `emergency_close`) only mutates DB/state after `connector.close_position`/`modify_position` returns `result.success`. If the SPA optimistically assumes success, a broker rejection, REST timeout, or 403/401 leaves the operator believing a position is closed when it is still live and exposed.

**Why it happens:**
Optimistic updates are the idiomatic "snappy UI" pattern in React/TanStack Query and are heavily recommended in tutorials. They are correct for low-stakes UIs (a todo toggle) but wrong for irreversible money operations. The HTMX dashboard never had this gap because it only swapped DOM *after* the server response arrived — the server response *was* the UI. Moving to a client-state model reintroduces the gap between "user intent" and "server truth."

**How to avoid:**
- Hard rule for all live-money mutations: **server-confirmed success is the only thing that clears/updates the UI.** No optimistic updates on close / modify / partial-close / kill-switch. Use `useMutation` with the row/modal staying in a pending state until `onSuccess`, then `invalidateQueries(['positions'])` to refetch ground truth from MT5.
- `onSuccess` trusts the *server's* returned state (re-fetch positions), not a locally-constructed optimistic value.
- On `onError`, surface the broker error inline (the current `modify_levels`/`close_partial` already return `result.error`) and keep the user's typed values — mirror the existing `_render_edit_modal_with_error` behavior.
- Shape the JSON API to return a structured result (`{success, error, ticket, new_sl, new_tp, closed_volume, price}`) so the SPA can render confirmed truth.

**Warning signs:**
Row disappears instantly on click then reappears on next poll; a toast says "Closed #X" but the position is still in MT5; QA on the demo account sees "success" UI during a deliberately-induced broker reject.

**Phase to address:** Page-migration wave that ports positions + kill switch (the live-money write pages). Establish the "no optimistic updates for money ops" rule in the SPA-scaffold phase as a documented mutation convention so every later wave inherits it.

---

### Pitfall 2: Double-fire — same Close/kill-switch request sent twice (no idempotency, button not disabled-while-pending)

**What goes wrong:**
Operator double-clicks "Close" (or the network is slow and they click again), or a React re-render re-triggers the handler, and two `POST /api/close/{account}/{ticket}` fire. For a full close this is usually benign (second close 404s on an already-closed ticket), but **partial close is not idempotent**: two `close-partial` at 50% close 50% then 50%-of-the-remainder = 75% total. The kill switch double-firing re-runs `emergency_close()` and re-sends the Discord kill-switch alert. There is no server-side idempotency key today — every POST executes.

**Why it happens:**
SPA buttons don't auto-disable. HTMX implicitly serialized this (the element was busy during the swap; `hx-disabled-elt` was idiomatic). In React you must explicitly disable on `isPending`. Partial-close-by-percent is inherently non-idempotent because it's relative to *current* volume (`close_partial` computes `pos.volume * percent/100` from live volume).

**How to avoid:**
- **Disable the button while the mutation is pending** (`disabled={mutation.isPending}`) for every destructive button. Single highest-value, lowest-cost mitigation.
- **Idempotency for non-idempotent ops:** generate a client request-id (UUID) per user-initiated action, send it as a header, have FastAPI dedupe (return prior result for a repeated id within a short TTL). Change partial-close to send an **absolute target volume** (the lot value the user confirmed), not a relative percent, so a replay is a no-op rather than compounding.
- Kill switch: keep the existing two-step confirmation (`/api/emergency-preview` → `/api/emergency-close`); `emergency_close()` is largely safe to re-call (it closes whatever is open). Disable confirm on pending; gate re-enable on server response.

**Warning signs:**
Partial close removes more than configured; duplicate Discord alerts; two MT5 close deals in history for one click; demo QA double-clicking produces 75% closes.

**Phase to address:** SPA-scaffold phase (disabled-while-pending mutation wrapper + request-id convention); positions/kill-switch migration wave (apply; switch partial-close to absolute volume).

---

### Pitfall 3: Session cookie not sent through the Vite dev proxy → 401 loops and dev that can't reproduce prod auth

**What goes wrong:**
In `vite dev` the SPA runs on `localhost:5173` and calls FastAPI. If requests go cross-origin to `:8080`, the `telebot_session` cookie (SameSite=Lax, httpOnly) is not attached, every API call 401s, the SPA bounces to `/login`, login "succeeds" but the cookie still isn't reused → infinite redirect loop. Developers then "fix" it by weakening cookie attributes or moving the token to `localStorage` — exactly what this project forbids.

**Why it happens:**
Browsers gate cookies on origin/SameSite. The prod design is *same-origin behind nginx* (cookie just works); dev with two ports is *not* same-origin, so the prod assumption silently breaks only in dev, tempting a wrong fix.

**How to avoid:**
- Configure Vite `server.proxy` so `/api`, `/login`, `/logout`, `/stream`, `/static` proxy to FastAPI through the **same origin** (`localhost:5173`). The SPA then uses relative URLs and the cookie is sent automatically. Do **not** add credentialed-wildcard CORS as a workaround.
- Always send `credentials: 'include'` (fetch) / `withCredentials: true` (axios).
- Keep production strictly same-origin: nginx serves the built SPA and proxies `/api` to FastAPI under one host. No second origin, no CORS layer, no JS-readable token. This preserves the existing httpOnly + SameSite=Lax + `session_cookie_secure` model in `config.py`/`dashboard.py` unchanged.

**Warning signs:**
Login works but the next API call 401s; `Set-Cookie` present but cookie absent on later requests in devtools; redirect loop `/login → /overview → /login`; a PR adding CORS middleware or `localStorage.setItem('token', ...)`.

**Phase to address:** SPA-scaffold + auth phase — define the dev proxy and auth/fetch wrapper once.

---

### Pitfall 4: CSRF protection silently dropped or weakened when leaving HTMX

**What goes wrong:**
The current CSRF defense (`_verify_csrf`) requires every state-changing request to carry an `HX-Request` header (HTMX sets it automatically; cross-origin forms can't). When the SPA replaces HTMX those requests no longer send `HX-Request`, so either (a) every mutation 403s and a dev "fixes" it by deleting `_verify_csrf` (removing CSRF entirely), or (b) the SPA hard-codes `HX-Request: true` (works but leaves a lying legacy contract). Login uses a *different* mechanism (double-submit cookie on `/login` only) which must also be preserved.

**Why it happens:**
The CSRF scheme is header-presence-based and tightly coupled to HTMX's auto-header. It's invisible until the first SPA mutation 403s, and the fastest "fix" is to remove the dependency.

**How to avoid:**
- Keep a deliberate custom-header CSRF check (genuinely sufficient with SameSite=Lax cookies for same-origin JSON, since cross-site attackers can't set custom headers). Replace the `HX-Request` check with an explicit app header (e.g. `X-Requested-With: telebot-spa`) that the SPA fetch wrapper always sends, and update `_verify_csrf` to accept it. Do **not** delete `_verify_csrf`.
- Keep `SameSite=Lax` (already set) — the real anti-CSRF backbone for the session cookie; the header check is defense-in-depth.
- Preserve the `/login` double-submit-cookie flow exactly; the SPA login page must read/submit `csrf_token` the same way.
- Add a regression test asserting a POST without the custom header is rejected 403, so a later refactor can't silently drop it.

**Warning signs:**
All mutations 403 right after a page is ported; a diff removing `_verify_csrf` from an endpoint's `Depends`; mutations succeeding from a header-less curl (CSRF is gone).

**Phase to address:** JSON-API phase (server-side header check + regression test); SPA-scaffold phase (fetch wrapper always sends it).

---

### Pitfall 5: nginx SPA catch-all swallows legacy HTMX routes / the API / SSE during parallel-run

**What goes wrong:**
Cutover is *page-by-page*: for weeks some routes are HTMX, some React. A naïve SPA deploy adds `try_files $uri /index.html;` at `location /`, which intercepts `/overview` (still HTMX), `/api/...`, `/stream` (SSE), `/login`, `/static/css/...` — returning the SPA shell for everything. Legacy pages render blank, API calls return HTML, SSE dies, and the operator's *live control surface* is dead mid-migration. The current `nginx/telebot.conf` proxies `location /` straight to `telebot:8080`; the migration must carve routes carefully, not flip the default.

**Why it happens:**
SPA hosting guides universally recommend the `try_files … /index.html` fallback. That advice assumes the SPA owns the whole origin — false during a page-by-page parallel run.

**How to avoid:**
- Route explicitly, not by catch-all. Keep `/api/`, `/login`, `/logout`, `/stream`, `/static/` proxied to FastAPI. Add SPA `location` blocks **only for routes already cut over**; widen the SPA footprint as each page is verified.
- For SPA deep-links (e.g. reloading `/analytics`), serve `index.html` *only under the SPA's own path* (host the SPA under a prefix like `/app/` during parallel-run, or whitelist cut-over paths) so a deep-link 404 doesn't leak into still-HTMX routes.
- Preserve the existing SSE block (`proxy_buffering off; proxy_read_timeout 86400s`) for `/stream` — easy to lose when restructuring.
- Keep the `location = /login` rate-limit block intact.
- Treat nginx as a reviewed artifact per cutover step, with rollback (the point of parallel-run is reversibility).

**Warning signs:**
A still-HTMX page renders the SPA shell or blank; `/api/*` returns `<!doctype html>`; SSE stops (overview/staged stop live-updating); direct-loading `/analytics` 404s or shows the wrong app.

**Phase to address:** Parallel-run/cutover phase owns this; SPA-scaffold phase decides the SPA URL strategy (subpath vs whitelisted paths) up front because it dictates nginx + Vite `base`.

---

### Pitfall 6: TanStack Query stale cache / refetch-on-focus shows the wrong position or price

**What goes wrong:**
Two failure modes:
1. **Stale cache shows wrong truth.** TanStack Query serves cached data while revalidating. After a close/modify, if the mutation doesn't invalidate `['positions']` (mutations do **not** auto-invalidate — verified in docs), the table shows a closed position as still open, or stale SL/TP. The operator could act on a stale row (close a position that's already gone, modify SL on the wrong ticket).
2. **`refetchOnWindowFocus` (default ON) doesn't fire trades**, but it *does* cause surprise background refetches. Combined with an open "Edit levels" modal it can race: the list refetches and re-orders/re-keys rows under the modal, so confirm targets a different ticket than displayed — the exact "modal mounting / input clobbering" class this rewrite exists to kill, recreated at the data layer.

**Why it happens:**
TanStack defaults: `staleTime: 0` (everything stale immediately), `refetchOnWindowFocus: true`. Defaults optimize freshness for read UIs, not stability for a money-control surface.

**How to avoid:**
- After every mutation, `invalidateQueries(['positions'])` (+ derived keys) — never hand-patch the cache for money state; refetch MT5 truth.
- Use **stable query keys keyed by `{account, ticket}`** and key the modal to a specific ticket object, not a list index, so a background refetch can't swap what the modal acts on.
- Set a small `staleTime` (~ the existing 2–3s cadence) so focus-refetch doesn't hammer the MT5 REST bridge; consider `refetchOnWindowFocus: false` on the positions/edit surface specifically (keep it on for read-only analytics if desired).
- Keep the existing SSE `/stream` as the live-update transport (positions/accounts/pending-stages already flow over it at 2s) and feed SSE into the query cache via `setQueryData`/invalidation. Reuses the proven backend; avoids N polling timers.

**Warning signs:**
A closed position lingers; SL shown ≠ SL in MT5; opening the edit modal, waiting, then confirming hits a different ticket; MT5 bridge load spikes when the operator alt-tabs.

**Phase to address:** SPA-scaffold phase (money-safe QueryClient defaults); positions migration wave (invalidate-on-mutation, ticket-keyed modals).

---

### Pitfall 7: Float rounding / number formatting on lots and prices (XAUUSD pip-size history)

**What goes wrong:**
Lots/prices reformatted in JS. JS has only IEEE-754 doubles; naïve `toFixed`/`parseFloat` round-trips produce `0.30000000000000004`-style values or wrong rounding. For lots this can submit an invalid volume (broker rejects, or rounds against the operator); XAUUSD precision has *already bitten this project* (quick task 260501-i7u "Fix XAUUSD pip-size"; `_enrich_stage_for_ui` hard-codes `*100` pip math). Displaying a price at the wrong decimal precision, or parsing a localized number (comma decimal) wrong, makes the operator act on a misread value.

**Why it happens:**
The HTMX dashboard formatted numbers *server-side* in Python/Jinja (`{:.2f}`), where the existing pip/precision logic lives. Moving rendering to the client duplicates that logic in JS and invites drift — especially per-symbol precision (XAUUSD vs FX pairs differ).

**How to avoid:**
- **Do math + rounding server-side; send display-ready and machine-precise values in JSON.** Return both the numeric value and a preformatted display string per field, computed by the same Python precision logic the bot already uses. The SPA should not re-derive pip distances or re-round lot volumes.
- Where the SPA must format, never round volumes/prices that get *submitted* — submit the exact server-provided value (ties into Pitfall 2's absolute volume).
- Force a fixed locale for number rendering (avoid browser-locale comma/period ambiguity).
- Add a parity test: for a fixed set of positions (incl. XAUUSD), SPA-rendered values must equal Python-rendered values.

**Warning signs:**
A lot value with a long float tail; XAUUSD price shown with FX precision (or vice-versa); pip distance differs between SPA and bot logs; broker rejects on "invalid volume."

**Phase to address:** JSON-API phase (formatting/precision stays server-side; shape payload accordingly); positions/staged migration waves verify parity.

---

### Pitfall 8: Timezone bugs in history / timestamps

**What goes wrong:**
The backend works in UTC (`datetime.now(timezone.utc)`) but the app has a configured display `timezone` (`config.py` `timezone: ZoneInfo`). If the SPA receives a naïve/UTC timestamp and renders with `new Date(...)` (browser-local zone), history rows, "elapsed" timers (`_enrich_stage_for_ui` computes elapsed in UTC), and date-range filters (`from_date`/`to_date` in `/history`) show/scope the wrong day. A "today" filter could miss or double-count trades around midnight.

**Why it happens:**
Server rendered with the configured zone before; the SPA defaults to browser-local. Date-only filter boundaries are the classic off-by-one-day bug.

**How to avoid:**
- Send timestamps as **unambiguous ISO-8601 with offset/UTC `Z`**, plus the intended display zone (the app `timezone`) so the SPA renders consistently regardless of browser location.
- Do date-range filtering server-side in the configured zone (it already accepts `from_date`/`to_date`); the SPA sends the same string format, server interprets boundaries — don't compute day boundaries client-side.
- Render history/elapsed with a date lib pinned to the configured zone, not raw `Date`.

**Warning signs:**
History timestamps shift by your UTC offset; "today" filter off by a day near midnight; staged elapsed timer hours off; a row under the wrong date.

**Phase to address:** JSON-API phase (timestamp contract); history migration wave verifies filter boundaries against known data.

---

### Pitfall 9: shadcn/ui + Tailwind version mismatch breaks the build

**What goes wrong:**
shadcn components are generated for a specific Tailwind major. This repo already moved to **Tailwind v4** (STATE.md, v1.1 Phase 05-05) and the stack is **React 19** — exactly shadcn's current default lane — but a stray non-canary `npx shadcn init` or a pasted v3-era component pulls v3 utility/`tailwind.config` assumptions and the build breaks or styles are wrong (e.g. the documented Tailwind-v4 + Radix dropdown/select transparency regression). React 19 also changed `forwardRef`, so older shadcn primitives may need the codemod. **Verified:** shadcn explicitly supports Tailwind v4 + React 19 (canary CLI); the v4+Radix transparency issue is documented.

**Why it happens:**
Most shadcn tutorials still assume Tailwind v3 + React 18; copy-pasting them onto a v4/19 base mismatches the generated CSS layer/config model.

**How to avoid:**
Pin Tailwind v4 + React 19 + the matching shadcn CLI from day one of the scaffold; generate components fresh (don't paste v3 snippets); apply the OKLCH dark-mode token migration (map the existing `#252542`/`#1a1a2e`/`#0f0f1a` palette into v4 tokens); verify a dropdown/dialog renders opaque before building pages on top.

**Warning signs:**
Build errors about `@tailwind`/`@config`; transparent popovers/selects; `forwardRef` type errors.

**Phase to address:** Phase 2 (scaffold) — first thing, before any page.

---

### Pitfall 10: Vite build pitfalls — env baked at build time + asset base path behind nginx

**What goes wrong:**
`VITE_*` env vars are inlined into the JS bundle **at build time** and are **public** (verified, Vite docs) — baking an API base URL means the same image can't move between dev/prod, and baking any secret leaks it to every browser. Separately, if the SPA is served under a subpath behind nginx (the recommended parallel-run strategy) but Vite `base` is left at `/`, all hashed assets 404 (requests go to `/assets/...` instead of `/app/assets/...`) and the SPA shows a blank page.

**Why it happens:**
Vite's build-time static replacement is invisible until prod; `base` defaults to `/` and only bites when served under a prefix.

**How to avoid:**
Use **relative same-origin API URLs** (no `VITE_API_URL` needed) so nothing environment-specific is baked. Never put secrets in `VITE_*`. Set Vite `base` to match the nginx serving path (e.g. `/app/`) so asset URLs resolve; keep `base` and the nginx `location` in lockstep. In Docker, build the static bundle in a build stage and have nginx serve it — no Node runtime in prod (matches the locked Vite-over-Next.js decision).

**Warning signs:**
Blank SPA with 404s on `/assets/*.js` in the network tab; a secret string findable in `dist/`; an image that works in dev but points at `localhost` in prod.

**Phase to address:** Phase 2 (scaffold: `base` + relative URLs) and Phase 4 (Docker/nginx deploy).

---

### Pitfall 11: Parallel-run drift + decommissioning a page before parity is verified

**What goes wrong:**
During the multi-week parallel run the backend computation feeds *both* the HTMX page and the React page. If a fix/behavior change lands on one path but not the other, the two dashboards disagree (drift) — and an operator may trust the wrong one for a live-money decision. Worse, decommissioning an HTMX page as soon as the React one "looks done" removes the safety net before the React version is verified against the MT5 demo for that page's live-money actions; a regression then has no fallback in prod.

**Why it happens:**
Two presentations of the same data, maintained in parallel, drift unless they share a single source of truth; "looks done" feels like done when there's schedule pressure.

**How to avoid:**
Refactor so both paths consume the **same JSON API / same Python computation** (the rewrite already does this — endpoints only change response shape), minimizing drift-prone logic. Per the locked strategy: **analytics (read-only) is the pilot**; a page's HTMX version is decommissioned **only after** its React replacement is verified against the MT5 demo, and the live-money pages (positions, kill-switch) cut over last with the most verification. Keep nginx-level reversibility at every step. Add a short parity checklist per page before flipping.

**Warning signs:**
HTMX and SPA show different numbers for the same account; a fix referenced in only one template/component; a decommission PR with no demo-verification note for that page.

**Phase to address:** Phase 4 (cutover) owns the discipline; Phase 1 (shared JSON API) structurally prevents most drift.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Optimistic updates on money mutations | Snappy UI | Silent no-op / phantom-closed positions → real loss | **Never** for close/modify/partial/kill-switch |
| Hard-code `HX-Request: true` in SPA to satisfy `_verify_csrf` | Mutations stop 403-ing immediately | Confusing legacy contract; CSRF semantics now lie | Only as a throwaway on day 1 of API work; replace with explicit header before any page cut over |
| `try_files /index.html` catch-all at `location /` | Standard SPA routing in one line | Swallows still-HTMX routes + API + SSE mid-migration | Only *after* full cutover, when SPA owns the origin |
| Token in `localStorage` to dodge the dev-proxy cookie problem | "Auth just works" in dev | XSS-exfiltratable creds; violates locked decision | **Never** |
| Re-derive pip/precision/rounding in JS | Fewer API fields | Drift from Python truth; XAUUSD precision regressions | Never for submitted values; display-only if parity-tested |
| Decommission HTMX page right after React "looks done" | Fewer things to maintain | No fallback when a live-money regression surfaces in prod | Only after demo-verified parity for that page |
| Disable `refetchOnWindowFocus` globally without thought | Stops surprise refetches | Stale read-only pages | Acceptable on money pages; keep judicious freshness on read-only analytics |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| FastAPI session cookie via Vite dev | Cross-origin `:5173`→`:8080`, cookie dropped, then weaken cookie/CORS | Vite `server.proxy` makes it same-origin; `credentials:'include'`; never credentialed-wildcard CORS |
| MT5 REST bridge (via connector) | Treating SPA "success" as broker success | Only `result.success` from the connector clears UI; surface `result.error` inline |
| SSE `/stream` behind nginx | Restructuring nginx loses `proxy_buffering off` / long read timeout → SSE dies | Preserve existing SSE location settings; test live-update after every nginx change |
| nginx during parallel-run | One catch-all routes everything to SPA | Explicit per-route proxy; widen SPA paths only as pages are verified |
| Docker build of the SPA | Baking dev API URL or secrets into the bundle (`VITE_*` is build-time + public) | Relative URLs (same-origin); never secrets in `VITE_*`; build with prod `base`/env |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Per-query polling timers replacing the single SSE stream | Many parallel REST calls to the MT5 bridge | Keep SSE as push transport; feed cache via `setQueryData` | As soon as multiple live tables each poll |
| `staleTime: 0` + `refetchOnWindowFocus` on positions | Refetch storm on every alt-tab; broker bridge load | Set `staleTime` ~ poll cadence; focus-refetch off on money pages | Single operator alt-tabbing frequently |
| Re-render whole positions table on every SSE tick | Flicker / lost focus in open modal (the bug we're fleeing) | Stable ticket keys; isolate modal state from list state | Immediately on first live tick with a modal open |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Moving auth token to `localStorage`/`sessionStorage` | XSS → full control-surface takeover (close all, kill switch) | Keep httpOnly session cookie; no JS-readable token (locked decision) |
| Dropping `_verify_csrf` to make SPA mutations work | CSRF can trigger close/kill-switch cross-site | Replace HTMX-header check with explicit SPA header; keep SameSite=Lax; regression-test rejection |
| `SameSite=None` / lowering `secure` to fix dev | Cookie sent cross-site / over http → CSRF + interception | Fix via same-origin dev proxy, not by weakening cookie attrs; keep `session_cookie_secure` in prod |
| CORS `allow_origins=['*']` + `allow_credentials=True` | Browser-blocked or, if forced, credential leak | Stay same-origin; add no CORS layer at all |
| Baking a secret into `VITE_*` | Secret shipped to every browser in the JS bundle | `VITE_*` is public/build-time; keep secrets server-side |
| New `/api/*` endpoint missing `_verify_auth` | Unauthenticated close/kill-switch | Every new endpoint keeps `Depends(_verify_auth)` + `_verify_csrf` |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No confirmation on irreversible actions | Accidental close / kill-switch | Keep two-step kill-switch preview→confirm; add confirm to full-close of large positions |
| Button enabled while request in flight | Double-fire (Pitfall 2) | `disabled={isPending}` + spinner on every destructive button |
| Generic "Error" toast hiding the broker reason | Operator can't tell why a close failed → blind retries | Surface `result.error` text inline (backend already returns it) |
| Modal inputs reset by background refetch | Recreates the HTMX clobbering bug at the data layer | Isolate modal/form state; ticket-keyed; refetch only the list, not the open form |
| No persistent "TRADING PAUSED" / kill-switch banner | Operator unaware trading is halted | Port the existing paused banner; drive from `/api/trading-status` |

## "Looks Done But Isn't" Checklist

- [ ] **Close button:** Stays pending until server confirms; row reflects MT5 truth (induce a broker reject on demo — UI must NOT say "closed").
- [ ] **Partial close:** Double-click on demo — total closed = the one requested amount, not compounded.
- [ ] **Kill switch:** Two-step preview→confirm preserved; confirm disabled-while-pending; single Discord alert; safe if pressed with nothing open.
- [ ] **CSRF:** A POST to any `/api/*` mutation with no SPA header returns 403 (automated test).
- [ ] **Auth:** Expired/cleared session on an API call returns 401 and the SPA redirects to `/login` exactly once (no loop); deep-link after logout lands on login with `?next=`.
- [ ] **Dev proxy:** Login in `vite dev` and a subsequent mutation both carry the cookie (no `localStorage`, no CORS).
- [ ] **nginx parallel-run:** Each still-HTMX page, `/api/*`, `/stream`, `/static/*`, `/login` all reach FastAPI; only cut-over SPA paths serve `index.html`; SSE still streams.
- [ ] **Deep-link:** Reloading a cut-over SPA route (e.g. `/analytics`) doesn't 404 and doesn't hijack a non-cut-over route.
- [ ] **Numbers:** XAUUSD price + lot precision match the bot's own values; submitted volumes are server-provided exact values.
- [ ] **Timezone:** History "today" filter and elapsed timers match the configured app timezone, verified around a midnight boundary.
- [ ] **Vite build:** No secret in the bundle (`grep` dist for sensitive strings); asset paths resolve under prod `base`.
- [ ] **shadcn/Tailwind:** Build succeeds on locked Tailwind v4 + React 19; dropdown/select/dialog render opaque; modals layer above the table.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Phantom-closed position (optimistic clear, real position live) | HIGH (real exposure) | Roll the page back to HTMX (one nginx edit); reconcile positions against MT5; remove optimistic update |
| CSRF accidentally removed | MEDIUM | Re-add `_verify_csrf`/SPA-header dep; rotate session secret if exploited; add regression test |
| nginx catch-all broke live pages | LOW (config rollback) | Revert nginx to per-route proxy; reload; SPA build untouched |
| Partial-close compounding | MEDIUM | Switch API to absolute volume + idempotency key; audit recent partial closes in trade history |
| Stale-cache wrong-row action | MEDIUM | Add invalidate-on-mutation + ticket-keyed modal; reconcile any mis-targeted modify |
| Secret baked into bundle | MEDIUM | Rotate secret; rebuild; move it server-side; purge cached assets |

## Pitfall-to-Phase Mapping

Likely phase shape (PROJECT.md): (1) JSON-API layer → (2) SPA scaffold + auth + design system → (3) page-migration waves → (4) parallel-run cutover + HTMX decommission.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1. Optimistic-clear of money mutation | Phase 2 (rule) + Phase 3 positions/kill-switch wave | Demo broker-reject test: UI never claims success without server confirm |
| 2. Double-fire / no idempotency | Phase 2 (disabled-while-pending wrapper + request-id) + Phase 3 | Double-click partial close on demo = single requested amount |
| 3. Dev-proxy cookie / 401 loop | Phase 2 (auth + dev proxy) | Login + mutation in `vite dev` both carry cookie; no loop |
| 4. CSRF dropped/weakened | Phase 1 (server header check + test) + Phase 2 (fetch wrapper) | Automated 403 on header-less POST |
| 5. nginx catch-all swallows routes | Phase 4 (cutover) + Phase 2 (URL/base strategy) | Each route resolves to the right app per cutover step; SSE alive |
| 6. TanStack stale cache / focus refetch | Phase 2 (QueryClient defaults) + Phase 3 (invalidate-on-mutation) | Closed position gone immediately; modal acts on correct ticket |
| 7. Float/precision (XAUUSD) | Phase 1 (server-side formatting contract) + Phase 3 | SPA values == Python values for XAUUSD + lots |
| 8. Timezone in history | Phase 1 (ISO+zone contract) + Phase 3 history wave | "Today" filter correct across midnight in app zone |
| 9. shadcn/Tailwind version mismatch | Phase 2 (scaffold) | Clean build on locked Tailwind v4 + React 19; Radix components opaque |
| 10. Vite build (env/base) | Phase 2 (scaffold) + Phase 4 (deploy) | No secret in dist; assets load under prod base behind nginx |
| 11. Parallel-run drift / premature decommission | Phase 4 (cutover) + Phase 1 (shared API) | HTMX page kept until React parity demo-verified |

---

## Sources

- This repository: `dashboard.py` (auth `_verify_auth`, CSRF `_verify_csrf`, destructive endpoints `close_position`/`modify_levels`/`close_partial`/`emergency_close`, SSE `/stream`, `_enrich_stage_for_ui` pip math), `nginx/telebot.conf` (proxy + SSE + login rate-limit), `config.py` (`session_cookie_secure`, `timezone`), `.planning/STATE.md` (Tailwind v4 + React 19 decisions; XAUUSD pip-size quick task 260501-i7u), `.planning/PROJECT.md` (locked stack + parallel-run cutover decision). — HIGH
- [TanStack Query — Important Defaults](https://tanstack.com/query/latest/docs/framework/react/guides/important-defaults) and [Window Focus Refetching](https://tanstack.com/query/latest/docs/framework/react/guides/window-focus-refetching) (staleTime:0, refetchOnWindowFocus default, mutations don't auto-invalidate). — HIGH
- [shadcn/ui — Tailwind v4](https://ui.shadcn.com/docs/tailwind-v4) and [Next.js 15 + React 19](https://ui.shadcn.com/docs/react-19) (canary init, forwardRef codemod, OKLCH). — HIGH
- [Tailwind v4 + Radix (shadcn) transparent dropdown/select discussion](https://github.com/tailwindlabs/tailwindcss/discussions/17137). — MEDIUM
- [Vite — Env Variables and Modes](https://vite.dev/guide/env-and-mode) (`VITE_*` build-time + public; `base`/`BASE_URL`). — HIGH

---
*Pitfalls research for: React 19 + Vite SPA over a live-money FastAPI/MT5 trading backend (v1.2 dashboard rewrite)*
*Researched: 2026-06-01*
