"""Diagnostic #4 — pinpoint which field value in the server's request dict
causes last_error=(-2, 'Unnamed arguments not allowed').

Diag3 proved a minimal dict works. Server's dict fails. Differences:
    - sl / tp are set (non-zero)
    - volume 0.16 (vs 0.01)
    - magic 202603 (vs 0)
    - server does NOT cast tick.ask to float() -> might be numpy.float64

This runs four probes, each mutating ONE aspect, to binary-search the cause.

Run:
    .\\venv\\Scripts\\python.exe diag4.py
"""

import MetaTrader5 as mt5
import numpy


def probe(label: str, request: dict) -> None:
    r = mt5.order_check(request)
    err = mt5.last_error()
    verdict = "PASS" if r is not None and r.retcode == 0 else "FAIL"
    print(f"[{verdict}] {label}")
    print(f"         last_error={err}")
    if r is None:
        print(f"         result=None")
    else:
        print(f"         retcode={r.retcode} comment={r.comment!r}")


def main() -> None:
    print(f"numpy {numpy.__version__} | MT5 {getattr(mt5, '__version__', 'n/a')}")
    print("─" * 60)

    if not mt5.initialize():
        print(f"init failed: {mt5.last_error()}")
        return
    mt5.symbol_select("XAUUSD", True)

    tick = mt5.symbol_info_tick("XAUUSD")
    if tick is None:
        print("no tick — aborting")
        mt5.shutdown()
        return

    print(f"tick.ask type: {type(tick.ask).__name__} value: {tick.ask}")
    print(f"tick.bid type: {type(tick.bid).__name__} value: {tick.bid}")
    print("─" * 60)

    ask = tick.ask  # raw (possibly numpy.float64)
    ask_native = float(tick.ask)

    # Base dict — minimal, known-good (matches diag3 Test 5)
    base = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": "XAUUSD",
        "volume": 0.01,
        "type": mt5.ORDER_TYPE_BUY,
        "price": ask_native,
        "deviation": 20,
        "magic": 0,
        "comment": "diag4",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    # Probe A: baseline (expect PASS — matches diag3)
    probe("A: baseline minimal dict, float-cast price", dict(base))

    # Probe B: use raw tick.ask (NO float cast) — numpy.float64 hypothesis
    b = dict(base)
    b["price"] = ask
    probe("B: price = tick.ask raw (no float cast)", b)

    # Probe C: add sl/tp (server includes these always)
    c = dict(base)
    c["sl"] = ask_native - 7.0
    c["tp"] = ask_native + 20.0
    probe("C: + sl/tp as native floats", c)

    # Probe D: sl/tp with raw numpy-style values (tick arithmetic)
    d = dict(base)
    d["sl"] = ask - 7.0   # could produce numpy.float64 if ask is numpy
    d["tp"] = ask + 20.0
    probe("D: + sl/tp derived from raw tick.ask", d)

    # Probe E: server-shaped volume and magic
    e = dict(base)
    e["volume"] = 0.16
    e["magic"] = 202603
    e["comment"] = "telebot"
    probe("E: volume=0.16, magic=202603, comment=telebot", e)

    # Probe F: full server-shaped dict — everything combined with NATIVE casts
    f = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": "XAUUSD",
        "volume": 0.16,
        "type": mt5.ORDER_TYPE_BUY,
        "price": ask_native,
        "sl": ask_native - 7.0,
        "tp": ask_native + 20.0,
        "deviation": 20,
        "magic": 202603,
        "comment": "telebot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    probe("F: full server-shaped, ALL native floats", f)

    # Probe G: same as F but with RAW tick.ask (simulates server bug if any)
    g = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": "XAUUSD",
        "volume": 0.16,
        "type": mt5.ORDER_TYPE_BUY,
        "price": ask,
        "sl": ask - 7.0,
        "tp": ask + 20.0,
        "deviation": 20,
        "magic": 202603,
        "comment": "telebot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    probe("G: full server-shaped, RAW tick.ask (unsafe)", g)

    mt5.shutdown()

    print("\n─ Interpretation ─")
    print("  If A passes and B fails -> numpy.float64 leaks via tick.ask are the cause.")
    print("  If A/B pass but C fails -> sl/tp values are the trigger.")
    print("  If A-E pass and F fails -> interaction effect.")
    print("  If F passes but G fails -> confirms float() cast is the fix.")


if __name__ == "__main__":
    main()
