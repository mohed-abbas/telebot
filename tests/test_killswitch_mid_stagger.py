"""Unit test for the kill-switch mid-stagger re-check (finding §4.5).

Executor.execute_signal reads self._trading_paused once at entry, then loops
over accounts with random stagger sleeps between each. If the kill switch fires
mid-stagger, the in-flight signal must NOT keep opening new positions on the
remaining accounts. This test drives that race with lightweight fakes (no DB
or broker) by flipping the kill switch from inside the first account's
execution and asserting the rest are skipped with the kill-switch reason.
"""

import asyncio
import types

import pytest

from executor import Executor
from models import GlobalConfig


class _FakeConn:
    connected = True


class _FakeAcct:
    enabled = True


def _make_executor(account_names):
    connectors = {name: _FakeConn() for name in account_names}
    accounts = {name: _FakeAcct() for name in account_names}
    tm = types.SimpleNamespace(connectors=connectors, accounts=accounts)
    cfg = GlobalConfig(stagger_delay_min=0.0, stagger_delay_max=0.0)
    return Executor(trade_manager=tm, global_config=cfg, notifier=None)


@pytest.mark.asyncio
async def test_kill_switch_mid_stagger_skips_remaining_accounts():
    account_names = [f"acct{i}" for i in range(5)]
    ex = _make_executor(account_names)

    executed = []

    async def fake_single(signal, target_account, source_name=""):
        executed.append(target_account)
        # Kill switch fires while the first account is in flight.
        if len(executed) == 1:
            ex._trading_paused = True
        return [{"account": target_account, "status": "opened"}]

    ex._execute_single_account = fake_single

    results = await ex.execute_signal(signal=object(), source_name="test")

    # Exactly one account should have opened a position; the kill switch must
    # have stopped all remaining accounts.
    assert len(executed) == 1

    opened = [r for r in results if r.get("status") == "opened"]
    skipped_ks = [
        r for r in results
        if r.get("status") == "skipped" and "kill switch" in r.get("reason", "").lower()
    ]
    assert len(opened) == 1
    # The remaining four accounts must be recorded as skipped for the kill switch.
    assert len(skipped_ks) == 4
    assert {r["account"] for r in skipped_ks} == set(account_names) - {executed[0]}


@pytest.mark.asyncio
async def test_all_accounts_execute_when_not_paused():
    account_names = [f"acct{i}" for i in range(4)]
    ex = _make_executor(account_names)

    executed = []

    async def fake_single(signal, target_account, source_name=""):
        executed.append(target_account)
        return [{"account": target_account, "status": "opened"}]

    ex._execute_single_account = fake_single

    results = await ex.execute_signal(signal=object(), source_name="test")

    assert sorted(executed) == sorted(account_names)
    assert all(r.get("status") == "opened" for r in results)
