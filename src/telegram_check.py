from __future__ import annotations

import asyncio
import os
import sys

import requests
from pyrogram import Client
from pyrogram.enums import ChatMemberStatus, ChatType


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required GitHub Actions secret/variable: {name}")
    return value


def bot_api(method: str, token: str, **params):
    response = requests.get(
        f"https://api.telegram.org/bot{token}/{method}",
        params=params,
        timeout=20,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Telegram Bot API {method} returned non-JSON HTTP {response.status_code}") from exc
    if not payload.get("ok"):
        description = payload.get("description", "Unknown Bot API error")
        raise RuntimeError(f"Bot API {method} failed: {description}")
    return payload["result"]


def verify_bot_api(token: str, target: str) -> dict:
    me = bot_api("getMe", token)
    print(f"PASS Bot API authentication: @{me.get('username', 'no_username')} (id={me['id']})")

    chat = bot_api("getChat", token, chat_id=target)
    print(
        f"PASS Bot API destination resolved: title={chat.get('title', chat.get('username', ''))!r}, "
        f"type={chat.get('type')}, id={chat.get('id')}"
    )
    if chat.get("type") not in ("channel", "supergroup"):
        raise RuntimeError("Destination must be a Telegram channel or supergroup.")

    member = bot_api("getChatMember", token, chat_id=chat["id"], user_id=me["id"])
    status = member.get("status")
    print(f"INFO Bot API membership status: {status}")

    if chat["type"] == "channel":
        if status not in ("administrator", "creator"):
            raise RuntimeError("Bot is not an administrator of the destination channel.")
        if status == "administrator" and not member.get("can_post_messages", False):
            raise RuntimeError("Bot administrator is missing the can_post_messages permission.")
    else:
        if status not in ("administrator", "creator", "member"):
            raise RuntimeError("Bot is not a member of the destination supergroup.")
        if status == "administrator" and member.get("can_send_messages") is False:
            raise RuntimeError("Bot administrator cannot send messages in this supergroup.")

    print("PASS Bot API confirms destination membership and posting permissions.")
    return chat


async def verify_pyrogram(api_id: int, api_hash: str, token: str, target: str, expected_chat_id: int) -> None:
    app = Client(
        name="telegram-verification",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=token,
        in_memory=True,
    )
    async with app:
        me = await app.get_me()
        print(f"PASS Pyrogram bot authentication: @{me.username or 'no_username'} (id={me.id})")

        # An ephemeral Pyrogram session has an empty peer cache at startup.
        # Populate it from dialogs before resolving a numeric -100... ID.
        try:
            async for dialog in app.get_dialogs():
                if dialog.chat.id == expected_chat_id:
                    print("PASS Pyrogram found the destination in the bot's dialogs.")
                    break
            else:
                print("INFO Destination not found in Pyrogram dialogs; trying direct resolution.")
        except Exception as exc:
            print(f"INFO Could not enumerate Pyrogram dialogs ({type(exc).__name__}); trying direct resolution.")

        try:
            chat = await app.get_chat(target)
        except Exception as exc:
            message = str(exc)
            if "PEER_ID_INVALID" in message or "PeerIdInvalid" in type(exc).__name__:
                raise RuntimeError(
                    "Bot API verified the channel and permissions, but Pyrogram cannot resolve its peer "
                    "from this fresh in-memory session. For a public channel, set TELEGRAM_TARGET to "
                    "@channelusername. For a private channel, ensure the bot is a member/admin and use "
                    "a Pyrogram session/peer cache that has encountered the channel."
                ) from exc
            raise

        if chat.id != expected_chat_id:
            raise RuntimeError(f"Bot API and Pyrogram resolved different destinations: {expected_chat_id} vs {chat.id}")
        if chat.type not in (ChatType.CHANNEL, ChatType.SUPERGROUP):
            raise RuntimeError("Pyrogram resolved a destination that is not a channel or supergroup.")
        print(f"PASS Pyrogram destination resolved: type={chat.type}, id={chat.id}")
        print("PASS Telegram verification complete. No message was sent.")


def main() -> int:
    try:
        api_id = int(required("API_ID"))
        api_hash = required("API_HASH")
        token = required("BOT_TOKEN")
        target = required("TELEGRAM_TARGET")

        chat = verify_bot_api(token, target)
        asyncio.run(verify_pyrogram(api_id, api_hash, token, target, int(chat["id"])))
        return 0
    except Exception as exc:
        print(f"FAIL Telegram verification: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
