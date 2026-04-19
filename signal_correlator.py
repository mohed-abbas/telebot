"""In-memory orphan-signal correlator for Phase 6 staged entries (D-04..D-07).

Tracks pending OPEN_TEXT_ONLY signals per (symbol, direction) within a
configurable window. Follow-up OPEN signals pair to the most-recent orphan
one-to-one; paired orphans are evicted immediately. Window-expired orphans
are evicted on every register/pair call (lazy GC).

Thread safety: a single asyncio.Lock serialises all mutations so concurrent
register_orphan / pair_followup callers see a consistent state.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class _PendingOrphan:
    signal_id: int
    created_at: float  # time.time() monotonic-ish seconds


class SignalCorrelator:
    """Pair orphan text-only signals to follow-ups by (symbol, direction)."""

    def __init__(self, window_seconds: int = 600):
        self._window = window_seconds
        self._orphans: dict[tuple[str, str], list[_PendingOrphan]] = {}
        self._lock = asyncio.Lock()

    def _evict_expired(self, key: tuple[str, str]) -> None:
        """Drop orphans older than the window. Called under the lock."""
        now = time.time()
        cutoff = now - self._window
        lst = self._orphans.get(key, [])
        fresh = [o for o in lst if o.created_at >= cutoff]
        if fresh:
            self._orphans[key] = fresh
        else:
            self._orphans.pop(key, None)

    async def register_orphan(
        self, signal_id: int, symbol: str, direction: str,
    ) -> None:
        """Record a pending text-only signal. Called by trade_manager on OPEN_TEXT_ONLY."""
        key = (symbol.upper(), direction.lower())
        async with self._lock:
            self._evict_expired(key)
            self._orphans.setdefault(key, []).append(
                _PendingOrphan(signal_id=signal_id, created_at=time.time())
            )
            logger.info(
                "Correlator: registered orphan signal_id=%d %s %s (window=%ds)",
                signal_id, symbol, direction, self._window,
            )

    async def pair_followup(self, symbol: str, direction: str) -> int | None:
        """Pair a follow-up OPEN signal to the most-recent orphan.

        Returns the orphan's signal_id, or None if no orphan matches.
        One-to-one (D-06): the paired orphan is evicted immediately — a second
        pair call returns None.
        Most-recent wins (D-05): .pop() from the tail of the per-key list.
        """
        key = (symbol.upper(), direction.lower())
        async with self._lock:
            self._evict_expired(key)
            lst = self._orphans.get(key)
            if not lst:
                logger.info(
                    "Correlator: no orphan matched for %s %s — treating as standalone OPEN",
                    symbol, direction,
                )
                return None
            orphan = lst.pop()
            if not lst:
                self._orphans.pop(key, None)
            logger.info(
                "Correlator: paired follow-up to orphan signal_id=%d %s %s",
                orphan.signal_id, symbol, direction,
            )
            return orphan.signal_id
