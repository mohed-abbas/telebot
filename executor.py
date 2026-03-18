"""Multi-account staggered execution engine.

Wraps TradeManager with humanization:
  - Shuffles account execution order
  - Random 1-5s delay between accounts
  - Periodic expired order cleanup
"""

from __future__ import annotations

import asyncio
import logging
import random

from models import GlobalConfig, SignalAction
from trade_manager import TradeManager

logger = logging.getLogger(__name__)


class Executor:
    def __init__(self, trade_manager: TradeManager, global_config: GlobalConfig):
        self.tm = trade_manager
        self.cfg = global_config
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start background tasks (pending order cleanup loop)."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Executor started — cleanup loop running")

    async def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def execute_signal(self, signal: SignalAction) -> list[dict]:
        """Execute a signal across all accounts with staggered delays.

        Shuffles account order and adds random delays between each account
        to avoid identical execution patterns.
        """
        # Get list of account names and shuffle
        account_names = list(self.tm.connectors.keys())
        random.shuffle(account_names)

        all_results = []

        for i, acct_name in enumerate(account_names):
            # Add staggered delay (skip first account)
            if i > 0:
                delay = random.uniform(
                    self.cfg.stagger_delay_min,
                    self.cfg.stagger_delay_max,
                )
                logger.debug("Stagger delay: %.1fs before %s", delay, acct_name)
                await asyncio.sleep(delay)

            # Execute on this single account via trade_manager
            # Trade manager processes one account at a time here
            connector = self.tm.connectors.get(acct_name)
            acct = self.tm.accounts.get(acct_name)
            if not connector or not acct or not acct.enabled or not connector.connected:
                all_results.append({
                    "account": acct_name,
                    "status": "skipped",
                    "reason": "disabled or disconnected",
                })
                continue

            # We call the trade_manager's internal method for single-account execution
            # For OPEN signals, we need the signal_id
            results = await self._execute_single_account(signal, acct_name)
            all_results.extend(results)

        return all_results

    async def _execute_single_account(
        self, signal: SignalAction, target_account: str,
    ) -> list[dict]:
        """Execute signal on a single target account.

        Temporarily filters connectors to only the target account.
        """
        # Save original connectors, filter to just this account
        original = self.tm.connectors
        self.tm.connectors = {target_account: original[target_account]}
        try:
            results = await self.tm.handle_signal(signal)
        finally:
            self.tm.connectors = original
        return results

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
