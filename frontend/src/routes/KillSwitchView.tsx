// frontend/src/routes/KillSwitchView.tsx — PAGE-07, the Emergency Kill Switch.
//
// The most consequential destructive action in the app: CONFIRM CLOSE ALL closes ALL positions,
// cancels ALL pending orders, and PAUSES trading. Parity ref: templates/partials/
// kill_switch_preview.html (red card, positions/orders counts, warning copy, CONFIRM CLOSE ALL,
// hide-confirm-when-count==0). Built as StagedView.tsx (read the preview via useQuery) +
// LoginView.tsx:47-70 (the submit-disabled-while-pending discipline on the confirm).
//
// Two server reads, both via useQuery:
//   GET /api/v2/emergency/preview → EmergencyPreview {open_positions, pending_orders, accounts[]}
//   GET /api/v2/trading-status    → TradingStatus {paused, status}  (drives Resume visibility)
//
// Mutations come from useEmergency() (Wave 1, 11-02): close + resume. Money-safe discipline is
// baked into the hook — api() only (CSRF echoed, Pitfall 2), NO setQueryData (SC#1 / Pitfall 1:
// the UI must not show "all flat / paused" until the server confirms it), both onSuccess paths
// invalidate overview/trading-status/positions so this page re-derives from the server. So there
// is NO optimistic local state here — the preview counts and the paused pill update only after
// the server confirms via invalidateQueries.
//
// Threat mitigations (plan §threat_model):
//   T-11-17 (tampering / accidental double-fire) — the two-step preview→confirm IS the guard: a
//     deliberate second action (CONFIRM CLOSE ALL) after the preview, disabled-while-pending so a
//     double-click cannot re-fire; no optimistic state (server-confirmed only).
//   T-11-18 (spoofing) — both mutations go through useEmergency → api() → X-CSRF-Token.
//   T-11-19 (operator-error empty close) — the confirm button is HIDDEN when both counts == 0, so
//     there is no empty/accidental close-all.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ErrorPanel } from "@/components/state/ErrorPanel";
import { Loading } from "@/components/state/Loading";
import { Button } from "@/components/ui/button";
import { useEmergency } from "@/hooks/useEmergency";
import { api } from "@/lib/http";

// ── API types (RESEARCH §Overview/status + §Live-money mutations) ───────────────────────────────

interface EmergencyPreview {
  open_positions: number;
  pending_orders: number;
  accounts: string[];
}

interface TradingStatus {
  paused: boolean;
  status: "paused" | "running";
}

// ── Small presentational helper: a labelled count row inside the red card ───────────────────────

function CountRow({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-card-foreground">{value}</span>
    </div>
  );
}

// ── Page ────────────────────────────────────────────────────────────────────────────────────────

export function KillSwitchView() {
  const { close, resume } = useEmergency();

  // Step 1 read: the preview (counts that WILL be closed). StagedView Loading/ErrorPanel branch
  // order — isPending → Loading, isError → inline ErrorPanel, else render.
  const preview = useQuery<EmergencyPreview>({
    queryKey: ["emergency-preview"],
    queryFn: () => api("/api/v2/emergency/preview") as Promise<EmergencyPreview>,
  });

  // The pause state — drives the Resume button visibility (shown ONLY while paused).
  const tradingStatus = useQuery<TradingStatus>({
    queryKey: ["trading-status"],
    queryFn: () => api("/api/v2/trading-status") as Promise<TradingStatus>,
  });

  // The two-step guard: the operator must explicitly arm the confirm (T-11-17). "Keep trading
  // active" disarms back to the preview without closing anything (the non-destructive escape).
  const [armed, setArmed] = useState(false);

  const title = (
    <h2 className="mb-6 text-xl font-semibold text-destructive">
      Emergency Kill Switch
    </h2>
  );

  if (preview.isPending) {
    return (
      <div className="mx-auto max-w-md py-6">
        {title}
        <Loading rows={3} />
      </div>
    );
  }

  if (preview.isError) {
    return (
      <div className="mx-auto max-w-md py-6">
        {title}
        <ErrorPanel error={preview.error} onRetry={() => preview.refetch()} />
      </div>
    );
  }

  const { open_positions, pending_orders } = preview.data;
  // T-11-19: nothing to close → no confirm action at all (parity with the legacy
  // `{% if position_count > 0 or order_count > 0 %}` guard).
  const nothingToClose = open_positions === 0 && pending_orders === 0;
  const paused = tradingStatus.data?.paused === true;

  return (
    <div className="mx-auto max-w-md py-6">
      {title}

      {/* Red --destructive card (kill_switch_preview.html parity STRUCTURE). */}
      <div className="rounded-lg border border-destructive/50 bg-card p-6">
        <div className="mb-6 flex flex-col gap-3">
          <CountRow label="Open Positions" value={open_positions} />
          <CountRow label="Pending Orders" value={pending_orders} />
        </div>

        <p className="mb-4 text-sm text-muted-foreground">
          This will close ALL positions, cancel ALL pending orders, and pause
          trading. You must manually re-enable trading afterwards.
        </p>

        {nothingToClose ? (
          <p className="text-center text-sm text-muted-foreground">
            No open positions or pending orders.
          </p>
        ) : armed ? (
          // Armed: the deliberate second action. Disabled-while-pending (T-11-17) so a
          // double-click cannot re-fire; label morphs to "Closing all…".
          <div className="flex flex-col gap-2">
            <Button
              variant="destructive"
              size="default"
              className="w-full"
              disabled={close.isPending}
              onClick={() => close.mutate()}
            >
              {close.isPending ? "Closing all…" : "CONFIRM CLOSE ALL"}
            </Button>
            <Button
              variant="ghost"
              size="default"
              className="w-full"
              disabled={close.isPending}
              onClick={() => setArmed(false)}
            >
              Keep trading active
            </Button>
          </div>
        ) : (
          // Step 1 → step 2: arm the confirm. This is the entry button into the two-step flow.
          <Button
            variant="destructive"
            size="default"
            className="w-full"
            onClick={() => setArmed(true)}
          >
            Emergency Kill Switch
          </Button>
        )}
      </div>

      {/* Resume Trading — cyan variant="default", shown ONLY while paused (T-11 §Resume). */}
      {paused && (
        <Button
          variant="default"
          size="default"
          className="mt-4 w-full"
          disabled={resume.isPending}
          onClick={() => resume.mutate()}
        >
          {resume.isPending ? "Resuming…" : "Resume Trading"}
        </Button>
      )}
    </div>
  );
}
