from __future__ import annotations

import asyncio
import os
from pathlib import Path

from pyrogram import Client


def _client(api_id: int, api_hash: str, bot_token: str) -> Client:
    session_string = os.environ.get("PYROGRAM_SESSION_STRING", "").strip()
    if session_string:
        # Keep the same MTProto auth key between GitHub Actions runs. Telegram
        # access hashes are tied to an authorization session, not just a bot ID.
        return Client(
            "tgvideo_bot",
            api_id=api_id,
            api_hash=api_hash,
            session_string=session_string,
            in_memory=True,
        )
    return Client(
        "tgvideo_bot",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,
        in_memory=True,
    )


def _is_invite_link(value: str) -> bool:
    value = value.lower()
    return any(marker in value for marker in (
        "t.me/+", "t.me/joinchat/", "telegram.me/+", "telegram.me/joinchat/"
    ))


async def _upload(path: Path, caption: str) -> int:
    required = ("API_ID", "API_HASH", "BOT_TOKEN", "TELEGRAM_TARGET")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing GitHub Secrets/environment values: " + ", ".join(missing))
    try:
        api_id = int(os.environ["API_ID"])
    except ValueError as exc:
        raise RuntimeError("API_ID must be an integer") from exc

    api_hash = os.environ["API_HASH"].strip()
    bot_token = os.environ["BOT_TOKEN"].strip()
    target = os.environ["TELEGRAM_TARGET"].strip()
    peer_source = os.environ.get("PYROGRAM_PEER_SOURCE", "").strip()
    session_string = os.environ.get("PYROGRAM_SESSION_STRING", "").strip()
    access_hash_text = os.environ.get("PYROGRAM_CHANNEL_ACCESS_HASH", "").strip()

    client = _client(api_id, api_hash, bot_token)

    async with client:
        me = await client.get_me()
        if not me.is_bot:
            raise RuntimeError("PYROGRAM_SESSION_STRING must belong to the configured bot, not a user account.")

        upload_target: int | str = target

        # Public usernames resolve the channel and its real access hash normally.
        # If the channel was made private again after bootstrap, fall back to the
        # stored session-specific access hash below.
        resolved_public = False
        if peer_source and not _is_invite_link(peer_source):
            try:
                chat = await client.get_chat(peer_source)
                if target.lstrip("-").isdigit() and int(chat.id) != int(target):
                    raise RuntimeError(
                        "PYROGRAM_PEER_SOURCE resolved to a different chat than TELEGRAM_TARGET."
                    )
                await client.resolve_peer(chat.id)
                upload_target = chat.id
                resolved_public = True
            except Exception as exc:
                if not (target.startswith("-100") and target[1:].isdigit() and session_string and access_hash_text):
                    raise RuntimeError(
                        f"Could not resolve PYROGRAM_PEER_SOURCE ({type(exc).__name__}: {exc})"
                    ) from exc
                print("INFO Public peer source is unavailable; using the stored private-channel access hash.")

        if not resolved_public and target.startswith("-100") and target[1:].isdigit():
            # A Bot API chat ID alone is insufficient for MTProto. The previous
            # zero-access-hash workaround passed peer construction but Telegram
            # rejected the actual upload with CHANNEL_INVALID.
            if not session_string:
                raise RuntimeError(
                    "Private-channel MTProto upload needs a persistent bot session. "
                    "Set PYROGRAM_SESSION_STRING and PYROGRAM_CHANNEL_ACCESS_HASH. "
                    "A fresh bot_token session plus numeric channel ID cannot discover "
                    "the private channel access hash by itself."
                )
            if not access_hash_text:
                raise RuntimeError(
                    "Missing PYROGRAM_CHANNEL_ACCESS_HASH. Generate it using "
                    "src/bootstrap_pyrogram_session.py while the channel has a public username."
                )
            try:
                access_hash = int(access_hash_text)
            except ValueError as exc:
                raise RuntimeError("PYROGRAM_CHANNEL_ACCESS_HASH must be an integer.") from exc
            if access_hash == 0:
                raise RuntimeError(
                    "PYROGRAM_CHANNEL_ACCESS_HASH must be the real non-zero hash; zero caused CHANNEL_INVALID."
                )

            channel_id = int(target[4:])
            await client.storage.update_peers(
                [(int(target), access_hash, "channel", None, None)]
            )
            peer = await client.resolve_peer(int(target))
            if getattr(peer, "channel_id", None) != channel_id:
                raise RuntimeError("Pyrogram resolved a peer that does not match TELEGRAM_TARGET.")
            if getattr(peer, "access_hash", None) != access_hash:
                raise RuntimeError("Pyrogram did not load the configured channel access hash.")
            upload_target = int(target)

        elif not resolved_public:
            upload_target = int(target) if target.lstrip("-").isdigit() else target
            await client.resolve_peer(upload_target)

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
    if path.stat().st_size > 2_000_000_000:
        raise RuntimeError(
            "File exceeds the configured 2,000,000,000-byte limit. "
            "Split/re-encode it in a separate, explicitly configured processing step."
        )
    return asyncio.run(_upload(path, caption))
