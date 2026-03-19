# Codebase Concerns

**Analysis Date:** 2026-03-19

## Tech Debt

### Database Synchronization & Thread Safety

**Issue:** SQLite connection created with `check_same_thread=False` but database operations are async with a global lock, creating potential race conditions.

**Files:** `db.py` (lines 23, 15-16), `bot.py` (line 49)

**Impact:** While the asyncio.Lock guards concurrent async operations, the SQLite connection itself is not thread-safe. If any sync operations occur on different threads (or if the lock is not perfectly maintained), database corruption could occur. The WAL journal mode (line 25) helps but is not a complete safeguard.

**Fix approach:**
- Replace `sqlite3.connect()` with `aiosqlite` (already in requirements.txt but not used) for true async SQLite
- Remove `check_same_thread=False` and use proper async patterns throughout
- Test under high concurrency (multiple accounts executing simultaneously)

### Database Query Injection Vulnerability

**Issue:** Dynamic field names in SQL queries use string formatting for column/table names (not parameterized).

**Files:** `db.py` (lines 190-193, 203-204)

**Impact:** While the actual values are parameterized, field names like `trades_count` and `server_messages` are built dynamically. If these were user-controlled, this would be a serious SQL injection vector. Currently low risk since field names are hardcoded, but fragile if refactored.

**Fix approach:**
- Whitelist allowed field names explicitly
- Use a constants dict for valid field mappings
- Add assertions or enum validation before building queries

### Timezone Handling Inconsistency

**Issue:** Database uses UTC ISO format (`datetime.now(timezone.utc).isoformat()`) but configuration accepts timezone as ZoneInfo for display purposes. Timezone conversions happen in signal parsing (bot.py line 175) but not consistently across all database reads/writes.

**Files:** `db.py` (throughout), `bot.py` (line 175), `config.py` (line 31)

**Impact:** Potential confusion when querying daily_stats which uses `date.today().isoformat()` (local timezone) but signals use UTC. Daily limits could reset at wrong time.

**Fix approach:**
- Standardize all database timestamps to UTC
- Document that daily_stats dates are UTC, not local time
- Apply timezone conversion when displaying to user (dashboard)

## Known Bugs

### Pending Order Cleanup Race Condition

**Issue:** Pending orders marked as "expired" in database may not be properly synchronized with MT5 state. If a limit order fills (converts to position) between cleanup check and cancellation attempt, the cancel will fail.

**Files:** `executor.py` (lines 97-109), `trade_manager.py` (lines 456-479), `mt5_connector.py` (lines 509-533)

**Impact:** Failed cancellation attempts logged as warnings but no retry mechanism. Orphaned limit orders on MT5 side not reflected in database, creating discrepancy between bot state and actual positions.

**Fix approach:**
- Before canceling, query MT5 to verify order still exists
- Distinguish between "order filled" (expected) and "cancel failed" (error) outcomes
- Implement retry queue with exponential backoff for failed cancellations

### Zone-Based Entry Logic for SELL Orders

**Issue:** The zone-based execution logic in `trade_manager.py` (lines 289-316) may execute incorrectly for SELL orders at zone boundaries.

**Files:** `trade_manager.py` (lines 302-308)

**Impact:** When current price equals zone boundary for a SELL order:
- If `current_price >= zone_low`, executes market order
- Zone should represent "sell high" area, but logic treats all prices >= zone_low as good execution
- May execute market sells at unfavorable prices if price just touches zone_low

**Fix approach:**
- Review and clarify zone semantics: Is zone_low the acceptable floor or a hard minimum?
- Add unit tests for boundary conditions (price == zone_low, price == zone_high)
- Document expected behavior in code comments

### Missing Position State Reconciliation

**Issue:** Bot assumes MT5 connector always has current position state, but connections can drop and reconnect. No reconciliation between cached positions and actual MT5 state.

**Files:** `bot.py` (lines 143-151), `executor.py` (lines 62-72), `mt5_connector.py` (lines 252-273)

**Impact:** If MT5 connection is lost mid-trade and reconnects:
1. Bot may not know about newly closed positions
2. Dashboard may show stale positions
3. "Already have a BUY position open" check could incorrectly block new trades

**Fix approach:**
- After reconnection, force full position sync from MT5
- Add `last_sync_time` tracking to detect stale state
- Implement graceful degradation when position sync fails

## Security Considerations

### Hardcoded Magic Number in MT5 Orders

**Issue:** Magic number hardcoded as `202603` (March 2026) in all MT5 orders and used for identification.

**Files:** `mt5_connector.py` (lines 385, 476)

**Impact:** Not a security risk per se, but inflexible. If broker requires magic number changes or multi-bot coordination needed, current approach breaks. Also makes it impossible to distinguish which bot placed an order if multiple instances run.

**Fix approach:**
- Move magic number to configuration
- Include instance ID or deployment name in magic number calculation
- Document magic number purpose and usage

### Environment Variable Validation Missing

**Issue:** Many required environment variables (TG_API_ID, TG_API_HASH, MT5 credentials) are loaded and passed around without validation beyond "did it load".

**Files:** `config.py` (lines 50-78), `bot.py` (lines 127-130)

**Impact:** Invalid or truncated credentials could cause silent failures or unexpected behavior. For example, invalid TG_API_HASH would only fail when connecting.

**Fix approach:**
- Add schema validation (e.g., TG_API_ID is numeric, TG_SESSION is valid StringSession format)
- Test connectivity early in startup (before starting listener)
- Fail fast with clear error messages if credentials invalid

### Password Storage in Memory

**Issue:** MT5 account passwords loaded into memory and stored in AccountConfig dataclass. Not cleared after use.

**Files:** `bot.py` (lines 83-107), `config.py` (lines 96-102), `models.py` (not explicitly, but AccountConfig holds passwords indirectly)

**Impact:** Passwords remain in process memory for lifetime of application. Vulnerable to memory dumps or debugging. No way to rotate passwords without restarting bot.

**Fix approach:**
- Use environment variables for passwords, read only at connection time
- Clear password from memory after MT5 initialization
- Never log or print passwords (currently doesn't, but add safety checks)
- Consider using secure credential store (e.g., systemd user service with LoadCredential)

### Dashboard Default Credentials

**Issue:** Default dashboard credentials hardcoded as "admin" / "changeme".

**Files:** `config.py` (lines 77-78)

**Impact:** Production deployment risk. If `DASHBOARD_PASS` not explicitly set in .env, bot exposes trading dashboard with weak default auth.

**Fix approach:**
- Remove hardcoded defaults for passwords
- Require explicit env var or generate random credentials on first run
- Add startup warning if credentials are defaults
- Document secure credential rotation in deployment guide

## Performance Bottlenecks

### Single-Threaded Async Database Operations

**Issue:** All database operations serialized through a single asyncio.Lock, meaning concurrent signal processing will queue up waiting for database writes.

**Files:** `db.py` (line 15, throughout with `async with _lock:`)

**Impact:** If two signals arrive simultaneously:
1. Signal 1 locks db, writes signal/trade records (multiple commits)
2. Signal 2 waits on lock
3. Execution stalls during heavy signal periods

With 30 max daily trades per account, during high-volume signal periods (e.g., market opens), lock contention could cause 100ms+ delays.

**Fix approach:**
- Use connection pooling or separate read/write connections
- Batch database writes where possible (e.g., accumulate stats, commit once per second)
- Switch to aiosqlite for proper async database support
- Profile with concurrent signal injection to measure actual impact

### Regex Compilation on Every Signal Parse

**Issue:** Regular expressions in `signal_parser.py` (lines 32-95) compiled at module load, which is correct, but many regex operations (.search, .finditer) happen repeatedly per signal.

**Files:** `signal_parser.py` (lines 183-190, 216-219)

**Impact:** Minimal since patterns are reasonably simple and pre-compiled, but `_extract_symbol_from_text` (lines 247-253) iterates through entire SYMBOL_MAP on every call. Not a bottleneck now but scales poorly if symbol map grows.

**Fix approach:**
- Compile a combined symbol regex on startup
- Cache symbol extraction results per chat_id if repeated symbols
- Profile actual parsing time to confirm non-issue

### Dashboard Position Query N+1 Problem

**Issue:** Dashboard calls are incomplete in provided snippet, but pattern suggests potential N+1 queries when loading positions across multiple accounts.

**Files:** `dashboard.py` (lines 80-89, but full position fetch not shown)

**Impact:** If dashboard fetches all positions for all accounts, each account lookup hits MT5 separately (network round-trip). With 10 accounts, this could take 1-2 seconds.

**Fix approach:**
- Batch position queries across accounts at connector level
- Cache positions with short TTL (e.g., 5 seconds) if frequently accessed
- Show data from database audit log instead of live MT5 queries where appropriate

## Fragile Areas

### Signal Parser — High Regex Complexity

**Issue:** Signal parsing relies on 7+ regex patterns with many variants (dashes, spacing, abbreviations). Brittle to variations in signal format.

**Files:** `signal_parser.py` (lines 29-95)

**Impact:** Signals that don't match expected format silently treated as non-signals (return None). Easy to miss valid signals if Telegram group changes format slightly.

**Fix approach:**
- Add comprehensive logging when parse_signal returns None (log attempt and reason)
- Create regression test suite with actual Telegram messages from the signal group
- Add "failed to parse" alert to Discord if signal-like text detected but not parsed
- Consider using a more flexible parsing approach (e.g., NLP, ML-based classification)

### Entry Zone Logic — Implicit Semantics

**Issue:** Entry zone semantics (low/high) interpreted differently for BUY vs SELL but logic is subtle and easy to misunderstand.

**Files:** `trade_manager.py` (lines 289-316), `signal_parser.py` (lines 203-209)

**Impact:** If logic needs modification, it's easy to introduce bugs. Comments in trade_manager explain logic but code is tightly coupled to direction enum.

**Fix approach:**
- Extract zone logic into separate functions: `is_price_in_buy_zone()`, `is_price_in_sell_zone()`
- Add comprehensive unit tests with varied price scenarios
- Document zone semantics clearly (what does zone represent semantically for each direction?)

### Stale Signal Check — Time-of-Check-to-Time-of-Use Race

**Issue:** Stale signal check (trade_manager.py lines 267-287) happens once before executing, but price changes between check and order placement.

**Files:** `trade_manager.py` (lines 134-139, 267-287)

**Impact:** Signal marked as stale (price already past TP1) and skipped, but market moves and suddenly valid. Opposite case: signal passes stale check, then price moves against us in 1 second, and we execute at bad price. Not a critical issue (risk is priced in) but limits adaptability.

**Fix approach:**
- Make stale check configurable (skip, warn, or execute with reduced size)
- Check again immediately before order execution
- Add time-to-execute metric to audit log to measure actual TOCTOU window

### Missing Manual Intervention Mechanism

**Issue:** Once a signal executes, there's no manual override or emergency kill switch until position closes. Dashboard has placeholder for kill switch (notifier.py line 97) but not implemented.

**Files:** `notifier.py` (lines 97-99), `dashboard.py` (incomplete in snapshot)

**Impact:** If signal is misinterpreted or market moves unexpectedly, trading continues on autopilot. Can only close manually through MT5 terminal.

**Fix approach:**
- Implement per-account emergency close button in dashboard
- Add global kill switch that closes all positions immediately
- Require re-enable from dashboard after kill switch activation
- Log all manual overrides to audit trail

## Scaling Limits

### Max Daily Trades Per Account

**Issue:** Daily trade limits (max_daily_trades_per_account = 30) are hard limits but checked very late in execution.

**Files:** `config.py` (line 71), `trade_manager.py` (lines 104-108)

**Impact:** If high-frequency signal group (50+ signals/day), bot will silently ignore 20+ signals without user awareness. Limit is per-account but global limit may be needed.

**Fix approach:**
- Add global daily trade limit across all accounts
- Alert user when approaching daily limit (e.g., at 25/30)
- Make limits configurable per account without code changes
- Add dashboard view of daily limit status

### Server Message Limit

**Issue:** Separate limit on MT5 "server messages" (500/day) is unclear if it refers to actual MT5 protocol messages or bot-initiated orders.

**Files:** `config.py` (line 72), `trade_manager.py` (lines 110-114)

**Impact:** If limit is MT5-enforced, bot's limit may be too aggressive (causes idle time). If bot-only, unclear what "server message" counts as (modify order? cancel? check price?).

**Fix approach:**
- Document what counts as a server message
- Sync with MT5 documentation on actual server limits
- Test at limit boundaries to understand broker behavior
- Consider removing this limit if not MT5-enforced

### SQLite Database Growth

**Issue:** No archival or cleanup mechanism for trade history. Database grows indefinitely.

**Files:** `db.py` (tables created lines 31-94)

**Impact:** After 1 year of trading, database could grow to 100MB+. Backups slow, queries on large tables may degrade.

**Fix approach:**
- Implement monthly archival to CSV/JSON files
- Add periodic cleanup: move old trades to archive, keep last 3 months in live DB
- Add database maintenance command (vacuuming, index reanalysis)
- Monitor database file size in dashboard

## Dependencies at Risk

### Telethon Version Pinned to 1.42.0

**Issue:** Telethon pinned but Telegram API breaks frequently. Version 1.42.0 is dated and may have deprecated endpoints.

**Files:** `requirements.txt` (line 1)

**Impact:** Telethon session strings may become invalid if Telegram changes authentication. API changes could break message listening.

**Fix approach:**
- Update to latest Telethon (4.x) and test thoroughly
- Implement graceful reconnection if session expires
- Add monitoring for Telegram API errors
- Document tested Telethon versions

### Missing Test Dependencies

**Issue:** requirements.txt doesn't include pytest, but test files exist.

**Files:** `requirements.txt`, `test_*.py` files

**Impact:** Test suite can't run in CI/CD unless pytest installed separately. Developers unfamiliar with project may not realize tests need additional setup.

**Fix approach:**
- Create requirements-dev.txt with pytest, pytest-asyncio
- Add to CI/CD workflow
- Document test setup in README

### No Production Web Server

**Issue:** Dashboard uses uvicorn directly in async task, but uvicorn not designed for embedded use.

**Files:** `bot.py` (lines 254-269)

**Impact:** Dashboard is single-threaded, blocking at any request. High load causes Telegram message handler to stall. No graceful shutdown of web server.

**Fix approach:**
- Run dashboard in separate process or container
- Use production ASGI server (gunicorn + uvicorn)
- Add process manager (systemd, supervisord) to restart if crashes
- Implement proper shutdown signal handling

## Missing Critical Features

### Connection Monitoring & Auto-Reconnect

**Issue:** MT5 connections initialized once at startup. If connection drops, no automatic reconnection.

**Files:** `bot.py` (lines 143-151), `executor.py` (lines 62-72)

**Impact:** Single disconnection stops all trading. User must restart bot to resume.

**Fix approach:**
- Implement heartbeat check (ping MT5 every 30 seconds)
- Auto-reconnect on disconnection with exponential backoff
- Notify user on Discord when connection lost/restored
- Track connection uptime metrics in dashboard

### Order Modification Without Position Lookup

**Issue:** MODIFY_SL and MODIFY_TP signals close all matching positions but don't validate direction or entry price first.

**Files:** `trade_manager.py` (lines 389-452)

**Impact:** If accidentally send "Modify SL to 5000" for a BUY XAUUSD trade, it could break positions if SL invalid for direction.

**Fix approach:**
- Add validation: check if new SL is valid for position direction before modifying
- Show confirmation dialog or require second signal to confirm high-impact modifications
- Alert if modifying "unusual" SL values (e.g., SL closer to entry than before)

### No Historical Signal Accuracy Tracking

**Issue:** Bot doesn't track if signals were profitable or track accuracy of signal source.

**Files:** No tracking mechanism in codebase

**Impact:** Can't measure signal quality or identify if a source has degraded. Equal weight given to all signal sources.

**Fix approach:**
- Add signal_accuracy table tracking win rate per source/symbol
- Dashboard shows win rate and profit factor per signal group
- Ability to disable low-accuracy signal groups automatically
- Document in VPS_DEPLOYMENT_GUIDE.md

## Test Coverage Gaps

### Missing Tests for MT5Connector Implementations

**What's not tested:** MT5LinuxConnector and MetaAPI backends (if implemented). No mocking of mt5linux/rpyc library.

**Files:** `mt5_connector.py` (lines 232-533)

**Risk:** Changes to connection logic could break MT5 communication without catching in tests. High-impact area since it's core trading functionality.

**Priority:** High — MT5 connectivity is critical path

### Missing Integration Tests for Trade Manager

**What's not tested:** End-to-end trade execution with realistic signal flow. Current tests (test_trade_manager.py) likely unit tests only.

**Files:** `trade_manager.py` (entire module)

**Risk:** Complex zone logic, position tracking, daily limits all untested together. Multi-account execution not tested.

**Priority:** High — This is where trading logic lives

### Missing Regression Tests for Signal Parser

**What's not tested:** Parser handles signals from actual Telegram groups. Tests use artificial signal formats.

**Files:** `signal_parser.py`, `test_signal_parser.py`

**Risk:** Real-world signals may have variations (typos, formatting changes) that break parser.

**Priority:** Medium — Coverage seems reasonable but real-world data missing

### Missing Tests for Async Patterns

**What's not tested:** Race conditions, concurrent signals, lock contention, asyncio cancellation.

**Files:** `db.py`, `executor.py`, entire async handling

**Risk:** Concurrency bugs only appear under load or in specific timing windows. Silent failures possible.

**Priority:** High — async bugs are hardest to debug

---

*Concerns audit: 2026-03-19*
