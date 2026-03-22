# Phase 3: Observability & Infrastructure - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Signal logging, dashboard fixes, analytics, and deployment hardening. Operational problems are visible before they become outages, and the deployment is production-hardened.

Requirements: OBS-01, OBS-02, OBS-03, OBS-04, ANLYT-01, INFRA-01, INFRA-02, INFRA-03, INFRA-04

</domain>

<decisions>
## Implementation Decisions

### VPS Docker + Nginx setup
- Production docker-compose.yml stays **standalone** — joins shared services via external networks
- Two external networks: **`proxy-net`** (nginx reverse proxy) and **`data-net`** (PostgreSQL access)
- Telebot container joins both networks: proxy-net for dashboard HTTPS, data-net for DATABASE_URL
- User will create a **subdomain** for the dashboard (not set up yet — provide nginx config template)
- **Certbot runs in shared container** — nginx config should use existing cert paths
- DATABASE_URL in production .env points to shared PostgreSQL via data-net hostname

### Signal accuracy dashboard
- **Single signal source** for now (one Telegram group) — no per-source grouping needed yet, but schema should support it for future
- Display on a **new /analytics dashboard page** with win rate, profit factor, total trades
- **Calculate on page load** — query database directly, no background job or caching
- Group by symbol for now (since only one source) — show per-symbol win rate and profit factor

### Telethon version
- **Stay on 1.42.0** — document only, no version change
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Signal parser
- `signal_parser.py` — Regex-based signal detection. OBS-01 needs logging when parse_signal returns None.
- `models.py:SYMBOL_MAP` — Symbol mapping dict. OBS-04 needs compiled regex for this.

### Dashboard
- `dashboard.py` — FastAPI endpoints, HTMX partials, _get_all_positions (N+1 query target for OBS-03)
- `templates/overview.html` — Page structure for reference when creating analytics page

### Infrastructure
- `docker-compose.yml` — Production compose, needs external networks added
- `docker-compose.dev.yml` — Local dev compose (Phase 2), reference for structure
- `bot.py:259-275` — Uvicorn dashboard launch (INFRA-01 lifecycle target)
- `Dockerfile` — Current build config

### VPS layout (from memory)
- Shared services at `/home/murx/shared` with proxy-net and data-net external networks
- Apps at `/home/murx/apps` — telebot lives here in production
- Certbot in shared container with existing SSL certs

### Concerns
- `.planning/codebase/CONCERNS.md` — Signal parser fragility, dashboard N+1, regex performance
- `.planning/research/PITFALLS.md` — Dashboard blocking Telegram handler

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `notifier.py:notify_alert()` — Already used for Discord alerts, wire for OBS-01 signal parse failures
- `dashboard.py:_get_all_positions()` — Current N+1 pattern to fix for OBS-03
- `db.py` — asyncpg pool ready for analytics queries
- `templates/base.html` — Dashboard base template for new analytics page

### Established Patterns
- HTMX partials for live-updating dashboard sections
- FastAPI endpoints with HTTP Basic auth
- Jinja2 templates with Tailwind CSS classes

### Integration Points
- `signal_parser.py:parse_signal()` — Add logging before return None paths
- `bot.py` — Add parse failure alert after parse_signal returns None for signal-like text
- `docker-compose.yml` — Add networks section pointing to proxy-net and data-net
- New `nginx/telebot.conf` — Nginx config for shared reverse proxy

</code_context>

<specifics>
## Specific Ideas

- Only one signal source (Telegram group) for now — analytics shows per-symbol breakdown
- Nginx config should be a template file in the repo that gets copied to VPS shared nginx config dir
- Production DATABASE_URL will reference the shared PostgreSQL via data-net container hostname

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-observability-infrastructure*
*Context gathered: 2026-03-22*
