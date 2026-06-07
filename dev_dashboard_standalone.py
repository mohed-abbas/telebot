"""dev_dashboard_standalone.py — DEV-ONLY dashboard runner for the Docker dev stack.

Boots the FastAPI dashboard (legacy HTMX `/` + SPA `/app`) with a DryRun executor
stub and the dev Postgres, WITHOUT starting bot.py / the Telegram client. This
avoids the TG_SESSION conflict with the live VPS bot during the Phase-12 cutover
parity check.

Unlike dev_dashboard.py, this runner does NOT import tests.conftest (which pulls
in pytest / pytest_asyncio — absent from the runtime image that installs only
requirements.txt). The dry-run executor stub below is ported verbatim from
tests/conftest.py::_make_dryrun_executor so the dashboard surface
(_get_all_positions / _get_accounts_overview) has deterministic data.

NOT for production. Runs on 0.0.0.0:8080 inside the container.
"""

import asyncio
import os
import types

import uvicorn

import db
import dashboard
from models import AccountConfig
from mt5_connector import DryRunConnector, Position as MT5Position


def _make_dryrun_executor():
    """Lightweight executor stub backed by a DryRunConnector.

    Ported from tests/conftest.py::_make_dryrun_executor. Mirrors only the surface
    dashboard._get_all_positions / _get_accounts_overview reach:
    executor.tm.connectors, executor.tm.accounts, executor.cfg.max_daily_trades_per_account.
    Injects one deterministic XAUUSD position so positions/formatting routes have a
    stable row without a live MT5 bridge.
    """
    conn = DryRunConnector("Vantage Demo-10k", "TestServer", 12345, "pass")
    conn._connected = True  # connected without awaiting connect() (no MT5 bridge)
    conn._fake_positions = {
        100001: MT5Position(
            ticket=100001, symbol="XAUUSD", direction="buy", volume=0.30,
            open_price=2800.123, sl=2790.0, tp=2820.0, profit=12.5,
        )
    }
    conn.set_simulated_price("XAUUSD", 2805.0, 2805.2)

    acct = AccountConfig(
        name="Vantage Demo-10k", server="TestServer", login=12345,
        password_env="TEST_PASS", risk_percent=1.0, max_lot_size=1.0,
        max_daily_loss_percent=3.0, max_open_trades=3, enabled=True,
    )

    tm = types.SimpleNamespace(
        connectors={"Vantage Demo-10k": conn},
        accounts={"Vantage Demo-10k": acct},
    )
    cfg = types.SimpleNamespace(max_daily_trades_per_account=30)
    return types.SimpleNamespace(tm=tm, cfg=cfg)


async def main() -> None:
    await db.init_db(os.environ["DATABASE_URL"])
    dashboard.init_dashboard(_make_dryrun_executor(), notifier=None, settings=None)
    config = uvicorn.Config(
        dashboard.app, host="0.0.0.0", port=8080, log_level="info"
    )
    await uvicorn.Server(config).serve()


if __name__ == "__main__":
    asyncio.run(main())
