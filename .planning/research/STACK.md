# Stack Research

**Domain:** Async Python trading bot hardening
**Researched:** 2026-03-19
**Confidence:** HIGH

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| aiosqlite | 0.20.0 | Async SQLite wrapper | Already in requirements.txt; replaces sync sqlite3 + check_same_thread=False. True async I/O eliminates thread safety concerns |
| pytest | 8.3+ | Test framework | Standard Python test runner. Needed for regression tests and CI/CD |
| pytest-asyncio | 0.24+ | Async test support | Required for testing async functions (db, trade execution, signal handling) |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-mock | 3.14+ | Mock objects for testing | Mocking MT5 connectors, Discord webhooks, Telegram client in tests |
| pytest-cov | 5.0+ | Coverage reporting | Measuring test coverage, identifying untested paths |
| pydantic | 2.9+ | Schema validation | Validating env vars, config files at startup (fail-fast) — alternative: manual validation with dataclasses |
| uvicorn[standard] | 0.32.0 | Production ASGI | Already used; standard extra adds uvloop + httptools for better performance |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| ruff | Fast Python linter/formatter | All-in-one replacement for flake8+black+isort, ~100x faster |
| requirements-dev.txt | Dev dependency separation | Keep test/lint deps separate from production deps |

## Installation

```bash
# Production (existing)
pip install -r requirements.txt

# Dev dependencies (new)
pip install -r requirements-dev.txt
# Contains: pytest, pytest-asyncio, pytest-mock, pytest-cov, ruff
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| aiosqlite | databases + aiosqlite | Only if you need multi-DB support; overkill here |
| Manual env validation | pydantic-settings | If config becomes complex (10+ validated fields); adds dependency |
| pytest-asyncio | anyio testing | Only if migrating away from asyncio to trio/anyio |
| SQLite (keep) | PostgreSQL | Only if you need concurrent writes from multiple processes; SQLite is fine for single-process bot |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| sqlite3 with check_same_thread=False | Creates false sense of thread safety; actual race conditions under concurrent async ops | aiosqlite with async context managers |
| Global asyncio.Lock for all DB ops | Serializes all database access unnecessarily; kills concurrency | aiosqlite connection-per-operation or connection pool |
| Bare string formatting in SQL | Even for column names, fragile and invitation for injection if refactored | Whitelist dict mapping field names to allowed SQL identifiers |
| multiprocessing for dashboard | Complicates shared state (executor, notifier references) | Keep in-process but use proper ASGI lifecycle management |

## Stack Patterns by Variant

**If staying conservative (recommended):**
- Use aiosqlite directly (drop-in replacement for current sqlite3 usage)
- Keep FastAPI + uvicorn in-process, add proper shutdown handling
- Manual env validation with clear error messages

**If willing to add dependencies:**
- Use pydantic-settings for type-safe config validation
- Use alembic for SQLite schema migrations
- Use structlog for structured JSON logging

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| aiosqlite 0.20.0 | Python 3.8+ | Uses sqlite3 from stdlib under the hood |
| pytest-asyncio 0.24+ | pytest 8.x | Requires `asyncio_mode = "auto"` in pytest.ini for cleanest usage |
| FastAPI 0.115.0 | uvicorn 0.32.0 | Already compatible in current setup |
| Telethon 1.42.0 | Python 3.12 | Works but check for deprecation warnings; 2.x rewrite exists but is alpha |

## Sources

- aiosqlite GitHub (omni-us/aiosqlite) — async patterns, connection lifecycle
- pytest-asyncio docs — async test fixture patterns
- Python asyncio docs — Lock vs Semaphore patterns, task cancellation
- SQLite WAL mode documentation — concurrent access patterns

---
*Stack research for: async Python trading bot hardening*
*Researched: 2026-03-19*
