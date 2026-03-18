"""Trade manager — the brain of the signal execution pipeline.

Responsibilities:
  - Zone-based execution logic (market vs limit)
  - Stale signal detection (price already past TP1)
  - Position tracking and signal-to-position mapping
  - Trade management (modify SL, partial close, full close)
  - Daily limit enforcement
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import db
from models import (
    AccountConfig,
    Direction,
    GlobalConfig,
    SignalAction,
    SignalType,
)
from mt5_connector import MT5Connector, OrderType, OrderResult
from risk_calculator import (
    calculate_lot_size,
    calculate_sl_distance,
    calculate_sl_with_jitter,
    calculate_tp_with_jitter,
)

logger = logging.getLogger(__name__)


class TradeManager:
    def __init__(
        self,
        connectors: dict[str, MT5Connector],
        accounts: list[AccountConfig],
        global_config: GlobalConfig,
    ):
        self.connectors = connectors  # account_name → connector
        self.accounts = {a.name: a for a in accounts}
        self.cfg = global_config

    async def handle_signal(self, signal: SignalAction) -> list[dict]:
        """Process a parsed signal. Returns list of execution results for notification."""
        if signal.type == SignalType.OPEN:
            return await self._handle_open(signal)
        elif signal.type == SignalType.CLOSE:
            return await self._handle_close(signal)
        elif signal.type == SignalType.CLOSE_PARTIAL:
            return await self._handle_close_partial(signal)
        elif signal.type == SignalType.MODIFY_SL:
            return await self._handle_modify_sl(signal)
        elif signal.type == SignalType.MODIFY_TP:
            return await self._handle_modify_tp(signal)
        return []

    # ── OPEN ────────────────────────────────────────────────────────────

    async def _handle_open(self, signal: SignalAction) -> list[dict]:
        """Handle a new trade signal with zone-based execution."""
        results = []

        # Log the signal
        signal_id = await db.log_signal(
            raw_text=signal.raw_text,
            signal_type="open",
            action_taken="processing",
            symbol=signal.symbol,
            direction=signal.direction.value if signal.direction else "",
            entry_zone_low=signal.entry_zone[0] if signal.entry_zone else 0,
            entry_zone_high=signal.entry_zone[1] if signal.entry_zone else 0,
            sl=signal.sl or 0,
            tp=signal.target_tp or 0,
        )

        for acct_name, connector in self.connectors.items():
            acct = self.accounts.get(acct_name)
            if not acct or not acct.enabled:
                continue
            if not connector.connected:
                results.append({"account": acct_name, "status": "skipped", "reason": "disconnected"})
                continue

            result = await self._execute_open_on_account(signal, signal_id, acct, connector)
            results.append(result)

        return results

    async def _execute_open_on_account(
        self,
        signal: SignalAction,
        signal_id: int,
        acct: AccountConfig,
        connector: MT5Connector,
    ) -> dict:
        """Execute an open signal on a single account with all checks."""
        name = acct.name

        # ── Check daily limits ──────────────────────────────────────────
        trade_count = await db.get_daily_stat(name, "trades_count")
        if trade_count >= self.cfg.max_daily_trades_per_account:
            reason = f"Daily trade limit ({self.cfg.max_daily_trades_per_account}) reached"
            logger.warning("%s: %s", name, reason)
            return {"account": name, "status": "skipped", "reason": reason}

        msg_count = await db.get_daily_stat(name, "server_messages")
        if msg_count >= self.cfg.max_daily_server_messages:
            reason = f"Daily server message limit ({self.cfg.max_daily_server_messages}) reached"
            logger.warning("%s: %s", name, reason)
            return {"account": name, "status": "skipped", "reason": reason}

        # ── Check max open trades ───────────────────────────────────────
        positions = await connector.get_positions(signal.symbol)
        if len(positions) >= acct.max_open_trades:
            reason = f"Max open trades ({acct.max_open_trades}) reached for {signal.symbol}"
            return {"account": name, "status": "skipped", "reason": reason}

        # ── Check duplicate (same direction already open) ───────────────
        for pos in positions:
            if pos.direction == signal.direction.value:
                reason = f"Already have a {signal.direction.value} position open on {signal.symbol}"
                return {"account": name, "status": "skipped", "reason": reason}

        # ── Get current price ───────────────────────────────────────────
        price_data = await connector.get_price(signal.symbol)
        if price_data is None:
            return {"account": name, "status": "failed", "reason": "Cannot get current price"}
        bid, ask = price_data

        # ── Stale signal check ──────────────────────────────────────────
        current_price = bid if signal.direction == Direction.SELL else ask
        stale_reason = self._check_stale(signal, current_price)
        if stale_reason:
            logger.info("%s: Stale signal — %s", name, stale_reason)
            return {"account": name, "status": "skipped", "reason": stale_reason}

        # ── Zone check → market or limit ────────────────────────────────
        zone_low, zone_high = signal.entry_zone
        use_market, limit_price = self._determine_order_type(
            signal.direction, current_price, zone_low, zone_high,
        )

        # ── Calculate lot size ──────────────────────────────────────────
        acct_info = await connector.get_account_info()
        if acct_info is None:
            return {"account": name, "status": "failed", "reason": "Cannot get account info"}

        entry_for_calc = current_price if use_market else limit_price
        sl_distance = calculate_sl_distance(entry_for_calc, signal.sl)
        lot_size = calculate_lot_size(
            account_balance=acct_info.balance,
            risk_percent=acct.risk_percent,
            sl_distance=sl_distance,
            max_lot_size=acct.max_lot_size,
            jitter_percent=self.cfg.lot_jitter_percent,
            symbol=signal.symbol,
        )

        if lot_size <= 0:
            return {"account": name, "status": "failed", "reason": "Calculated lot size is 0"}

        # ── Apply SL/TP jitter ──────────────────────────────────────────
        jittered_sl = calculate_sl_with_jitter(
            signal.sl, self.cfg.sl_tp_jitter_points, signal.direction,
        )
        jittered_tp = signal.target_tp
        if jittered_tp:
            jittered_tp = calculate_tp_with_jitter(
                jittered_tp, self.cfg.sl_tp_jitter_points, signal.direction,
            )

        # ── Execute ─────────────────────────────────────────────────────
        if use_market:
            order_type = (
                OrderType.MARKET_BUY if signal.direction == Direction.BUY
                else OrderType.MARKET_SELL
            )
            result = await connector.open_order(
                symbol=signal.symbol,
                order_type=order_type,
                volume=lot_size,
                sl=jittered_sl,
                tp=jittered_tp or 0.0,
                comment="telebot",
            )
        else:
            order_type = (
                OrderType.BUY_LIMIT if signal.direction == Direction.BUY
                else OrderType.SELL_LIMIT
            )
            result = await connector.open_order(
                symbol=signal.symbol,
                order_type=order_type,
                volume=lot_size,
                price=limit_price,
                sl=jittered_sl,
                tp=jittered_tp or 0.0,
                comment="telebot",
            )

        await db.increment_daily_stat(name, "server_messages")

        if result.success:
            await db.increment_daily_stat(name, "trades_count")
            await db.log_trade(
                signal_id=signal_id,
                account_name=name,
                symbol=signal.symbol,
                direction=signal.direction.value,
                entry_price=result.price,
                sl=jittered_sl,
                tp=jittered_tp or 0.0,
                lot_size=lot_size,
                ticket=result.ticket,
                status="opened" if use_market else "pending",
                raw_signal=signal.raw_text,
            )

            # Track limit order expiry
            if not use_market:
                expires_at = (
                    datetime.utcnow() + timedelta(minutes=self.cfg.limit_order_expiry_minutes)
                ).isoformat()
                await db.log_pending_order(
                    signal_id=signal_id,
                    account_name=name,
                    ticket=result.ticket,
                    symbol=signal.symbol,
                    order_type=order_type.value,
                    volume=lot_size,
                    price=limit_price,
                    sl=jittered_sl,
                    tp=jittered_tp or 0.0,
                    expires_at=expires_at,
                )

            return {
                "account": name,
                "status": "executed" if use_market else "limit_placed",
                "ticket": result.ticket,
                "price": result.price if use_market else limit_price,
                "lot_size": lot_size,
                "sl": jittered_sl,
                "tp": jittered_tp or 0.0,
                "order_type": "market" if use_market else "limit",
            }
        else:
            await db.log_trade(
                signal_id=signal_id,
                account_name=name,
                symbol=signal.symbol,
                direction=signal.direction.value,
                entry_price=0,
                sl=jittered_sl,
                tp=jittered_tp or 0.0,
                lot_size=lot_size,
                ticket=0,
                status="failed",
                raw_signal=signal.raw_text,
            )
            return {"account": name, "status": "failed", "reason": result.error}

    def _check_stale(self, signal: SignalAction, current_price: float) -> str | None:
        """Check if the signal is stale (price already past TPs)."""
        if not signal.tps:
            return None

        numeric_tps = [tp for tp in signal.tps if isinstance(tp, (int, float))]
        if not numeric_tps:
            return None

        tp1 = numeric_tps[0]

        if signal.direction == Direction.SELL:
            # For SELL, price should be above TP1 (we're selling high, TP is below)
            if current_price <= tp1:
                return f"Price ({current_price:.2f}) already at/below TP1 ({tp1:.2f})"
        elif signal.direction == Direction.BUY:
            # For BUY, price should be below TP1 (we're buying low, TP is above)
            if current_price >= tp1:
                return f"Price ({current_price:.2f}) already at/above TP1 ({tp1:.2f})"

        return None

    def _determine_order_type(
        self,
        direction: Direction,
        current_price: float,
        zone_low: float,
        zone_high: float,
    ) -> tuple[bool, float]:
        """Determine market vs limit order and the limit price.

        Returns: (use_market: bool, limit_price: float)
        """
        zone_mid = (zone_low + zone_high) / 2

        if direction == Direction.SELL:
            # SELL: want to sell high. Execute market if price is in/above zone.
            if current_price >= zone_low:
                return True, 0.0  # market order
            else:
                # Price below zone — place sell limit at zone midpoint
                return False, zone_mid

        else:  # BUY
            # BUY: want to buy low. Execute market if price is in/below zone.
            if current_price <= zone_high:
                return True, 0.0  # market order
            else:
                # Price above zone — place buy limit at zone midpoint
                return False, zone_mid

    # ── CLOSE ───────────────────────────────────────────────────────────

    async def _handle_close(self, signal: SignalAction) -> list[dict]:
        results = []
        signal_id = await db.log_signal(
            raw_text=signal.raw_text, signal_type="close",
            action_taken="processing", symbol=signal.symbol,
        )

        for acct_name, connector in self.connectors.items():
            acct = self.accounts.get(acct_name)
            if not acct or not acct.enabled or not connector.connected:
                continue

            positions = await connector.get_positions(signal.symbol)
            for pos in positions:
                result = await connector.close_position(pos.ticket)
                await db.increment_daily_stat(acct_name, "server_messages")
                if result.success:
                    await db.update_trade_close(pos.ticket, acct_name, pos.profit, result.price)
                    results.append({
                        "account": acct_name, "status": "closed",
                        "ticket": pos.ticket, "pnl": pos.profit,
                    })
                else:
                    results.append({
                        "account": acct_name, "status": "failed",
                        "ticket": pos.ticket, "reason": result.error,
                    })
        return results

    # ── CLOSE PARTIAL ───────────────────────────────────────────────────

    async def _handle_close_partial(self, signal: SignalAction) -> list[dict]:
        results = []
        close_fraction = (signal.close_percent or 50.0) / 100.0

        signal_id = await db.log_signal(
            raw_text=signal.raw_text, signal_type="close_partial",
            action_taken="processing", symbol=signal.symbol,
            details=f"close {signal.close_percent}%",
        )

        for acct_name, connector in self.connectors.items():
            acct = self.accounts.get(acct_name)
            if not acct or not acct.enabled or not connector.connected:
                continue

            positions = await connector.get_positions(signal.symbol)
            for pos in positions:
                close_vol = round(pos.volume * close_fraction, 2)
                close_vol = max(close_vol, 0.01)
                if close_vol >= pos.volume:
                    close_vol = pos.volume  # full close if fraction rounds up

                result = await connector.close_position(pos.ticket, volume=close_vol)
                await db.increment_daily_stat(acct_name, "server_messages")
                if result.success:
                    results.append({
                        "account": acct_name, "status": "partial_closed",
                        "ticket": pos.ticket, "closed_volume": close_vol,
                    })
                else:
                    results.append({
                        "account": acct_name, "status": "failed",
                        "ticket": pos.ticket, "reason": result.error,
                    })
        return results

    # ── MODIFY SL ───────────────────────────────────────────────────────

    async def _handle_modify_sl(self, signal: SignalAction) -> list[dict]:
        results = []
        signal_id = await db.log_signal(
            raw_text=signal.raw_text, signal_type="modify_sl",
            action_taken="processing", symbol=signal.symbol,
            details=f"new_sl={signal.new_sl}",
        )

        for acct_name, connector in self.connectors.items():
            acct = self.accounts.get(acct_name)
            if not acct or not acct.enabled or not connector.connected:
                continue

            positions = await connector.get_positions(signal.symbol)
            for pos in positions:
                new_sl = signal.new_sl
                if new_sl == 0.0:
                    # Breakeven: set SL to entry price
                    new_sl = pos.open_price

                result = await connector.modify_position(pos.ticket, sl=new_sl)
                await db.increment_daily_stat(acct_name, "server_messages")
                if result.success:
                    results.append({
                        "account": acct_name, "status": "sl_modified",
                        "ticket": pos.ticket, "new_sl": new_sl,
                    })
                else:
                    results.append({
                        "account": acct_name, "status": "failed",
                        "ticket": pos.ticket, "reason": result.error,
                    })
        return results

    # ── MODIFY TP ───────────────────────────────────────────────────────

    async def _handle_modify_tp(self, signal: SignalAction) -> list[dict]:
        results = []
        signal_id = await db.log_signal(
            raw_text=signal.raw_text, signal_type="modify_tp",
            action_taken="processing", symbol=signal.symbol,
            details=f"new_tp={signal.new_tp}",
        )

        for acct_name, connector in self.connectors.items():
            acct = self.accounts.get(acct_name)
            if not acct or not acct.enabled or not connector.connected:
                continue

            positions = await connector.get_positions(signal.symbol)
            for pos in positions:
                result = await connector.modify_position(pos.ticket, tp=signal.new_tp)
                await db.increment_daily_stat(acct_name, "server_messages")
                if result.success:
                    results.append({
                        "account": acct_name, "status": "tp_modified",
                        "ticket": pos.ticket, "new_tp": signal.new_tp,
                    })
                else:
                    results.append({
                        "account": acct_name, "status": "failed",
                        "ticket": pos.ticket, "reason": result.error,
                    })
        return results

    # ── PENDING ORDER CLEANUP ───────────────────────────────────────────

    async def cleanup_expired_orders(self) -> list[dict]:
        """Cancel pending orders that have expired. Called periodically."""
        expired = await db.get_expired_pending_orders()
        results = []
        for order in expired:
            acct_name = order["account_name"]
            connector = self.connectors.get(acct_name)
            if not connector or not connector.connected:
                continue

            result = await connector.cancel_pending(order["ticket"])
            await db.mark_pending_cancelled(order["id"])
            await db.increment_daily_stat(acct_name, "server_messages")
            results.append({
                "account": acct_name,
                "status": "cancelled" if result.success else "cancel_failed",
                "ticket": order["ticket"],
                "symbol": order["symbol"],
            })
            logger.info(
                "%s: Cancelled expired limit order #%d (%s)",
                acct_name, order["ticket"], order["symbol"],
            )
        return results
