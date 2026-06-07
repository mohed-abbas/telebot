// frontend/src/hooks/usePartialClose.ts — idempotent partial-close of a live position (PAGE-06).
//
// THE footgun this hook exists to disarm (Pitfall 3 / T-11-04): the legacy partial-close was
// percent-of-remaining, so a retried request closed a fraction of the *already-reduced* volume
// (e.g. two "close 50%" fires → 75% closed). The fix is two-fold:
//   1. D-04: send an ABSOLUTE close_volume in lots — never a percent. The body has no `percent`.
//   2. Send a stable client-generated request_id. The server replays a cached 200 for the SAME
//      id+params (broker untouched), so a PURE retry of the same amount is safe. A reused id with
//      DIFFERENT params → 409. An in-flight retry → 409. We surface 409 with a specific operator
//      message and reset nothing automatically.
//
// request_id lifecycle (the load-bearing part): held in a useRef seeded with crypto.randomUUID().
// A pure retry (same amount) MUST reuse the id to hit the cached-200 replay — so we DO NOT mint a
// new id on every submit. `regenerateRequestId()` is called by the page ONLY when the operator
// changes the intended amount, which makes the next submit a genuinely new operation.
//
// Discipline shared with the other hooks: api() only (CSRF — Pitfall 2), NO setQueryData
// (SC#1 / Pitfall 1), 401 handled globally, non-409 errors via errorMessage() (T-11-06).
//
// Server contract: POST /api/v2/positions/{account}/{ticket}/close-partial
//   Body PartialCloseIn {close_volume:float, request_id:str}
//   → {ok,success,closed_volume,closed_volume_display,error}
//   409 = id reused w/ different params OR in-flight retry. 422 = close_volume out of range.

import { useCallback, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, HttpError } from "@/lib/http";
import { errorMessage } from "@/components/state/ErrorPanel";

const CONFLICT_MESSAGE =
  "That close already ran or the amount changed — refresh and retry.";

export interface PartialCloseVars {
  account: string;
  ticket: number | string;
  /** Absolute volume to close, in lots (D-04). NEVER a percent. */
  closeVolume: number;
}

export function usePartialClose() {
  const qc = useQueryClient();

  // Stable per-operation idempotency key. Reused across pure retries (same amount) so the server
  // replays its cached 200 instead of hitting the broker a second time (Pitfall 3).
  const requestIdRef = useRef<string>(crypto.randomUUID());

  // Mint a fresh request_id. The page calls this ONLY when the operator changes the amount, so the
  // next submit is treated as a new operation rather than a retry of the previous one.
  const regenerateRequestId = useCallback(() => {
    requestIdRef.current = crypto.randomUUID();
  }, []);

  const mutation = useMutation({
    mutationFn: ({ account, ticket, closeVolume }: PartialCloseVars) =>
      api(`/api/v2/positions/${encodeURIComponent(account)}/${encodeURIComponent(String(ticket))}/close-partial`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          close_volume: closeVolume, // absolute lots (D-04) — no percent field
          request_id: requestIdRef.current,
        }),
      }),
    onSuccess: () => {
      // SC#1: re-derive remaining volume from the broker; never optimistically reduce it.
      qc.invalidateQueries({ queryKey: ["positions"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
      toast.success("Partial close confirmed");
    },
    onError: (error) => {
      // 409 = id reused w/ different params OR in-flight retry (Pitfall 3) — specific copy.
      if (error instanceof HttpError && error.status === 409) {
        toast.error(CONFLICT_MESSAGE);
        return;
      }
      toast.error(errorMessage(error));
    },
  });

  return { ...mutation, regenerateRequestId };
}
