"""In-memory orphan-signal correlator for Phase 6 staged entries (D-04..D-07).

Tracks pending OPEN_TEXT_ONLY signals per (account, symbol, direction) within a
configurable window. Follow-up OPEN signals pair to the most-recent orphan
one-to-one; paired orphans are evicted immediately. Window-expired orphans
are evicted on every register/pair call (lazy GC).

§1.4 multi-account identity: the key includes account_name so an account's
follow-up can only ever pair to its OWN orphan. Without the account dimension,
two accounts opening the same (symbol, direction) share one LIFO bucket, and a
reshuffled fan-out can pop the wrong account's signal_id. account_name defaults
to "" for the single-bucket legacy shape (single-account deployments and the
correlator unit tests behave identically).

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
    """Pair orphan text-only signals to follow-ups by (account, symbol, direction)."""

    def __init__(self, window_seconds: int = 600):
        self._window = window_seconds
        self._orphans: dict[tuple[str, str, str], list[_PendingOrphan]] = {}
        self._lock = asyncio.Lock()

    def _evict_expired(self, key: tuple[str, str, str]) -> None:
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
        account_name: str = "",
    ) -> None:
        """Record a pending text-only signal. Called by trade_manager on OPEN_TEXT_ONLY.

        account_name scopes the orphan (§1.4) so only this account's follow-up
        can pair to it. Defaults to "" for the legacy single-bucket shape.
        """
        key = (account_name, symbol.upper(), direction.lower())
        async with self._lock:
            self._evict_expired(key)
            self._orphans.setdefault(key, []).append(
                _PendingOrphan(signal_id=signal_id, created_at=time.time())
            )
            logger.info(
                "Correlator: registered orphan signal_id=%d %s %s %s (window=%ds)",
                signal_id, account_name, symbol, direction, self._window,
            )

    async def pair_followup(
        self, symbol: str, direction: str, account_name: str = "",
    ) -> int | None:
        """Pair a follow-up OPEN signal to the most-recent orphan.

        Returns the orphan's signal_id, or None if no orphan matches.
        One-to-one (D-06): the paired orphan is evicted immediately — a second
        pair call returns None.
        Most-recent wins (D-05): .pop() from the tail of the per-key list.
        account_name (§1.4) scopes the lookup to this account's own orphans;
        defaults to "" for the legacy single-bucket shape.
        """
        key = (account_name, symbol.upper(), direction.lower())
        async with self._lock:
            self._evict_expired(key)
            lst = self._orphans.get(key)
            if not lst:
                logger.info(
                    "Correlator: no orphan matched for %s %s %s — treating as standalone OPEN",
                    account_name, symbol, direction,
                )
                return None
            orphan = lst.pop()
            if not lst:
                self._orphans.pop(key, None)
            logger.info(
                "Correlator: paired follow-up to orphan signal_id=%d %s %s %s",
                orphan.signal_id, account_name, symbol, direction,
            )
            return orphan.signal_id
