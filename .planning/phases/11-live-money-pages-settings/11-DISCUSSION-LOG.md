# Phase 11: Live-money Pages + Settings - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-07
**Phase:** 11-live-money-pages-settings
**Areas discussed:** Positions action surface, Destructive-action confirm friction, Partial-close input model, Settings confirm scope + footgun

---

## Positions action surface

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror legacy shape | Row Close button + ONE Edit modal combining SL/TP modify AND partial-close + expandable drilldown. 1:1 parity; modal outside polling subtree. | ✓ |
| Split modify vs partial | Separate Edit-SL/TP and Partial-close flows, two entry points per row. | |
| You decide | Planner picks cleanest layout hitting parity + modal-outside-polling. | |

**User's choice:** Mirror legacy shape
**Notes:** → CONTEXT D-01.

### Follow-up — Edit modal submit granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Two independent submits | Each operation its own button + pending state + CSRF call + toast. Save SL/TP → /levels; Close lots → /close-partial. | ✓ |
| One combined Save | Single Save fires both calls in sequence; ambiguous partial-success states. | |
| You decide | Planner picks. | |

**User's choice:** Two independent submits
**Notes:** Maps cleanly to the two distinct endpoints; avoids mis-firing a close. → CONTEXT D-02.

---

## Destructive-action confirm friction

| Option | Description | Selected |
|--------|-------------|----------|
| Inline confirm step | Click Close → button morphs to "Confirm close #ticket? / ✕" in place; 2nd click fires (disabled-while-pending). In-app guard replacing legacy hx-confirm. Same for partial-close Close lots. | ✓ |
| Native confirm dialog | Keep blocking confirm()-style dialog like legacy hx-confirm. | |
| No confirm, rely on pending | Single click fires; safety only from disabled-while-pending + server-confirmed result. | |

**User's choice:** Inline confirm step
**Notes:** Kill-switch two-step is separately locked; this covers individual position buttons. → CONTEXT D-03.

---

## Partial-close input model

| Option | Description | Selected |
|--------|-------------|----------|
| Absolute lots, live remainder | Operator types lots to CLOSE directly (API shape); UI shows "remaining after: X.XX"; zod validates 0 < v < volume, lot-step rounded. No percent model. | ✓ |
| Percent → absolute preview | Pick % / slider, convert to absolute, show resolved lots, send absolute. Re-introduces percent mental model. | |
| Quick presets + lots field | Absolute lots field plus quick-fill preset buttons (½, all-but-min). | |

**User's choice:** Absolute lots, live remainder
**Notes:** The absolute-lots design is exactly what killed the percent-of-current 75%-trap (Phase 8 D-09); UI must not re-introduce percents. → CONTEXT D-04.

---

## Settings confirm scope + footgun

### Confirm scope

| Option | Description | Selected |
|--------|-------------|----------|
| All changes confirm | Every settings save runs validate→diff→confirm regardless of field. Uniform, impossible to miscategorize. | ✓ |
| Only risk fields confirm | Defined risk-field set triggers confirm-diff; benign fields save directly. Requires a dangerous-field list. | |
| You decide | Planner classifies. | |

**User's choice:** All changes confirm
**Notes:** → CONTEXT D-05.

### Footgun warning placement (SUX-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Both: inline + in diff | Warning recomputes live while editing AND restates in confirm-diff modal. Strongest coverage. | ✓ |
| Inline only | Live warning by the fields; confirm modal shows plain diff. | |
| In confirm diff only | Warning only at submit time in the confirm modal. | |

**User's choice:** Both: inline + in diff
**Notes:** Compounded value derived client-side from two bare numerics — Pitfall-5-safe. → CONTEXT D-06.

### Footgun math — mode awareness (raised by Claude from operator memory)

| Option | Description | Selected |
|--------|-------------|----------|
| Mode-aware calc | percent/risk mode: max_stages × risk_value (compounds). fixed_lot mode: risk_value IS the total — no ×multiplication; warn on absolute total. zod caps switch on mode, mirror server. | ✓ |
| My note is stale | The fixed_lot=TOTAL semantics changed since 2026-05-01. | |
| You decide | Planner reads server _validate to derive caps. | |

**User's choice:** Mode-aware calc
**Notes:** Confirms the 2026-05-01 operator-confirmed lot semantics still hold: fixed_lot `risk_value` = TOTAL across max_stages, not per-trade. The SUX-02 "max_stages × risk_value" wording is a percent-mode illustration only. → CONTEXT D-07.

---

## Claude's Discretion

- Overview composition (condensed vs full positions table; kill-switch entry point; PAUSED banner + pending-stages layout).
- Kill-switch page structure for the locked two-step preview→confirm flow.
- Settings audit-timeline + revert UX detail.
- Whether multiple drilldowns open at once + the keep-alive-across-refetch mechanism.
- Inline-confirm rendering detail (button morph vs popover).
- Per-field copywriting (SUX-04) and which shadcn components each page adds.
- Exact refetchInterval/staleTime numbers within the Phase-9 D-09 frame.

## Deferred Ideas

None — discussion stayed within phase scope. Legacy-route / SSE / Tailwind-CLI removal remains Phase 12.
