// frontend/src/lib/queryClient.ts — the shared QueryClient + the single global 401 handler.
//
// D-06 / SPA-04: ONE `onAuthError` wired on BOTH the QueryCache and the MutationCache `onError`,
// so any 401 from any query or mutation triggers exactly one hard nav to the login view. The hard
// nav (`window.location.assign`) clears in-memory state. Loop-break (T-09-08): skip the redirect
// when we are already on `/app/login`, so a 401 from the login view itself can't bounce forever.
//
// D-09: the inherited polling defaults every Phase 10/11 page gets for free —
//   placeholderData: keepPreviousData     → no flicker on refetch (keeps last data while fetching)
//   refetchIntervalInBackground: false    → polling pauses on a hidden tab
// Server state lives here (TanStack Query); form/UI state stays local React state — never mixed.

import {
  MutationCache,
  QueryCache,
  QueryClient,
  keepPreviousData,
} from "@tanstack/react-query";

import { HttpError } from "./http";

const LOGIN_PATH = "/app/login";

/**
 * Single global auth-error handler. On a 401, hard-navigate to the login view
 * exactly once — unless we are already on the login view (the loop-break).
 */
const onAuthError = (error: unknown): void => {
  if (error instanceof HttpError && error.status === 401) {
    if (!window.location.pathname.startsWith(LOGIN_PATH)) {
      window.location.assign(LOGIN_PATH);
    }
  }
};

export const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: onAuthError }),
  mutationCache: new MutationCache({ onError: onAuthError }),
  defaultOptions: {
    queries: {
      placeholderData: keepPreviousData, // D-09: no flicker on refetch
      refetchIntervalInBackground: false, // D-09: pause polling on a hidden tab
      staleTime: 1000, // same-origin internal tool: brief freshness window
      retry: false, // internal tool: surface failures (incl. 401) immediately, no retry storm
    },
  },
});
