import asyncio
import io
import logging
from datetime import datetime

import httpx
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

from config import settings
from discord_sender import send_message

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

        # Handle media
        if has_photo or has_video:
            file_size = 0
            if has_photo:
                # Photo sizes are in message.photo.sizes; use file.size from Telethon
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

    logger.info("Bot started. Listening to %d chat(s)", len(settings.tg_chat_ids))
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
