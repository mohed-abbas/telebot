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
# DRY-RUN BACKEND — logs everything, executes nothing
# ═══════════════════════════════════════════════════════════════════════


class DryRunConnector(MT5Connector):
    """Simulates MT5 connection for testing. No real trades placed."""

    _fake_positions: dict[int, Position]

    def __init__(self, account_name: str, server: str, login: int, password: str,
                 magic_number: int = 202603, password_env: str = ""):
        super().__init__(account_name, server, login, password, magic_number=magic_number, password_env=password_env)
        self._ticket_counter = 100000
        self._fake_positions = {}

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
        self._ticket_counter += 1
        ticket = self._ticket_counter
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
                if not body.get("ok"):
                    error = body.get("error", {})
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
        if data and data.get("connected"):
            self._connected = True
            self._clear_password()
            logger.info("%s: Connected via REST API", self.account_name)
            return True
        self._connected = False
        return False

    async def disconnect(self) -> None:
        await self._request("POST", "/api/v1/disconnect")
        self._connected = False
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("%s: Disconnected", self.account_name)

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
        return DryRunConnector(account_name, server, login, password, magic_number=magic_number, password_env=password_env)
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
