// frontend/src/lib/entryTps.test.ts — per-entry TP padding/trimming for the Settings form.

import { describe, expect, it } from "vitest";
import { DEFAULT_ENTRY_TP, entryTps, withEntryTp } from "@/lib/entryTps";

describe("entryTps", () => {
  it("pads a canonical (trimmed) map with the default TP up to the entry count", () => {
    expect(entryTps([2, 2, 3], 5)).toEqual([2, 2, 3, DEFAULT_ENTRY_TP, DEFAULT_ENTRY_TP]);
  });

  it("an empty map means the default TP on every entry", () => {
    expect(entryTps([], 3)).toEqual([2, 2, 2]);
    expect(entryTps(undefined, 2)).toEqual([2, 2]);
  });

  it("trims selections beyond the entry count", () => {
    expect(entryTps([2, 2, 2, 3, 3], 3)).toEqual([2, 2, 2]);
  });

  it("clamps the entry count to 1..10 while the field is being typed", () => {
    expect(entryTps([3], Number.NaN)).toEqual([3]);
    expect(entryTps([], 0)).toEqual([2]);
    expect(entryTps([], 50)).toHaveLength(10);
  });
});

describe("entryTps — server default", () => {
  it("pads with the default TP the server sends", () => {
    expect(entryTps([1], 3, 3)).toEqual([1, 3, 3]);
  });
});

describe("withEntryTp", () => {
  it("keeps choices for entries beyond the current count", () => {
    // 5 entries mapped, form shows 3 (count lowered): editing entry 1 keeps entries 4–5.
    expect(withEntryTp([2, 2, 2, 3, 3], 0, 1)).toEqual([1, 2, 2, 3, 3]);
  });

  it("grows the list with the default when the entry is past its end", () => {
    expect(withEntryTp([], 2, 3)).toEqual([2, 2, 3]);
    expect(withEntryTp([1], 2, 4, 3)).toEqual([1, 3, 4]);
  });
});
