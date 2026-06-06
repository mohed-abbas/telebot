// frontend/src/lib/useElapsed.ts — per-second ticking elapsed timer (D-06).
//
// Returns a formatted MM:SS / H:MM:SS duration computed as `now - Date.parse(startedAtIso)`,
// clamped at 0. A 1s setInterval re-renders `now` so the duration ticks smoothly between the
// staged page's 3s polls (D-07) — it animates the delta, not the poll cadence.
//
// Pitfall-5-EXEMPT (RESEARCH Pattern 2 / D-06): Pitfall 5 bans the SPA re-deriving server
// MONEY/PRICE precision (the XAUUSD pip class of bug). A wall-clock DURATION is neither money
// nor price — it has no broker-precision semantics. The server still OWNS the epoch (`started_at`
// from the 10-02 widening, sourced from the machine `created_at`, NOT the client clock); the
// client merely animates the relative delta. This is the ONE client-side number computation the
// phase allows.
//
// Cleans up the interval on unmount.

import { useEffect, useState } from "react";

export function useElapsed(startedAtIso: string | null | undefined): string {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  // Guard unparseable input (missing/null started_at, or a malformed string): Date.parse
  // returns NaN, and NaN escapes Math.max(0, …) — yielding "NaN:NaN" without this check (WR-04).
  const start = Date.parse(startedAtIso ?? "");
  const secs = Number.isFinite(start)
    ? Math.max(0, Math.floor((now - start) / 1000))
    : 0;
  const h = Math.floor(secs / 3600),
    m = Math.floor((secs % 3600) / 60),
    s = secs % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
