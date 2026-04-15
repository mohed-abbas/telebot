"""Diagnostic #5 — replicate the server's full startup sequence.

diag4 proved the raw order_check call works with the full server-shaped
dict. The server still fails with (-2, 'Unnamed arguments not allowed').
The key remaining difference is that the server's lifespan calls:

    mt5.initialize(path=...)
    mt5.login(MT5_LOGIN, password=..., server=...)

BEFORE any request handler runs. This diag mirrors that exactly and then
runs order_check with the same dict shape. If this reproduces -2, the
culprit is `mt5.login()` after `mt5.initialize()` while the terminal is
already logged in manually.

Run:
    .\\venv\\Scripts\\python.exe diag5.py
"""

import MetaTrader5 as mt5
import config


def main() -> None:
    print(f"MT5_LOGIN={config.MT5_LOGIN}  MT5_SERVER={config.MT5_SERVER!r}")
    print(f"MT5_TERMINAL_PATH={config.MT5_TERMINAL_PATH!r}")
    print("─" * 60)

    # Step 1: initialize (mirrors server.lifespan)
    init_kwargs = {}
    if config.MT5_TERMINAL_PATH:
        init_kwargs["path"] = config.MT5_TERMINAL_PATH
    ok = mt5.initialize(**init_kwargs) if init_kwargs else mt5.initialize()
    print(f"mt5.initialize({init_kwargs!r}) -> {ok}   last_error={mt5.last_error()}")
    if not ok:
        return

    info = mt5.account_info()
    if info is not None:
        print(f"after init: logged in as login={info.login} server={info.server!r}")
    else:
        print("after init: account_info=None")

    # Step 2: login (mirrors server.lifespan auto-login)
    if config.MT5_LOGIN and config.MT5_PASSWORD and config.MT5_SERVER:
        ok2 = mt5.login(
            config.MT5_LOGIN,
            password=config.MT5_PASSWORD,
            server=config.MT5_SERVER,
        )
        print(f"mt5.login(...) -> {ok2}   last_error={mt5.last_error()}")
        info = mt5.account_info()
        if info is not None:
            print(f"after login: balance={info.balance} equity={info.equity}")
    else:
        print("SKIPPED mt5.login() — no credentials in config")

    # Step 3: run the exact same order_check probe as diag4
    mt5.symbol_select("XAUUSD", True)
    tick = mt5.symbol_info_tick("XAUUSD")
    sym = mt5.symbol_info("XAUUSD")
    print(f"\ntick.ask={tick.ask} bid={tick.bid}  filling_mode={sym.filling_mode}")

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": "XAUUSD",
        "volume": 0.16,
        "type": mt5.ORDER_TYPE_BUY,
        "price": float(tick.ask),
        "sl": float(tick.ask) - 7.0,
        "tp": float(tick.ask) + 20.0,
        "deviation": 20,
        "magic": 202603,
        "comment": "telebot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    print("\n[TEST] order_check(request) after initialize+login")
    r = mt5.order_check(request)
    print(f"        result: {r}")
    print(f"        last_error: {mt5.last_error()}")

    mt5.shutdown()

    print("\n─ Interpretation ─")
    print("  If this FAILS with -2 'Unnamed arguments not allowed' ->")
    print("     mt5.login() is breaking the binding. Fix: skip auto-login in")
    print("     lifespan when terminal is already attached (check account_info).")
    print("  If this PASSES ->")
    print("     The culprit is uvicorn/fastapi's async context, not login().")
    print("     Next step: try a sync FastAPI endpoint or run without uvicorn.")


if __name__ == "__main__":
    main()
