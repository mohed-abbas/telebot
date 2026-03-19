# Coding Conventions

**Analysis Date:** 2026-03-19

## Naming Patterns

**Files:**
- Lowercase with underscores: `bot.py`, `config.py`, `signal_parser.py`, `risk_calculator.py`
- Test files: `test_<module>.py` format (e.g., `test_signal_parser.py`, `test_risk_calculator.py`)
- Module names are descriptive and match their primary responsibility

**Functions:**
- snake_case for all function definitions: `calculate_lot_size()`, `parse_signal()`, `format_message()`
- Private/internal functions prefixed with underscore: `_load_keywords()`, `_resolve_symbol()`, `_setup_trading()`
- Async functions named with action verbs: `async def connect()`, `async def execute_signal()`, `async def log_trade()`

**Variables:**
- snake_case throughout: `account_balance`, `risk_percent`, `entry_zone`, `max_lot_size`
- Module-level constants in UPPER_CASE: `MAX_FILE_SIZE = 8 * 1024 * 1024`, `GOLD_PIP_VALUE_PER_LOT = 1.0`
- Private module-level variables prefixed with underscore: `_DB_PATH`, `_db`, `_lock`
- Dataclass fields use snake_case: `entry_zone`, `target_tp`, `close_percent`

**Types:**
- Use `Enum` classes for fixed sets of values: `SignalType`, `Direction`, `OrderType`
- Enum values are lowercase strings: `SignalType.OPEN`, `Direction.BUY`
- Dataclass names use PascalCase: `SignalAction`, `AccountConfig`, `GlobalConfig`, `TradeRecord`
- Type hints use modern syntax: `dict[int, str]`, `list[float]`, `tuple[float, float]`, `str | None` (Python 3.10+ union syntax)

## Code Style

**Formatting:**
- No explicit formatter configured (no `.prettierrc`, `pyproject.toml`, or `.flake8`)
- Code follows PEP 8 conventions implicitly
- Line wrapping and indentation follow standard Python practices
- Imports organized into standard groups (standard library, third-party, local)

**Linting:**
- No explicit linter configuration detected
- Code is written to be PEP 8 compliant

## Import Organization

**Order:**
1. Standard library imports: `import asyncio`, `from datetime import datetime`
2. Third-party imports: `import httpx`, `from telethon import TelegramClient`
3. Local imports: `from config import settings`, `from models import SignalAction`

**Path Aliases:**
- No path aliases or abbreviations used
- Relative imports not used; all imports are absolute
- Common pattern: `from models import Direction` for dataclasses and enums

**Module docstrings:**
- All modules have module-level docstrings explaining purpose and behavior
- Example from `signal_parser.py`: `"""Parse Telegram trading signals into structured SignalAction objects.\n\nHandles zone-based entries, multiple TPs, and trade management updates."""`

## Error Handling

**Patterns:**
- Generic `Exception` catching with logging: `except Exception as exc: logger.error(...)`
- Specific exception handling in critical paths: `except asyncio.CancelledError: pass`
- Validation through return values: `parse_signal()` returns `SignalAction | None` (None for invalid signals)
- Early returns for validation failures: Check conditions and return `None` immediately
- Sentinel values for special cases: `new_sl=0.0` represents "move to breakeven"
- Graceful degradation: Missing webhooks → log and skip notification
- Connection errors logged with context: `logger.error("Trade execution error: %s", exc)`

**Error logging context:**
- Always include contextual information in error messages
- Use formatted strings with `%s` for values: `logger.error("could not resolve name for chat %d: %s", chat_id, exc)`

## Logging

**Framework:** Python's built-in `logging` module

**Setup:**
- Configured in `bot.py` with basicConfig at module initialization
- Format: `"%(asctime)s [%(levelname)s] %(name)s: %(message)s"`
- Level: `logging.INFO` by default
- Module loggers created per-file: `logger = logging.getLogger(__name__)`

**Patterns:**
- Info-level for important state changes: `logger.info("Trading ENABLED (%s) — %d account(s) configured", mode, len(accounts))`
- Warning-level for recoverable issues: `logger.warning("Could not resolve name for chat %d: %s", chat_id, exc)`
- Debug-level for detailed execution flow: `logger.debug("Stagger delay: %.1fs before %s", delay, acct_name)`
- Error-level for failures and exceptions: `logger.error("Trade execution error: %s", exc)`

## Comments

**When to Comment:**
- Complex regex patterns: Comments explain what each pattern matches
- Business logic: Comments explain "why" decisions, not "what" code does
- Non-obvious algorithmic choices: Example: comments in `risk_calculator.py` explaining Gold pip calculations
- Section dividers: Use `# ── Section name ────────────────` for visual organization

**JSDoc/Type Hints:**
- Docstrings use triple-quoted format for functions
- Parameter descriptions included in docstrings
- Example from `risk_calculator.py`:
  ```python
  def calculate_lot_size(
      account_balance: float,
      risk_percent: float,
      ...
  ) -> float:
      """Calculate lot size based on risk % and SL distance.

      Args:
          account_balance: Current account balance in USD
          risk_percent: Risk per trade as percentage (e.g. 1.0 = 1%)
          ...
      Returns:
          Lot size rounded to 2 decimal places, or 0.0 if invalid.
      """
  ```

## Function Design

**Size:**
- Most functions 10-50 lines
- Larger functions (100+ lines) like `parse_signal()` are acceptable for complex parsing logic
- Prefer extracting helper functions for repeated logic: `_resolve_symbol()`, `_select_target_tp()`

**Parameters:**
- Use dataclasses for multiple related parameters: `AccountConfig`, `GlobalConfig`
- Pass `|` union types for optional values: `Direction | None`, `str | None`
- Prefer explicit parameters over **kwargs

**Return Values:**
- Use `None` for "not found" or "invalid": `parse_signal()` returns `SignalAction | None`
- Use tuples for fixed multi-value returns: `get_price() -> tuple[float, float] | None`
- Use dataclasses for structured returns: `AccountInfo` dataclass instead of dict
- Use lists for variable-length collections: `list[Position]`, `list[dict]`

## Module Design

**Exports:**
- All public functions/classes are importable
- Use module docstrings to explain exports
- Private functions prefixed with underscore: `_load_keywords()`, `_setup_trading()`

**Barrel Files:**
- `models.py` serves as a central definitions module (exports `SignalAction`, `Direction`, `SignalType`, etc.)
- No package-level `__init__.py` files (single-file modules)

## Database Access Pattern

**Pattern:**
- Centralized in `db.py` module
- Async functions with locking: `async def log_signal(...)`
- Parameterized queries to prevent SQL injection: Uses `?` placeholders
- Global state: `_db`, `_lock`, `_DB_PATH` module-level variables
- Thread-safe with `asyncio.Lock()`

## Configuration Pattern

**Pattern:**
- Frozen dataclass: `@dataclass(frozen=True) class Settings`
- Lazy loading via private `_load_settings()` function
- Helper functions `_req()` and `_opt()` for required/optional env vars
- Sentinel loading: Environment variables loaded via `environ.get()`
- All config read at startup: `settings = _load_settings()` at module level

---

*Convention analysis: 2026-03-19*
