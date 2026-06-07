# Phase 11: Live-money Pages + Settings - Pattern Map

**Mapped:** 2026-06-07
**Files analyzed:** 16 new files + 2 modified (router.tsx, Sidebar.tsx)
**Analogs found:** 14 with a real code analog / 16 new files (2 are genuinely-new patterns with only a structural reference)

> This phase is a **React 19 + Vite + TanStack Query + shadcn SPA consumer phase**. Almost every
> "hard" mechanism (fetch wrapper, CSRF echo, global 401, polling defaults, DataTable, state trio)
> is already shipped in Phases 9/10. The new code is **page compositions + mutation hooks + rhf/zod
> forms + two pure-function utils**. Analog files below are all in `frontend/src/`; the legacy
> `templates/partials/*.html` are **parity references only** (structure/copy to replicate), NOT code
> to copy — translate HTMX → React per the inherited patterns.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `routes/OverviewView.tsx` | route/page | request-response (poll) | `routes/StagedView.tsx` | exact (polling read page) |
| `routes/PositionsView.tsx` | route/page | request-response (poll) + CRUD | `routes/StagedView.tsx` + `DataTable` | exact (poll) / role-match (actions) |
| `routes/KillSwitchView.tsx` | route/page | request-response (read→mutate) | `routes/StagedView.tsx` (read) + `LoginView.tsx` (submit-on-confirm) | role-match |
| `routes/SettingsView.tsx` | route/page | request-response (read→validate→confirm) | `routes/StagedView.tsx` (read) + `LoginView.tsx` (form submit) | role-match |
| `components/positions/EditPositionDialog.tsx` | component (modal) | event-driven (2 submits) | `edit_levels_modal.html` (parity) + shadcn `dialog` | role-match (structure) / new (dialog) |
| `components/positions/InlineConfirm.tsx` | component | event-driven | `button.tsx` variants (composes) | **no direct analog** — new (button-morph/popover) |
| `components/positions/PositionDrilldown.tsx` | component | request-response (poll) | `StagedView.tsx` `StageCard` + `DataTable` | role-match |
| `components/settings/SettingsForm.tsx` | component (form) | transform (rhf+zod) | `LoginView.tsx` (form shape, but rhf is new) | partial / **new (rhf+zod)** |
| `components/settings/ConfirmDiffDialog.tsx` | component (modal) | event-driven | `settings_confirm_modal.html` (parity) + shadcn `dialog` | role-match (structure) / new (dialog) |
| `components/settings/AuditTimeline.tsx` | component | request-response | `DataTable.tsx` + `StagedView` resolved table | exact |
| `hooks/useClose.ts` (close mutation) | hook | CRUD (mutation) | **`Sidebar.tsx` signOut** (only existing mutation) + `lib/http.ts` | partial — closest is `signOut`; `useMutation` itself is new |
| `hooks/useLevels.ts` (modify SL/TP) | hook | CRUD (mutation) | same as above | partial / new |
| `hooks/usePartialClose.ts` (partial-close + request_id) | hook | CRUD (mutation, idempotent) | same as above | partial / new |
| `hooks/useEmergency.ts` (close/resume) | hook | CRUD (mutation) | same as above | partial / new |
| `hooks/useSettingsMutations.ts` (validate/confirm/revert) | hook | CRUD (mutation) | same as above | partial / new |
| `lib/footgun.ts` | utility (pure fn) | transform | `lib/useElapsed.ts` (pure-ish client calc precedent) | role-match |
| `lib/settingsSchema.ts` | utility (zod schema) | transform | **no analog** — new (first zod in repo) | **none** |
| `lib/settingsSchema.test.ts` / `lib/footgun.test.ts` | test (vitest) | — | **no analog** — new (first JS test runner) | **none** |
| `routes/router.tsx` (MODIFY) | config/router | — | itself (existing routes) | exact |
| `components/shell/Sidebar.tsx` (MODIFY) | component (nav) | — | itself (NAV_ENTRIES) | exact |

---

## Shared Patterns

These cross-cutting patterns apply to **every** new file and must be copied verbatim from the
cited shipped sources. The planner should reference these once and not re-derive them per-plan.

### Shared 1: The `api()` fetch wrapper — every queryFn AND mutationFn (CSRF auto-echo)
**Source:** `frontend/src/lib/http.ts` (lines 46-74, esp. 50-53)
**Apply to:** ALL hooks and pages. Never call raw `fetch` (Pitfall 2 = silent CSRF drop → 403).

```typescript
// lib/http.ts:46-59 — the ONE fetch path. Echoes X-CSRF-Token on POST/PUT/PATCH/DELETE only,
// attaches the httpOnly session cookie via credentials:"same-origin", throws HttpError on non-2xx.
export async function api(path: string, init: RequestInit = {}): Promise<unknown> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (STATE_CHANGING_METHODS.has(method)) {            // POST/PUT/PATCH/DELETE
    headers.set("X-CSRF-Token", readCookie("telebot_csrf"));   // double-submit echo (SC#2)
  }
  const res = await fetch(path, { ...init, headers, credentials: "same-origin" });
  if (!res.ok) { /* parse {error:{code,message,fields?}} */ throw new HttpError(res.status, body); }
  ...
}
```
- **Mutation body convention** (from `LoginView.tsx:52-57`): `{ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({...}) }`. CSRF header is added automatically — do NOT set it manually.
- `HttpError` (`http.ts:15-25`) carries `.status` and `.body` — branch on `e.status === 409` (partial-close conflict) / `=== 422` etc.

### Shared 2: Error message extraction from the `{error:{code,message,fields?}}` envelope
**Source:** `frontend/src/components/state/ErrorPanel.tsx` `errorMessage()` (lines 27-36) — **already exported, reuse it directly** for mutation toasts too.
**Apply to:** every mutation `onError` (sonner toast) and every read `ErrorPanel`.

```typescript
// ErrorPanel.tsx:27-36 — DO NOT re-implement messageFromEnvelope; import this.
export function errorMessage(error: unknown): string {
  if (error instanceof HttpError) {
    const body = error.body as { error?: { code?: string; message?: string } } | undefined;
    const msg = body?.error?.message;
    if (typeof msg === "string" && msg.trim()) return msg;
    return `Request failed (HTTP ${error.status}).`;
  }
  ...
}
```
- Read failures → inline `<ErrorPanel error={error} onRetry={() => refetch()} />` (D-11, NOT a toast).
- Mutation failures → `toast.error(errorMessage(e))` (D-11, IS a toast). 401 never reaches either — global `onAuthError` redirects first.

### Shared 3: Global 401 + inherited polling defaults (you get these for free)
**Source:** `frontend/src/lib/queryClient.ts` (lines 42-61)
**Apply to:** all `useQuery`/`useMutation` — **do nothing**; the defaults are already wired.
- `placeholderData: keepPreviousData` (no flicker on refetch) + `refetchIntervalInBackground:false` (poll pauses on hidden tab) + `retry:false` + global `onAuthError` on BOTH QueryCache and MutationCache. Each page only sets its own `refetchInterval` (e.g. `3000`).

### Shared 4: sonner toast for action feedback
**Source:** `frontend/src/components/shell/Sidebar.tsx` (lines 15, 63) — the only existing toast call.
**Apply to:** every live-money/settings mutation `onSuccess`/`onError`.

```typescript
import { toast } from "sonner";
// Sidebar.tsx:63 (error case):  toast.error("Sign out failed. Please try again.");
// Phase 11 success case:        toast.success(`Settings saved for ${account}.`);
```
The `<Toaster/>` is already mounted at root (Phase 9). Just import `toast` from `sonner`.

### Shared 5: Page shell + state-branch skeleton (Loading / ErrorPanel / Empty)
**Source:** `frontend/src/routes/StagedView.tsx` (lines 146-226)
**Apply to:** every page (Overview, Positions, KillSwitch, Settings).

```typescript
// StagedView.tsx:190-226 — the EXACT page-state branch order every page copies:
if (isPending) return (<div className="mx-auto max-w-6xl py-6"><h2 className="mb-6 text-xl font-semibold text-foreground">Title</h2><Loading rows={6} /></div>);
if (isError)   return (<div ...><h2 ...>Title</h2><ErrorPanel error={error} onRetry={() => refetch()} /></div>);
// success: data.length === 0 ? <Empty title="…" message="…" /> : <DataTable .../>
```
- Page container: `mx-auto max-w-6xl py-6`. Page title: `text-xl font-semibold text-foreground` (UI-SPEC Heading 20px/600).
- Imports to copy verbatim (StagedView.tsx:22-31): `useQuery`, `DataTable`/`Column`, `DirectionBadge`, `Empty`, `ErrorPanel`, `Loading`, `api`, path-alias `@/...`.

### Shared 6: `*_display` render / bare submit (Pitfall 5)
**Source:** `frontend/src/components/data/DataTable.tsx` (header comment + `sign` accessor lines 82-99) and `StagedView.tsx:133,185`.
**Apply to:** every money/price/volume/P&L cell across all four pages.
- Render the server `*_display` string in `cell`; pass the **raw** numeric to `sign(row)` ONLY for green/red P&L coloring (`DataTable.tsx:83-89`). NEVER `toFixed`/`Intl`/`Math.round` a money field.
- **Exception:** `sl`/`tp` on `Position` have **no `_display` twin** (RESEARCH §Positions) — render raw or minimal; they are operator-edited prices.
- **Allowed client calcs:** the footgun number (off two bare numerics) and elapsed duration (`lib/useElapsed.ts`) — both Pitfall-5-safe.

---

## Pattern Assignments

### `routes/OverviewView.tsx` (route/page, poll) — PAGE-05

**Analog:** `frontend/src/routes/StagedView.tsx` (exact polling-page template).
**Parity ref:** `templates/overview.html` + `partials/overview_cards.html` (structure only).

- **Polling read** — copy `StagedView.tsx:146-153` verbatim, change query key/url/interval:
```typescript
const { data, isPending, isError, error, refetch } = useQuery<OverviewMeta>({
  queryKey: ["overview"],
  queryFn: () => api("/api/v2/overview") as Promise<OverviewMeta>,
  refetchInterval: 3000,   // UI-SPEC target ~3000ms; inherited bg-pause is free
});
```
- **Multiple polled sources** — Overview needs `GET /api/v2/overview`, `GET /api/v2/trading-status` (PAUSED banner), `GET /api/v2/positions` (table), and `GET /api/v2/stages` (top-5 pending; reuse the StagedView contract — RESEARCH Open Question 2). Use one `useQuery` per source (each with its own `refetchInterval:3000`); they share the global defaults.
- **Account cards** — compose like `StagedView.tsx` `StageCard`/`Field` (lines 97-142): `rounded-lg border border-border bg-card p-4`, `font-mono` numerics, `DirectionBadge`-style green/red status chips. Render `*_display` twins from `AccountOverview`.
- **TRADING PAUSED banner** (focal-secondary per UI-SPEC) — red `--destructive` text/border above the positions table when `trading-status.paused`. Copy: **TRADING PAUSED** / "Kill switch active — no signals will be processed".
- **Positions table** — reuse the `PositionsView` table or a condensed `DataTable` (planner discretion). Empty: "No open positions".

### `routes/PositionsView.tsx` (route/page, poll + CRUD) — PAGE-06

**Analog:** `StagedView.tsx` (poll + DataTable) for the table; `Sidebar.tsx` `signOut` + `lib/http.ts` for the mutation shape.
**Parity ref:** `templates/partials/positions_table.html` (columns Account|Symbol|Direction|Volume|Entry|SL|TP|P&L|Actions; drilldown row; mobile card variant).

- **Table columns** — build a `Column<Position>[]` exactly like `StagedView.tsx:156-188`. P&L column uses `sign: (r) => r.profit` for green/red (`DataTable.tsx:83-89`) with `cell: (r) => r.profit_display`. Direction via `<DirectionBadge>`. Actions column renders Close (inline-confirm) + Edit (opens dialog).
- **Server-confirmed close mutation** — see `hooks/useClose.ts` below. Button `disabled={close.isPending}`, label morphs "Close" → "Closing…" (UI-SPEC copy). UI clears the row ONLY in `onSuccess` via `invalidateQueries(["positions"])` — **never** `setQueryData` (Pitfall 1 / SC#1).
- **Poll-safe modal/drilldown (SC#3)** — the Edit `Dialog` and drilldown state live in **local React state** (`useState` keyed by ticket), NOT the query cache; the `Dialog` portal renders outside the polling subtree. This is the proven mechanism (RESEARCH Pattern 5; Phase 9 probe). Multiple drilldowns open allowed.

### `routes/KillSwitchView.tsx` (route/page, read→mutate) — PAGE-07

**Analog:** `StagedView.tsx` (read the preview) + `LoginView.tsx:47-70` (the submit-disabled-while-pending pattern on confirm).
**Parity ref:** `templates/partials/kill_switch_preview.html` (red card; positions/orders counts; warning copy; CONFIRM CLOSE ALL; hide confirm when count==0).

- **Step 1 read** — `useQuery` on `GET /api/v2/emergency/preview` → `EmergencyPreview { open_positions, pending_orders, accounts[] }`.
- **Step 2 confirm** — `useEmergency` mutation (`POST /api/v2/emergency/close`). `<Button variant="destructive" disabled={close.isPending}>` → "CONFIRM CLOSE ALL" / "Closing all…". Cancel = "Keep trading active". Hide confirm when both counts are 0.
- **Resume** — `POST /api/v2/emergency/resume`, cyan `variant="default"` "Resume Trading" / "Resuming…", shown only while paused.

### `routes/SettingsView.tsx` (route/page, read→validate→confirm) — PAGE-08

**Analog:** `StagedView.tsx` (read) for the GET; composes `SettingsForm`, `ConfirmDiffDialog`, `AuditTimeline`.
**Parity ref:** `templates/partials/account_settings_tab.html` + `settings_confirm_modal.html` + `settings_audit_timeline.html`.

- **Read** — `useQuery` on `GET /api/v2/settings/{account}` → `SettingsView { values, audit, diff:null }`. `values` are BARE typed values = the rhf form's `defaultValues`. `values.max_lot_size` feeds the zod `fixed_lot` cap branch (RESEARCH SUX-03).
- **Two-step flow (D-05)** — copy RESEARCH "Two-step settings flow" (lines 478-486): Save → `POST .../validate` → **branch on `data.valid`** (200 even on invalid — Pitfall 7), invalid → `toast.error` rejection; valid → open `ConfirmDiffDialog` with `diff` + `dry_run_text` → Confirm → `POST .../{account}`.
- **State split (SC#3)** — form state in react-hook-form/local; the GET is server state; the confirm `Dialog` renders outside any polling subtree (Settings need not poll, so this is naturally satisfied).

### `components/positions/EditPositionDialog.tsx` (modal, 2 independent submits) — D-01/D-02

**Analog:** `templates/partials/edit_levels_modal.html` for **structure/copy** (parity — the legacy already uses two separate `<form>`s, D-02 parity); shadcn `dialog` (new) for the React primitive; `hooks/useLevels` + `hooks/usePartialClose` for the two submits.
**Genuinely new:** the shadcn `Dialog` primitive (Pitfall 9 — render opaque before wiring).

- **Structure** (from `edit_levels_modal.html`): position summary grid (Account/Direction/Volume/Entry/P&L via `*_display`) → SL/TP form (placeholder "Leave blank to keep current") → divider → partial-close form.
- **Two independent submits (D-02)** — SL/TP form button "Save SL/TP" (cyan, `useLevels`) and partial-close button "Close lots" (destructive + inline-confirm, `usePartialClose`). Each own pending state, own CSRF call, own toast. Modal stays open on either error (typed values preserved); closes only on confirmed success. NO combined Save.
- **CRITICAL parity deviation** — legacy partial-close used **percent** (`name="percent"` 1-99, `edit_levels_modal.html:84-88`). DO NOT replicate. Use **absolute lots + "Remaining after: X.XX"** (D-04). The legacy `hx-confirm` blocking dialog (`positions_table.html:43`) is replaced by `InlineConfirm` (D-03).

### `components/positions/InlineConfirm.tsx` (component) — D-03

**Analog:** **no direct code analog** — new pattern. Closest structural reference: `button.tsx` variants (`destructive`, sizes) which it composes, and `LoginView`'s local-`useState` pending discipline.
- Replaces `hx-confirm` browser dialog. First click → "Confirm close #{ticket}? ✓ / ✕"; second click fires (`disabled={isPending}`); ✕ cancels. In-place button morph OR shadcn `popover` (executor's choice, D-03 — only one ships). Destructive red per UI-SPEC. min-h-10 tap target.

### `components/positions/PositionDrilldown.tsx` (component, poll) — D-01

**Analog:** `StagedView.tsx` `StageCard`/`Field` (lines 97-142) for the labelled-field card layout; `DataTable` for the fill-history table.
**Parity ref:** `templates/partials/position_drilldown.html` (Fill History table Stage|Time|Lots|Band|SL at Fill|Status; Current P/L + Entry/SL/TP row; Signal Source block with raw text).
- Reads `GET /api/v2/positions/{account}/{ticket}`. Open/expanded state in **local state keyed by ticket** so it survives background refetch (SC#3). Render `*_display` twins.

### `components/settings/SettingsForm.tsx` (form, rhf+zod) — SUX-02/03

**Analog:** `LoginView.tsx:90-123` for the **field markup** (Label + Input + `role="alert"` error text + disabled-while-pending), but the rhf+zod wiring is **genuinely new** (first form library in repo).
**Parity ref:** `account_settings_tab.html` (field set + help copy); UI-SPEC §Copywriting Contract (DB-column → operator labels — authoritative).
- **rhf+zod (new)** — `useForm({ resolver: zodResolver(makeSettingsSchema(maxLotSize)), defaultValues: values })`. shadcn `select` for `risk_mode`, `tooltip` for per-field help. Field validation error → inline `text-destructive` `role="alert"` (mirror `LoginView.tsx:114-118`).
- **Inline footgun** — call `lib/footgun.ts` live as `risk_value`/`max_stages` change; render amber `AlertTriangle` note (UI-SPEC §Color — amber, NOT destructive red, NOT cyan).
- Save button copy "Review changes" (opens validate flow — does NOT persist).

### `components/settings/ConfirmDiffDialog.tsx` (modal) — D-05/D-06

**Analog:** `settings_confirm_modal.html` for structure (parity); shadcn `dialog` (new, same as EditPositionDialog).
- Renders `diff` table (Field | old → new), `dry_run_text` **verbatim** (server-rendered, do NOT recompute), and the footgun **restated** (call `lib/footgun.ts` again). Confirm button "Confirm change" / "Saving…" (cyan, disabled-while-pending). Body copy: "applies to signals received AFTER you confirm; in-flight unaffected".

### `components/settings/AuditTimeline.tsx` (component) — PAGE-08

**Analog:** `DataTable.tsx` + `StagedView.tsx` resolved-table columns (exact).
**Parity ref:** `settings_audit_timeline.html` (Timestamp|Field|Change(old→new)|Actor|Action).
- Render `audit[]` from the SettingsView GET in a `DataTable` (newest-first). Use `timestamp_display` (Pitfall 5). **Revert** = single "Revert last change" + confirm (RESEARCH Open Question 1 — API reverts latest-only, no `audit_id`; do NOT add a per-row `audit_id` call). Revert via `useSettingsMutations`, confirmation toast "Reverted last change for {account}.".

### `hooks/useClose.ts` / `useLevels.ts` / `usePartialClose.ts` / `useEmergency.ts` / `useSettingsMutations.ts` (mutation hooks)

**Analog:** `frontend/src/components/shell/Sidebar.tsx` `signOut` (lines 51-68) is the ONLY existing mutation in the repo — it shows the `api(..., {method:"POST"})` + try/catch + `toast.error` shape. **`useMutation` itself is a new pattern** (no `useMutation` exists yet); follow RESEARCH Patterns 2 & 3.

- **Core mutation shape (no optimistic — SC#1/Pitfall 1)** — RESEARCH Pattern 2:
```typescript
const qc = useQueryClient();
const close = useMutation({
  mutationFn: () => api(`/api/v2/positions/${account}/${ticket}/close`, { method: "POST" }),
  onSuccess: () => { qc.invalidateQueries({ queryKey: ["positions"] }); toast.success("Position closed"); },
  onError: (e) => toast.error(errorMessage(e)),   // reuse ErrorPanel.errorMessage; 401 handled globally
});
// <Button variant="destructive" disabled={close.isPending}>{close.isPending ? "Closing…" : "Close"}</Button>
```
- **`usePartialClose` — request_id + 409 (Pitfall 3)** — RESEARCH Pattern 3: `const requestId = useRef(crypto.randomUUID())`; body `{ close_volume, request_id: requestId.current }`; **reuse the id on pure retries**, regenerate only when the operator changes the amount; on `e.status === 409` toast "That close already ran or the amount changed — refresh and retry." `close_volume` is **absolute lots** (D-04), never percent.
- **`useLevels`** — body `CloseLevelsIn { sl?, tp? }` (both optional; null = keep). No-op returns `{ok:true, changed:{}}`.
- **`useEmergency`** — `close` (`POST /emergency/close`) + `resume` (`POST /emergency/resume`), both no body; invalidate `["overview","trading-status","positions"]` on success.
- **`useSettingsMutations`** — `validate` (branch on `data.valid`, NOT status — Pitfall 7), `confirm` (`POST /settings/{account}` body `{account, values}`), `revert` (`POST /settings/{account}/revert` body `{account}`). Bodies nest fields under `values` (RESEARCH §Settings request-body note).
- **Anti-pattern guard for all five:** NO `setQueryData` before server confirm; button always `disabled={mutation.isPending}`.

### `lib/footgun.ts` (pure fn) — D-06/D-07/Pitfall 6

**Analog:** `lib/useElapsed.ts` (the precedent for an allowed pure client calc off bare numerics).
- Copy RESEARCH §"Mode-aware footgun" (lines 467-474) verbatim. **percent mode** → `riskValue * maxStages` (compounds). **fixed_lot mode** → do NOT multiply; `riskValue` is the TOTAL across stages (operator-confirmed; `trade_manager.py:108-117`). A single un-branched `risk_value * max_stages` is the Pitfall-6 bug. Pure function → unit-tested.

### `lib/settingsSchema.ts` (zod schema, mode-aware) — SUX-03

**Analog:** **none** — first zod schema in the repo (new pattern).
- Copy RESEARCH §"Mode-aware zod sketch" (lines 349-362). `makeSettingsSchema(maxLotSize)` factory: percent `risk_value ≤ 5.0`; fixed_lot `risk_value ≤ maxLotSize` (per-account, from GET `values.max_lot_size`); `max_stages` 1-10, `default_sl_pips` 1-500, `max_daily_trades` 1-100 (caps table RESEARCH lines 333-340). **Derive from `dashboard.validate_settings_form`, never hardcode.** Do NOT cap `max_open_trades` (read-only, not in the form). zod v4 API — verify `superRefine`/`z.enum`/`addIssue("custom")` at install via `npm run build`.

### `lib/settingsSchema.test.ts` / `lib/footgun.test.ts` (vitest) — Wave 0

**Analog:** **none** — first JS test runner (vitest is a Wave-0 framework add).
- Pure-function unit tests (RESEARCH §Validation Architecture, Wave 0 Gaps). `settingsSchema.test.ts`: percent ≤5.0, fixed_lot ≤ max_lot_size, int bounds. `footgun.test.ts`: percent multiplies, fixed_lot does NOT (Pitfall 6). Run via `npx vitest run`.

### `routes/router.tsx` (MODIFY) — exact analog: itself

**Pattern** (router.tsx:33-62): add four child routes under `path:"/"` mirroring the existing `analytics`/`signals`/`history`/`stages` entries (path WITHOUT `/app` prefix; basename adds it). Add `overview`, `positions`, `emergency`, `settings`. Flip the index `<Navigate to="/analytics">` → `to="/overview"` (router.tsx:36-38; OQ2 — Overview is now live).

### `components/shell/Sidebar.tsx` (MODIFY) — exact analog: itself

**Pattern** (Sidebar.tsx:27-35): the disabled-visible `{ label: "Positions" }` and `{ label: "Settings" }` entries get a `to:` (→ become live NavLinks via the generic branch lines 101-108). "Overview" already maps `to:"/"` (index now resolves to Overview). No structural change — just add `to` props.

---

## No Analog Found (use RESEARCH patterns + structural reference)

Files with NO existing code analog in this codebase — the planner points executors at the
**RESEARCH Code Examples / Patterns** and the cited structural reference instead:

| File | Role | Data Flow | Reason | Use Instead |
|------|------|-----------|--------|-------------|
| `lib/settingsSchema.ts` | utility (zod) | transform | First zod schema in repo | RESEARCH §Mode-aware zod sketch (349-362) + caps table |
| `lib/*.test.ts` | test (vitest) | — | First JS test runner | RESEARCH §Validation Architecture Wave 0 |
| `components/positions/InlineConfirm.tsx` | component | event-driven | No two-click-confirm pattern exists | D-03 spec + `button.tsx` variants + local-`useState` pending (LoginView) |
| `hooks/use*.ts` (`useMutation`) | hook | CRUD | No `useMutation` call exists yet | RESEARCH Patterns 2 & 3; closest existing = `Sidebar.signOut` |
| `SettingsForm.tsx` (rhf+zod wiring) | component | transform | First react-hook-form usage | RESEARCH §Standard Stack + `LoginView` field markup for the JSX |
| shadcn `dialog`/`tooltip`/`select`/`badge`/`popover` | ui | — | Not yet installed (Phase 9/10 only added button/input/label/card/sonner) | `npx shadcn@latest add ...` then Pitfall-9 opaque-render gate |

---

## Metadata

**Analog search scope:** `frontend/src/{routes,components,lib,auth,hooks}` (full SPA source, 23 files) + `templates/partials/*.html` (parity references, structure only).
**Files scanned:** 23 frontend source files read/grepped; 8 legacy parity templates referenced (2 read in full: `positions_table.html`, `edit_levels_modal.html`; the other 6 structure-summarized from RESEARCH §Legacy Parity Targets).
**Key inherited infra confirmed shipped:** `lib/http.ts` (CSRF echo), `lib/queryClient.ts` (global 401 + polling defaults), `auth/csrf.ts` (cold-start seed), `components/data/DataTable.tsx`, `components/state/{Loading,Empty,ErrorPanel}.tsx`, `routes/StagedView.tsx` (polling template), `routes/router.tsx`, `components/shell/Sidebar.tsx`.
**New deps to install (not in package.json):** `react-hook-form`, `zod`, `@hookform/resolvers`, `vitest` + shadcn `dialog tooltip select badge popover`.
**Pattern extraction date:** 2026-06-07

---

## PATTERN MAPPING COMPLETE

**Phase:** 11 - live-money-pages-settings
**Files classified:** 18 (16 new + 2 modified)
**Analogs found:** 14 / 16 new files (2 are genuinely-new with only a structural reference)

### Coverage
- Files with exact/strong analog: 9 (Overview/Positions/KillSwitch/Settings pages, AuditTimeline, PositionDrilldown, footgun, router, Sidebar)
- Files with role-match / partial analog: 5 (EditPositionDialog, ConfirmDiffDialog, SettingsForm, the 5 mutation hooks collectively)
- Files with NO analog (new pattern): `lib/settingsSchema.ts`, `lib/*.test.ts`, `InlineConfirm.tsx` (+ rhf/zod/useMutation/shadcn-dialog as new *mechanisms* layered into otherwise-analoged files)

### Key Patterns Identified
- **Every read = `useQuery` poller copied from `StagedView.tsx`** (queryKey + `api()` queryFn + `refetchInterval:3000`), with the `isPending→Loading / isError→ErrorPanel / empty→Empty / DataTable` branch order verbatim.
- **Every mutation = `useMutation` with NO optimistic clear** — `api(...,{method:"POST"})` mutationFn, `disabled={isPending}` button, UI updates ONLY in `onSuccess` via `invalidateQueries`, `onError → toast.error(errorMessage(e))`. CSRF is auto-echoed by `api()`; never raw fetch. (closest existing mutation = `Sidebar.signOut`; `useMutation` is otherwise new.)
- **Server-state / form-state split is the SC#3 mechanism** — query cache for live data, react-hook-form/local state for modal inputs, `Dialog` portal outside the polling subtree (proven by Phase 9 probe; no new infra).
- **Genuinely new mechanisms** (no analog): react-hook-form + zod forms, the mode-aware zod cap schema + footgun pure fns, the two-click `InlineConfirm`, and the 5 shadcn components — all gated by `npm run build` (TS) + Pitfall-9 opaque-render check + two vitest units.

### File Created
`/Users/murx/Developer/personal/telebot/.planning/phases/11-live-money-pages-settings/11-PATTERNS.md`

### Ready for Planning
Pattern mapping complete. The planner can point each plan's action section at a concrete analog file + line range (all under `frontend/src/`) and the shared-pattern excerpts above, with the legacy `templates/partials/*.html` cited as parity-only structure references.
