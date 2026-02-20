"""Lists all Telegram groups/channels your account is in, with their IDs.

Usage:
    python list_groups.py
"""

import asyncio
from os import environ

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat

load_dotenv()

async def main():
    client = TelegramClient(
        StringSession(environ["TG_SESSION"]),
        int(environ["TG_API_ID"]),
        environ["TG_API_HASH"],
    )
    await client.connect()

    print(f"{'GROUP NAME':<40} {'CHAT ID':<20} {'TYPE'}")
    print("-" * 75)

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, (Channel, Chat)):
            # Telethon gives the full marked ID via dialog.id
            print(f"{dialog.name:<40} {dialog.id:<20} {type(entity).__name__}")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
