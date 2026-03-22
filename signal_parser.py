"""Parse Telegram trading signals into structured SignalAction objects.

Handles zone-based entries, multiple TPs, and trade management updates.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from models import Direction, SignalAction, SignalType, SYMBOL_MAP, _SYMBOL_PATTERN

logger = logging.getLogger(__name__)

_KEYWORDS_PATH = Path(__file__).parent / "signal_keywords.json"


def _load_keywords() -> dict:
    if _KEYWORDS_PATH.exists():
        with open(_KEYWORDS_PATH) as f:
            return json.load(f)
    return {}


KEYWORDS = _load_keywords()

# ── Regex patterns ──────────────────────────────────────────────────────

# New trade: "Gold sell now 4978 - 4982" or "XAUUSD BUY 2150-2155"
_RE_OPEN = re.compile(
    r"(?P<symbol>gold|xauusd|xau/?usd|xau)\s+"
    r"(?P<direction>buy|sell)\s+"
    r"(?:now\s+)?"
    r"(?P<price1>[\d]+(?:\.[\d]+)?)\s*[-–—]\s*(?P<price2>[\d]+(?:\.[\d]+)?)",
    re.IGNORECASE,
)

# Fallback: single-price entry "Gold buy 2150" (no zone)
_RE_OPEN_SINGLE = re.compile(
    r"(?P<symbol>gold|xauusd|xau/?usd|xau)\s+"
    r"(?P<direction>buy|sell)\s+"
    r"(?:now\s+)?@?\s*(?P<price>[\d]+(?:\.[\d]+)?)",
    re.IGNORECASE,
)

# SL line: "SL: 4986" or "SL 4986" or "sl : 4986"
_RE_SL = re.compile(
    r"(?:^|\n)\s*sl\s*[:.]?\s*(?P<sl>[\d]+(?:\.[\d]+)?)",
    re.IGNORECASE,
)

# TP lines: "TP: 4975" or "TP. 4975" or "TP1: 4975" or "TP: open"
_RE_TP = re.compile(
    r"(?:^|\n)\s*tp\d?\s*[:.]?\s*(?P<tp>[\d]+(?:\.[\d]+)?|open)",
    re.IGNORECASE,
)

# Close signals
_RE_CLOSE = re.compile(
    r"(?:close\s+(?:all|gold|xauusd|xau|trade)|exit\s+(?:trade|all|gold))",
    re.IGNORECASE,
)

# Partial close
_RE_CLOSE_PARTIAL = re.compile(
    r"(?:close\s+(?:half|partial|\d+\s*%)|"
    r"tp\s*1\s*(?:hit|reached|done).*(?:close|partial)|"
    r"secure\s+(?:profits?|partial)|"
    r"take\s+(?:partial|half)\s+(?:profit|off))",
    re.IGNORECASE,
)

_RE_CLOSE_PERCENT = re.compile(r"(\d+)\s*%", re.IGNORECASE)

# SL to breakeven
_RE_SL_BE = re.compile(
    r"(?:move\s+sl\s+(?:to\s+)?(?:be|breakeven|break\s*even|entry))|"
    r"(?:sl\s+(?:to\s+)?(?:be|breakeven|break\s*even|entry))",
    re.IGNORECASE,
)

# SL update: "Update SL: 4978" or "New SL: 4978" or "SL: 4978 (update)"
_RE_SL_UPDATE = re.compile(
    r"(?:(?:update|new|move)\s+sl\s*[:.]?\s*(?P<sl>[\d]+(?:\.[\d]+)?))|"
    r"(?:sl\s*[:.]?\s*(?P<sl2>[\d]+(?:\.[\d]+)?)\s*\(?update\)?)",
    re.IGNORECASE,
)

# TP update: "New TP: 4965" or "Update TP: 4965"
_RE_TP_UPDATE = re.compile(
    r"(?:(?:update|new)\s+tp\s*[:.]?\s*(?P<tp>[\d]+(?:\.[\d]+)?))",
    re.IGNORECASE,
)


def _resolve_symbol(raw: str) -> str:
    """Map raw symbol text to canonical MT5 symbol."""
    return SYMBOL_MAP.get(raw.lower().strip(), raw.upper().strip())


def _select_target_tp(tps: list[float | str], index: int = 2) -> float | None:
    """Select TP at 1-based index (default TP2). Skip 'open' values."""
    numeric = [tp for tp in tps if isinstance(tp, (int, float))]
    if len(numeric) >= index:
        return numeric[index - 1]
    if numeric:
        return numeric[-1]  # fallback to last numeric TP
    return None


_SIGNAL_KEYWORDS = {"buy", "sell", "sl", "tp", "entry", "close", "exit"}
_RE_PRICE_LIKE = re.compile(r"\b\d{3,5}(?:\.\d{1,2})?\b")


def is_signal_like(text: str) -> bool:
    """Heuristic: does this text look like it might be a trading signal?

    Requires at least 2 trading keywords OR 1 keyword + a price-like number.
    This reduces false positives from casual messages mentioning 'gold' or 'buy'.
    """
    lower = text.lower()
    keyword_count = sum(1 for kw in _SIGNAL_KEYWORDS if kw in lower)
    has_price = bool(_RE_PRICE_LIKE.search(text))

    if keyword_count >= 2:
        return True
    if keyword_count >= 1 and has_price:
        return True
    return False


def parse_signal(text: str) -> SignalAction | None:
    """Parse a Telegram message into a SignalAction, or None if not a signal.

    Priority order:
    1. Close all
    2. Partial close
    3. SL to breakeven
    4. SL update
    5. TP update
    6. New trade (zone or single price)
    """
    stripped = text.strip()
    if not stripped:
        return None

    # ── 1. Full close ───────────────────────────────────────────────────
    if _RE_CLOSE.search(stripped):
        symbol = _extract_symbol_from_text(stripped)
        return SignalAction(
            type=SignalType.CLOSE,
            symbol=symbol,
            raw_text=text,
        )

    # ── 2. Partial close ───────────────────────────────────────────────
    if _RE_CLOSE_PARTIAL.search(stripped):
        symbol = _extract_symbol_from_text(stripped)
        pct_match = _RE_CLOSE_PERCENT.search(stripped)
        close_pct = float(pct_match.group(1)) if pct_match else 50.0
        return SignalAction(
            type=SignalType.CLOSE_PARTIAL,
            symbol=symbol,
            raw_text=text,
            close_percent=close_pct,
        )

    # ── 3. SL to breakeven ─────────────────────────────────────────────
    if _RE_SL_BE.search(stripped):
        symbol = _extract_symbol_from_text(stripped)
        return SignalAction(
            type=SignalType.MODIFY_SL,
            symbol=symbol,
            raw_text=text,
            new_sl=0.0,  # sentinel: 0.0 means "use entry price"
        )

    # ── 4. SL update ───────────────────────────────────────────────────
    sl_update = _RE_SL_UPDATE.search(stripped)
    if sl_update:
        sl_val = sl_update.group("sl") or sl_update.group("sl2")
        symbol = _extract_symbol_from_text(stripped)
        return SignalAction(
            type=SignalType.MODIFY_SL,
            symbol=symbol,
            raw_text=text,
            new_sl=float(sl_val),
        )

    # ── 5. TP update ───────────────────────────────────────────────────
    tp_update = _RE_TP_UPDATE.search(stripped)
    if tp_update:
        symbol = _extract_symbol_from_text(stripped)
        return SignalAction(
            type=SignalType.MODIFY_TP,
            symbol=symbol,
            raw_text=text,
            new_tp=float(tp_update.group("tp")),
        )

    # ── 6. New trade (zone entry) ──────────────────────────────────────
    open_match = _RE_OPEN.search(stripped)
    if open_match:
        return _build_open_signal(open_match, stripped, text, zone=True)

    # ── 7. New trade (single price fallback) ───────────────────────────
    open_single = _RE_OPEN_SINGLE.search(stripped)
    if open_single:
        return _build_open_signal(open_single, stripped, text, zone=False)

    # Not a recognized signal
    if is_signal_like(stripped):
        logger.warning("Signal-like text not parsed: %.200s", stripped)
    return None


def _build_open_signal(
    match: re.Match, stripped: str, raw_text: str, zone: bool
) -> SignalAction | None:
    """Build a SignalAction for a new trade from a regex match."""
    symbol = _resolve_symbol(match.group("symbol"))
    direction = Direction.BUY if match.group("direction").upper() == "BUY" else Direction.SELL

    if zone:
        p1 = float(match.group("price1"))
        p2 = float(match.group("price2"))
        entry_zone = (min(p1, p2), max(p1, p2))
    else:
        price = float(match.group("price"))
        entry_zone = (price, price)  # single price = zero-width zone

    # Extract SL
    sl_match = _RE_SL.search(stripped)
    sl = float(sl_match.group("sl")) if sl_match else None

    # Extract all TPs
    tps: list[float | str] = []
    for tp_match in _RE_TP.finditer(stripped):
        val = tp_match.group("tp")
        tps.append(val.lower() if val.lower() == "open" else float(val))

    # Validate SL direction
    if sl is not None and entry_zone:
        zone_mid = (entry_zone[0] + entry_zone[1]) / 2
        if direction == Direction.BUY and sl >= zone_mid:
            logger.warning("Invalid signal: BUY but SL (%.2f) >= entry zone mid (%.2f)", sl, zone_mid)
            return None
        if direction == Direction.SELL and sl <= zone_mid:
            logger.warning("Invalid signal: SELL but SL (%.2f) <= entry zone mid (%.2f)", sl, zone_mid)
            return None

    # Select target TP (TP2 by default)
    target_tp_index = KEYWORDS.get("default_target_tp", 2)
    target_tp = _select_target_tp(tps, target_tp_index)

    return SignalAction(
        type=SignalType.OPEN,
        symbol=symbol,
        raw_text=raw_text,
        direction=direction,
        entry_zone=entry_zone,
        sl=sl,
        tps=tps,
        target_tp=target_tp,
    )


def _extract_symbol_from_text(text: str) -> str:
    """Try to find a known symbol in the text using compiled regex, default to XAUUSD."""
    match = _SYMBOL_PATTERN.search(text)
    if match:
        return SYMBOL_MAP[match.group().lower()]
    return "XAUUSD"  # default for gold signal groups


def format_parsed_signal(signal: SignalAction) -> str:
    """Format a parsed signal for Discord logging."""
    if signal.type == SignalType.OPEN:
        zone = signal.entry_zone
        zone_str = f"{zone[0]:.2f} - {zone[1]:.2f}" if zone else "N/A"
        dir_str = signal.direction.value.upper() if signal.direction else "?"
        tps_str = ", ".join(
            str(tp) if isinstance(tp, str) else f"{tp:.2f}" for tp in signal.tps
        )
        sl_str = f"{signal.sl:.2f}" if signal.sl is not None else "N/A"
        tp_str = f"{signal.target_tp:.2f}" if signal.target_tp is not None else "N/A"
        return (
            f"PARSED SIGNAL: {dir_str} {signal.symbol}\n"
            f"  Zone: {zone_str}\n"
            f"  SL: {sl_str}\n"
            f"  TPs: [{tps_str}]\n"
            f"  Target TP: {tp_str}"
        )
    elif signal.type == SignalType.CLOSE:
        return f"PARSED SIGNAL: CLOSE {signal.symbol}"
    elif signal.type == SignalType.CLOSE_PARTIAL:
        return f"PARSED SIGNAL: CLOSE {signal.close_percent:.0f}% {signal.symbol}"
    elif signal.type == SignalType.MODIFY_SL:
        if signal.new_sl == 0.0:
            return f"PARSED SIGNAL: MOVE SL TO BREAKEVEN {signal.symbol}"
        return f"PARSED SIGNAL: UPDATE SL → {signal.new_sl:.2f} {signal.symbol}"
    elif signal.type == SignalType.MODIFY_TP:
        return f"PARSED SIGNAL: UPDATE TP → {signal.new_tp:.2f} {signal.symbol}"
    return f"PARSED SIGNAL: {signal.type.value} {signal.symbol}"
