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
from datetime import datetime, timezone

import db
from models import AccountSettings, Direction, GlobalConfig, SignalAction, SignalType
from notifier import Notifier
from trade_manager import Band, TradeManager, stage_is_in_zone_at_arrival

logger = logging.getLogger(__name__)


class Executor:
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
        logger.info("Executor started — cleanup + heartbeat + zone-watch loops running")

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
        for task in (self._cleanup_task, self._heartbeat_task, self._zone_watch_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def execute_signal(self, signal: SignalAction) -> list[dict]:
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

            results = await self._execute_single_account(signal, acct_name)
            all_results.extend(results)

        return all_results

    async def _execute_single_account(
        self, signal: SignalAction, target_account: str,
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
        return await temp_tm.handle_signal(signal)

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

                    for stage in stages:
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

        # XAUUSD is the only v1.1-supported symbol; pip size hard-coded for parity
        # with trade_manager._pip_size_for_symbol (gold = $0.01).
        pip_size = 0.01 if symbol.upper() == "XAUUSD" else 0.0001
        default_sl_pips = getattr(snapshot, "default_sl_pips", 100) if snapshot else 100
        if direction_str == "buy":
            entry_price = band_high
            sl_price = entry_price - default_sl_pips * pip_size
            direction_enum = Direction.BUY
        else:
            entry_price = band_low
            sl_price = entry_price + default_sl_pips * pip_size
            direction_enum = Direction.SELL

        synth = SignalAction(
            type=SignalType.OPEN,
            symbol=symbol,
            raw_text=(
                f"<zone-watch stage {stage['stage_number']} signal_id={signal_id}>"
            ),
            direction=direction_enum,
            entry_zone=(band_low, band_high),
            sl=sl_price,
            tps=[],
            target_tp=None,
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
            try:
                await db.update_stage_status(
                    stage["id"], "failed",
                    cancelled_reason=str(reason)[:200],
                )
            except Exception:
                pass
