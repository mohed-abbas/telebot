// frontend/src/lib/settingsSchema.test.ts — SUX-03 cap-mirror unit.
//
// Proves the client zod schema mirrors the AUTHORITATIVE server caps from
// dashboard.validate_settings_form (zod is UX-only defense-in-depth; the server re-validates
// on confirm). Caps DERIVED — not invented (RESEARCH §Settings Caps table):
//   risk_value (percent)   : > 0 AND <= 5.0
//   risk_value (fixed_lot) : > 0 AND <= max_lot_size  (per-account, passed in at runtime)
//   max_stages             : int 1..10
//   default_sl_pips        : int 1..500
//   max_daily_trades       : int 1..100
//   max_open_trades        : READ-ONLY — NOT in the form, NO cap.

import { describe, expect, it } from "vitest";
import { makeSettingsSchema } from "@/lib/settingsSchema";

// A valid baseline the per-test overrides mutate one field at a time.
const base = {
  risk_mode: "percent" as const,
  risk_value: 2.0,
  max_stages: 4,
  default_sl_pips: 50,
  max_daily_trades: 10,
};

describe("makeSettingsSchema — mode-aware risk_value caps", () => {
  it("percent mode rejects risk_value > 5.0 (6.0)", () => {
    const r = makeSettingsSchema(0.5).safeParse({
      ...base,
      risk_mode: "percent",
      risk_value: 6.0,
    });
    expect(r.success).toBe(false);
  });

  it("percent mode accepts risk_value 2.0 (<= 5.0)", () => {
    const r = makeSettingsSchema(0.5).safeParse({
      ...base,
      risk_mode: "percent",
      risk_value: 2.0,
    });
    expect(r.success).toBe(true);
  });

  it("fixed_lot mode rejects risk_value > per-account max_lot_size (0.9 > 0.5)", () => {
    const r = makeSettingsSchema(0.5).safeParse({
      ...base,
      risk_mode: "fixed_lot",
      risk_value: 0.9,
    });
    expect(r.success).toBe(false);
  });

  it("fixed_lot mode accepts risk_value 0.4 (<= max_lot_size 0.5)", () => {
    const r = makeSettingsSchema(0.5).safeParse({
      ...base,
      risk_mode: "fixed_lot",
      risk_value: 0.4,
    });
    expect(r.success).toBe(true);
  });

  it("the fixed_lot cap is per-account (0.9 passes when max_lot_size is 1.0)", () => {
    const r = makeSettingsSchema(1.0).safeParse({
      ...base,
      risk_mode: "fixed_lot",
      risk_value: 0.9,
    });
    expect(r.success).toBe(true);
  });

  it("rejects non-positive risk_value (0)", () => {
    const r = makeSettingsSchema(0.5).safeParse({ ...base, risk_value: 0 });
    expect(r.success).toBe(false);
  });
});

describe("makeSettingsSchema — integer bounds", () => {
  const schema = makeSettingsSchema(0.5);

  it("max_stages 0 rejected, 1 accepted, 10 accepted, 11 rejected", () => {
    expect(schema.safeParse({ ...base, max_stages: 0 }).success).toBe(false);
    expect(schema.safeParse({ ...base, max_stages: 1 }).success).toBe(true);
    expect(schema.safeParse({ ...base, max_stages: 10 }).success).toBe(true);
    expect(schema.safeParse({ ...base, max_stages: 11 }).success).toBe(false);
  });

  it("default_sl_pips 0 rejected, 1 accepted, 500 accepted, 501 rejected", () => {
    expect(schema.safeParse({ ...base, default_sl_pips: 0 }).success).toBe(false);
    expect(schema.safeParse({ ...base, default_sl_pips: 1 }).success).toBe(true);
    expect(schema.safeParse({ ...base, default_sl_pips: 500 }).success).toBe(true);
    expect(schema.safeParse({ ...base, default_sl_pips: 501 }).success).toBe(false);
  });

  it("max_daily_trades 0 rejected, 1 accepted, 100 accepted, 101 rejected", () => {
    expect(schema.safeParse({ ...base, max_daily_trades: 0 }).success).toBe(false);
    expect(schema.safeParse({ ...base, max_daily_trades: 1 }).success).toBe(true);
    expect(schema.safeParse({ ...base, max_daily_trades: 100 }).success).toBe(true);
    expect(schema.safeParse({ ...base, max_daily_trades: 101 }).success).toBe(false);
  });

  it("rejects a non-integer int field (max_stages 2.5)", () => {
    expect(schema.safeParse({ ...base, max_stages: 2.5 }).success).toBe(false);
  });
});

describe("makeSettingsSchema — read-only fields", () => {
  it("does NOT cap max_open_trades (read-only; passthrough extra key allowed)", () => {
    // An out-of-any-plausible-cap max_open_trades must NOT cause a validation failure,
    // because the schema defines no rule for it (it is not a form field).
    const r = makeSettingsSchema(0.5).safeParse({
      ...base,
      max_open_trades: 9999,
    });
    expect(r.success).toBe(true);
  });
});
