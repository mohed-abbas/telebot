"""Diagnostic #2 — verify init-in-executor pattern.

Tests whether mt5.initialize() + mt5.order_check() running on the SAME
dedicated worker thread succeeds. This matches the pattern the REST
server uses (single ThreadPoolExecutor in server.py since commit 8d99206).

Run on the Windows VPS:
    .\\venv\\Scripts\\python.exe diag2.py

Expected outcomes:
- Test F succeeds (retcode=0 comment='Done')
    -> thread-pinning works; the server must not be running latest code.
- Test F fails with (-2, 'Unnamed arguments not allowed')
    -> MT5 needs initialize() on the true process-main thread; our fix
       approach is wrong and we need a different solution.
"""

import threading

import MetaTrader5 as mt5
from concurrent.futures import ThreadPoolExecutor


def main() -> None:
    ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5")

    def thread_label(label: str) -> str:
        return f"{label}: thread={threading.current_thread().name}"

    print(ex.submit(thread_label, "in executor").result())
    print("main thread:", threading.current_thread().name)

    init_ok = ex.submit(mt5.initialize).result()
    print("init in executor:", init_ok)
    print("last_error after init:", ex.submit(mt5.last_error).result())

    ex.submit(mt5.symbol_select, "XAUUSD", True).result()

    req = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": "XAUUSD",
        "volume": 0.01,
        "type": mt5.ORDER_TYPE_SELL_LIMIT,
        "price": 4900.0,
        "sl": 4910.0,
        "tp": 4880.0,
        "magic": 0,
        "comment": "diag2",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }

    print("\n--- TEST F: init + order_check in same executor ---")
    r = ex.submit(mt5.order_check, req).result()
    print("order_check:", r)
    print("last_error:", ex.submit(mt5.last_error).result())

    ex.submit(mt5.shutdown).result()
    ex.shutdown(wait=True)


if __name__ == "__main__":
    main()
