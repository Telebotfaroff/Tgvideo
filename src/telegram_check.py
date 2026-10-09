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


async def verify_pyrogram(api_id: int, api_hash: str, token: str, target: str, expected_chat_id: int) -> bool:
    """Diagnostic only: Bot API verification is authoritative for bot posting access.

    Pyrogram bot sessions cannot use get_dialogs(), and a fresh in-memory
    MTProto session may lack the access hash for a private channel's numeric ID.
    That transport limitation should not invalidate the Bot API permission test.
    """
    app = Client(
        name="telegram-verification",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=token,
        in_memory=True,
    )
    try:
        async with app:
            me = await app.get_me()
            print(f"PASS Pyrogram bot authentication: @{me.username or 'no_username'} (id={me.id})")
            try:
                chat = await app.get_chat(target)
                if chat.id != expected_chat_id:
                    print(
                        f"WARNING Pyrogram resolved a different destination: "
                        f"{chat.id} (Bot API resolved {expected_chat_id})."
                    )
                    return False
                print(f"PASS Pyrogram destination resolved: type={chat.type}, id={chat.id}")
                return True
            except Exception as exc:
                print(
                    "WARNING Pyrogram could not resolve the destination in this fresh bot session "
                    f"({type(exc).__name__}: {exc}). The Bot API independently verified the "
                    "channel and posting permissions. MTProto upload readiness is not confirmed."
                )
                return False
    except Exception as exc:
        print(
            "WARNING Pyrogram diagnostic could not complete "
            f"({type(exc).__name__}: {exc}). Bot API verification remains authoritative "
            "for the bot token and destination permissions."
        )
        return False


def main() -> int:
    try:
        api_id = int(required("API_ID"))
        api_hash = required("API_HASH")
        token = required("BOT_TOKEN")
        target = required("TELEGRAM_TARGET")

        chat = verify_bot_api(token, target)
        pyrogram_ok = asyncio.run(verify_pyrogram(api_id, api_hash, token, target, int(chat["id"])))
        if not pyrogram_ok:
            print(
                "RESULT: PASS — Bot API authentication, channel access, membership, and posting "
                "permissions are valid. WARNING — Pyrogram MTProto peer resolution needs separate "
                "attention before using the Pyrogram uploader."
            )
        else:
            print("RESULT: PASS — Bot API and Pyrogram destination checks succeeded.")
        return 0
    except Exception as exc:
        print(f"FAIL Telegram verification: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
