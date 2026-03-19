# Codebase Structure

**Analysis Date:** 2026-03-19

## Directory Layout

```
/Users/murx/Developer/personal/telebot/
├── bot.py                       # Main entry point — Telegram listener + trading orchestrator
├── config.py                    # Environment loading and Settings dataclass
├── models.py                    # Shared data models (SignalAction, AccountConfig, etc.)
├── signal_parser.py             # Parse raw Telegram text into SignalAction objects
├── risk_calculator.py           # Lot sizing and jitter logic
├── trade_manager.py             # Trade execution orchestration per account
├── executor.py                  # Staggered multi-account execution wrapper
├── mt5_connector.py             # Abstract MT5 broker interface (pluggable backends)
├── notifier.py                  # Discord notification router
├── discord_sender.py            # Discord webhook client with retry logic
├── db.py                        # SQLite async wrapper for audit logs
├── dashboard.py                 # FastAPI web dashboard app
├── generate_session.py          # One-time utility: generate Telegram StringSession
├── list_groups.py               # One-time utility: list Telegram groups
├── requirements.txt             # Python dependency pins
├── Dockerfile                   # Container image definition
├── docker-compose.yml           # Multi-service orchestration (single service: bot)
├── .env                         # Runtime environment variables (secrets, not committed)
├── .env.example                 # Template for all required env vars
├── accounts.example.json        # Template for MT5 account configuration
├── signal_keywords.json         # Optional: keyword mappings for signal detection
├── .dockerignore                # Files excluded from Docker image
├── .gitignore                   # Git exclusions
├── VPS_DEPLOYMENT_GUIDE.md      # Deployment instructions
├── README.md                    # Project overview
├── test_signal_parser.py        # Unit tests for signal parsing (30+ cases)
├── test_trade_manager.py        # Unit tests for trade execution
├── test_risk_calculator.py      # Unit tests for lot sizing
├── static/                      # Web assets (CSS, JS, images)
│   └── .gitkeep
├── templates/                   # Jinja2 HTML templates for dashboard
│   ├── base.html                # Base layout with sidebar navigation
│   ├── overview.html            # Dashboard home — account balances, quick stats
│   ├── positions.html           # Current open positions with quick actions
│   ├── history.html             # Trade execution history with P&L
│   ├── signals.html             # Signal audit log — all parsed signals
│   ├── settings.html            # Configuration panel (manual controls)
│   └── partials/
│       ├── overview_cards.html  # Card component (injected via HTMX)
│       └── positions_table.html # Table component (injected via HTMX)
├── data/                        # Runtime data (created by app, not committed)
│   └── telebot.db               # SQLite database (signals, trades, daily stats)
└── .planning/
    └── codebase/                # GSD planning documents
        ├── ARCHITECTURE.md      # System design and data flow
        ├── STRUCTURE.md         # This file
        ├── CONVENTIONS.md       # Coding standards (if generated)
        └── TESTING.md           # Test patterns (if generated)
```

## Directory Purposes

**Root Directory:**
- Purpose: All Python modules, config, and deployment files live here (flat structure)
- Contains: Core bot logic, utilities, config, tests
- Key files: `bot.py` (entry), `config.py` (env loading), `models.py` (shared types)

**templates/:**
- Purpose: Jinja2 HTML templates for FastAPI dashboard
- Contains: Base layout, page templates, partial components (for HTMX injection)
- Key files: `base.html` (nav + layout), `overview.html`, `positions.html`, `history.html`
- Generated: No, hand-written
- Committed: Yes

**static/:**
- Purpose: Web assets (CSS, JS, images) for dashboard
- Contains: Tailwind CSS (loaded via CDN in base.html), HTMX (loaded via CDN)
- Generated: No
- Committed: Yes (.gitkeep only currently)

**data/:**
- Purpose: Runtime database and generated files
- Contains: `telebot.db` (SQLite database created on first run)
- Generated: Yes (by `db.init_db()`)
- Committed: No (.gitignore)

**.planning/codebase/:**
- Purpose: GSD (Guided Software Development) analysis and planning documents
- Contains: Architecture, structure, conventions, testing, concerns
- Generated: Yes (by GSD tools)
- Committed: Yes

## Key File Locations

**Entry Points:**
- `bot.py:274-275`: Main async entry point (asyncio.run(main()))
- `dashboard.py:66`: FastAPI app definition (injected into uvicorn in bot.py:260-268)

**Configuration:**
- `config.py:17-79`: Settings dataclass with all env var mappings
- `.env`: Runtime environment (secrets, not committed)
- `accounts.example.json`: Template for `accounts.json` (MT5 accounts config)

**Core Logic:**
- `signal_parser.py:28-100`: Regex patterns and parsing logic
- `trade_manager.py:36-300+`: Trade execution orchestration
- `executor.py:21-110`: Staggered execution wrapper
- `mt5_connector.py:60-180`: MT5 abstract interface
- `risk_calculator.py:24-88`: Lot sizing formulas

**Testing:**
- `test_signal_parser.py`: Comprehensive signal parsing tests (30+ cases)
- `test_trade_manager.py`: Trade execution scenario tests
- `test_risk_calculator.py`: Lot sizing and jitter tests

**Database:**
- `db.py:18-26`: Database initialization and schema creation
- Data persisted to `data/telebot.db` (created at runtime)

**Dashboard:**
- `dashboard.py:66-400+`: FastAPI endpoints and auth
- `templates/base.html`: Base layout template
- `templates/overview.html`: Home page (account info)
- `templates/positions.html`: Open positions view
- `templates/history.html`: Trade history
- `templates/signals.html`: Signal audit log

## Naming Conventions

**Files:**
- `bot.py`, `config.py`, `models.py`: Core modules, snake_case
- `test_*.py`: Test files, test_ prefix + module name
- `*_example.json`, `.env.example`: Templates, _example or .example suffix
- Utility scripts: `generate_session.py`, `list_groups.py`

**Directories:**
- `templates/`: HTML template directory (standard Jinja2 pattern)
- `static/`: Web assets directory (standard FastAPI pattern)
- `data/`: Runtime data directory (lowercase, simple name)
- `.planning/codebase/`: Hidden directory for planning documents

**Python Classes:**
- PascalCase: `TelegramClient`, `TradeManager`, `MT5Connector`, `SignalAction`, `Settings`

**Python Functions:**
- snake_case: `parse_signal()`, `calculate_lot_size()`, `handle_signal()`, `format_message()`
- Private functions: `_setup_trading()`, `_handle_open()`, `_format_header()`

**Python Variables:**
- Global settings: `settings = _load_settings()` (lowercase, immutable)
- Instance vars: `self.tm`, `self.cfg`, `self.http` (snake_case, descriptive)
- Enums: `SignalType.OPEN`, `Direction.BUY`, `OrderType.MARKET_BUY` (UPPER_CASE values)

**Database Tables:**
- `signals`: Parsed trading signals (audit log)
- `trades`: Executed trades (with P&L and audit trail)
- `daily_stats`: Daily aggregates per account (trades, messages, P&L)
- `pending_orders`: Limit orders awaiting fill (zone-based execution)

## Where to Add New Code

**New Signal Type (e.g., pyramid scaling):**
- Update `models.py:7-13` to add `SignalType.PYRAMID`
- Add parsing logic to `signal_parser.py` (new regex pattern + handler function)
- Add execution handler to `trade_manager.py` (new async method `_handle_pyramid()`)
- Route to handler in `trade_manager.handle_signal()` (line 47-59)
- Add notification template to `notifier.py:106-123`
- Add tests to `test_signal_parser.py` (new test class) and `test_trade_manager.py`

**New Dashboard Page (e.g., risk calculator):**
- Create new template at `templates/risk.html`
- Add route in `dashboard.py` (e.g., `@app.get("/risk")`)
- Add nav link in `templates/base.html:50-60`
- Use Jinja2 with HTMX for interactivity (pattern: see `templates/overview.html`)

**New MT5 Backend (e.g., Oanda):**
- Create backend class in new file `mt5_oanda.py` (inherit from `MT5Connector`)
- Implement abstract methods: `connect()`, `open_order()`, `get_positions()`, etc.
- Update factory in `bot.py:98-106` to handle new backend string (e.g., "oanda")
- Test integration in `test_trade_manager.py` with mock connector

**New Utility Script:**
- Add to root as `utility_name.py` (snake_case)
- Follow pattern of `generate_session.py` (load config, run one-time task, exit)
- Document in README.md usage section

**Database Schema Change:**
- Update `db.py:30-95` (_create_tables function)
- Add migration logic if needed (check if table exists, ALTER if schema changed)
- Update relevant query functions in `db.py`
- Update model if needed in `models.py`

## Special Directories

**data/:**
- Purpose: SQLite database and generated runtime files
- Generated: Yes (created on first run)
- Committed: No (in .gitignore)
- Cleanup: Safe to delete between runs (logs will re-initialize)

**.planning/codebase/:**
- Purpose: GSD-generated architecture documents
- Generated: Yes (by `gsd:map-codebase` command)
- Committed: Yes (for team reference)
- Format: Markdown (.md files)

**.git/:**
- Purpose: Git repository metadata
- Committed: Yes (repo history)
- Note: Standard hidden directory, not part of deployed artifact

## Import Organization

**Standard Pattern Observed:**

```python
# 1. Standard library
import asyncio
import logging
from datetime import datetime
from pathlib import Path

# 2. Third-party packages
from telethon import TelegramClient, events
from fastapi import Depends, FastAPI
import httpx

# 3. Local modules
from config import settings
from models import SignalAction
from trade_manager import TradeManager
```

## File Dependencies Graph

**Core Path (Telegram relay only):**
- `bot.py` → `config.py`, `discord_sender.py`

**Extended Path (with trading):**
- `bot.py` → `config.py`, `signal_parser.py`, `executor.py`, `notifier.py`, `dashboard.py`
- `executor.py` → `trade_manager.py`
- `trade_manager.py` → `mt5_connector.py`, `risk_calculator.py`, `db.py`, `models.py`
- `dashboard.py` → `db.py` (read-only queries)

**No circular imports:** Each file only imports upward in the stack (executor imports trade_manager, not vice versa).

---

*Structure analysis: 2026-03-19*
