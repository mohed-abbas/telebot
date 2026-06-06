// frontend/src/routes/AnalyticsView.tsx — PAGE-01, the analytics pilot.
//
// The first real SPA page. Proves the full API+SPA+auth+nginx stack on a read-only, no-live-money
// surface (SC#1) and exercises every shared primitive built in Task 1 (DataTable, the Loading/
// Empty/ErrorPanel state trio, useUrlFilters).
//
// Data contract (10-01 widening, consumed here): GET /api/v2/analytics returns
//   { total_trades, wins, losses, win_rate, profit_factor,
//     total_profit(+_display), gross_profit(+_display), gross_loss(+_display),
//     by_source: [{ source_name, total_trades, wins, losses, win_rate, profit_factor,
//                   net_pnl(+_display), best_trade(+_display), worst_trade(+_display) }],
//     extremes: { best_trade(+_display), worst_trade(+_display) },
//     avg_stages: float | null, sources: [str] }
//
// Filter state lives in the URL (?range=&source=) via useUrlFilters (D-02). Range tabs map
// 7d→7 / 30d→30 / 90d→90 / all→"" ; empty source = no filter (all-source default load).
//
// Pitfall-5 discipline: money/price render from server `_display` strings ONLY. win_rate and
// profit_factor are RATIOS (not money/price) and per D-14 may be formatted client-side (the
// percent / ratio affordance), mirroring the legacy template; avg_stages is a count, likewise.
//
// Polling: NONE (D-03) — analytics never background-polls; refetchOnWindowFocus is the inherited
// v5 default. A manual Refresh button (D-04) calls refetch().

import { useQuery } from "@tanstack/react-query";

import { DataTable, type Column } from "@/components/data/DataTable";
import { Empty } from "@/components/state/Empty";
import { ErrorPanel } from "@/components/state/ErrorPanel";
import { Loading } from "@/components/state/Loading";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/http";
import { useUrlFilters } from "@/lib/useUrlFilters";
import { cn } from "@/lib/utils";

// ── API types (10-01 analytics widening) ──────────────────────────────────────────────────

interface AnalyticsBySource {
  source_name: string;
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  profit_factor: number | null;
  net_pnl: number;
  net_pnl_display: string;
  best_trade: number | null;
  best_trade_display: string | null;
  worst_trade: number | null;
  worst_trade_display: string | null;
}

interface AnalyticsExtremes {
  best_trade: number | null;
  best_trade_display: string | null;
  worst_trade: number | null;
  worst_trade_display: string | null;
}

interface Analytics {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  profit_factor: number | null;
  total_profit: number;
  total_profit_display: string;
  gross_profit: number;
  gross_profit_display: string;
  gross_loss: number;
  gross_loss_display: string;
  by_source: AnalyticsBySource[];
  extremes: AnalyticsExtremes;
  avg_stages: number | null;
  sources: string[];
}

interface AnalyticsFilters extends Record<string, string> {
  range: string;
  source: string;
}

// ── Ratio formatting (NOT money/price — allowed client-side per D-14) ─────────────────────

/** win_rate is a 0–100 percentage in the legacy template ("%.1f" + "%"). */
function formatWinRate(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${value.toFixed(1)}%`;
}

/** profit_factor is a dimensionless ratio in the legacy template ("%.2f"). */
function formatProfitFactor(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toFixed(2);
}

// ── Range tabs ────────────────────────────────────────────────────────────────────────────

const RANGE_TABS: { label: string; value: string }[] = [
  { label: "7d", value: "7" },
  { label: "30d", value: "30" },
  { label: "90d", value: "90" },
  { label: "All", value: "" },
];

// ── Small presentational helpers ──────────────────────────────────────────────────────────

function KpiCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "green" | "red" | "neutral";
}) {
  const toneClass =
    tone === "green"
      ? "text-green-400"
      : tone === "red"
        ? "text-red-400"
        : "text-card-foreground";
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className={cn("mt-1 font-mono text-2xl font-semibold", toneClass)}>
        {value}
      </p>
      {sub ? (
        <p className="mt-1 font-mono text-xs text-muted-foreground">{sub}</p>
      ) : null}
    </div>
  );
}

function PnlRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "green" | "red";
}) {
  const toneClass =
    tone === "green"
      ? "text-green-400"
      : tone === "red"
        ? "text-red-400"
        : "text-card-foreground";
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={cn("font-mono text-sm", toneClass)}>{value}</span>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────────────────

export function AnalyticsView() {
  const { filters, setFilter } = useUrlFilters<AnalyticsFilters>([
    "range",
    "source",
  ]);

  const { data, isPending, isError, error, refetch, isFetching } =
    useQuery<Analytics>({
      // Key derives from the URL filters → a URL change auto-refetches (keepPreviousData = no flicker).
      queryKey: ["analytics", filters],
      queryFn: () => {
        const params = new URLSearchParams();
        if (filters.range) params.set("range", filters.range);
        if (filters.source) params.set("source", filters.source);
        const qs = params.toString();
        return api(`/api/v2/analytics${qs ? `?${qs}` : ""}`) as Promise<Analytics>;
      },
      // No background poll (D-03) — analytics is snapshot-only; manual Refresh re-queries.
    });

  // ── By-source DataTable columns (legacy order: Source | Trades | W/L | Win Rate | PF | Net P&L | Best/Worst) ──
  const columns: Column<AnalyticsBySource>[] = [
    { header: "Source", cell: (r) => r.source_name },
    { header: "Trades", cell: (r) => r.total_trades, align: "right", mono: true },
    {
      header: "W/L",
      cell: (r) => `${r.wins}/${r.losses}`,
      align: "right",
      mono: true,
    },
    {
      header: "Win Rate",
      cell: (r) => formatWinRate(r.win_rate),
      align: "right",
      mono: true,
    },
    {
      header: "PF",
      cell: (r) => formatProfitFactor(r.profit_factor),
      align: "right",
      mono: true,
    },
    {
      header: "Net P&L",
      cell: (r) => r.net_pnl_display,
      align: "right",
      mono: true,
      sign: (r) => r.net_pnl,
    },
    {
      header: "Best/Worst",
      cell: (r) =>
        `${r.best_trade_display ?? "—"} / ${r.worst_trade_display ?? "—"}`,
      align: "right",
      mono: true,
    },
  ];

  return (
    <div className="mx-auto max-w-6xl py-6">
      {/* Header: title + range tabs + manual Refresh (D-04) */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-foreground">Analytics</h2>
        <div className="flex items-center gap-2">
          <div
            role="tablist"
            aria-label="Date range"
            className="flex rounded-md border border-border bg-card p-0.5"
          >
            {RANGE_TABS.map((tab) => {
              const active = filters.range === tab.value;
              return (
                <button
                  key={tab.label}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setFilter({ range: tab.value })}
                  className={cn(
                    "rounded px-3 py-1 text-sm transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
                    active
                      ? "bg-primary/10 font-medium text-primary"
                      : "text-muted-foreground hover:bg-muted/30",
                  )}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>
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
      </div>

      {/* Active source filter chip */}
      {filters.source ? (
        <div className="mb-4 flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Source:</span>
          <span className="rounded-md bg-primary/10 px-2 py-0.5 font-mono text-sm text-primary">
            {filters.source}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={() => setFilter({ source: "" })}
          >
            Clear
          </Button>
        </div>
      ) : null}

      {/* Query states */}
      {isPending ? (
        <Loading rows={6} />
      ) : isError ? (
        <ErrorPanel error={error} onRetry={() => refetch()} />
      ) : (
        <div className="flex flex-col gap-6">
          {/* KPI cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KpiCard
              label="Total Trades"
              value={String(data.total_trades)}
              sub={`${data.wins} W / ${data.losses} L`}
            />
            <KpiCard
              label="Win Rate"
              value={formatWinRate(data.win_rate)}
              tone={(data.win_rate ?? 0) >= 50 ? "green" : "red"}
            />
            <KpiCard
              label="Profit Factor"
              value={formatProfitFactor(data.profit_factor)}
              tone={(data.profit_factor ?? 0) > 1.0 ? "green" : "red"}
            />
            <KpiCard
              label="Net P&L"
              value={data.total_profit_display}
              tone={data.total_profit > 0 ? "green" : "red"}
            />
          </div>

          {/* P&L panel + optional Avg-Stages card */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="rounded-lg border border-border bg-card p-4 lg:col-span-2">
              <p className="mb-2 text-sm font-medium text-card-foreground">
                Profit &amp; Loss
              </p>
              <PnlRow
                label="Gross Profit"
                value={data.gross_profit_display}
                tone="green"
              />
              <PnlRow
                label="Gross Loss"
                value={data.gross_loss_display}
                tone="red"
              />
              <div className="my-2 border-t border-border" />
              <PnlRow
                label="Best Trade"
                value={data.extremes.best_trade_display ?? "—"}
                tone="green"
              />
              <PnlRow
                label="Worst Trade"
                value={data.extremes.worst_trade_display ?? "—"}
                tone="red"
              />
            </div>

            {/* Avg-Stages card — renders ONLY when a source filter yields a truthy avg_stages (Pitfall 3). */}
            {data.avg_stages ? (
              <div className="rounded-lg border border-border bg-card p-4">
                <p className="text-xs font-medium text-muted-foreground">
                  Avg Stages Filled
                </p>
                <p className="mt-1 font-mono text-2xl font-semibold text-card-foreground">
                  {data.avg_stages.toFixed(2)}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  for source {filters.source}
                </p>
              </div>
            ) : null}
          </div>

          {/* Performance by source */}
          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium text-card-foreground">
              Performance by Source
            </p>
            {data.by_source.length === 0 ? (
              <Empty
                title="No trades in this range"
                message="No closed trades match the selected date range. Try a wider range."
              />
            ) : (
              <DataTable
                columns={columns}
                rows={data.by_source}
                rowKey={(r) => r.source_name}
                onRowClick={(r) =>
                  setFilter({ source: r.source_name }, { push: true })
                }
                rowClassName={(r) =>
                  filters.source === r.source_name ? "bg-primary/10" : undefined
                }
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
