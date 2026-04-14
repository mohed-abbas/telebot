"""MT5 connection abstraction layer.

Supports two backends:
  - dry_run — logs everything, executes nothing (testing)
  - rest_api — REST bridge to MT5 (production)

The rest of the codebase only imports this module, never the backend directly.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from enum import Enum

import httpx

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

    def __init__(self, account_name: str, server: str, login: int, password: str,
                 magic_number: int = 202603, password_env: str = ""):
        self.account_name = account_name
        self.server = server
        self.login = login
        self.password = password
        self.magic_number = magic_number
        self.password_env = password_env
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def _clear_password(self) -> None:
        """Clear password from memory after successful connection."""
        self.password = ""

    async def ping(self) -> bool:
        """Check if MT5 connection is alive. Returns True if healthy."""
        raise NotImplementedError

    async def connect(self, password: str | None = None) -> bool:
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
# DRY-RUN BACKEND — full trade lifecycle simulation
# ═══════════════════════════════════════════════════════════════════════


class DryRunConnector(MT5Connector):
    """Simulates MT5 with live prices, SL/TP monitoring, and P&L tracking."""

    _fake_positions: dict[int, Position]

    MARGIN_PER_LOT = 2000.0  # ~$2000 margin per standard lot for gold

    def __init__(self, account_name: str, server: str, login: int, password: str,
                 magic_number: int = 202603, password_env: str = "",
                 price_simulator=None, on_position_closed=None,
                 initial_balance: float = 10000.0):
        super().__init__(account_name, server, login, password, magic_number=magic_number, password_env=password_env)
        self._ticket_counter = 100000
        self._fake_positions = {}
        self._simulated_prices: dict[str, tuple[float, float]] = {}  # fallback static prices
        self._price_simulator = price_simulator
        self._on_position_closed = on_position_closed  # async callback(account, pos, close_price, pnl, reason)
        self._balance = initial_balance
        self._realized_pnl = 0.0
        self._pending_orders: dict[int, dict] = {}
        self._monitor_task: asyncio.Task | None = None

    async def ping(self) -> bool:
        """Dry-run connector is always alive if connected."""
        return self._connected

    async def connect(self, password: str | None = None) -> bool:
        logger.info("[DRY-RUN] %s: Connected to %s (login: %d)", self.account_name, self.server, self.login)
        self._connected = True
        self._clear_password()
        return True

    async def disconnect(self) -> None:
        logger.info("[DRY-RUN] %s: Disconnected", self.account_name)
        self._connected = False

    # ── Price management ───────────────────────────────────────────────

    def set_simulated_price(self, symbol: str, bid: float, ask: float) -> None:
        """Pre-load a simulated price. Also bootstraps the PriceSimulator."""
        self._simulated_prices[symbol] = (bid, ask)
        if self._price_simulator:
            mid = (bid + ask) / 2.0
            self._price_simulator.register_symbol(symbol, mid)

    async def get_price(self, symbol: str) -> tuple[float, float] | None:
        # Prefer live simulator prices
        if self._price_simulator:
            price = self._price_simulator.get_price(symbol)
            if price:
                return price
        # Fall back to static prices
        price = self._simulated_prices.get(symbol)
        if price is None:
            logger.warning("[DRY-RUN] %s: get_price(%s) → no price available", self.account_name, symbol)
        return price

    # ── P&L calculation ────────────────────────────────────────────────

    def _get_current_price(self, symbol: str) -> tuple[float, float] | None:
        """Synchronous price lookup for internal calculations."""
        if self._price_simulator:
            price = self._price_simulator.get_price(symbol)
            if price:
                return price
        return self._simulated_prices.get(symbol)

    def _calc_pnl(self, pos: Position) -> float:
        """Calculate unrealized P&L for a position."""
        price_data = self._get_current_price(pos.symbol)
        if not price_data:
            return 0.0
        bid, ask = price_data
        if pos.direction == "buy":
            return (bid - pos.open_price) * pos.volume * 100
        else:
            return (pos.open_price - ask) * pos.volume * 100

    # ── Account info (dynamic) ─────────────────────────────────────────

    async def get_account_info(self) -> AccountInfo:
        unrealized = sum(self._calc_pnl(p) for p in self._fake_positions.values())
        equity = self._balance + unrealized
        margin = sum(p.volume * self.MARGIN_PER_LOT for p in self._fake_positions.values())
        return AccountInfo(
            balance=round(self._balance, 2),
            equity=round(equity, 2),
            margin=round(margin, 2),
            free_margin=round(equity - margin, 2),
        )

    # ── Positions (with live P&L) ──────────────────────────────────────

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        positions = list(self._fake_positions.values())
        if symbol:
            positions = [p for p in positions if p.symbol == symbol]
        # Update profit in-place for dashboard display
        for pos in positions:
            pos.profit = round(self._calc_pnl(pos), 2)
        return positions

    # ── Order execution ────────────────────────────────────────────────

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
        self._ticket_counter += 1
        ticket = self._ticket_counter
        direction = "buy" if "buy" in order_type.value else "sell"

        # For market orders without a price, use the current simulated price
        if price == 0.0:
            price_data = self._get_current_price(symbol)
            if price_data:
                bid, ask = price_data
                price = ask if direction == "buy" else bid  # buy at ask, sell at bid

        # Register symbol with price simulator for live tracking
        if self._price_simulator and price > 0:
            self._price_simulator.register_symbol(symbol, price)

        is_pending = order_type in (
            OrderType.BUY_LIMIT, OrderType.SELL_LIMIT,
            OrderType.BUY_STOP, OrderType.SELL_STOP,
        )

        if is_pending:
            # Store as pending order — will fill when price reaches the level
            self._pending_orders[ticket] = {
                "ticket": ticket, "symbol": symbol, "order_type": order_type.value,
                "direction": direction, "volume": volume, "price": price,
                "sl": sl, "tp": tp, "comment": comment,
            }
            logger.info(
                "[DRY-RUN] %s: PENDING %s %s vol=%.2f price=%.2f sl=%.2f tp=%.2f → ticket=%d",
                self.account_name, order_type.value, symbol, volume, price, sl, tp, ticket,
            )
        else:
            # Market order — create position immediately
            self._fake_positions[ticket] = Position(
                ticket=ticket, symbol=symbol, direction=direction,
                volume=volume, open_price=price, sl=sl, tp=tp, profit=0.0, comment=comment,
            )
            logger.info(
                "[DRY-RUN] %s: OPEN %s %s vol=%.2f price=%.2f sl=%.2f tp=%.2f → ticket=%d",
                self.account_name, order_type.value, symbol, volume, price, sl, tp, ticket,
            )

        return OrderResult(success=True, ticket=ticket, price=price, volume=volume)

    # ── Position modification ──────────────────────────────────────────

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
            self._fake_positions[ticket] = Position(
                ticket=pos.ticket, symbol=pos.symbol, direction=pos.direction,
                volume=pos.volume, open_price=pos.open_price,
                sl=sl if sl is not None else pos.sl,
                tp=tp if tp is not None else pos.tp,
                profit=pos.profit, comment=pos.comment,
            )
            return OrderResult(success=True, ticket=ticket)
        return OrderResult(success=False, ticket=ticket, error="Position not found")

    # ── Position closing (with P&L) ───────────────────────────────────

    async def close_position(self, ticket: int, volume: float | None = None) -> OrderResult:
        if ticket not in self._fake_positions:
            return OrderResult(success=False, ticket=ticket, error="Position not found")

        pos = self._fake_positions[ticket]
        pnl = self._calc_pnl(pos)

        # Determine close price
        price_data = self._get_current_price(pos.symbol)
        close_price = 0.0
        if price_data:
            bid, ask = price_data
            close_price = bid if pos.direction == "buy" else ask

        if volume and volume < pos.volume:
            # Partial close — proportional P&L
            fraction = volume / pos.volume
            realized = pnl * fraction
            self._balance += realized
            self._realized_pnl += realized
            self._fake_positions[ticket] = Position(
                ticket=pos.ticket, symbol=pos.symbol, direction=pos.direction,
                volume=round(pos.volume - volume, 2), open_price=pos.open_price,
                sl=pos.sl, tp=pos.tp, profit=0.0, comment=pos.comment,
            )
            logger.info(
                "[DRY-RUN] %s: PARTIAL CLOSE ticket=%d vol=%.2f P&L=$%.2f",
                self.account_name, ticket, volume, realized,
            )
        else:
            # Full close
            self._balance += pnl
            self._realized_pnl += pnl
            del self._fake_positions[ticket]
            logger.info(
                "[DRY-RUN] %s: CLOSE ticket=%d P&L=$%.2f balance=$%.2f",
                self.account_name, ticket, pnl, self._balance,
            )

        return OrderResult(success=True, ticket=ticket, price=close_price, volume=volume or pos.volume)

    # ── Pending orders ─────────────────────────────────────────────────

    async def cancel_pending(self, ticket: int) -> OrderResult:
        if ticket in self._pending_orders:
            del self._pending_orders[ticket]
            logger.info("[DRY-RUN] %s: CANCEL pending ticket=%d", self.account_name, ticket)
            return OrderResult(success=True, ticket=ticket)
        logger.info("[DRY-RUN] %s: CANCEL pending ticket=%d (not found)", self.account_name, ticket)
        return OrderResult(success=True, ticket=ticket)

    async def get_pending_orders(self, symbol: str | None = None) -> list[dict]:
        orders = list(self._pending_orders.values())
        if symbol:
            orders = [o for o in orders if o["symbol"] == symbol]
        return orders

    # ── Background monitoring loop ─────────────────────────────────────

    async def start_monitoring(self) -> None:
        """Start the SL/TP and pending order monitoring loop."""
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("[DRY-RUN] %s: Monitor loop started", self.account_name)

    async def stop_monitoring(self) -> None:
        """Stop the monitoring loop."""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
            logger.info("[DRY-RUN] %s: Monitor loop stopped", self.account_name)

    async def _monitor_loop(self) -> None:
        """Check SL/TP hits and pending order fills every second."""
        while True:
            try:
                await asyncio.sleep(1)
                await self._check_sl_tp()
                await self._check_pending_fills()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[DRY-RUN] %s: Monitor error: %s", self.account_name, exc)

    async def _check_sl_tp(self) -> None:
        """Close positions whose SL or TP has been breached."""
        for ticket in list(self._fake_positions.keys()):
            pos = self._fake_positions.get(ticket)
            if not pos:
                continue
            price_data = self._get_current_price(pos.symbol)
            if not price_data:
                continue
            bid, ask = price_data

            if pos.direction == "buy":
                if pos.sl > 0 and bid <= pos.sl:
                    await self._close_by_trigger(ticket, pos, pos.sl, "SL hit")
                elif pos.tp > 0 and bid >= pos.tp:
                    await self._close_by_trigger(ticket, pos, pos.tp, "TP hit")
            elif pos.direction == "sell":
                if pos.sl > 0 and ask >= pos.sl:
                    await self._close_by_trigger(ticket, pos, pos.sl, "SL hit")
                elif pos.tp > 0 and ask <= pos.tp:
                    await self._close_by_trigger(ticket, pos, pos.tp, "TP hit")

    async def _close_by_trigger(self, ticket: int, pos: Position, close_price: float, reason: str) -> None:
        """Close a position due to SL/TP hit."""
        if ticket not in self._fake_positions:
            return  # Already closed (race condition guard)

        if pos.direction == "buy":
            pnl = (close_price - pos.open_price) * pos.volume * 100
        else:
            pnl = (pos.open_price - close_price) * pos.volume * 100

        self._balance += pnl
        self._realized_pnl += pnl
        del self._fake_positions[ticket]

        logger.info(
            "[DRY-RUN] %s: %s on #%d %s %s @ %.2f → P&L: $%.2f | balance: $%.2f",
            self.account_name, reason, ticket, pos.symbol, pos.direction.upper(),
            close_price, pnl, self._balance,
        )

        if self._on_position_closed:
            try:
                await self._on_position_closed(self.account_name, pos, close_price, pnl, reason)
            except Exception as exc:
                logger.error("[DRY-RUN] %s: Callback error: %s", self.account_name, exc)

    async def _check_pending_fills(self) -> None:
        """Fill pending orders when price reaches the limit."""
        for ticket in list(self._pending_orders.keys()):
            order = self._pending_orders.get(ticket)
            if not order:
                continue
            price_data = self._get_current_price(order["symbol"])
            if not price_data:
                continue
            bid, ask = price_data

            filled = False
            otype = order["order_type"]
            if otype == "buy_limit":
                filled = ask <= order["price"]
            elif otype == "sell_limit":
                filled = bid >= order["price"]
            elif otype == "buy_stop":
                filled = ask >= order["price"]
            elif otype == "sell_stop":
                filled = bid <= order["price"]

            if filled:
                self._fake_positions[ticket] = Position(
                    ticket=ticket, symbol=order["symbol"],
                    direction=order["direction"], volume=order["volume"],
                    open_price=order["price"], sl=order["sl"], tp=order["tp"],
                    profit=0.0, comment=order.get("comment", ""),
                )
                del self._pending_orders[ticket]

                logger.info(
                    "[DRY-RUN] %s: FILLED pending #%d %s %s @ %.2f",
                    self.account_name, ticket, order["symbol"],
                    order["direction"].upper(), order["price"],
                )

                if self._on_position_closed:
                    try:
                        pos = self._fake_positions[ticket]
                        await self._on_position_closed(
                            self.account_name, pos, order["price"], 0.0, "pending_filled",
                        )
                    except Exception as exc:
                        logger.error("[DRY-RUN] %s: Fill callback error: %s", self.account_name, exc)


# ═══════════════════════════════════════════════════════════════════════
# REST API BACKEND — connects to MT5 via HTTP REST server
# ═══════════════════════════════════════════════════════════════════════


class RestApiConnector(MT5Connector):
    """Connects to MT5 via a REST API server (production backend).

    The REST server runs on a Windows VPS with native MT5 access.
    For local development, the mt5-simulator Docker container provides
    the same API.
    """

    def __init__(
        self,
        account_name: str,
        server: str,
        login: int,
        password: str,
        host: str = "localhost",
        port: int = 8001,
        api_key: str = "",
        use_tls: bool = True,
        magic_number: int = 202603,
        password_env: str = "",
    ):
        super().__init__(account_name, server, login, password, magic_number=magic_number, password_env=password_env)
        self.host = host
        self.port = port
        self.api_key = api_key
        scheme = "https" if use_tls else "http"
        self._base_url = f"{scheme}://{host}:{port}"
        self._http: httpx.AsyncClient | None = None

    def _ensure_client(self) -> httpx.AsyncClient:
        """Create or return the HTTP client."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=15.0,
                headers={"X-API-Key": self.api_key},
            )
        return self._http

    async def _request(self, method: str, path: str, **kwargs) -> dict | None:
        """Make an HTTP request with retry logic. Returns parsed data or None on error."""
        client = self._ensure_client()
        last_exc = None
        for attempt in range(3):  # up to 3 attempts
            try:
                resp = await client.request(method, path, **kwargs)
                if resp.status_code == 401:
                    logger.error("%s: REST API auth failed (401)", self.account_name)
                    return None
                if resp.status_code == 503:
                    self._connected = False
                    logger.warning("%s: REST API reports not connected (503)", self.account_name)
                    return None
                body = resp.json()
                # FastAPI wraps HTTPException payloads as {"detail": {...}}.
                # Unwrap so structured error.code / error.message surface in logs
                # instead of the generic "ok=false" fallback. Without this, server-side
                # errors (e.g. SYMBOL_NOT_FOUND) appear as silent None returns.
                if isinstance(body, dict) and "detail" in body and isinstance(body["detail"], dict) and "ok" in body["detail"]:
                    body = body["detail"]
                if not body.get("ok"):
                    error = body.get("error") or {}
                    logger.warning("%s: REST API error: %s — %s", self.account_name, error.get("code"), error.get("message"))
                    return None
                return body.get("data")
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                last_exc = exc
                if attempt < 2:
                    logger.warning("%s: REST request failed (attempt %d): %s", self.account_name, attempt + 1, exc)
                    await asyncio.sleep(1)
                continue
            except Exception as exc:
                logger.error("%s: Unexpected REST error: %s", self.account_name, exc)
                return None
        logger.error("%s: REST request failed after 3 attempts: %s", self.account_name, last_exc)
        self._connected = False
        return None

    async def ping(self) -> bool:
        data = await self._request("GET", "/api/v1/ping")
        if data is None:
            return False
        return bool(data.get("alive"))

    async def connect(self, password: str | None = None) -> bool:
        pwd = password or (os.environ.get(self.password_env, "") if self.password_env else "") or self.password
        if not pwd:
            logger.error("%s: No password available for connect", self.account_name)
            return False
        data = await self._request("POST", "/api/v1/connect", json={
            "login": self.login,
            "password": pwd,
            "server": self.server,
        })
        if data and data.get("login"):
            self._connected = True
            logger.info("%s: Connected via REST API", self.account_name)
            return True
        self._connected = False
        return False

    async def disconnect(self) -> None:
        # Don't call /api/v1/disconnect — it triggers mt5.shutdown() on the server,
        # killing the entire MT5 runtime. Just reset local state; reconnect will
        # re-login via /api/v1/connect which calls mt5.login() (safe to call repeatedly).
        self._connected = False
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("%s: Disconnected (local)", self.account_name)

    async def get_price(self, symbol: str) -> tuple[float, float] | None:
        data = await self._request("GET", f"/api/v1/price/{symbol}")
        if data is None:
            return None
        return (data["bid"], data["ask"])

    async def get_account_info(self) -> AccountInfo | None:
        data = await self._request("GET", "/api/v1/account")
        if data is None:
            return None
        return AccountInfo(
            balance=data["balance"],
            equity=data["equity"],
            margin=data["margin"],
            free_margin=data["free_margin"],
            currency=data.get("currency", "USD"),
        )

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        params = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._request("GET", "/api/v1/positions", params=params)
        if data is None:
            return []
        return [
            Position(
                ticket=p["ticket"],
                symbol=p["symbol"],
                direction=p["direction"],
                volume=p["volume"],
                open_price=p["open_price"],
                sl=p["sl"],
                tp=p["tp"],
                profit=p.get("profit", 0.0),
                comment=p.get("comment", ""),
            )
            for p in data.get("positions", [])
        ]

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
        data = await self._request("POST", "/api/v1/order", json={
            "symbol": symbol,
            "order_type": order_type.value,
            "volume": volume,
            "price": price,
            "sl": sl,
            "tp": tp,
            "comment": comment,
            "magic": self.magic_number,
        })
        if data is None:
            return OrderResult(success=False, error="REST API request failed")
        if data.get("success"):
            logger.info(
                "%s: Order opened — ticket=%d price=%.2f vol=%.2f",
                self.account_name, data["ticket"], data["price"], data["volume"],
            )
            return OrderResult(
                success=True,
                ticket=data["ticket"],
                price=data["price"],
                volume=data["volume"],
            )
        return OrderResult(success=False, error=data.get("error", "Unknown error"))

    async def modify_position(
        self, ticket: int, sl: float | None = None, tp: float | None = None
    ) -> OrderResult:
        data = await self._request("PUT", f"/api/v1/position/{ticket}", json={
            "sl": sl,
            "tp": tp,
        })
        if data is None:
            return OrderResult(success=False, ticket=ticket, error="REST API request failed")
        if data.get("success"):
            return OrderResult(success=True, ticket=ticket)
        return OrderResult(success=False, ticket=ticket, error=data.get("error", "Unknown error"))

    async def close_position(self, ticket: int, volume: float | None = None) -> OrderResult:
        body = {}
        if volume is not None:
            body["volume"] = volume
        data = await self._request("DELETE", f"/api/v1/position/{ticket}", json=body if body else None)
        if data is None:
            return OrderResult(success=False, ticket=ticket, error="REST API request failed")
        if data.get("success"):
            return OrderResult(
                success=True,
                ticket=data.get("ticket", ticket),
                price=data.get("price", 0.0),
                volume=data.get("volume", 0.0),
            )
        return OrderResult(success=False, ticket=ticket, error=data.get("error", "Unknown error"))

    async def cancel_pending(self, ticket: int) -> OrderResult:
        data = await self._request("DELETE", f"/api/v1/pending-order/{ticket}")
        if data is None:
            return OrderResult(success=False, ticket=ticket, error="REST API request failed")
        if data.get("success"):
            return OrderResult(success=True, ticket=ticket)
        return OrderResult(success=False, ticket=ticket, error=data.get("error", "Unknown error"))

    async def get_pending_orders(self, symbol: str | None = None) -> list[dict]:
        params = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._request("GET", "/api/v1/pending-orders", params=params)
        if data is None:
            return []
        return data.get("orders", [])


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
    password_env = kwargs.get("password_env", "")
    if backend == "dry_run":
        return DryRunConnector(
            account_name, server, login, password,
            magic_number=magic_number, password_env=password_env,
            price_simulator=kwargs.get("price_simulator"),
            on_position_closed=kwargs.get("on_position_closed"),
            initial_balance=kwargs.get("initial_balance", 10000.0),
        )
    elif backend == "rest_api":
        return RestApiConnector(
            account_name, server, login, password,
            host=kwargs.get("mt5_host", "localhost"),
            port=kwargs.get("mt5_port", 8001),
            api_key=kwargs.get("mt5_api_key", ""),
            use_tls=kwargs.get("mt5_use_tls", True),
            magic_number=magic_number,
            password_env=password_env,
        )
    else:
        raise ValueError(f"Unknown MT5 backend: {backend}")
