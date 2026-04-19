from __future__ import annotations

import re as _re
from dataclasses import dataclass, field
from enum import Enum


class SignalType(Enum):
    OPEN = "open"
    MODIFY_SL = "modify_sl"
    MODIFY_TP = "modify_tp"
    CLOSE = "close"
    CLOSE_PARTIAL = "close_partial"


class Direction(Enum):
    BUY = "buy"
    SELL = "sell"


# Canonical symbol mapping: various names → MT5 symbol
SYMBOL_MAP: dict[str, str] = {
    "gold": "XAUUSD",
    "xauusd": "XAUUSD",
    "xau/usd": "XAUUSD",
    "xau": "XAUUSD",
}

# Compiled regex for O(1) symbol lookup — keys sorted by length descending
# so "xau/usd" matches before "xau".
_SYMBOL_PATTERN = _re.compile(
    "|".join(_re.escape(k) for k in sorted(SYMBOL_MAP.keys(), key=len, reverse=True)),
    _re.IGNORECASE,
)


@dataclass(frozen=True)
class SignalAction:
    """Parsed trading signal from Telegram."""

    type: SignalType
    symbol: str  # Canonical MT5 symbol, e.g. "XAUUSD"
    raw_text: str  # Original message for audit

    direction: Direction | None = None
    entry_zone: tuple[float, float] | None = None  # (low, high)
    sl: float | None = None
    tps: list[float | str] = field(default_factory=list)  # "open" for trailing
    target_tp: float | None = None  # TP2 by default (auto-selected)

    # For modification signals
    new_sl: float | None = None
    new_tp: float | None = None
    close_percent: float | None = None  # e.g. 50.0 for "close half"


@dataclass
class AccountConfig:
    """Configuration for a single MT5 trading account."""

    name: str
    server: str
    login: int
    password_env: str  # env var name holding the password
    risk_percent: float
    max_lot_size: float
    max_daily_loss_percent: float = 3.0
    max_open_trades: int = 3
    enabled: bool = True
    mt5_host: str = ""  # per-account MT5 bridge hostname (overrides global)
    mt5_port: int = 0   # per-account MT5 bridge port (overrides global)


@dataclass(frozen=True, slots=True)
class AccountSettings:
    """Frozen per-account runtime settings — DB source of truth (Phase 5, D-27/D-32).

    Returned by SettingsStore.effective(). Used by TradeManager for risk/lot
    calculations and by Phase 6 staged entries as a cheap-to-copy snapshot
    via dataclasses.replace().
    """

    account_name: str
    risk_mode: str        # "percent" | "fixed_lot"
    risk_value: float     # percent of equity OR fixed lot size
    max_stages: int
    default_sl_pips: int
    max_daily_trades: int
    # Carried from accounts table (v1.0) for convenience
    max_open_trades: int
    max_lot_size: float


@dataclass
class GlobalConfig:
    """Global trading configuration."""

    default_target_tp: int = 2  # Use TP2
    limit_order_expiry_minutes: int = 30
    max_daily_trades_per_account: int = 30
    max_daily_server_messages: int = 500
    stagger_delay_min: float = 1.0
    stagger_delay_max: float = 5.0
    lot_jitter_percent: float = 4.0
    sl_tp_jitter_points: float = 0.8


@dataclass
class TradeRecord:
    """Record of an executed trade for the audit log."""

    signal_id: int | None = None
    account_name: str = ""
    symbol: str = ""
    direction: str = ""
    entry_price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    lot_size: float = 0.0
    ticket: int = 0
    status: str = ""  # "opened", "closed", "modified", "failed"
    pnl: float = 0.0
    timestamp: str = ""
    raw_signal: str = ""
