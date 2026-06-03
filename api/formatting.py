"""api/formatting.py — single source of display-string formatting (Phase 08 Plan 01).

D-08: the ONE place numeric/time formatting lives. Every model's `_display`
twin routes through these functions; routes never format inline. Extending the
per-symbol price precision happens here (`_SYMBOL_DIGITS`), never in a model or
a route — this is what stops the XAUUSD pip-size class of bug (quick task
260501-i7u) from recurring.

D-05  parallel `_display` fields (this module produces the display string).
D-06  machine timestamps: ISO-8601 + UTC offset (`ts_machine`).
D-07  display timestamps: absolute "YYYY-MM-DD HH:MM:SS UTC" (`ts_display`).

The project reasons in UTC throughout (db.py UTC-today idiom). `GOLD_PIP_SIZE` is
imported from risk_calculator to keep pip-size single-sourced even though current
display formatting derives digits from `_SYMBOL_DIGITS`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from risk_calculator import GOLD_PIP_SIZE  # noqa: F401  (single-source pip size, D-08)

# Price digits per symbol. Default 5 (FX). XAUUSD prints to 2dp (broker convention).
# Extend HERE for new instruments — never inline a `:.Nf` literal in a route/model.
_SYMBOL_DIGITS: dict[str, int] = {"XAUUSD": 2}


def price_display(symbol: str, value: float) -> str:
    """Format a price to the symbol's display precision (default 5dp; XAUUSD 2dp)."""
    digits = _SYMBOL_DIGITS.get(symbol.upper(), 5)
    return f"{value:.{digits}f}"


def money_display(value: float) -> str:
    """Format a money amount: thousands-separated, 2dp."""
    return f"{value:,.2f}"


def volume_display(value: float) -> str:
    """Format a lot volume to 2dp (matches round(vol, 2) lot-step in dashboard.py)."""
    return f"{value:.2f}"


def ts_machine(dt: datetime) -> str:
    """ISO-8601 machine timestamp with explicit UTC offset (D-06)."""
    return dt.astimezone(timezone.utc).isoformat()


def ts_display(dt: datetime) -> str:
    """Absolute human display timestamp: 'YYYY-MM-DD HH:MM:SS UTC' (D-07)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
