"""FastAPI app that simulates the MetaTrader5 REST API."""

import os
import random
import secrets
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import SimulatorState

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("MT5_API_KEY", "dev-key")
INITIAL_BALANCE = float(os.environ.get("SIMULATOR_BALANCE", "10000.0"))
PRICE_MODE = os.environ.get("SIMULATOR_PRICE_MODE", "static")

STATIC_PRICES: dict[str, dict[str, float]] = {
    "XAUUSD": {"bid": 2345.67, "ask": 2345.87, "spread": 0.20},
}

MARKET_ORDER_TYPES = {"market_buy", "market_sell"}
PENDING_ORDER_TYPES = {"buy_limit", "sell_limit", "buy_stop", "sell_stop"}
ALL_ORDER_TYPES = MARKET_ORDER_TYPES | PENDING_ORDER_TYPES

# ---------------------------------------------------------------------------
# Global state – reset on each startup
# ---------------------------------------------------------------------------

state: SimulatorState
_random_walk_prices: dict[str, dict[str, float]] = {}


def _init_state() -> None:
    global state, _random_walk_prices
    state = SimulatorState(initial_balance=INITIAL_BALANCE)
    # Seed random walk prices from the static table
    _random_walk_prices = {
        sym: {"bid": v["bid"], "ask": v["ask"], "spread": v["spread"]}
        for sym, v in STATIC_PRICES.items()
    }


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(application: FastAPI):
    _init_state()
    yield


app = FastAPI(title="MT5 Simulator", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _error(code: str, message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"ok": False, "data": None, "error": {"code": code, "message": message}},
    )


def _get_price(symbol: str) -> Optional[tuple[float, float]]:
    """Return (bid, ask) for *symbol*, or None if unknown."""
    mode = os.environ.get("SIMULATOR_PRICE_MODE", PRICE_MODE)
    if mode == "random_walk":
        if symbol not in _random_walk_prices:
            return None
        entry = _random_walk_prices[symbol]
        entry["bid"] += random.gauss(0, 0.5)
        entry["ask"] = entry["bid"] + entry["spread"]
        return (round(entry["bid"], 2), round(entry["ask"], 2))
    else:
        # static
        if symbol not in STATIC_PRICES:
            return None
        p = STATIC_PRICES[symbol]
        return (p["bid"], p["ask"])


def _get_price_for_state(symbol: str) -> Optional[tuple[float, float]]:
    """Wrapper suitable for passing to SimulatorState methods."""
    return _get_price(symbol)


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Re-read key each request so tests can override the env var
    api_key = os.environ.get("MT5_API_KEY", "dev-key")
    provided = request.headers.get("X-API-Key", "")
    if not secrets.compare_digest(provided, api_key):
        return JSONResponse(
            status_code=401,
            content={
                "ok": False,
                "data": None,
                "error": {"code": "UNAUTHORIZED", "message": "Invalid or missing API key"},
            },
        )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ConnectRequest(BaseModel):
    login: int
    password: str
    server: str


class OrderRequest(BaseModel):
    symbol: str
    order_type: str
    volume: float
    price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    comment: str = ""
    magic: int = 0


class ModifyPositionRequest(BaseModel):
    sl: Optional[float] = None
    tp: Optional[float] = None


class ClosePositionRequest(BaseModel):
    volume: Optional[float] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

PREFIX = "/api/v1"


@app.get(f"{PREFIX}/ping")
async def ping():
    return _ok({"alive": True, "terminal_connected": state.connected})


@app.post(f"{PREFIX}/connect")
async def connect(body: ConnectRequest):
    state.connected = True
    state.login = body.login
    state.server = body.server
    return _ok({"connected": True})


@app.post(f"{PREFIX}/disconnect")
async def disconnect():
    state.connected = False
    return _ok({"connected": False})


@app.get(f"{PREFIX}/price/{{symbol}}")
async def get_price(symbol: str):
    price_data = _get_price(symbol)
    if price_data is None:
        return _error("SYMBOL_NOT_FOUND", f"Symbol '{symbol}' is not available", status=404)
    bid, ask = price_data
    return _ok({"symbol": symbol, "bid": bid, "ask": ask})


@app.get(f"{PREFIX}/account")
async def get_account():
    equity = state.calculate_equity(_get_price_for_state)
    margin = state.calculate_margin(_get_price_for_state)
    free_margin = equity - margin
    return _ok({
        "balance": round(state.balance, 2),
        "equity": round(equity, 2),
        "margin": round(margin, 2),
        "free_margin": round(free_margin, 2),
        "currency": state.currency,
    })


@app.get(f"{PREFIX}/positions")
async def get_positions(symbol: Optional[str] = Query(None)):
    positions = list(state.positions.values())
    if symbol:
        positions = [p for p in positions if p.symbol == symbol]
    # Refresh profit for each position
    result = []
    for pos in positions:
        pnl = state._position_pnl(pos, _get_price_for_state)
        result.append({
            "ticket": pos.ticket,
            "symbol": pos.symbol,
            "direction": pos.direction,
            "volume": pos.volume,
            "open_price": pos.open_price,
            "sl": pos.sl,
            "tp": pos.tp,
            "profit": round(pnl, 2),
            "comment": pos.comment,
        })
    return _ok({"positions": result})


@app.post(f"{PREFIX}/order")
async def create_order(body: OrderRequest):
    if body.order_type not in ALL_ORDER_TYPES:
        return _error("INVALID_ORDER_TYPE", f"Unknown order type '{body.order_type}'")

    if body.volume > 100:
        return _error("ORDER_REJECTED", "Volume exceeds maximum of 100 lots")

    price_data = _get_price(body.symbol)
    if price_data is None:
        return _error("SYMBOL_NOT_FOUND", f"Symbol '{body.symbol}' is not available", status=404)

    bid, ask = price_data

    if body.order_type in MARKET_ORDER_TYPES:
        # Market order – fill immediately
        if body.order_type == "market_buy":
            fill_price = ask
            direction = "buy"
        else:
            fill_price = bid
            direction = "sell"

        ticket = state.next_ticket()
        from state import SimulatedPosition

        pos = SimulatedPosition(
            ticket=ticket,
            symbol=body.symbol,
            direction=direction,
            volume=body.volume,
            open_price=fill_price,
            sl=body.sl,
            tp=body.tp,
            comment=body.comment,
            magic=body.magic,
        )
        state.positions[ticket] = pos
        return _ok({
            "success": True,
            "ticket": ticket,
            "price": fill_price,
            "volume": body.volume,
            "error": "",
        })
    else:
        # Pending order
        ticket = state.next_ticket()
        from state import SimulatedPendingOrder

        order = SimulatedPendingOrder(
            ticket=ticket,
            symbol=body.symbol,
            order_type=body.order_type,
            volume=body.volume,
            price=body.price,
            sl=body.sl,
            tp=body.tp,
            comment=body.comment,
            magic=body.magic,
        )
        state.pending_orders[ticket] = order
        return _ok({
            "success": True,
            "ticket": ticket,
            "price": body.price,
            "volume": body.volume,
            "error": "",
        })


@app.put(f"{PREFIX}/position/{{ticket}}")
async def modify_position(ticket: int, body: ModifyPositionRequest):
    pos = state.positions.get(ticket)
    if pos is None:
        return _error("POSITION_NOT_FOUND", f"Position {ticket} not found", status=404)

    if body.sl is not None:
        pos.sl = body.sl
    if body.tp is not None:
        pos.tp = body.tp

    return _ok({"success": True, "ticket": ticket, "error": ""})


@app.delete(f"{PREFIX}/position/{{ticket}}")
async def close_position(ticket: int, body: ClosePositionRequest = ClosePositionRequest()):
    pos = state.positions.get(ticket)
    if pos is None:
        return _error("POSITION_NOT_FOUND", f"Position {ticket} not found", status=404)

    price_data = _get_price(pos.symbol)
    if price_data is None:
        return _error("SYMBOL_NOT_FOUND", f"Symbol '{pos.symbol}' is not available", status=404)

    bid, ask = price_data
    close_price = bid if pos.direction == "buy" else ask

    requested_volume = body.volume if body.volume is not None else pos.volume

    if requested_volume >= pos.volume:
        # Full close
        pnl = state._position_pnl(pos, _get_price_for_state)
        state.balance += pnl
        closed_volume = pos.volume
        del state.positions[ticket]
    else:
        # Partial close – calculate P&L on the closed portion
        from state import GOLD_CONTRACT_SIZE

        if pos.direction == "buy":
            pnl = (close_price - pos.open_price) * requested_volume * GOLD_CONTRACT_SIZE
        else:
            pnl = (pos.open_price - close_price) * requested_volume * GOLD_CONTRACT_SIZE
        state.balance += pnl
        pos.volume = round(pos.volume - requested_volume, 8)
        closed_volume = requested_volume

    return _ok({
        "success": True,
        "ticket": ticket,
        "price": close_price,
        "volume": closed_volume,
        "error": "",
    })


@app.get(f"{PREFIX}/pending-orders")
async def get_pending_orders(symbol: Optional[str] = Query(None)):
    orders = list(state.pending_orders.values())
    if symbol:
        orders = [o for o in orders if o.symbol == symbol]
    result = [
        {
            "ticket": o.ticket,
            "symbol": o.symbol,
            "type": o.order_type,
            "volume": o.volume,
            "price": o.price,
            "sl": o.sl,
            "tp": o.tp,
        }
        for o in orders
    ]
    return _ok({"orders": result})


@app.delete(f"{PREFIX}/pending-order/{{ticket}}")
async def cancel_pending_order(ticket: int):
    if ticket not in state.pending_orders:
        return _error("ORDER_NOT_FOUND", f"Pending order {ticket} not found", status=404)
    del state.pending_orders[ticket]
    return _ok({"success": True, "ticket": ticket, "error": ""})
