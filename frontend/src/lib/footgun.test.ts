// frontend/src/lib/footgun.test.ts — Pitfall-6 regression unit (D-07 / SUX-02).
//
// The whole point of this unit: prove the footgun calc is MODE-AWARE.
//   percent mode   → exposure compounds → multiply risk_value × max_stages.
//   fixed_lot mode → risk_value is the TOTAL across stages → must NOT multiply
//                    (operator-confirmed 2026-05-01; trade_manager.py:108-117).
// A single un-branched `risk_value * max_stages` is the Pitfall-6 bug — these
// assertions fail if someone re-introduces it.

import { describe, expect, it } from "vitest";
import { footgun } from "@/lib/footgun";

describe("footgun (mode-aware compounded-exposure copy)", () => {
  it("percent mode multiplies risk_value × max_stages (2 × 4 = 8%)", () => {
    const s = footgun("percent", 2, 4);
    // compounded total appears
    expect(s).toContain("8");
    // exact UI-SPEC copy contract
    expect(s).toBe("4 entries at 2% risks up to 8% per signal.");
  });

  it("percent mode compounds for other values (1.5 × 3 = 4.5%)", () => {
    const s = footgun("percent", 1.5, 3);
    expect(s).toBe("3 entries at 1.5% risks up to 4.5% per signal.");
  });

  it("fixed_lot mode does NOT multiply (Pitfall 6: 0.4, 4 → no 1.6)", () => {
    const s = footgun("fixed_lot", 0.4, 4);
    // the operator's risk_value IS the total — both bare numerics present
    expect(s).toContain("0.4");
    expect(s).toContain("4");
    // the compounded number must NOT appear — multiplying would show 1.6
    expect(s).not.toContain("1.6");
    // exact UI-SPEC copy contract
    expect(s).toBe(
      "This sizes up to 0.4 total lots per signal across 4 entries.",
    );
  });

  it("fixed_lot mode never displays a multiplied lot total (0.5, 3 → no 1.5)", () => {
    const s = footgun("fixed_lot", 0.5, 3);
    expect(s).not.toContain("1.5");
    expect(s).toBe(
      "This sizes up to 0.5 total lots per signal across 3 entries.",
    );
  });
});
