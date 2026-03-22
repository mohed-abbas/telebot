# Phase 3: Observability & Infrastructure - Research

**Researched:** 2026-03-22
**Domain:** Observability (logging, analytics, performance) + Docker/nginx deployment hardening
**Confidence:** HIGH

## Summary

Phase 3 covers two distinct domains: (1) observability improvements to the signal parser, dashboard, and symbol lookup, and (2) infrastructure hardening with Docker external networks, nginx reverse proxy, and ASGI lifecycle management. The observability work is mostly code-level Python changes -- adding logging, batching queries, compiling regex, and building analytics SQL queries. The infrastructure work requires Docker Compose networking, nginx config templating, and proper FastAPI lifespan integration.

The codebase is well-positioned for these changes. The asyncpg pool is already in place, the dashboard uses FastAPI+HTMX+Jinja2 patterns that extend naturally to an analytics page, and the Docker/nginx configuration is standard containerized deployment. The Telethon evaluation (INFRA-02) is documentation-only since the decision is to stay on 1.42.0.

**Primary recommendation:** Tackle observability (OBS-01 through OBS-04, ANLYT-01) first since those are pure Python changes with no deployment risk, then layer on infrastructure (INFRA-01 through INFRA-04) which touches deployment topology.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- Production docker-compose.yml stays **standalone** -- joins shared services via external networks
- Two external networks: **`proxy-net`** (nginx reverse proxy) and **`data-net`** (PostgreSQL access)
- Telebot container joins both networks: proxy-net for dashboard HTTPS, data-net for DATABASE_URL
- User will create a **subdomain** for the dashboard (not set up yet -- provide nginx config template)
- **Certbot runs in shared container** -- nginx config should use existing cert paths
- DATABASE_URL in production .env points to shared PostgreSQL via data-net hostname
- **Single signal source** for now (one Telegram group) -- no per-source grouping needed yet, but schema should support it for future
- Display on a **new /analytics dashboard page** with win rate, profit factor, total trades
- **Calculate on page load** -- query database directly, no background job or caching
- Group by symbol for now (since only one source) -- show per-symbol win rate and profit factor
- **Stay on Telethon 1.42.0** -- document only, no version change
- Evaluate compatibility, note any known security patches or deprecations
- Create a brief findings document, not a migration plan

### Claude's Discretion
- Signal parser logging: format, log level, what constitutes "signal-like" text for alerts (OBS-01)
- Server message limit documentation approach (OBS-02)
- Dashboard position query batching implementation (OBS-03)
- Symbol map regex compilation approach (OBS-04)
- ASGI lifecycle management details (INFRA-01)
- Analytics page layout and metrics calculations
- Nginx config specifics (upstream, proxy headers, SSL paths)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| OBS-01 | Signal parser logs detailed reason when parse_signal returns None; Discord alert for signal-like text not parsed | Logging pattern at each return-None path in signal_parser.py; heuristic for "signal-like" detection; notifier.notify_alert() already available |
| OBS-02 | Server message limits documented: what counts, sync with MT5 broker limits, configurable per account | Documentation-only requirement; research on MT5 server message semantics |
| OBS-03 | Dashboard position queries batched across accounts; no N+1 pattern; optional short-TTL cache | asyncio.gather pattern for _get_all_positions(); simple dict-based TTL cache |
| OBS-04 | Symbol map uses compiled combined regex for lookup instead of iterating SYMBOL_MAP | re.compile combined alternation pattern from SYMBOL_MAP keys |
| ANLYT-01 | Signal accuracy tracking: win rate and profit factor per signal source and symbol | PostgreSQL aggregate queries on existing trades table; new /analytics page with Jinja2+HTMX |
| INFRA-01 | Dashboard runs with proper ASGI lifecycle management; graceful shutdown on SIGTERM | FastAPI lifespan context manager; uvicorn graceful shutdown; db.close_db() and executor.stop() in shutdown |
| INFRA-02 | Telethon version evaluated: document compatibility, identify security patches | Telethon 1.42.0 is current latest stable (Nov 2025); documentation findings |
| INFRA-03 | Docker compose configured to join existing shared services networks | Docker Compose external network syntax for proxy-net and data-net |
| INFRA-04 | Nginx reverse proxy configuration for dashboard with HTTPS | nginx server block with proxy_pass, SSE support, certbot SSL paths |

</phase_requirements>

## Standard Stack

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | 0.31.0 | PostgreSQL async driver | Already used; powers analytics queries |
| FastAPI | 0.115.0 | Dashboard web framework | Already used; add lifespan + analytics routes |
| uvicorn | 0.32.0 | ASGI server | Already used; embedded in bot.py |
| Jinja2 | 3.1.4 | Template rendering | Already used; analytics page template |
| Telethon | 1.42.0 | Telegram client | Already used; staying on this version |

### Supporting (no new dependencies)
No new packages are needed. All phase 3 requirements can be met with the existing stack:
- Logging: Python stdlib `logging`
- Regex: Python stdlib `re`
- Docker: `docker-compose.yml` configuration
- Nginx: Configuration file (no Python package)
- Analytics: SQL queries via asyncpg

**No `pip install` needed for this phase.**

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw SQL analytics | SQLAlchemy for ORM queries | Overkill for 2 aggregate queries; raw SQL is simpler and already the project pattern |
| Dict-based TTL cache | cachetools or aiocache | Adding a dependency for one cache is not worth it; 5-line dict cache suffices |
| CDN Tailwind | Local Tailwind build | Already using CDN pattern throughout; consistency trumps optimization for internal dashboard |

## Architecture Patterns

### Recommended Project Structure (new/modified files)
```
telebot/
+-- signal_parser.py          # OBS-01: add logging at return-None paths
+-- models.py                 # OBS-04: compiled combined regex for SYMBOL_MAP
+-- dashboard.py              # OBS-03: batch queries; ANLYT-01: analytics route
+-- db.py                     # ANLYT-01: analytics query functions
+-- bot.py                    # INFRA-01: lifespan integration; OBS-01: alert on parse failure
+-- templates/
|   +-- analytics.html        # ANLYT-01: new analytics page
|   +-- base.html             # Add "Analytics" nav link
+-- docker-compose.yml        # INFRA-03: external networks
+-- nginx/
|   +-- telebot.conf          # INFRA-04: nginx reverse proxy config template
+-- docs/
|   +-- server-messages.md    # OBS-02: server message limit documentation
|   +-- telethon-eval.md      # INFRA-02: Telethon 1.42.0 evaluation
```

### Pattern 1: Signal Parser Logging (OBS-01)

**What:** Add structured logging at every `return None` path in `parse_signal()`, plus a heuristic to detect "signal-like" text that failed to parse.

**When to use:** Every `return None` in parse_signal should log the reason.

**Implementation approach:**
```python
# In signal_parser.py

# Heuristic for "signal-like" text detection
_RE_SIGNAL_LIKE = re.compile(
    r"(?:buy|sell|gold|xauusd|sl|tp|entry|close|exit)",
    re.IGNORECASE,
)

def parse_signal(text: str) -> SignalAction | None:
    stripped = text.strip()
    if not stripped:
        return None  # Empty text, no logging needed

    # ... existing parsing logic ...

    # At end: not a recognized signal
    if _RE_SIGNAL_LIKE.search(stripped):
        logger.warning(
            "Signal-like text not parsed: %.200s", stripped
        )
        # Return a flag or let caller handle alert
    return None
```

The caller in `bot.py` should check for signal-like text and fire a Discord alert:
```python
signal = parse_signal(text)
if signal:
    # ... execute ...
elif _is_signal_like(text):
    if notifier:
        await notifier.notify_alert(
            f"PARSE FAILED: Signal-like text not recognized:\n{text[:200]}"
        )
```

**Confidence:** HIGH -- straightforward logging addition.

### Pattern 2: Position Query Batching (OBS-03)

**What:** Replace sequential per-account `get_positions()` calls with `asyncio.gather()`.

**Current N+1 pattern in `_get_all_positions()`:**
```python
# CURRENT: sequential (N+1)
for acct_name, connector in _executor.tm.connectors.items():
    acct_positions = await connector.get_positions()  # One at a time
```

**Batched pattern:**
```python
# FIXED: parallel with asyncio.gather
async def _get_all_positions() -> list[dict]:
    if not _executor:
        return []

    connected = {
        name: conn for name, conn in _executor.tm.connectors.items()
        if conn.connected
    }
    if not connected:
        return []

    # Fetch all accounts in parallel
    results = await asyncio.gather(
        *(conn.get_positions() for conn in connected.values()),
        return_exceptions=True,
    )

    positions = []
    for acct_name, result in zip(connected.keys(), results):
        if isinstance(result, Exception):
            logger.error("Failed to get positions for %s: %s", acct_name, result)
            continue
        for pos in result:
            positions.append({
                "account": acct_name,
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "direction": pos.direction,
                "volume": pos.volume,
                "open_price": pos.open_price,
                "sl": pos.sl,
                "tp": pos.tp,
                "profit": pos.profit,
            })
    return positions
```

**Optional TTL cache (5 seconds):**
```python
_positions_cache: dict = {"data": [], "expires": 0.0}

async def _get_all_positions_cached() -> list[dict]:
    now = time.monotonic()
    if now < _positions_cache["expires"]:
        return _positions_cache["data"]
    data = await _get_all_positions()
    _positions_cache["data"] = data
    _positions_cache["expires"] = now + 5.0
    return data
```

**Confidence:** HIGH -- asyncio.gather is the standard Python pattern for this.

### Pattern 3: Compiled Combined Regex for Symbol Lookup (OBS-04)

**What:** Replace `_extract_symbol_from_text()` linear iteration with a single compiled regex.

**Current O(n) pattern:**
```python
def _extract_symbol_from_text(text: str) -> str:
    lower = text.lower()
    for raw, canonical in SYMBOL_MAP.items():
        if raw in lower:
            return canonical
    return "XAUUSD"
```

**Compiled regex pattern:**
```python
# Build once at module load from SYMBOL_MAP keys
_SYMBOL_PATTERN = re.compile(
    "|".join(re.escape(k) for k in sorted(SYMBOL_MAP.keys(), key=len, reverse=True)),
    re.IGNORECASE,
)

def _extract_symbol_from_text(text: str) -> str:
    match = _SYMBOL_PATTERN.search(text)
    if match:
        return SYMBOL_MAP[match.group().lower()]
    return "XAUUSD"
```

Sorting by length descending ensures `xau/usd` matches before `xau`. The regex engine handles this in a single pass.

**Confidence:** HIGH -- standard optimization; sorted-by-length ensures correct match priority.

### Pattern 4: Analytics SQL Queries (ANLYT-01)

**What:** Calculate win rate and profit factor from existing `trades` table.

**Win rate:** Percentage of closed trades with positive P&L.
**Profit factor:** Sum of winning P&L / abs(sum of losing P&L).

```sql
-- Per-symbol analytics
SELECT
    symbol,
    COUNT(*) FILTER (WHERE status = 'closed') AS total_trades,
    COUNT(*) FILTER (WHERE status = 'closed' AND pnl > 0) AS winning_trades,
    COUNT(*) FILTER (WHERE status = 'closed' AND pnl <= 0) AS losing_trades,
    ROUND(
        COUNT(*) FILTER (WHERE status = 'closed' AND pnl > 0)::numeric
        / NULLIF(COUNT(*) FILTER (WHERE status = 'closed'), 0) * 100, 1
    ) AS win_rate,
    COALESCE(SUM(pnl) FILTER (WHERE status = 'closed' AND pnl > 0), 0) AS gross_profit,
    COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'closed' AND pnl <= 0)), 0) AS gross_loss,
    CASE
        WHEN COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'closed' AND pnl <= 0)), 0) = 0
        THEN NULL
        ELSE ROUND(
            COALESCE(SUM(pnl) FILTER (WHERE status = 'closed' AND pnl > 0), 0)::numeric
            / ABS(SUM(pnl) FILTER (WHERE status = 'closed' AND pnl <= 0)), 2
        )
    END AS profit_factor,
    COALESCE(SUM(pnl) FILTER (WHERE status = 'closed'), 0) AS net_pnl
FROM trades
WHERE status = 'closed'
GROUP BY symbol
ORDER BY total_trades DESC;
```

This uses PostgreSQL `FILTER (WHERE ...)` aggregate syntax, which is clean and efficient. No new tables needed -- the existing `trades` table already has `symbol`, `status`, `pnl`, and `close_time`.

**Future-proofing for signal source:** The `signals` table has `id` which is referenced by `trades.signal_id`. When multiple signal sources are added, a `source` column can be added to `signals` and the analytics query joined through `signal_id`. For now, single-source means no JOIN needed.

**Confidence:** HIGH -- PostgreSQL FILTER syntax verified; trades table schema confirmed.

### Pattern 5: FastAPI Lifespan (INFRA-01)

**What:** Replace bare `asyncio.create_task(server.serve())` with proper ASGI lifespan management.

**Current problem in bot.py (lines 271-289):**
- Uvicorn launched as fire-and-forget `asyncio.create_task`
- No shutdown handler for SIGTERM
- No cleanup of db pool, executor background tasks, or HTTP client
- `client.run_until_disconnected()` blocks until Telethon disconnects, but uvicorn has no shutdown coordination

**Solution -- FastAPI lifespan context manager:**
```python
# In dashboard.py
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: nothing extra needed (init_dashboard called before)
    logger.info("Dashboard ASGI lifespan: startup")
    yield
    # Shutdown: clean up
    logger.info("Dashboard ASGI lifespan: shutdown")
    if _executor:
        await _executor.stop()
    await db.close_db()

app = FastAPI(title="Telebot Dashboard", docs_url=None, redoc_url=None, lifespan=lifespan)
```

**Key insight:** The lifespan shutdown runs when uvicorn receives SIGTERM. This is the correct place to call `executor.stop()` and `db.close_db()`. The Docker `stop_grace_period` (default 10s) gives uvicorn time to complete the shutdown sequence.

**Bot.py changes:**
- Add signal handlers for SIGTERM/SIGINT that trigger graceful Telethon disconnect
- Ensure `db.close_db()` is called in all exit paths
- The uvicorn `--timeout-graceful-shutdown` can be set via config

**Confidence:** HIGH -- FastAPI lifespan is the official recommended pattern; verified from official docs.

### Pattern 6: Docker Compose External Networks (INFRA-03)

**What:** Production docker-compose.yml joins proxy-net and data-net.

```yaml
services:
  telebot:
    build: .
    container_name: telebot
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./accounts.json:/app/accounts.json:ro
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - proxy-net
      - data-net

networks:
  proxy-net:
    name: proxy-net
    external: true
  data-net:
    name: data-net
    external: true
```

**Key changes from current:**
- Remove `ports: - "8080:8080"` -- nginx handles external access, no direct port exposure
- Add `networks` section for both proxy-net and data-net
- Container is accessible to nginx via `telebot:8080` on proxy-net
- Container reaches PostgreSQL via data-net hostname

**Confidence:** HIGH -- Docker Compose external network syntax verified from official docs.

### Pattern 7: Nginx Config Template (INFRA-04)

**What:** nginx server block for reverse-proxying the dashboard with SSL.

```nginx
# nginx/telebot.conf
# Copy to /home/murx/shared/nginx/conf.d/telebot.conf on VPS

server {
    listen 80;
    server_name dashboard.YOURDOMAIN.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name dashboard.YOURDOMAIN.com;

    ssl_certificate /etc/letsencrypt/live/dashboard.YOURDOMAIN.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dashboard.YOURDOMAIN.com/privkey.pem;

    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        proxy_pass http://telebot:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE support (critical for /stream endpoint)
        proxy_buffering off;
        proxy_cache off;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_read_timeout 86400s;  # 24h for SSE
    }
}
```

**Critical for SSE:** The dashboard has a `/stream` SSE endpoint. Nginx defaults to buffering responses, which breaks SSE. `proxy_buffering off` and `proxy_cache off` are required. The `Connection ''` header (empty) keeps the connection alive for SSE without upgrade semantics (which is for WebSocket). `proxy_read_timeout 86400s` prevents nginx from closing the SSE stream prematurely.

**The dashboard also sets `X-Accel-Buffering: no`** in the SSE response headers (line 359 of dashboard.py), which tells nginx to disable buffering per-response. This is a belt-and-suspenders approach.

**Confidence:** HIGH -- nginx SSE proxy configuration verified from multiple sources.

### Anti-Patterns to Avoid
- **Don't add background analytics jobs:** User decision is calculate-on-page-load. No caching layer, no periodic computation, no celery/background tasks.
- **Don't expose ports in docker-compose:** With proxy-net, nginx handles external access. Exposing 8080 directly bypasses HTTPS.
- **Don't use `@app.on_event("startup")`:** This is deprecated in FastAPI. Use lifespan context manager.
- **Don't JOIN signals table for analytics yet:** Single signal source means no source grouping needed. Query trades table directly. Schema future-proofs by keeping signal_id FK.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SSE through nginx | Custom SSE buffering workaround | `proxy_buffering off` + `X-Accel-Buffering: no` | Already handled by nginx config directives |
| Position cache invalidation | Complex cache invalidation logic | Simple monotonic-clock TTL dict | 5-second TTL is sufficient; positions change rarely |
| Analytics calculations in Python | Python-side aggregation loops | PostgreSQL FILTER + aggregate SQL | Database handles grouping, NULL safety, and division-by-zero |
| Docker networking | Manual container linking or host networking | Docker Compose external networks | Standard Docker pattern for multi-compose communication |
| SSL termination | Self-signed certs or app-level TLS | Certbot via shared container | Already running on VPS; just reference cert paths |

**Key insight:** All infrastructure components (nginx, certbot, PostgreSQL, Docker networks) already exist on the VPS. This phase only creates config files to plug into them.

## Common Pitfalls

### Pitfall 1: Nginx Buffers Break SSE
**What goes wrong:** Dashboard SSE stream (/stream) works locally but freezes behind nginx -- events batch up and arrive in chunks instead of real-time.
**Why it happens:** Nginx enables response buffering by default. SSE requires each `data: ...\n\n` frame to be flushed immediately.
**How to avoid:** Set `proxy_buffering off` in nginx location block AND keep the existing `X-Accel-Buffering: no` header in dashboard.py SSE response.
**Warning signs:** Dashboard stops auto-refreshing after deploying behind nginx; browser Network tab shows SSE connection but no events.

### Pitfall 2: Docker Network Not Found on First Deploy
**What goes wrong:** `docker compose up` fails with "network proxy-net not found" because the shared services haven't created the external networks yet.
**Why it happens:** `external: true` means Compose expects the network to already exist; it won't create it.
**How to avoid:** Document the prerequisite: `docker network create proxy-net && docker network create data-net` must be run (or shared services compose must be up first). Add a note in deployment docs.
**Warning signs:** Container fails to start with network-related error on fresh VPS or after Docker daemon restart.

### Pitfall 3: Analytics Division by Zero
**What goes wrong:** Profit factor calculation divides by zero when there are no losing trades (or no trades at all).
**Why it happens:** `SUM(pnl) FILTER (WHERE pnl <= 0)` returns 0 for all-winning streaks.
**How to avoid:** Use `NULLIF(..., 0)` in the divisor. Display "N/A" or infinity symbol in the template when profit_factor is NULL.
**Warning signs:** HTTP 500 on analytics page when all trades are winners (ironically, a "good" scenario).

### Pitfall 4: Lifespan Shutdown Not Called When Bot Crashes
**What goes wrong:** If Telethon raises an unhandled exception, `client.run_until_disconnected()` exits but uvicorn's lifespan shutdown may not fire because the process terminates.
**Why it happens:** `asyncio.create_task(server.serve())` creates the uvicorn task, but if the main coroutine crashes, asyncio cancels all tasks without waiting for shutdown.
**How to avoid:** Wrap the main function in try/finally that explicitly calls cleanup. Register atexit handler as backup.
**Warning signs:** Database connections left open after crash; "connection reset" errors on next startup.

### Pitfall 5: Signal-Like Heuristic Too Broad
**What goes wrong:** Every casual message mentioning "gold" or "buy" triggers a Discord "PARSE FAILED" alert, flooding the alerts channel.
**Why it happens:** Heuristic matches common words that appear in normal conversation.
**How to avoid:** Require multiple trading keywords in the same message (e.g., "buy" AND a price-like number). Use a score threshold rather than single keyword match. Consider message length -- very short messages with trading terms are more likely signals.
**Warning signs:** Dozens of false-positive parse failure alerts per day.

### Pitfall 6: asyncio.gather Exception Swallowing
**What goes wrong:** One account's `get_positions()` raises an exception, but `return_exceptions=True` silently captures it, and the dashboard shows incomplete data without any indication.
**Why it happens:** `asyncio.gather(return_exceptions=True)` returns exceptions as values rather than raising them.
**How to avoid:** Always check `isinstance(result, Exception)` in the result loop and log errors. Consider adding a visual indicator on the dashboard when an account's data is stale.
**Warning signs:** Dashboard shows fewer positions than expected; no error in logs.

## Code Examples

### Analytics Query Function (db.py)
```python
# Source: PostgreSQL FILTER aggregate syntax
async def get_analytics_by_symbol() -> list[dict]:
    """Get win rate, profit factor, and trade stats grouped by symbol."""
    rows = await _pool.fetch("""
        SELECT
            symbol,
            COUNT(*) AS total_trades,
            COUNT(*) FILTER (WHERE pnl > 0) AS wins,
            COUNT(*) FILTER (WHERE pnl <= 0) AS losses,
            ROUND(
                COUNT(*) FILTER (WHERE pnl > 0)::numeric
                / NULLIF(COUNT(*), 0) * 100, 1
            ) AS win_rate,
            COALESCE(SUM(pnl) FILTER (WHERE pnl > 0), 0) AS gross_profit,
            COALESCE(ABS(SUM(pnl) FILTER (WHERE pnl <= 0)), 0) AS gross_loss,
            CASE
                WHEN COALESCE(ABS(SUM(pnl) FILTER (WHERE pnl <= 0)), 0) = 0
                THEN NULL
                ELSE ROUND(
                    COALESCE(SUM(pnl) FILTER (WHERE pnl > 0), 0)::numeric
                    / ABS(SUM(pnl) FILTER (WHERE pnl <= 0)), 2
                )
            END AS profit_factor,
            COALESCE(SUM(pnl), 0) AS net_pnl
        FROM trades
        WHERE status = 'closed'
        GROUP BY symbol
        ORDER BY total_trades DESC
    """)
    return [dict(r) for r in rows]


async def get_analytics_summary() -> dict:
    """Get overall analytics summary (all symbols combined)."""
    row = await _pool.fetchrow("""
        SELECT
            COUNT(*) AS total_trades,
            COUNT(*) FILTER (WHERE pnl > 0) AS wins,
            COUNT(*) FILTER (WHERE pnl <= 0) AS losses,
            ROUND(
                COUNT(*) FILTER (WHERE pnl > 0)::numeric
                / NULLIF(COUNT(*), 0) * 100, 1
            ) AS win_rate,
            COALESCE(SUM(pnl) FILTER (WHERE pnl > 0), 0) AS gross_profit,
            COALESCE(ABS(SUM(pnl) FILTER (WHERE pnl <= 0)), 0) AS gross_loss,
            CASE
                WHEN COALESCE(ABS(SUM(pnl) FILTER (WHERE pnl <= 0)), 0) = 0
                THEN NULL
                ELSE ROUND(
                    COALESCE(SUM(pnl) FILTER (WHERE pnl > 0), 0)::numeric
                    / ABS(SUM(pnl) FILTER (WHERE pnl <= 0)), 2
                )
            END AS profit_factor,
            COALESCE(SUM(pnl), 0) AS net_pnl
        FROM trades
        WHERE status = 'closed'
    """)
    return dict(row) if row else {}
```

### Signal-Like Detection Heuristic (signal_parser.py)
```python
# Multi-keyword heuristic to reduce false positives
_SIGNAL_KEYWORDS = {"buy", "sell", "sl", "tp", "entry", "close", "exit"}
_RE_PRICE_LIKE = re.compile(r"\b\d{3,5}(?:\.\d{1,2})?\b")

def is_signal_like(text: str) -> bool:
    """Heuristic: does this text look like it might be a trading signal?

    Requires at least 2 trading keywords OR 1 keyword + a price-like number.
    """
    lower = text.lower()
    keyword_count = sum(1 for kw in _SIGNAL_KEYWORDS if kw in lower)
    has_price = bool(_RE_PRICE_LIKE.search(text))

    if keyword_count >= 2:
        return True
    if keyword_count >= 1 and has_price:
        return True
    return False
```

### FastAPI Lifespan Integration (dashboard.py)
```python
# Source: https://fastapi.tiangolo.com/advanced/events/
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Dashboard ASGI lifespan: startup complete")
    yield
    # Shutdown -- clean up resources
    logger.info("Dashboard ASGI lifespan: shutting down")
    if _executor:
        await _executor.stop()
    import db as _db
    await _db.close_db()

app = FastAPI(
    title="Telebot Dashboard",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `@app.on_event("startup")` / `@app.on_event("shutdown")` | `lifespan` async context manager | FastAPI 0.93+ (2023) | Old events are deprecated; lifespan is the only supported approach going forward |
| Docker Compose v1 `links` | Docker Compose v2 external networks | Docker Compose v2 (2022) | `links` is legacy; external named networks are the standard for multi-project communication |
| Telethon 1.x | Telethon 2.x (alpha) | In development | 2.x is not stable; 1.42.0 is the correct choice for production |

**Deprecated/outdated:**
- `@app.on_event("startup")` / `@app.on_event("shutdown")`: Deprecated in FastAPI. Use `lifespan` parameter.
- Docker Compose `links`: Legacy feature. Use named networks instead.
- Telethon 2.x: Alpha quality with breaking changes. Not suitable for production.

## Telethon 1.42.0 Evaluation Summary (INFRA-02)

**Current status:** 1.42.0 is the latest stable release (November 2025). It is the current version in requirements.txt.

**Python compatibility:** Supports Python 3.9+. Added support for Python 3.14 in 1.42.0.

**Security posture:**
- No known CVEs specifically targeting Telethon 1.42.0 (verified via Snyk advisory)
- The changelog shows connection error handling improvements across versions
- File download safety improvement in 1.42.0: "removed potential misuse when downloading files using inferred path"

**Deprecations in Telethon affecting this project:**
- `force_sms` and `sign_up` deprecated (not used in this project)
- `imghdr` no longer used internally (Python 3.13+ compatibility)

**Recommendation:** Stay on 1.42.0. No action required. Document findings in `docs/telethon-eval.md`.

**Confidence:** HIGH -- PyPI and official docs confirm 1.42.0 is current stable.

## Open Questions

1. **VPS shared nginx config directory path**
   - What we know: Shared services at `/home/murx/shared`, nginx runs in shared container
   - What's unclear: Exact path where nginx conf.d files are mounted (e.g., `/home/murx/shared/nginx/conf.d/` or similar)
   - Recommendation: Use placeholder `NGINX_CONF_DIR` in deployment docs; user fills in during deployment

2. **SSL certificate hostname**
   - What we know: User will create a subdomain for the dashboard; certbot runs in shared container
   - What's unclear: The actual subdomain name (e.g., `dashboard.example.com`)
   - Recommendation: Use `dashboard.YOURDOMAIN.com` placeholder in nginx config template

3. **Server message limit semantics (OBS-02)**
   - What we know: `max_daily_server_messages = 500` exists in GlobalConfig; `server_messages` is tracked in daily_stats
   - What's unclear: Whether "server message" maps to a specific MT5 broker concept or is a bot-internal limit
   - Recommendation: Document as bot-internal safety limit; note that MT5 brokers may have their own limits that should be checked per-broker

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (not yet installed -- Phase 4 scope) |
| Config file | None -- no pytest.ini or pyproject.toml exists |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v --tb=short` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OBS-01 | parse_signal returns None with logging; signal-like detection | unit | `python -m pytest tests/test_signal_parser.py::test_parse_failure_logging -x` | No -- Wave 0 |
| OBS-02 | Documentation only | manual-only | N/A (review docs/server-messages.md) | N/A |
| OBS-03 | Batched position queries via asyncio.gather | unit | `python -m pytest tests/test_dashboard.py::test_batch_positions -x` | No -- Wave 0 |
| OBS-04 | Compiled regex symbol lookup produces same results | unit | `python -m pytest tests/test_signal_parser.py::test_compiled_symbol_lookup -x` | No -- Wave 0 |
| ANLYT-01 | Analytics SQL returns correct win rate / profit factor | unit | `python -m pytest tests/test_analytics.py -x` | No -- Wave 0 |
| INFRA-01 | Lifespan shutdown calls cleanup | unit | `python -m pytest tests/test_dashboard.py::test_lifespan_shutdown -x` | No -- Wave 0 |
| INFRA-02 | Documentation only | manual-only | N/A (review docs/telethon-eval.md) | N/A |
| INFRA-03 | Docker compose has correct external networks | smoke | `docker compose -f docker-compose.yml config` (validates YAML) | N/A |
| INFRA-04 | Nginx config syntax valid | smoke | `nginx -t -c nginx/telebot.conf` (requires nginx installed) | N/A |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/ -x -q` (when test files exist)
- **Per wave merge:** Full suite
- **Phase gate:** `docker compose -f docker-compose.yml config` passes; key unit tests pass

### Wave 0 Gaps
Note: Full test infrastructure (pytest, requirements-dev.txt) is Phase 4 scope (TEST-01). For Phase 3, validation focuses on:
- [ ] Manual verification: analytics page loads with correct calculations
- [ ] Manual verification: `docker compose config` validates the compose file
- [ ] Manual verification: nginx config syntax check
- [ ] Smoke test: signal parser logging produces output when parse fails

## Sources

### Primary (HIGH confidence)
- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/) -- lifespan context manager pattern
- [Docker Compose Networking](https://docs.docker.com/compose/how-tos/networking/) -- external network syntax
- [Docker Compose Networks Reference](https://docs.docker.com/reference/compose-file/networks/) -- network configuration schema
- [Telethon Changelog](https://docs.telethon.dev/en/stable/misc/changelog.html) -- version history and 1.42.0 changes
- [Telethon PyPI](https://pypi.org/project/Telethon/) -- latest version confirmation (1.42.0, Nov 2025)
- [asyncpg PyPI](https://pypi.org/project/asyncpg/) -- version 0.31.0 confirmed
- [FastAPI PyPI](https://pypi.org/project/fastapi/) -- latest 0.135.1 (Mar 2026); project uses 0.115.0

### Secondary (MEDIUM confidence)
- [Nginx SSE Configuration](https://oneuptime.com/blog/post/2025-12-16-server-sent-events-nginx/view) -- proxy_buffering off for SSE
- [DigitalOcean Nginx SSE](https://www.digitalocean.com/community/questions/nginx-optimization-for-server-sent-events-sse) -- SSE nginx optimization
- [Communication Between Docker Compose Projects](https://www.baeldung.com/ops/docker-compose-communication) -- external network patterns

### Tertiary (LOW confidence)
- Server message limit semantics: Based on code analysis only. No MT5 documentation found to confirm whether brokers enforce a specific "server message" quota.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies; all existing packages confirmed
- Architecture patterns: HIGH -- all patterns verified from official docs or standard Python idioms
- Observability (OBS-01 through OBS-04): HIGH -- straightforward Python logging, regex, asyncio changes
- Analytics (ANLYT-01): HIGH -- PostgreSQL FILTER syntax verified; trades table schema confirmed
- Infrastructure (INFRA-01 through INFRA-04): HIGH -- Docker, nginx, FastAPI lifespan all well-documented
- Pitfalls: HIGH -- based on direct code analysis and verified nginx/Docker behavior

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable domain; no fast-moving dependencies)

---
*Phase: 03-observability-infrastructure*
*Research completed: 2026-03-22*
