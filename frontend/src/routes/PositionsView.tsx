// frontend/src/routes/PositionsView.tsx — the Positions page (PAGE-06).
//
// 1:1 parity with the legacy positions view (templates/partials/positions_table.html, structure
// only — the HTMX/SSE wiring is NOT replicated). It is the highest-blast-radius interactive surface:
// a 3s-polling DataTable of open positions, each row carrying a destructive Close (two-click
// InlineConfirm + useClose) and an Edit button (opens EditPositionDialog), plus a per-row expandable
// PositionDrilldown.
//
// The money-safe invariants this page enforces:
//   - SC#1 server-confirmed: Close clears the row ONLY via useClose's invalidateQueries in onSuccess
//     — NEVER setQueryData. A position never renders closed while still live at the broker.
//   - SC#3 poll-safe: the Edit dialog AND the drilldown expand-state are LOCAL React state (a Set of
//     open tickets + the open-dialog position), rendered outside the polling subtree — a 3s refetch
//     never collapses an open drilldown or clobbers typed modal input.
//   - D-11: a read failure renders the INLINE ErrorPanel (NOT a toast); mutation errors toast (in the
//     hooks). Empty renders the Empty state.
//
// Pitfall-5: every money/price/volume/P&L cell renders the server `*_display` twin; the raw `profit`
// numeric feeds only DataTable's `sign` accessor (green/red coloring). sl/tp have no _display twin
// (operator-edited prices) — rendered raw with a "—" fallback.

import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import type { Column } from "@/components/data/DataTable";
import { DirectionBadge } from "@/components/data/DirectionBadge";
import { Empty } from "@/components/state/Empty";
import { ErrorPanel } from "@/components/state/ErrorPanel";
import { Loading } from "@/components/state/Loading";
import { Button } from "@/components/ui/button";
import { InlineConfirm } from "@/components/positions/InlineConfirm";
import {
  EditPositionDialog,
  type EditPosition,
} from "@/components/positions/EditPositionDialog";
import { PositionDrilldown } from "@/components/positions/PositionDrilldown";
import { useClose } from "@/hooks/useClose";
import { api } from "@/lib/http";

// ── API type (RESEARCH §Positions list contract) ───────────────────────────────────────────────

interface Position {
  account: string;
  ticket: number | string;
  symbol: string;
  direction: "buy" | "sell";
  volume: number;
  volume_display?: string | null;
  open_price: number;
  open_price_display?: string | null;
  // sl/tp have NO _display twin (operator-edited prices, RESEARCH §Positions).
  sl: number | null;
  tp: number | null;
  profit: number;
  profit_display?: string | null;
}

const PAGE_TITLE = "Positions";

function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-6xl py-6">
      <h2 className="mb-6 text-xl font-semibold text-foreground">{PAGE_TITLE}</h2>
      {children}
    </div>
  );
}

export function PositionsView() {
  const { data, isPending, isError, error, refetch } = useQuery<Position[]>({
    queryKey: ["positions"],
    queryFn: () => api("/api/v2/positions") as Promise<Position[]>,
    // The polling page (D-07). Background pause is free via the inherited
    // refetchIntervalInBackground:false (queryClient.ts).
    refetchInterval: 3000,
  });

  const close = useClose();

  // ── Poll-safe local UI state (SC#3 — NOT the query cache) ─────────────────────────────────────
  // Drilldown expand-state: a Set of open tickets (multi-open allowed; survives refetch).
  const [openTickets, setOpenTickets] = useState<Set<string>>(new Set());
  // The position whose Edit dialog is open (null = closed). Local state, outside the poll subtree.
  const [editing, setEditing] = useState<EditPosition | null>(null);

  function toggleDrilldown(ticket: number | string) {
    const key = String(ticket);
    setOpenTickets((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  // ── Columns (parity: Account|Symbol|Direction|Volume|Entry|SL|TP|P&L|Actions) ─────────────────
  const columns: Column<Position>[] = [
    { header: "Account", cell: (p) => p.account },
    { header: "Symbol", cell: (p) => p.symbol, mono: true },
    {
      header: "Direction",
      cell: (p) => <DirectionBadge direction={p.direction} />,
    },
    {
      header: "Volume",
      cell: (p) => p.volume_display ?? "—",
      align: "right",
      mono: true,
    },
    {
      header: "Entry",
      cell: (p) => p.open_price_display ?? "—",
      align: "right",
      mono: true,
    },
    {
      header: "SL",
      // Raw (no _display twin) — operator-edited price.
      cell: (p) => (p.sl != null ? p.sl : "—"),
      align: "right",
      mono: true,
    },
    {
      header: "TP",
      cell: (p) => (p.tp != null ? p.tp : "—"),
      align: "right",
      mono: true,
    },
    {
      header: "P&L",
      // *_display twin for the text; raw `profit` for the green/red sign coloring (DataTable).
      cell: (p) => p.profit_display ?? "—",
      sign: (p) => p.profit,
      align: "right",
      mono: true,
    },
    {
      header: "Actions",
      cell: (p) => {
        // Per-row pending: useClose is a single page-level hook, so scope its pending to THIS row
        // via the variables it was called with (only the closing ticket shows "Closing…").
        const closingThisRow =
          close.isPending && String(close.variables?.ticket) === String(p.ticket);
        return (
          <div className="flex flex-wrap items-center gap-2">
            {/* Close: two-click InlineConfirm → useClose. UI clears the row ONLY in onSuccess via
                invalidateQueries (SC#1) — never setQueryData. */}
            <InlineConfirm
              label={closingThisRow ? "Closing…" : "Close"}
              ticket={p.ticket}
              onConfirm={() =>
                close.mutate({ account: p.account, ticket: p.ticket })
              }
              pending={closingThisRow}
              pendingLabel="Closing…"
            />
            {/* Edit: opens the combined modal (local state, outside the poll subtree). */}
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="min-h-10"
              onClick={() =>
                setEditing({
                  account: p.account,
                  ticket: p.ticket,
                  symbol: p.symbol,
                  direction: p.direction,
                  volume: p.volume,
                  volume_display: p.volume_display,
                  open_price_display: p.open_price_display,
                  profit: p.profit,
                  profit_display: p.profit_display,
                  sl: p.sl,
                  tp: p.tp,
                })
              }
            >
              Edit
            </Button>
            {/* Drilldown toggle. */}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="min-h-10"
              aria-expanded={openTickets.has(String(p.ticket))}
              onClick={() => toggleDrilldown(p.ticket)}
            >
              {openTickets.has(String(p.ticket)) ? "Hide" : "Details"}
            </Button>
          </div>
        );
      },
    },
  ];

  if (isPending) {
    return (
      <PageShell>
        <Loading rows={6} />
      </PageShell>
    );
  }

  if (isError) {
    // Read failure → INLINE ErrorPanel (D-11), never a toast.
    return (
      <PageShell>
        <ErrorPanel
          error={error}
          message="Something went wrong loading positions."
          onRetry={() => refetch()}
        />
      </PageShell>
    );
  }

  const positions = data;

  return (
    <PageShell>
      {positions.length === 0 ? (
        <Empty
          title="No open positions"
          message="Positions will appear here as signals fill."
        />
      ) : (
        // The table renders Close/Edit/drilldown actions. The drilldown rows are rendered
        // immediately after each position row, gated by the local openTickets Set (SC#3).
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50">
                {columns.map((c) => (
                  <th
                    key={c.header}
                    className={`px-4 py-3 font-medium text-muted-foreground ${
                      c.align === "right" ? "text-right" : "text-left"
                    }`}
                  >
                    {c.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => {
                const isOpen = openTickets.has(String(p.ticket));
                return (
                  <Fragment key={p.ticket}>
                    <tr className="border-b border-border last:border-b-0 hover:bg-muted/30">
                      {columns.map((c) => {
                        const s = c.sign?.(p);
                        const tone =
                          s == null || s === 0
                            ? ""
                            : s > 0
                              ? "text-green-400"
                              : "text-red-400";
                        return (
                          <td
                            key={c.header}
                            className={`px-4 py-3 ${c.mono ? "font-mono" : ""} ${
                              c.align === "right" ? "text-right" : ""
                            } ${tone}`}
                          >
                            {c.cell(p)}
                          </td>
                        );
                      })}
                    </tr>
                    {isOpen ? (
                      <tr className="border-b border-border last:border-b-0">
                        <td colSpan={columns.length} className="p-0">
                          {/* Drilldown renders OUTSIDE the polling subtree's data flow — its own
                              query, mounted/unmounted by the local openTickets Set (SC#3). */}
                          <div className="px-4 pb-4">
                            <PositionDrilldown
                              account={p.account}
                              ticket={p.ticket}
                            />
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Edit dialog — rendered at the page root (the shadcn Dialog portals it out of the table /
          polling subtree). Local `editing` state drives open/close (SC#3). */}
      <EditPositionDialog
        position={editing}
        open={editing !== null}
        onClose={() => setEditing(null)}
      />
    </PageShell>
  );
}
