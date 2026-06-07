// frontend/src/components/settings/ConfirmDiffDialog.tsx — the confirm step (D-05/D-06, PAGE-08).
//
// Step 2 of the two-step settings flow: after /validate returns valid:true, this modal shows the
// operator EXACTLY what will change before anything persists. It renders:
//   • the validate diff table (Field | old → new),
//   • the server-rendered dry_run_text VERBATIM (Pitfall 5 — do NOT recompute; it is the server's
//     authoritative human summary of the change),
//   • the footgun RESTATED via footgun(mode, risk_value, max_stages) (mode-aware — no multiply in
//     fixed_lot, Pitfall 6) so the compounded-exposure warning is repeated at the point of commit.
//
// The shadcn Dialog is opaque (Pitfall-9 verified in 11-01) and renders outside any polling subtree
// (Settings does not poll, so this is naturally satisfied — SC#3).
//
// "Confirm change" (cyan variant=default, disabled-while-pending → "Saving…") fires the confirm path;
// "Go back" closes the modal WITHOUT persisting or discarding — the editable form keeps the typed
// values (the parent owns the form state; this modal is controlled via open/onOpenChange).

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { footgun } from "@/lib/footgun";
import type { SettingsDiffEntry } from "@/hooks/useSettingsMutations";

export interface ConfirmDiffDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  account: string;
  /** The validate diff (Field | old → new). */
  diff: SettingsDiffEntry[];
  /** The server-rendered human summary — shown VERBATIM (Pitfall 5). */
  dryRunText: string;
  /** Mode-aware footgun inputs (restated at the point of commit). */
  mode: "percent" | "fixed_lot";
  riskValue: number;
  maxStages: number;
  /** Fires the confirm (persist) path. */
  onConfirm: () => void;
  /** True while the confirm mutation is in-flight → disables Confirm, shows "Saving…". */
  pending: boolean;
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  return String(v);
}

export function ConfirmDiffDialog({
  open,
  onOpenChange,
  account,
  diff,
  dryRunText,
  mode,
  riskValue,
  maxStages,
  onConfirm,
  pending,
}: ConfirmDiffDialogProps) {
  const footgunText = footgun(mode, riskValue, maxStages);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Confirm settings change — {account}</DialogTitle>
          <DialogDescription>
            Review the change below. It applies to signals received AFTER you
            confirm. In-flight staged sequences are unaffected.
          </DialogDescription>
        </DialogHeader>

        {/* Diff table — Field | old → new. */}
        {diff.length > 0 && (
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50 text-left text-muted-foreground">
                  <th className="px-3 py-2 font-medium">Field</th>
                  <th className="px-3 py-2 font-medium">Change</th>
                </tr>
              </thead>
              <tbody>
                {diff.map((d) => (
                  <tr
                    key={d.field}
                    className="border-b border-border last:border-b-0"
                  >
                    <td className="px-3 py-2">{d.field}</td>
                    <td className="px-3 py-2 font-mono">
                      <span className="text-muted-foreground">
                        {fmt(d.old)}
                      </span>{" "}
                      → <span className="text-foreground">{fmt(d.new)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Server dry-run summary — VERBATIM (Pitfall 5: do NOT recompute). */}
        {dryRunText && (
          <p className="whitespace-pre-wrap text-sm text-muted-foreground">
            {dryRunText}
          </p>
        )}

        {/* Footgun RESTATED at the point of commit (mode-aware — Pitfall 6). */}
        <div
          role="note"
          className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-400"
        >
          <span>{footgunText}</span>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={pending}
          >
            Go back
          </Button>
          <Button onClick={onConfirm} disabled={pending}>
            {pending ? "Saving…" : "Confirm change"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
