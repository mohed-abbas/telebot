import asyncio
import json
import logging

import httpx

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0


async def send_message(
    client: httpx.AsyncClient,
    webhook_url: str,
    text: str,
    file_bytes: bytes | None = None,
    filename: str | None = None,
) -> None:
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            if file_bytes and filename:
                resp = await client.post(
                    webhook_url,
                    data={"payload_json": json.dumps({"content": text[:2000]})},
                    files={"file": (filename, file_bytes)},
                )
            else:
                resp = await client.post(webhook_url, json={"content": text[:2000]})
            resp.raise_for_status()
            logger.info("Discord message sent (attempt %d)", attempt)
            return
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            if attempt == _MAX_RETRIES:
                logger.error(
                    "Discord send failed after %d attempts: %s", _MAX_RETRIES, exc
                )
                return
            delay = _BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(
                "Discord send attempt %d failed (%s), retrying in %.1fs",
                attempt,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
