// frontend/src/routes/HistoryView.tsx — PAGE-03, the Trade History parity page.
//
// A read-only snapshot table of closed trades, mirroring the legacy templates/history_table.html
// column set EXACTLY (Time, Account, Source, Symbol, Direction, Entry, SL, TP, Lots, Status, P&L),
// plus a 5-field filter bar (account/source/symbol/from_date/to_date) whose state lives in the URL
// (bookmarkable, D-05). Reuses the Plan-04 shared primitives (DataTable + state trio + useUrlFilters).
//
// Data contract (10-03 history widening, consumed here): GET /api/v2/history returns rows with
//   account, ticket, symbol, direction, volume(+_display), open_price(+_display),
//   close_price(+_display), profit(+_display), opened_at(+_display), closed_at(+_display),
//   sl/tp(+_display), status, source_name. GET params: account/source/symbol/from_date/to_date.
// GET /api/v2/history/filter-options → { accounts, symbols, sources, directions } — directions is
// empty (not a filter, D-05); the three populated lists drive the dropdowns.
//
// Pitfall-5 discipline: every money/price cell renders the server `_display` string ONLY —
// no client-side number reformatting anywhere in this file.
//
// Polling: NONE (D-03) — history never background-polls. Manual Refresh (D-04). The inherited
// global keepPreviousData gives flicker-free filter changes (no row flash on a filter edit).

import { useQuery } from "@tanstack/react-query";

import { DataTable, type Column } from "@/components/data/DataTable";
import { Empty } from "@/components/state/Empty";
import { ErrorPanel } from "@/components/state/ErrorPanel";
import { Loading } from "@/components/state/Loading";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/http";
import { useUrlFilters } from "@/lib/useUrlFilters";
import { cn } from "@/lib/utils";

// ── API types (10-03 history widening) ──────────────────────────────────────────────────────

interface HistoryTrade {
  account: string | number | null;
  ticket: string | number | null;
  symbol: string | null;
  direction: string | null;
  volume: number | null;
  volume_display: string | null;
  open_price: number | null;
  open_price_display: string | null;
  close_price: number | null;
  close_price_display: string | null;
  profit: number | null;
  profit_display: string | null;
  opened_at: string | null;
  opened_at_display: string | null;
  closed_at: string | null;
  closed_at_display: string | null;
  sl: number | null;
  sl_display: string | null;
  tp: number | null;
  tp_display: string | null;
  status: string | null;
  source_name: string | null;
}

interface FilterOptions {
  accounts: string[];
  symbols: string[];
  sources: string[];
  directions: string[];
}

interface HistoryFilters extends Record<string, string> {
  account: string;
  source: string;
  symbol: string;
  from_date: string;
  to_date: string;
}

const FILTER_KEYS = [
  "account",
  "source",
  "symbol",
  "from_date",
  "to_date",
] as const;

// ── Small presentational helpers ────────────────────────────────────────────────────────────

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

const selectClass =
  "h-9 min-w-0 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30";

const inputClass = selectClass;

/** A native <select> dropdown driving one filter param. Empty value clears the param. */
function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <select
        className={selectClass}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">All</option>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </label>
  );
}

/** A native date input driving one filter param. Empty value clears the param. */
function FilterDate({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <input
        type="date"
        className={inputClass}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────────────────

export function HistoryView() {
  const { filters, setFilter } = useUrlFilters<HistoryFilters>(FILTER_KEYS);

  // Filter-options drive the dropdowns (directions is empty → not a filter, D-05).
  const { data: options } = useQuery<FilterOptions>({
    queryKey: ["history-filter-options"],
    queryFn: () =>
      api("/api/v2/history/filter-options") as Promise<FilterOptions>,
  });

  const { data, isPending, isError, error, refetch, isFetching } = useQuery<
    HistoryTrade[]
  >({
    // Key derives from the URL filters → a URL change auto-refetches (keepPreviousData = no flicker).
    queryKey: ["history", filters],
    queryFn: () => {
      const params = new URLSearchParams();
      for (const key of FILTER_KEYS) {
        const v = filters[key];
        if (v) params.set(key, v);
      }
      const qs = params.toString();
      return api(`/api/v2/history${qs ? `?${qs}` : ""}`) as Promise<
        HistoryTrade[]
      >;
    },
    // No background poll (D-03) — history is snapshot-only; manual Refresh re-queries.
  });

  // ── Columns in legacy order: Time | Account | Source | Symbol | Direction | Entry | SL | TP | Lots | Status | P&L ──
  const columns: Column<HistoryTrade>[] = [
    {
      header: "Time",
      // Legacy renders the close time when present, else the open time.
      cell: (r) => r.closed_at_display ?? r.opened_at_display ?? "—",
      mono: true,
    },
    { header: "Account", cell: (r) => r.account ?? "—" },
    { header: "Source", cell: (r) => r.source_name ?? "—" },
    { header: "Symbol", cell: (r) => r.symbol ?? "—", mono: true },
    {
      header: "Direction",
      cell: (r) => <DirectionBadge direction={r.direction} />,
    },
    {
      header: "Entry",
      cell: (r) => r.open_price_display ?? "—",
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
    {
      header: "Lots",
      cell: (r) => r.volume_display ?? "—",
      align: "right",
      mono: true,
    },
    { header: "Status", cell: (r) => r.status ?? "—" },
    {
      header: "P&L",
      cell: (r) => r.profit_display ?? "—",
      align: "right",
      mono: true,
      sign: (r) => r.profit,
    },
  ];

  return (
    <div className="mx-auto max-w-6xl py-6">
      {/* Header: title + manual Refresh (D-04) */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-foreground">Trade History</h2>
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

      {/* Filter bar: 3 selects + 2 date inputs. Each edit replaces the URL param (D-05). */}
      <div className="mb-6 flex flex-wrap items-end gap-3 rounded-lg border border-border bg-card p-4">
        <FilterSelect
          label="Account"
          value={filters.account}
          options={options?.accounts ?? []}
          onChange={(v) => setFilter({ account: v })}
        />
        <FilterSelect
          label="Source"
          value={filters.source}
          options={options?.sources ?? []}
          onChange={(v) => setFilter({ source: v })}
        />
        <FilterSelect
          label="Symbol"
          value={filters.symbol}
          options={options?.symbols ?? []}
          onChange={(v) => setFilter({ symbol: v })}
        />
        <FilterDate
          label="From"
          value={filters.from_date}
          onChange={(v) => setFilter({ from_date: v })}
        />
        <FilterDate
          label="To"
          value={filters.to_date}
          onChange={(v) => setFilter({ to_date: v })}
        />
      </div>

      {/* Query states */}
      {isPending ? (
        <Loading rows={8} />
      ) : isError ? (
        <ErrorPanel error={error} onRetry={() => refetch()} />
      ) : data.length === 0 ? (
        <Empty
          title="No trades match"
          message="No closed trades match the selected filters. Try widening or clearing them."
        />
      ) : (
        <DataTable
          columns={columns}
          rows={data}
          rowKey={(r, i) => (r.ticket != null ? String(r.ticket) : i)}
        />
      )}
    </div>
  );
}
