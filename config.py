from dataclasses import dataclass
from os import environ
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    tg_api_id: int
    tg_api_hash: str
    tg_session: str
    tg_chat_ids: list[int]
    discord_webhook_url: str
    timezone: ZoneInfo


def _load_settings() -> Settings:
    def _req(key: str) -> str:
        val = environ.get(key)
        if not val:
            raise SystemExit(f"Missing required env var: {key}")
        return val

    return Settings(
        tg_api_id=int(_req("TG_API_ID")),
        tg_api_hash=_req("TG_API_HASH"),
        tg_session=_req("TG_SESSION"),
        tg_chat_ids=[int(x.strip()) for x in _req("TG_CHAT_IDS").split(",")],
        discord_webhook_url=_req("DISCORD_WEBHOOK_URL"),
        timezone=ZoneInfo(_req("TIMEZONE")),
    )


settings = _load_settings()
