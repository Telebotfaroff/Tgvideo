from __future__ import annotations

import asyncio
import os
import sys

from pyrogram import Client
from pyrogram.enums import ChatMemberStatus


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required GitHub Actions secret/variable: {name}")
    return value


async def verify() -> int:
    api_id = int(required("API_ID"))
    api_hash = required("API_HASH")
    bot_token = required("BOT_TOKEN")
    target = required("TELEGRAM_TARGET")

    app = Client(
        name="telegram-verification",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,
        in_memory=True,
    )

    async with app:
        me = await app.get_me()
        print(f"PASS bot authentication: @{me.username or 'no_username'} (id={me.id})")

        chat = await app.get_chat(target)
        print(
            f"PASS destination resolved: title={getattr(chat, 'title', None)!r}, "
            f"type={chat.type}, id={chat.id}"
        )

        if chat.type not in ("channel", "supergroup"):
            print("FAIL destination must be a Telegram channel or supergroup.")
            return 1

        member = await app.get_chat_member(chat.id, me.id)
        status = member.status
        print(f"INFO bot membership status: {status}")

        # Posting to a broadcast channel requires administrator privileges.
        if chat.type == "channel":
            if status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
                print("FAIL bot is not an administrator of the destination channel.")
                return 1
            if status == ChatMemberStatus.ADMINISTRATOR and not getattr(member, "can_post_messages", False):
                print("FAIL bot is an admin but does not have permission to post messages.")
                return 1
        else:
            if status not in (
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER,
                ChatMemberStatus.MEMBER,
            ):
                print("FAIL bot is not a member of the destination supergroup.")
                return 1
            if status == ChatMemberStatus.ADMINISTRATOR and getattr(member, "can_send_messages", True) is False:
                print("FAIL bot admin does not have permission to send messages.")
                return 1

        print("PASS destination membership and posting permissions verified.")
        print("NOTE no message was sent; this test is read-only.")
        return 0


def main() -> int:
    try:
        return asyncio.run(verify())
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        # Keep logs useful without exposing any configured token/secret.
        print(f"FAIL Telegram verification: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
