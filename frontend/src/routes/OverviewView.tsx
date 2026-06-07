// frontend/src/routes/OverviewView.tsx — PAGE-05, the live-money landing surface.
//
// The operator's default page (/app index resolves here). It is the capstone of Wave 3 — it does
// NOT re-implement the positions table or the kill switch; it COMPOSES the already-shipped pieces:
//   - a red TRADING PAUSED banner driven by GET /api/v2/trading-status (escalates ABOVE the
//     open-positions focal point — UI-SPEC §Visual Hierarchy),
//   - per-account cards from GET /api/v2/overview (overview_cards.html parity STRUCTURE),
//   - the open-positions table by RENDERING <PositionsView/> (11-03) — which owns its own
//     ["positions"] 3s poll AND keeps its Edit modal + drilldown in LOCAL state portaled outside
//     the polling subtree, so SC#3 (an open modal/drilldown survives ≥2 background refetch cycles)
//     is inherited for free — no state is shared with this page,
//   - a pending-stages card (top-5) from GET /api/v2/stages (RESEARCH Open Question 2 — reuse the
//     shipped StagedView contract; NO new endpoint), and
//   - an Emergency Kill Switch entry (destructive) that NAVIGATES to /emergency (KillSwitchView,
//     11-05) — the two-step confirm lives there.
//
// Polling (D-07): one useQuery per source, each refetchInterval 3000. Background pause is free via
// the inherited refetchIntervalInBackground:false (queryClient.ts). The ["positions"] poll is owned
// by the embedded <PositionsView/>; ["trading-status"] is shared with KillSwitchView so the banner
// and that page re-derive together.
//
// Pitfall-5 discipline: every money value renders the server `*_display` twin ONLY. The ONE allowed
// client calc is the margin-used RATIO (margin / balance × 100) — a dimensionless percentage off two
// bare numerics, the same Pitfall-5-exempt category as win_rate/elapsed (NOT a money re-format).
// Counts (open_trades, daily_trades) and the risk percentage are bare ints/floats, rendered raw.

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import type { ReactNode } from "react";

import { DirectionBadge } from "@/components/data/DirectionBadge";
import { Empty } from "@/components/state/Empty";
import { ErrorPanel } from "@/components/state/ErrorPanel";
import { Loading } from "@/components/state/Loading";
import { Button } from "@/components/ui/button";
import { PositionsView } from "@/routes/PositionsView";
import { api } from "@/lib/http";
import { cn } from "@/lib/utils";

// ── API types ───────────────────────────────────────────────────────────────────────────────────

// AccountOverview mirrors api/schemas.py:57 — money fields carry `_display` twins; counts/percent
// are bare. (open_trades/daily_trades/risk_percent/daily_limit_pct are NOT money — rendered raw.)
interface AccountOverview {
  name: string;
  connected: boolean;
  enabled: boolean;
  balance: number;
  balance_display: string;
  equity: number;
  equity_display: string;
  margin: number;
  margin_display: string;
  free_margin: number;
  free_margin_display: string;
  open_trades: number;
  total_profit: number;
  total_profit_display: string;
  daily_trades: number;
  daily_messages: number;
  max_daily_trades: number;
  daily_limit_pct: number;
  risk_percent: number;
  max_lot: number;
}

interface OverviewMeta {
  trading_paused: boolean;
  open_positions: number;
  accounts: AccountOverview[];
}

interface TradingStatus {
  paused: boolean;
  status: "paused" | "running";
}

// Stages contract (reused from StagedView / GET /api/v2/stages — RESEARCH Open Question 2). Only the
// `active` list feeds the top-5 pending card here; `resolved` is ignored on Overview.
interface ActiveStage {
  account_name: string;
  symbol: string;
  direction: string;
  filled: number;
  total: number;
  band_low_display: string | null;
  band_high_display: string | null;
  current_price_display: string | null;
}

interface StagesPayload {
  active: ActiveStage[];
  resolved: unknown[];
}

const PAGE_TITLE = "Overview";

// ── Small presentational helpers ──────────────────────────────────────────────────────────────

/** A label/value row inside an account card. */
function CardRow({
  label,
  children,
  tone,
}: {
  label: string;
  children: ReactNode;
  tone?: "green" | "red" | "yellow";
}) {
  const toneClass =
    tone === "green"
      ? "text-green-400"
      : tone === "red"
        ? "text-red-400"
        : tone === "yellow"
          ? "text-yellow-400"
          : "text-card-foreground";
  return (
    <>
      <div className="text-muted-foreground">{label}</div>
      <div className={cn("text-right font-mono font-semibold", toneClass)}>
        {children}
      </div>
    </>
  );
}

/** One per-account card (overview_cards.html parity STRUCTURE). */
function AccountCard({ a }: { a: AccountOverview }) {
  // daily-limit threshold coloring (parity: yellow≥80%, red≥100%).
  const dailyTone: "green" | "red" | "yellow" =
    a.daily_limit_pct >= 100 ? "red" : a.daily_limit_pct >= 80 ? "yellow" : "green";

  // Margin-used RATIO — a dimensionless percentage off two bare numerics (Pitfall-5-exempt, same as
  // win_rate/elapsed). NEVER re-formats a money string. Guard divide-by-zero.
  const marginPct =
    a.balance > 0 ? Math.min((a.margin / a.balance) * 100, 100) : 0;
  const barColor =
    marginPct > 50 ? "bg-red-500" : marginPct > 30 ? "bg-yellow-500" : "bg-primary";

  return (
    <div className="rounded-lg border border-border bg-card p-5 text-card-foreground shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-lg font-semibold">{a.name}</h3>
        <span
          className={cn(
            "rounded-md border border-border px-2 py-0.5 text-xs font-medium",
            a.connected ? "text-green-400" : "text-red-400",
          )}
        >
          {a.connected ? "Connected" : "Offline"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-y-2 text-sm">
        {/* Money fields → server `*_display` twin ONLY (Pitfall 5). */}
        <CardRow label="Balance">{a.balance_display}</CardRow>
        <CardRow label="Equity">{a.equity_display}</CardRow>
        <CardRow
          label="Open P&L"
          tone={a.total_profit >= 0 ? "green" : "red"}
        >
          {a.total_profit_display}
        </CardRow>
        <CardRow label="Open Trades">{a.open_trades}</CardRow>
        <CardRow label="Daily Trades" tone={dailyTone}>
          {a.daily_trades} / {a.max_daily_trades}
        </CardRow>
        {/* risk_percent is a bare percentage (not money) — rendered raw. */}
        <CardRow label="Risk">{a.risk_percent}%</CardRow>
      </div>

      {/* Margin-used bar (ratio, Pitfall-5-exempt). */}
      {a.balance > 0 ? (
        <div className="mt-3">
          <div className="mb-1 flex justify-between text-xs text-muted-foreground">
            <span>Margin Used</span>
            <span className="font-mono">{marginPct.toFixed(1)}%</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-muted">
            <div
              className={cn("h-1.5 rounded-full", barColor)}
              style={{ width: `${marginPct}%` }}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** One pending-stage card (top-5). Reuses the StagedView active-stage layout, condensed. */
function PendingStageCard({ s }: { s: ActiveStage }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold text-card-foreground">
          {s.symbol}
        </span>
        <DirectionBadge direction={s.direction} />
        <span className="text-xs text-muted-foreground">{s.account_name}</span>
      </div>
      <div className="grid grid-cols-3 gap-3 text-sm">
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted-foreground">Stages</span>
          <span className="font-mono text-card-foreground">
            {s.filled}/{s.total}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted-foreground">Target Band</span>
          <span className="font-mono text-card-foreground">
            {s.band_low_display ?? "—"} – {s.band_high_display ?? "—"}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted-foreground">Current Price</span>
          <span className="font-mono text-card-foreground">
            {s.current_price_display ?? "—"}
          </span>
        </div>
      </div>
    </div>
  );
}

function SectionHeading({ children }: { children: ReactNode }) {
  return (
    <h3 className="mb-3 text-sm font-medium text-muted-foreground">{children}</h3>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────────────────────

export function OverviewView() {
  // One useQuery per source. Each polls at 3s (D-07); the inherited refetchIntervalInBackground:false
  // pauses them on a hidden tab for free. The ["positions"] poll is owned by the embedded
  // <PositionsView/> below — NOT duplicated here.
  const overview = useQuery<OverviewMeta>({
    queryKey: ["overview"],
    queryFn: () => api("/api/v2/overview") as Promise<OverviewMeta>,
    refetchInterval: 3000,
  });

  // Shared key with KillSwitchView — banner + that page re-derive together on a paused change.
  const tradingStatus = useQuery<TradingStatus>({
    queryKey: ["trading-status"],
    queryFn: () => api("/api/v2/trading-status") as Promise<TradingStatus>,
    refetchInterval: 3000,
    // WR-01: keep the last-known status across a transient poll failure so a single failed
    // refetch never flips a real PAUSED state to "running" (undefined → paused:false).
    placeholderData: keepPreviousData,
  });

  // Pending stages (top-5) — reuse the shipped GET /api/v2/stages contract (Open Question 2).
  const stages = useQuery<StagesPayload>({
    queryKey: ["stages"],
    queryFn: () => api("/api/v2/stages") as Promise<StagesPayload>,
    refetchInterval: 3000,
  });

  const paused = tradingStatus.data?.paused === true;
  // WR-01: fail safe — an unknown status (cold-start error, no cached value) must NOT render as
  // "running". Surface a degraded indicator so the operator is never silently shown a not-paused
  // layout while the pause state is genuinely unknown.
  const statusUnknown = tradingStatus.data == null && tradingStatus.isError;

  return (
    <div className="mx-auto max-w-6xl py-6">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-foreground">{PAGE_TITLE}</h2>
        {/* Emergency Kill Switch entry — the destructive entry; the two-step confirm lives at
            /emergency (KillSwitchView, 11-05). */}
        <Button asChild variant="destructive" size="default" className="min-h-10">
          <Link to="/emergency">Emergency Kill Switch</Link>
        </Button>
      </div>

      {/* Per-account cards (overview_cards.html parity STRUCTURE). */}
      <section className="mb-8">
        <SectionHeading>Accounts</SectionHeading>
        {overview.isPending ? (
          <Loading rows={2} />
        ) : overview.isError ? (
          <ErrorPanel
            error={overview.error}
            message="Something went wrong loading the account overview."
            onRetry={() => overview.refetch()}
          />
        ) : overview.data.accounts.length === 0 ? (
          <Empty
            title="No accounts configured."
            message="Edit accounts.json to add trading accounts."
          />
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {overview.data.accounts.map((a) => (
              <AccountCard key={a.name} a={a} />
            ))}
          </div>
        )}
      </section>

      {/* TRADING PAUSED banner — red --destructive, ABOVE the open-positions focal point
          (UI-SPEC §Visual Hierarchy: it escalates above the focal point when paused). */}
      {paused ? (
        <div
          role="alert"
          className="mb-6 rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-center"
        >
          <p className="text-sm font-bold tracking-wide text-destructive">
            TRADING PAUSED
          </p>
          <p className="mt-1 text-sm text-destructive">
            Kill switch active — no signals will be processed
          </p>
        </div>
      ) : statusUnknown ? (
        // WR-01: degraded — do NOT imply trading is live when the status fetch failed.
        <div
          role="alert"
          className="mb-6 rounded-lg border border-border bg-muted/40 p-4 text-center"
        >
          <p className="text-sm font-semibold tracking-wide text-muted-foreground">
            TRADING STATUS UNAVAILABLE
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Could not reach the server — pause state is unknown
          </p>
        </div>
      ) : null}

      {/* Open Positions — RENDER the shipped PositionsView (11-03). It owns its own ["positions"]
          3s poll and keeps its Edit modal + drilldown in LOCAL state portaled outside the polling
          subtree, so SC#3 is inherited for free; no state is shared with this page. */}
      <section className="mb-8">
        <SectionHeading>Open Positions</SectionHeading>
        <PositionsView />
      </section>

      {/* Pending Stages — top-5 from GET /api/v2/stages (Open Question 2, no new endpoint). */}
      <section>
        <SectionHeading>Pending Stages</SectionHeading>
        {stages.isPending ? (
          <Loading rows={2} />
        ) : stages.isError ? (
          <ErrorPanel
            error={stages.error}
            message="Something went wrong loading pending stages."
            onRetry={() => stages.refetch()}
          />
        ) : stages.data.active.length === 0 ? (
          <Empty
            title="No pending stages"
            message="Staged entries awaiting their trigger band will appear here."
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {stages.data.active.slice(0, 5).map((s, i) => (
              <PendingStageCard key={`${s.account_name}-${s.symbol}-${i}`} s={s} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
