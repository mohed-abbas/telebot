# Phase 11: Live-money Pages + Settings - Research

**Researched:** 2026-06-07
**Domain:** React 19 + Vite + TanStack Query + shadcn/ui SPA consuming the shipped Phase 8 `/api/v2` JSON contract (live-money mutations + settings)
**Confidence:** HIGH (every contract claim derived from the actual source files in this repo)

## Summary

Phase 11 is a **pure presentation-layer consumer phase**. Every read and mutation it needs already ships in `api/actions.py`, `api/meta.py`, `api/positions.py`, `api/settings.py`, and `api/schemas.py`. The single highest-value research output is *exact, source-derived contracts* so the planner never has to re-read the backend: this document pins every request/response shape, the error envelope, the mode-aware settings caps, and the inherited frontend infrastructure the pages slot into.

The four pages reuse a mature substrate: the `api()` fetch wrapper already echoes CSRF on mutations and throws `HttpError`; the `QueryClient` already has `keepPreviousData` + `refetchIntervalInBackground:false` + a global 401 handler; `DataTable` + Loading/Empty/ErrorPanel already exist; `StagedView.tsx` is a working template for the polling-page pattern (`useQuery` + `refetchInterval:3000`). Phase 11 adds React pages, five shadcn components (`dialog`, `tooltip`, `select`, `badge`, `popover`), and three npm packages (`react-hook-form`, `zod`, `@hookform/resolvers`) — nothing more.

The two genuinely subtle areas are (1) **the mode-aware `risk_value` caps and footgun math** — the server treats `risk_value` as a TOTAL across `max_stages` in `fixed_lot` mode, NOT per-trade, and even the server's own dry-run divides by `max_stages` in both modes; and (2) **the poll-safe modal/drilldown survival**, which the codebase already achieves structurally via the TanStack-Query-vs-local-state split (proven live in Phase 9's throwaway probe). Both are addressed concretely below.

**Primary recommendation:** Build each page as a `useQuery` poller (server state) + `useMutation` per action (no optimistic clear; UI updates only in `onSuccess`) + react-hook-form/local state for modals (form state). Derive zod caps from `dashboard.validate_settings_form` verbatim. Render the footgun and confirm-diff modal outside the polling subtree. Add one Vitest unit test for the zod cap schema as the new automated proof; everything else is backend pytest (already green) + `npm run build` + manual money-safe SC checks.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (carried-forward invariants — do NOT re-litigate)

- **Server-confirmed mutations only (SC#1):** close / modify SL+TP / partial-close update or clear the UI ONLY on server-confirmed success — no optimistic clear. On error the modal stays open with typed values preserved and surfaces an error toast. Every destructive button is disabled-while-pending. (Pitfall 1.)
- **CSRF on every mutation (SC#2):** every live-money POST carries the `X-CSRF-Token` double-submit header (readable `telebot_csrf` cookie echoed) and is rejected `403` without it. (Phase 8 D-15/D-16, Phase 9 D-04/D-06.)
- **partial-close contract (Phase 8 D-09/D-10/D-11):** body carries `close_volume` in absolute lots, validated `0 < close_volume < pos.volume` rounded to lot step, plus a client-generated UUID `request_id`. Same id+same params → cached 200 replay (no broker hit); same id+different params → 409.
- **`*_display` render / bare-numeric submit (Phase 8 D-05, Pitfall 5):** SPA renders the server `*_display` string, submits the bare numeric, never re-rounds. The compounded-exposure number is a client calc off two bare numerics → Pitfall-5-safe.
- **Polling, not SSE (Phase 9 D-09):** TanStack Query `refetchInterval` + `refetchIntervalInBackground:false` + `placeholderData:keepPreviousData`. Server state = TanStack Query; form/UI state = react-hook-form/local — never mixed. Open modals/drilldowns live OUTSIDE the polling subtree (`#modal-root` pattern) — SC#3.
- **Shared primitives inherited from Phase 10:** reuse `DataTable` + Loading/Empty/ErrorPanel. Read-load failures → inline `ErrorPanel`, not a toast (D-11). Live-money action feedback IS a toast (sonner).

### Implementation Decisions (locked)

- **D-01:** Mirror legacy positions shape 1:1 — row Close + one combined Edit modal (SL/TP + partial-close) + expandable drilldown. Edit modal renders outside the polling subtree.
- **D-02:** Inside the Edit modal, modify-SL/TP and partial-close are TWO independent submits — each its own button/pending state/CSRF call/toast. `POST .../levels` and `POST .../close-partial`. Modal stays open on either error; closes only on confirmed success. No combined Save.
- **D-03:** Per-position Close and partial-close Close lots use an inline two-click confirm (button morph OR small popover — executor's choice). Replaces legacy `hx-confirm` browser dialog. Misclick recoverable.
- **D-04:** Operator types absolute lots to CLOSE directly (no percent/slider). UI shows current volume + live "Remaining after: X.XX". zod-validate `0 < value < volume` rounded to lot step. Client UUID `request_id` per submit.
- **D-05:** EVERY settings change runs validate→confirm-diff→confirm. No dangerous-field allow-list. Flow: edit → Save → `POST .../validate` → confirm modal (diff + dry-run) → Confirm → `POST .../{account}` (re-validates server-side). Sonner success/rejection/revert toasts (SUX-01).
- **D-06:** Compounded-exposure footgun warning shows in BOTH places: inline live-recomputed near the fields AND restated in the confirm-diff modal. Client calc off two bare numerics.
- **D-07:** Footgun math and zod caps are MODE-AWARE. **percent/risk mode** → exposure compounds: warn on `max_stages × risk_value`. **`fixed_lot` mode** → `risk_value` is the TOTAL across `max_stages`, NOT per-trade → do NOT multiply; warn on the absolute total. zod caps switch on mode and MIRROR the server (`api/settings.py` `_validate` + `store.effective`) — derive, never hardcode.

### Claude's Discretion (researcher/planner decides)

- Overview composition (full vs condensed positions table; kill-switch entry treatment; PAUSED banner + pending-stages card layout).
- Kill-switch page structure for the locked two-step preview→confirm.
- Settings audit-timeline + revert UX detail.
- Whether multiple drilldowns open at once (legacy allowed it) + the exact refetch-survival mechanism.
- Inline-confirm rendering (button morph vs popover) for D-03.
- Per-field copywriting (SUX-04) — the UI-SPEC already fixes this; see Copywriting Contract there.
- Which shadcn components each page adds; where shared live-money components/hooks live.
- Exact `refetchInterval`/`staleTime` per page (overview ~3000ms target).

### Deferred Ideas (OUT OF SCOPE)

None deferred to other phases beyond the standing boundary: NO new JSON endpoints (Phase 8 done), NO bot-core changes, legacy-route/SSE/Tailwind-CLI removal stays Phase 12. Legacy dashboard keeps running at `/` in parallel throughout Phase 11.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PAGE-05 | Overview page parity with live polling | `GET /api/v2/overview` (`OverviewMeta`) + `GET /api/v2/positions` + `GET /api/v2/trading-status` shapes pinned below; `overview.html`/`overview_cards.html` parity structure extracted; `StagedView.tsx` is the polling template |
| PAGE-06 | Positions + safe live-money actions (close, modify SL+TP, partial-close), server-confirmed only, disabled-while-pending, error toasts | `POST .../close`, `.../levels`, `.../close-partial` shapes + 409 semantics pinned; `positions_table.html`/`edit_levels_modal.html`/`position_drilldown.html` parity extracted; `useMutation`/`isPending` pattern documented |
| PAGE-07 | Emergency kill switch two-step preview→confirm | `GET /api/v2/emergency/preview` (`EmergencyPreview`) → `POST /api/v2/emergency/close` (`EmergencyResult`) → `POST /api/v2/emergency/resume`; `kill_switch_preview.html` parity extracted |
| PAGE-08 | Settings page parity — per-account form, two-step confirm w/ diff, audit timeline, revert | `GET /settings/{account}` (`SettingsView`), `POST .../validate` (`SettingsValidateResult`), `POST .../{account}` (confirm), `POST .../revert` pinned; `account_settings_tab.html`/`settings_confirm_modal.html`/`settings_audit_timeline.html` parity extracted |
| SUX-01 | Viewport save/error/revert toasts (sonner) | sonner already installed (Phase 9); error-envelope shape `{error:{code,message,fields?}}` pinned for toast copy derivation |
| SUX-02 | Inline field help/tooltip incl. compounded-exposure footgun | mode-aware footgun formulas derived from `_compute_dry_run` + `trade_manager.py`; tooltip via shadcn `tooltip` (to add) |
| SUX-03 | Client validation (rhf + zod) mirroring server hard-caps incl. mode-dependent + per-account `risk_value` caps | EXACT caps derived from `validate_settings_form` (dashboard.py:708-759) + `store.effective` — table below |
| SUX-04 | Copywriting pass (DB-column → operator labels) | UI-SPEC Copywriting Contract is authoritative; legacy `account_settings_tab.html` is the parity baseline |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Live position data (poll) | API (`GET /api/v2/positions`, `/overview`, `/trading-status`) | Browser (TanStack Query cache) | Server owns truth + `_display` formatting (Pitfall 5); SPA only renders |
| Close / modify SL+TP / partial-close mutations | API (`api/actions.py`) | Browser (`useMutation` orchestration) | Broker calls + idempotency live server-side; SPA never re-rounds, never optimistic |
| Idempotency / 409 replay | API (`api/idempotency.py`, Postgres) | Browser (generates `request_id` UUID) | Dedupe is a server guarantee; client only supplies a stable id |
| CSRF enforcement | API (`api/deps.verify_csrf_token`) | Browser (`api()` echoes header) | Double-submit; server is authoritative, client echoes the readable cookie |
| Settings validation (hard caps) | API (`validate_settings_form`, authoritative) | Browser (zod mirror, defense-in-depth) | Server re-validates on confirm; zod is UX-only, NEVER a replacement (T-08-18) |
| Footgun / compounded-exposure calc | Browser (pure client calc off bare numerics) | — | Presentation-only derived value; Pitfall-5-safe (not re-rounding server money) |
| Modal/form state | Browser (react-hook-form / local React state) | — | Decoupled from polling so refetch can't clobber typed input (SC#3) |
| Kill-switch preview + execute | API (`api/meta.py` preview, `api/actions.py` close/resume) | Browser (two-step flow UI) | Engine pause is server state; SPA renders preview + confirm |

## Standard Stack

### Core (already installed — Phase 9/10)

| Library | Version (installed) | Purpose | Why Standard |
|---------|--------------------|---------|--------------|
| react / react-dom | 19.2.7 | UI runtime | Locked stack; `ref`-as-prop, no `forwardRef` `[VERIFIED: frontend/package.json]` |
| @tanstack/react-query | 5.101.0 | Server-state polling + mutations | Inherited `QueryClient` defaults; the SC#3 server/form split `[VERIFIED: frontend/package.json + queryClient.ts]` |
| react-router-dom | 7.17.0 | `/app/*` routing | `createBrowserRouter` declarative; basename `/app` `[VERIFIED: router.tsx]` |
| sonner | 2.0.7 | Action toasts (SUX-01) | Toaster mounted at root (Phase 9 D-11) `[VERIFIED: package.json]` |
| radix-ui (umbrella) | 1.4.3 | shadcn primitive base | Granular imports `import { Dialog } from "radix-ui"` `[VERIFIED: package.json]` |
| lucide-react | 1.17.0 | Icons (AlertTriangle for footgun) | `[VERIFIED: package.json]` |
| tailwindcss + @tailwindcss/vite | 4.3.0 | Styling (no `tailwind.config.js`) | `@theme` tokens in `index.css` `[VERIFIED: package.json]` |

### Supporting (NEW — Phase 11 adds these)

| Library | Version (registry latest) | Purpose | When to Use |
|---------|--------------------------|---------|-------------|
| `react-hook-form` | 7.77.0 | Settings/edit-levels/partial-close forms | All multi-field forms; pairs with zod resolver `[ASSUMED]` (see Package Legitimacy Audit — slopcheck unavailable) |
| `zod` | 4.4.3 | Client schema mirroring server caps (SUX-03) | Settings cap schema, partial-close range. **NOTE: zod 4.x is a major version — API differs from v3** `[ASSUMED]` |
| `@hookform/resolvers` | 5.4.0 | Bridge zod → react-hook-form | `zodResolver(schema)`. **resolvers v5 + zod v4 pairing — confirm import path at install** `[ASSUMED]` |

> **Version pinning caution:** zod jumped to v4 and `@hookform/resolvers` to v5. The v4/v5 pairing is current and compatible, but the import for the resolver changed across major versions (`import { zodResolver } from "@hookform/resolvers/zod"`). Verify at install with `npm run build` (TS strict will catch a wrong import). Do NOT copy zod-v3 snippets.

### shadcn components to add via CLI (lean set — Phase 9 D-11 discipline)

| Component | Needed for | CLI |
|-----------|-----------|-----|
| `dialog` | Edit-levels modal, settings confirm-diff modal | `npx shadcn@latest add dialog` |
| `tooltip` | Per-field settings help (SUX-02) | `npx shadcn@latest add tooltip` |
| `select` | Settings `risk_mode` (percent / fixed_lot) | `npx shadcn@latest add select` |
| `badge` | TRADING PAUSED chip / status chips (only if generic chip needed beyond `DirectionBadge`) | `npx shadcn@latest add badge` |
| `popover` *(optional, D-03)* | Inline confirm IF popover variant chosen over button-morph | `npx shadcn@latest add popover` |

> **Pitfall-9 gate before wiring any mutation:** render `dialog` + `select` and confirm OPAQUE, correct dark-brand colors (no transparent-popover regression) BEFORE wiring live-money calls. (UI-SPEC verification gate.)

**Installation:**
```bash
cd frontend
npm install react-hook-form zod @hookform/resolvers
npx shadcn@latest add dialog tooltip select badge popover
```

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| react-hook-form | Plain controlled `useState` | Works for tiny forms, but settings has 5+ fields with cross-field validation (mode-aware caps) — rhf+zod is the locked SUX-03 choice |
| zod | yup / manual validators | zod is locked by SUX-03/UI-SPEC; TS-first inference pairs with the existing strict-TS build |
| @tanstack/react-table | hand-rolled `DataTable` | Already hand-rolled and proven (Phase 10 D-10); do NOT add react-table |

## Package Legitimacy Audit

> slopcheck could not be installed in this environment (`pip install slopcheck` failed). Per the graceful-degradation protocol, all three NEW packages are tagged `[ASSUMED]` and the planner should gate each install behind a `checkpoint:human-verify` task OR rely on the `npm run build` TS gate + the registry evidence below (all three are long-established, high-trust packages with official GitHub repos).

| Package | Registry | Created | Source Repo | postinstall | slopcheck | Disposition |
|---------|----------|---------|-------------|-------------|-----------|-------------|
| `react-hook-form` | npm | 2019-03-20 | github.com/react-hook-form/react-hook-form | none | unavailable | Approved (mature, ~7yr, official repo) |
| `zod` | npm | 2020-03-07 | github.com/colinhacks/zod | none | unavailable | Approved (mature, official repo) — verify v4 API |
| `@hookform/resolvers` | npm | 2020-05-20 | github.com/react-hook-form/resolvers | none | unavailable | Approved (official rhf org repo) |

**Packages removed due to [SLOP]:** none
**Packages flagged [SUS]:** none
**Registry verification:** all three resolve on npm with versions confirmed (`npm view`), no `postinstall` scripts present. All are tagged `[ASSUMED]` only because slopcheck was unavailable and the package names originated from the UI-SPEC (non-authoritative for provenance), per the package-name provenance rule.

## Architecture Patterns

### System Architecture Diagram

```
                          ┌─────────────────────────────────────────────┐
  Operator browser        │  React SPA  (/app/*, basename "/app")        │
  ─────────────────       │                                             │
                          │  ┌───────────────┐    ┌──────────────────┐  │
   reads (poll 3s) ───────┼─▶│ TanStack Query │    │ react-hook-form  │◀─┼── typed input
                          │  │  (server state)│    │  / local state   │  │   (form state)
                          │  └───────┬────────┘    └────────┬─────────┘  │
                          │          │                      │            │
                          │   useQuery refetchInterval   useMutation     │
                          │   (Overview/Positions/        (close/levels/ │
                          │    trading-status)             partial/      │
                          │          │                     emergency/    │
                          │          │                     settings)     │
                          │   ┌──────▼──────────────────────▼─────────┐  │
                          │   │  api() fetch wrapper (lib/http.ts)     │  │
                          │   │  • echoes X-CSRF-Token on mutations    │  │
                          │   │  • credentials: same-origin            │  │
                          │   │  • throws HttpError on non-2xx         │  │
                          │   └──────────────────┬─────────────────────┘  │
                          │   ┌──────────────────▼─────────────────────┐  │
                          │   │ #modal-root / Dialog (OUTSIDE poll      │  │
                          │   │ subtree) — Edit modal, confirm-diff,    │  │
                          │   │ drilldown survive background refetch    │  │
                          │   └─────────────────────────────────────────┘ │
                          └────────────────────────┬────────────────────┘
                                                   │  same-origin /api/v2/*
                                                   ▼
       ┌───────────────────────────────────────────────────────────────────┐
       │  FastAPI /api/v2  (Phase 8 — SHIPPED, UNCHANGED in Phase 11)       │
       │  ┌──────────┐ ┌─────────┐ ┌────────────┐ ┌────────────┐           │
       │  │ meta.py  │ │positions│ │ actions.py │ │settings.py │           │
       │  │ overview │ │ list +  │ │ close      │ │ GET/validate│          │
       │  │ status   │ │ drill-  │ │ levels     │ │ confirm    │           │
       │  │ preview  │ │ down    │ │ close-part.│ │ revert     │           │
       │  └──────────┘ └─────────┘ │ emergency  │ └─────┬──────┘           │
       │   deps.verify_csrf_token  └─────┬──────┘       │                  │
       │   errors.py → {error:{code,…}}  │     validate_settings_form       │
       │                          idempotency (Postgres) (authoritative caps)│
       └──────────────────────────────────┼────────────────┬──────────────┘
                                           ▼                ▼
                                    MT5 connector      SettingsStore + DB
                                    (broker, untouched) (account_settings + audit)
```

### Recommended Project Structure

```
frontend/src/
├── routes/
│   ├── OverviewView.tsx      # PAGE-05 — poller + PAUSED banner + positions + pending + kill-switch entry
│   ├── PositionsView.tsx     # PAGE-06 — DataTable + row Close + Edit modal + drilldown
│   ├── KillSwitchView.tsx    # PAGE-07 — two-step preview→confirm (or a modal off Overview)
│   ├── SettingsView.tsx      # PAGE-08 — per-account form + confirm-diff + audit + revert
│   └── router.tsx            # add overview/positions/emergency/settings routes; flip index → /overview
├── components/
│   ├── positions/
│   │   ├── EditPositionDialog.tsx   # combined modal: two independent forms (D-02)
│   │   ├── InlineConfirm.tsx        # D-03 button-morph or popover guard
│   │   └── PositionDrilldown.tsx    # fill history + signal attribution
│   ├── settings/
│   │   ├── SettingsForm.tsx         # rhf + zod; inline footgun
│   │   ├── ConfirmDiffDialog.tsx    # diff + dry-run + footgun restated
│   │   └── AuditTimeline.tsx        # newest-first + revert action
│   └── ui/                          # shadcn adds: dialog, tooltip, select, badge, popover
├── lib/
│   ├── settingsSchema.ts     # zod cap schema (mode-aware) — SUX-03; THE testable unit
│   ├── footgun.ts            # pure mode-aware compounded-exposure calc — D-06/D-07
│   └── useMutationToast.ts   # optional: wrap useMutation + sonner success/error
└── hooks/                    # per-page query/mutation hooks (optional)
```

### Pattern 1: Polling read page (the proven template)
**What:** `useQuery` with `refetchInterval`; render Loading/ErrorPanel/Empty/DataTable.
**When:** Overview, Positions.
**Example (from the shipped `StagedView.tsx` — copy this shape):**
```typescript
// Source: frontend/src/routes/StagedView.tsx (verbatim pattern, lines 146-153)
const { data, isPending, isError, error, refetch } = useQuery<Position[]>({
  queryKey: ["positions"],
  queryFn: () => api("/api/v2/positions") as Promise<Position[]>,
  refetchInterval: 3000, // background pause is free via refetchIntervalInBackground:false
});
// isPending → <Loading/>; isError → <ErrorPanel error={error} onRetry={refetch}/> (D-11 inline, NOT toast)
```

### Pattern 2: Server-confirmed mutation, no optimistic (the money-safe core)
**What:** `useMutation`; button `disabled={isPending}`; UI changes ONLY in `onSuccess`; error → sonner toast, modal stays open.
**When:** every live-money action (SC#1).
**Example:**
```typescript
// Source: derived from lib/http.ts api() + queryClient.ts MutationCache (Phase 9 D-06)
const qc = useQueryClient();
const close = useMutation({
  mutationFn: () =>
    api(`/api/v2/positions/${account}/${ticket}/close`, { method: "POST" }),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ["positions"] }); // refetch truth, not optimistic
    toast.success("Position closed");
  },
  onError: (e) => toast.error(messageFromEnvelope(e)), // 401 already handled globally
});
// <Button variant="destructive" disabled={close.isPending}>
//   {close.isPending ? "Closing…" : "Close"}
// </Button>
```

### Pattern 3: Partial-close with idempotency request_id (D-04 / Pitfall 3)
**What:** generate a UUID per submit attempt; submit ABSOLUTE lots; handle 409.
**Example:**
```typescript
// Source: api/actions.py:160-228 (close-partial contract) + PartialCloseIn schema
const requestId = useRef(crypto.randomUUID()); // stable across retries of the SAME intent
const partial = useMutation({
  mutationFn: (closeVolume: number) =>
    api(`/api/v2/positions/${account}/${ticket}/close-partial`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ close_volume: closeVolume, request_id: requestId.current }),
    }),
  onSuccess: () => { qc.invalidateQueries({ queryKey: ["positions"] }); toast.success("Lots closed"); },
  onError: (e) => {
    if (e instanceof HttpError && e.status === 409)
      toast.error("That close already ran or the amount changed — refresh and retry.");
    else toast.error(messageFromEnvelope(e));
  },
});
// IMPORTANT: regenerate requestId only when the operator changes the intended amount —
// a pure retry of the same amount MUST reuse the id to get the cached 200 replay (no double broker hit).
```

### Pattern 4: Error message extraction from the Phase 8 envelope
```typescript
// Source: api/errors.py — failure body is {error:{code,message,fields?}}
function messageFromEnvelope(e: unknown): string {
  if (e instanceof HttpError) {
    const b = e.body as { error?: { message?: string; fields?: Record<string,string> } } | undefined;
    return b?.error?.message ?? `Request failed (${e.status})`;
  }
  return "Unexpected error";
}
// Success responses are BARE (the resource itself) — only failures carry the envelope.
```

### Pattern 5: Poll-safe modal (SC#3) — how this codebase achieves it
**Mechanism (no new infrastructure needed):**
- Server data lives in TanStack Query (`useQuery` for positions). A refetch replaces the *query cache*, which re-renders the table rows.
- The Edit modal's SL/TP/lots inputs live in **react-hook-form / local React state**, NOT in the query cache. A background refetch cannot touch them.
- The modal/dialog is rendered as a sibling of the polling subtree (a `Dialog` portal, equivalent to the legacy `#modal-root` which sat outside the `hx-trigger="every 3s"` div in `overview.html:64`).
- **This was proven LIVE in Phase 9's throwaway ProbeView** (STATE.md: "useQuery(trading-status, refetchInterval 3000) vs useState input survived ≥2 refetch cycles unclobbered, D-08/SPA-05").
- For the drilldown: store its open/expanded state in local component state keyed by ticket; the row data refetches but the open flag persists across renders. Multiple drilldowns open simultaneously is allowed (legacy `positions_table.html:60` comment "D-06: multiple can be open").

### Anti-Patterns to Avoid
- **Optimistic clear / `setQueryData` before server confirm** — forbidden (SC#1, Pitfall 1). A position must never render as closed while live at the broker.
- **Re-rounding server numbers in JS** — render `*_display`, submit bare numeric (Pitfall 5). The ONLY allowed client calc is the footgun (off two bare numerics) and elapsed duration.
- **Re-introducing a percent/slider partial-close model** — the absolute-lots contract is the anti-"75% trap" design (D-04, Pitfall 3). Never show "% of volume".
- **One combined Save in the Edit modal** — two distinct endpoints, two independent submits (D-02).
- **Hardcoding zod caps** — derive from `validate_settings_form` (caps table below). Server is authoritative; zod mirrors.
- **Reverting by `audit_id`** — see Open Question 1: the legacy template offered per-row revert with `audit_id`, but the Phase 8 `revert` endpoint reverts ONLY the latest change with no `audit_id` param.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Number/price/money formatting | Client `toFixed`/`Intl` | Server `*_display` fields | Pitfall 5; XAUUSD pip-size already bit this project |
| Idempotent partial-close dedupe | Client-side debounce | Server `request_id` + Postgres guard | Phase 8 owns it; client only supplies the UUID |
| CSRF token plumbing | Per-call header logic | `api()` wrapper (auto-echoes) | Already centralized (`lib/http.ts`) |
| 401 redirect | Per-query catch | Global `onAuthError` (QueryCache+MutationCache) | Already wired; single bounce, loop-break |
| Settings hard-cap validation | Reinvented thresholds | zod mirror of `validate_settings_form` | Server re-validates; zod is UX-only defense-in-depth |
| Generic data table | Another table impl | `DataTable` (`components/data/DataTable.tsx`) | Proven mono/sign/align; Phase 10 D-10 |
| Loading/empty/error states | Bespoke per page | `Loading` / `Empty` / `ErrorPanel` | Phase 10 trio; read-failure = inline panel (D-11) |
| Modal primitive | Custom overlay | shadcn `dialog` (radix) | Opaque dark tokens, a11y, portal-out-of-poll-subtree |

**Key insight:** Phase 11's value is *fidelity to existing contracts*, not new mechanisms. Almost every "hard" problem (formatting, CSRF, idempotency, 401, polling-vs-form) was already solved in Phase 8/9/10. The genuinely new code is four page compositions + the mode-aware zod schema + the footgun calc.

## Settings Caps + Footgun — DERIVED FROM SERVER SOURCE (SUX-03 / D-07)

> **Source of truth:** `dashboard.validate_settings_form` (dashboard.py:708-759), `_SETTINGS_HARD_CAPS_INT` (dashboard.py:658-662), and `_compute_dry_run` (dashboard.py:776-790). The zod schema MUST mirror these exactly.

### Exact caps the zod schema must mirror

| Field | Type | Rule | Source |
|-------|------|------|--------|
| `risk_mode` | enum | must be `"percent"` or `"fixed_lot"` | dashboard.py:719-724 |
| `risk_value` (percent mode) | float | `> 0` AND `<= 5.0` | dashboard.py:733-738 |
| `risk_value` (fixed_lot mode) | float | `> 0` AND `<= max_lot_size` (per-account, from `store.effective(account).max_lot_size`) | dashboard.py:739-741 |
| `max_stages` | int | `1 <= v <= 10` | `_SETTINGS_HARD_CAPS_INT` line 659 |
| `default_sl_pips` | int | `1 <= v <= 500` | line 660 |
| `max_daily_trades` | int | `1 <= v <= 100` | line 661 |

**Per-account cap mechanism:** `max_lot_size` is NOT a fixed constant — it comes from the `accounts` table joined into `store.effective(account)` (settings_store.py:34,47,70). The `risk_value` upper bound in `fixed_lot` mode is therefore per-account. The SettingsView `values` dict includes `max_lot_size` (it is one of `_SETTINGS_FIELDS`, api/settings.py:79-87), so the SPA can read it from the GET response and feed it into the zod schema's `fixed_lot` branch dynamically.

> **NOTE — `max_open_trades`:** also in `_SETTINGS_FIELDS` and the `values` dict, but `validate_settings_form` does NOT parse or cap it (it's an `accounts`-table column, not in the settings form). It is read-only on this page — do not add a zod cap for it; do not submit it as a changed field.

### Mode-aware zod sketch (derive, do not hardcode blindly)
```typescript
// Source: dashboard.validate_settings_form (caps) + store.effective (per-account max_lot_size)
function makeSettingsSchema(maxLotSize: number) {
  return z.object({
    risk_mode: z.enum(["percent", "fixed_lot"]),
    risk_value: z.number().positive(),         // refine below by mode
    max_stages: z.number().int().min(1).max(10),
    default_sl_pips: z.number().int().min(1).max(500),
    max_daily_trades: z.number().int().min(1).max(100),
  }).superRefine((v, ctx) => {
    if (v.risk_mode === "percent" && v.risk_value > 5.0)
      ctx.addIssue({ code: "custom", path: ["risk_value"], message: "risk_value must be between 0 and 5.0." });
    if (v.risk_mode === "fixed_lot" && v.risk_value > maxLotSize)
      ctx.addIssue({ code: "custom", path: ["risk_value"], message: "Risk value exceeds max_lot_size for this account." });
  });
}
// zod v4 API: confirm z.enum / superRefine / addIssue("custom") signatures at install (npm run build).
```

### Footgun / compounded-exposure formula (D-06/D-07) — MODE-AWARE

| Mode | Formula | Copy (UI-SPEC) |
|------|---------|----------------|
| `percent` | exposure compounds → `max_stages × risk_value` (%) | *"{max_stages} entries at {risk_value}% risks up to {max_stages × risk_value}% per signal."* |
| `fixed_lot` | `risk_value` is the TOTAL across stages → do NOT multiply; warn on the absolute total | *"This sizes up to {risk_value} total lots per signal across {max_stages} entries."* |

**CRITICAL semantic — verified in source:**
- `trade_manager.py:108-117` (`stage_lot_size`): "For fixed_lot mode, snapshot.risk_value carries the **target total lot size across all stages**." Returns `risk_value / max_stages` per stage.
- `trade_manager.py:690-691`: "snapshot.risk_value carries the operator-configured **total lot**; stage_lot_size produces the per-stage slice."
- `_compute_dry_run` (dashboard.py:776-790): computes `per_stage = risk_value / max_stages` for **BOTH** modes — i.e. even the server's own dry-run treats `risk_value` as a total-across-stages in both modes and shows per-stage. The confirm-diff modal renders this server `dry_run_text` verbatim.

So the inline footgun must NOT multiply `risk_value × max_stages` in `fixed_lot` mode — that would display a wrong, alarming number. The percent-mode "×stages" wording in the SUX-02 requirement text is a percent-mode illustration only (operator-confirmed 2026-05-01, MEMORY `project_lot_semantics.md`). The footgun is a pure client calc off two bare numerics (`risk_value`, `max_stages`) → Pitfall-5-safe.

## Exact Server Contracts the SPA Must Match

> All pinned from the actual source. Success bodies are BARE; failures use `{error:{code,message,fields?}}` (api/errors.py). Status→code map: 400 bad_request, 401 unauthorized, 403 forbidden, 404 not_found, 409 conflict, 422 validation_error, 503 unavailable.

### Overview / status (PAGE-05) — `api/meta.py`
- `GET /api/v2/overview` → `OverviewMeta { trading_paused: bool, open_positions: int, accounts: AccountOverview[] }`. `AccountOverview` carries `_display` twins for balance/equity/margin/free_margin/total_profit plus `daily_trades`, `max_daily_trades`, `daily_limit_pct`, `risk_percent`, `max_lot`, `connected`, `enabled` (schemas.py:57-78).
- `GET /api/v2/trading-status` → `TradingStatus { paused: bool, status: "paused"|"running" }`. Drives the TRADING PAUSED banner.
- `GET /api/v2/emergency/preview` → `EmergencyPreview { open_positions: int, pending_orders: int, accounts: string[] }`.

### Positions (PAGE-06) — `api/positions.py`
- `GET /api/v2/positions` → `Position[]`. Each: `account, ticket, symbol, direction("buy"|"sell"), volume(+_display), open_price(+_display), sl(float|null), tp(float|null), profit(+_display)` (schemas.py:39-51). **Note: `sl`/`tp` have NO `_display` twin** — render raw or format minimally (they're prices the operator edits).
- `GET /api/v2/positions/{account}/{ticket}` → drilldown dict: `{ position:{…entry_price_display,lot_size_display,pnl_display,sl,tp}, fill_history:[…], signal:{source_name,signal_type,raw_text,timestamp…} }` (positions.py:52-75; parity `position_drilldown.html`). 404 if gone.

### Live-money mutations (PAGE-06/07) — `api/actions.py` — ALL CSRF-guarded
- `POST /api/v2/positions/{account}/{ticket}/close` → `MutationResult { ok, success, error }`. No body. 404 if account unknown.
- `POST /api/v2/positions/{account}/{ticket}/levels` → `{ ok, success, changed:{sl?,tp?}, error }`. Body `CloseLevelsIn { sl?:float, tp?:float }` (both optional; null = keep). 422 if sl/tp ≤ 0; 404 if position gone. No-op (nothing changed) → `{ok:true, changed:{}}`. Only changed fields hit the broker.
- `POST /api/v2/positions/{account}/{ticket}/close-partial` → `{ ok, success, closed_volume, closed_volume_display, error }`. Body `PartialCloseIn { close_volume:float, request_id:str }`. Server `round(close_volume, 2)`. **409** = `request_id` reused with different params OR concurrent in-flight retry ("request in progress"). **404** position gone. **422** `close_volume out of range` (not `0 < cv < pos.volume`). Same id+same params → cached 200 replay, broker untouched.
- `POST /api/v2/emergency/close` → `EmergencyResult { results: dict, ok: true }`. No body. Closes all, cancels orders, pauses.
- `POST /api/v2/emergency/resume` → `{ status: "resumed" }`. No body.

### Settings (PAGE-08) — `api/settings.py` — validate/confirm/revert CSRF-guarded
- `GET /api/v2/settings/{account}` → `SettingsView { account, values:{risk_mode,risk_value,max_stages,default_sl_pips,max_daily_trades,max_open_trades,max_lot_size}, audit:[{id,account_name,field,old_value,new_value,actor,timestamp,timestamp_display}], diff:null }`. 404 unknown account, 503 store uninitialized. **`values` are BARE typed values** (risk_value is a float, not a `_display` string) — this is the form's initial state.
- `POST /api/v2/settings/{account}/validate` → `SettingsValidateResult { valid, errors:{field:msg}, diff:[{field,old,new}], dry_run_text }`. Body `SettingsValidateIn { account, values:dict }`. **Returns 200 even when `valid:false`** (errors in the `errors` map, NOT an HTTP error) — branch on `valid`, not on status. `dry_run_text` is server-rendered (render it verbatim in the confirm modal). `values` dict is the same shape `validate_settings_form` expects (string-coercible field values).
- `POST /api/v2/settings/{account}` → `MutationResult { ok, success }`. Body `SettingsConfirmIn { account, values:dict }`. **Re-validates server-side**; 422 `Re-validation failed` if caps re-breached. Applies each CHANGED field via `store.update` (writes setting + audit row atomically).
- `POST /api/v2/settings/{account}/revert` → `MutationResult { ok, success }`. Body `SettingsRevertIn { account }`. Inverts ONLY the latest persisted change (no `audit_id` param). 404 "Nothing to revert" if no audit rows. Records the revert as a NEW audit entry.

> **Settings request-body shape note:** validate/confirm bodies are `{ account, values:{…} }` (the field dict nested under `values`), NOT a flat field body. `values` field values should be sent as the form values (the server's `validate_settings_form` coerces strings/numbers). Mirror what the legacy form posted.

## Legacy Parity Targets (extracted structure to replicate)

| Legacy template | What to replicate in React |
|-----------------|----------------------------|
| `overview.html` | PAUSED banner (red) above; kill-switch entry button; account cards (`overview_cards.html`); Open Positions table; Pending Stages (top-5); `#modal-root` outside poll subtree (line 64) |
| `overview_cards.html` | Per-account card: name + Connected/Offline chip; Balance/Equity/Open P&L (green/red)/Open Trades/Daily Trades (yellow≥80%/red≥100%)/Risk%; margin-used bar. Empty: "No accounts configured." |
| `positions_table.html` | Columns Account\|Symbol\|Direction(BUY green/SELL red)\|Volume\|Entry\|SL\|TP\|P&L(green/red)\|Actions(Close destructive + Edit). Drilldown row per position (multiple open allowed). Empty: "No open positions". Mobile card variant. **Legacy used `hx-confirm` browser dialog → replace with inline two-click confirm (D-03).** |
| `edit_levels_modal.html` | Combined modal: position summary grid; SL/TP form (placeholder "Leave blank to keep current"); divider; partial-close form. **Legacy partial-close used PERCENT (`name="percent"`, 1-99) — DO NOT replicate; use absolute lots + "Remaining after" (D-04).** Two separate `<form>`s already (D-02 parity). |
| `position_drilldown.html` | Fill History table (Stage\|Time\|Lots\|Band\|SL at Fill\|Status); Current P/L + Entry/SL/TP row; Signal Source (source_name/time/type + raw text `<details>`). |
| `kill_switch_preview.html` | Red card: Open Positions count + Pending Orders count; warning copy ("close ALL … manually re-enable"); CONFIRM CLOSE ALL (red); Cancel. Hide confirm when count==0. |
| `account_settings_tab.html` | Form: risk_mode select; risk_value (mode-aware help + range); max_stages (inline footgun, percent-only in legacy — make mode-aware); default_sl_pips; max_daily_trades; "Changes apply to next signal" notice; audit timeline. |
| `settings_confirm_modal.html` | Diff table (Field\|old→new); "Effect on a typical signal" dry-run box; destructive alert ("applies to signals received AFTER you confirm; in-flight unaffected"); Confirm/Discard. |
| `settings_audit_timeline.html` | Table Timestamp\|Field\|Change(old→new)\|Actor\|Action(Revert). **Legacy Revert posts `?audit_id=` per row — but API reverts only the latest. See Open Question 1.** |

## Runtime State Inventory

Not applicable — Phase 11 is greenfield React page composition against an existing API. No rename/refactor/migration. No stored data, live-service config, OS-registered state, secrets, or build artifacts are renamed or migrated. (Confirmed: scope is presentation-layer-only; no backend or data changes.)

## Common Pitfalls

### Pitfall 1: Optimistic clear hides a still-live position (SC#1)
**What goes wrong:** UI marks a position closed before the broker confirms; on broker rejection the operator believes it's closed while it's live.
**How to avoid:** `useMutation` with NO `setQueryData`; update only in `onSuccess` via `invalidateQueries`; button `disabled={isPending}`.
**Warning sign:** any `queryClient.setQueryData` in a close/partial/levels mutation.

### Pitfall 2: CSRF silently dropped on a mutation (SC#2)
**What goes wrong:** a fetch that bypasses `api()` won't carry `X-CSRF-Token` → 403.
**How to avoid:** ALL mutations go through `api()` (it echoes the header on POST/PUT/PATCH/DELETE). Never raw `fetch`.
**Warning sign:** a 403 on a mutation in dev; or a `fetch(` call outside `lib/http.ts`.

### Pitfall 3: Partial-close double-fire / wrong amount (D-04)
**What goes wrong:** retrying with a fresh `request_id` or with a percent model re-closes lots.
**How to avoid:** absolute lots + a stable `request_id` per intent; reuse the id on pure retries; handle 409.
**Warning sign:** `request_id` regenerated on every render; a "% of volume" input.

### Pitfall 5: Re-rounding server numbers (XAUUSD class bug)
**What goes wrong:** JS `toFixed` re-derives precision and corrupts pip-sized prices.
**How to avoid:** render `*_display`; submit bare numeric. Only footgun + elapsed are client calcs (off bare numerics, no re-rounding).
**Warning sign:** `toFixed`/`Intl.NumberFormat`/`Math.round` on a money/price field.

### Pitfall 6 (phase-specific): fixed_lot footgun shows a wrong compounded number
**What goes wrong:** multiplying `risk_value × max_stages` in fixed_lot mode displays e.g. "0.4 × 4 = 1.6 lots" when the operator's `risk_value` IS the 0.4 total.
**How to avoid:** branch the footgun calc on `risk_mode`; in fixed_lot show the absolute total, never multiply.
**Warning sign:** a single un-branched `risk_value * max_stages` in the footgun component.

### Pitfall 7 (phase-specific): treating validate's `valid:false` as an HTTP error
**What goes wrong:** `POST .../validate` returns **200** with `{valid:false, errors}`; catching it as a thrown error misses the field errors.
**How to avoid:** read the JSON body, branch on `data.valid`; only confirm opens the diff modal.
**Warning sign:** validate wired through `useMutation.onError` for cap failures.

### Pitfall 9 (UI-SPEC gate): transparent popover/dialog regression
**What goes wrong:** a shadcn dialog/select renders semi-transparent over the dark bg.
**How to avoid:** render dialog+select first, confirm opaque correct tokens, THEN wire mutations.

## Code Examples

### Mode-aware footgun (pure, testable)
```typescript
// Source: dashboard._compute_dry_run + trade_manager.py:108-117 (fixed_lot = total)
export function footgun(mode: "percent" | "fixed_lot", riskValue: number, maxStages: number) {
  if (mode === "percent") {
    const total = riskValue * maxStages; // compounds
    return `${maxStages} entries at ${riskValue}% risks up to ${total}% per signal.`;
  }
  // fixed_lot: riskValue is the TOTAL across stages — do NOT multiply
  return `This sizes up to ${riskValue} total lots per signal across ${maxStages} entries.`;
}
```

### Two-step settings flow
```typescript
// Source: api/settings.py validate (200 even on invalid) + confirm (re-validates)
const v = await api(`/api/v2/settings/${account}/validate`,
  { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ account, values }) }) as SettingsValidateResult;
if (!v.valid) { toast.error(`Couldn't save: ${Object.values(v.errors)[0]}`); return; }
// open ConfirmDiffDialog with v.diff + v.dry_run_text (+ restated footgun)
// on Confirm: POST /api/v2/settings/${account} {account, values} → toast.success(`Settings saved for ${account}.`)
```

## State of the Art

| Old Approach (legacy HTMX) | Current Approach (Phase 11 SPA) | Impact |
|----------------------------|----------------------------------|--------|
| `hx-confirm` blocking browser dialog | inline two-click confirm (D-03) | styleable, testable, recoverable |
| partial-close percent-of-volume | absolute lots + request_id (D-04) | kills the 75% double-fire trap |
| OOB toast HTML fragments (`_render_toast_oob`) | sonner toasts | viewport-level, decoupled from response HTML |
| HTML confirm modal returned from server | JSON `{valid,errors,diff,dry_run_text}` → client modal | server/form-state split; no refresh-race |
| SSE `/stream` for pending-stages flash | 3s TanStack Query poll | no Node/SSE runtime dep (deferred to Phase 12 removal) |
| per-row revert by `audit_id` | revert latest-only (API limitation) | see Open Question 1 |

**Deprecated/outdated:** zod v3 snippets (project is on v4); `@hookform/resolvers` v3/v4 import paths; any percent-based partial-close UI.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `react-hook-form` 7.77.0 is legitimate/safe | Standard Stack | slopcheck unavailable; mitigated by mature official repo + npm run build gate |
| A2 | `zod` 4.4.3 v4 API (`superRefine`/`z.enum`) matches sketch | Settings Caps | wrong v4 signature → TS build error (caught fast); adjust at install |
| A3 | `@hookform/resolvers` 5.4.0 exports `zodResolver` from `/zod` | Standard Stack | wrong import → build error; confirm path at install |
| A4 | Drilldown payload keys (`fill_history`, `signal`) stable as in positions.py | Contracts | drilldown render gap; verify against a live response in dev |

## Open Questions

1. **Audit revert granularity mismatch (parity vs contract).**
   - What we know: legacy `settings_audit_timeline.html` renders a per-row "Revert change" button posting `?audit_id={row.id}`. The Phase 8 `POST /settings/{account}/revert` reverts ONLY the latest persisted change and takes NO `audit_id` (api/settings.py:259-305).
   - What's unclear: whether the SPA should (a) show a single "Revert last change" action (matches the shipped API, no new endpoint), or (b) show per-row Revert buttons but only enable it on the newest row.
   - Recommendation: **(a) or (b)-enabled-on-newest-only.** Do NOT add an `audit_id` endpoint — that violates the hard boundary (no new endpoints). The UI-SPEC copy "Revert (per-row; opens revert confirm)" should be implemented as revert-latest. Flag for the planner; lean to a single "Revert last change" + confirm toast, which is unambiguous and contract-faithful.

2. **Overview pending-stages source.**
   - What we know: legacy overview embedded pending-stages via SSE `/stream`. Phase 11 is poll-only; `GET /api/v2/stages` exists (PAGE-04 shipped) and `StagedView` already consumes it.
   - Recommendation: reuse `GET /api/v2/stages` (top-5 active) on the Overview poll. No new endpoint needed. (Claude's discretion per CONTEXT.)

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node/npm (build) | Vite build, shadcn add | ✓ (Dockerfile node:22 build stage; local needed for dev) | — | — |
| npm registry (rhf/zod/resolvers) | SUX-03 forms | ✓ | confirmed via `npm view` | — |
| shadcn CLI | dialog/tooltip/select/badge/popover | ✓ (`components.json` present) | new-york/neutral | manual component paste (last resort) |
| Phase 8 `/api/v2` running | all pages | ✓ (shipped) | — | — |
| Python 3.12 container | backend pytest contract tests | ✓ (per MEMORY `project_local_dashboard_verification.md`) | 3.12 | — |
| MT5 demo / live bot | live SC verification (close/partial fire) | ✗ locally (Telegram session conflict — run dashboard standalone) | — | Manual SC checks on VPS w/ MT5 demo; local = build + zod unit + read-only |

**Missing with no fallback:** none blocking. Live money-mutation SC (actual broker close) require the VPS+MT5-demo manual gate (per MEMORY: verify SPA locally WITHOUT full bot.py; full money-path verification is a VPS UAT step).

## Validation Architecture

> nyquist_validation is enabled. This project has **backend pytest** + **`npm run build` as the type/compile gate** + **manual browser SC checks** (no JS test runner yet — same model as Phase 9/10). Phase 11 adds NO endpoints, so the Phase 8 contract tests already gate the server side. The new automated surface is the **zod cap schema + footgun calc as pure-function Vitest units** (highest-value, fast, deterministic).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Backend: `pytest` (`pyproject.toml [tool.pytest.ini_options] testpaths=["tests"]`). Frontend: `vitest` (NEW — Wave 0; one unit file for zod+footgun) + `npm run build` as the TS gate |
| Config file | Backend: `pyproject.toml`. Frontend: none yet — add minimal `vitest` config (or `vite` test field) in Wave 0 |
| Quick run command | `cd frontend && npm run build` (per task) + `cd frontend && npx vitest run src/lib/settingsSchema.test.ts` once it exists |
| Full suite command | `pytest tests/ -x` + `cd frontend && npm run build && npx vitest run` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SC#1 | Close/partial/levels never optimistic; UI updates only on success | manual (browser, MT5 demo) | Click Close; confirm row clears only after server 200; on forced error, modal stays open | manual |
| SC#2 | Every mutation 403s without CSRF | integration (already green) | `pytest tests/test_api_csrf.py -x` | ✅ exists |
| SC#3 | Open Edit modal / drilldown survives ≥2 refetch cycles | manual (browser) | Type SL, leave modal open, watch ≥2 × 3s polls, confirm input intact | manual (proven by Phase 9 probe) |
| SC#4 | Partial-close idempotency 409 on id-reuse-diff-params; kill-switch two-step | integration (already green) + manual | `pytest tests/test_api_idempotency.py -x`; manual kill-switch preview→confirm | ✅ exists + manual |
| SUX-03 | zod caps mirror server (mode-aware + per-account max_lot_size) | unit (NEW) | `npx vitest run src/lib/settingsSchema.test.ts` | ❌ Wave 0 |
| SUX-02/D-07 | footgun: percent compounds ×stages; fixed_lot = total (no multiply) | unit (NEW) | `npx vitest run src/lib/footgun.test.ts` | ❌ Wave 0 |
| SUX-01 | sonner success/rejection/revert toasts | manual (browser) | Save→success toast; cap-breach→rejection toast; revert→revert toast | manual |
| PAGE-05..08 | render + TS-shape parity to contracts | build/smoke | `cd frontend && npm run build` (TS strict catches shape drift) | ✅ (build) |
| Settings validate/confirm/revert contract | (already green) | integration | `pytest tests/test_api_settings.py -x` | ✅ exists |

### Sampling Rate
- **Per task commit:** `cd frontend && npm run build` (fast TS/Tailwind/Vite gate).
- **Per wave merge:** `pytest tests/ -x` + `cd frontend && npm run build && npx vitest run`.
- **Phase gate:** full backend suite green; zod+footgun units green; all SC manually verified in browser (live money-path SC on VPS+MT5 demo).

### Wave 0 Gaps
- [ ] `frontend` test runner: add `vitest` (+ minimal config) — the only framework gap.
- [ ] `frontend/src/lib/settingsSchema.test.ts` — asserts the mode-aware caps match `validate_settings_form` (percent ≤5.0, fixed_lot ≤ max_lot_size, ints 1-10/1-500/1-100). Covers SUX-03.
- [ ] `frontend/src/lib/footgun.test.ts` — asserts percent multiplies, fixed_lot does NOT. Covers SUX-02/D-07/Pitfall-6.
- [ ] No new backend tests needed — Phase 8 contract tests (`test_api_csrf`, `test_api_idempotency`, `test_api_settings`, `test_settings_form`) already cover the server side (no endpoints added).

## Project Constraints (from CLAUDE.md)

`/Users/murx/CLAUDE.md` is a Figma-MCP workflow guide oriented to a Vue 3/Nuxt/shadcn-vue stack. **It does NOT apply to this React 19 SPA** — there is no project-local `./CLAUDE.md` in the telebot repo, and this phase uses React + shadcn (radix), not Vue. The only transferable directives:
- Download Figma assets locally as SVG with kebab-case names if Figma is used (no Figma in this phase — UI-SPEC is the design contract).
- Reuse existing components/composables instead of duplicating (aligns with Don't-Hand-Roll).
- WCAG accessibility (dialog a11y via radix; role="alert" on validation errors per UI-SPEC).

**Project MEMORY directives (authoritative for this repo):**
- No `Co-Authored-By` lines in commits (do not add).
- Don't commit prematurely — wait for the operator to test and confirm.
- Give VPS/docker commands as copy-paste text, don't run locally.
- `fixed_lot` `risk_value` = TOTAL across max_stages (operator-confirmed) — drives D-07.
- Verify dashboard locally WITHOUT full `bot.py` (Telegram session conflict); tests need a Python 3.12 container.

## Sources

### Primary (HIGH confidence — read directly this session)
- `api/actions.py`, `api/meta.py`, `api/positions.py`, `api/settings.py`, `api/schemas.py`, `api/errors.py` — exact contracts
- `dashboard.py:658-790` — `validate_settings_form`, `_SETTINGS_HARD_CAPS_INT`, `_compute_dry_run`
- `settings_store.py`, `trade_manager.py:108-117,690-691` — fixed_lot total-across-stages semantic
- `frontend/src/lib/http.ts`, `lib/queryClient.ts`, `auth/csrf.ts`, `components/data/DataTable.tsx`, `routes/StagedView.tsx`, `routes/router.tsx` — inherited infra + patterns
- `templates/overview.html`, `overview_cards.html`, `positions_table.html`, `edit_levels_modal.html`, `position_drilldown.html`, `kill_switch_preview.html`, `account_settings_tab.html`, `settings_confirm_modal.html`, `settings_audit_timeline.html` — parity targets
- `11-CONTEXT.md`, `11-UI-SPEC.md`, `REQUIREMENTS.md`, `STATE.md`, `09-VALIDATION.md` — locked decisions + validation model
- `npm view` (react-hook-form 7.77.0, zod 4.4.3, @hookform/resolvers 5.4.0) — version + repo + created date

### Secondary (MEDIUM)
- MEMORY files (`project_lot_semantics.md`, `project_local_dashboard_verification.md`) — operator-confirmed semantics

### Tertiary (LOW)
- none — every claim is source-derived

## Metadata

**Confidence breakdown:**
- Server contracts: HIGH — pinned from actual source
- Settings caps + footgun: HIGH — derived from `validate_settings_form` + `trade_manager` + operator confirmation
- Inherited infra/patterns: HIGH — read the shipped files
- New package versions: MEDIUM — registry-confirmed but slopcheck unavailable + zod v4 API needs install-time confirmation
- Validation model: HIGH — matches Phase 9/10 established approach

**Research date:** 2026-06-07
**Valid until:** 2026-07-07 (stable; contracts are shipped and frozen by the no-new-endpoints boundary)

## RESEARCH COMPLETE

**Phase:** 11 - Live-money Pages + Settings
**Confidence:** HIGH

### Key Findings
- Every contract is pinned from source: close/levels/close-partial (incl. 409 replay), overview/trading-status/emergency-preview, settings GET/validate(200-on-invalid)/confirm(re-validates)/revert(latest-only). Error envelope is `{error:{code,message,fields?}}`; success bodies are bare.
- The exact mode-aware caps come from `dashboard.validate_settings_form` (percent: risk_value ≤5.0; fixed_lot: risk_value ≤ per-account `max_lot_size`; ints 1-10/1-500/1-100). The zod schema reads `max_lot_size` from the SettingsView `values` to build the fixed_lot branch.
- **fixed_lot `risk_value` is the TOTAL across stages** (confirmed in `trade_manager.py` + the server's own `_compute_dry_run` divides by max_stages in both modes) — the footgun MUST NOT multiply by max_stages in fixed_lot mode.
- The poll-safe modal (SC#3) needs no new mechanism: TanStack-Query server state + react-hook-form/local form state + Dialog portal outside the poll subtree — proven live in Phase 9's probe.
- Validation: no new backend endpoints → Phase 8 pytest contract tests already gate the server; the new automated proof is two pure-function Vitest units (zod caps + footgun). Vitest is the only Wave-0 framework gap. Live money-path SC are a VPS+MT5-demo manual gate.

### File Created
`/Users/murx/Developer/personal/telebot/.planning/phases/11-live-money-pages-settings/11-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Standard Stack | HIGH (MEDIUM on new pkg API) | Installed deps verified; new pkgs registry-confirmed but zod v4 API needs install-time check |
| Architecture | HIGH | Patterns read from shipped StagedView/http/queryClient |
| Pitfalls | HIGH | Derived from STATE.md pitfalls + source semantics |

### Open Questions
1. Audit revert granularity: legacy per-row `audit_id` vs API revert-latest-only — recommend single "Revert last change" (no new endpoint).
2. Overview pending-stages: reuse `GET /api/v2/stages` top-5 (no new endpoint).

### Ready for Planning
Research complete. Planner can create PLAN.md files; contracts, caps, footgun math, parity targets, and validation map are all pinned.
