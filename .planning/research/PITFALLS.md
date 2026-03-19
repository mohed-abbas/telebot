# Pitfalls Research

**Domain:** Async Python trading bot hardening
**Researched:** 2026-03-19
**Confidence:** HIGH

## Critical Pitfalls

### Pitfall 1: aiosqlite Migration Breaks Transaction Semantics

**What goes wrong:**
Current code uses a single persistent connection with manual `conn.commit()`. aiosqlite uses connection-per-operation by default. Migrating naively can break multi-statement transactions (e.g., log_signal + log_trade must be atomic).

**Why it happens:**
Developers replace `conn.execute()` with `await db.execute()` line-by-line without considering that each `async with aiosqlite.connect()` block is a separate connection.

**How to avoid:**
- Keep related writes in the same `async with` block
- Use `await db.execute("BEGIN")` ... `await db.commit()` for multi-statement transactions
- Alternatively, use a single long-lived aiosqlite connection with proper async access
- Test with concurrent signal injection to verify atomicity

**Warning signs:**
- Database has partial records (signal without corresponding trade)
- daily_stats counts don't match actual trades

**Phase to address:** Phase 1 (Foundation)

---

### Pitfall 2: Reconnect Loop Causes Cascade Failures

**What goes wrong:**
Auto-reconnect fires during market hours, triggers full position sync, which takes 2-5 seconds per account. During this window, new signals arrive and queue up. When reconnect completes, queued signals execute with stale zone checks.

**Why it happens:**
Reconnection and signal handling aren't coordinated. No "paused" state between disconnect and full reconciliation.

**How to avoid:**
- Set a `reconnecting` flag that signal handler checks before processing
- Queue signals during reconnection, process after reconciliation completes
- Add configurable max reconnect attempts before alerting and stopping

**Warning signs:**
- Trades executed immediately after reconnection at bad prices
- Multiple "stale signal" alerts right after reconnection

**Phase to address:** Phase 2 (Reliability)

---

### Pitfall 3: Kill Switch Leaves Orphaned Limit Orders

**What goes wrong:**
Emergency close sends market close for all positions but forgets pending limit orders. These fill later when price reaches the limit, opening new unwanted positions.

**Why it happens:**
Kill switch only queries `get_positions()` (open positions) but not `get_orders()` (pending limits).

**How to avoid:**
- Kill switch must: (1) close all positions, (2) cancel all pending orders, (3) pause executor
- Query both positions AND orders from MT5
- Verify zero positions AND zero orders after kill switch

**Warning signs:**
- New position appears after kill switch was pressed
- Pending orders still visible in MT5 terminal

**Phase to address:** Phase 2 (Reliability)

---

### Pitfall 4: Test Mocks Diverge from Real MT5 Behavior

**What goes wrong:**
MT5 connector mocks return clean success/failure, but real MT5 has nuanced responses: partial fills, requotes, "trade context busy" errors, connection timeouts mid-order.

**Why it happens:**
Mock objects are designed for the happy path. Edge cases in MT5 protocol aren't documented well enough to mock accurately.

**How to avoid:**
- Base mocks on actual MT5 response captures (record responses from dry-run or test account)
- Include specific error codes in mocks (10006=TRADE_RETCODE_REJECT, 10004=TRADE_RETCODE_REQUOTE)
- Have a separate "chaos mock" that randomly fails to test resilience
- Keep dry-run mode as the gold standard for integration-level testing

**Warning signs:**
- All tests pass but production has errors not covered by any test
- Mock responses don't include fields that real MT5 returns

**Phase to address:** Phase 4 (Testing)

---

### Pitfall 5: Concurrent Test Execution Produces Flaky Results

**What goes wrong:**
Async tests share database state, event loops, or module-level globals. Tests pass individually but fail when run together (or vice versa).

**Why it happens:**
Python asyncio test fixtures are tricky. Module-level variables (like the current global `_lock` and `conn` in db.py) persist across tests.

**How to avoid:**
- Use in-memory SQLite (`:memory:`) for tests — fresh database per test
- Use `pytest-asyncio` with `scope="function"` fixtures (default)
- Never share mutable state across test functions
- Run `pytest -x` initially to catch ordering issues

**Warning signs:**
- Tests pass locally but fail in CI
- Tests fail when run in different order
- "Database is locked" errors in test output

**Phase to address:** Phase 4 (Testing)

---

### Pitfall 6: UTC Migration Breaks Daily Limit Enforcement

**What goes wrong:**
Current daily_stats uses `date.today().isoformat()` (local timezone). Switching to UTC changes when the "day" resets. If bot runs in UTC+3 timezone, daily limit resets 3 hours earlier than expected.

**Why it happens:**
`date.today()` returns local date. Changing to `datetime.now(timezone.utc).date()` shifts the boundary.

**How to avoid:**
- Document that daily limits reset at UTC midnight (not local midnight)
- If user expects local-time resets, make timezone configurable for daily_stats specifically
- Test with dates near midnight in both local and UTC

**Warning signs:**
- Daily trade count resets at unexpected time
- User reports "I still had trades left but bot said limit reached"

**Phase to address:** Phase 1 (Foundation)

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Single aiosqlite connection (not pool) | Simpler migration | May bottleneck under very high signal volume | Acceptable for v1 — bot processes ~30 signals/day max |
| Staying on Telethon 1.42 | No migration work | May miss security patches, API changes | Acceptable until Telegram forces API change or security issue found |
| In-process dashboard | No IPC complexity | Dashboard latency affects signal processing | Acceptable unless dashboard traffic becomes significant |
| No alembic migrations | No migration tooling overhead | Schema changes require manual SQL | Acceptable while schema is stable |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| MT5 reconnect | Calling `initialize()` without first calling `shutdown()` | Always shutdown stale connection before reconnecting |
| aiosqlite WAL mode | Assuming WAL is set per-connection | WAL persists in the database file; set once during `init_db()`, verify on connect |
| Discord webhooks during reconnect | Flooding #alerts with reconnect attempts | Debounce: only notify on first disconnect and on successful reconnect |
| Telethon session after Telethon update | Session format changes between versions | Keep session backup; test session validity before going live |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| aiosqlite connection per query | Each query opens/closes connection file handle | Use connection pool or single long-lived connection | >50 queries/second |
| Full position sync on every heartbeat | MT5 API hammered every 30s × N accounts | Only full sync after reconnect; heartbeat just pings | >5 accounts |
| Archival query on large tables | SELECT * FROM trades for CSV export blocks other queries | Use LIMIT/OFFSET pagination, run during low-activity hours | >100k rows |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Logging MT5 passwords during startup validation | Credentials in log files | Never log credential values; log "credential present: yes/no" |
| Kill switch without auth | Anyone with dashboard URL can close all positions | Kill switch must require authentication (already behind HTTP Basic) |
| Env validation error messages expose credential format | Helps attackers guess valid formats | Generic messages: "MT5_PASSWORD is required" not "MT5_PASSWORD must be 8+ chars with numbers" |

## "Looks Done But Isn't" Checklist

- [ ] **aiosqlite migration:** Often missing WAL mode re-initialization — verify `PRAGMA journal_mode=wal` after migration
- [ ] **Auto-reconnect:** Often missing "pause trading during reconnect" — verify no trades execute between disconnect and full sync
- [ ] **Kill switch:** Often missing pending order cancellation — verify both positions AND orders are cleared
- [ ] **Env validation:** Often missing valid-format checks (only checks presence) — verify TG_API_ID is numeric, not just non-empty
- [ ] **Test coverage:** Often missing async edge cases — verify tests include concurrent signal scenarios, not just sequential
- [ ] **UTC migration:** Often missing daily_stats migration — verify existing records are either migrated or new table started

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Broken transactions after aiosqlite migration | LOW | Fix transaction boundaries, data self-heals on next signal |
| Cascade execution after reconnect | MEDIUM | Manual position review in MT5, close unwanted trades |
| Orphaned orders after kill switch | MEDIUM | Manual cancellation in MT5 terminal |
| Flaky tests in CI | LOW | Isolate with in-memory DB, fix shared state |
| Daily limit reset time shift | LOW | Communicate new reset time, adjust if needed |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Transaction semantics | Phase 1 | Concurrent signal test with DB assertion |
| Reconnect cascade | Phase 2 | Simulate disconnect during signal processing |
| Kill switch orphans | Phase 2 | Kill switch test verifying zero positions AND orders |
| Mock divergence | Phase 4 | Compare mock responses with dry-run captures |
| Flaky async tests | Phase 4 | CI passes 3 consecutive runs |
| UTC daily limit shift | Phase 1 | Test daily limit at midnight UTC boundary |

---
*Pitfalls research for: async Python trading bot hardening*
*Researched: 2026-03-19*
