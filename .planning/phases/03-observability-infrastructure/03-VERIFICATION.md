---
phase: 03-observability-infrastructure
verified: 2026-03-22T19:45:00Z
status: gaps_found
score: 4/5 success criteria verified
re_verification: false
gaps:
  - truth: "DB archival command exists and moves records older than 3 months to archive files"
    status: failed
    reason: "archive_old_trades() function exists in db.py but is never called from a CLI entry point or maintenance command. ROADMAP success criterion 5 requires a runnable command, not just an internal function."
    artifacts:
      - path: "db.py"
        issue: "archive_old_trades() defined but orphaned — no caller exists outside db.py"
    missing:
      - "A maintenance CLI script or bot.py --archive flag that invokes archive_old_trades() from the command line"
human_verification:
  - test: "Docker networking and nginx reverse proxy"
    expected: "Bot accessible to nginx on proxy-net as telebot:8080; dashboard reachable via HTTPS with SSE streaming working"
    why_human: "Requires VPS deployment with docker network create proxy-net data-net and actual nginx service"
  - test: "Discord parse failure alert delivery"
    expected: "When a Telegram message matching the signal-like heuristic fails to parse, a Discord message appears in the alerts channel starting with 'PARSE FAILED:'"
    why_human: "Requires live Telegram + Discord connections to observe end-to-end"
---

# Phase 3: Observability & Infrastructure Verification Report

**Phase Goal:** Operational problems are visible before they become outages, and the deployment is production-hardened
**Verified:** 2026-03-22T19:45:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (from ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | When signal-like text fails to parse, detailed reason logged and Discord alert sent | VERIFIED | `is_signal_like()` in signal_parser.py; `elif is_signal_like(text)` + `notify_alert("PARSE FAILED: ...")` in bot.py lines 270-275 |
| 2 | Dashboard position data fetched without N+1; no per-position round-trips to MT5 | VERIFIED | `_get_all_positions()` in dashboard.py uses `asyncio.gather(*(...get_positions()...), return_exceptions=True)` |
| 3 | Signal accuracy (win rate, profit factor) per symbol visible on dashboard | VERIFIED | `get_analytics_by_symbol()` and `get_analytics_summary()` in db.py; `/analytics` route in dashboard.py; `templates/analytics.html` renders per-symbol table |
| 4 | Dashboard has proper ASGI lifecycle; graceful SIGTERM shutdown; nginx + Docker config applied | VERIFIED | `lifespan` context manager in dashboard.py with `close_db()` call; SIGTERM/SIGINT handlers + `shutdown_event` + `finally:` block in bot.py; docker-compose.yml uses external networks; nginx/telebot.conf exists |
| 5 | Telethon compatibility documented; DB archival command exists and moves records older than 3 months | PARTIAL | Telethon eval doc exists (`docs/telethon-eval.md`). `archive_old_trades()` function defined in db.py but NOT exposed as a runnable CLI command. |

**Score:** 4/5 truths verified (criterion 5 is partial — Telethon side passes, archival command side fails)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `signal_parser.py` | `is_signal_like()`, warning at final return-None, `_SYMBOL_PATTERN` import | VERIFIED | All three present at lines 113-131, 213-216, 13 |
| `models.py` | `_SYMBOL_PATTERN` compiled from SYMBOL_MAP keys, sorted by length desc | VERIFIED | Lines 31-34; `_re.IGNORECASE` flag; keys sorted `key=len, reverse=True` |
| `bot.py` | `is_signal_like` import; `elif is_signal_like(text)` branch; `notify_alert("PARSE FAILED...")` | VERIFIED | Lines 15, 270-275 |
| `docs/server-messages.md` | Server message limit documentation | VERIFIED | Covers write operations, daily_stats tracking, configuration, MT5 broker limits |
| `db.py` | `get_analytics_by_symbol()` and `get_analytics_summary()` with NULLIF division-by-zero handling | VERIFIED | Lines 348-408; NULLIF and CASE guards present; empty-state default dict returned |
| `dashboard.py` | `asyncio.gather` batched positions; `/analytics` route; `lifespan` context manager | VERIFIED | Lines 68-85, 154-163, 411-412 |
| `templates/analytics.html` | Summary cards, per-symbol table, None profit_factor handled, empty state handled | VERIFIED | Full template at correct path; all conditional rendering confirmed |
| `templates/base.html` | Analytics nav link with active state | VERIFIED | Line 54: `href="/analytics"` with `{% if page == 'analytics' %}nav-active{% endif %}` |
| `docker-compose.yml` | External networks proxy-net and data-net; no direct port exposure | VERIFIED | No `ports:` section; service joins both networks; both declared `external: true` |
| `nginx/telebot.conf` | HTTPS reverse proxy with SSE support, security headers, YOURDOMAIN placeholder | VERIFIED | `proxy_buffering off`, `proxy_cache off`, `proxy_read_timeout 86400s`, 4 security headers |
| `Dockerfile` | Copies `docs/` and `nginx/` directories | VERIFIED | Lines 14-15 |
| `docs/telethon-eval.md` | Version-locked decision, security assessment, 2.x alpha note | VERIFIED | Decision to stay on 1.42.0; no known CVEs; 2.x not suitable; evaluation date 2026-03-22 |
| `db.py` (archival) | `archive_old_trades()` callable as maintenance command | ORPHANED | Function defined in db.py lines 414-454 but no CLI entrypoint calls it |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `bot.py` | `signal_parser.py` | `is_signal_like()` import + `elif is_signal_like(text)` call | WIRED | Confirmed at lines 15, 270 |
| `bot.py` | `notifier.py` | `notify_alert()` called with "PARSE FAILED:" message | WIRED | Confirmed at lines 273-274 |
| `signal_parser.py` | `models.py` | `_SYMBOL_PATTERN` import used in `_extract_symbol_from_text()` | WIRED | Import line 13; usage lines 272-274 |
| `dashboard.py` | `db.py` | `get_analytics_by_symbol()` and `get_analytics_summary()` in `/analytics` route | WIRED | Lines 156-157 |
| `dashboard.py` | `templates/analytics.html` | `TemplateResponse("analytics.html", ...)` | WIRED | Line 158 |
| `templates/base.html` | `/analytics` route | nav link href | WIRED | Line 54 |
| `dashboard.py` | `db.py` | `close_db()` called in lifespan shutdown | WIRED | Lines 80-82 |
| `docker-compose.yml` | `nginx/telebot.conf` | telebot container accessible on proxy-net as telebot:8080 | WIRED | `proxy-net` in both; nginx proxies to `http://telebot:8080` |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| OBS-01 | 03-01 | Signal parser logs reason when parse_signal returns None; Discord alert on signal-like text | SATISFIED | `is_signal_like()` heuristic + warning log at line 215; `elif is_signal_like` + `notify_alert` in bot.py |
| OBS-02 | 03-01 | Server message limits documented | SATISFIED | `docs/server-messages.md` covers write ops, tracking, config, broker limits |
| OBS-03 | 03-02 | Dashboard position queries batched; no N+1 | SATISFIED | `asyncio.gather` in `_get_all_positions()` with `return_exceptions=True` |
| OBS-04 | 03-01 | Symbol map uses compiled combined regex | SATISFIED | `_SYMBOL_PATTERN` in models.py; `_extract_symbol_from_text()` uses `.search()` |
| ANLYT-01 | 03-02 | Win rate and profit factor per symbol in DB and on dashboard | SATISFIED | SQL analytics functions in db.py; `/analytics` page with per-symbol table |
| INFRA-01 | 03-03 | Dashboard uses proper ASGI lifecycle; graceful shutdown on SIGTERM | SATISFIED | `lifespan` context manager; SIGTERM handler + `shutdown_event` + `finally:` cleanup |
| INFRA-02 | 03-03 | Telethon version evaluated; version-locked decision documented | SATISFIED | `docs/telethon-eval.md` with version-locked decision, security assessment, 2.x evaluation |
| INFRA-03 | 03-03 | Docker compose joins shared services network | SATISFIED | `docker-compose.yml` joins `proxy-net` and `data-net` as external networks; no host ports exposed |
| INFRA-04 | 03-03 | Nginx reverse proxy configuration provided | SATISFIED | `nginx/telebot.conf` with HTTPS, SSE support (`proxy_buffering off`), security headers |

**Note on DB-03:** REQUIREMENTS.md maps DB-03 to Phase 2 (not Phase 3). None of the Phase 3 plans claim DB-03. However, ROADMAP Phase 3 success criterion 5 includes "DB archival command exists." The `archive_old_trades()` function was implemented in Phase 2 (02-02-PLAN.md) and exists in db.py, but has no runnable CLI entry point. This gap is in the ROADMAP success criteria scope and must be addressed.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `db.py` | 414 | `archive_old_trades()` defined but never called | Warning | Function is orphaned — ROADMAP criterion 5 requires a runnable command |
| `bot.py` | 332 | `import db as _db_module` inside `finally:` block | Info | Late import in finally block — functional but unconventional; no goal impact |

No placeholder components, empty handlers, or stub implementations found across modified files.

### Human Verification Required

#### 1. Docker Network Connectivity

**Test:** Deploy to VPS with `docker network create proxy-net && docker network create data-net`, then `docker compose up -d`. Verify the bot container can reach PostgreSQL via the data-net hostname, and nginx can proxy to `telebot:8080` on proxy-net.
**Expected:** Dashboard accessible at configured HTTPS domain; no "host not found" connection errors in logs.
**Why human:** Requires live VPS with shared nginx container on proxy-net and PostgreSQL on data-net.

#### 2. HTTPS Dashboard and SSE Stream

**Test:** After nginx config deployment, access `https://dashboard.YOURDOMAIN.com/` and navigate to the Overview page. Let the SSE stream run for 30+ seconds.
**Expected:** Page loads with HTTPS; `/stream` SSE endpoint stays connected (nginx `proxy_read_timeout 86400s` prevents timeout); no buffering artifacts.
**Why human:** Requires live domain, Let's Encrypt certificate, and nginx reload.

#### 3. Discord Parse Failure Alert

**Test:** In a monitored Telegram channel, send a message like "gold sell 2450 sl 2460" (invalid signal: SELL but SL above entry). Observe Discord alerts channel.
**Expected:** A Discord message appears saying "PARSE FAILED: Signal-like text not recognized:" followed by the message text.
**Why human:** Requires live Telegram session + Discord webhook connected; can't verify end-to-end without real connections.

### Gaps Summary

One gap blocks full goal achievement:

**DB archival CLI command missing.** ROADMAP Phase 3 success criterion 5 states "DB archival command exists and moves records older than 3 months to archive files." The `archive_old_trades()` async function exists in db.py (implemented in Phase 2, lines 414-454) and is fully substantive. However, it has no runnable entry point — no CLI script, no argparse handler in bot.py, and no maintenance command. An operator cannot run archival from the command line or as a scheduled task. The fix is small: add a maintenance script (e.g. `maintenance.py --archive`) or a bot.py `--archive` flag that calls `archive_old_trades()`.

All 9 requirement IDs (OBS-01, OBS-02, OBS-03, OBS-04, ANLYT-01, INFRA-01, INFRA-02, INFRA-03, INFRA-04) are fully satisfied by the implemented code. The gap is in a ROADMAP success criterion that references work spanning Phase 2 and Phase 3.

---

_Verified: 2026-03-22T19:45:00Z_
_Verifier: Claude (gsd-verifier)_
