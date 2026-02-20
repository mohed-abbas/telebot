"""Run this locally to generate a Telethon StringSession.

It will prompt for your phone number and the login code Telegram sends you.
Copy the output string into your .env file as TG_SESSION.

Usage:
    pip install telethon
    python generate_session.py
"""

import asyncio

from telethon import TelegramClient, errors
from telethon.sessions import StringSession


async def main():
    api_id = int(input("Enter your Telegram API ID: "))
    api_hash = input("Enter your Telegram API hash: ")
    phone = input("Enter your phone number (with country code, e.g. +33...): ")

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()

    # First attempt: sends code via Telegram app
    result = await client.send_code_request(phone)
    code_type = type(result.type).__name__
    print(f"\n>>> Code delivery method: {code_type}")
    print(f">>> Expected code length: {getattr(result.type, 'length', 'unknown')}")

    retry = input("\nDid you receive the code? (y/n): ").strip().lower()

    if retry == "n":
        # Second attempt: force SMS delivery
        print("\nRequesting code via SMS instead...")
        result = await client.send_code_request(phone, force_sms=True)
        code_type = type(result.type).__name__
        print(f">>> New delivery method: {code_type}")
        print(f">>> Expected code length: {getattr(result.type, 'length', 'unknown')}")
        print("\nCheck your SMS messages now.")

    code = input("\nEnter the 5-digit numeric code: ")

    try:
        await client.sign_in(phone, code, phone_code_hash=result.phone_code_hash)
    except errors.SessionPasswordNeededError:
        password = input("Enter your 2FA password: ")
        await client.sign_in(password=password)

    session_string = client.session.save()
    print("\n--- Your session string (copy this into .env as TG_SESSION) ---")
    print(session_string)
    print("--- End of session string ---")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
