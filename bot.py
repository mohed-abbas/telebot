import asyncio
import io
import logging
from datetime import datetime

import httpx
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

from config import settings, load_accounts_config
from discord_sender import send_message
from signal_parser import parse_signal, format_parsed_signal

MAX_FILE_SIZE = 8 * 1024 * 1024  # 8 MB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def format_message(
    group_name: str, sender_name: str, timestamp: datetime, text: str
) -> str:
    time_str = timestamp.strftime("%H:%M")
    return f"[{group_name}] [{sender_name} \u2022 {time_str}]: {text}"


async def resolve_group_names(client: TelegramClient) -> dict[int, str]:
    names = {}
    for chat_id in settings.tg_chat_ids:
        try:
            entity = await client.get_entity(chat_id)
            names[chat_id] = getattr(entity, "title", None) or str(chat_id)
        except Exception as exc:
            logger.warning("Could not resolve name for chat %d: %s", chat_id, exc)
            names[chat_id] = str(chat_id)
    return names


def _setup_trading(http: httpx.AsyncClient):
    """Initialize the trading pipeline if enabled. Returns (executor, notifier) or (None, None)."""
    if not settings.trading_enabled:
        logger.info("Trading is DISABLED (TRADING_ENABLED=false)")
        return None, None

    import db
    from models import AccountConfig, GlobalConfig
    from mt5_connector import create_connector
    from trade_manager import TradeManager
    from executor import Executor
    from notifier import Notifier

    # Initialize database
    db.init_db(settings.db_path)

    # Load accounts config
    accts_data = load_accounts_config()
    accts_raw = accts_data.get("accounts", [])
    global_raw = accts_data.get("global", {})

    if not accts_raw:
        logger.warning("No accounts configured — trading disabled")
        return None, None

    global_config = GlobalConfig(
        default_target_tp=global_raw.get("default_target_tp", 2),
        limit_order_expiry_minutes=global_raw.get("limit_order_expiry_minutes", 30),
        max_daily_trades_per_account=global_raw.get("max_daily_trades_per_account", 30),
        max_daily_server_messages=global_raw.get("max_daily_server_messages", 500),
        stagger_delay_min=global_raw.get("stagger_delay_min", 1.0),
        stagger_delay_max=global_raw.get("stagger_delay_max", 5.0),
        lot_jitter_percent=global_raw.get("lot_jitter_percent", 4.0),
        sl_tp_jitter_points=global_raw.get("sl_tp_jitter_points", 0.8),
    )

    accounts = []
    connectors = {}
    backend = settings.mt5_backend if not settings.trading_dry_run else "dry_run"

    for raw in accts_raw:
        acct = AccountConfig(
            name=raw["name"],
            server=raw["server"],
            login=raw["login"],
            password_env=raw.get("password_env", ""),
            risk_percent=raw.get("risk_percent", 1.0),
            max_lot_size=raw.get("max_lot_size", 1.0),
            max_daily_loss_percent=raw.get("max_daily_loss_percent", 3.0),
            max_open_trades=raw.get("max_open_trades", 3),
            enabled=raw.get("enabled", True),
        )
        accounts.append(acct)

        password = raw.get("_password", "")
        conn = create_connector(
            backend=backend,
            account_name=acct.name,
            server=acct.server,
            login=acct.login,
            password=password,
            mt5_host=settings.mt5_host,
            mt5_port=settings.mt5_port,
        )
        connectors[acct.name] = conn

    tm = TradeManager(connectors, accounts, global_config)
    executor = Executor(tm, global_config)
    notifier = Notifier(
        http=http,
        executions_webhook=settings.discord_webhook_executions or None,
        alerts_webhook=settings.discord_webhook_alerts or None,
    )

    mode = "DRY-RUN" if settings.trading_dry_run else backend.upper()
    logger.info(
        "Trading ENABLED (%s) — %d account(s) configured",
        mode, len(accounts),
    )

    return executor, notifier


async def main() -> None:
    client = TelegramClient(
        StringSession(settings.tg_session),
        settings.tg_api_id,
        settings.tg_api_hash,
        connection_retries=10,
        retry_delay=5,
        auto_reconnect=True,
    )

    http = httpx.AsyncClient(timeout=30.0)

    await client.start()

    # ── Initialize trading pipeline ─────────────────────────────────
    executor, notifier = _setup_trading(http)

    if executor:
        # Connect all MT5 accounts
        for acct_name, connector in executor.tm.connectors.items():
            connected = await connector.connect()
            if not connected and notifier:
                await notifier.notify_connection_lost(acct_name, "Initial connection failed")

        # Start background tasks (pending order cleanup)
        await executor.start()

    group_names = await resolve_group_names(client)
    for chat_id, name in group_names.items():
        logger.info("Watching: %s (%d)", name, chat_id)

    @client.on(events.NewMessage(chats=settings.tg_chat_ids))
    async def handler(event):
        sender = await event.get_sender()
        if sender is None:
            sender_name = "Unknown"
        else:
            parts = filter(
                None,
                [
                    getattr(sender, "first_name", None),
                    getattr(sender, "last_name", None),
                ],
            )
            sender_name = (
                " ".join(parts) or getattr(sender, "title", None) or "Unknown"
            )

        group_name = group_names.get(event.chat_id, str(event.chat_id))
        ts = event.message.date.astimezone(settings.timezone)
        text = event.message.text or event.message.message or ""
        media = event.message.media

        has_photo = isinstance(media, MessageMediaPhoto)
        has_video = (
            isinstance(media, MessageMediaDocument)
            and media.document
            and media.document.mime_type
            and media.document.mime_type.startswith("video/")
        )

        if not text and not has_photo and not has_video:
            logger.debug("Skipping message %d (no text/media)", event.message.id)
            return

        # Build the header line
        if text:
            formatted = format_message(group_name, sender_name, ts, text)
        else:
            formatted = format_message(group_name, sender_name, ts, "")

        # ── Relay to #signals (existing behavior) ───────────────────
        if has_photo or has_video:
            file_size = 0
            if has_photo:
                file_size = event.message.file.size or 0
                media_type = "photo"
            elif has_video:
                file_size = media.document.size or 0
                media_type = "video"

            if file_size > MAX_FILE_SIZE:
                notice = f"[A {media_type} was shared ({file_size / (1024*1024):.1f} MB) — too large to relay]"
                if text:
                    formatted += f"\n{notice}"
                else:
                    formatted = format_message(group_name, sender_name, ts, notice)
                logger.info("Relaying (large %s skipped): %s", media_type, formatted[:80])
                await send_message(http, settings.discord_webhook_url, formatted)
            else:
                buffer = io.BytesIO()
                await client.download_media(event.message, file=buffer)
                file_bytes = buffer.getvalue()

                ext = event.message.file.ext or (".jpg" if has_photo else ".mp4")
                filename = f"{media_type}_{event.message.id}{ext}"

                logger.info("Relaying (%s, %.1f KB): %s", media_type, len(file_bytes) / 1024, formatted[:80])
                await send_message(
                    http, settings.discord_webhook_url, formatted,
                    file_bytes=file_bytes, filename=filename,
                )
        else:
            logger.info("Relaying: %s", formatted[:80])
            await send_message(http, settings.discord_webhook_url, formatted)

        # ── Signal parsing & trade execution ────────────────────────
        if text:
            signal = parse_signal(text)
            if signal:
                parsed_log = format_parsed_signal(signal)
                logger.info("Signal detected: %s", parsed_log.replace("\n", " | "))

                if executor and settings.trading_enabled:
                    try:
                        results = await executor.execute_signal(signal)
                        if notifier:
                            await notifier.notify_execution(signal, results)
                    except Exception as exc:
                        logger.error("Trade execution error: %s", exc)
                        if notifier:
                            await notifier.notify_alert(
                                f"EXECUTION ERROR: {exc}\nSignal: {signal.raw_text[:200]}"
                            )

    logger.info("Bot started. Listening to %d chat(s)", len(settings.tg_chat_ids))

    # ── Launch dashboard ────────────────────────────────────────────
    if settings.dashboard_enabled:
        import uvicorn
        from dashboard import app as dashboard_app, init_dashboard

        init_dashboard(executor, notifier, settings)

        config = uvicorn.Config(
            dashboard_app,
            host="0.0.0.0",
            port=settings.dashboard_port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        # Run dashboard in background — don't block Telegram listener
        asyncio.create_task(server.serve())
        logger.info("Dashboard running on http://0.0.0.0:%d", settings.dashboard_port)

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
