// frontend/src/components/state/Empty.tsx — shared empty state (D-10).
//
// Driven by `data.length === 0` (or an empty payload). An icon + copy panel — NOT an error.
// lucide-react icon usage mirrors AppShell (`Menu, X` from lucide-react). Tokens: bg-card,
// border-border, text-muted-foreground.

import { Inbox, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export interface EmptyProps {
  /** Headline (e.g. "No trades yet"). */
  title?: string;
  /** Secondary copy explaining the empty state. */
  message?: string;
  /** lucide icon component; defaults to Inbox. */
  icon?: LucideIcon;
  className?: string;
}

export function Empty({
  title = "Nothing to show",
  message,
  icon: Icon = Inbox,
  className,
}: EmptyProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-card px-6 py-12 text-center",
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-8 text-muted-foreground" />
      <p className="text-sm font-medium text-card-foreground">{title}</p>
      {message ? (
        <p className="max-w-sm text-xs text-muted-foreground">{message}</p>
      ) : null}
    </div>
  );
}
