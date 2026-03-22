"""Async concurrency tests and executor signal gating.

Tests concurrent signal handling, database contention under parallel writes,
kill switch behavior, and signal gating when paused or reconnecting.

Requires PostgreSQL running via docker-compose.dev.yml on port 5433.
"""

import asyncio

import pytest
import pytest_asyncio

import db
from models import AccountConfig, Direction, GlobalConfig, SignalAction, SignalType
from mt5_connector import DryRunConnector, OrderType
from trade_manager import TradeManager
from executor import Executor


# ── PricedDryRunConnector (local copy to avoid cross-file import) ────


class PricedDryRunConnector(DryRunConnector):
    """DryRunConnector that returns configurable fake prices."""

    def __init__(
        self,
        *args,
        prices: dict[str, tuple[float, float]] | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._prices = prices or {"XAUUSD": (4980.0, 4981.0)}

    async def get_price(self, symbol: str) -> tuple[float, float] | None:
        return self._prices.get(symbol)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def priced_connector():
    """Connected PricedDryRunConnector with XAUUSD."""
    c = PricedDryRunConnector(
        "test-acct", "TestServer", 12345, "pass",
        prices={"XAUUSD": (4980.0, 4981.0)},
    )
    await c.connect()
    yield c
    await c.disconnect()


@pytest.fixture
def tm(priced_connector, account, global_config, db_pool):
    """TradeManager with single priced connector."""
    return TradeManager(
        connectors={account.name: priced_connector},
        accounts=[account],
        global_config=global_config,
    )


@pytest.fixture
def executor(tm, global_config):
    """Executor wrapping the trade manager (no notifier)."""
    return Executor(trade_manager=tm, global_config=global_config, notifier=None)


# ── Tests: Concurrent Signals ────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestConcurrentSignals:
    async def test_concurrent_same_signal_no_duplicate(
        self, tm, priced_connector, make_signal, db_pool,
    ):
        """5 identical SELL signals concurrently -> at most 1 executed.

        The duplicate position check in _handle_open prevents opening
        a second position with the same direction on the same symbol.
        """
        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )

        # Fire 5 identical signals concurrently
        all_results = await asyncio.gather(
            *[tm.handle_signal(signal) for _ in range(5)]
        )

        # Flatten results
        flat = [r for batch in all_results for r in batch]

        # Count how many actually executed or placed limit
        executed = [r for r in flat if r["status"] in ("executed", "limit_placed")]
        skipped = [r for r in flat if r["status"] == "skipped"]

        # At most 1 should execute -- rest are duplicates or hit max open
        assert len(executed) <= 1
        # At least some should be skipped
        assert len(skipped) >= 1

    async def test_concurrent_different_directions_both_execute(
        self, tm, priced_connector, make_signal, db_pool,
    ):
        """SELL + BUY simultaneously for same symbol -> both can execute
        since they are different directions."""
        sell_signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )
        buy_signal = make_signal(
            direction=Direction.BUY,
            entry_zone=(4978.0, 4982.0),
            sl=4973.0,
            tps=[4986.0, 4990.0],
            target_tp=4990.0,
        )

        results = await asyncio.gather(
            tm.handle_signal(sell_signal),
            tm.handle_signal(buy_signal),
        )

        flat = [r for batch in results for r in batch]
        executed = [r for r in flat if r["status"] in ("executed", "limit_placed")]

        # Both different directions should be able to execute
        assert len(executed) == 2

    async def test_concurrent_db_writes_no_deadlock(self, db_pool):
        """10 concurrent db.log_signal() calls complete without deadlock."""
        tasks = [
            db.log_signal(
                raw_text=f"concurrent signal {i}",
                signal_type="open",
                action_taken="test",
                symbol="XAUUSD",
                direction="sell",
            )
            for i in range(10)
        ]

        signal_ids = await asyncio.gather(*tasks)

        # All 10 should have succeeded and returned valid IDs
        assert len(signal_ids) == 10
        assert all(sid > 0 for sid in signal_ids)

        # Verify all 10 records exist in DB
        signals = await db.get_recent_signals(limit=20)
        concurrent_signals = [
            s for s in signals if s["raw_text"].startswith("concurrent signal")
        ]
        assert len(concurrent_signals) == 10


# ── Tests: Executor Kill Switch ──────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestExecutorKillSwitch:
    async def test_kill_switch_pauses_trading(self, executor):
        """emergency_close() sets _trading_paused=True and blocks signals."""
        assert executor._trading_paused is False
        assert executor.is_accepting_signals() is True

        result = await executor.emergency_close()

        assert executor._trading_paused is True
        assert executor.is_accepting_signals() is False
        assert isinstance(result, dict)

    async def test_kill_switch_closes_positions(self, executor, priced_connector):
        """Open 2 positions, emergency_close() removes them."""
        # Reset paused state if previous test left it
        executor._trading_paused = False

        # Open 2 positions manually
        await priced_connector.open_order(
            "XAUUSD", OrderType.MARKET_SELL, 0.10,
            price=4980.0, sl=4986.0, tp=4973.0,
        )
        await priced_connector.open_order(
            "XAUUSD", OrderType.MARKET_BUY, 0.10,
            price=4981.0, sl=4975.0, tp=4990.0,
        )
        positions = await priced_connector.get_positions()
        assert len(positions) == 2

        result = await executor.emergency_close()

        assert result["closed_positions"] == 2
        assert result["failed_closes"] == 0

        positions_after = await priced_connector.get_positions()
        assert len(positions_after) == 0

    async def test_resume_trading(self, executor):
        """emergency_close() then resume_trading() re-enables signals."""
        await executor.emergency_close()
        assert executor._trading_paused is True
        assert executor.is_accepting_signals() is False

        executor.resume_trading()

        assert executor._trading_paused is False
        assert executor.is_accepting_signals() is True


# ── Tests: Executor Signal Gating ────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestExecutorSignalGating:
    async def test_paused_executor_rejects_signals(self, executor, make_signal):
        """When _trading_paused=True, execute_signal returns skipped."""
        executor._trading_paused = True

        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )
        results = await executor.execute_signal(signal)

        assert len(results) == 1
        assert results[0]["status"] == "skipped"
        assert "kill switch" in results[0]["reason"].lower() or "paused" in results[0]["reason"].lower()

        # Reset
        executor._trading_paused = False

    async def test_reconnecting_account_skipped(self, executor, make_signal):
        """Account in _reconnecting set is skipped during execute_signal."""
        executor._reconnecting.add("test-acct")

        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )
        results = await executor.execute_signal(signal)

        # Account should be skipped
        assert len(results) == 1
        assert results[0]["status"] == "skipped"
        assert "reconnecting" in results[0]["reason"]

        # Clean up
        executor._reconnecting.discard("test-acct")

    async def test_all_reconnecting_blocks_signals(self, executor):
        """When all connectors are reconnecting, is_accepting_signals() returns False."""
        executor._reconnecting.add("test-acct")

        assert executor.is_accepting_signals() is False

        executor._reconnecting.discard("test-acct")
        assert executor.is_accepting_signals() is True
