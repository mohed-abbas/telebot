"""Per-account lot sizing with humanization jitter.

Gold (XAUUSD) specifics:
  - 1 standard lot = 100 troy ounces
  - 1 pip = $0.01 price movement = $1.00 per standard lot
  - Lot size = risk_amount / (sl_distance_in_pips × pip_value_per_lot)
"""

from __future__ import annotations

import logging
import random

from models import AccountConfig, Direction

logger = logging.getLogger(__name__)

# Gold: 1 pip = $0.01 movement, pip value = $1.00 per standard lot (100 oz)
# So: $1 risk with 10 pip SL → 0.10 lots
GOLD_PIP_VALUE_PER_LOT = 1.0  # $1 per pip per standard lot
GOLD_PIP_SIZE = 0.01  # 1 pip = $0.01 movement in price


def calculate_lot_size(
    account_balance: float,
    risk_percent: float,
    sl_distance: float,
    max_lot_size: float,
    jitter_percent: float = 0.0,
    symbol: str = "XAUUSD",
) -> float:
    """Calculate lot size based on risk % and SL distance.

    Args:
        account_balance: Current account balance in USD
        risk_percent: Risk per trade as percentage (e.g. 1.0 = 1%)
        sl_distance: Distance from entry to SL in price points (e.g. 5.0 = $5 move)
        max_lot_size: Hard cap on lot size for this account
        jitter_percent: Random ±% variation for humanization (e.g. 4.0 = ±4%)
        symbol: Trading symbol (currently only XAUUSD supported)

    Returns:
        Lot size rounded to 2 decimal places, or 0.0 if invalid.
    """
    if account_balance <= 0 or risk_percent <= 0 or sl_distance <= 0:
        logger.warning("Invalid inputs: balance=%.2f risk=%.2f sl_dist=%.2f", account_balance, risk_percent, sl_distance)
        return 0.0

    risk_amount = account_balance * (risk_percent / 100.0)
    sl_pips = sl_distance / GOLD_PIP_SIZE
    lot_size = risk_amount / (sl_pips * GOLD_PIP_VALUE_PER_LOT)

    # Apply humanization jitter
    if jitter_percent > 0:
        jitter = random.uniform(-jitter_percent, jitter_percent) / 100.0
        lot_size *= (1.0 + jitter)

    # Clamp to max and ensure minimum
    lot_size = min(lot_size, max_lot_size)
    lot_size = max(lot_size, 0.01)  # minimum 0.01 lots

    return round(lot_size, 2)


def calculate_sl_with_jitter(sl: float, jitter_points: float, direction: Direction) -> float:
    """Apply slight random jitter to SL for humanization.

    For BUY: SL is below entry, so jitter moves it slightly up or down.
    For SELL: SL is above entry, so jitter moves it slightly up or down.
    """
    if jitter_points <= 0:
        return sl
    offset = random.uniform(-jitter_points, jitter_points)
    return round(sl + offset, 2)


def calculate_tp_with_jitter(tp: float, jitter_points: float, direction: Direction) -> float:
    """Apply slight random jitter to TP for humanization."""
    if jitter_points <= 0:
        return tp
    offset = random.uniform(-jitter_points, jitter_points)
    return round(tp + offset, 2)


def calculate_sl_distance(entry_price: float, sl: float) -> float:
    """Calculate absolute distance between entry and SL in price points."""
    return abs(entry_price - sl)
