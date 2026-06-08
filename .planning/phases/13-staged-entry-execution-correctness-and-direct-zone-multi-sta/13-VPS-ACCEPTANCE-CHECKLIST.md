# Phase 13 — VPS End-to-End Live Acceptance Checklist

**Run on:** the Linux VPS bot pointed at the Windows MT5 **demo** account.
**Why:** EXEC2-05 (13-04 orphan protective-TP) and EXEC2-06 (13-05 direct-zone multistage) are
code-complete and DryRun-gated; the live MT5 round-trip was deferred here per the deploy-at-end
policy. This is the single live sign-off for both.

Relevant defaults (confirm against the demo account's settings/snapshot):
- `correlation_window_seconds` = 600 (orphan window-expiry threshold)
- `default_sl_pips` = 100 (orphan default SL; R=1:1 protective TP distance)
- zone-watch loop tick ≈ 10s
- Test symbol assumed `XAUUSD` (must be in MT5 Market Watch on the Windows host, or price reads return None)

---

## Pre-flight

- [ ] Linux VPS pulled latest `main` and rebuilt: `docker compose up -d --build telebot`
- [ ] `docker compose logs -f telebot` shows clean startup, `init_db` ran, MT5 REST bridge connected
- [ ] Migration present on shared Postgres: `staged_entries` has `signal_sl` + `signal_tp` columns
- [ ] Windows host: MT5 terminal + `mt5-rest-server` running for the demo account (no changes pulled — verify it's just up)
- [ ] Trading on the demo account is enabled and `XAUUSD` is in Market Watch
- [ ] A way to watch positions live (MT5 terminal and/or the dashboard positions view)

---

## Scenario A — EXEC2-05: Orphan protective-TP at window expiry (13-04)

> An orphan = a text-only OPEN whose stage 1 filled at market on its default SL, with no follow-up
> inside the correlation window. At expiry it must get an R=1:1 protective TP, SL untouched, exactly once.

- [ ] **A1.** Fire a **text-only OPEN** (orphan) → stage 1 fills at market with its **default SL**.
- [ ] **A2.** Send **no** follow-up. Wait past `correlation_window_seconds` (default **600s**).
- [ ] **A3.** Within ~10s after expiry, the position shows a **TP at distance == its SL distance** (R=1:1), and **SL is unchanged**.
- [ ] **A4.** The TP is set **exactly once** — no repeated modifies on later loop ticks (watch a few ticks; confirm no churn in logs/MT5).
- [ ] **A5.** Repeat A1 but **send a follow-up before expiry** → confirm **NO protective TP** is applied (the follow-up's real SL/TP wins).

**Scenario A pass =** A3 ✅ + A4 ✅ + A5 ✅ (protective TP only on the true orphan, once, SL preserved).

---

## Scenario B — EXEC2-06: Direct-zone multi-stage scale-in (13-05)

> Standalone OPEN with a zone now scales in across N bands (mirrors the correlated-followup path),
> routed through `staged_entries` + the zone-watcher — not a single `zone_mid` fill, no resting limits.

- [ ] **B1.** Fire a standalone **OPEN with zone + SL + TP** and `max_stages=N` → **N stages register**; already-crossed bands fill with the **signal's SL and TP** (not default SL / TP=0) at the **per-stage volume**; the rest **arm**.
- [ ] **B2.** Let price **walk into the zone** → armed bands fill as price enters, each carrying the **signal SL/TP**.
- [ ] **B3.** Fire the same with `max_stages=1` → exactly **ONE whole-zone entry** (no `zone_mid` single-fill).
- [ ] **B4.** Fire an OPEN whose price has **already run past the zone** → it is **skipped as stale**, **no order placed**.
- [ ] **B5.** Confirm a direct-zone sequence is **drained by the kill-switch** and **reconciled on reconnect** (inherited Phase-6 safety).

**Scenario B pass =** B1–B4 ✅ (correct fills/arming, single whole-zone at N=1, stale skip) + B5 ✅ (safety inherited).

---

## Money-correctness spot-checks (both scenarios)

- [ ] No filled stage ever shows **SL = 0** (every fill carries a real SL — signal SL or default SL).
- [ ] Per-stage **volume** ≈ `risk_value / max_stages` (percent mode) — total exposure across N stages does **not** exceed the single-trade `risk_value` ceiling.
- [ ] An OPEN with **no SL** is cleanly **skipped** (logged `skipped`, no order, no error).

---

## Sign-off

- [ ] Scenario A passed on demo
- [ ] Scenario B passed on demo
- [ ] Money-correctness spot-checks passed
- [ ] Any anomalies noted below and triaged

**Signed off by:** ______________  **Date:** ____________  **Demo account / broker:** ____________

**Notes / anomalies:**
