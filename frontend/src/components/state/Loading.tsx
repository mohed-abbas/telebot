// frontend/src/components/state/Loading.tsx — shared skeleton loading state (D-10).
//
// Driven by a query's `isPending`. Renders skeleton rows (plain animate-pulse divs with border
// tokens — no shadcn `skeleton` dependency so the state trio is self-contained). Tokens copied
// from Sidebar/AppShell: bg-card, border-border, bg-muted.

import { cn } from "@/lib/utils";

export interface LoadingProps {
  /** Number of skeleton rows to render. */
  rows?: number;
  className?: string;
}

export function Loading({ rows = 5, className }: LoadingProps) {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-live="polite"
      className={cn(
        "overflow-hidden rounded-lg border border-border bg-card",
        className,
      )}
    >
      <span className="sr-only">Loading…</span>
      <div className="divide-y divide-border">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 px-4 py-3">
            <div className="h-4 flex-1 animate-pulse rounded bg-muted" />
            <div className="h-4 w-20 animate-pulse rounded bg-muted" />
            <div className="h-4 w-16 animate-pulse rounded bg-muted" />
          </div>
        ))}
      </div>
    </div>
  );
}
