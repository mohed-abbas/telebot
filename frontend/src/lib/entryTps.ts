// frontend/src/lib/entryTps.ts — per-entry take-profit list for the Settings form.
//
// The server stores stage_tp_map canonically: trailing entries on the default TP are dropped,
// so "TP2 everywhere" is []. The form always shows one selector per entry, so it pads the stored
// list with the default TP up to the entry count (and trims it when the count goes down).

/** Fallback for the TP an unmapped entry uses, when the server does not send default_entry_tp. */
export const DEFAULT_ENTRY_TP = 2;

/** One TP per entry for `entries` entries (clamped to 1..10): the stored map, padded with the default. */
export function entryTps(
  map: readonly number[] | undefined,
  entries: number,
  defaultTp: number = DEFAULT_ENTRY_TP,
): number[] {
  const n = Number.isFinite(entries) ? Math.min(Math.max(Math.trunc(entries), 1), 10) : 1;
  return Array.from({ length: n }, (_, i) => map?.[i] ?? defaultTp);
}

/**
 * Set entry `index`'s TP without dropping choices for entries beyond the current count, so
 * lowering Maximum entries (or clearing it while typing) and raising it again keeps them.
 */
export function withEntryTp(
  map: readonly number[],
  index: number,
  tp: number,
  defaultTp: number = DEFAULT_ENTRY_TP,
): number[] {
  const next = Array.from({ length: Math.max(map.length, index + 1) }, (_, i) => map[i] ?? defaultTp);
  next[index] = tp;
  return next;
}
