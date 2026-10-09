from __future__ import annotations

import asyncio
import os
from pathlib import Path

from pyrogram import Client


async def _upload(path: Path, caption: str) -> int:
    required = ("API_ID", "API_HASH", "BOT_TOKEN", "TELEGRAM_TARGET")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing GitHub Secrets/environment values: " + ", ".join(missing))
    try:
        api_id = int(os.environ["API_ID"])
    except ValueError as exc:
        raise RuntimeError("API_ID must be an integer") from exc

    client = Client(
        "tgvideo_bot",
        api_id=api_id,
        api_hash=os.environ["API_HASH"],
        bot_token=os.environ["BOT_TOKEN"],
        in_memory=True,
    )
    async with client:
        sent = await client.send_video(
            chat_id=os.environ["TELEGRAM_TARGET"],
            video=str(path),
            caption=caption[:1024],
            supports_streaming=True,
        )
        return int(sent.id)


def upload_video(path: Path, caption: str) -> int:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("Upload file is missing or empty")
    # Keep a safety margin below Telegram's common 2 GiB MTProto file ceiling.
    if path.stat().st_size > 2_000_000_000:
        raise RuntimeError(
            "File exceeds the configured 2,000,000,000-byte limit. "
            "Split/re-encode it in a separate, explicitly configured processing step."
        )
    return asyncio.run(_upload(path, caption))
