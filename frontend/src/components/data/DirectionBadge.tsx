// frontend/src/components/data/DirectionBadge.tsx — shared BUY/SELL direction badge.
//
// Extracted from HistoryView/SignalsView/StagedView, which carried byte-identical copies
// (IN-01). Single source for the green/red tone tokens and the "—" absent fallback.

import { cn } from "@/lib/utils";

/** BUY/SELL direction badge (green/red); "—" when absent. */
export function DirectionBadge({ direction }: { direction: string | null }) {
  if (!direction) return <span className="text-muted-foreground">—</span>;
  const up = direction.toUpperCase();
  const tone =
    up === "BUY"
      ? "bg-green-400/10 text-green-400"
      : up === "SELL"
        ? "bg-red-400/10 text-red-400"
        : "bg-muted/50 text-card-foreground";
  return (
    <span className={cn("rounded-md px-2 py-0.5 font-mono text-xs", tone)}>
      {up}
    </span>
  );
}
