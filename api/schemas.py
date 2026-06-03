"""api/schemas.py — full Pydantic v2 response/request contract (Phase 08 Plan 01).

Plans 02-05 import these models without exploring the codebase. Plain BaseModel
subclasses (dicts coerce; no `from_attributes` needed — routes pass dicts/kwargs).

D-05 dual-value rule: ONLY price/money/volume/timestamp fields get a parallel
`_display` twin (a pre-computed string from api/formatting.py). ints / strings /
enums / bools stay bare. Schemas only DECLARE the `_display` fields — the route
fills them via api/formatting.py (schemas never format).

Field shapes mirror the existing dashboard dict shapes (dashboard.py:1438-1449
positions, 1493-1508 accounts) and the mt5_connector OrderResult/Position
dataclasses (mt5_connector.py:33-52).
"""

from __future__ import annotations

from pydantic import BaseModel

# ─── Auth ────────────────────────────────────────────────────────────────────


class LoginIn(BaseModel):
    """Login request body (JSON port of the form login — Plan 02 finalises)."""

    password: str
    csrf_token: str


class AuthUser(BaseModel):
    """Authenticated user identity returned by /auth/me."""

    user: str


# ─── Positions (mirrors dashboard.py:1438-1449 + mt5_connector Position) ──────


class Position(BaseModel):
    account: str
    ticket: int
    symbol: str
    direction: str  # "buy" | "sell"
    volume: float
    volume_display: str
    open_price: float
    open_price_display: str
    sl: float | None = None
    tp: float | None = None
    profit: float
    profit_display: str


# ─── Accounts (mirrors dashboard.py:1493-1508) ───────────────────────────────


class AccountOverview(BaseModel):
    name: str
    connected: bool
    enabled: bool
    balance: float
    balance_display: str
    equity: float
    equity_display: str
    margin: float
    margin_display: str
    free_margin: float
    free_margin_display: str
    open_trades: int
    total_profit: float
    total_profit_display: str
    daily_trades: int
    daily_messages: int
    max_daily_trades: int
    daily_limit_pct: float
    risk_percent: float
    max_lot: float


# ─── History ─────────────────────────────────────────────────────────────────


class HistoryTrade(BaseModel):
    account: str
    ticket: int
    symbol: str
    direction: str
    volume: float
    volume_display: str
    open_price: float
    open_price_display: str
    close_price: float | None = None
    close_price_display: str | None = None
    profit: float
    profit_display: str
    opened_at: str | None = None  # ts_machine (ISO-8601 + offset)
    opened_at_display: str | None = None  # ts_display ("... UTC")
    closed_at: str | None = None
    closed_at_display: str | None = None


class FilterOptions(BaseModel):
    """Distinct filter values for the history page (accounts/symbols/directions)."""

    accounts: list[str] = []
    symbols: list[str] = []
    directions: list[str] = []


# ─── Signals ─────────────────────────────────────────────────────────────────


class Signal(BaseModel):
    id: int
    raw_text: str
    signal_type: str
    symbol: str | None = None
    direction: str | None = None
    action_taken: str | None = None
    received_at: str | None = None  # ts_machine
    received_at_display: str | None = None  # ts_display


# ─── Stages ──────────────────────────────────────────────────────────────────


class Stage(BaseModel):
    id: int
    account: str
    symbol: str
    direction: str
    stage_number: int
    max_stages: int
    volume: float
    volume_display: str
    entry_price: float
    entry_price_display: str
    status: str
    created_at: str | None = None
    created_at_display: str | None = None


# ─── Analytics ───────────────────────────────────────────────────────────────


class Analytics(BaseModel):
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    profit_factor: float
    total_profit: float
    total_profit_display: str
    gross_profit: float
    gross_profit_display: str
    gross_loss: float
    gross_loss_display: str


# ─── Overview / status meta ──────────────────────────────────────────────────


class OverviewMeta(BaseModel):
    """Top-of-overview composite (accounts + trading status + open count)."""

    trading_paused: bool
    open_positions: int
    accounts: list[AccountOverview] = []


class TradingStatus(BaseModel):
    paused: bool
    status: str  # e.g. "running" | "paused" | "resumed"


class EmergencyPreview(BaseModel):
    """What a kill-switch would close (preview before confirmation)."""

    open_positions: int
    pending_orders: int
    accounts: list[str] = []


class EmergencyResult(BaseModel):
    """Per-account kill-switch outcome envelope."""

    results: dict
    ok: bool = True


# ─── Settings ────────────────────────────────────────────────────────────────


class SettingsView(BaseModel):
    """Effective settings for an account (Plan 05 fills the field set)."""

    account: str
    values: dict
    diff: dict | None = None


# ─── Request bodies (mutations) ──────────────────────────────────────────────


class CloseLevelsIn(BaseModel):
    """Modify SL/TP on an open position (modify-levels)."""

    sl: float | None = None
    tp: float | None = None


class PartialCloseIn(BaseModel):
    """Partial close — D-09 absolute volume + D-10/D-11 idempotency request_id."""

    close_volume: float
    request_id: str


class SettingsValidateIn(BaseModel):
    account: str
    values: dict


class SettingsConfirmIn(BaseModel):
    account: str
    values: dict


class SettingsRevertIn(BaseModel):
    account: str


# ─── Mutation envelopes ──────────────────────────────────────────────────────


class MutationResult(BaseModel):
    """Generic mutation outcome ({ok|success} on success, error on failure)."""

    ok: bool = True
    success: bool | None = None
    error: str | None = None
