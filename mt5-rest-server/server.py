"""MT5 REST API Server — wraps native MetaTrader5 Python API.

Runs on Windows VPS with a real MT5 terminal. One instance per account.
"""

import asyncio
import concurrent.futures
import functools
import logging
import secrets
from contextlib import asynccontextmanager

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


# Single dedicated worker thread for ALL MT5 calls. The MetaTrader5 C-extension
# is NOT thread-safe, so max_workers=1 serialises every call onto one thread —
# preserving the library's call ordering while moving the blocking work off the
# event loop. Without this, a single order_send/history_deals_get/order_check
# (which can block for seconds) freezes every other endpoint (/ping, /price,
# /positions) on FastAPI's single loop, causing client 15s ReadTimeouts and the
# false heartbeat-driven re-login (retcode-10027) cascade.
_mt5_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="mt5",
)


def _invoke_capture(fn, args, kwargs):
    """Run an MT5 call and atomically read mt5.last_error() on the SAME thread.

    Must not expand an empty kwargs dict: MT5's C-extension functions
    (order_check, order_send, symbol_info_tick, etc.) are METH_O and reject
    any non-NULL kwargs object, even an empty one, with
    (-2, 'Unnamed arguments not allowed'). `fn(*args, **{})` triggers that;
    `fn(*args)` does not. See diag6.py variants A vs B.

    last_error() reads MT5's global/thread-local error state. Capturing it in
    the same executor job as the call keeps the (result, error) pair coherent —
    a separate job could be interleaved with another coroutine's MT5 call on the
    shared worker thread and clobber last_error before we read it.
    """
    result = fn(*args, **kwargs) if kwargs else fn(*args)
    return result, mt5.last_error()


async def _run_err(fn, *args, **kwargs):
    """Dispatch a blocking MT5 call to the dedicated worker thread.

    Returns (result, last_error) with last_error captured atomically alongside
    the call. On an exception the call is logged and (None, None) is returned.
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _mt5_executor, functools.partial(_invoke_capture, fn, args, kwargs)
        )
    except Exception as exc:
        logger.error("MT5 call raised: %s — %s", getattr(fn, "__name__", fn), exc)
        return None, None


async def _run(fn, *args, **kwargs):
    """Dispatch a blocking MT5 call to the dedicated worker thread, returning
    only the result (last_error discarded). See _run_err for the error-aware
    variant used where mt5.last_error() must be read after the call.
    """
    result, _ = await _run_err(fn, *args, **kwargs)
    return result


# ── Filling-mode negotiation ──────────────────────────────────────


def _filling_choice(filling_mode: int, is_market: bool) -> str:
    """Pure policy: pick 'IOC' | 'FOK' | 'RETURN' from a filling_mode bitmask.

    symbol_info.filling_mode is a bitmask: bit 1 (=1) FOK, bit 2 (=2) IOC,
    bit 4 (=4) RETURN. Pending orders (is_market=False) use RETURN: market-
    execution brokers (e.g. Vantage) typically reject IOC/FOK on pendings.
    For market deals prefer IOC, then FOK, else fall back to RETURN.

    Kept free of any mt5 import so it is unit-testable without MetaTrader5.
    """
    if not is_market:
        return "RETURN"
    if filling_mode & 2:
        return "IOC"
    if filling_mode & 1:
        return "FOK"
    return "RETURN"


def _negotiate_filling(sym_info, is_market: bool):
    """Resolve _filling_choice to the concrete mt5 ORDER_FILLING_* constant.

    Shared by create_order (open) and close_position (flatten) so a symbol that
    the open path settled on FOK/RETURN is closed with the SAME supported mode —
    hard-coding IOC on close makes every bot close (incl. the kill-switch
    flatten) fail with retcode 10030 on such symbols.
    """
    filling_mode = int(sym_info.filling_mode) if sym_info is not None else 0
    return {
        "IOC": mt5.ORDER_FILLING_IOC,
        "FOK": mt5.ORDER_FILLING_FOK,
        "RETURN": mt5.ORDER_FILLING_RETURN,
    }[_filling_choice(filling_mode, is_market)]


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
        result, error = await _run_err(mt5.initialize, **init_kwargs)
    else:
        result, error = await _run_err(mt5.initialize)

    if not result:
        logger.error("MT5 initialization failed: %s", error)
    else:
        logger.info("MT5 initialized")
        # Auto-login if credentials configured
        if config.MT5_LOGIN and config.MT5_PASSWORD and config.MT5_SERVER:
            success, error = await _run_err(
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
                logger.error("MT5 login failed: %s", error)

    yield

    # Shutdown
    logger.info("Shutting down MT5...")
    await _run(mt5.shutdown)
    _mt5_executor.shutdown(wait=True)
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
    success, error = await _run_err(mt5.login, req.login, password=req.password, server=req.server)
    if not success:
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

    # Select filling mode based on what the broker/symbol actually supports.
    # Shared with close_position via _negotiate_filling so opens and closes agree.
    sym_info = await _run(mt5.symbol_info, req.symbol)
    type_filling = _negotiate_filling(sym_info, action == mt5.TRADE_ACTION_DEAL)

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
        "type_filling": type_filling,
    }

    logger.info("order_send request: %s", request)

    # Pre-flight validation — order_check returns a structured retcode that
    # explains *why* order_send would fail, instead of the generic
    # (-2, 'Unnamed arguments not allowed') that surfaces otherwise.
    check, check_err = await _run_err(mt5.order_check, request)
    if check is None:
        logger.warning("order_check returned None: last_error=%s", check_err)
    else:
        logger.info(
            "order_check: retcode=%s comment=%s margin=%s",
            check.retcode, check.comment, getattr(check, "margin", None),
        )
        if check.retcode != 0:
            return _ok({
                "success": False,
                "ticket": 0,
                "price": 0.0,
                "volume": 0.0,
                "error": f"order_check retcode={check.retcode} {check.comment}",
            })

    result, error = await _run_err(mt5.order_send, request)
    if result is None:
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
    result, error = await _run_err(mt5.order_send, request)
    if result is None:
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

    # Negotiate the SAME supported filling mode the open path used — hard-coding
    # IOC here makes every close fail with 10030 on symbols that fell back to
    # FOK/RETURN, leaving positions the bot can open but never close.
    sym_info = await _run(mt5.symbol_info, pos.symbol)
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
        "type_filling": _negotiate_filling(sym_info, True),
    }
    result, error = await _run_err(mt5.order_send, request)
    if result is None:
        _err("CLOSE_FAILED", f"Close failed: {error}")

    # Retry once with RETURN if the broker still rejects the negotiated mode.
    if (
        result.retcode == mt5.TRADE_RETCODE_INVALID_FILL
        and request["type_filling"] != mt5.ORDER_FILLING_RETURN
    ):
        request["type_filling"] = mt5.ORDER_FILLING_RETURN
        result, error = await _run_err(mt5.order_send, request)
        if result is None:
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


@app.get("/api/v1/history/deals", dependencies=[Depends(verify_api_key)])
async def get_history_deals(
    from_ts: float = Query(..., description="Unix timestamp (UTC) inclusive"),
    to_ts: float | None = Query(None, description="Unix timestamp (UTC) inclusive; defaults to now"),
):
    """Return MT5 deal history in the [from_ts, to_ts] window.

    Wraps `mt5.history_deals_get(date_from, date_to)`. Used by the bot's
    history-sync loop to reconcile broker-side closes (SL/TP hits) into
    the trades table so analytics + history P&L show the right numbers.
    """
    from datetime import datetime, timezone
    date_from = datetime.fromtimestamp(from_ts, tz=timezone.utc)
    if to_ts is None:
        date_to = datetime.now(tz=timezone.utc)
    else:
        date_to = datetime.fromtimestamp(to_ts, tz=timezone.utc)
    deals = await _run(mt5.history_deals_get, date_from, date_to)
    if deals is None:
        deals = ()
    result = [
        {
            "ticket": d.ticket,
            "order": d.order,
            "position_id": d.position_id,
            "time": d.time,             # MT5 epoch seconds (server time)
            "type": d.type,             # 0=buy, 1=sell, others=balance/credit/etc
            "entry": d.entry,           # 0=in (open), 1=out (close), 2=inout, 3=out_by
            "volume": d.volume,
            "price": d.price,
            "profit": d.profit,
            "commission": d.commission,
            "swap": d.swap,
            "symbol": d.symbol,
            "comment": d.comment,
            "magic": d.magic,
        }
        for d in deals
    ]
    return _ok({"deals": result})


@app.delete("/api/v1/pending-order/{ticket}", dependencies=[Depends(verify_api_key)])
async def cancel_pending_order(ticket: int):
    request = {
        "action": mt5.TRADE_ACTION_REMOVE,
        "order": ticket,
    }
    result, error = await _run_err(mt5.order_send, request)
    if result is None:
        _err("CANCEL_FAILED", f"Cancel failed: {error}")

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        _err("CANCEL_FAILED", f"retcode={result.retcode} {result.comment}")

    return _ok({"ticket": ticket, "cancelled": True})


# ── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=config.PORT, log_level="info")
