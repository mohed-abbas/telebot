# Phase 11: Live-money Pages + Settings - Context

**Gathered:** 2026-06-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Bring the **four highest-blast-radius SPA surfaces** to parity using the money-safe
mutation discipline established in Phase 9 — the UI changes state **only** after the
server confirms success, every mutation carries CSRF, destructive buttons are
disabled-while-pending, and client-side zod validation mirrors the server hard caps.

In scope (PAGE-05..08, SUX-01..04):
1. **Overview page** (PAGE-05) — parity with live polling: positions table +
   pending-stages card + kill-switch entry + TRADING PAUSED banner. A background
   refetch through ≥2 cycles must never clobber an open positions drilldown or
   edit-levels modal (SC#3).
2. **Positions page** (PAGE-06) — the 4 live-money actions (close, modify SL+TP,
   partial-close) with server-confirmed mutations only (no optimistic clear),
   disabled-while-pending, error toasts.
3. **Emergency kill switch** (PAGE-07) — two-step preview → confirm flow (confirm
   disabled-while-pending). Partial-close uses absolute target volume + request-id so
   a double-fire cannot close the wrong amount.
4. **Settings page** (PAGE-08, SUX-01..04) — per-account form, two-step
   dangerous-change confirmation rendering a diff, audit timeline, revert, viewport
   sonner toasts, per-field help/tooltips incl. the live compounded-exposure footgun
   warning, react-hook-form + zod validation mirroring server hard-caps (mode-dependent
   and per-account `risk_value` caps), and operator-legible copywriting.

**This phase is the SPA *consumer* of the already-shipped Phase 8 JSON API.** The
entire mutation/read contract exists (`api/actions.py`, `api/meta.py`,
`api/settings.py`, `api/positions.py`). Phase 11 builds React pages; it does **not**
add endpoints.

**Out of this phase (hard boundary):**
- ANY new JSON API endpoint → Phase 8 (done). If a page needs a read/mutation, it
  reuses what Phase 8 shipped. (The Phase-10 read-only widenings were the last allowed
  serialization-only extensions; Phase 11 adds none.)
- ANY change to the bot core (`executor.py`, `trade_manager.py`, `db.py` write paths,
  `mt5_connector.py`, MT5 bridge) — unchanged; v1.2 confines blast radius to
  presentation.
- Removing legacy HTMX routes / SSE `/stream` / legacy Tailwind-CLI stage → Phase 12.
  Legacy dashboard keeps running at `/` in parallel throughout Phase 11.

</domain>

<locked_invariants>
## Locked Invariants (NOT gray areas — carried forward, do not re-litigate)

These are fixed by the ROADMAP success criteria and Phase 8/9 conventions. They
constrain HOW every decision below is implemented:

- **Server-confirmed mutations only** (SC#1): on positions, close / modify SL+TP /
  partial-close update or clear the UI **only** on server-confirmed success — no
  optimistic clear. On error the modal stays open with typed values preserved and
  surfaces the error toast. Every destructive button is disabled-while-pending so a
  position can never appear closed while still live at the broker. (Pitfall 1.)
- **CSRF on every mutation** (SC#2): every live-money POST (close, levels,
  partial-close, kill-switch confirm, settings confirm/revert) carries the
  `X-CSRF-Token` double-submit header (readable `telebot_csrf` cookie echoed) and is
  rejected `403` without it — verified against the Phase 8 regression test.
  (Phase 8 D-15/D-16, Phase 9 D-04/D-06.)
- **partial-close contract** (Phase 8 D-09/D-10/D-11): request body carries
  `close_volume` in **absolute lots**, validated `0 < close_volume < pos.volume` and
  rounded to lot step, plus a **client-generated UUID `request_id`**. Same id + same
  params → replay cached 200 (no broker hit); same id + different params → **409**.
- **`*_display` render / bare-numeric submit** (Phase 8 D-05, Pitfall 5): SPA renders
  the server-formatted `*_display` field, submits the bare numeric, never re-rounds.
  The compounded-exposure number is a client *calc* off two bare numerics (not
  re-rounding server money/prices), so it is Pitfall-5-safe.
- **Polling, not SSE** (Phase 9 D-09): live views use TanStack Query `refetchInterval`
  with `refetchIntervalInBackground:false` + `placeholderData:keepPreviousData`.
  Server state = TanStack Query; form/UI state = react-hook-form/local — never mixed.
  Open modals/drilldowns live **outside the polling subtree** (the legacy
  `#modal-root` pattern) so refetch cannot clobber typed input (SC#3).
- **Shared primitives inherited from Phase 10** (Phase 10 D-10/D-11): reuse the
  `DataTable` (`frontend/src/components/data/DataTable.tsx`) + Loading/Empty/Error
  trio for the Overview/Positions tables; read-load failures render an inline panel,
  not a toast (D-11) — but live-money *action* feedback IS a toast (sonner).

</locked_invariants>

<decisions>
## Implementation Decisions

### Positions action surface (PAGE-06)
- **D-01:** **Mirror the legacy positions shape 1:1.** Each row has a destructive
  **Close** button + an **Edit** button that opens **one combined modal** (SL/TP
  modify AND partial-close), plus an **expandable drilldown** row. Parity targets:
  `templates/partials/positions_table.html`, `edit_levels_modal.html`,
  `position_drilldown.html`. The Edit modal renders **outside the polling subtree**
  (legacy `#modal-root` pattern) so background refetch never clobbers typed values
  (satisfies SC#3 for the modal; the drilldown must likewise survive refetch).
- **D-02:** Inside the combined Edit modal, modify-SL/TP and partial-close are **two
  independent submits** — each its own button, own pending/disabled state, own CSRF
  call, own toast. **Save SL/TP** → `POST /api/v2/positions/{account}/{ticket}/levels`;
  **Close lots** → `POST /api/v2/positions/{account}/{ticket}/close-partial`. The modal
  stays open on either error (typed values preserved); closes only on server-confirmed
  success. No single combined Save — that would create ambiguous partial-success states
  and risk mis-firing a close. Maps cleanly to the two distinct endpoints.

### Destructive-action confirm friction (PAGE-06)
- **D-03:** Per-position **Close** and the partial-close **Close lots** action use an
  **inline two-click confirm** — first click morphs the button into a
  "✓ Confirm close #ticket? / ✕" in-place state (or a small confirm popover); the
  second click fires (disabled-while-pending). This replaces the legacy
  `hx-confirm()` blocking browser dialog (`positions_table.html:43`) with an in-app,
  styleable, testable guard. A misclick is recoverable (Cancel) without a full modal.
  *(The kill-switch two-step preview→confirm is a separate, already-locked flow — see
  D-06; this decision is only about the individual position buttons.)*

### Partial-close input model (PAGE-06)
- **D-04:** The operator **types the absolute lots to CLOSE directly** (exactly what
  the API wants — no client-side percent conversion). The UI shows current volume + a
  live **"remaining after: X.XX"** readout, and zod-validates `0 < value < volume`
  rounded to the symbol lot step. **No percent/slider model** — the absolute-lots
  design is precisely what killed the percent-of-current "75% trap" (Phase 8 D-09 /
  Pitfall 3); the UI must not re-introduce the percent mental model. A
  client-generated UUID `request_id` accompanies each submit (Phase 8 D-10).

### Settings confirm scope + footgun (PAGE-08, SUX-01..04)
- **D-05:** **Every settings change runs the two-step validate→confirm-diff flow**,
  regardless of field. On a live-money settings page every field ultimately shapes
  risk, so a uniform "review the diff + dry-run before it persists" gate is simplest
  to reason about and impossible to mis-categorize (no "dangerous field" allow-list to
  maintain). Flow: edit → Save → `POST /settings/{account}/validate` (returns
  `{valid, errors, diff, dry_run_text}`) → render confirm modal with the diff +
  dry-run → Confirm → `POST /settings/{account}` (re-validates server-side). Toasts:
  sonner success on confirm, explicit rejection toast on validation failure, revert
  confirmation toast (SUX-01).
- **D-06:** The **compounded-exposure footgun warning (SUX-02) shows in BOTH places**:
  (a) **inline, recomputed live** as the operator edits `risk_value` or `max_stages`
  (near the fields), and (b) **restated in the confirm-diff modal** before persisting.
  Caught while typing AND at the final gate. The compounded value is derived
  client-side from the two bare numeric fields (a calc, not re-rounding server money —
  Pitfall-5-safe).
- **D-07:** **The footgun math and the zod caps are MODE-AWARE** (SUX-03 "mode-dependent
  ... `risk_value` caps"):
  - **percent / risk mode** → exposure compounds: warn on `max_stages × risk_value`
    (e.g. 2% × 4 = ~8%).
  - **`fixed_lot` mode** → `risk_value` is the **TOTAL across `max_stages`, NOT
    per-trade** (operator-confirmed 2026-05-01). So **do NOT multiply by `max_stages`**;
    warn on the absolute total instead.
  zod client caps likewise switch on mode and **mirror the server's mode-dependent +
  per-account caps** — the planner must read the server validation core
  (`api/settings.py` `_validate` + `SettingsStore`/`store.effective`) to derive the
  exact caps rather than hardcode. The naive "max_stages × risk_value" wording in the
  SUX-02 requirement text is a percent-mode illustration only; the implementation must
  not display a wrong compounded number in fixed_lot mode.

### Claude's Discretion (planner/researcher decides)
- Exact Overview composition: whether the positions table on Overview reuses the full
  Positions-page table or a condensed view; the kill-switch entry-point treatment
  (button → kill-switch page/modal); how the TRADING PAUSED banner + pending-stages
  card compose. (Parity reference: `templates/overview.html`,
  `partials/overview_cards.html`.)
- Kill-switch page structure for the (already-locked) two-step preview→confirm:
  `GET /api/v2/emergency/preview` → render preview → `POST /api/v2/emergency/close`
  (confirm disabled-while-pending); resume via `POST /api/v2/emergency/resume`.
  Parity ref: `templates/partials/kill_switch_preview.html`.
- Settings audit-timeline + revert UX detail: how the timeline renders
  (`SettingsView` payload, parity ref `partials/settings_audit_timeline.html`) and how
  revert (`POST /settings/{account}/revert`, inverts the latest persisted change) is
  triggered/confirmed. Revert is itself a CSRF mutation with a confirmation toast.
- Whether multiple position drilldowns can be open at once (legacy allowed it) and the
  exact mechanism that keeps an open drilldown alive across a background refetch.
- The inline-confirm rendering detail (in-place button morph vs small popover) for D-03.
- Per-field copywriting (SUX-04): mapping DB-column names → operator mental models with
  units, on labels/placeholders/confirmation text. Parity baseline:
  `templates/account_settings_tab.html`.
- Which shadcn components each page adds via the CLI (per Phase 9 D-11 — keep lean),
  and where shared live-money components/hooks live under `frontend/src`.
- Exact `refetchInterval`/`staleTime` numbers per page within the Phase-9 D-09 frame
  (overview ~3000ms target).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & milestone scope
- `.planning/REQUIREMENTS.md` §PAGE — PAGE-05..PAGE-08 — and §SUX — SUX-01..SUX-04
  (the 8 requirements this phase delivers).
- `.planning/ROADMAP.md` Phase 11 — goal + 5 success criteria (esp. SC#1 server-confirmed
  mutations, SC#2 CSRF, SC#3 poll-safe drilldown/modal, SC#4 kill-switch + partial-close,
  SC#5 settings) + Research flag (partial-close shape note) + UI hint.
- `.planning/PROJECT.md` §Current Milestone (v1.2) + §Key Decisions — locked stack
  (React 19 · Vite · shadcn/ui · Tailwind v4), presentation-layer-only blast radius,
  parallel-run + page-by-page reversible cutover, httpOnly session-cookie + CSRF.
- `.planning/STATE.md` §Blockers/Concerns — Pitfall 1 (no optimistic updates),
  Pitfall 2 (CSRF), Pitfall 3 (partial-close idempotency), Pitfall 5 (server-side
  formatting) — all four bite this phase directly.

### Phase 8 contract this phase CONSUMES (already shipped — read for exact shapes)
- `api/actions.py` — `POST /positions/{account}/{ticket}/close` (`MutationResult`),
  `/levels`, `/close-partial` (absolute volume + request_id), `/emergency/close`
  (`EmergencyResult`), `/emergency/resume`. The live-money mutation surface.
- `api/meta.py` — `GET /overview` (`OverviewMeta`), `GET /trading-status`
  (`TradingStatus` — TRADING PAUSED banner source), `GET /emergency/preview`
  (`EmergencyPreview` — kill-switch step-1 source).
- `api/positions.py` — `GET /positions` (`list[Position]`), `GET /positions/{account}/{ticket}`
  (drilldown).
- `api/settings.py` — `GET /settings/{account_name}` (`SettingsView`),
  `POST /settings/{account_name}/validate` (`{valid, errors, diff, dry_run_text}`),
  `POST /settings/{account_name}` (confirm — re-validates server-side),
  `POST /settings/{account_name}/revert`. **`_validate` + `store.effective` are the
  source of truth for the mode-dependent + per-account caps zod must mirror (D-07).**
- `api/schemas.py` — `MutationResult`, `EmergencyResult`, `EmergencyPreview`,
  `Position`, `OverviewMeta`, `TradingStatus`, `SettingsView`, `SettingsValidateResult`.
- `.planning/phases/08-json-api-foundation/08-CONTEXT.md` — D-05 dual-value `*_display`,
  D-09/D-10/D-11 partial-close absolute-volume + request_id + 409 semantics, D-15/D-16
  CSRF mechanism + required regression test.

### Phase 9 conventions this phase INHERITS (do NOT re-decide)
- `.planning/phases/09-spa-scaffold-auth-design-system/09-CONTEXT.md` — D-06 global 401
  handler, D-08 server-state/form-state split (the structural HTMX-race kill — SC#3),
  D-09 QueryClient defaults (`keepPreviousData`, `refetchIntervalInBackground:false`,
  global `onAuthError`), D-10 `destructive` token ready for live-money buttons, D-11
  per-page shadcn adds, D-04 fetch wrapper echoing `X-CSRF-Token`.

### Phase 10 shared primitives this phase REUSES
- `.planning/phases/10-read-only-page-migration-analytics-pilot-signals-history-sta/10-CONTEXT.md`
  — D-10 shared `DataTable` + Loading/Empty/Error trio, D-11 inline error panel for
  read-load failure (vs toast for action feedback).
- `frontend/src/components/data/DataTable.tsx` — the shared table the
  Overview/Positions tables compose.
- `frontend/src/routes/*` + `router.tsx` + `frontend/src/lib/{http,queryClient}.ts` —
  the shell/router/fetch-wrapper the live-money pages slot into.

### Legacy parity references (the SPA must match these on live data)
- `templates/overview.html` + `templates/partials/overview_cards.html` — Overview
  parity target (positions table + pending-stages + kill-switch entry + PAUSED banner).
- `templates/positions.html` + `partials/positions_table.html` +
  `partials/edit_levels_modal.html` + `partials/position_drilldown.html` — Positions
  parity target (row Close + Edit modal + drilldown).
- `templates/partials/kill_switch_preview.html` — kill-switch two-step parity target.
- `templates/settings.html` + `partials/account_settings_tab.html` +
  `partials/settings_confirm_modal.html` + `partials/settings_audit_timeline.html` —
  Settings parity target (form + confirm-diff modal + audit timeline + revert).

### v1.2 research synthesis
- `.planning/research/ARCHITECTURE.md` §4 (live data transport — polling), §"Anti-Patterns"
  (5 = no WebSocket/SSE).
- `.planning/research/PITFALLS.md` — Pitfall 1, 2, 3, 5 (all four apply here).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Entire Phase-8 live-money JSON API** — `api/actions.py`, `api/meta.py`,
  `api/positions.py`, `api/settings.py` ship every read + mutation this phase needs.
  Phase 11 writes React, not endpoints.
- **Phase-10 `DataTable` + state trio** (`frontend/src/components/data/DataTable.tsx`)
  — Overview/Positions tables compose them; mono numerics + color-by-sign for P&L
  already proven.
- **Phase-9 fetch wrapper + QueryClient** (`frontend/src/lib/{http,queryClient}.ts`)
  — already echoes `X-CSRF-Token`, has global `onAuthError`, `keepPreviousData`,
  no-background-poll-when-hidden.
- **`MutationCache` global 401** (Phase 9 D-06) — live-money mutation errors flow
  through it; per-mutation toasts layer on top.
- **Legacy `#modal-root` outside-polling pattern** — the edit-levels modal already
  lives outside the 3s polling div in HTMX (`edit_levels_modal.html` header comment);
  the SPA replicates this structurally via the server-state/form-state split.

### Established Patterns
- **Server-confirmed, disabled-while-pending, no optimistic** — the money-safe
  mutation discipline; the SPA's TanStack `useMutation` `isPending` drives button
  disable + the UI updates only in `onSuccess`.
- **`*_display` render / bare submit** — every money/price/volume field.
- **Mode-dependent settings validation** — the server `_validate` already enforces
  mode-dependent + per-account caps; the zod client schema mirrors it (does not invent
  caps).

### Integration Points
- New live-money pages under `frontend/src/routes/*` (Overview, Positions, KillSwitch,
  Settings) slotting into the Phase-9 shell routes.
- `useMutation` hooks wrapping the `api/actions.py` + `api/settings.py` POSTs, each
  generating a `request_id` (partial-close) and reading `telebot_csrf` for the header.
- react-hook-form + zod schemas (Settings, edit-levels, partial-close) co-located with
  their forms; zod caps derived from `api/settings.py` `_validate` semantics.

</code_context>

<specifics>
## Specific Ideas

- **"Mirror the legacy positions shape."** Row Close + one combined Edit modal (SL/TP +
  partial) + expandable drilldown — 1:1 with the legacy templates, modal outside the
  polling subtree.
- **"Two independent submits in the Edit modal."** SL/TP and partial-close are
  different endpoints; never one ambiguous Save.
- **"Inline two-click confirm, not a browser dialog."** Replace `hx-confirm` with an
  in-app button-morph guard on Close / Close lots.
- **"Type absolute lots, show remaining-after."** No percent/slider — the absolute
  contract is the anti-75%-trap design; don't re-introduce percents in the UI.
- **"Every settings change confirms."** Uniform validate→diff→confirm; no
  dangerous-field allow-list.
- **"Footgun warning in both places, and it's mode-aware."** Inline-while-editing AND
  in the confirm diff; percent mode compounds ×stages, fixed_lot treats `risk_value`
  as the total (operator-confirmed 2026-05-01) — never show a wrong compounded number.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. Overview composition, kill-switch page
structure, audit-timeline/revert UX, and drilldown-multi-open mechanics were left to
planner discretion (within the locked invariants), not deferred to other phases.
Legacy-route / SSE `/stream` / Tailwind-CLI removal remains Phase 12.

</deferred>

---

*Phase: 11-live-money-pages-settings*
*Context gathered: 2026-06-07*
