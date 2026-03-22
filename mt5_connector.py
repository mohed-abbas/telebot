"""MT5 connection abstraction layer.

Supports two backends:
  - mt5linux (Wine + RPyC) — free, self-hosted, primary
  - MetaAPI (cloud) — paid fallback

The rest of the codebase only imports this module, never the backend directly.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class OrderType(Enum):
    MARKET_BUY = "market_buy"
    MARKET_SELL = "market_sell"
    BUY_LIMIT = "buy_limit"
    SELL_LIMIT = "sell_limit"
    BUY_STOP = "buy_stop"
    SELL_STOP = "sell_stop"


@dataclass
class OrderResult:
    success: bool
    ticket: int = 0
    price: float = 0.0
    volume: float = 0.0
    error: str = ""


@dataclass
class Position:
    ticket: int
    symbol: str
    direction: str  # "buy" or "sell"
    volume: float
    open_price: float
    sl: float
    tp: float
    profit: float
    comment: str = ""


@dataclass
class AccountInfo:
    balance: float
    equity: float
    margin: float
    free_margin: float
    currency: str = "USD"


class MT5Connector:
    """Abstract base for MT5 connections. Each account gets its own connector."""

    def __init__(self, account_name: str, server: str, login: int, password: str, magic_number: int = 202603):
        self.account_name = account_name
        self.server = server
        self.login = login
        self.password = password
        self.magic_number = magic_number
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def _clear_password(self) -> None:
        """Clear password from memory after successful connection."""
        self.password = ""

    async def connect(self) -> bool:
        raise NotImplementedError

    async def disconnect(self) -> None:
        raise NotImplementedError

    async def get_price(self, symbol: str) -> tuple[float, float] | None:
        """Returns (bid, ask) or None if unavailable."""
        raise NotImplementedError

    async def get_account_info(self) -> AccountInfo | None:
        raise NotImplementedError

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        raise NotImplementedError

    async def open_order(
        self,
        symbol: str,
        order_type: OrderType,
        volume: float,
        price: float = 0.0,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "",
    ) -> OrderResult:
        raise NotImplementedError

    async def modify_position(
        self, ticket: int, sl: float | None = None, tp: float | None = None
    ) -> OrderResult:
        raise NotImplementedError

    async def close_position(self, ticket: int, volume: float | None = None) -> OrderResult:
        """Close position fully, or partially if volume < position volume."""
        raise NotImplementedError

    async def cancel_pending(self, ticket: int) -> OrderResult:
        raise NotImplementedError

    async def get_pending_orders(self, symbol: str | None = None) -> list[dict]:
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════════════════
# DRY-RUN BACKEND — logs everything, executes nothing
# ═══════════════════════════════════════════════════════════════════════


class DryRunConnector(MT5Connector):
    """Simulates MT5 connection for testing. No real trades placed."""

    _ticket_counter: int = 100000
    _fake_positions: dict[int, Position]

    def __init__(self, account_name: str, server: str, login: int, password: str, magic_number: int = 202603):
        super().__init__(account_name, server, login, password, magic_number=magic_number)
        self._fake_positions = {}

    async def connect(self) -> bool:
        logger.info("[DRY-RUN] %s: Connected to %s (login: %d)", self.account_name, self.server, self.login)
        self._connected = True
        self._clear_password()
        return True

    async def disconnect(self) -> None:
        logger.info("[DRY-RUN] %s: Disconnected", self.account_name)
        self._connected = False

    async def get_price(self, symbol: str) -> tuple[float, float] | None:
        # Return a fake price for testing — in production this queries MT5
        logger.info("[DRY-RUN] %s: get_price(%s) → simulated", self.account_name, symbol)
        return None  # Caller must handle None (skip execution)

    async def get_account_info(self) -> AccountInfo:
        return AccountInfo(balance=10000.0, equity=10000.0, margin=0.0, free_margin=10000.0)

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        positions = list(self._fake_positions.values())
        if symbol:
            positions = [p for p in positions if p.symbol == symbol]
        return positions

    async def open_order(
        self,
        symbol: str,
        order_type: OrderType,
        volume: float,
        price: float = 0.0,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "",
    ) -> OrderResult:
        DryRunConnector._ticket_counter += 1
        ticket = DryRunConnector._ticket_counter
        logger.info(
            "[DRY-RUN] %s: OPEN %s %s vol=%.2f price=%.2f sl=%.2f tp=%.2f → ticket=%d",
            self.account_name, order_type.value, symbol, volume, price, sl, tp, ticket,
        )
        direction = "buy" if "buy" in order_type.value else "sell"
        self._fake_positions[ticket] = Position(
            ticket=ticket, symbol=symbol, direction=direction,
            volume=volume, open_price=price, sl=sl, tp=tp, profit=0.0, comment=comment,
        )
        return OrderResult(success=True, ticket=ticket, price=price, volume=volume)

    async def modify_position(
        self, ticket: int, sl: float | None = None, tp: float | None = None
    ) -> OrderResult:
        logger.info(
            "[DRY-RUN] %s: MODIFY ticket=%d sl=%s tp=%s",
            self.account_name, ticket,
            f"{sl:.2f}" if sl is not None else "unchanged",
            f"{tp:.2f}" if tp is not None else "unchanged",
        )
        if ticket in self._fake_positions:
            pos = self._fake_positions[ticket]
            if sl is not None:
                self._fake_positions[ticket] = Position(
                    ticket=pos.ticket, symbol=pos.symbol, direction=pos.direction,
                    volume=pos.volume, open_price=pos.open_price, sl=sl,
                    tp=tp if tp is not None else pos.tp, profit=pos.profit,
                )
            return OrderResult(success=True, ticket=ticket)
        return OrderResult(success=False, ticket=ticket, error="Position not found")

    async def close_position(self, ticket: int, volume: float | None = None) -> OrderResult:
        logger.info(
            "[DRY-RUN] %s: CLOSE ticket=%d volume=%s",
            self.account_name, ticket,
            f"{volume:.2f}" if volume else "full",
        )
        if ticket in self._fake_positions:
            pos = self._fake_positions[ticket]
            if volume and volume < pos.volume:
                # Partial close
                self._fake_positions[ticket] = Position(
                    ticket=pos.ticket, symbol=pos.symbol, direction=pos.direction,
                    volume=pos.volume - volume, open_price=pos.open_price,
                    sl=pos.sl, tp=pos.tp, profit=pos.profit,
                )
            else:
                del self._fake_positions[ticket]
            return OrderResult(success=True, ticket=ticket)
        return OrderResult(success=False, ticket=ticket, error="Position not found")

    async def cancel_pending(self, ticket: int) -> OrderResult:
        logger.info("[DRY-RUN] %s: CANCEL pending ticket=%d", self.account_name, ticket)
        return OrderResult(success=True, ticket=ticket)

    async def get_pending_orders(self, symbol: str | None = None) -> list[dict]:
        return []


# ═══════════════════════════════════════════════════════════════════════
# MT5LINUX BACKEND — Wine + RPyC (primary production backend)
# ═══════════════════════════════════════════════════════════════════════


class MT5LinuxConnector(MT5Connector):
    """Connects to MT5 via mt5linux (Wine + RPyC bridge).

    Requires an MT5 terminal running in Wine with RPyC server on port 18812.
    """

    def __init__(
        self,
        account_name: str,
        server: str,
        login: int,
        password: str,
        host: str = "localhost",
        port: int = 18812,
        magic_number: int = 202603,
    ):
        super().__init__(account_name, server, login, password, magic_number=magic_number)
        self.host = host
        self.port = port
        self._mt5 = None

    async def connect(self) -> bool:
        try:
            from mt5linux import MetaTrader5
            self._mt5 = MetaTrader5(host=self.host, port=self.port)
            self._mt5.initialize()
            result = self._mt5.login(login=self.login, password=self.password, server=self.server)
            if not result:
                error = self._mt5.last_error()
                logger.error("%s: MT5 login failed: %s", self.account_name, error)
                self._connected = False
                return False
            info = self._mt5.account_info()
            logger.info(
                "%s: Connected — balance=%.2f equity=%.2f",
                self.account_name, info.balance, info.equity,
            )
            self._connected = True
            self._clear_password()
            return True
        except Exception as exc:
            logger.error("%s: MT5 connection failed: %s", self.account_name, exc)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        if self._mt5:
            try:
                self._mt5.shutdown()
            except Exception:
                pass
        self._connected = False
        logger.info("%s: Disconnected", self.account_name)

    async def get_price(self, symbol: str) -> tuple[float, float] | None:
        if not self._mt5:
            return None
        try:
            tick = self._mt5.symbol_info_tick(symbol)
            if tick is None:
                return None
            return (tick.bid, tick.ask)
        except Exception as exc:
            logger.error("%s: get_price failed: %s", self.account_name, exc)
            return None

    async def get_account_info(self) -> AccountInfo | None:
        if not self._mt5:
            return None
        try:
            info = self._mt5.account_info()
            if info is None:
                return None
            return AccountInfo(
                balance=info.balance,
                equity=info.equity,
                margin=info.margin,
                free_margin=info.margin_free,
                currency=info.currency,
            )
        except Exception as exc:
            logger.error("%s: get_account_info failed: %s", self.account_name, exc)
            return None

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        if not self._mt5:
            return []
        try:
            if symbol:
                raw = self._mt5.positions_get(symbol=symbol)
            else:
                raw = self._mt5.positions_get()
            if raw is None:
                return []
            positions = []
            for p in raw:
                positions.append(Position(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    direction="buy" if p.type == 0 else "sell",
                    volume=p.volume,
                    open_price=p.price_open,
                    sl=p.sl,
                    tp=p.tp,
                    profit=p.profit,
                    comment=p.comment,
                ))
            return positions
        except Exception as exc:
            logger.error("%s: get_positions failed: %s", self.account_name, exc)
            return []

    async def open_order(
        self,
        symbol: str,
        order_type: OrderType,
        volume: float,
        price: float = 0.0,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "",
    ) -> OrderResult:
        if not self._mt5:
            return OrderResult(success=False, error="Not connected")
        try:
            import MetaTrader5 as mt5_const

            type_map = {
                OrderType.MARKET_BUY: mt5_const.ORDER_TYPE_BUY,
                OrderType.MARKET_SELL: mt5_const.ORDER_TYPE_SELL,
                OrderType.BUY_LIMIT: mt5_const.ORDER_TYPE_BUY_LIMIT,
                OrderType.SELL_LIMIT: mt5_const.ORDER_TYPE_SELL_LIMIT,
                OrderType.BUY_STOP: mt5_const.ORDER_TYPE_BUY_STOP,
                OrderType.SELL_STOP: mt5_const.ORDER_TYPE_SELL_STOP,
            }

            # Get fill price for market orders
            if order_type in (OrderType.MARKET_BUY, OrderType.MARKET_SELL):
                tick = self._mt5.symbol_info_tick(symbol)
                if tick is None:
                    return OrderResult(success=False, error="Cannot get price")
                price = tick.ask if order_type == OrderType.MARKET_BUY else tick.bid
                action = mt5_const.TRADE_ACTION_DEAL
            else:
                action = mt5_const.TRADE_ACTION_PENDING

            request = {
                "action": action,
                "symbol": symbol,
                "volume": volume,
                "type": type_map[order_type],
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": 20,  # max slippage in points
                "magic": self.magic_number,
                "comment": comment or "telebot",
                "type_time": mt5_const.ORDER_TIME_GTC,
                "type_filling": mt5_const.ORDER_FILLING_IOC,
            }

            result = self._mt5.order_send(request)
            if result is None:
                error = self._mt5.last_error()
                return OrderResult(success=False, error=str(error))

            if result.retcode != mt5_const.TRADE_RETCODE_DONE:
                return OrderResult(
                    success=False,
                    error=f"retcode={result.retcode} comment={result.comment}",
                )

            logger.info(
                "%s: Order opened — ticket=%d price=%.2f vol=%.2f",
                self.account_name, result.order, result.price, result.volume,
            )
            return OrderResult(
                success=True,
                ticket=result.order,
                price=result.price,
                volume=result.volume,
            )
        except Exception as exc:
            logger.error("%s: open_order failed: %s", self.account_name, exc)
            return OrderResult(success=False, error=str(exc))

    async def modify_position(
        self, ticket: int, sl: float | None = None, tp: float | None = None
    ) -> OrderResult:
        if not self._mt5:
            return OrderResult(success=False, error="Not connected")
        try:
            import MetaTrader5 as mt5_const

            # Get current position to fill in unchanged values
            positions = self._mt5.positions_get(ticket=ticket)
            if not positions:
                return OrderResult(success=False, ticket=ticket, error="Position not found")
            pos = positions[0]

            request = {
                "action": mt5_const.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol": pos.symbol,
                "sl": sl if sl is not None else pos.sl,
                "tp": tp if tp is not None else pos.tp,
            }

            result = self._mt5.order_send(request)
            if result is None or result.retcode != mt5_const.TRADE_RETCODE_DONE:
                error = str(self._mt5.last_error()) if result is None else result.comment
                return OrderResult(success=False, ticket=ticket, error=error)

            logger.info("%s: Position %d modified — sl=%.2f tp=%.2f", self.account_name, ticket, request["sl"], request["tp"])
            return OrderResult(success=True, ticket=ticket)
        except Exception as exc:
            logger.error("%s: modify_position failed: %s", self.account_name, exc)
            return OrderResult(success=False, ticket=ticket, error=str(exc))

    async def close_position(self, ticket: int, volume: float | None = None) -> OrderResult:
        if not self._mt5:
            return OrderResult(success=False, error="Not connected")
        try:
            import MetaTrader5 as mt5_const

            positions = self._mt5.positions_get(ticket=ticket)
            if not positions:
                return OrderResult(success=False, ticket=ticket, error="Position not found")
            pos = positions[0]

            close_volume = volume if volume and volume < pos.volume else pos.volume
            close_type = mt5_const.ORDER_TYPE_SELL if pos.type == 0 else mt5_const.ORDER_TYPE_BUY

            tick = self._mt5.symbol_info_tick(pos.symbol)
            if tick is None:
                return OrderResult(success=False, ticket=ticket, error="Cannot get price")
            close_price = tick.bid if pos.type == 0 else tick.ask

            request = {
                "action": mt5_const.TRADE_ACTION_DEAL,
                "position": ticket,
                "symbol": pos.symbol,
                "volume": close_volume,
                "type": close_type,
                "price": close_price,
                "deviation": 20,
                "magic": self.magic_number,
                "comment": "telebot_close",
                "type_filling": mt5_const.ORDER_FILLING_IOC,
            }

            result = self._mt5.order_send(request)
            if result is None or result.retcode != mt5_const.TRADE_RETCODE_DONE:
                error = str(self._mt5.last_error()) if result is None else result.comment
                return OrderResult(success=False, ticket=ticket, error=error)

            logger.info("%s: Position %d closed — vol=%.2f price=%.2f", self.account_name, ticket, close_volume, close_price)
            return OrderResult(success=True, ticket=ticket, price=close_price, volume=close_volume)
        except Exception as exc:
            logger.error("%s: close_position failed: %s", self.account_name, exc)
            return OrderResult(success=False, ticket=ticket, error=str(exc))

    async def cancel_pending(self, ticket: int) -> OrderResult:
        if not self._mt5:
            return OrderResult(success=False, error="Not connected")
        try:
            import MetaTrader5 as mt5_const
            request = {
                "action": mt5_const.TRADE_ACTION_REMOVE,
                "order": ticket,
            }
            result = self._mt5.order_send(request)
            if result is None or result.retcode != mt5_const.TRADE_RETCODE_DONE:
                error = str(self._mt5.last_error()) if result is None else result.comment
                return OrderResult(success=False, ticket=ticket, error=error)
            return OrderResult(success=True, ticket=ticket)
        except Exception as exc:
            return OrderResult(success=False, ticket=ticket, error=str(exc))

    async def get_pending_orders(self, symbol: str | None = None) -> list[dict]:
        if not self._mt5:
            return []
        try:
            if symbol:
                orders = self._mt5.orders_get(symbol=symbol)
            else:
                orders = self._mt5.orders_get()
            if orders is None:
                return []
            return [
                {
                    "ticket": o.ticket,
                    "symbol": o.symbol,
                    "type": o.type,
                    "volume": o.volume_current,
                    "price": o.price_open,
                    "sl": o.sl,
                    "tp": o.tp,
                }
                for o in orders
            ]
        except Exception as exc:
            logger.error("%s: get_pending_orders failed: %s", self.account_name, exc)
            return []


def create_connector(
    backend: str,
    account_name: str,
    server: str,
    login: int,
    password: str,
    **kwargs,
) -> MT5Connector:
    """Factory function to create the appropriate connector."""
    magic_number = kwargs.get("magic_number", 202603)
    if backend == "dry_run":
        return DryRunConnector(account_name, server, login, password, magic_number=magic_number)
    elif backend == "mt5linux":
        return MT5LinuxConnector(
            account_name, server, login, password,
            host=kwargs.get("mt5_host", "localhost"),
            port=kwargs.get("mt5_port", 18812),
            magic_number=magic_number,
        )
    else:
        raise ValueError(f"Unknown MT5 backend: {backend}")
