// frontend/src/routes/StagedView.tsx — PAGE-04, the Pending Stages (staged-entries) parity page.
//
// The ONLY page that background-polls (D-07): useQuery refetchInterval 3000, mirroring the legacy
// /staged hx-trigger cadence. Background polling auto-pauses on a hidden tab for free via the
// inherited refetchIntervalInBackground:false (queryClient.ts).
//
// Data contract (10-02 stages widening): GET /api/v2/stages → { active: ActiveStage[], resolved:
//   ResolvedStage[] }.
//   - ACTIVE rows render as a card-per-account (D-08): symbol + BUY/SELL badge + account, then
//     Stages (filled/total — the CORRECT enriched keys, D-13; NOT the legacy template's blank-cell
//     count keys which never resolve → the legacy blank-cell bug; the SPA shows correct values, a
//     documented parity exception), Target Band, Current Price, Elapsed.
//   - The Elapsed value ticks per-second via useElapsed(started_at) off the server machine epoch
//     (10-02 widening) — smooth between the 3s polls, not jumpy (D-06).
//   - RESOLVED rows render in the shared DataTable with the _RESOLVED_STATUS_LABELS map applied
//     CLIENT-SIDE (pure presentation strings, not money/price).
//
// Pitfall-5 discipline: every money/price cell renders the server `_display` string ONLY. The ONE
// client-side number computation allowed is the elapsed DURATION (D-06, exempt). No client-side
// numeric reformatting (no precision re-derivation) anywhere in this file.

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { DataTable, type Column } from "@/components/data/DataTable";
import { Empty } from "@/components/state/Empty";
import { ErrorPanel } from "@/components/state/ErrorPanel";
import { Loading } from "@/components/state/Loading";
import { api } from "@/lib/http";
import { cn } from "@/lib/utils";
import { useElapsed } from "@/lib/useElapsed";

// ── API types (10-02 stages widening) ───────────────────────────────────────────────────────

interface ActiveStage {
  account_name: string;
  symbol: string;
  direction: string;
  // CORRECT enriched keys (D-13) — the legacy template's blank-cell count keys never resolved.
  filled: number;
  total: number;
  band_low: number | null;
  band_low_display: string | null;
  band_high: number | null;
  band_high_display: string | null;
  current_price: number | null;
  current_price_display: string | null;
  distance_str: string | null;
  status: string;
  // Server machine epoch (ISO-8601 + offset) from the 10-02 widening — the useElapsed input.
  started_at: string;
  started_at_display: string | null;
}

interface ResolvedStage {
  id: number;
  signal_id: number | null;
  stage_number: number | null;
  account_name: string | null;
  symbol: string | null;
  direction: string | null;
  status: string;
  cancelled_reason: string | null;
  created_at: string | null;
  created_at_display: string | null;
  filled_at: string | null;
  filled_at_display: string | null;
}

interface StagesPayload {
  active: ActiveStage[];
  resolved: ResolvedStage[];
}

// ── Resolved status_label map (dashboard.py:489-497 _RESOLVED_STATUS_LABELS — reproduced EXACTLY,
//    pure presentation strings, applied client-side) ──────────────────────────────────────────

const RESOLVED_STATUS_LABELS: Record<string, string> = {
  cancelled_by_kill_switch: "Kill-switch drain",
  cancelled_stage1_closed: "Stage 1 exited",
  cancelled_target_reached: "Target/SL reached",
  abandoned_reconnect: "Abandoned (reconnect)",
  failed: "Failed",
  capped: "Capped",
  filled: "Filled",
};

function statusLabel(status: string): string {
  return RESOLVED_STATUS_LABELS[status] ?? status;
}

// ── Small presentational helpers ──────────────────────────────────────────────────────────────

/** BUY/SELL direction badge (green/red); "—" when absent. */
function DirectionBadge({ direction }: { direction: string | null }) {
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

/** Labelled field inside a stage card. */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm text-card-foreground">{children}</span>
    </div>
  );
}

/** A single active-stage card (one per account). Elapsed ticks per-second (D-06). */
function StageCard({ s }: { s: ActiveStage }) {
  // Per-second ticking off the server machine epoch (10-02 widening) — smooth between 3s polls.
  const elapsed = useElapsed(s.started_at);
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold text-card-foreground">
          {s.symbol}
        </span>
        <DirectionBadge direction={s.direction} />
        <span className="text-xs text-muted-foreground">{s.account_name}</span>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {/* CORRECT counts (D-13) — filled/total, not the legacy blank-cell keys. */}
        <Field label="Stages">
          <span className="font-mono">
            {s.filled}/{s.total}
          </span>
        </Field>
        <Field label="Target Band">
          <span className="font-mono">
            {s.band_low_display ?? "—"} – {s.band_high_display ?? "—"}
          </span>
        </Field>
        <Field label="Current Price">
          {/* Server _display string ONLY (Pitfall 5). */}
          <span className="font-mono">{s.current_price_display ?? "—"}</span>
        </Field>
        <Field label="Elapsed">
          {/* The ONE client-side number computation allowed (D-06) — a relative duration. */}
          <span className="font-mono">{elapsed}</span>
        </Field>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────────────────────

export function StagedView() {
  const { data, isPending, isError, error, refetch } = useQuery<StagesPayload>({
    queryKey: ["stages"],
    queryFn: () => api("/api/v2/stages") as Promise<StagesPayload>,
    // The ONLY polling page (D-07). Background pause is free via the inherited
    // refetchIntervalInBackground:false. No manual Refresh button — it self-refreshes.
    refetchInterval: 3000,
  });

  // ── Resolved-table columns: Account | Symbol | Direction | Stage | Status | Reason | Time ──
  const columns: Column<ResolvedStage>[] = [
    { header: "Account", cell: (r) => r.account_name ?? "—" },
    { header: "Symbol", cell: (r) => r.symbol ?? "—", mono: true },
    {
      header: "Direction",
      cell: (r) => <DirectionBadge direction={r.direction} />,
    },
    {
      header: "Stage",
      cell: (r) => (r.stage_number != null ? String(r.stage_number) : "—"),
      align: "right",
      mono: true,
    },
    {
      header: "Status",
      // Apply the _RESOLVED_STATUS_LABELS map CLIENT-SIDE (presentation strings).
      cell: (r) => statusLabel(r.status),
    },
    {
      header: "Reason",
      cell: (r) => (
        <span className="text-muted-foreground">
          {r.cancelled_reason ?? "—"}
        </span>
      ),
    },
    {
      header: "Time",
      // Server _display strings only (Pitfall 5) — prefer filled_at, fall back to created_at.
      cell: (r) => r.filled_at_display ?? r.created_at_display ?? "—",
      mono: true,
    },
  ];

  if (isPending) {
    return (
      <div className="mx-auto max-w-6xl py-6">
        <h2 className="mb-6 text-xl font-semibold text-foreground">
          Pending Stages
        </h2>
        <Loading rows={6} />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="mx-auto max-w-6xl py-6">
        <h2 className="mb-6 text-xl font-semibold text-foreground">
          Pending Stages
        </h2>
        <ErrorPanel error={error} onRetry={() => refetch()} />
      </div>
    );
  }

  const { active, resolved } = data;
  const bothEmpty = active.length === 0 && resolved.length === 0;

  return (
    <div className="mx-auto max-w-6xl py-6">
      <h2 className="mb-6 text-xl font-semibold text-foreground">
        Pending Stages
      </h2>

      {bothEmpty ? (
        <Empty
          title="No staged entries"
          message="No active or recently resolved staged entries. They will appear here as signals stage."
        />
      ) : (
        <div className="flex flex-col gap-8">
          {/* Active stages — card per account (D-08). */}
          <section>
            <h3 className="mb-3 text-sm font-medium text-muted-foreground">
              Active stages
            </h3>
            {active.length === 0 ? (
              <Empty
                title="No active stages"
                message="No stages are currently awaiting their trigger band."
              />
            ) : (
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                {active.map((s, i) => (
                  <StageCard key={`${s.account_name}-${s.symbol}-${i}`} s={s} />
                ))}
              </div>
            )}
          </section>

          {/* Recently resolved — shared DataTable. */}
          <section>
            <h3 className="mb-3 text-sm font-medium text-muted-foreground">
              Recently resolved
            </h3>
            {resolved.length === 0 ? (
              <Empty
                title="No resolved stages"
                message="Recently filled or cancelled stages will appear here."
              />
            ) : (
              <DataTable
                columns={columns}
                rows={resolved}
                rowKey={(r) => r.id}
              />
            )}
          </section>
        </div>
      )}
    </div>
  );
}
