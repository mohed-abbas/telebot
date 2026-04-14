"""MT5 REST API Server — wraps native MetaTrader5 Python API.

Runs on Windows VPS with a real MT5 terminal. One instance per account.
"""

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from functools import partial

import MetaTrader5 as mt5
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel

import config

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# ── Request/Response Models ───────────────────────────────────────


class ConnectRequest(BaseModel):
    login: int
    password: str
    server: str


class OrderRequest(BaseModel):
    symbol: str
    order_type: str  # "market_buy", "market_sell", "buy_limit", etc.
    volume: float
    price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    comment: str = ""
    magic: int = 0


class ModifyRequest(BaseModel):
    sl: float | None = None
    tp: float | None = None


class CloseRequest(BaseModel):
    volume: float | None = None


# ── Helpers ───────────────────────────────────────────────────────


def _ok(data: dict) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(code: str, message: str, status: int = 400) -> dict:
    raise HTTPException(
        status_code=status,
        detail={
            "ok": False,
            "data": None,
            "error": {"code": code, "message": message},
        },
    )


async def _run(fn, *args, **kwargs):
    """Run a blocking MT5 function in a thread pool with timeout."""
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, partial(fn, *args, **kwargs)),
            timeout=10.0,
        )
    except asyncio.TimeoutError:
        logger.error("MT5 call timed out: %s", fn.__name__)
        return None


# ── Auth ──────────────────────────────────────────────────────────


async def verify_api_key(x_api_key: str = Header(...)):
    if not config.API_KEY or not secrets.compare_digest(x_api_key, config.API_KEY):
        raise HTTPException(
            status_code=401,
            detail={
                "ok": False,
                "data": None,
                "error": {"code": "AUTH_FAILED", "message": "Invalid API key"},
            },
        )


# ── Order Type Mapping ────────────────────────────────────────────

ORDER_TYPE_MAP = {
    "market_buy": (mt5.ORDER_TYPE_BUY, mt5.TRADE_ACTION_DEAL),
    "market_sell": (mt5.ORDER_TYPE_SELL, mt5.TRADE_ACTION_DEAL),
    "buy_limit": (mt5.ORDER_TYPE_BUY_LIMIT, mt5.TRADE_ACTION_PENDING),
    "sell_limit": (mt5.ORDER_TYPE_SELL_LIMIT, mt5.TRADE_ACTION_PENDING),
    "buy_stop": (mt5.ORDER_TYPE_BUY_STOP, mt5.TRADE_ACTION_PENDING),
    "sell_stop": (mt5.ORDER_TYPE_SELL_STOP, mt5.TRADE_ACTION_PENDING),
}


# ── Lifespan ──────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize MT5
    logger.info("Initializing MT5 terminal...")
    init_kwargs = {}
    if config.MT5_TERMINAL_PATH:
        init_kwargs["path"] = config.MT5_TERMINAL_PATH

    if init_kwargs:
        result = await _run(mt5.initialize, **init_kwargs)
    else:
        result = await _run(mt5.initialize)

    if not result:
        error = mt5.last_error()
        logger.error("MT5 initialization failed: %s", error)
    else:
        logger.info("MT5 initialized")
        # Auto-login if credentials configured
        if config.MT5_LOGIN and config.MT5_PASSWORD and config.MT5_SERVER:
            success = await _run(
                mt5.login,
                config.MT5_LOGIN,
                password=config.MT5_PASSWORD,
                server=config.MT5_SERVER,
            )
            if success:
                info = await _run(mt5.account_info)
                if info:
                    logger.info(
                        "MT5 logged in — balance=%.2f equity=%.2f",
                        info.balance,
                        info.equity,
                    )
            else:
                error = mt5.last_error()
                logger.error("MT5 login failed: %s", error)

    yield

    # Shutdown
    logger.info("Shutting down MT5...")
    await _run(mt5.shutdown)
    logger.info("MT5 shutdown complete")


app = FastAPI(
    title="MT5 REST Server",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


# ── Endpoints ─────────────────────────────────────────────────────


@app.get("/api/v1/ping")
async def ping():
    info = await _run(mt5.terminal_info)
    alive = info is not None and info.connected
    return _ok({"alive": alive})


@app.post("/api/v1/connect", dependencies=[Depends(verify_api_key)])
async def connect(req: ConnectRequest):
    success = await _run(mt5.login, req.login, password=req.password, server=req.server)
    if not success:
        error = mt5.last_error()
        _err("LOGIN_FAILED", f"MT5 login failed: {error}")
    info = await _run(mt5.account_info)
    if info is None:
        _err("NOT_CONNECTED", "Login succeeded but cannot get account info", 503)
    return _ok({
        "login": info.login,
        "server": info.server,
        "balance": info.balance,
        "equity": info.equity,
    })


@app.post("/api/v1/disconnect", dependencies=[Depends(verify_api_key)])
async def disconnect():
    await _run(mt5.shutdown)
    return _ok({"disconnected": True})


@app.get("/api/v1/price/{symbol}", dependencies=[Depends(verify_api_key)])
async def get_price(symbol: str):
    await _run(mt5.symbol_select, symbol, True)
    tick = await _run(mt5.symbol_info_tick, symbol)
    if tick is None:
        _err("SYMBOL_NOT_FOUND", f"Symbol {symbol} not found", 404)
    return _ok({"symbol": symbol, "bid": tick.bid, "ask": tick.ask})


@app.get("/api/v1/account", dependencies=[Depends(verify_api_key)])
async def get_account():
    info = await _run(mt5.account_info)
    if info is None:
        _err("NOT_CONNECTED", "Cannot get account info", 503)
    return _ok({
        "balance": info.balance,
        "equity": info.equity,
        "margin": info.margin,
        "free_margin": info.margin_free,
        "currency": info.currency,
    })


@app.get("/api/v1/positions", dependencies=[Depends(verify_api_key)])
async def get_positions(symbol: str | None = Query(None)):
    if symbol:
        raw = await _run(mt5.positions_get, symbol=symbol)
    else:
        raw = await _run(mt5.positions_get)
    if raw is None:
        raw = ()
    positions = [
        {
            "ticket": p.ticket,
            "symbol": p.symbol,
            "direction": "buy" if p.type == 0 else "sell",
            "volume": p.volume,
            "open_price": p.price_open,
            "sl": p.sl,
            "tp": p.tp,
            "profit": p.profit,
            "comment": p.comment,
        }
        for p in raw
    ]
    return _ok({"positions": positions})


@app.post("/api/v1/order", dependencies=[Depends(verify_api_key)])
async def create_order(req: OrderRequest):
    if req.order_type not in ORDER_TYPE_MAP:
        _err("INVALID_ORDER_TYPE", f"Unknown order type: {req.order_type}")

    mt5_type, action = ORDER_TYPE_MAP[req.order_type]

    # Ensure the symbol is selected in Market Watch before order_send.
    # Without this, MT5's C-extension parameter validation rejects the request
    # with (-2, 'Unnamed arguments not allowed'). Applies to both market and
    # pending orders — market branch only incidentally activated via symbol_info_tick.
    await _run(mt5.symbol_select, req.symbol, True)

    # For market orders, get fill price
    if action == mt5.TRADE_ACTION_DEAL:
        tick = await _run(mt5.symbol_info_tick, req.symbol)
        if tick is None:
            _err("SYMBOL_NOT_FOUND", f"Cannot get price for {req.symbol}", 404)
        price = tick.ask if "buy" in req.order_type else tick.bid
    else:
        price = req.price

    request = {
        "action": action,
        "symbol": req.symbol,
        "volume": req.volume,
        "type": mt5_type,
        "price": price,
        "sl": req.sl,
        "tp": req.tp,
        "deviation": 20,
        "magic": req.magic or config.MT5_MAGIC_NUMBER,
        "comment": req.comment or "telebot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = await _run(mt5.order_send, request)
    if result is None:
        error = mt5.last_error()
        return _ok({
            "success": False,
            "ticket": 0,
            "price": 0.0,
            "volume": 0.0,
            "error": str(error),
        })

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return _ok({
            "success": False,
            "ticket": 0,
            "price": 0.0,
            "volume": 0.0,
            "error": f"retcode={result.retcode} {result.comment}",
        })

    return _ok({
        "success": True,
        "ticket": result.order,
        "price": result.price,
        "volume": result.volume,
        "error": "",
    })


@app.put("/api/v1/position/{ticket}", dependencies=[Depends(verify_api_key)])
async def modify_position(ticket: int, req: ModifyRequest):
    positions = await _run(mt5.positions_get, ticket=ticket)
    if not positions:
        _err("POSITION_NOT_FOUND", f"Position {ticket} not found", 404)
    pos = positions[0]

    await _run(mt5.symbol_select, pos.symbol, True)

    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol": pos.symbol,
        "sl": req.sl if req.sl is not None else pos.sl,
        "tp": req.tp if req.tp is not None else pos.tp,
    }
    result = await _run(mt5.order_send, request)
    if result is None:
        error = mt5.last_error()
        _err("MODIFY_FAILED", f"Modify failed: {error}")

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        _err("MODIFY_FAILED", f"retcode={result.retcode} {result.comment}")

    return _ok({"ticket": ticket, "sl": request["sl"], "tp": request["tp"]})


@app.delete("/api/v1/position/{ticket}", dependencies=[Depends(verify_api_key)])
async def close_position(ticket: int, req: CloseRequest = None):
    if req is None:
        req = CloseRequest()

    positions = await _run(mt5.positions_get, ticket=ticket)
    if not positions:
        _err("POSITION_NOT_FOUND", f"Position {ticket} not found", 404)
    pos = positions[0]

    close_volume = req.volume if req.volume and req.volume < pos.volume else pos.volume
    close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY

    await _run(mt5.symbol_select, pos.symbol, True)

    tick = await _run(mt5.symbol_info_tick, pos.symbol)
    if tick is None:
        _err("SYMBOL_NOT_FOUND", f"Cannot get price for {pos.symbol}", 404)
    close_price = tick.bid if pos.type == 0 else tick.ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol": pos.symbol,
        "volume": close_volume,
        "type": close_type,
        "price": close_price,
        "deviation": 20,
        "magic": config.MT5_MAGIC_NUMBER,
        "comment": "telebot_close",
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = await _run(mt5.order_send, request)
    if result is None:
        error = mt5.last_error()
        _err("CLOSE_FAILED", f"Close failed: {error}")

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        _err("CLOSE_FAILED", f"retcode={result.retcode} {result.comment}")

    return _ok({
        "ticket": ticket,
        "closed_volume": close_volume,
        "price": result.price,
    })


@app.get("/api/v1/pending-orders", dependencies=[Depends(verify_api_key)])
async def get_pending_orders(symbol: str | None = Query(None)):
    if symbol:
        orders = await _run(mt5.orders_get, symbol=symbol)
    else:
        orders = await _run(mt5.orders_get)
    if orders is None:
        orders = ()
    result = [
        {
            "ticket": o.ticket,
            "symbol": o.symbol,
            "type": o.type,
            "volume": o.volume_current,
            "price": o.price_open,
            "sl": o.sl,
            "tp": o.tp,
            "comment": o.comment,
        }
        for o in orders
    ]
    return _ok({"orders": result})


@app.delete("/api/v1/pending-order/{ticket}", dependencies=[Depends(verify_api_key)])
async def cancel_pending_order(ticket: int):
    request = {
        "action": mt5.TRADE_ACTION_REMOVE,
        "order": ticket,
    }
    result = await _run(mt5.order_send, request)
    if result is None:
        error = mt5.last_error()
        _err("CANCEL_FAILED", f"Cancel failed: {error}")

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        _err("CANCEL_FAILED", f"retcode={result.retcode} {result.comment}")

    return _ok({"ticket": ticket, "cancelled": True})


# ── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=config.PORT, log_level="info")
