# Execution Audit — Remediation Backlog

Deferred items from the 2026-07-09 execution audit (`execution-audit-2026-07-09.md`). Waves 1–4 landed all critical/high findings and the high-value mediums/lows. The items below were consciously deferred — lower value, tightly coupled through `db.py`/`trade_manager.py`, or judged too risky for the benefit.

## Deferred — trade-state consistency (need db.py + trade_manager.py co-changes)

- **Limit-order status transition never completes** (`trade_manager.py` ~1014). Limit-order trades are logged `status='pending'` and never transition; a broker-side close of a limit-filled position is never reconciled. Needs a new db status-transition path + reconcile hook.
- **Daily trade-limit is read-then-act** (`trade_manager.py` ~794). Concurrent Telethon handlers can exceed the daily cap. Needs an atomic DB increment-and-check (e.g. `UPDATE ... RETURNING`), not a separate read then write.
- **Unstaged path has no durable intent** (`trade_manager.py` ~1004). The non-staged execution path writes no pre-submit intent row and has no forward reconciliation, so a crash mid-submit can orphan a broker position. Needs a durable intent row like the staged path already has.

## Deferred — defensive edge cases (low probability)

- **Zone-watch snapshot rebuild schema drift** (`executor.py` ~991). If an `AccountSettings` field is missing on rebuild, `fixed_lot` stages silently downgrade to percent sizing. Add explicit field-presence handling.
- **Point-band stages can't fire** (`executor.py` ~751). A stage with `zone_low == zone_high` degenerates the zone-watch pre-flight tolerance to zero and never fires. Rare in practice.

## Deferred — recommended SKIP (risk > benefit on live money-handling)

- **Float → Decimal in risk/price/lot math** (`risk_calculator.py` ~64, and broadly). No `Decimal`, no broker `volume_step`/`digits` awareness; the fixed-lot per-stage floor can slightly exceed the configured total. A full precision refactor across the hot path is high-risk on a live trading system for a low-severity gain. Revisit only if a broker actually rejects on volume step.

## Follow-ups surfaced DURING the waves (not in the original audit)

- **`trade_manager.py` ~1172 close path finalizes floating P&L** — the bot's own close path calls `update_trade_close` with `pos.profit` (floating profit at close time) and sets `status='closed'` immediately, so it is never reconciled to the authoritative `deal.profit`. Same inaccuracy class as §4.6; route it through `mark_trade_closing` too. (Flagged by the Wave 4 PNL reviewer.)
- **Promote `TRUST_PROXY` / `SESSION_ABSOLUTE_MAX_AGE` into `config.Settings`** — Wave 3 auth reads these directly from `os.environ` in `dashboard.py`; centralize for validation. See [[project_wave3_auth_deploy_reqs]].
- **SPA `'closing'` status badge (optional)** — the new transient `'closing'` trade status renders as raw text in `HistoryView` (graceful). Add an explicit badge/label if desired.

## Already resolved (were in the audit's medium/low list)

- `update_stage_status` had no status precondition → fixed in Wave 2 (§4.2).
- No catch-all `/api/v2` exception handler → fixed in Wave 1 (§3.1).
