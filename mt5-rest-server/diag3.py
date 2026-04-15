"""Diagnostic #3 — confirm NumPy 2.x ABI mismatch is the cause of
(-2, 'Unnamed arguments not allowed').

Hypothesis: MetaTrader5 5.0.5735 was compiled against NumPy 1.x. When
numpy 2.x is installed, string-arg calls (symbol_info_tick, symbol_info)
still work, but dict-arg calls (order_check, order_send) fail with
last_error=(-2, 'Unnamed arguments not allowed') because the C-extension
can't unmarshal the dict correctly across the ABI boundary.

Run on the Windows VPS:
    .\\venv\\Scripts\\python.exe diag3.py

What this does:
1. Prints numpy and MetaTrader5 versions (so we capture environment).
2. Initializes MT5 on the main thread (same as server.py).
3. Calls symbol_info_tick("XAUUSD") — STRING arg baseline (should work).
4. Calls symbol_info("XAUUSD") — STRING arg baseline (should work).
5. Calls order_check(request) — DICT arg (expected to fail if numpy 2.x).
6. Also tries order_check(request=request) keyword form as a secondary check.

Expected outcomes:

  BEFORE `pip install "numpy<2"`:
    - Tests 3 and 4 succeed.
    - Test 5 returns None with last_error=(-2, 'Unnamed arguments not allowed').
    - Test 6 probably also returns None.
    -> confirms ABI mismatch is the cause.

  AFTER `pip install "numpy<2" --force-reinstall`
  AND `pip install --force-reinstall --no-deps MetaTrader5`:
    - All tests pass.
    - Test 5 returns a TradeCheckResult with retcode=0 'Done'.
    -> confirms fix.
"""

import MetaTrader5 as mt5
import numpy


def main() -> None:
    print("─" * 60)
    print(f"numpy    version: {numpy.__version__}")
    print(f"MT5 file version: {getattr(mt5, '__version__', 'n/a')}")
    print(f"MT5 author      : {getattr(mt5, '__author__', 'n/a')}")
    print("─" * 60)

    if not mt5.initialize():
        print(f"[FAIL] mt5.initialize() returned False. last_error={mt5.last_error()}")
        return
    print("[ OK ] mt5.initialize()")

    if not mt5.symbol_select("XAUUSD", True):
        print(f"[WARN] symbol_select XAUUSD returned False. last_error={mt5.last_error()}")
    else:
        print("[ OK ] mt5.symbol_select('XAUUSD', True)")

    # Test 3: string-arg baseline
    tick = mt5.symbol_info_tick("XAUUSD")
    print(f"\n[TEST 3] symbol_info_tick('XAUUSD') -> {tick is not None and 'tick ok' or 'None'}")
    print(f"         last_error={mt5.last_error()}")
    if tick is None:
        print("[FAIL] Cannot continue without tick data.")
        mt5.shutdown()
        return

    # Test 4: string-arg baseline
    sym_info = mt5.symbol_info("XAUUSD")
    print(f"\n[TEST 4] symbol_info('XAUUSD') -> {sym_info is not None and 'info ok' or 'None'}")
    print(f"         last_error={mt5.last_error()}")
    if sym_info is not None:
        print(f"         filling_mode bitmask: {sym_info.filling_mode}")
        print(f"         trade_mode: {sym_info.trade_mode}  (4=SYMBOL_TRADE_MODE_FULL)")
        print(f"         visible: {sym_info.visible}")

    # Build a clean native-Python request dict
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": "XAUUSD",
        "volume": 0.01,
        "type": mt5.ORDER_TYPE_BUY,
        "price": float(tick.ask),
        "deviation": 20,
        "magic": 0,
        "comment": "diag3",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    print("\n[TEST 5] order_check(request) — POSITIONAL dict arg")
    r5 = mt5.order_check(request)
    print(f"         result: {r5}")
    print(f"         last_error: {mt5.last_error()}")

    print("\n[TEST 6] order_check(request=request) — KEYWORD dict arg")
    r6 = mt5.order_check(request=request)
    print(f"         result: {r6}")
    print(f"         last_error: {mt5.last_error()}")

    print("\n─ Interpretation ─")
    if r5 is None and r6 is None:
        print("  Both forms fail -> ABI/binding mismatch (numpy 2.x hypothesis).")
        print("  Fix: pip install 'numpy<2' --force-reinstall")
        print("       pip install --force-reinstall --no-deps MetaTrader5")
    elif r5 is None and r6 is not None:
        print("  Positional fails, keyword works -> signature-only fix.")
        print("  Fix: change server.py to use mt5.order_check(request=request)")
        print("       and mt5.order_send(request=request).")
    elif r5 is not None:
        print("  Both forms work -> the -2 error must come from something")
        print("  specific to the server's request dict. Compare values.")

    mt5.shutdown()


if __name__ == "__main__":
    main()
