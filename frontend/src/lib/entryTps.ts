// frontend/src/lib/entryTps.ts — per-entry take-profit list for the Settings form.
//
// The server stores stage_tp_map canonically: trailing entries on the default TP are dropped,
// so "TP2 everywhere" is []. The form always shows one selector per entry, so it pads the stored
// list with the default TP up to the entry count (and trims it when the count goes down).

/** The provider TP an entry uses when the account sets none (the parser's default target). */
export const DEFAULT_ENTRY_TP = 2;

/** One TP per entry for `entries` entries (clamped to 1..10): the stored map, padded with the default. */
export function entryTps(map: readonly number[] | undefined, entries: number): number[] {
  const n = Number.isFinite(entries) ? Math.min(Math.max(Math.trunc(entries), 1), 10) : 1;
  return Array.from({ length: n }, (_, i) => map?.[i] ?? DEFAULT_ENTRY_TP);
}
