"""Multi-account staggered execution engine with heartbeat monitoring.

Wraps TradeManager with humanization and resilience:
  - Shuffles account execution order
  - Random 1-5s delay between accounts
  - Periodic expired order cleanup
  - Heartbeat monitoring (30s) with auto-reconnect
  - Kill switch (emergency close all positions)
  - Signal gating during reconnect or kill switch
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import fields as _dc_fields
from datetime import datetime, timedelta, timezone

import db
from models import AccountSettings, Direction, GlobalConfig, SignalAction, SignalType
from notifier import Notifier
from risk_calculator import GOLD_PIP_SIZE
from trade_manager import Band, TradeManager, stage_is_in_zone_at_arrival

logger = logging.getLogger(__name__)


class Executor:
    # §1.3(b): bounded re-modify attempts before escalating an unverified
    # SL/TP to the operator (prevents every-tick modify spam on a stuck broker).
    _SLTP_VERIFY_MAX_ATTEMPTS = 3

    def __init__(self, trade_manager: TradeManager, global_config: GlobalConfig,
                 notifier: Notifier | None = None, price_simulator=None):
        self.tm = trade_manager
        self.cfg = global_config
        self.notifier = notifier
        self._price_simulator = price_simulator
        self._trading_paused: bool = False       # Kill switch flag
        self._reconnecting: set[str] = set()     # Account names currently reconnecting
        self._last_sync: dict[str, float] = {}   # account -> timestamp of last position sync
        self._heartbeat_task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._zone_watch_task: asyncio.Task | None = None  # Phase 6 D-11/D-14
        self._history_sync_task: asyncio.Task | None = None
        # Per-account high-water mark (UTC) of the last successful history-sync
        # poll. Initialised lazily to (now - lookback_hours) on first iteration.
        self._last_history_sync: dict[str, datetime] = {}
        # §1.3(b) post-trade SL/TP verification sweep — bounded-retry bookkeeping.
        # stage_id -> consecutive failed re-modify attempts; stage_ids already
        # escalated to the operator (so we notify once, not every 10s tick).
        self._sltp_verify_attempts: dict[int, int] = {}
        self._sltp_verify_notified: set[int] = set()

    def is_accepting_signals(self) -> bool:
        """Check if executor can process new signals."""
        if self._trading_paused:
            return False
        # Accept if at least one account is connected and not reconnecting
        for name, conn in self.tm.connectors.items():
            if conn.connected and name not in self._reconnecting:
                return True
        return False

    async def start(self) -> None:
        """Start background tasks (cleanup + heartbeat + simulation monitors)."""
        if self._price_simulator:
            await self._price_simulator.start()
        # Start monitoring loops for dry-run connectors
        from mt5_connector import DryRunConnector
        for conn in self.tm.connectors.values():
            if isinstance(conn, DryRunConnector) and conn.connected:
                await conn.start_monitoring()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._zone_watch_task = asyncio.create_task(self._zone_watch_loop())
        self._history_sync_task = asyncio.create_task(self._history_sync_loop())
        logger.info(
            "Executor started — cleanup + heartbeat + zone-watch + history-sync loops running",
        )

    async def stop(self) -> None:
        # Stop dry-run monitoring loops
        from mt5_connector import DryRunConnector
        for conn in self.tm.connectors.values():
            if isinstance(conn, DryRunConnector):
                await conn.stop_monitoring()
        # Stop price simulator
        if self._price_simulator:
            await self._price_simulator.stop()
        # Stop background tasks
        for task in (
            self._cleanup_task, self._heartbeat_task, self._zone_watch_task,
            self._history_sync_task,
        ):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def execute_signal(self, signal: SignalAction, source_name: str = "") -> list[dict]:
        """Execute a signal across all accounts with staggered delays.

        Shuffles account order and adds random delays between each account
        to avoid identical execution patterns.
        """
        if self._trading_paused:
            return [{"account": "all", "status": "skipped", "reason": "Trading paused (kill switch)"}]

        account_names = list(self.tm.connectors.keys())
        random.shuffle(account_names)

        all_results = []

        for i, acct_name in enumerate(account_names):
            if i > 0:
                delay = random.uniform(
                    self.cfg.stagger_delay_min,
                    self.cfg.stagger_delay_max,
                )
                logger.debug("Stagger delay: %.1fs before %s", delay, acct_name)
                await asyncio.sleep(delay)

            # Kill-switch mid-stagger re-check (mirror of D-21). If the kill
            # switch fired during a stagger sleep, do not open new positions on
            # any remaining account — record them as skipped and break.
            if self._trading_paused:
                for remaining in account_names[i:]:
                    all_results.append({
                        "account": remaining,
                        "status": "skipped",
                        "reason": "Trading paused (kill switch)",
                    })
                break

            connector = self.tm.connectors.get(acct_name)
            acct = self.tm.accounts.get(acct_name)
            if not connector or not acct or not acct.enabled or not connector.connected:
                all_results.append({
                    "account": acct_name,
                    "status": "skipped",
                    "reason": "disabled or disconnected",
                })
                continue

            # Skip accounts currently reconnecting
            if acct_name in self._reconnecting:
                all_results.append({"account": acct_name, "status": "skipped", "reason": "reconnecting"})
                continue

            results = await self._execute_single_account(signal, acct_name, source_name=source_name)
            all_results.extend(results)

        return all_results

    async def _execute_single_account(
        self, signal: SignalAction, target_account: str, source_name: str = "",
    ) -> list[dict]:
        """Execute signal on a single target account.

        Creates a temporary TradeManager scoped to just this account so that
        concurrent signals never see each other's filtered connector dicts
        (fixes the shared-state race condition in the previous swap approach).
        """
        temp_tm = TradeManager(
            connectors={target_account: self.tm.connectors[target_account]},
            accounts=[self.tm.accounts[target_account]],
            global_config=self.tm.cfg,
        )
        temp_tm.settings_store = getattr(self.tm, "settings_store", None)
        temp_tm.correlator = getattr(self.tm, "correlator", None)
        return await temp_tm.handle_signal(signal, source_name=source_name)

    # ── Heartbeat & Reconnect ────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Check MT5 connection health every 30s."""
        while True:
            try:
                await asyncio.sleep(30)
                for acct_name, connector in self.tm.connectors.items():
                    if acct_name in self._reconnecting:
                        continue  # Already reconnecting
                    if self._trading_paused:
                        continue  # Kill switch active, don't bother checking
                    # Skip accounts that were never connected (e.g. no password configured)
                    if not connector.password and not (
                        connector.password_env and os.environ.get(connector.password_env)
                    ):
                        continue
                    alive = await connector.ping()
                    if not alive:
                        # Connection lost or broker disconnected — start reconnect
                        logger.warning("%s: Heartbeat failed — starting reconnect", acct_name)
                        asyncio.create_task(self._reconnect_account(acct_name, connector))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Heartbeat loop error: %s", exc)

    async def _reconnect_account(self, acct_name: str, connector) -> None:
        """Reconnect a single account with exponential backoff (1s -> 60s max)."""
        # Skip accounts without a password (no point reconnecting)
        if not connector.password and not (
            connector.password_env and os.environ.get(connector.password_env)
        ):
            logger.debug("%s: Skipping reconnect — no password configured", acct_name)
            self._reconnecting.discard(acct_name)
            return

        self._reconnecting.add(acct_name)
        if self.notifier:
            await self.notifier.notify_connection_lost(acct_name, "Heartbeat failed — reconnecting")

        delay = 1.0
        max_delay = 60.0
        attempt = 0

        while True:
            await asyncio.sleep(delay)
            attempt += 1
            try:
                # Reset local state only — don't call server disconnect
                connector._connected = False
                success = await asyncio.wait_for(connector.connect(), timeout=15)
                if success:
                    # Full position sync before accepting signals (REL-02)
                    await self._sync_positions(acct_name, connector)
                    self._reconnecting.discard(acct_name)
                    self._last_sync[acct_name] = time.time()
                    if self.notifier:
                        await self.notifier.notify_connection_restored(acct_name)
                    logger.info("%s: Reconnected and synced (attempt %d)", acct_name, attempt)
                    return
            except asyncio.TimeoutError:
                logger.error("%s: Reconnect attempt %d timed out (15s)", acct_name, attempt)
            except Exception as exc:
                logger.error("%s: Reconnect attempt %d failed: %s", acct_name, attempt, exc)

            delay = min(delay * 2, max_delay)

    async def _sync_positions(self, acct_name: str, connector) -> None:
        """Full position sync from MT5 after reconnect (REL-02 + Phase 6 D-24/D-25).

        D-24 reconcile: for every pending staged_entries row on this account,
        mark `filled` when a matching `comment` is present on MT5, or
        `abandoned_reconnect` when the row is older than
        `GlobalConfig.signal_max_age_minutes` and no MT5 position matches.
        Young rows with no MT5 match are left alone.
        """
        try:
            positions = await connector.get_positions()
            logger.info(
                "%s: Position sync — %d open position(s)",
                acct_name, len(positions),
            )
        except Exception as exc:
            logger.error("%s: Position sync failed: %s", acct_name, exc)
            return

        # D-24 — reconcile staged_entries against live MT5 positions by comment.
        try:
            pending = await db.get_pending_stages(account_name=acct_name)
        except Exception as exc:
            logger.error("%s: staged_entries fetch failed during sync: %s", acct_name, exc)
            return

        if not pending:
            return

        by_comment = {
            getattr(p, "comment", ""): p
            for p in positions
            if getattr(p, "comment", "")
        }

        max_age_minutes = getattr(self.cfg, "signal_max_age_minutes", 30)
        now = datetime.now(timezone.utc)

        reconciled = 0
        abandoned = 0
        for stage in pending:
            target_comment = stage["mt5_comment"]
            match = by_comment.get(target_comment)
            if match is not None:
                await db.update_stage_status(stage["id"], "filled", mt5_ticket=match.ticket)
                reconciled += 1
                logger.info(
                    "%s: reconnect reconciled signal_id=%d stage=%d ticket=%d",
                    acct_name, stage["signal_id"], stage["stage_number"], match.ticket,
                )
                continue

            # No MT5 match. Decide abandon vs keep-armed by age.
            created = stage["created_at"]
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_minutes = (now - created).total_seconds() / 60.0
            if age_minutes > max_age_minutes:
                await db.update_stage_status(
                    stage["id"], "abandoned_reconnect",
                    cancelled_reason=f"no_mt5_match_after_{int(age_minutes)}min",
                )
                abandoned += 1
                logger.warning(
                    "%s: reconnect abandoned signal_id=%d stage=%d — age=%dmin > %dmin and no MT5 position",
                    acct_name, stage["signal_id"], stage["stage_number"],
                    int(age_minutes), max_age_minutes,
                )

        if reconciled or abandoned:
            logger.info(
                "%s: staged_entries reconciliation — %d filled, %d abandoned",
                acct_name, reconciled, abandoned,
            )

    # ── Kill Switch ──────────────────────────────────────────────────

    async def emergency_close(self) -> dict:
        """Kill switch: close all positions, cancel all pending, pause trading.

        Sets _trading_paused FIRST to prevent new signals during close.
        D-21: drains staged_entries BEFORE the position-close loop so no stage
        can fire between the pause and the close.
        """
        self._trading_paused = True  # Block new signals IMMEDIATELY
        logger.warning("KILL SWITCH ACTIVATED — closing all positions and cancelling orders")

        # D-21 — drain staged_entries FIRST so armed stages can't fire between
        # pause and position-close. cancelled_by_kill_switch is terminal (D-22):
        # resume_trading does NOT un-cancel these rows.
        try:
            drained_stages = await db.drain_staged_entries_for_kill_switch()
        except Exception as exc:
            logger.error("Kill switch: drain_staged_entries failed: %s", exc)
            drained_stages = 0
        logger.warning("Kill switch: drained %d pending stage(s)", drained_stages)

        closed_positions = 0
        failed_closes = 0
        cancelled_orders = 0
        failed_cancels = 0

        for acct_name, connector in self.tm.connectors.items():
            if not connector.connected:
                continue

            # Close all positions
            try:
                positions = await connector.get_positions()
                for pos in positions:
                    result = await connector.close_position(pos.ticket)
                    if result.success:
                        closed_positions += 1
                        logger.info("%s: Closed position #%d (%s)", acct_name, pos.ticket, pos.symbol)
                    else:
                        failed_closes += 1
                        logger.error("%s: Failed to close #%d: %s", acct_name, pos.ticket, result.error)
            except Exception as exc:
                logger.error("%s: Error closing positions: %s", acct_name, exc)

            # Cancel all pending orders
            try:
                orders = await connector.get_pending_orders()
                for order in orders:
                    result = await connector.cancel_pending(order["ticket"])
                    if result.success:
                        cancelled_orders += 1
                        logger.info("%s: Cancelled order #%d", acct_name, order["ticket"])
                    else:
                        failed_cancels += 1
                        logger.error("%s: Failed to cancel #%d: %s", acct_name, order["ticket"], result.error)
            except Exception as exc:
                logger.error("%s: Error cancelling orders: %s", acct_name, exc)

        return {
            "closed_positions": closed_positions,
            "failed_closes": failed_closes,
            "cancelled_orders": cancelled_orders,
            "failed_cancels": failed_cancels,
            "drained_stages": drained_stages,
        }

    def resume_trading(self) -> None:
        """Re-enable trading after kill switch.

        D-22: we deliberately do NOT un-cancel drained staged_entries.
        'cancelled_by_kill_switch' is terminal. Operator re-sends the signal.
        """
        self._trading_paused = False
        logger.info("Trading RESUMED — kill switch deactivated")

    # ── Background Tasks ─────────────────────────────────────────────

    async def _cleanup_loop(self) -> None:
        """Periodically cancel expired pending orders."""
        while True:
            try:
                await asyncio.sleep(60)  # check every minute
                results = await self.tm.cleanup_expired_orders()
                if results:
                    logger.info("Cleaned up %d expired orders", len(results))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Cleanup loop error: %s", exc)
                await asyncio.sleep(30)

    # ── History sync (broker-side close reconciliation) ─────────────

    # MT5 deal entry constant — DEAL_ENTRY_OUT (closing leg of a position).
    # Hard-coded to avoid an import dependency on MetaTrader5 in the bot
    # process, which only talks to MT5 via the REST server.
    _DEAL_ENTRY_OUT = 1

    async def _history_sync_loop(self) -> None:
        """Reconcile broker-side position closes into the trades table.

        For each connected account, every `history_sync_interval_seconds`:
          - fetch deal history since the per-account high-water mark
            (initialised to now - `history_sync_lookback_hours` on first run)
          - for each closing deal whose position_id maps to a status='opened'
            trade in our DB, call db.update_trade_close(...) with the deal's
            profit (gross broker P&L; commission and swap excluded for now)
          - advance the high-water mark to max(deal.time) + 1s

        This is the path that fixes /analytics zeros and /history empty P&L
        for trades the broker closed via SL/TP or via manual MT5 action.
        """
        interval = max(5, int(self.cfg.history_sync_interval_seconds))
        lookback = max(1, int(self.cfg.history_sync_lookback_hours))
        while True:
            try:
                await asyncio.sleep(interval)
                if self._trading_paused:
                    # Don't reconcile while drained — operator may be in the
                    # middle of inspecting state. Resume picks it up next tick.
                    continue
                for acct_name, connector in self.tm.connectors.items():
                    if acct_name in self._reconnecting:
                        continue
                    if not connector.connected:
                        continue
                    try:
                        await self._sync_history_for_account(
                            acct_name, connector, lookback,
                        )
                    except Exception as exc:
                        logger.warning(
                            "%s: history-sync iteration failed: %s",
                            acct_name, exc,
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("History-sync loop error: %s", exc)

    async def _sync_history_for_account(
        self, acct_name: str, connector, lookback_hours: int,
    ) -> None:
        """One iteration of the history sync for a single account."""
        now = datetime.now(timezone.utc)
        since = self._last_history_sync.get(acct_name)
        if since is None:
            since = now - timedelta(hours=lookback_hours)

        try:
            open_tickets = await db.get_open_trade_tickets_for_account(acct_name)
        except Exception as exc:
            logger.warning(
                "%s: history-sync DB lookup failed: %s", acct_name, exc,
            )
            return
        if not open_tickets:
            # Nothing to reconcile; still advance the watermark so the next
            # iteration doesn't re-scan a growing window.
            self._last_history_sync[acct_name] = now
            return

        try:
            deals = await connector.get_history_deals(since, now)
        except Exception as exc:
            logger.warning(
                "%s: history-sync REST call failed: %s", acct_name, exc,
            )
            return

        if not deals:
            self._last_history_sync[acct_name] = now
            return

        max_deal_time = 0.0
        reconciled = 0
        for deal in deals:
            if deal.time > max_deal_time:
                max_deal_time = deal.time
            if deal.entry != self._DEAL_ENTRY_OUT:
                continue
            ticket = deal.position_id
            if ticket not in open_tickets:
                continue
            try:
                await db.update_trade_close(
                    ticket=ticket,
                    account_name=acct_name,
                    pnl=deal.profit,
                    close_price=deal.price,
                )
            except Exception as exc:
                logger.error(
                    "%s: update_trade_close ticket=%d failed: %s",
                    acct_name, ticket, exc,
                )
                continue
            reconciled += 1
            logger.info(
                "%s: history-sync reconciled ticket=%d pnl=%+.2f close=%.2f",
                acct_name, ticket, deal.profit, deal.price,
            )

        if max_deal_time > 0:
            # +1s so we don't re-process the boundary deal next tick.
            advanced = datetime.fromtimestamp(max_deal_time + 1.0, tz=timezone.utc)
            self._last_history_sync[acct_name] = max(advanced, since)
        else:
            self._last_history_sync[acct_name] = now

        if reconciled:
            logger.info(
                "%s: history-sync — %d trade(s) reconciled this tick",
                acct_name, reconciled,
            )

    # ── Phase 6 Zone Watch (D-11/D-14) ───────────────────────────────

    async def _zone_watch_loop(self) -> None:
        """D-11/D-14 — poll MT5 for every awaiting_zone stage; fire when band entered.

        Cadence: 10s uniform. Cross-cuts:
          - D-21 kill-switch: loop-entry guard + per-stage mid-tick re-check
          - D-24/D-25 idempotency: probe MT5 by target `comment` before submit
          - D-14 pre-flight: re-fetch bid/ask; require within band ± 0.5*band_width
          - D-16 cascade: if stage 1 of a signal_id is filled-in-DB but absent
                          on MT5, cancel remaining unfilled stages for that signal
        """
        while True:
            try:
                await asyncio.sleep(10)  # D-14 cadence
                if self._trading_paused:
                    continue

                # EXEC2-05 (D2-09..D2-12) — orphan protective-TP watchdog.
                # Runs FIRST and independently of awaiting_zone rows: an orphan
                # stage-1 has no awaiting_zone siblings by definition, so it would
                # never appear in get_active_stages() / by_pair below. At
                # correlation-window expiry it gets an R=1:1 protective TP off its
                # default-SL distance. Failure-isolated so it never aborts the loop.
                try:
                    await self._run_orphan_protective_tp_watchdog()
                except Exception as exc:
                    logger.warning("Zone watch: orphan-TP watchdog error: %s", exc)

                # §1.3(b) — post-trade SL/TP verification sweep. Confirms every
                # filled stage's live broker position actually carries the
                # intended SL/TP; re-issues a bounded modify when it deviated
                # (e.g. a stage-1 align that silently failed). Failure-isolated
                # so it never aborts the loop.
                try:
                    await self._run_stage_sltp_verification_sweep()
                except Exception as exc:
                    logger.warning("Zone watch: SL/TP verification sweep error: %s", exc)

                try:
                    rows = await db.get_active_stages()
                except Exception as exc:
                    logger.error("Zone watch: get_active_stages failed: %s", exc)
                    continue
                if not rows:
                    continue

                # Group by (account, symbol) so get_price / get_positions run once.
                by_pair: dict[tuple[str, str], list[dict]] = {}
                for r in rows:
                    by_pair.setdefault((r["account_name"], r["symbol"]), []).append(r)

                # D-16 per-tick memoization: (account, signal_id) -> stage-1-live-or-not-cascadable.
                # True  = fire-ok (stage 1 live OR stage 1 not-yet-filled so no cascade)
                # False = already cascaded this tick; subsequent stages for this signal_id skip
                stage1_live_cache: dict[tuple[str, int], bool] = {}

                for (acct_name, symbol), stages in by_pair.items():
                    if acct_name in self._reconnecting:
                        continue
                    connector = self.tm.connectors.get(acct_name)
                    if connector is None:
                        continue

                    try:
                        price = await connector.get_price(symbol)
                    except Exception as exc:
                        logger.warning("%s: zone-watch get_price failed: %s", acct_name, exc)
                        continue
                    if price is None:
                        continue
                    bid, ask = price

                    try:
                        positions = await connector.get_positions()
                    except Exception as exc:
                        logger.warning(
                            "%s: zone-watch get_positions failed: %s", acct_name, exc,
                        )
                        continue

                    positions_by_comment = {
                        getattr(p, "comment", ""): p
                        for p in positions
                        if getattr(p, "comment", "")
                    }

                    # Price-based cascade: if live price has reached the
                    # signal's target_tp or sl, cancel ALL unfilled stages
                    # for that signal_id and skip them in the band-fire loop.
                    # Faster than D-16 (broker-independent) and complementary.
                    cascaded_signal_ids: set[int] = set()
                    seen_signal_ids: set[int] = set()
                    for stage in stages:
                        sid_iter = stage["signal_id"]
                        if sid_iter in seen_signal_ids:
                            continue
                        seen_signal_ids.add(sid_iter)

                        # EXEC2-01: prefer the PERSISTED per-stage SL/TP
                        # (Plan 01/03/05). For a correlated sequence the
                        # signals row is the orphan (sl=0/tp=0), so the old
                        # get_signal_targets path was a silent no-op — deep
                        # stages kept firing after price already hit the real
                        # TP. The stage row carries the follow-up's real SL/TP.
                        # get_signal_targets remains the NULL fallback for
                        # pre-migration rows / direct-zone signals whose own
                        # signals row already holds real sl/tp.
                        stage_sl = stage.get("signal_sl")
                        stage_tp = stage.get("signal_tp")
                        stage_dir = (stage.get("direction") or "").lower()

                        targets = None
                        if stage_sl is None or stage_tp is None or not stage_dir:
                            try:
                                targets = await db.get_signal_targets(sid_iter)
                            except Exception as exc:
                                logger.warning(
                                    "%s: target fetch failed signal_id=%d: %s",
                                    acct_name, sid_iter, exc,
                                )
                                targets = None

                        sig_dir = stage_dir or (
                            (targets.get("direction") or "").lower()
                            if targets else ""
                        )
                        sig_sl = (
                            float(stage_sl) if stage_sl is not None
                            else float((targets or {}).get("sl") or 0.0)
                        )
                        sig_tp = (
                            float(stage_tp) if stage_tp is not None
                            else float((targets or {}).get("tp") or 0.0)
                        )
                        if not sig_dir or (sig_sl <= 0 and sig_tp <= 0):
                            # No usable protective levels from either source.
                            continue
                        hit_reason: str | None = None
                        if sig_dir == "buy":
                            if sig_tp > 0 and bid >= sig_tp:
                                hit_reason = "tp_reached"
                            elif sig_sl > 0 and bid <= sig_sl:
                                hit_reason = "sl_reached"
                        elif sig_dir == "sell":
                            if sig_tp > 0 and ask <= sig_tp:
                                hit_reason = "tp_reached"
                            elif sig_sl > 0 and ask >= sig_sl:
                                hit_reason = "sl_reached"
                        if hit_reason is None:
                            continue
                        try:
                            cancelled = await db.cancel_unfilled_stages_target_reached(
                                sid_iter, reason=hit_reason, account_name=acct_name,
                            )
                        except Exception as exc:
                            logger.error(
                                "%s: target-cascade DB write failed signal_id=%d: %s",
                                acct_name, sid_iter, exc,
                            )
                            continue
                        cascaded_signal_ids.add(sid_iter)
                        logger.info(
                            "%s: target cascade — signal_id=%d %s "
                            "(bid=%.2f ask=%.2f sl=%.2f tp=%.2f); "
                            "cancelled %d unfilled stage(s)",
                            acct_name, sid_iter, hit_reason,
                            bid, ask, sig_sl, sig_tp, cancelled,
                        )

                    for stage in stages:
                        if stage["signal_id"] in cascaded_signal_ids:
                            continue
                        # D-21 mid-tick re-check (before any work on this stage)
                        if self._trading_paused:
                            break

                        signal_id = stage["signal_id"]
                        band_low = stage["band_low"]
                        band_high = stage["band_high"]
                        band_width = max(band_high - band_low, 0.0)
                        tolerance = 0.5 * band_width
                        direction = stage["direction"]

                        band = Band(
                            stage_number=stage["stage_number"],
                            low=band_low,
                            high=band_high,
                        )
                        if not stage_is_in_zone_at_arrival(band, bid, ask, direction):
                            continue

                        # D-16 — stage-1-exit cascade. Verify stage 1 is still live on MT5.
                        cache_key = (acct_name, signal_id)
                        if cache_key not in stage1_live_cache:
                            stage1_comment = f"telebot-{signal_id}-s1"
                            if stage1_comment in positions_by_comment:
                                # Stage 1 is live on MT5 — fire is OK.
                                stage1_live_cache[cache_key] = True
                            else:
                                # Stage 1 not on MT5. Was it ever filled?
                                try:
                                    stage1_row = await db.get_stage_by_comment(stage1_comment)
                                except Exception:
                                    stage1_row = None
                                if stage1_row and stage1_row.get("status") == "filled":
                                    # Stage 1 filled-then-exited. Cascade.
                                    try:
                                        cancelled = await db.cancel_unfilled_stages_for_signal(
                                            signal_id, reason="stage1_closed",
                                            account_name=acct_name,
                                        )
                                    except Exception as exc:
                                        logger.error(
                                            "%s: D-16 cascade DB write failed: %s",
                                            acct_name, exc,
                                        )
                                        cancelled = 0
                                    logger.info(
                                        "%s: D-16 cascade — stage 1 of signal_id=%d no longer "
                                        "open on MT5; cancelled %d unfilled stage(s)",
                                        acct_name, signal_id, cancelled,
                                    )
                                    stage1_live_cache[cache_key] = False
                                    continue
                                else:
                                    # Stage 1 still awaiting (or no row) — do NOT cascade.
                                    # Fire is OK as far as D-16 is concerned.
                                    stage1_live_cache[cache_key] = True

                        if not stage1_live_cache[cache_key]:
                            continue  # already cascaded this tick

                        # D-14 pre-flight re-check
                        try:
                            price2 = await connector.get_price(symbol)
                        except Exception:
                            continue
                        if price2 is None:
                            continue
                        bid2, ask2 = price2
                        price_center = (band_low + band_high) / 2.0
                        mid_price = (bid2 + ask2) / 2.0
                        if abs(mid_price - price_center) > band_width + tolerance:
                            logger.info(
                                "%s: zone-watch skip stage=%d signal_id=%d — price drifted "
                                "outside band±tolerance",
                                acct_name, stage["stage_number"], signal_id,
                            )
                            continue

                        # D-21 re-check BEFORE submit
                        if self._trading_paused:
                            break

                        # D-25 idempotency probe.
                        target_comment = stage["mt5_comment"]
                        match = positions_by_comment.get(target_comment)
                        if match is not None:
                            await db.update_stage_status(
                                stage["id"], "filled", mt5_ticket=match.ticket,
                            )
                            logger.info(
                                "%s: zone-watch idempotency match — stage=%d already on MT5 "
                                "ticket=%d",
                                acct_name, stage["stage_number"], match.ticket,
                            )
                            continue

                        # Build synthetic signal + call stage-aware _execute_open_on_account.
                        await self._fire_zone_stage(
                            acct_name=acct_name, connector=connector,
                            symbol=symbol, stage=stage,
                            bid=bid2, ask=ask2,
                            signal_id=signal_id,
                        )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Zone watch loop error: %s", exc)

    async def _run_orphan_protective_tp_watchdog(self) -> None:
        """EXEC2-05 (D2-09..D2-12) — protective-TP watchdog for orphan stage-1.

        An orphan text-only position (stage 1 filled at market with a default
        SL, no follow-up in the correlation window) must never be left
        unmanaged. At window expiry we attach a protective TP so it rides on
        its default SL + an assigned target.

        Runs independently of the awaiting_zone band-fire path: an orphan has
        NO sibling stages by definition, so it never appears in
        get_active_stages(). This watchdog fetches its own candidates and
        per-(account,symbol) live positions.

          - Window gate (D2-12): act ONLY after the signal is older than
            ``correlation_window_seconds`` (a fast follow-up still gets to set
            the real SL/TP first) AND only when there are NO sibling stages.
            Both are enforced by ``db.get_orphan_candidate_stage1s``.
          - R=1:1 (D2-10/D2-11): ``TP = entry ± (sl_distance × 1)`` where
            ``sl_distance = default_sl_pips × pip_size`` (the same value used at
            orphan stage-1 open). R is the literal constant 1 — no config knob.
          - Idempotency (Open Q2): read the live position's CURRENT TP; skip if
            already non-zero. Survives reconnects / loop re-ticks; no schema.
          - Failure isolation (D-17 pattern): a modify_position error is logged
            and swallowed — it must not abort the watchdog or the loop.
        """
        if self._trading_paused:
            return

        try:
            window = int(getattr(self.cfg, "correlation_window_seconds", 600))
        except Exception:
            window = 600

        try:
            candidates = await db.get_orphan_candidate_stage1s(window)
        except Exception as exc:
            logger.warning("orphan-TP candidate fetch failed: %s", exc)
            return
        if not candidates:
            return

        # Group by (account, symbol) so get_positions runs once per connector.
        by_pair: dict[tuple[str, str], list[dict]] = {}
        for row in candidates:
            by_pair.setdefault(
                (row["account_name"], row["symbol"]), []
            ).append(row)

        for (acct_name, symbol), rows in by_pair.items():
            if acct_name in self._reconnecting:
                continue
            connector = self.tm.connectors.get(acct_name)
            if connector is None:
                continue

            try:
                positions = await connector.get_positions()
            except Exception as exc:
                logger.warning(
                    "%s: orphan-TP get_positions failed: %s", acct_name, exc,
                )
                continue

            positions_by_comment = {
                getattr(p, "comment", ""): p
                for p in positions
                if getattr(p, "comment", "")
            }

            for row in rows:
                await self._attach_one_orphan_protective_tp(
                    acct_name=acct_name, connector=connector,
                    symbol=symbol, row=row,
                    positions_by_comment=positions_by_comment,
                )

    async def _attach_one_orphan_protective_tp(
        self,
        *,
        acct_name: str,
        connector,
        symbol: str,
        row: dict,
        positions_by_comment: dict,
    ) -> None:
        """Attach an R=1:1 protective TP to a single orphan stage-1 position.

        Idempotent (skips an already-set TP) and failure-isolated. See
        ``_run_orphan_protective_tp_watchdog`` for the locked constraints.
        """
        pip_size = GOLD_PIP_SIZE if symbol.upper() == "XAUUSD" else 0.0001

        comment = row.get("mt5_comment") or f"telebot-{row['signal_id']}-s1"
        position = positions_by_comment.get(comment)
        if position is None:
            # Row claims a live ticket but MT5 shows no matching position
            # right now (e.g. just closed) — nothing to protect.
            return

        # Idempotency (Open Q2): skip if a TP is already set. Survives
        # reconnect / loop re-ticks without a persisted flag.
        current_tp = getattr(position, "tp", 0.0) or 0.0
        if current_tp != 0.0:
            return

        # Resolve default_sl_pips from the frozen snapshot (parity with
        # _fire_zone_stage / the orphan stage-1 open).
        snapshot_dict = row.get("snapshot_settings")
        if isinstance(snapshot_dict, str):
            try:
                snapshot_dict = json.loads(snapshot_dict)
            except Exception:
                snapshot_dict = {}
        if not isinstance(snapshot_dict, dict):
            snapshot_dict = {}
        default_sl_pips = snapshot_dict.get("default_sl_pips", 100) or 100

        sl_distance = default_sl_pips * pip_size  # R=1:1 → TP distance == SL distance
        entry = getattr(position, "open_price", 0.0) or 0.0
        direction = (row.get("direction") or getattr(position, "direction", "") or "").lower()
        if direction == "buy":
            protective_tp = entry + sl_distance
        else:
            protective_tp = entry - sl_distance

        # Keep the existing SL unchanged (D-08 default SL preserved).
        keep_sl = getattr(position, "sl", 0.0)
        ticket = getattr(position, "ticket", None) or row.get("mt5_ticket")

        try:
            modify_result = await connector.modify_position(
                ticket, sl=keep_sl, tp=protective_tp,
            )
        except Exception as exc:  # never let a connector error abort the loop
            logger.warning(
                "%s: orphan protective-TP raised ticket=%s — continuing: %s",
                acct_name, ticket, exc,
            )
            return

        if getattr(modify_result, "success", False):
            logger.info(
                "%s: orphan protective-TP attached ticket=%s tp=%.5f "
                "(entry=%.5f sl_distance=%.5f R=1:1, signal_id=%d)",
                acct_name, ticket, protective_tp, entry, sl_distance,
                row["signal_id"],
            )
            try:
                await db.log_signal(
                    raw_text=(
                        f"<orphan-protective-tp signal_id={row['signal_id']} "
                        f"ticket={ticket}>"
                    ),
                    signal_type="orphan_protective_tp",
                    action_taken=f"orphan_protective_tp ticket={ticket}",
                    symbol=symbol,
                    direction=direction,
                    sl=keep_sl or 0.0,
                    tp=protective_tp,
                )
            except Exception as exc:  # audit row failure must not abort
                logger.warning(
                    "%s: orphan protective-TP audit log failed: %s",
                    acct_name, exc,
                )
        else:
            logger.warning(
                "%s: orphan protective-TP FAILED ticket=%s reason=%s",
                acct_name, ticket, getattr(modify_result, "error", "unknown"),
            )

    async def _run_stage_sltp_verification_sweep(self) -> None:
        """§1.3(b) — confirm filled positions actually carry their SL/TP.

        For every FILLED stage that persisted an authoritative SL/TP
        (``db.get_filled_stages_for_sltp_verification``) and still has a live
        broker position, compare the position's live SL/TP against the targets
        and re-issue ``modify_position`` when they deviate beyond a tolerance
        that swallows humanization jitter. The canonical failure this closes: a
        stage-1 align (correlated follow-up) whose immediate modify failed —
        the position is then left on its default SL with TP=0 forever, and the
        orphan watchdog excludes any stage-1 that has sibling rows.

        Idempotent (a matched position is a no-op), bounded (``N`` failed
        re-modifies then an operator notification), and safe (never touches a
        position the operator/broker has already closed).
        """
        if self._trading_paused:
            return

        try:
            rows = await db.get_filled_stages_for_sltp_verification()
        except Exception as exc:
            logger.warning("SL/TP sweep: candidate fetch failed: %s", exc)
            return
        if not rows:
            return

        by_pair: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            by_pair.setdefault(
                (row["account_name"], row["symbol"]), []
            ).append(row)

        for (acct_name, symbol), stages in by_pair.items():
            if acct_name in self._reconnecting:
                continue
            connector = self.tm.connectors.get(acct_name)
            if connector is None:
                continue

            try:
                positions = await connector.get_positions()
            except Exception as exc:
                logger.warning(
                    "%s: SL/TP sweep get_positions failed: %s", acct_name, exc,
                )
                continue

            positions_by_comment = {
                getattr(p, "comment", ""): p
                for p in positions
                if getattr(p, "comment", "")
            }

            for stage in stages:
                await self._verify_one_stage_sltp(
                    acct_name=acct_name, connector=connector,
                    symbol=symbol, stage=stage,
                    positions_by_comment=positions_by_comment,
                )

    async def _verify_one_stage_sltp(
        self,
        *,
        acct_name: str,
        connector,
        symbol: str,
        stage: dict,
        positions_by_comment: dict,
    ) -> None:
        """Verify/repair one filled stage's live SL/TP. See the sweep docstring."""
        stage_id = stage["id"]
        comment = stage.get("mt5_comment") or ""
        position = positions_by_comment.get(comment)
        if position is None:
            # No live position with our comment — the operator/broker closed it
            # (or it never opened). Do NOT re-modify a ghost. Clear any tracked
            # retry/notify state so a future re-fill starts clean.
            self._sltp_verify_attempts.pop(stage_id, None)
            self._sltp_verify_notified.discard(stage_id)
            return

        target_sl = stage.get("signal_sl")
        target_tp = stage.get("signal_tp")
        live_sl = getattr(position, "sl", 0.0) or 0.0
        live_tp = getattr(position, "tp", 0.0) or 0.0

        # Tolerance swallows the SL/TP humanization jitter (the live values were
        # jittered at open; the persisted targets are the raw plan) so we only
        # act on GROSS deviation — chiefly an unset level (0.0) that should be
        # protected. Respect the symbol's pip size for the cushion.
        pip_size = GOLD_PIP_SIZE if symbol.upper() == "XAUUSD" else 0.0001
        jitter = float(getattr(self.cfg, "sl_tp_jitter_points", 0.0) or 0.0)
        tol = jitter + 2 * pip_size

        needs_fix = False
        if target_sl is not None:
            if live_sl == 0.0 or abs(live_sl - float(target_sl)) > tol:
                needs_fix = True
        if target_tp is not None:
            if live_tp == 0.0 or abs(live_tp - float(target_tp)) > tol:
                needs_fix = True

        if not needs_fix:
            # In sync — idempotent no-op. Reset any prior retry/notify state.
            self._sltp_verify_attempts.pop(stage_id, None)
            self._sltp_verify_notified.discard(stage_id)
            return

        attempts = self._sltp_verify_attempts.get(stage_id, 0)
        if attempts >= self._SLTP_VERIFY_MAX_ATTEMPTS:
            # Exhausted retries — escalate ONCE, then stop hammering the broker.
            if stage_id not in self._sltp_verify_notified:
                self._sltp_verify_notified.add(stage_id)
                ticket = getattr(position, "ticket", None) or stage.get("mt5_ticket")
                logger.error(
                    "%s: SL/TP UNVERIFIED after %d attempts — ticket=%s "
                    "signal_id=%d stage=%d live_sl=%.5f live_tp=%.5f "
                    "target_sl=%s target_tp=%s",
                    acct_name, attempts, ticket, stage["signal_id"],
                    stage["stage_number"], live_sl, live_tp,
                    target_sl, target_tp,
                )
                if self.notifier:
                    try:
                        await self.notifier.notify_alert(
                            f"STAGE SL/TP UNVERIFIED: {acct_name} ticket={ticket} "
                            f"(signal_id={stage['signal_id']} stage={stage['stage_number']}) "
                            f"— live sl={live_sl} tp={live_tp}, target sl={target_sl} "
                            f"tp={target_tp}; broker rejected {attempts} re-modify attempts"
                        )
                    except Exception as exc:
                        logger.warning(
                            "%s: SL/TP unverified notify failed: %s", acct_name, exc,
                        )
            return

        # Snap the position to the authoritative targets. Pass None for a level
        # with no target so the REST bridge preserves the existing value
        # (0.0 would be read as an explicit "remove"). A non-null target always
        # wins — this is what protects the stage-1-align-failed position.
        sl_to_send = float(target_sl) if target_sl is not None else None
        tp_to_send = float(target_tp) if target_tp is not None else None
        ticket = getattr(position, "ticket", None) or stage.get("mt5_ticket")

        try:
            result = await connector.modify_position(
                ticket, sl=sl_to_send, tp=tp_to_send,
            )
        except Exception as exc:  # never let a connector error abort the sweep
            self._sltp_verify_attempts[stage_id] = attempts + 1
            logger.warning(
                "%s: SL/TP sweep modify raised ticket=%s — continuing: %s",
                acct_name, ticket, exc,
            )
            return

        if getattr(result, "success", False):
            self._sltp_verify_attempts.pop(stage_id, None)
            self._sltp_verify_notified.discard(stage_id)
            logger.info(
                "%s: SL/TP re-aligned ticket=%s sl=%s tp=%s "
                "(signal_id=%d stage=%d)",
                acct_name, ticket, sl_to_send, tp_to_send,
                stage["signal_id"], stage["stage_number"],
            )
        else:
            self._sltp_verify_attempts[stage_id] = attempts + 1
            logger.warning(
                "%s: SL/TP sweep modify FAILED ticket=%s reason=%s (attempt %d)",
                acct_name, ticket, getattr(result, "error", "unknown"),
                attempts + 1,
            )

    async def _fire_zone_stage(
        self,
        *,
        acct_name: str,
        connector,
        symbol: str,
        stage: dict,
        bid: float,
        ask: float,
        signal_id: int,
    ) -> None:
        """Build a synthetic SignalAction and call trade_manager's stage-aware fill.

        Separated from _zone_watch_loop so the loop body stays readable.
        """
        acct = self.tm.accounts.get(acct_name)
        if acct is None:
            return

        # Rebuild AccountSettings from the stage's frozen JSONB snapshot (D-30).
        snapshot_dict = stage.get("snapshot_settings")
        if isinstance(snapshot_dict, str):
            try:
                snapshot_dict = json.loads(snapshot_dict)
            except Exception:
                snapshot_dict = {}
        if not isinstance(snapshot_dict, dict):
            snapshot_dict = {}
        try:
            snapshot = AccountSettings(
                **{f.name: snapshot_dict[f.name] for f in _dc_fields(AccountSettings)}
            )
        except Exception as exc:
            logger.error(
                "%s: zone-watch snapshot rebuild failed signal_id=%d stage=%d: %s",
                acct_name, signal_id, stage["stage_number"], exc,
            )
            snapshot = None

        direction_str = stage["direction"]
        band_low = stage["band_low"]
        band_high = stage["band_high"]

        # XAUUSD is the only v1.1-supported symbol.
        # Source of truth: risk_calculator.GOLD_PIP_SIZE (parity with
        # trade_manager._pip_size_for_symbol; gold pip = $0.10 = 10 points).
        pip_size = GOLD_PIP_SIZE if symbol.upper() == "XAUUSD" else 0.0001
        default_sl_pips = getattr(snapshot, "default_sl_pips", 100) if snapshot else 100
        if direction_str == "buy":
            entry_price = band_high
            sl_price = entry_price - default_sl_pips * pip_size
            direction_enum = Direction.BUY
        else:
            entry_price = band_low
            sl_price = entry_price + default_sl_pips * pip_size
            direction_enum = Direction.SELL

        # EXEC2-01 / D2-05: carry the signal's REAL persisted SL/TP (set by
        # Plan 01/03/05) so a late stage fired by this watchdog ends with the
        # same protective levels as the rest of its sequence — not a rebuilt
        # default_sl_pips SL with TP=0. NULL-safe: a pre-migration row whose
        # signal_sl is NULL falls back to the default_sl_pips-derived sl_price
        # (NEVER sl=0 — the D-08 backstop at _execute_open_on_account remains).
        # signal_tp may be None for an orphan stage with no TP; that is
        # acceptable here (the orphan-TP attach is Plan 03/04).
        signal_sl = stage.get("signal_sl")
        signal_tp = stage.get("signal_tp")
        resolved_sl = sl_price if signal_sl is None else signal_sl

        synth = SignalAction(
            type=SignalType.OPEN,
            symbol=symbol,
            raw_text=(
                f"<zone-watch stage {stage['stage_number']} signal_id={signal_id}>"
            ),
            direction=direction_enum,
            entry_zone=(band_low, band_high),
            sl=resolved_sl,
            tps=[],
            target_tp=signal_tp,
        )

        try:
            result = await self.tm._execute_open_on_account(
                synth, signal_id, acct, connector,
                staged=True,
                stage_number=stage["stage_number"],
                stage_row_id=stage["id"],
                snapshot=snapshot,
            )
        except Exception as exc:
            logger.error(
                "%s: zone-watch stage fill raised: %s (signal_id=%d stage=%d)",
                acct_name, exc, signal_id, stage["stage_number"],
            )
            try:
                await db.update_stage_status(
                    stage["id"], "failed",
                    cancelled_reason=str(exc)[:200],
                )
            except Exception:
                pass
            return

        status = result.get("status")
        if status in ("executed", "limit_placed", "filled"):
            ticket = result.get("ticket")
            try:
                await db.update_stage_status(
                    stage["id"], "filled",
                    mt5_ticket=int(ticket) if ticket else None,
                )
            except Exception as exc:
                logger.error(
                    "%s: update_stage_status(filled) failed signal_id=%d stage=%d: %s",
                    acct_name, signal_id, stage["stage_number"], exc,
                )
        elif status == "capped":
            # _execute_open_on_account already wrote status='capped' via update_stage_status.
            pass
        elif status in ("failed", "skipped"):
            # Only write 'failed' if the row is still open (don't overwrite any terminal
            # state _execute_open_on_account may have set, e.g. via the D-25 probe).
            reason = result.get("reason", "unknown")
            # §4.2: a lost firing claim means the at-arrival path already owns
            # this row and is mid-submit. Writing 'failed' here would strand the
            # winner's fill (its 'firing'->'filled' would no-op the row back).
            # Leave it alone — the owning path finalizes it.
            if reason == "claim_lost":
                return
            try:
                await db.update_stage_status(
                    stage["id"], "failed",
                    cancelled_reason=str(reason)[:200],
                )
            except Exception:
                pass
