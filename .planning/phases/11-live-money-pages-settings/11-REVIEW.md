---
phase: 11-live-money-pages-settings
reviewed: 2026-06-07T00:00:00Z
depth: standard
files_reviewed: 22
files_reviewed_list:
  - frontend/src/components/positions/EditPositionDialog.tsx
  - frontend/src/components/positions/InlineConfirm.tsx
  - frontend/src/components/positions/PositionDrilldown.tsx
  - frontend/src/components/settings/AuditTimeline.tsx
  - frontend/src/components/settings/ConfirmDiffDialog.tsx
  - frontend/src/components/settings/SettingsForm.tsx
  - frontend/src/components/shell/Sidebar.tsx
  - frontend/src/hooks/useClose.ts
  - frontend/src/hooks/useEmergency.ts
  - frontend/src/hooks/useLevels.ts
  - frontend/src/hooks/usePartialClose.ts
  - frontend/src/hooks/useSettingsMutations.ts
  - frontend/src/lib/footgun.ts
  - frontend/src/lib/footgun.test.ts
  - frontend/src/lib/settingsSchema.ts
  - frontend/src/lib/settingsSchema.test.ts
  - frontend/src/routes/KillSwitchView.tsx
  - frontend/src/routes/OverviewView.tsx
  - frontend/src/routes/PositionsView.tsx
  - frontend/src/routes/SettingsView.tsx
  - frontend/src/routes/router.tsx
findings:
  critical: 2
  warning: 6
  info: 4
  total: 12
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-06-07
**Depth:** standard
**Files Reviewed:** 22
**Status:** issues_found

## Summary

Reviewed the Phase 11 live-money pages + settings surface (positions table, edit/partial-close
dialog, kill switch, overview, two-step settings flow, and supporting hooks/libs). The core
money-safe invariants the phase advertises are largely held: every reviewed hook routes through
`api()` (no raw `fetch`, CSRF echoed), there is no `setQueryData` optimistic clear anywhere,
mutations gate on `isPending`, the partial-close idempotency key + 409 handling is correct, the
footgun calc is genuinely mode-aware (and unit-proven), and the zod caps mirror the documented
server caps. The `*_display` twin discipline is followed for money/price fields.

However the review surfaced two correctness defects that affect live money and account isolation:

1. **CR-01** — the partial-close amount is rounded *up* to the lot step before submit while the
   over-volume guard checks the *un-rounded* value, so a near-full entry (e.g. type 0.998 on a
   1.00-lot position) submits a `close_volume` equal to the FULL volume through the partial-close
   endpoint — closing the entire position when the operator intended a partial.
2. **CR-02** — `<AccountSettings>` is not re-keyed on account switch, so the rhf form (and the
   `review`/`confirmData`/`confirmOpen` state) carry account A's typed values into account B. The
   operator can confirm-and-persist account A's settings onto account B.

Plus six warnings (silent PAUSED-banner suppression on a failed status fetch, un-encoded path
params, etc.) and four info items.

## Critical Issues

### CR-01: Partial-close rounds up past open volume → full close via the partial endpoint

**File:** `frontend/src/components/positions/EditPositionDialog.tsx:101-143`
**Issue:** The over-volume guard validates the *un-rounded* input but the submit sends the
*rounded* value:

```ts
const closeValid = closeParsed?.success === true && closeNum < position.volume; // raw closeNum
// ...
closeVolume: roundToStep(closeNum),   // rounded value is what is sent
```

`roundToStep` uses `Math.round`, which rounds *up* at the half-step. For a position with
`volume = 1.00`, typing `0.998`:
- `closeNum = 0.998`, so `closeNum < position.volume` (0.998 < 1.0) is **true**;
- `partialSchema.safeParse(roundToStep(0.998))` = `safeParse(1.0)` passes `.max(1.0)` (equal is allowed);
- `closeValid` is **true**, the InlineConfirm arms, and submit sends `close_volume: 1.0`.

The operator believes they are closing 0.998 lots and leaving a sliver open; the server receives a
request to close the entire 1.00-lot position. This is a live-money behavior defect — the whole
point of the absolute-lots model (D-04) is that "Remaining after" reflects what stays open, and
here it lies (the readout shows `0.00` remaining only if you read it, while the field still reads
0.998). The guard and the submitted value must operate on the SAME (rounded) number, and the
upper bound must be strict against the rounded value.

**Fix:**
```ts
const rounded = Number.isFinite(closeNum) ? roundToStep(closeNum) : NaN;
const closeParsed = Number.isFinite(rounded)
  ? partialSchema.safeParse(rounded)
  : null;
// strict: a partial close must leave a non-zero remainder against the ACTUAL submitted value
const closeValid = closeParsed?.success === true && rounded < position.volume;
// ...
const remainingAfter =
  Number.isFinite(rounded) && rounded > 0
    ? Math.max(0, position.volume - rounded)
    : position.volume;
// ...
closeVolume: rounded,   // submit the same value the guard approved
```

### CR-02: Settings form + review state not reset on account switch → cross-account persist

**File:** `frontend/src/routes/SettingsView.tsx:112-120, 134-229`
**Issue:** `<AccountSettings account={account} … />` is rendered without a `key={account}`, so
switching the account selector re-renders the same component instance rather than remounting it.
Two consequences:

1. `SettingsForm` calls `useForm({ defaultValues: { …values } })`. react-hook-form reads
   `defaultValues` only at **mount**. Without a remount, switching from account A to account B
   leaves every field showing account A's values even though `data.values` (and the GET query)
   now reflect B. The operator edits what they believe is B against A's baseline.
2. The local `review`, `confirmData`, and `confirmOpen` state persist across the switch. If the
   operator opened the confirm dialog (or has a stashed `review`) for A, then switches to B, the
   `ConfirmDiffDialog` renders `account={B}` while `riskValue`/`maxStages`/`mode` come from A's
   `review`, and `handleConfirm()` fires `confirm.mutate({ account: B, values: { ...review } })`
   — persisting account A's typed values onto account B.

This breaks account isolation on a live-money settings page.

**Fix:** Remount the per-account body when the account changes so both rhf defaults and all local
review state reset:
```tsx
<AccountSettings
  key={account}            // re-mount on account switch → fresh rhf defaults + cleared review state
  account={account}
  validate={validate}
  confirm={confirm}
  invalidate={() => qc.invalidateQueries({ queryKey: ["settings", account] })}
/>
```
(Resetting via `form.reset(values)` in an effect keyed on `account` is an alternative for the form,
but it does not clear `review`/`confirmData`/`confirmOpen` — the `key` remount handles both.)

## Warnings

### WR-01: Failed `trading-status` fetch silently hides the TRADING PAUSED banner

**File:** `frontend/src/routes/OverviewView.tsx:259, 299-311` and `frontend/src/routes/KillSwitchView.tsx:111, 170`
**Issue:** `const paused = tradingStatus.data?.paused === true;`. When the `["trading-status"]`
query is loading, erroring, or returns a transient network failure, `tradingStatus.data` is
`undefined` and `paused` collapses to `false`. On a money-safe dashboard this means a real
PAUSED state (kill switch active, no signals processed) is rendered as NOT paused — the red
escalation banner and the Resume button both disappear on any status-fetch blip. The operator
can be misled into thinking trading is live when it is paused (or vice-versa). The query has no
`isError` handling for this banner.

**Fix:** Treat an unknown status as a non-clear (fail safe). At minimum, when
`tradingStatus.isError`, show a degraded "trading status unavailable" indicator instead of
silently rendering the not-paused layout; and prefer the last-known value via `keepPreviousData`
so a single failed poll does not flip the banner. Do not let `undefined` read as "running".

### WR-02: Path parameters interpolated into request URLs without encoding

**File:** `frontend/src/hooks/useClose.ts:36`, `frontend/src/hooks/useLevels.ts:37`, `frontend/src/hooks/usePartialClose.ts:57`, `frontend/src/components/positions/PositionDrilldown.tsx:80`, `frontend/src/routes/SettingsView.tsx:142`
**Issue:** `account` (and `ticket`) are interpolated raw into the path, e.g.
`` api(`/api/v2/positions/${account}/${ticket}/close`) ``. Account names originate from
`accounts.json` / server config and can plausibly contain spaces or URL-significant characters
(`/`, `#`, `?`, `%`). An account named `My Acct` or one containing a `/` would produce a malformed
or mis-routed path, and any `#`/`?` would truncate the path. This is a robustness/correctness gap
on every live-money mutation URL.

**Fix:** Encode each dynamic segment:
```ts
api(`/api/v2/positions/${encodeURIComponent(account)}/${encodeURIComponent(String(ticket))}/close`, …)
```
Apply uniformly across the four hooks and the two views.

### WR-03: `regenerateRequestId` fires on every keystroke, defeating cached-200 replay on edit-back

**File:** `frontend/src/components/positions/EditPositionDialog.tsx:248-253`
**Issue:** The close-volume `onChange` calls `partial.regenerateRequestId()` on *every* input
event. The hook's contract (usePartialClose.ts:12-15, 49-53) is that the id is regenerated ONLY
when the operator *changes the intended amount*, so that a pure retry of the same amount reuses
the id and hits the server's cached-200 replay. But because regeneration is bound to raw keystroke
events, typing `0.5`, deleting to `0.`, then re-typing `0.5` mints THREE new ids for the same final
amount — and any in-flight-error retry path that involves re-focusing/re-entering the field will
mint a fresh id, turning a safe replay into a NEW operation against the broker. The idempotency
guarantee is keystroke-fragile rather than amount-driven.

**Fix:** Regenerate based on the committed amount, not the raw event — e.g. track the
last-submitted rounded volume and only call `regenerateRequestId()` when the rounded value about
to be submitted differs from the last submitted one, or regenerate in `handleCloseLots` only after
a confirmed success. Do not couple it to `onChange`.

### WR-04: InlineConfirm stays armed after a successful close inside the Edit dialog edge case

**File:** `frontend/src/components/positions/EditPositionDialog.tsx:267-274` + `frontend/src/components/positions/InlineConfirm.tsx:51-86`
**Issue:** `InlineConfirm` holds its `armed` flag in internal `useState` with no reset hook. In
`EditPositionDialog` the modal closes on success (`onSuccess: () => onClose()`), but the component
is not unmounted (the Dialog stays mounted; `position` controls render). If a partial close
*errors* (modal stays open by design), the InlineConfirm remains `armed` with `pending` back to
`false`, so the ✓ is immediately re-enabled pointing at the SAME `handleCloseLots`. Combined with
WR-03 (same request_id may or may not have regenerated), a second ✓ click can re-fire. There is no
`onConfirm`-completed reset of the armed state, and no `disabled`-after-success window.

**Fix:** Have `InlineConfirm` accept a reset signal (e.g. disarm in a `useEffect` keyed on a
`resetKey`/ticket prop, or expose an imperative reset the parent calls in the mutation's
`onSettled`). After any confirm fire, return to idle so a deliberate second arming is required.

### WR-05: `validate.isPending` / validate errors not reflected on the "Review changes" button

**File:** `frontend/src/components/settings/SettingsForm.tsx:208-211`, `frontend/src/routes/SettingsView.tsx:155-174`
**Issue:** The "Review changes" submit button is never disabled while `validate.isPending`. The
two-step contract relies on `disabled-while-pending` for destructive actions, and while validate
itself is non-destructive (dry-run), a double-click submits the validate mutation twice and can
open the confirm dialog on the stale first response while a second is in flight, or stack two
toasts on a `valid:false` result. Every other submit in the phase gates on `isPending`; this one
does not.

**Fix:** Thread `validate.isPending` into `SettingsForm` and set
`disabled={validate.isPending}` (and a "Reviewing…" label) on the Review button, matching the
confirm/close pattern.

### WR-06: `closeNum`/`Number()` accepts non-finite & locale-edge inputs silently

**File:** `frontend/src/components/positions/EditPositionDialog.tsx:102, 120-121`
**Issue:** `Number(closeVolume)` / `Number(sl)` / `Number(tp)` coerce loosely. `Number("")` is 0
(guarded for closeVolume by the `trim() === ""` check, but `sl`/`tp` use the same blank→undefined
guard so that path is OK), however `Number("1e3")`, `Number("0x10")`, `Number(" 5 ")`,
`Number("Infinity")` all parse to finite/huge numbers. For sl/tp the values flow straight into the
levels mutation body with no client bound, relying entirely on the server 422. For closeVolume the
zod `.positive().max(volume)` catches range, but `Number("Infinity")` → not finite → `closeParsed`
null → invalid (OK), while `"1e1"` on a 100-lot position would pass. Mostly defended, but the SL/TP
path sends arbitrarily-parsed numbers (including `1e308`) with no client sanity check.

**Fix:** Parse sl/tp with the same finite + positive discipline used for close volume before
calling `levels.mutate`, and reject non-finite numbers in the UI rather than relying solely on the
server's 422 round-trip.

## Info

### IN-01: `useEmergency` close success toast may overstate result on partial failure

**File:** `frontend/src/hooks/useEmergency.ts:33-41`
**Issue:** `close` resolves on any 2xx and toasts "All positions closed, trading paused", but the
server contract is `EmergencyResult {results, ok}` — `results` can carry per-account failures while
the overall response is 2xx. The toast does not inspect `results`/`ok`, so a partial close-all
shows an unqualified success.

**Fix:** Inspect the returned `ok`/`results` and toast a qualified message (e.g. "Closed N of M;
see results") when not all accounts succeeded.

### IN-02: `audit.sort((a,b) => b.id - a.id)` assumes numeric, monotonic ids

**File:** `frontend/src/components/settings/AuditTimeline.tsx:56`
**Issue:** Defensive newest-first sort keys on `b.id - a.id`. If `id` is ever non-numeric or not
monotonic with time (e.g. a UUID, or ids reused across accounts), the ordering silently degrades.
Low risk given the typed `id: number`, but the "newest-first" guarantee is coupled to id ordering
rather than `timestamp`.

**Fix:** Sort on `timestamp` (the semantic ordering key) or document that `id` is a monotonic
autoincrement.

### IN-03: Overview pending-stage key uses array index, risking remount churn

**File:** `frontend/src/routes/OverviewView.tsx:339-341`
**Issue:** `key={`${s.account_name}-${s.symbol}-${i}`}` includes the array index `i`. On a 3s poll
where the active-stage list reorders, index-based keys cause React to re-key/remount cards
unnecessarily. Purely a UI-stability nit (no money impact), but the composite already has
account+symbol — adding the index defeats the stable part of the key.

**Fix:** Prefer a stable per-stage identifier from the payload (e.g. a stage/ticket id) if
available; drop the index from the key.

### IN-04: `raw_text.slice(0, 500)` truncates without affordance

**File:** `frontend/src/components/positions/PositionDrilldown.tsx:231`
**Issue:** The raw signal text is hard-truncated to 500 chars inside the `<details>` with no
ellipsis or "truncated" indicator, so an operator inspecting a long signal silently sees a cut-off
body and may believe that is the full message. Not a security/correctness defect (it is rendered as
text, not HTML — no XSS), purely a transparency nit.

**Fix:** Append a "… (truncated)" marker when `raw_text.length > 500`, or render the full text
(it is already inside a collapsed, scrollable `<pre>`).

---

_Reviewed: 2026-06-07_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
