// frontend/src/lib/footgun.ts — pure mode-aware compounded-exposure copy (D-06 / D-07).
//
// The footgun warning is the ONE allowed client-side calc off two BARE numerics
// (risk_value, max_stages) — Pitfall-5-safe: it is neither money nor price, so it has
// no broker-precision semantics (cf. useElapsed.ts, the elapsed-duration precedent).
//
// MODE-AWARE — the load-bearing distinction (RESEARCH §Mode-aware footgun + Pitfall 6):
//   • "percent"   → exposure COMPOUNDS across entries → multiply risk_value × max_stages.
//   • "fixed_lot" → risk_value is the TOTAL lot size across all stages, NOT per-trade
//                   (operator-confirmed 2026-05-01; trade_manager.py:108-117 returns
//                   risk_value / max_stages per stage). So we MUST NOT multiply here —
//                   doing so would display a wrong, alarming number (e.g. "1.6 lots"
//                   when the operator's configured total is 0.4). That is the Pitfall-6 bug.
//
// Copy strings are the verbatim UI-SPEC Copywriting Contract (11-UI-SPEC.md:308-309).

export function footgun(
  mode: "percent" | "fixed_lot",
  riskValue: number,
  maxStages: number,
): string {
  if (mode === "percent") {
    // percent mode: exposure compounds across entries — multiply.
    const total = riskValue * maxStages;
    return `${maxStages} entries at ${riskValue}% risks up to ${total}% per signal.`;
  }
  // fixed_lot mode: riskValue is the TOTAL across stages — do NOT multiply (Pitfall 6).
  return `This sizes up to ${riskValue} total lots per signal across ${maxStages} entries.`;
}
