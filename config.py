from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from os import environ
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    # ── Telegram ──
    tg_api_id: int
    tg_api_hash: str
    tg_session: str
    tg_chat_ids: list[int]

    # ── Discord webhooks ──
    discord_webhook_url: str  # #signals (raw relay)
    discord_webhook_executions: str  # #executions (trade confirmations)
    discord_webhook_alerts: str  # #alerts (errors, warnings)

    # ── General ──
    timezone: ZoneInfo

    # ── Trading ──
    trading_enabled: bool
    trading_dry_run: bool
    mt5_backend: str  # "dry_run", "rest_api"
    mt5_host: str
    mt5_port: int
    mt5_magic_number: int
    mt5_api_key: str
    mt5_use_tls: bool
    accounts_config_path: str
    database_url: str

    # ── Dashboard ──
    dashboard_enabled: bool
    dashboard_port: int
    dashboard_user: str
    dashboard_pass: str


def _load_settings() -> Settings:
    def _req(key: str, validator=None) -> str:
        val = environ.get(key)
        if not val:
            raise SystemExit(f"FATAL: Missing required env var: {key}")
        if validator and not validator(val):
            raise SystemExit(f"FATAL: Invalid format for {key}")
        return val

    def _opt(key: str, default: str = "") -> str:
        return environ.get(key, default)

    def _is_numeric(v: str) -> bool:
        return v.isdigit()

    def _is_pg_url(v: str) -> bool:
        return v.startswith(("postgres://", "postgresql://"))

    return Settings(
        tg_api_id=int(_req("TG_API_ID", validator=_is_numeric)),
        tg_api_hash=_req("TG_API_HASH"),
        tg_session=_req("TG_SESSION"),
        tg_chat_ids=[int(x.strip()) for x in _req("TG_CHAT_IDS").split(",")],
        discord_webhook_url=_req("DISCORD_WEBHOOK_URL"),
        discord_webhook_executions=_opt("DISCORD_WEBHOOK_EXECUTIONS"),
        discord_webhook_alerts=_opt("DISCORD_WEBHOOK_ALERTS"),
        timezone=ZoneInfo(_req("TIMEZONE")),
        trading_enabled=_opt("TRADING_ENABLED", "false").lower() in ("true", "1", "yes"),
        trading_dry_run=_opt("TRADING_DRY_RUN", "true").lower() in ("true", "1", "yes"),
        mt5_backend=_opt("MT5_BACKEND", "dry_run"),
        mt5_host=_opt("MT5_HOST", "localhost"),
        mt5_port=int(_opt("MT5_PORT", "18812")),
        mt5_magic_number=int(_opt("MT5_MAGIC_NUMBER", "202603")),
        mt5_api_key=_opt("MT5_API_KEY", ""),
        mt5_use_tls=_opt("MT5_USE_TLS", "true").lower() in ("true", "1", "yes"),
        accounts_config_path=_opt("ACCOUNTS_CONFIG", "accounts.json"),
        database_url=_req("DATABASE_URL", validator=_is_pg_url),
        dashboard_enabled=_opt("DASHBOARD_ENABLED", "true").lower() in ("true", "1", "yes"),
        dashboard_port=int(_opt("DASHBOARD_PORT", "8080")),
        dashboard_user=_opt("DASHBOARD_USER", "admin"),
        dashboard_pass=_req("DASHBOARD_PASS"),
    )


settings = _load_settings()


def load_accounts_config(path: str | None = None) -> dict:
    """Load accounts.json and resolve password env vars."""
    config_path = Path(path or settings.accounts_config_path)
    if not config_path.exists():
        logger.warning("Accounts config not found: %s — trading disabled", config_path)
        return {"accounts": [], "global": {}}

    with open(config_path) as f:
        data = json.load(f)

    # Resolve password env vars
    for acct in data.get("accounts", []):
        env_key = acct.get("password_env", "")
        if env_key:
            password = environ.get(env_key, "")
            if not password:
                logger.warning("Password env var %s not set for account %s", env_key, acct.get("name"))
            acct["_password"] = password

    return data
