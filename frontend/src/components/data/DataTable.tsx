// frontend/src/components/data/DataTable.tsx — the shared column-driven table (D-10).
//
// Hand-rolled (NO @tanstack/react-table — not installed, not needed). The column model is
// `Column<Row>{ header, cell, align?, mono?, sign? }`:
//   - `cell(row)` returns whatever the CALLER passes — for money/price columns that is the
//     server `_display` string. The table NEVER formats numbers (Pitfall 5 / Pitfall 2):
//     no client-side number formatting anywhere in this file.
//   - `align: "right"` + `mono` give right-aligned tabular numerics.
//   - `sign(row)` is an OPTIONAL raw-number accessor used ONLY to color the cell green/red
//     by sign (P&L). The displayed text still comes from `cell` (the _display string).
//
// Token conventions copied from Sidebar/AppShell: bg-card, border, text-muted-foreground,
// hover:bg-muted/30, font-mono. The cyan --primary accent is reserved (never used for data) —
// active-row highlighting via bg-primary/10 is the caller's concern (passed through rowClassName).

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type Align = "left" | "right";

export interface Column<Row> {
  /** Column header label. */
  header: string;
  /** Cell renderer — caller passes the server `_display` string for money/price columns. */
  cell: (row: Row) => ReactNode;
  /** Numeric columns → "right". Defaults to "left". */
  align?: Align;
  /** Tabular numerics → font-mono. */
  mono?: boolean;
  /** Optional raw-number accessor: colors the cell green/red by sign (P&L). */
  sign?: (row: Row) => number | null | undefined;
}

export interface DataTableProps<Row> {
  columns: Column<Row>[];
  rows: Row[];
  /** Stable key per row (index fallback if omitted). */
  rowKey?: (row: Row, index: number) => string | number;
  /** Optional per-row click handler (e.g. by-source row → ?source=). */
  onRowClick?: (row: Row) => void;
  /** Optional per-row className (e.g. active-row bg-primary/10). */
  rowClassName?: (row: Row) => string | undefined;
}

export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  onRowClick,
  rowClassName,
}: DataTableProps<Row>) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="sticky top-0 border-b border-border bg-muted/50">
            {columns.map((c) => (
              <th
                key={c.header}
                className={cn(
                  "px-4 py-3 font-medium text-muted-foreground",
                  c.align === "right" ? "text-right" : "text-left",
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={rowKey ? rowKey(row, i) : i}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={cn(
                "border-b border-border last:border-b-0 hover:bg-muted/30",
                onRowClick && "cursor-pointer",
                rowClassName?.(row),
              )}
            >
              {columns.map((c) => {
                const s = c.sign?.(row);
                const tone =
                  s == null || s === 0
                    ? ""
                    : s > 0
                      ? "text-green-400"
                      : "text-red-400";
                return (
                  <td
                    key={c.header}
                    className={cn(
                      "px-4 py-3",
                      c.mono && "font-mono",
                      c.align === "right" && "text-right",
                      tone,
                    )}
                  >
                    {c.cell(row)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
