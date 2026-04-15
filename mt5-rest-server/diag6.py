"""Diagnostic #6 — reproduce the -2 error inside a minimal uvicorn app.

diag5 (standalone Python) works. server.py (uvicorn + FastAPI) fails.
This minimal app mirrors server.py's lifespan + handler shape. It tests
FOUR variants of the same order_check call to pinpoint what specifically
breaks under uvicorn:

    A. Direct sync call inside async handler:
       `check = mt5.order_check(request)`
    B. Via `await _run(...)` wrapper (what server.py uses):
       `check = await _run(mt5.order_check, request)`
    C. Via asyncio.to_thread (offload to threadpool):
       `check = await asyncio.to_thread(mt5.order_check, request)`
    D. Via loop.run_in_executor with None (default executor):
       `check = await loop.run_in_executor(None, mt5.order_check, request)`

Run in one terminal on the VPS:
    # Stop the real server first to free port/MT5 attachment
    Get-NetTCPConnection -LocalPort 8001 -State Listen -EA SilentlyContinue |
      Select -ExpandProperty OwningProcess -Unique |
      Where { $_ -ne 0 } | ForEach { Stop-Process -Id $_ -Force }

    .\\venv\\Scripts\\python.exe diag6.py

In another terminal, hit each endpoint:
    curl http://127.0.0.1:8002/A
    curl http://127.0.0.1:8002/B
    curl http://127.0.0.1:8002/C
    curl http://127.0.0.1:8002/D

Each response is JSON: {"variant": "A", "result": "...", "last_error": "..."}.

Whichever variant returns retcode=0 'Done' is the one we must use in server.py.
"""

import asyncio
import threading
from contextlib import asynccontextmanager

import MetaTrader5 as mt5
from fastapi import FastAPI

import config


async def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return None


def _build_request() -> dict:
    mt5.symbol_select("XAUUSD", True)
    tick = mt5.symbol_info_tick("XAUUSD")
    return {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": "XAUUSD",
        "volume": 0.01,
        "type": mt5.ORDER_TYPE_BUY,
        "price": float(tick.ask),
        "deviation": 20,
        "magic": 202603,
        "comment": "diag6",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }


def _format(variant: str, result, err, thread_name: str) -> dict:
    return {
        "variant": variant,
        "thread": thread_name,
        "result": repr(result),
        "last_error": repr(err),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_kwargs = {}
    if config.MT5_TERMINAL_PATH:
        init_kwargs["path"] = config.MT5_TERMINAL_PATH
    ok = mt5.initialize(**init_kwargs) if init_kwargs else mt5.initialize()
    print(f"init={ok} thread={threading.current_thread().name} err={mt5.last_error()}")

    if ok and config.MT5_LOGIN and config.MT5_PASSWORD and config.MT5_SERVER:
        ok2 = mt5.login(
            config.MT5_LOGIN,
            password=config.MT5_PASSWORD,
            server=config.MT5_SERVER,
        )
        print(f"login={ok2} thread={threading.current_thread().name} err={mt5.last_error()}")

    yield
    mt5.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/A")
async def variant_a():
    req = _build_request()
    result = mt5.order_check(req)
    err = mt5.last_error()
    return _format("A_direct_sync", result, err, threading.current_thread().name)


@app.get("/B")
async def variant_b():
    req = _build_request()
    result = await _run(mt5.order_check, req)
    err = mt5.last_error()
    return _format("B_via_run_wrapper", result, err, threading.current_thread().name)


@app.get("/C")
async def variant_c():
    req = _build_request()
    result = await asyncio.to_thread(mt5.order_check, req)
    err = mt5.last_error()
    return _format("C_asyncio_to_thread", result, err, threading.current_thread().name)


@app.get("/D")
async def variant_d():
    req = _build_request()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, mt5.order_check, req)
    err = mt5.last_error()
    return _format("D_run_in_executor", result, err, threading.current_thread().name)


@app.get("/threads")
async def show_threads():
    return {
        "handler_thread": threading.current_thread().name,
        "ident": threading.get_ident(),
        "main_thread": threading.main_thread().name,
        "main_ident": threading.main_thread().ident,
    }


if __name__ == "__main__":
    import uvicorn

    print(f"main thread: {threading.current_thread().name} ident={threading.get_ident()}")
    uvicorn.run("diag6:app", host="127.0.0.1", port=8002, log_level="info")
