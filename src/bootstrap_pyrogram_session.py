"""Create a persistent bot MTProto session and channel access hash.

Run this locally while the destination channel has a public @username.
The output contains credentials: never paste it into chat or commit it.
"""
from __future__ import annotations

import asyncio
import json
import re
from getpass import getpass

from pyrogram import Client


def prompt(name: str, secret: bool = False) -> str:
    value = (getpass(f"{name}: ") if secret else input(f"{name}: ")).strip()
    if not value:
        raise SystemExit(f"{name} is required.")
    return value


def normalize_username(value: str) -> str:
    value = value.strip()
    if value.startswith("https://t.me/"):
        value = value.removeprefix("https://t.me/").split("?", 1)[0].strip("/")
    if value.startswith("@"):
        value = value[1:]
    if not re.fullmatch(r"[A-Za-z0-9_]{5,}", value):
        raise SystemExit(
            "PYROGRAM_PEER_SOURCE must be a public @username or https://t.me/username URL; "
            "private invite links cannot be resolved by a bot session."
        )
    return "@" + value


async def main() -> None:
    api_id = int(prompt("API_ID"))
    api_hash = prompt("API_HASH", secret=True)
    bot_token = prompt("BOT_TOKEN", secret=True)
    target = prompt("TELEGRAM_TARGET (numeric -100... channel ID)")
    peer_source = normalize_username(prompt("Public channel @username (temporary if needed)"))

    if not target.startswith("-100") or not target[1:].isdigit():
        raise SystemExit("TELEGRAM_TARGET must be a numeric -100... channel ID.")

    app = Client(
        "tgvideo-bootstrap",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,
        in_memory=True,
    )
    async with app:
        me = await app.get_me()
        if not me.is_bot:
            raise SystemExit("The client did not authenticate as a bot.")

        chat = await app.get_chat(peer_source)
        if int(chat.id) != int(target):
            raise SystemExit(
                f"Username resolved to chat ID {chat.id}, but TELEGRAM_TARGET is {target}. "
                "No credentials were exported."
            )

        peer = await app.resolve_peer(chat.id)
        access_hash = getattr(peer, "access_hash", None)
        if not isinstance(access_hash, int) or access_hash == 0:
            raise SystemExit("Telegram did not return a real non-zero channel access hash.")

        session_string = await app.export_session_string()
        result = {
            "PYROGRAM_SESSION_STRING": session_string,
            "PYROGRAM_CHANNEL_ACCESS_HASH": str(access_hash),
            "BOT_ID": str(me.id),
            "CHANNEL_ID": str(chat.id),
        }
        print("\nSAVE THESE VALUES AS GITHUB ACTIONS SECRETS. KEEP THEM PRIVATE:")
        print(json.dumps(result, indent=2))
        print(
            "\nThis is a bot-authorized session, not a personal-user session. "
            "The session string and access hash must be used together."
        )


if __name__ == "__main__":
    asyncio.run(main())
