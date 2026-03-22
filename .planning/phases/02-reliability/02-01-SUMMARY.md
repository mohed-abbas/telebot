---
phase: 02-reliability
plan: 01
subsystem: mt5-connector
tags: [mt5, ping, eoferror, reconnect, password, resilience]
---

## Performance
- Tasks: 2/2
- Duration: ~3 min (interactive)

## Accomplishments
- MT5 connector base class now has abstract ping() and password_env field
- DryRunConnector implements ping() returning self._connected
- MT5LinuxConnector.ping() checks broker connectivity via terminal_info().connected
- All 8 MT5LinuxConnector methods wrapped with (EOFError, ConnectionError, OSError) catch
- connect() re-reads password from env var for reconnect after SEC-04 clearing
- Factory passes password_env through to all connector types
- bot.py passes acct.password_env when creating connectors

## Task Commits
- `01e90ab`: feat(02-01): add ping() and password_env to MT5 connector base
- `37e5bb6`: feat(02-01): add ping(), EOFError wrapping, reconnect password to MT5LinuxConnector

## Files Created/Modified
- `mt5_connector.py` — ping(), EOFError wrapping, password_env, reconnect support
- `bot.py` — passes password_env to create_connector

## Self-Check: PASSED
