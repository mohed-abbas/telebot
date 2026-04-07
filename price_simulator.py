"""Simulated price feed using Geometric Brownian Motion.

Provides realistic price evolution for dry-run testing.
Shared across all DryRunConnector instances so every account
sees the same market price for a given symbol.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random

logger = logging.getLogger(__name__)

# Default full spreads per symbol (in price units)
DEFAULT_SPREADS: dict[str, float] = {
    "XAUUSD": 0.30,
}
DEFAULT_SPREAD = 0.30

# GBM parameters
ANNUAL_VOLATILITY = 0.15  # 15% annualized for gold
SECONDS_PER_DAY = 86400
DT = 1.0 / SECONDS_PER_DAY  # 1 second as fraction of a trading day


class PriceSimulator:
    """GBM-based price simulator with background update loop."""

    def __init__(self, volatility_multiplier: float = 1.0):
        self._prices: dict[str, float] = {}       # symbol → mid price
        self._spreads: dict[str, float] = {}       # symbol → half-spread
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._running = False
        self._volatility_multiplier = volatility_multiplier
        self._sigma = ANNUAL_VOLATILITY

    def register_symbol(self, symbol: str, initial_price: float, spread: float | None = None) -> None:
        """Start tracking a symbol. Idempotent — ignores if already registered."""
        if symbol in self._prices:
            return
        if spread is None:
            spread = DEFAULT_SPREADS.get(symbol, DEFAULT_SPREAD)
        self._prices[symbol] = initial_price
        self._spreads[symbol] = spread / 2.0
        logger.info("[SIM] Registered %s at %.2f (spread=%.2f)", symbol, initial_price, spread)

    def get_price(self, symbol: str) -> tuple[float, float] | None:
        """Returns (bid, ask) for a tracked symbol, or None."""
        mid = self._prices.get(symbol)
        if mid is None:
            return None
        half = self._spreads.get(symbol, DEFAULT_SPREAD / 2.0)
        return (mid - half, mid + half)

    async def start(self) -> None:
        """Start the background price update loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._update_loop())
        logger.info("[SIM] Price simulator started (volatility_mult=%.1f)", self._volatility_multiplier)

    async def stop(self) -> None:
        """Stop the background loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[SIM] Price simulator stopped")

    async def _update_loop(self) -> None:
        """Update all tracked prices every second using GBM."""
        sigma = self._sigma * self._volatility_multiplier
        sqrt_dt = math.sqrt(DT)

        while self._running:
            try:
                await asyncio.sleep(1)
                async with self._lock:
                    for symbol in self._prices:
                        z = random.gauss(0, 1)
                        drift = -0.5 * sigma * sigma * DT
                        diffusion = sigma * sqrt_dt * z
                        self._prices[symbol] *= math.exp(drift + diffusion)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[SIM] Price update error: %s", exc)
