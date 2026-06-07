// frontend/src/hooks/useLevels.ts — modify SL/TP on a live position (PAGE-06).
//
// Same money-safe discipline as useClose: api() only (CSRF echoed — Pitfall 2), NO setQueryData
// (SC#1 / Pitfall 1 — never optimistically move the SL/TP before the broker confirms), 401 handled
// globally, errors surfaced via errorMessage() into a sonner toast (T-11-06).
//
// Server contract: POST /api/v2/positions/{account}/{ticket}/levels
//   Body CloseLevelsIn {sl?:float, tp?:float} — BOTH optional; an omitted/null field means "keep".
//   No-op (no changed fields) → {ok:true, changed:{}}. 422 if sl/tp ≤ 0.
// We send ONLY the fields the operator actually changed (undefined fields are dropped from the body).

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/http";
import { errorMessage } from "@/components/state/ErrorPanel";

export interface LevelsVars {
  account: string;
  ticket: number | string;
  /** New stop-loss. Omit (undefined) to keep the existing SL. */
  sl?: number;
  /** New take-profit. Omit (undefined) to keep the existing TP. */
  tp?: number;
}

export function useLevels() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ account, ticket, sl, tp }: LevelsVars) => {
      // CloseLevelsIn: include only the changed fields; an undefined field is "keep".
      const body: { sl?: number; tp?: number } = {};
      if (sl !== undefined) body.sl = sl;
      if (tp !== undefined) body.tp = tp;

      return api(`/api/v2/positions/${account}/${ticket}/levels`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => {
      // SC#1: re-fetch from the broker; never optimistically write the new levels.
      qc.invalidateQueries({ queryKey: ["positions"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
      toast.success("Levels updated");
    },
    onError: (error) => {
      toast.error(errorMessage(error));
    },
  });
}
