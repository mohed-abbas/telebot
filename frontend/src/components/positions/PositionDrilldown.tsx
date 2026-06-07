// frontend/src/components/positions/PositionDrilldown.tsx — the per-position drilldown (D-01).
//
// Reads GET /api/v2/positions/{account}/{ticket} → { position, fill_history[], signal } and lays it
// out like StagedView's StageCard/Field: a Fill-History DataTable, a Current-P/L + Entry/SL/TP row,
// and a Signal-Source block whose raw text lives in a <details> (parity ref position_drilldown.html,
// structure only — the legacy HTMX/SSE wiring is NOT replicated).
//
// Pitfall-5 discipline: every money/price/lot value renders the server `*_display` twin ONLY — there
// is no `toFixed`/`Intl`/`Math.round` on any money field in this file. sl/tp have no `_display` twin
// (operator-edited prices, RESEARCH §Positions) — they render raw with a "—" fallback.
//
// SC#3: the open/expanded state that mounts this component is held in the PARENT (PositionsView) as
// local React state keyed by ticket, so a 3s background refetch never collapses an open drilldown.
// This component itself only owns its own read query (keyed by ticket) — keepPreviousData (inherited)
// means a refetch never flickers it back to Loading.

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { DataTable, type Column } from "@/components/data/DataTable";
import { ErrorPanel } from "@/components/state/ErrorPanel";
import { Loading } from "@/components/state/Loading";
import { api } from "@/lib/http";

// ── API types (RESEARCH §Positions drilldown) ──────────────────────────────────────────────────

interface DrilldownPosition {
  entry_price_display?: string | null;
  lot_size_display?: string | null;
  pnl?: number | null;
  pnl_display?: string | null;
  sl?: number | null;
  tp?: number | null;
}

interface FillRow {
  stage_number?: number | null;
  filled_at_display?: string | null;
  lot_size_display?: string | null;
  band_low_display?: string | null;
  band_high_display?: string | null;
  sl_at_fill_display?: string | null;
  status?: string | null;
}

interface DrilldownSignal {
  source_name?: string | null;
  signal_type?: string | null;
  raw_text?: string | null;
  timestamp_display?: string | null;
}

interface DrilldownPayload {
  position: DrilldownPosition;
  fill_history: FillRow[];
  signal: DrilldownSignal | null;
}

// ── Labelled field (mirrors StagedView Field) ──────────────────────────────────────────────────

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm text-card-foreground">{children}</span>
    </div>
  );
}

export interface PositionDrilldownProps {
  account: string;
  ticket: number | string;
}

export function PositionDrilldown({ account, ticket }: PositionDrilldownProps) {
  const { data, isPending, isError, error, refetch } = useQuery<DrilldownPayload>({
    // Keyed by account+ticket so each open drilldown is its own cache entry (multi-open allowed).
    queryKey: ["position-drilldown", account, ticket],
    queryFn: () =>
      api(`/api/v2/positions/${encodeURIComponent(account)}/${encodeURIComponent(String(ticket))}`) as Promise<DrilldownPayload>,
  });

  if (isPending) {
    return (
      <div className="rounded-lg bg-muted/30 p-4">
        <Loading rows={3} />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="rounded-lg bg-muted/30 p-4">
        <ErrorPanel error={error} onRetry={() => refetch()} />
      </div>
    );
  }

  const { position, fill_history, signal } = data;

  // Fill-History columns: Stage | Time | Lots | Band | SL at Fill | Status (parity).
  const fillColumns: Column<FillRow>[] = [
    {
      header: "Stage",
      cell: (f) => (f.stage_number != null ? String(f.stage_number) : "—"),
      mono: true,
    },
    {
      header: "Time",
      cell: (f) => f.filled_at_display ?? "—",
      mono: true,
    },
    {
      header: "Lots",
      // *_display twin only (Pitfall 5).
      cell: (f) => f.lot_size_display ?? "—",
      align: "right",
      mono: true,
    },
    {
      header: "Band",
      cell: (f) =>
        f.band_low_display && f.band_high_display
          ? `${f.band_low_display} – ${f.band_high_display}`
          : "Market",
      mono: true,
    },
    {
      header: "SL at Fill",
      cell: (f) => f.sl_at_fill_display ?? "—",
      align: "right",
      mono: true,
    },
    {
      header: "Status",
      cell: (f) =>
        f.status === "filled" ? (
          <span className="text-green-400">filled</span>
        ) : (
          <span className="text-muted-foreground">{f.status ?? "—"}</span>
        ),
    },
  ];

  // P&L color from the raw numeric (sign), text from the *_display twin (Pitfall 5).
  const pnl = position.pnl;
  const pnlTone =
    pnl == null || pnl === 0
      ? "text-card-foreground"
      : pnl > 0
        ? "text-green-400"
        : "text-red-400";

  return (
    <div className="mt-2 flex flex-col gap-4 rounded-lg bg-muted/30 p-4">
      {/* Fill History */}
      <section>
        <h4 className="mb-2 text-sm font-semibold text-card-foreground">
          Fill History
        </h4>
        {fill_history.length === 0 ? (
          <p className="text-xs text-muted-foreground">No fills recorded.</p>
        ) : (
          <DataTable
            columns={fillColumns}
            rows={fill_history}
            rowKey={(f, i) => f.stage_number ?? i}
          />
        )}
      </section>

      {/* Current P/L + Entry / SL / TP */}
      <section className="flex flex-wrap items-start gap-6">
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted-foreground">Current P/L</span>
          {/* *_display twin only; color from the raw sign. */}
          <span className={`font-mono text-lg font-semibold ${pnlTone}`}>
            {position.pnl_display ?? "0.00"}
          </span>
        </div>
        <Field label="Entry">
          <span className="font-mono">{position.entry_price_display ?? "—"}</span>
        </Field>
        <Field label="SL">
          {/* sl has no _display twin (operator-edited price) — render raw. */}
          <span className="font-mono">
            {position.sl != null ? position.sl : "—"}
          </span>
        </Field>
        <Field label="TP">
          <span className="font-mono">
            {position.tp != null ? position.tp : "—"}
          </span>
        </Field>
      </section>

      {/* Signal Source attribution */}
      <section className="border-t border-border pt-3">
        {signal ? (
          <>
            <h4 className="mb-2 text-sm font-semibold text-card-foreground">
              Signal Source
            </h4>
            <div className="flex flex-col gap-1 text-xs">
              <div>
                <span className="text-muted-foreground">Source: </span>
                <span className="font-medium text-card-foreground">
                  {signal.source_name ?? "Unknown"}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">Time: </span>
                <span className="text-card-foreground">
                  {signal.timestamp_display ?? "—"}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">Type: </span>
                <span className="capitalize text-card-foreground">
                  {signal.signal_type
                    ? signal.signal_type.replace(/_/g, " ")
                    : "—"}
                </span>
              </div>
              {signal.raw_text ? (
                <details className="mt-2">
                  <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                    Raw signal text
                  </summary>
                  <pre className="mt-1 overflow-x-auto rounded bg-muted p-2 text-xs whitespace-pre-wrap text-card-foreground">
                    {signal.raw_text.slice(0, 500)}
                  </pre>
                </details>
              ) : null}
            </div>
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            No linked signal (manual or imported trade)
          </p>
        )}
      </section>
    </div>
  );
}
