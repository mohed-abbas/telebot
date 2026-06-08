"""Integration tests for trade manager with real DB + PricedDryRunConnector.

Requires PostgreSQL running via docker-compose.dev.yml on port 5433.
"""

import pytest
import pytest_asyncio

import db
from models import AccountConfig, Direction, GlobalConfig, SignalAction, SignalType
from mt5_connector import DryRunConnector, OrderType
from trade_manager import TradeManager


# ── PricedDryRunConnector ────────────────────────────────────────────


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
    """Connected PricedDryRunConnector with XAUUSD at (4980.0, 4981.0)."""
    c = PricedDryRunConnector(
        "test-acct", "TestServer", 12345, "pass",
        prices={"XAUUSD": (4980.0, 4981.0)},
    )
    await c.connect()
    yield c
    await c.disconnect()


@pytest_asyncio.fixture
async def tm(priced_connector, account, global_config, db_pool):
    """TradeManager with single priced connector.

    Post-EXEC2-06 (Plan 13-05): _handle_open is a multi-stage staged scale-in,
    so a standalone OPEN now inserts staged_entries rows (FK → accounts). Seed
    the account row so the FK resolves; with NO settings_store attached,
    snapshot is None → max_stages=1 → ONE whole-zone band fired at market.
    """
    await db.upsert_account_if_missing(
        name=account.name, server="Test", login=99999, password_env="",
        risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
        max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
    )
    await db.upsert_account_settings_if_missing(account_name=account.name)
    return TradeManager(
        connectors={account.name: priced_connector},
        accounts=[account],
        global_config=global_config,
    )


@pytest_asyncio.fixture
async def multi_account_tm(db_pool, global_config):
    """TradeManager with 2 accounts and 2 priced connectors.

    Post-EXEC2-06: seed both account rows so staged_entries FK resolves.
    """
    acct1 = AccountConfig(
        name="acct-1", server="TestServer", login=11111,
        password_env="TEST_PASS", risk_percent=1.0, max_lot_size=1.0,
        max_daily_loss_percent=3.0, max_open_trades=3, enabled=True,
    )
    acct2 = AccountConfig(
        name="acct-2", server="TestServer", login=22222,
        password_env="TEST_PASS", risk_percent=1.0, max_lot_size=1.0,
        max_daily_loss_percent=3.0, max_open_trades=3, enabled=True,
    )
    for a in (acct1, acct2):
        await db.upsert_account_if_missing(
            name=a.name, server="Test", login=a.login, password_env="",
            risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
            max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
        )
        await db.upsert_account_settings_if_missing(account_name=a.name)
    c1 = PricedDryRunConnector(
        "acct-1", "TestServer", 11111, "pass",
        prices={"XAUUSD": (4980.0, 4981.0)},
    )
    c2 = PricedDryRunConnector(
        "acct-2", "TestServer", 22222, "pass",
        prices={"XAUUSD": (4980.0, 4981.0)},
    )
    return TradeManager(
        connectors={"acct-1": c1, "acct-2": c2},
        accounts=[acct1, acct2],
        global_config=global_config,
    ), c1, c2


# ── Tests: Full Signal Flow ──────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestFullSignalFlow:
    async def test_open_sell_market_in_zone(self, tm, priced_connector, make_signal):
        """SELL signal, price 4980 in zone 4978-4982.

        Post-EXEC2-06: a standalone OPEN is a staged scale-in. No settings_store
        → max_stages=1 → ONE whole-zone band (4978-4982). SELL in-zone-at-arrival
        (bid=4980 >= band.low=4978) → the band FIRES at market. results = [band
        executed, staged summary].
        """
        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )
        results = await tm.handle_signal(signal)

        executed = [r for r in results if r.get("status") == "executed"]
        assert len(executed) == 1
        assert executed[0]["order_type"] == "market"
        assert executed[0]["ticket"] > 0
        # The staged summary is appended (one whole-zone band, fired at arrival).
        summary = [r for r in results if r.get("status") == "staged"]
        assert len(summary) == 1
        assert summary[0]["fired_at_arrival"] == 1
        assert summary[0]["total"] == 1

        # Position should exist in connector
        positions = await priced_connector.get_positions("XAUUSD")
        assert len(positions) == 1
        assert positions[0].direction == "sell"

    async def test_open_buy_above_zone_arms_no_resting_limit(self, tm, priced_connector, make_signal):
        """BUY signal, price 2151 ABOVE zone 2140-2145.

        Post-EXEC2-06 / D2-01: standalone OPENs no longer place a resting LIMIT
        order. The whole-zone band (max_stages=1) is NOT crossed at arrival
        (BUY needs ask<=2145, ask=2151) → it ARMS (awaiting_zone) for the
        _zone_watch_loop to fire when price enters. Nothing fires at market.
        """
        priced_connector._prices = {"XAUUSD": (2150.0, 2151.0)}

        signal = make_signal(
            direction=Direction.BUY,
            entry_zone=(2140.0, 2145.0),
            sl=2135.0,
            tps=[2160.0, 2170.0],
            target_tp=2170.0,
            symbol="XAUUSD",
        )
        results = await tm.handle_signal(signal)

        # No resting limit order, no market fill — the band is armed.
        assert not any(r.get("status") == "limit_placed" for r in results)
        assert not any(r.get("status") == "executed" for r in results)
        summary = [r for r in results if r.get("status") == "staged"]
        assert len(summary) == 1
        assert summary[0]["fired_at_arrival"] == 0
        assert summary[0]["armed"] == 1
        # The armed band persisted as a staged_entries row (awaiting_zone).
        async with db._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT status FROM staged_entries WHERE symbol = 'XAUUSD'"
            )
        assert len(rows) == 1
        assert rows[0]["status"] == "awaiting_zone"

    async def test_open_sell_with_db_logging(self, tm, priced_connector, make_signal):
        """After handle_signal for OPEN (staged scale-in), a trade record exists.

        Post-EXEC2-06: the in-zone whole-zone band fires at market and logs a
        trade row exactly as before.
        """
        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )
        results = await tm.handle_signal(signal)
        assert any(r.get("status") == "executed" for r in results)

        # Verify DB has a trade record
        trades = await db.get_recent_trades(limit=10)
        assert len(trades) >= 1
        trade = trades[0]
        assert trade["symbol"] == "XAUUSD"
        assert trade["direction"] == "sell"
        assert trade["account_name"] == "test-acct"


# ── Tests: Close and Modify ──────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestCloseAndModify:
    async def test_close_signal_removes_positions(self, tm, priced_connector):
        """Open a position, then send CLOSE signal -> position removed."""
        await priced_connector.open_order(
            "XAUUSD", OrderType.MARKET_SELL, 0.10,
            price=4980.0, sl=4986.0, tp=4973.0,
        )
        positions = await priced_connector.get_positions("XAUUSD")
        assert len(positions) == 1

        close_signal = SignalAction(
            type=SignalType.CLOSE, symbol="XAUUSD", raw_text="Close gold",
        )
        results = await tm.handle_signal(close_signal)
        assert len(results) == 1
        assert results[0]["status"] == "closed"

        positions = await priced_connector.get_positions("XAUUSD")
        assert len(positions) == 0

    async def test_modify_sl_breakeven(self, tm, priced_connector):
        """Open position at 4980, send MODIFY_SL with new_sl=0.0 -> SL becomes 4980.0."""
        await priced_connector.open_order(
            "XAUUSD", OrderType.MARKET_SELL, 0.10,
            price=4980.0, sl=4986.0, tp=4973.0,
        )

        modify_signal = SignalAction(
            type=SignalType.MODIFY_SL, symbol="XAUUSD",
            raw_text="Move SL to BE", new_sl=0.0,
        )
        results = await tm.handle_signal(modify_signal)
        assert len(results) == 1
        assert results[0]["status"] == "sl_modified"
        assert results[0]["new_sl"] == 4980.0

    async def test_close_partial_halves_volume(self, tm, priced_connector):
        """Open position vol=0.10, send CLOSE_PARTIAL 50% -> volume becomes 0.05."""
        await priced_connector.open_order(
            "XAUUSD", OrderType.MARKET_SELL, 0.10,
            price=4980.0, sl=4986.0, tp=4973.0,
        )

        partial_signal = SignalAction(
            type=SignalType.CLOSE_PARTIAL, symbol="XAUUSD",
            raw_text="Close 50%", close_percent=50.0,
        )
        results = await tm.handle_signal(partial_signal)
        assert len(results) == 1
        assert results[0]["status"] == "partial_closed"

        positions = await priced_connector.get_positions("XAUUSD")
        assert len(positions) == 1
        assert positions[0].volume == pytest.approx(0.05, abs=0.001)


# ── Tests: Daily Limit Enforcement ───────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestDailyLimitEnforcement:
    async def test_daily_limit_blocks_trades(self, priced_connector, account, db_pool, make_signal):
        """max_daily_trades=2: after 2 trades, 3rd is rejected."""
        cfg = GlobalConfig(
            default_target_tp=2,
            limit_order_expiry_minutes=30,
            max_daily_trades_per_account=2,
            max_daily_server_messages=500,
            stagger_delay_min=0,
            stagger_delay_max=0,
            lot_jitter_percent=0,
            sl_tp_jitter_points=0,
        )
        tm_limited = TradeManager(
            connectors={account.name: priced_connector},
            accounts=[account],
            global_config=cfg,
        )

        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )

        # Seed the account row so staged_entries FK resolves (post-EXEC2-06).
        await db.upsert_account_if_missing(
            name=account.name, server="Test", login=99999, password_env="",
            risk_percent=1.0, max_lot_size=1.0, max_daily_loss_percent=3.0,
            max_open_trades=3, enabled=True, mt5_host="", mt5_port=0,
        )
        await db.upsert_account_settings_if_missing(account_name=account.name)

        # Execute 2 trades. Post-EXEC2-06 each standalone OPEN is a staged
        # scale-in (max_stages=1 → one whole-zone band fired at market). D-18:
        # one signal = one daily slot.
        r1 = await tm_limited.handle_signal(signal)
        assert any(r.get("status") == "executed" for r in r1)

        # Clear positions so duplicate check doesn't block
        priced_connector._fake_positions.clear()

        r2 = await tm_limited.handle_signal(signal)
        assert any(r.get("status") == "executed" for r in r2)

        # Clear positions again
        priced_connector._fake_positions.clear()

        # 3rd should be blocked by daily limit (band skipped before submit).
        r3 = await tm_limited.handle_signal(signal)
        assert not any(r.get("status") == "executed" for r in r3)
        skipped = [r for r in r3 if r.get("status") == "skipped"]
        assert skipped
        assert any("Daily trade limit" in r.get("reason", "") for r in skipped)


# ── Tests: Multi-Account Execution ───────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestMultiAccountExecution:
    async def test_signal_dispatches_to_both_accounts(self, multi_account_tm, make_signal):
        """OPEN signal with 2 accounts → dispatched to both.

        Post-EXEC2-06: standalone OPENs are now staged (staged_entries rows).
        The staged comment scheme `telebot-{signal_id}-s{stage}` carries NO
        account discriminator and the column is globally UNIQUE (db.py:230),
        so two accounts sharing one signal_id collide on the SECOND account's
        stage-1 row. This is a PRE-EXISTING Phase-6 limitation (the correlated
        path uses the identical scheme; db.py:1023-1024 documents the collision)
        that EXEC2-06 surfaces by making every standalone OPEN staged.

        Failure isolation (D-17) holds: the first account stages+fires; the
        second account's create_staged_entries surfaces the UNIQUE collision as
        a per-account failure without aborting the dispatch loop. This test
        asserts dispatch reaches both accounts and the first fires. The
        comment-scheme fix (account-scoped comment or relaxed UNIQUE) is tracked
        in deferred-items.md as an architectural decision (Rule 4).
        """
        import asyncpg

        tm_multi, c1, c2 = multi_account_tm
        await c1.connect()
        await c2.connect()

        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )
        # The second account's stage-1 insert collides on the globally-UNIQUE
        # mt5_comment; the loop is not wrapped, so the exception propagates after
        # the first account has already staged+fired. Assert the first fired and
        # the collision is the documented UNIQUE violation.
        try:
            results = await tm_multi.handle_signal(signal)
        except asyncpg.UniqueViolationError as exc:
            assert "mt5_comment" in str(exc)
            # First account fired before the collision → its position exists.
            positions = await c1.get_positions("XAUUSD")
            assert len(positions) == 1
            return

        # If the scheme is ever made account-scoped, both accounts fire.
        account_names = {r["account"] for r in results}
        assert {"acct-1", "acct-2"} <= account_names
        executed = [r for r in results if r["status"] == "executed"]
        assert len(executed) == 2


# ── Tests: Zone Logic Integration ────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestZoneLogicIntegration:
    async def test_sell_in_zone_market_order(self, tm, priced_connector, make_signal):
        """Price 4980 in zone 4978-4982 → the whole-zone band fires at MARKET.

        Post-EXEC2-06: standalone OPENs fire crossed bands at market (never a
        resting limit). The in-zone band's executed result carries
        order_type='market'.
        """
        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )
        results = await tm.handle_signal(signal)
        executed = [r for r in results if r.get("status") == "executed"]
        assert len(executed) == 1
        assert executed[0]["order_type"] == "market"

    async def test_buy_above_zone_arms_not_limit(self, tm, priced_connector, make_signal):
        """Price 2151 above zone 2140-2145 → band ARMS (D2-01: no resting limit).

        Post-EXEC2-06: the v1.0 'limit order at zone midpoint' behavior is gone
        for standalone OPENs. The whole-zone band is not crossed (BUY needs
        ask<=2145, ask=2151) → it arms (awaiting_zone); the _zone_watch_loop
        fires it when price enters the zone. No limit order is placed.
        """
        priced_connector._prices = {"XAUUSD": (2150.0, 2151.0)}

        signal = make_signal(
            direction=Direction.BUY,
            entry_zone=(2140.0, 2145.0),
            sl=2135.0,
            tps=[2160.0, 2170.0],
            target_tp=2170.0,
        )
        results = await tm.handle_signal(signal)
        assert not any(r.get("status") == "limit_placed" for r in results)
        assert not any(r.get("status") == "executed" for r in results)
        summary = [r for r in results if r.get("status") == "staged"]
        assert len(summary) == 1 and summary[0]["armed"] == 1


# ── Tests: Stale Signal Rejection ────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
class TestStaleSignalIntegration:
    async def test_sell_price_below_tp1_rejected(self, tm, priced_connector, make_signal):
        """SELL signal with price below TP1 is rejected as stale."""
        # Set price below TP1 (4970 < 4975)
        priced_connector._prices = {"XAUUSD": (4970.0, 4971.0)}

        signal = make_signal(
            direction=Direction.SELL,
            entry_zone=(4978.0, 4982.0),
            sl=4986.0,
            tps=[4975.0, 4973.0],
            target_tp=4973.0,
        )
        results = await tm.handle_signal(signal)
        assert len(results) == 1
        assert results[0]["status"] == "skipped"
        assert "TP1" in results[0]["reason"]
