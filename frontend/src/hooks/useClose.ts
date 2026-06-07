// frontend/src/hooks/useClose.ts — the close-a-position mutation (PAGE-06).
//
// Money-safe discipline (the whole reason these hooks exist):
//   - SC#1 / Pitfall 1: NEVER setQueryData. A position must never render closed while it is
//     still live at the broker. UI state changes ONLY after a server-confirmed 2xx, via
//     invalidateQueries in onSuccess — the next refetch reflects the real broker state.
//   - Pitfall 2 / T-11-03: every call goes through api() (frontend/src/lib/http.ts), which
//     echoes the X-CSRF-Token double-submit header on POST. Raw fetch() would 403. Never fetch().
//   - 401 is FREE: the single global onAuthError on the MutationCache (queryClient.ts) hard-navs
//     to /app/login. Never handle 401 per-hook.
//   - T-11-06: error copy comes only from errorMessage() (the typed {error:{message}} envelope) —
//     no raw exception/stack ever reaches the viewport.
//
// Server contract: POST /api/v2/positions/{account}/{ticket}/close → MutationResult {ok,success,error}. No body.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/http";
import { errorMessage } from "@/components/state/ErrorPanel";

export interface ClosePositionVars {
  account: string;
  ticket: number | string;
}

/**
 * Close a single live position. No request body. On a confirmed 2xx we invalidate the
 * positions + overview queries (never setQueryData) so the UI re-derives from the broker.
 */
export function useClose() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ account, ticket }: ClosePositionVars) =>
      api(`/api/v2/positions/${encodeURIComponent(account)}/${encodeURIComponent(String(ticket))}/close`, { method: "POST" }),
    onSuccess: () => {
      // SC#1: server-confirmed only — re-fetch positions + overview, no optimistic write.
      qc.invalidateQueries({ queryKey: ["positions"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
      toast.success("Position closed");
    },
    onError: (error) => {
      toast.error(errorMessage(error));
    },
  });
}
