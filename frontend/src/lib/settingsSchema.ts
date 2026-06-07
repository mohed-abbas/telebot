// frontend/src/lib/settingsSchema.ts — mode-aware zod cap schema (SUX-03).
//
// Mirrors the AUTHORITATIVE server caps in dashboard.validate_settings_form
// (dashboard.py:708-759) + _SETTINGS_HARD_CAPS_INT (658-662). This is UX-only
// defense-in-depth (T-08-18 / threat T-11-01: the server re-validates on confirm and is
// authoritative — a bypassed client cap cannot persist out-of-cap settings). Caps are
// DERIVED from the server, never invented:
//
//   risk_value (percent)   : > 0 AND <= 5.0                 (dashboard.py:733-738)
//   risk_value (fixed_lot) : > 0 AND <= max_lot_size        (dashboard.py:739-741)
//        ↳ max_lot_size is PER-ACCOUNT (store.effective(account).max_lot_size); the SPA reads
//          it from the SettingsView `values` GET response and passes it into this factory.
//   max_stages             : int 1..10                      (line 659)
//   default_sl_pips        : int 1..500                     (line 660)
//   max_daily_trades       : int 1..100                     (line 661)
//
// max_open_trades is in the SettingsView `values` dict but validate_settings_form does NOT
// parse or cap it (it is an accounts-table column, read-only on this page). The schema defines
// NO rule for it — extra keys are stripped, never rejected (RESEARCH §max_open_trades note).
//
// zod v4 API: z.enum / .superRefine / ctx.addIssue({ code: "custom" }) — confirmed at build.

import { z } from "zod";

export function makeSettingsSchema(maxLotSize: number) {
  return z
    .object({
      risk_mode: z.enum(["percent", "fixed_lot"]),
      risk_value: z.number().positive(),
      max_stages: z.number().int().min(1).max(10),
      default_sl_pips: z.number().int().min(1).max(500),
      max_daily_trades: z.number().int().min(1).max(100),
    })
    .superRefine((v, ctx) => {
      // percent mode: hard cap 5.0 (server validate_settings_form).
      if (v.risk_mode === "percent" && v.risk_value > 5.0) {
        ctx.addIssue({
          code: "custom",
          path: ["risk_value"],
          message: "Risk value must be between 0 and 5.0%.",
        });
      }
      // fixed_lot mode: per-account cap = max_lot_size (read at runtime from SettingsView).
      if (v.risk_mode === "fixed_lot" && v.risk_value > maxLotSize) {
        ctx.addIssue({
          code: "custom",
          path: ["risk_value"],
          message: `Risk value exceeds max lot size (${maxLotSize}) for this account.`,
        });
      }
    });
}
