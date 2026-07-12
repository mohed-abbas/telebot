"""Unit tests for the MT5 REST bridge filling-mode negotiation (audit §4.4)
and the threaded _run dispatch helpers (audit §4.3).

mt5-rest-server/server.py can only be imported on a host with MetaTrader5,
FastAPI, pydantic and python-dotenv installed (the Windows VPS / test
container). To keep the *pure* logic testable anywhere, this module injects
minimal stand-ins for those import dependencies into sys.modules, imports
server, exercises the pure helpers, then restores sys.modules.

Covers:
  * _filling_choice — the pure IOC/FOK/RETURN policy (no mt5 needed).
  * _negotiate_filling — resolves the policy to mt5 ORDER_FILLING_* constants
    and is shared by BOTH create_order (open) and close_position (close), so a
    symbol whose open fell back to FOK/RETURN is closed with the SAME mode
    (regression guard for the hard-coded IOC-on-close that produced 10030).
  * _run / _run_err — verifies the blocking MT5 call runs off the event loop on
    a single dedicated worker thread and that last_error is captured atomically.
"""
import asyncio
import importlib
import os
import sys
import threading
import types

import pytest

_SERVER_DIR = os.path.join(os.path.dirname(__file__), "..", "mt5-rest-server")


def _fake_mt5():
    m = types.ModuleType("MetaTrader5")
    # Constants referenced at server import time (ORDER_TYPE_MAP).
    m.ORDER_TYPE_BUY = 0
    m.ORDER_TYPE_SELL = 1
    m.ORDER_TYPE_BUY_LIMIT = 2
    m.ORDER_TYPE_SELL_LIMIT = 3
    m.ORDER_TYPE_BUY_STOP = 4
    m.ORDER_TYPE_SELL_STOP = 5
    m.TRADE_ACTION_DEAL = 1
    m.TRADE_ACTION_PENDING = 5
    m.TRADE_ACTION_SLTP = 6
    m.TRADE_ACTION_REMOVE = 7
    m.ORDER_TIME_GTC = 0
    m.TRADE_RETCODE_DONE = 10009
    m.TRADE_RETCODE_INVALID_FILL = 10030
    # Filling constants — distinct sentinels so we can assert the mapping.
    m.ORDER_FILLING_FOK = "FOK_CONST"
    m.ORDER_FILLING_IOC = "IOC_CONST"
    m.ORDER_FILLING_RETURN = "RETURN_CONST"
    m.last_error = lambda: (0, "ok")
    return m


def _fake_fastapi():
    m = types.ModuleType("fastapi")

    class _App:
        def __init__(self, *a, **k):
            pass

        def _dec(self, *a, **k):
            def wrap(fn):
                return fn
            return wrap

        get = post = put = delete = _dec

    class HTTPException(Exception):
        def __init__(self, *a, **k):
            super().__init__()

    m.FastAPI = _App
    m.Depends = lambda *a, **k: None
    m.Header = lambda *a, **k: None
    m.Query = lambda *a, **k: None
    m.HTTPException = HTTPException
    m.Request = object
    return m


def _fake_pydantic():
    m = types.ModuleType("pydantic")

    class BaseModel:
        pass

    m.BaseModel = BaseModel
    return m


def _fake_config():
    m = types.ModuleType("config")
    m.API_KEY = "test"
    m.MT5_LOGIN = 0
    m.MT5_PASSWORD = ""
    m.MT5_SERVER = ""
    m.MT5_TERMINAL_PATH = ""
    m.MT5_MAGIC_NUMBER = 202603
    m.PORT = 8001
    return m


@pytest.fixture(scope="module")
def server():
    """Import mt5-rest-server/server.py with stubbed deps; restore after."""
    stubs = {
        "MetaTrader5": _fake_mt5(),
        "fastapi": _fake_fastapi(),
        "pydantic": _fake_pydantic(),
        "config": _fake_config(),
    }
    saved = {name: sys.modules.get(name) for name in list(stubs) + ["server"]}
    sys.modules.update(stubs)
    sys.modules.pop("server", None)
    sys.path.insert(0, _SERVER_DIR)
    try:
        mod = importlib.import_module("server")
        yield mod
    finally:
        if _SERVER_DIR in sys.path:
            sys.path.remove(_SERVER_DIR)
        for name, orig in saved.items():
            if orig is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = orig
        # Release the dedicated MT5 worker thread created at import.
        try:
            mod._mt5_executor.shutdown(wait=False)
        except Exception:
            pass


# ── §4.4 filling-mode negotiation ─────────────────────────────────


@pytest.mark.parametrize(
    "bitmask, is_market, expected",
    [
        # Market deals: prefer IOC (bit 2), then FOK (bit 1), else RETURN.
        (0b010, True, "IOC"),   # IOC only
        (0b011, True, "IOC"),   # FOK+IOC -> IOC wins
        (0b111, True, "IOC"),   # all -> IOC
        (0b001, True, "FOK"),   # FOK only
        (0b101, True, "FOK"),   # FOK+RETURN, no IOC -> FOK
        (0b100, True, "RETURN"),  # RETURN only
        (0b000, True, "RETURN"),  # nothing advertised -> RETURN
        # Pending orders always negotiate RETURN regardless of the bitmask.
        (0b010, False, "RETURN"),
        (0b011, False, "RETURN"),
        (0b111, False, "RETURN"),
        (0b000, False, "RETURN"),
    ],
)
def test_filling_choice_policy(server, bitmask, is_market, expected):
    assert server._filling_choice(bitmask, is_market) == expected


def test_negotiate_filling_maps_to_mt5_constants(server):
    sym = types.SimpleNamespace(filling_mode=0b010)  # IOC supported
    assert server._negotiate_filling(sym, True) == "IOC_CONST"

    sym = types.SimpleNamespace(filling_mode=0b001)  # FOK only
    assert server._negotiate_filling(sym, True) == "FOK_CONST"

    sym = types.SimpleNamespace(filling_mode=0b100)  # RETURN only
    assert server._negotiate_filling(sym, True) == "RETURN_CONST"


def test_negotiate_filling_close_matches_fok_open(server):
    """Regression for §4.4: a FOK-only symbol must be CLOSED with FOK, not the
    old hard-coded IOC (which produced retcode 10030 on every close)."""
    fok_only = types.SimpleNamespace(filling_mode=0b001)
    # A market close is is_market=True, same as the open path for market deals.
    assert server._negotiate_filling(fok_only, True) == server.mt5.ORDER_FILLING_FOK
    # And crucially NOT the old hard-coded IOC.
    assert server._negotiate_filling(fok_only, True) != server.mt5.ORDER_FILLING_IOC


def test_negotiate_filling_none_sym_info_defaults_return(server):
    # symbol_info() came back None -> bitmask treated as 0 -> RETURN.
    assert server._negotiate_filling(None, True) == "RETURN_CONST"
    assert server._negotiate_filling(None, False) == "RETURN_CONST"


# ── §4.3 threaded dispatch ────────────────────────────────────────


async def test_run_executes_on_dedicated_worker_thread(server):
    """_run must NOT run the blocking MT5 call on the event-loop thread."""
    main_thread = threading.current_thread().name
    seen = {}

    def blocking_call(x):
        seen["thread"] = threading.current_thread().name
        return x * 2

    result = await server._run(blocking_call, 21)
    assert result == 42
    assert seen["thread"] != main_thread
    # Single dedicated worker -> named by the executor's thread_name_prefix.
    assert seen["thread"].startswith("mt5")


async def test_run_err_captures_last_error_atomically(server, monkeypatch):
    """_run_err returns (result, last_error) with last_error read on the SAME
    worker thread as the call."""
    err_thread = {}

    def failing_call():
        return None

    def fake_last_error():
        err_thread["thread"] = threading.current_thread().name
        return (-4, "boom")

    monkeypatch.setattr(server.mt5, "last_error", fake_last_error)

    result, error = await server._run_err(failing_call)
    assert result is None
    assert error == (-4, "boom")
    # last_error was read on the worker thread, not the main/event-loop thread.
    assert err_thread["thread"].startswith("mt5")


async def test_run_swallows_exception_returns_none(server):
    def boom():
        raise RuntimeError("mt5 blew up")

    assert await server._run(boom) is None


async def test_run_no_kwargs_avoids_empty_kwargs_expansion(server):
    """METH_O guard: with no kwargs, fn must be called as fn(*args), never
    fn(*args, **{})."""
    def only_positional(a, b):
        return a + b

    assert await server._run(only_positional, 2, 3) == 5
