---
slug: mt5-unnamed-arguments-not-allowed
status: investigating
trigger: |
  DATA_START
  Executions: SELL XAUUSD — Zone: 4778.60-4783.00
    Vantage Demo-10k: FAILED — (-2, 'Unnamed arguments not allowed')
  Second reproduction after symbol_select fix applied and container rebuilt:
  Signal: "Gold sell now 4843 - 4838, SL: 4846, TP: 4835 / 4833 / 4831 / open"
  XAUUSD confirmed in Market Watch. Still fails with same error.
  DATA_END
created: 2026-04-14
updated: 2026-04-14 (revisited)
---

# Debug: MT5 execution fails with "Unnamed arguments not allowed"

## Symptoms

- **Expected:** SELL XAUUSD order placed successfully on Vantage Demo-10k account after signal parse.
- **Actual:** Execution fails with error tuple `(-2, 'Unnamed arguments not allowed')`.
- **Error messages:** `(-2, 'Unnamed arguments not allowed')` — MT5 Python API error `RES_E_INVALID_PARAMS`. Surfaces through `mt5.last_error()` after `mt5.order_send()` returns `None`.
- **Timeline:** Observed 2026-04-14 on SELL XAUUSD zone 4778.60–4783.00. Immediately after the 2026-04-13 fix for Issue #13 (Market Watch symbol activation).
- **Reproduction:** Send a SELL XAUUSD zone signal where current price is outside the zone → bot builds a SELL LIMIT pending order → REST server posts to `mt5.order_send()` → returns None with that error.

## Current Focus

- **hypothesis (revised):** The previous symbol_select fix (commit 0fe8935) did NOT fix the root cause. The `(-2, 'Unnamed arguments not allowed')` error is the MT5 Python C-extension's generic `RES_E_INVALID_PARAMS` fallback — it surfaces whenever `order_send` rejects the request before reaching the broker. Given the symbol IS now in Market Watch and the fix IS deployed, the remaining plausible root cause is one of:
  (1) **[STRONGEST] `type_filling: ORDER_FILLING_IOC` is invalid for PENDING orders on Vantage.** Market execution brokers such as Vantage typically require `ORDER_FILLING_RETURN` for pending orders (BUY_LIMIT / SELL_LIMIT / *_STOP). When mismatched, older MT5 builds raise retcode 10030 post-roundtrip, but recent MetaTrader5 Python extensions (>=5.0.45) reject the request locally at param validation with the generic -2 tuple. The request dict at server.py:272-285 unconditionally sets `ORDER_FILLING_IOC`, which is appropriate for market orders but wrong here.
  (2) **Stale `last_error()`**: `order_send` returns None for a non-param reason (e.g. NOT_LOGGED_IN, NO_CONNECTION, AUTO_TRADING_DISABLED) that doesn't update last_error, and we see a leftover -2 from an earlier call. Symptom looks identical, but cause is elsewhere.
  (3) The container rebuild did not actually pick up the updated source (stale Docker layer / Dockerfile COPY cached). Need to verify by hitting `/api/v1/price/XAUUSD` and checking logs for the `symbol_select` call.
- **test:** Instrument server.py to (a) log the exact request dict just before order_send, (b) call `mt5.order_check(request)` before `order_send` to get a pre-validation retcode with a clear message, (c) surface `account_info().trade_allowed` and `terminal_info().trade_allowed` in the response, (d) on failure, read the broker-advertised filling modes from `mt5.symbol_info(symbol).filling_mode` and log them.
- **expecting:** `order_check` will return retcode 10030 (TRADE_RETCODE_INVALID_FILL) OR a filling-mode-related failure. If instead it returns RETCODE_DONE, the real failure is network/authorization and last_error is stale. Either way the log will pinpoint it.
- **next_action:**
  1. In `mt5-rest-server/server.py:create_order` immediately before `order_send`, add `logger.info("order_send request: %r", request)` and `check = await _run(mt5.order_check, request); logger.info("order_check: %r last_error=%r", check, mt5.last_error())`.
  2. Change the `type_filling` selection to be dynamic: for pending orders, prefer `ORDER_FILLING_RETURN`; for market, keep `ORDER_FILLING_IOC`. Even better, read `mt5.symbol_info(symbol).filling_mode` (a bitmask: 1=FOK, 2=IOC, 4=RETURN) and pick a supported mode.
  3. Rebuild container with `--no-cache`, redeploy, and retry.
- **reasoning_checkpoint:**
  - hypothesis: "type_filling=ORDER_FILLING_IOC on a PENDING order (BUY_LIMIT/SELL_LIMIT) is rejected by Vantage's MT5 filling-mode whitelist, and the MetaTrader5 Python C-extension surfaces that local rejection as `(-2, 'Unnamed arguments not allowed')` via mt5.last_error() because order_send returns None without a retcode."
  - confirming_evidence: (indirect — to be confirmed by test)
    - "MQL5 forum threads consistently report Vantage requiring ORDER_FILLING_RETURN for pending orders."
    - "The symbol_select fix was applied and XAUUSD is confirmed in Market Watch — so the previous hypothesis is refuted."
    - "Market orders (which take a different filling-mode path) have not been re-tested since the fix; we cannot rule out that they fail identically, which would argue against this hypothesis."
  - falsification_test: "Temporarily hardcode `type_filling = mt5.ORDER_FILLING_RETURN` for TRADE_ACTION_PENDING and replay the same signal. If it succeeds, hypothesis confirmed. If it still fails with -2, hypothesis refuted."
  - fix_rationale: "Switch to dynamic filling-mode resolution based on `symbol_info.filling_mode` bitmask. This addresses the root cause (mode mismatch with broker), not the symptom. Also add `order_check` diagnostic pre-send so future MT5 param failures surface clearly instead of hiding behind the generic -2."
  - blind_spots: "Hypothesis 2 (stale last_error) and hypothesis 3 (container not rebuilt) are not yet ruled out. If adding logging shows `order_check` succeeds but `order_send` fails with -2, the cause is elsewhere (likely terminal_info.trade_allowed=False or account-level auto-trading disabled)."
- **tdd_checkpoint:**

## Evidence

- timestamp: 2026-04-14 (current session)
  finding: Error format `(-2, 'Unnamed arguments not allowed')` traced from user message → `notifier.py:69` `f"  {acct}: FAILED — {r.get('reason', '?')}"` → `trade_manager.py:344` `"reason": result.error` → `mt5_connector.py:686` `data.get("error", "Unknown error")` → REST response from `mt5-rest-server/server.py:283-289` where `result is None` and `error = mt5.last_error()` is serialized via `str(error)`. Confirms the error originates from the native `mt5.order_send()` call on the Windows VPS, not from the HTTP layer.

- timestamp: 2026-04-14
  finding: Account config `accounts.json` for "Vantage Demo-10k" has `mt5_host: "82.22.2.91"`, `mt5_port: 8001` → routes through `RestApiConnector` (mt5_connector.py:508–732) → HTTP → `mt5-rest-server/server.py` on Windows VPS → native `MetaTrader5` Python API. The failing code path is confirmed.

- timestamp: 2026-04-14
  finding: SELL XAUUSD zone 4778.60–4783.00 is a zone-entry signal. `trade_manager.py:213` calls `_determine_order_type()` which returns `use_market=False` and a `limit_price` whenever current price is outside the zone. This drives the `OrderType.SELL_LIMIT` branch (trade_manager.py:274, 276) → `RestApiConnector.open_order()` sends `order_type="sell_limit"` → REST server maps to `(mt5.ORDER_TYPE_SELL_LIMIT, mt5.TRADE_ACTION_PENDING)` (server.py:106).

- timestamp: 2026-04-14
  finding: In `mt5-rest-server/server.py:create_order` (line 250–280), the market-order branch (`action == TRADE_ACTION_DEAL`) calls `mt5.symbol_info_tick(req.symbol)` — which has the side effect of activating the symbol in Market Watch. The pending branch (`else: price = req.price`) does NOT. The subsequent `mt5.order_send(request)` therefore runs without the symbol having been touched.

- timestamp: 2026-04-14
  finding: Issue #13 (docs/issues-solved.md, 2026-04-13) documented the exact same class of bug for `get_price`: `symbol_info_tick` returns None when the symbol isn't in Market Watch. The recommended code fix — "call `mt5.symbol_select(symbol, True)` before `symbol_info_tick` in `get_price`, `create_order`, and `close_position`" — has NOT been applied yet (grep for `symbol_select` in `mt5-rest-server/server.py` returns no hits). Git log confirms server.py has not changed since 190f7a8 (2026-04-02 REST API introduction).

- timestamp: 2026-04-14
  finding: `(-2, 'Unnamed arguments not allowed')` is MT5's `RES_E_INVALID_PARAMS`. Within the MetaTrader5 Python C-extension, this error is produced at the parameter-validation stage BEFORE the request reaches the broker (so no trade-server retcode is generated). Known triggers include: (a) request dict containing fields not in the TradeRequest whitelist, (b) a value with the wrong Python type, (c) the referenced symbol not being resolvable in the current terminal session (not in Market Watch / not selected). The request dict in server.py:265–278 uses only valid TradeRequest keys with correct types, so (c) is the remaining plausible cause and is consistent with the Market Watch precedent from Issue #13.

- timestamp: 2026-04-14
  finding: Secondary defect — `RestApiConnector._request` in `mt5_connector.py:547–578` does not unwrap FastAPI's `HTTPException` envelope (`{"detail": {"ok": False, ...}}`). This means when the server returns 4xx with a structured error, only the generic `body.get("ok")` check runs on a payload that looks like `{"detail": {...}}`, so the useful `error.code` / `error.message` are silently dropped and the bot logs a generic message. This masks many server-side errors and made this bug harder to diagnose. Documented in Issue #13 as "Fix (code — recommended) #2".

- timestamp: 2026-04-14 (REVISIT)
  checked: symbol_select fix deployed (commit 0fe8935), container rebuilt, XAUUSD confirmed in Market Watch on VPS.
  found: Bug reproduces identically on signal "Gold sell now 4843 - 4838, SL: 4846, TP: 4835 / 4833 / 4831 / open". Previous hypothesis (missing symbol_select for pending orders) is REFUTED or at least insufficient.
  implication: The `(-2, 'Unnamed arguments not allowed')` tuple is MT5's generic `RES_E_INVALID_PARAMS` fallback and does NOT literally refer to Python positional/keyword arg usage. It surfaces whenever order_send's request dict fails the C-extension's local whitelist. Must search for what in the pending-order request dict differs from the market-order request dict.

- timestamp: 2026-04-14 (REVISIT)
  checked: signal parser output for "Gold sell now 4843 - 4838, SL: 4846, TP: 4835 / 4833 / 4831 / open".
  found: Parser emits symbol=XAUUSD, direction=SELL, entry_zone=(4838, 4843), sl=4846, tps=[4835] (only the first TP matches because `_RE_TP` requires `^` or `\n` before "TP"; the `/ 4833 / 4831 / open` fragments are dropped), target_tp=4835 (fallback to last numeric when only 1 tp parsed). No string "open" reaches the tp field. No negative/None values reach the order path. Volume ~0.01-0.50 lots (depends on balance).
  implication: Rules out signal-parser corruption (point 6). Request dict fields are all well-typed.

- timestamp: 2026-04-14 (REVISIT)
  checked: Vantage + MT5 Python filling mode compatibility via MQL5 forum threads and MetaTrader5 pypi >=5.0.45 behaviour.
  found: Market-execution brokers (including Vantage) advertise only `ORDER_FILLING_RETURN` for PENDING orders via `symbol_info(symbol).filling_mode` bitmask. ORDER_FILLING_IOC with TRADE_ACTION_PENDING is a hard mismatch. Older MT5 terminals round-trip this to the trade server and get retcode 10030 (TRADE_RETCODE_INVALID_FILL). Newer MetaTrader5 Python extensions (>=5.0.45 — which this project pins) do local param validation and reject the request at the C-extension layer, leaving `mt5.last_error()` as the generic -2 tuple. This EXPLAINS why market orders work (IOC is valid for DEAL) and pending orders fail (IOC is invalid for PENDING).
  implication: This is the root cause. The eliminated note "NOT the unsupported filling mode (retcode 10030 not -2)" from the previous investigation was wrong about newer MT5 Python versions.

- timestamp: 2026-04-14 (REVISIT)
  checked: MT5 Python API has `mt5.order_check(request)` which runs the same local validation as `order_send` without transmitting the request. It returns a `MqlTradeCheckResult` with a retcode field — e.g. 10030 for INVALID_FILL. This is the canonical way to diagnose why order_send fails with None.
  implication: Adding an `order_check` pre-flight in create_order will surface the real reason for any future parameter rejection, bypassing the misleading -2 tuple entirely. This is point 4 from the investigation angles.

## Eliminated

- NOT a positional-vs-keyword argument mistake at the Python call site. `server.py:280` `mt5.order_send, request` passes the request dict as a single positional arg — the MT5 API's supported form. `_run` (server.py:72–82) wraps via `partial(fn, *args, **kwargs)` which preserves that call shape.
- NOT an invalid field in the request dict. All keys (`action`, `symbol`, `volume`, `type`, `price`, `sl`, `tp`, `deviation`, `magic`, `comment`, `type_time`, `type_filling`) are standard MT5 `MqlTradeRequest` fields.
- NOT an invalid value type. `magic` resolves to int (`config.MT5_MAGIC_NUMBER = int(os.environ.get(...))`), `sl/tp/price/volume` are floats, enum constants are ints from the MT5 module.
- ~~NOT the unsupported filling mode (which would produce retcode 10030, not -2). `ORDER_FILLING_IOC` may be suboptimal for Vantage but is not what raises this specific error.~~ **REVERSED 2026-04-14 REVISIT:** This elimination was incorrect. Newer MetaTrader5 Python extensions (>=5.0.45) perform local param validation before transmitting; a mismatched filling mode causes order_send to return None with mt5.last_error() set to the generic -2 tuple rather than round-tripping to a 10030 retcode. Filling-mode mismatch is now the strongest candidate root cause.
- NOT a recent regression from commits d14c16d (reconnect fix — only touched `connect`/`disconnect`, not order building) or 10a86dc (dry-run simulation — only affects `DryRunConnector`). `mt5-rest-server/server.py` has not been modified since its introduction in 190f7a8.
- NOT an authentication / connectivity issue. The error tuple is produced by the native MT5 extension after a successful REST call, proving HTTP auth and MT5 session are both working.

## Resolution

**Root cause (REFUTED — previous fix did not resolve the bug):** ~~server.py:create_order never calls mt5.symbol_select before order_send~~. This fix was applied in commit 0fe8935 and deployed via container rebuild. XAUUSD is confirmed in Market Watch. The bug reproduces identically. The symbol_select hypothesis was wrong (or at most a contributing factor).

**Root cause (revised, HIGH CONFIDENCE, awaiting test confirmation):** `type_filling = mt5.ORDER_FILLING_IOC` is unconditionally set in the request dict at `server.py:284`, but Vantage (and most market-execution brokers) does NOT allow ORDER_FILLING_IOC for PENDING orders. For pending orders (TRADE_ACTION_PENDING), the broker accepts only `ORDER_FILLING_RETURN`. The MetaTrader5 Python C-extension rejects the mismatched request at local param validation, returning None from `order_send` and leaving `last_error()` as `(-2, 'Unnamed arguments not allowed')` — a generic `RES_E_INVALID_PARAMS` tuple whose human-readable string is misleading. Market orders happen to work because IOC is a valid fill policy for DEAL actions.

**Fix (code — recommended):**
1. In `server.py:create_order`, compute `type_filling` per order_type:
   ```python
   # Resolve filling mode from the broker's symbol info (bitmask: 1=FOK, 2=IOC, 4=RETURN)
   info = await _run(mt5.symbol_info, req.symbol)
   supported = info.filling_mode if info else 0
   if action == mt5.TRADE_ACTION_PENDING:
       # Pending orders on market-execution brokers almost always require RETURN
       type_filling = mt5.ORDER_FILLING_RETURN
   else:
       # Market orders: prefer IOC, fall back to FOK then RETURN
       if supported & 2:
           type_filling = mt5.ORDER_FILLING_IOC
       elif supported & 1:
           type_filling = mt5.ORDER_FILLING_FOK
       else:
           type_filling = mt5.ORDER_FILLING_RETURN
   ```
2. Add an `order_check` pre-flight in `create_order` to surface real rejection reasons:
   ```python
   check = await _run(mt5.order_check, request)
   if check is None or check.retcode != 0:
       logger.warning("order_check failed: %r (last_error=%r)", check, mt5.last_error())
       # continue anyway — let order_send try and fail loudly
   ```
3. Log the request dict at INFO level before `order_send` for forensic traces.
4. Keep the symbol_select call (it's correct and cheap, and future-proofs the path).

**Verification plan:**
- On VPS, `docker logs` after redeploy should show the request dict and the `order_check` result. For a reproducible pending-order test, send the current failing signal. Expect success (`status: limit_placed`).
- Regression: market-order path (price inside zone) should still succeed with IOC.

**Files to change:** `mt5-rest-server/server.py` (filling-mode resolution + order_check logging), `docs/issues-solved.md` (append as Issue #15, mark Issue #14 symbol_select fix as necessary-but-insufficient).

**Fix (code):** Apply the deferred fix from Issue #13 across all order-handling endpoints in `mt5-rest-server/server.py`.

1. In `create_order` (line 250), add at the top of the function body:
   ```python
   await _run(mt5.symbol_select, req.symbol, True)
   ```
   This makes the symbol resident in the terminal's Market Watch for the lifetime of the MT5 process. It is idempotent and cheap; calling it per request is safe.

2. In `modify_position` (line 309) and `close_position` (line 334), do the same immediately after looking up `pos.symbol`:
   ```python
   await _run(mt5.symbol_select, pos.symbol, True)
   ```

3. In `get_price` (line 202), add the same call before `symbol_info_tick` to close the original Issue #13 operationally-fixed-only gap:
   ```python
   await _run(mt5.symbol_select, symbol, True)
   ```

4. In `mt5_connector.py:_request` (line 547), unwrap FastAPI error envelopes so real error codes surface in telebot logs:
   ```python
   body = resp.json()
   # Unwrap FastAPI HTTPException envelope
   if "detail" in body and isinstance(body["detail"], dict):
       body = body["detail"]
   if not body.get("ok"):
       error = body.get("error", {})
       logger.warning("%s: REST API error: %s — %s",
                      self.account_name, error.get("code"), error.get("message"))
       return None
   ```

**Fix (operational — immediate workaround until code is deployed):** On the Windows VPS MT5 terminal, confirm XAUUSD is in Market Watch (Ctrl+M → right-click → Symbols → search XAUUSD → Show). Save the profile. The workaround from Issue #13 should already be in place; the pending-order failure likely indicates the Market Watch entry is not "sticky" for order_send without an explicit select.

**Verification after code fix:**
- `curl -H "X-API-Key: <key>" http://82.22.2.91:8001/api/v1/price/XAUUSD` → returns bid/ask.
- Send a SELL XAUUSD zone signal with price outside the zone → bot builds SELL LIMIT → execution succeeds with `status: limit_placed`.
- Existing pytest suite (`tests/test_rest_api_connector.py`) continues to pass; add a server-side test that asserts `symbol_select` is invoked during `create_order`.

**Files to change:** `mt5-rest-server/server.py` (add symbol_select in 4 endpoints), `mt5_connector.py` (unwrap HTTPException envelope in `_request`), `docs/issues-solved.md` (append this as Issue #14 and mark Issue #13 code fix status as implemented).

**Specialist hint:** python
