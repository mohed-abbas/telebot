// frontend/src/components/positions/EditPositionDialog.tsx — the combined Edit modal (D-01/D-02/D-04).
//
// THE highest-blast-radius surface in the SPA. It packs TWO independent live-money submits behind a
// single shadcn Dialog (rendered through the dialog PORTAL — outside the 3s polling subtree, SC#3):
//
//   1. SL/TP modify  → useLevels  (cyan "Save SL/TP"). Sends ONLY the fields the operator typed
//      (a blank input = "keep current"; never coerced to 0). 11-01 opaque-render gate already passed.
//   2. Partial close → usePartialClose (destructive "Close lots", wrapped in InlineConfirm — D-03).
//      D-04: the operator types ABSOLUTE LOTS to close (NEVER a percent — the legacy percent model is
//      the 75% trap, Pitfall 3). A live "Remaining after: X.XX" readout + a zod check 0 < value <
//      volume gate the Close. The request_id is regenerated ONLY when the typed amount changes, so a
//      pure retry of the same amount hits the server's cached-200 replay (usePartialClose contract).
//
// Two INDEPENDENT submits (D-02) — separate forms, separate buttons, separate `isPending`, separate
// CSRF calls (via api()), separate toasts. There is NO single combined "Save". On either submit's
// error the modal STAYS OPEN with typed values preserved (the hook surfaces the toast); the modal
// closes ONLY on that submit's confirmed success (we pass a per-call onSuccess that flips `open`).
//
// Dialog open/close + every input is LOCAL React state (useState) — never the query cache (SC#3), so
// a background refetch cannot clobber a half-typed SL/TP/lots field.
//
// Pitfall-5: the position summary renders the server `*_display` twins. sl/tp inputs are raw numerics
// (operator-edited prices — no _display twin).

import { useState } from "react";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DirectionBadge } from "@/components/data/DirectionBadge";
import { InlineConfirm } from "@/components/positions/InlineConfirm";
import { useLevels } from "@/hooks/useLevels";
import { usePartialClose } from "@/hooks/usePartialClose";

// The fields this modal needs off the Position row (a structural subset of the positions payload).
export interface EditPosition {
  account: string;
  ticket: number | string;
  symbol: string;
  direction: string;
  /** Raw volume — drives the partial-close upper bound and the "Remaining after" math. */
  volume: number;
  volume_display?: string | null;
  open_price_display?: string | null;
  profit?: number | null;
  profit_display?: string | null;
  /** Operator-edited prices — no _display twin (RESEARCH §Positions). */
  sl?: number | null;
  tp?: number | null;
}

export interface EditPositionDialogProps {
  /** The position being edited; `null` keeps the dialog closed. */
  position: EditPosition | null;
  /** Controlled open flag (local state in the parent — SC#3, outside the polling subtree). */
  open: boolean;
  /** Close request (✕, overlay click, Esc, or a confirmed success). */
  onClose: () => void;
}

// Lot-step rounding: the partial-close amount is validated to 2 dp (the symbol lot step the
// positions payload renders at). A finer step would need the server symbol metadata; 0.01 matches
// the legacy `%.2f` volume rendering and the API's float lots.
const LOT_STEP = 0.01;

function roundToStep(value: number): number {
  return Math.round(value / LOT_STEP) * LOT_STEP;
}

export function EditPositionDialog({
  position,
  open,
  onClose,
}: EditPositionDialogProps) {
  // ── Local input state (SC#3 — never the query cache) ──────────────────────────────────────────
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");
  const [closeVolume, setCloseVolume] = useState("");

  const levels = useLevels();
  const partial = usePartialClose();

  // Reset typed state whenever a different position opens the modal (keyed by ticket).
  const [lastTicket, setLastTicket] = useState<number | string | null>(null);
  if (position && position.ticket !== lastTicket) {
    setLastTicket(position.ticket);
    setSl("");
    setTp("");
    setCloseVolume("");
  }

  if (!position) return null;

  // ── Partial-close validation (D-04): absolute lots, 0 < value < volume, lot-step rounded ──────
  const closeNum = closeVolume.trim() === "" ? NaN : Number(closeVolume);
  // CR-01: round FIRST, then guard + submit the SAME rounded value. Validating the un-rounded
  // input while submitting the rounded one let `0.998` on a 1.00-lot position pass the guard yet
  // send `close_volume: 1.0` — a FULL close through the partial endpoint. The bound is strict
  // against the rounded value so a partial close always leaves a non-zero remainder.
  const closeRounded = Number.isFinite(closeNum) ? roundToStep(closeNum) : NaN;
  const partialSchema = z
    .number()
    .positive()
    .max(position.volume, { message: "Exceeds open volume." });
  const closeParsed = Number.isFinite(closeRounded)
    ? partialSchema.safeParse(closeRounded)
    : null;
  const closeValid = closeParsed?.success === true && closeRounded < position.volume;
  // Live "Remaining after" readout (the whole point of the absolute-lots model — no percent/slider).
  const remainingAfter =
    Number.isFinite(closeRounded) && closeRounded > 0
      ? Math.max(0, position.volume - closeRounded)
      : position.volume;

  // ── SL/TP submit (independent — D-02) ─────────────────────────────────────────────────────────
  function handleSaveLevels(e: React.FormEvent) {
    e.preventDefault();
    const slNum = sl.trim() === "" ? undefined : Number(sl);
    const tpNum = tp.trim() === "" ? undefined : Number(tp);
    // Send ONLY the changed fields (blank = keep); a no-op resolves {ok:true,changed:{}} server-side.
    levels.mutate(
      { account: position!.account, ticket: position!.ticket, sl: slNum, tp: tpNum },
      // Close the modal ONLY on confirmed success; on error the hook toasts and we stay open.
      { onSuccess: () => onClose() },
    );
  }

  // ── Partial-close submit (independent — D-02) ─────────────────────────────────────────────────
  function handleCloseLots() {
    if (!closeValid) return;
    partial.mutate(
      {
        account: position!.account,
        ticket: position!.ticket,
        // Absolute lots (D-04) — submit the SAME rounded value the guard approved (CR-01).
        closeVolume: closeRounded,
      },
      { onSuccess: () => onClose() },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // Esc / overlay / ✕ → close (never auto-close on a pending mutation submit).
        if (!next) onClose();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Edit position #{position.ticket}</DialogTitle>
        </DialogHeader>

        {/* Position summary grid — *_display twins (Pitfall 5). */}
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
          <div className="text-muted-foreground">Account</div>
          <div className="font-semibold text-card-foreground">
            {position.account}
          </div>

          <div className="text-muted-foreground">Direction</div>
          <div>
            <DirectionBadge direction={position.direction} />
          </div>

          <div className="text-muted-foreground">Volume</div>
          <div className="font-mono text-card-foreground">
            {position.volume_display ?? "—"}
          </div>

          <div className="text-muted-foreground">Entry</div>
          <div className="font-mono text-card-foreground">
            {position.open_price_display ?? "—"}
          </div>

          <div className="text-muted-foreground">P&amp;L</div>
          <div
            className={`font-mono ${
              position.profit == null || position.profit === 0
                ? "text-card-foreground"
                : position.profit > 0
                  ? "text-green-400"
                  : "text-red-400"
            }`}
          >
            {position.profit_display ?? "—"}
          </div>
        </div>

        {/* ── SL/TP modify form (independent submit — cyan "Save SL/TP") ──────────────────────── */}
        <form onSubmit={handleSaveLevels} className="mt-2 flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="edit-sl">Stop Loss</Label>
            <Input
              id="edit-sl"
              type="number"
              step="0.01"
              inputMode="decimal"
              placeholder="Leave blank to keep current"
              value={sl}
              onChange={(e) => setSl(e.target.value)}
              disabled={levels.isPending}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="edit-tp">Take Profit</Label>
            <Input
              id="edit-tp"
              type="number"
              step="0.01"
              inputMode="decimal"
              placeholder="Leave blank to keep current"
              value={tp}
              onChange={(e) => setTp(e.target.value)}
              disabled={levels.isPending}
            />
          </div>
          <div className="flex justify-end">
            {/* cyan variant=default (UI-SPEC: non-destructive primary CTA). */}
            <Button
              type="submit"
              variant="default"
              size="default"
              className="min-h-10"
              disabled={levels.isPending}
            >
              {levels.isPending ? "Saving…" : "Save SL/TP"}
            </Button>
          </div>
        </form>

        <div className="border-t border-border" />

        {/* ── Partial-close form (independent submit — destructive, absolute lots, D-04) ──────── */}
        <div className="flex flex-col gap-2">
          <Label htmlFor="edit-close-volume">Close volume (lots)</Label>
          <Input
            id="edit-close-volume"
            type="number"
            step="0.01"
            min="0"
            inputMode="decimal"
            value={closeVolume}
            onChange={(e) => {
              setCloseVolume(e.target.value);
              // The amount changed → mint a fresh request_id so this is a NEW operation, not a
              // retry of the previous amount (usePartialClose Pitfall-3 contract).
              partial.regenerateRequestId();
            }}
            disabled={partial.isPending}
            aria-invalid={closeVolume.trim() !== "" && !closeValid}
          />
          <p className="text-xs text-muted-foreground">
            Remaining after:{" "}
            <span className="font-mono">{remainingAfter.toFixed(2)}</span>
          </p>
          <p className="text-xs text-muted-foreground">
            Closes the entered lots at market. Remaining stays open.
          </p>
          <div className="flex justify-end">
            {/* Destructive Close lots, wrapped in the two-click InlineConfirm (D-03). Disabled while
                out of range (0 < value < volume) or while the close is in flight. */}
            {closeValid ? (
              <InlineConfirm
                label={partial.isPending ? "Closing…" : "Close lots"}
                ticket={position.ticket}
                onConfirm={handleCloseLots}
                pending={partial.isPending}
                pendingLabel="Closing…"
              />
            ) : (
              <Button
                type="button"
                variant="destructive"
                size="default"
                className="min-h-10"
                disabled
              >
                Close lots
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
