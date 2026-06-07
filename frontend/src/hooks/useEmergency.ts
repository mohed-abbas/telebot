// frontend/src/hooks/useEmergency.ts — the kill-switch: close-all + resume (PAGE-07).
//
// Same money-safe discipline as the positions hooks: api() only (CSRF echoed — Pitfall 2),
// NO setQueryData (SC#1 / Pitfall 1 — the UI must not show "all flat / paused" until the server
// confirms it actually closed everything), 401 handled globally, errors via errorMessage()
// (T-11-06). Both onSuccess paths invalidate the three queries the kill-switch touches so the
// overview banner, trading-status pill, and positions table all re-derive from the server.
//
// Server contracts (both no body):
//   POST /api/v2/emergency/close  → EmergencyResult {results, ok}
//   POST /api/v2/emergency/resume → {status:"resumed"}

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/http";
import { errorMessage } from "@/components/state/ErrorPanel";

// The three server-state queries a kill-switch action invalidates: the overview banner, the
// trading-status pill, and the positions table.
const EMERGENCY_KEYS = [["overview"], ["trading-status"], ["positions"]] as const;

export function useEmergency() {
  const qc = useQueryClient();

  const invalidateAll = () => {
    for (const queryKey of EMERGENCY_KEYS) {
      qc.invalidateQueries({ queryKey: [...queryKey] });
    }
  };

  const close = useMutation({
    mutationFn: () => api("/api/v2/emergency/close", { method: "POST" }),
    onSuccess: () => {
      invalidateAll();
      toast.success("All positions closed, trading paused");
    },
    onError: (error) => {
      toast.error(errorMessage(error));
    },
  });

  const resume = useMutation({
    mutationFn: () => api("/api/v2/emergency/resume", { method: "POST" }),
    onSuccess: () => {
      invalidateAll();
      toast.success("Trading resumed");
    },
    onError: (error) => {
      toast.error(errorMessage(error));
    },
  });

  return { close, resume };
}
