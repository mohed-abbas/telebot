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
import logging
import os
import random
import time

from models import GlobalConfig, SignalAction
from notifier import Notifier
from trade_manager import TradeManager

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
        logger.info("Executor started — cleanup + heartbeat loops running")

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
        for task in (self._cleanup_task, self._heartbeat_task):
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
        """Full position sync from MT5 after reconnect (REL-02)."""
        try:
            positions = await connector.get_positions()
            logger.info(
                "%s: Position sync — %d open position(s)",
                acct_name, len(positions),
            )
        except Exception as exc:
            logger.error("%s: Position sync failed: %s", acct_name, exc)

    # ── Kill Switch ──────────────────────────────────────────────────

    async def emergency_close(self) -> dict:
        """Kill switch: close all positions, cancel all pending, pause trading.

        Sets _trading_paused FIRST to prevent new signals during close.
        """
        self._trading_paused = True  # Block new signals IMMEDIATELY
        logger.warning("KILL SWITCH ACTIVATED — closing all positions and cancelling orders")

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
        }

    def resume_trading(self) -> None:
        """Re-enable trading after kill switch."""
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
