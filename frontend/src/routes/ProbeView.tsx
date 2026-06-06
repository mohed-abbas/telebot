// frontend/src/routes/ProbeView.tsx
//
// ⚠️ THROWAWAY SCAFFOLD / DIAGNOSTIC — DELETED IN PHASE 10. ⚠️
// This is NOT a real page. It exists ONLY to prove SC#5 (SPA-05) — the headline structural fix of
// the whole React rewrite — BEFORE any real page is built. Phase 10 lands the first real Overview
// page here and removes this file.
//
// SC#5 PROOF (the whole point):
//   - SERVER state: useQuery({ queryKey:["trading-status"], refetchInterval: 3000 }) polls the
//     lightest shipped read endpoint (api/meta.py GET /trading-status — in-memory flag, no DB/MT5).
//     Each refetch re-renders the status + the mono "last-updated" timestamp.
//   - FORM state: a SEPARATE `const [draft, setDraft] = useState("")` bound to an open <input>.
//   These two are STRUCTURALLY ISOLATED. A background refetch re-renders the data branch but NEVER
//   touches `draft`. The input value is NOT sourced from the query cache. This split is exactly
//   what killed the HTMX refresh-race bug class (open inputs getting clobbered on refresh).
//
// UI-SPEC §Color: the status dot uses STATUS colors (green LIVE / red disabled), NEVER the cyan
// accent. Mono readouts use --font-mono.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/http";
import { cn } from "@/lib/utils";

interface TradingStatus {
  paused: boolean;
  status: "running" | "paused";
}

function formatTime(epochMs: number): string {
  if (!epochMs) return "—";
  return new Date(epochMs).toLocaleTimeString();
}

export function ProbeView() {
  // SERVER state — polled every 3s. dataUpdatedAt ticks on each successful refetch.
  const { data, dataUpdatedAt, isError } = useQuery<TradingStatus>({
    queryKey: ["trading-status"],
    queryFn: () => api("/api/v2/trading-status") as Promise<TradingStatus>,
    refetchInterval: 3000,
  });

  // FORM state — strictly local, structurally isolated from the query above. A refetch must
  // NEVER reset this. Do NOT initialize it from `data`.
  const [draft, setDraft] = useState("");

  const live = data ? !data.paused : false;

  return (
    <div className="mx-auto max-w-xl py-8">
      {/* Throwaway scaffold banner — make it obvious this is diagnostic, not a real page. */}
      <p className="mb-4 rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
        Diagnostic scaffold — removed in Phase 10. Proves the server-state / form-state split
        (SC#5): the input below survives background refetches.
      </p>

      <div className="rounded-lg border border-border bg-card p-6">
        <h2 className="text-lg font-semibold text-card-foreground">Connection probe</h2>

        {/* SERVER-state readout — re-renders every 3s. */}
        <div className="mt-4 flex items-center gap-2">
          <span
            aria-hidden="true"
            className={cn(
              "inline-block size-2 rounded-full",
              isError ? "bg-destructive" : live ? "bg-green-500" : "bg-red-500",
            )}
          />
          <span className="font-mono text-sm text-muted-foreground">
            status: {isError ? "error" : (data?.status ?? "…")}
          </span>
        </div>
        <p className="mt-1 font-mono text-xs text-muted-foreground">
          last-updated: {formatTime(dataUpdatedAt)}
        </p>

        {/* FORM-state input — local useState, isolated from the poll above. */}
        <div className="mt-6 flex flex-col gap-2">
          <label htmlFor="probe-draft" className="text-sm text-card-foreground">
            Type here, watch it survive ≥2 refetches
          </label>
          <input
            id="probe-draft"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="type here, watch it survive ≥2 refetches"
            className="rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
        </div>
      </div>
    </div>
  );
}
