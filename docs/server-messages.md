# Server Message Limits

## What is a "server message"?

A **server message** is any MT5 API call that sends a write request to the broker's trade server. The bot tracks these internally as a safety limit to prevent runaway order placement.

**Counts as a server message (write operations):**

- `open_order()` -- placing a new market or limit order
- `modify_position()` -- updating SL/TP on an open position
- `close_position()` -- closing an open position (full or partial)
- `cancel_order()` -- cancelling a pending limit order

**Does NOT count (read-only queries):**

- `get_positions()` -- fetching current open positions
- `get_account_info()` -- reading account balance, equity, etc.
- `get_price()` -- retrieving current market prices

Each write operation increments the counter by 1 after the MT5 call completes, regardless of whether the broker accepted or rejected the request.

## How is it tracked?

The `daily_stats` table in the database tracks `server_messages` per account per day.

- **Increment:** `increment_daily_stat(account_name, "server_messages")` is called in `trade_manager.py` after each write operation to MT5. This covers order opens, SL/TP modifications, partial closes, full closes, and pending order cancellations.
- **Reset:** The counter resets at the UTC date boundary. The `_utc_today()` function in `db.py` determines the current date. A new row is created in `daily_stats` for each account on each new UTC day.
- **Check:** Before executing any signal, `trade_manager.py` calls `get_daily_stat(account_name, "server_messages")` and compares against the configured limit.

## MT5 broker limits

MT5 brokers may impose their own server message limits, which vary by broker and account type. These are **separate** from the bot's internal limit.

- Check with your broker for their specific daily or hourly message limits.
- Some brokers throttle requests rather than hard-blocking them.
- The bot's limit is a **conservative safety net** to prevent runaway order placement (e.g., from a parsing bug or duplicate signal flood).

## Configuration

Set the limit in `accounts.json` under the `global` section:

```json
{
  "global": {
    "max_daily_server_messages": 500
  }
}
```

- **Default:** 500 per account per day
- **Scope:** Per-account limit (each account has its own counter)
- **Behavior when reached:** The bot skips new trade executions for that account until the next UTC day. Existing positions are not affected -- they remain open with their current SL/TP.

The limit is loaded into `GlobalConfig.max_daily_server_messages` at startup.

## Monitoring

The dashboard overview page displays the current `daily_messages` count for each account alongside the daily trade count. This is visible on the main overview page.

Currently there is no percentage-based warning for approaching the server message limit. The bot will log a warning and skip execution when the limit is reached. If you need earlier warnings, consider lowering `max_daily_server_messages` to a conservative value well below your broker's actual limit.
