"""W4-RECONCILE — startup reconcile of staged rows / broker positions (D-24).

The reconnect path calls ``executor._sync_positions`` after every
disconnect/reconnect. Before this fix, a crash/restart left phantom 'armed'
staged rows and just-opened broker positions un-reconciled until the next
disconnect. ``bot._startup_reconcile`` now runs the SAME per-account sync once
at startup, for connected accounts only, isolating per-account failures.

Named distinctively so it does not collide with existing staged tests.
"""
from __future__ import annotations

import os
import sys

# bot.py imports config.settings at module load, which requires these env vars.
# Set safe test-only values before importing bot so _load_settings() succeeds.
_ENV_DEFAULTS = {
    "TG_API_ID": "12345",
    "TG_API_HASH": "test_hash",
    "TG_SESSION": "test_session",
    "TG_CHAT_IDS": "-1001",
    "DISCORD_WEBHOOK_URL": "https://discord.example/webhook",
    "TIMEZONE": "UTC",
    "DATABASE_URL": "postgresql://u:p@localhost:5432/telebot",
    "SESSION_SECRET": "x" * 48,  # >= 32 bytes of entropy
    "DASHBOARD_PASS_HASH": "$argon2id$" + ("a" * 80),  # >= 60 chars
}
for _k, _v in _ENV_DEFAULTS.items():
    os.environ.setdefault(_k, _v)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bot  # noqa: E402


class _FakeConnector:
    def __init__(self, connected: bool) -> None:
        self.connected = connected


class _FakeTradeManager:
    def __init__(self, connectors) -> None:
        self.connectors = connectors


class _FakeExecutor:
    def __init__(self, connectors) -> None:
        self.tm = _FakeTradeManager(connectors)
        self.synced: list[str] = []
        self.fail_for: set[str] = set()

    async def _sync_positions(self, acct_name, connector) -> None:
        self.synced.append(acct_name)
        if acct_name in self.fail_for:
            raise RuntimeError(f"boom {acct_name}")


async def test_startup_reconcile_runs_only_for_connected_accounts():
    connectors = {
        "acctA": _FakeConnector(connected=True),
        "acctB": _FakeConnector(connected=False),
        "acctC": _FakeConnector(connected=True),
    }
    executor = _FakeExecutor(connectors)

    await bot._startup_reconcile(executor)

    # Reconcile runs for connected accounts only, via the existing sync method.
    assert executor.synced == ["acctA", "acctC"]


async def test_startup_reconcile_isolates_per_account_failure():
    connectors = {
        "acctA": _FakeConnector(connected=True),
        "acctB": _FakeConnector(connected=True),
    }
    executor = _FakeExecutor(connectors)
    executor.fail_for = {"acctA"}  # first account blows up

    # A failure on one account must not abort startup or propagate.
    await bot._startup_reconcile(executor)

    # Both connected accounts were still attempted.
    assert executor.synced == ["acctA", "acctB"]
