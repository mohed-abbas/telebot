// frontend/src/components/positions/InlineConfirm.tsx — the two-click destructive confirm (D-03).
//
// Replaces the legacy `hx-confirm` BROWSER dialog (positions_table.html:43,79) with an in-app,
// recoverable, fully-styled guard. There is NO `window.confirm`/`confirm()` anywhere — a browser
// dialog is unstyleable, blocks the event loop, and (worst of all) cannot be made disabled-while-
// pending, so a double-press could fire a second live-money close. This component fixes all three:
//
//   idle   → a single destructive button showing the caller's `label` (e.g. "Close").
//   armed  → first click morphs in-place to "Confirm close #{ticket}?  ✓ / ✕":
//              ✓ calls `onConfirm` and is `disabled={pending}` (no double-fire — SC#1 discipline);
//              ✕ resets to idle (a misclick is fully recoverable — UI-SPEC interaction contract).
//
// D-03 picks the in-place button-morph variant (NOT the shadcn popover) — exactly one ships.
// All three controls clear the `min-h-10` (40px) tap-target floor (UI-SPEC spacing).
//
// This is a controlled-by-its-own-local-state widget: the armed/idle flip is internal `useState`,
// never the query cache — so a 3s background refetch (SC#3) cannot reset an armed confirm.

import { useState } from "react";
import { Check, X } from "lucide-react";

import { Button } from "@/components/ui/button";

export interface InlineConfirmProps {
  /** Idle-button label (e.g. "Close", "Close lots"). */
  label: string;
  /** The ticket id rendered into the confirm prompt: "Confirm close #{ticket}?". */
  ticket: number | string;
  /** Fired on the ✓ click — the actual live-money mutation. */
  onConfirm: () => void;
  /** While true the ✓ button is disabled (mutation in flight) — guards against a double-fire. */
  pending?: boolean;
  /** Pending-state label shown next to ✓ while `pending` (e.g. "Closing…"). */
  pendingLabel?: string;
  /** Optional extra classes for the idle button. */
  className?: string;
}

/**
 * A two-step destructive confirm. First click arms; ✓ confirms (disabled-while-pending); ✕ cancels.
 * No browser `confirm()` — the guard is a styled, recoverable, in-app morph.
 */
export function InlineConfirm({
  label,
  ticket,
  onConfirm,
  pending = false,
  pendingLabel,
  className,
}: InlineConfirmProps) {
  const [armed, setArmed] = useState(false);

  // While a mutation is in flight, keep the armed prompt up and show the pending label on ✓ so the
  // operator sees the action is running and cannot fire it a second time.
  if (armed) {
    return (
      <div className="flex min-h-10 items-center gap-2">
        <span className="text-xs text-muted-foreground">
          Confirm close #{ticket}?
        </span>
        <Button
          type="button"
          variant="destructive"
          size="sm"
          className="min-h-10"
          disabled={pending}
          aria-label={`Confirm close #${ticket}`}
          onClick={onConfirm}
        >
          <Check aria-hidden="true" />
          {pending ? (pendingLabel ?? "Closing…") : null}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="min-h-10"
          disabled={pending}
          aria-label="Cancel close"
          onClick={() => setArmed(false)}
        >
          <X aria-hidden="true" />
        </Button>
      </div>
    );
  }

  return (
    <Button
      type="button"
      variant="destructive"
      size="sm"
      className={`min-h-10 ${className ?? ""}`.trim()}
      onClick={() => setArmed(true)}
    >
      {label}
    </Button>
  );
}
