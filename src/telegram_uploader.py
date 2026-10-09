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
    target = os.environ["TELEGRAM_TARGET"].strip()
    peer_source = os.environ.get("PYROGRAM_PEER_SOURCE", "").strip()

    async with client:
        upload_target: int | str = target
        if peer_source:
            # A numeric private-channel ID alone does not carry MTProto's
            # channel access_hash. Resolve the private invite link (or public
            # username) first so Pyrogram caches the correct InputPeer.
            chat = await client.get_chat(peer_source)
            if target.lstrip("-").isdigit() and int(chat.id) != int(target):
                raise RuntimeError(
                    "PYROGRAM_PEER_SOURCE resolved to a different chat than TELEGRAM_TARGET."
                )
            await client.resolve_peer(chat.id)
            upload_target = chat.id
        elif target.startswith("-100") and target[1:].isdigit():
            # Do not pretend a Bot API-valid ID is necessarily enough for MTProto.
            try:
                await client.resolve_peer(int(target))
            except Exception as exc:
                raise RuntimeError(
                    "Pyrogram cannot resolve the private channel from TELEGRAM_TARGET alone. "
                    "Add GitHub secret PYROGRAM_PEER_SOURCE containing a valid private invite "
                    "link for this channel (or its public @username). The bot must already have "
                    "access, and the source must identify the same destination."
                ) from exc

        sent = await client.send_video(
            chat_id=upload_target,
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
