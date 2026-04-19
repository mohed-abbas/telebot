"""Tests for Phase 6 D-04..D-07 — SignalCorrelator orphan/follow-up pairing.

RED baseline: import fails until Task 2 creates signal_correlator.py.
"""
import asyncio
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture
async def correlator():
    from signal_correlator import SignalCorrelator
    return SignalCorrelator(window_seconds=600)


async def test_register_orphan(correlator):
    await correlator.register_orphan(signal_id=1, symbol="XAUUSD", direction="buy")
    # No exception raised; internal state verified by pair_followup in the next test.


async def test_pair_within_window(correlator):
    await correlator.register_orphan(1, "XAUUSD", "buy")
    paired = await correlator.pair_followup(symbol="XAUUSD", direction="buy")
    assert paired == 1


async def test_pair_most_recent_wins(correlator):
    await correlator.register_orphan(10, "XAUUSD", "buy")
    await correlator.register_orphan(20, "XAUUSD", "buy")
    paired = await correlator.pair_followup(symbol="XAUUSD", direction="buy")
    assert paired == 20


async def test_pair_one_to_one_cannot_repair(correlator):
    await correlator.register_orphan(1, "XAUUSD", "buy")
    assert await correlator.pair_followup("XAUUSD", "buy") == 1
    # second pair attempt on the same orphan must return None (D-06)
    assert await correlator.pair_followup("XAUUSD", "buy") is None


async def test_pair_past_window_returns_none():
    # Force fast-window expiry via a fresh 1-second instance.
    from signal_correlator import SignalCorrelator
    fast = SignalCorrelator(window_seconds=1)
    await fast.register_orphan(1, "XAUUSD", "buy")
    await asyncio.sleep(1.5)
    assert await fast.pair_followup("XAUUSD", "buy") is None


async def test_pair_wrong_direction_returns_none(correlator):
    await correlator.register_orphan(1, "XAUUSD", "buy")
    assert await correlator.pair_followup("XAUUSD", "sell") is None
