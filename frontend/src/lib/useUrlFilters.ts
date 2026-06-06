// frontend/src/lib/useUrlFilters.ts — the single URL-filter-sync helper (D-02/D-05).
//
// The URL search string is the source of truth for filter state (bookmarkable, back/forward
// works, deep-linkable). Built on react-router 7 `useSearchParams`. Shared by:
//   - Analytics (range, source) — D-02
//   - History (account, source, symbol, from_date, to_date) — D-05
//
// `setFilter` writes a patch back to the URL. By default it REPLACES the history entry
// (filter edits should not pile up back-stack entries); pass `{ push: true }` for explicit
// navigation that SHOULD push (e.g. clicking a by-source row → ?source=<name>).
//
// The query key derives directly from the returned `filters` object, so a URL change
// auto-refetches (inherited keepPreviousData prevents flicker on the transition).

import { useSearchParams } from "react-router-dom";

export function useUrlFilters<T extends Record<string, string>>(
  keys: readonly (keyof T & string)[],
) {
  const [params, setParams] = useSearchParams();
  const filters = Object.fromEntries(
    keys.map((k) => [k, params.get(k) ?? ""]),
  ) as T;
  const setFilter = (patch: Partial<T>, opts?: { push?: boolean }) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v as string);
      else next.delete(k);
    }
    // replace on filter edit; push on explicit navigation (row-click).
    setParams(next, { replace: !opts?.push });
  };
  return { filters, setFilter };
}
