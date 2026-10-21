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

## Follow-ups from the 2026-10-16 code-review batches (batch 7)

- **Partial closes overwrite instead of accumulating** (`executor.py`, `_sync_history_for_account`). The first closing deal of a position marks the trades row `closed` with that deal's profit, and the ticket then leaves `open_tickets`. A later partial-close deal of the same position is never added, so the stored P&L covers only the first slice. The expiry probe already sums all closing deals. A real fix needs closed volume per ticket (sum `deal.volume` until it reaches `lot_size`) before the row is final. The bot itself never partial-closes; this only matters for manual partial closes in MT5. (Code review of batch 6, finding #2.)
- **Netting accounts are unsupported.** On a netting account every stage of a signal merges into one position under one ticket: per-stage comments, SL/TP and D-16 tracking stop meaning anything. Batch 7 stopped treating `entry=2` (reversal) as a close, which removes the worst symptom, but the staged-entry model assumes hedging. Check `account_info().margin_mode == 2` (retail hedging) when an account is added.
- **"Deploy — Windows" workflow restarts services that do not exist.** `.github/workflows/deploy-windows-bridge.yml` runs `Restart-Service mt5-rest-*`, but the bridge runs from `start-all.bat` in the desktop session (it has to; see `docs/windows-vps-setup.md`). The workflow also needs a self-hosted runner on the Windows VPS. Parked by the operator on 2026-10-17.
- **Bridge time base.** `Deal.time` is broker-server time. Batch 7 made every reader tolerant (window widened by `DEAL_TIME_MARGIN`, no deal time used as a timestamp). If deal timestamps are ever needed on our clock (e.g. accurate `close_time` for SL/TP hits), the bridge should report its server offset and convert.

## Already resolved (were in the audit's medium/low list)

- `update_stage_status` had no status precondition → fixed in Wave 2 (§4.2).
- No catch-all `/api/v2` exception handler → fixed in Wave 1 (§3.1).
