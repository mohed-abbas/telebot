---
slug: 260501-hxd-history-deals-pnl-reconcile
status: in-progress
created: 2026-05-01
---

# Quick Task: poll MT5 history-deals to close trades with P&L

## Problem
trades.status flips to 'closed' (and pnl populates) only when the bot itself
sends the close (CLOSE signal, dashboard close button, or dry-run sim). When
the broker closes a position because SL/TP hit, no code notices and the
trade row stays 'opened' with pnl=0 forever. Side-effects:
  - /analytics shows zeros (filter is `status='closed' AND pnl IS NOT NULL`)
  - /history "P&L" column is empty
  - "Status" column always shows 'opened' for trades that have already exited

## Approach
Add an MT5 deal-history polling loop. Every 60s (configurable), fetch
deals since the last successful poll for each connected account, find each
deal that closed a position whose ticket exists in our trades table with
status='opened', and call `db.update_trade_close()`.

## Cadence + backfill
- Poll every 60s (matches bot's existing 10s position-poll order of magnitude).
- On startup, look back N hours to catch closes that happened during downtime.
  Default 48h (covers a weekend); configurable via
  `GlobalConfig.history_sync_lookback_hours`.

## Files to change

### 1. mt5-rest-server/server.py (deploys to Windows VPS)
Add `GET /api/v1/history/deals?from_ts=<unix>&to_ts=<unix>` that wraps
`mt5.history_deals_get(date_from, date_to)`. Returns serialised deals with:
ticket, order, position_id, time, type, entry, volume, price, profit,
commission, swap, symbol, comment, magic.

### 2. mt5_connector.py
- Add `Deal` dataclass.
- Add `MT5Connector.get_history_deals(since, until=None)` abstract method.
- Implement on `RestApiConnector`: GET the new endpoint, parse into Deal list.
- Implement no-op on `DryRunConnector` (sim path already updates trades via
  the existing on_close callback in bot.py:209).

### 3. models.py
Add to `GlobalConfig`:
  - `history_sync_interval_seconds: int = 60`
  - `history_sync_lookback_hours: int = 48`

### 4. db.py
- `get_open_trade_tickets_for_account(account_name) -> dict[int, int]`
  returns {ticket: trade_id} for status='opened' rows, used to filter the
  deal stream cheaply.

### 5. executor.py
- `_history_sync_loop`: per-account loop body
  - On first iteration: `since = now - lookback_hours`
  - On later iterations: `since = self._last_history_sync[acct_name]`
  - For each deal where `entry == DEAL_ENTRY_OUT` (position close) and
    `position_id` is in our open-trade map → call `update_trade_close()`.
  - Update `_last_history_sync[acct_name] = max_deal_time + 1s` (avoid
    re-processing the same boundary deal).
- Wire start/stop in start()/stop().

### 6. bot.py
No change — executor.start() spawns the loop.

### 7. tests
- `tests/test_history_sync.py` (new): unit-level loop test using a
  fake connector that returns canned deals; assert the open trade row
  becomes 'closed' with the correct pnl.

## MT5 deal type/entry constants used
- `mt5.DEAL_ENTRY_OUT = 1` — closing deal (what we want)
- `mt5.DEAL_TYPE_BUY = 0`, `DEAL_TYPE_SELL = 1` — direction; not needed for
  the close path but include in the Deal dataclass for future use.

## Edge cases
- Partial close: deal volume < position volume. For now we still mark closed
  with the deal's pnl — partial-close support is a separate concern (the
  bot's own partial close already calls update_trade_close(... pnl=0.0) per
  dashboard.py:1022 which is wrong but predates this task).
- Deal time precedes trade.timestamp by clock skew → ignore (don't reopen).
- Deal references position_id that we never opened (manual broker trade) →
  ignore (the open-trade map filters it out).

## Atomic commits
1. feat(rest-server): add /api/v1/history/deals endpoint
2. feat(connector): add get_history_deals + Deal dataclass
3. feat(models): GlobalConfig knobs for history sync cadence/backfill
4. feat(db): get_open_trade_tickets_for_account helper
5. feat(executor): history-sync loop reconciles broker-side closes to trades.pnl
6. test(executor): regression coverage for history-sync close reconciliation
