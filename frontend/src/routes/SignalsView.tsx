// frontend/src/routes/SignalsView.tsx — PAGE-02, the Signal Log parity page.
//
// A read-only snapshot table of recent signals, mirroring the legacy templates/signals.html
// column set EXACTLY: Time, Type, Symbol, Direction, Zone (low–high), SL, TP, Action, Details.
// Reuses the Plan-04 shared primitives (DataTable + the Loading/Empty/ErrorPanel state trio).
//
// Data contract (10-03 signals widening, consumed here): GET /api/v2/signals returns rows with
//   id, raw_text, signal_type, symbol, direction, action_taken, received_at(+_display),
//   entry_zone_low/high(+_display), sl/tp(+_display), details, source_name.
//
// Pitfall-5 discipline: every money/price cell renders the server `_display` string ONLY —
// no client-side number reformatting anywhere in this file.
//
// XSS safety (T-10-11): the Details cell renders `details ?? raw_text` as a React TEXT CHILD —
// channel-sourced signal text must not become live DOM (raw-HTML injection forbidden here).
//
// Polling: NONE (D-03) — signals never background-polls. A manual Refresh button (D-04) calls
// refetch(). The query sets no polling interval.

import { useQuery } from "@tanstack/react-query";

import { DataTable, type Column } from "@/components/data/DataTable";
import { Empty } from "@/components/state/Empty";
import { ErrorPanel } from "@/components/state/ErrorPanel";
import { Loading } from "@/components/state/Loading";
import { Button } from "@/components/ui/button";
import { DirectionBadge } from "@/components/data/DirectionBadge";
import { api } from "@/lib/http";

// ── API type (10-03 signals widening) ──────────────────────────────────────────────────────

interface Signal {
  id: number;
  raw_text: string;
  signal_type: string;
  symbol: string | null;
  direction: string | null;
  action_taken: string | null;
  received_at: string | null;
  received_at_display: string | null;
  entry_zone_low: number | null;
  entry_zone_low_display: string | null;
  entry_zone_high: number | null;
  entry_zone_high_display: string | null;
  sl: number | null;
  sl_display: string | null;
  tp: number | null;
  tp_display: string | null;
  details: string | null;
  source_name: string | null;
}

// ── Type-label map (legacy signals.html:31-46 — reproduced EXACTLY, presentation strings) ───
//
// open→OPEN, open_text_only→OPEN (NOW), close→CLOSE, close_partial→PARTIAL,
// modify_sl→MOD SL, modify_tp→MOD TP, else the raw signal_type.

const TYPE_LABELS: Record<string, string> = {
  open: "OPEN",
  open_text_only: "OPEN (NOW)",
  close: "CLOSE",
  close_partial: "PARTIAL",
  modify_sl: "MOD SL",
  modify_tp: "MOD TP",
};

function typeLabel(signalType: string): string {
  return TYPE_LABELS[signalType] ?? signalType;
}

// ── Small presentational helpers ────────────────────────────────────────────────────────────

/** A muted token badge for the mapped Type label. */
function TypeBadge({ signalType }: { signalType: string }) {
  return (
    <span className="rounded-md bg-muted/50 px-2 py-0.5 font-mono text-xs text-card-foreground">
      {typeLabel(signalType)}
    </span>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────────────────

export function SignalsView() {
  const { data, isPending, isError, error, refetch, isFetching } = useQuery<
    Signal[]
  >({
    queryKey: ["signals"],
    // No background poll (D-03) — signals is snapshot-only; manual Refresh re-queries.
    queryFn: () => api("/api/v2/signals") as Promise<Signal[]>,
  });

  // ── Columns in legacy order: Time | Type | Symbol | Direction | Zone | SL | TP | Action | Details ──
  const columns: Column<Signal>[] = [
    { header: "Time", cell: (r) => r.received_at_display ?? "—", mono: true },
    { header: "Type", cell: (r) => <TypeBadge signalType={r.signal_type} /> },
    { header: "Symbol", cell: (r) => r.symbol ?? "—", mono: true },
    {
      header: "Direction",
      cell: (r) => <DirectionBadge direction={r.direction} />,
    },
    {
      header: "Zone",
      // Server `_display` strings only (Pitfall 5). low–high; "—" when absent.
      cell: (r) =>
        r.entry_zone_low_display || r.entry_zone_high_display
          ? `${r.entry_zone_low_display ?? "—"}–${r.entry_zone_high_display ?? "—"}`
          : "—",
      align: "right",
      mono: true,
    },
    {
      header: "SL",
      cell: (r) => r.sl_display ?? "—",
      align: "right",
      mono: true,
    },
    {
      header: "TP",
      cell: (r) => r.tp_display ?? "—",
      align: "right",
      mono: true,
    },
    { header: "Action", cell: (r) => r.action_taken ?? "—" },
    {
      header: "Details",
      // XSS-safe: `details ?? raw_text` rendered as a React text child (T-10-11). The legacy
      // 80-char slice is presentation only — truncate visually with CSS, never via the value.
      cell: (r) => (
        <span
          className="block max-w-xs truncate text-muted-foreground"
          title={r.details ?? r.raw_text ?? ""}
        >
          {r.details ?? r.raw_text ?? "—"}
        </span>
      ),
    },
  ];

  return (
    <div className="mx-auto max-w-6xl py-6">
      {/* Header: title + manual Refresh (D-04) */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-foreground">Signal Log</h2>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          Refresh
        </Button>
      </div>

      {/* Query states */}
      {isPending ? (
        <Loading rows={8} />
      ) : isError ? (
        <ErrorPanel error={error} onRetry={() => refetch()} />
      ) : data.length === 0 ? (
        <Empty
          title="No signals yet"
          message="No signals have been received. New signals will appear here."
        />
      ) : (
        <DataTable columns={columns} rows={data} rowKey={(r) => r.id} />
      )}
    </div>
  );
}
