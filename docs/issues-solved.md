# Issues Solved — Telebot Trading Bot

A chronological record of issues encountered during development and deployment, along with their root causes and solutions.

---

## Issue #1: "Cannot get current price" in Dry-Run Mode

**Date:** 2026-04-07  
**Component:** `mt5_connector.py` — `DryRunConnector`  
**Symptom:** When a signal was received in `TRADING_DRY_RUN=true` mode, the bot logged `Cannot get current price` and skipped the trade.

**Root Cause:** `DryRunConnector.get_price()` returned `None` by design — there was no price feed in the stub connector. The `TradeManager` calls `get_price()` to calculate lot size and determine order type (market vs limit), so trades always failed.

**Fix:** Added `set_simulated_price()` method to `DryRunConnector` and had `TradeManager` feed the entry zone midpoint as a simulated price before executing. Later superseded by the full `PriceSimulator` implementation.

**Files Changed:** `mt5_connector.py`, `trade_manager.py`

---

## Issue #2: Entry Price Showing 0.00 on Dashboard

**Date:** 2026-04-07  
**Component:** `mt5_connector.py` — `DryRunConnector.open_order()`  
**Symptom:** Trades executed successfully but the entry price on the dashboard and in Discord notifications showed `0.00`.

**Root Cause:** `TradeManager` calls `open_order()` without a `price=` parameter for market orders (defaults to `0.0`). In real MT5, the broker fills at market price and returns the actual fill price. `DryRunConnector` just stored the `0.0` as-is.

**Fix:** Made `DryRunConnector.open_order()` resolve the current simulated price when `price == 0.0`:
```python
if price == 0.0:
    price_data = self._get_current_price(symbol)
    if price_data:
        bid, ask = price_data
        price = ask if direction == "buy" else bid
```

**Files Changed:** `mt5_connector.py`

---

## Issue #3: `/signals` and `/history` Dashboard Routes — Internal Server Error

**Date:** 2026-04-07  
**Component:** `templates/signals.html`, `templates/history.html`  
**Symptom:** Accessing `/signals` or `/history` on the dashboard returned 500 Internal Server Error.

**Root Cause:** Jinja2 templates used string slicing (`s.timestamp[:19]`) on `datetime` objects returned by asyncpg. `datetime` objects don't support string slicing.

**Fix:** Changed to proper datetime formatting:
```jinja
{{ s.timestamp.strftime('%Y-%m-%d %H:%M:%S') if s.timestamp else '-' }}
```

**Files Changed:** `templates/signals.html`, `templates/history.html`

---

## Issue #4: `'Notifier' object has no attribute 'alerts_webhook'`

**Date:** 2026-04-07  
**Component:** `bot.py` — `_on_sim_position_closed` callback  
**Symptom:** When a simulated SL/TP was hit in dry-run mode, the callback crashed with `AttributeError`.

**Root Cause:** The callback referenced `notifier.alerts_webhook` but the actual attribute on the `Notifier` class is `notifier.alerts_url`.

**Fix:** Changed all references from `notifier.alerts_webhook` to `notifier.alerts_url` in the callback.

**Files Changed:** `bot.py`

---

## Issue #5: No SL/TP Monitoring, No P&L, No Balance Updates in Dry-Run

**Date:** 2026-04-07  
**Component:** `DryRunConnector` (entire dry-run simulation)  
**Symptom:** In dry-run mode, trades sat open forever. No SL/TP auto-close, no P&L calculation, hardcoded balance/equity, no pending order fills, no Discord alerts for trade closures.

**Root Cause:** `DryRunConnector` was a minimal stub — designed only to log trades, not simulate the full trade lifecycle.

**Fix:** Implemented a complete trade lifecycle simulation:

1. **`price_simulator.py`** (new file) — Geometric Brownian Motion price engine:
   - GBM model: `price *= exp(σ × volatility_mult × √dt × Z)`
   - Background asyncio task updating all prices every 1 second
   - Configurable volatility via `SIM_VOLATILITY_MULTIPLIER` env var
   - Default spread: XAUUSD $0.30

2. **Enhanced `DryRunConnector`**:
   - Live P&L calculation per position using simulated prices
   - Dynamic balance/equity/margin tracking
   - SL/TP monitoring loop (1-second checks)
   - Pending order fill monitoring (buy limit, sell limit)
   - Callback pattern for SL/TP hits → DB update + Discord notification
   - Partial close support with P&L allocation

3. **Wiring in `bot.py` and `executor.py`**:
   - Shared `PriceSimulator` instance across all connectors
   - Lifecycle management (start/stop monitoring loops)
   - `_on_sim_position_closed` callback for DB + Discord integration

**Files Changed:** `price_simulator.py` (new), `mt5_connector.py`, `config.py`, `executor.py`, `bot.py`

**Config Added:**
- `SIM_VOLATILITY_MULTIPLIER` — Controls price movement speed (default: 1.0, use 10.0 for faster testing)
- `SIM_INITIAL_BALANCE` — Starting account balance in dry-run (default: 10000.0)

---

## Issue #6: REST API `connect()` Always Returns `False`

**Date:** 2026-04-11  
**Component:** `mt5_connector.py` — `RestApiConnector.connect()`  
**Symptom:** The bot connected to the REST server (200 OK) but internally marked the connection as failed. Dashboard showed account offline. Heartbeat triggered infinite reconnect loop.

**Root Cause:** The REST server returns `{"login": ..., "balance": ..., "equity": ...}` on successful connect. But the connector code checked `data.get("connected")` — a key that doesn't exist in the response. So `connect()` always returned `False`.

**Fix:** Changed the success check from `data.get("connected")` to `data.get("login")`:
```python
# Before (broken)
if data and data.get("connected"):

# After (fixed)
if data and data.get("login"):
```

**Files Changed:** `mt5_connector.py`

---

## Issue #7: `disconnect()` Kills Entire MT5 Runtime

**Date:** 2026-04-11  
**Component:** `mt5_connector.py` — `RestApiConnector.disconnect()`, `executor.py` — `_reconnect_account()`  
**Symptom:** After Bug #6 caused a reconnect, the reconnect loop called `disconnect()` then `connect()`. But reconnect always failed with `No IPC connection` or `LOGIN_FAILED`.

**Root Cause:** `disconnect()` called `POST /api/v1/disconnect` on the REST server, which triggers `mt5.shutdown()`. This completely destroys the MT5 Python API runtime. The subsequent `connect()` call (`mt5.login()`) fails because the MT5 API is no longer initialized.

**Fix (two-part):**

1. `RestApiConnector.disconnect()` — removed the server call, only resets local state:
```python
async def disconnect(self) -> None:
    # Don't call /api/v1/disconnect — it triggers mt5.shutdown()
    self._connected = False
    if self._http:
        await self._http.aclose()
        self._http = None
```

2. `Executor._reconnect_account()` — no longer calls `disconnect()`:
```python
# Before (broken)
await connector.disconnect()
success = await asyncio.wait_for(connector.connect(), timeout=15)

# After (fixed)
connector._connected = False
success = await asyncio.wait_for(connector.connect(), timeout=15)
```

**Files Changed:** `mt5_connector.py`, `executor.py`

---

## Issue #8: Password Cleared After First Connect (Reconnect Fails)

**Date:** 2026-04-11  
**Component:** `mt5_connector.py` — `RestApiConnector.connect()`  
**Symptom:** First connection succeeds, but any subsequent reconnect attempt fails because the password is empty.

**Root Cause:** `connect()` called `self._clear_password()` after successful login (a security measure to minimize password exposure in memory). But for the REST API connector, the password is needed for every `mt5.login()` call on reconnect — unlike direct MT5 where the terminal maintains the session.

**Fix:** Removed the `_clear_password()` call from `RestApiConnector.connect()`. The password is still needed for reconnects. The REST API already authenticates via API key, so the MT5 password is only used during the `/connect` call.

**Files Changed:** `mt5_connector.py`

---

## Issue #9: `config.py` Not Loading `ENV_FILE` for Multi-Account NSSM Services

**Date:** 2026-04-08  
**Component:** `mt5-rest-server/config.py`  
**Symptom:** NSSM services set `ENV_FILE=.env.account1` as an environment variable, but `config.py` always loaded `.env` (the default for `load_dotenv()`). Credentials were empty.

**Root Cause:** `config.py` called `load_dotenv()` without arguments, which only loads `.env`. The `ENV_FILE` environment variable was set by NSSM but never read by the code.

**Fix:** Made `config.py` respect the `ENV_FILE` environment variable:
```python
env_file = os.environ.get("ENV_FILE", ".env")
load_dotenv(env_file)
```

**Files Changed:** `mt5-rest-server/config.py`

---

## Issue #10: NSSM Service — MT5 IPC Timeout (Session 0 Isolation)

**Date:** 2026-04-11  
**Component:** Windows VPS deployment  
**Symptom:** NSSM service starts successfully, ping responds, but `alive: false`. Logs show `IPC timeout` or `No IPC connection` during MT5 initialization.

**Root Cause:** Windows services run in **Session 0** (an isolated session for services). The MT5 terminal runs in **Session 1** (the desktop session). The MT5 Python API communicates with the terminal via Windows named pipes, which don't cross session boundaries. Even running the service as the same user (Administrateur) doesn't help — it's the session that matters, not the user.

**Fix:** Abandoned the NSSM service approach. Instead, run uvicorn as a **startup application** in the same desktop session as MT5:

1. Created `C:\Apps\start-all.bat` that launches both MT5 terminal and uvicorn
2. Added a startup shortcut in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`
3. Configured Windows auto-login so the desktop session is always active after reboot

This ensures both MT5 and uvicorn run in the same session, allowing IPC to work.

**Files Changed:** Windows VPS configuration (no code changes)

---

## Issue #11: DNS Resolution Failure — `Temporary failure in name resolution`

**Date:** 2026-04-08  
**Component:** `mt5_connector.py` — `RestApiConnector`  
**Symptom:** Bot logged `REST request failed after 3 attempts: [Errno -3] Temporary failure in name resolution`.

**Root Cause:** The `accounts.json` on the Linux VPS had a hostname (e.g., `mt5-vantage`) instead of the Windows VPS IP address for `mt5_host`. The Docker container couldn't resolve this hostname.

**Fix:** Changed `mt5_host` in `accounts.json` to the Windows VPS IP address (`82.22.2.91`).

**Files Changed:** `accounts.json` (Linux VPS configuration)

---

## Issue #12: `.env.account1` Port Not Parsed by Install Script

**Date:** 2026-04-08  
**Component:** `mt5-rest-server/install-service.ps1`  
**Symptom:** NSSM service started with `Error: Option '--port' requires an argument`, looping endlessly.

**Root Cause:** The `install-service.ps1` script reads the `PORT` value from the `.env.account*` file, but the file had UTF-8 BOM or encoding issues from `Out-File`, causing the port value to not be parsed correctly. The `--port` flag was passed without a value.

**Fix:** Reinstalled the service manually with the port hardcoded in the NSSM parameters:
```powershell
C:\nssm\nssm.exe set mt5-rest-account1 AppParameters "-m uvicorn server:app --host 0.0.0.0 --port 8001"
```

**Files Changed:** None (manual NSSM reconfiguration)

---

## Summary

| # | Issue | Severity | Component | Resolution |
|---|-------|----------|-----------|------------|
| 1 | Cannot get current price (dry-run) | High | DryRunConnector | Added simulated price feed |
| 2 | Entry price 0.00 | Medium | DryRunConnector | Resolve price from simulator |
| 3 | /signals and /history 500 error | Medium | Jinja2 templates | Use .strftime() instead of string slicing |
| 4 | Notifier attribute error | Medium | bot.py callback | Fix attribute name |
| 5 | No trade lifecycle in dry-run | High | DryRunConnector | Full PriceSimulator + monitoring |
| 6 | connect() always returns False | Critical | RestApiConnector | Check `login` key instead of `connected` |
| 7 | disconnect() kills MT5 | Critical | RestApiConnector | Remove server call, local reset only |
| 8 | Password cleared for reconnect | High | RestApiConnector | Don't clear password for REST connector |
| 9 | ENV_FILE not loaded | Medium | config.py | Read ENV_FILE env var |
| 10 | NSSM Session 0 isolation | High | Windows deployment | Use startup app instead of service |
| 11 | DNS resolution failure | Medium | accounts.json | Use IP instead of hostname |
| 12 | Port not parsed by install script | Low | install-service.ps1 | Manual NSSM install with hardcoded port |
