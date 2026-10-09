from __future__ import annotations

import asyncio
import os
import sys

import requests
from pyrogram import Client


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required GitHub Actions secret/variable: {name}")
    return value


def _is_invite_link(value: str) -> bool:
    value = value.lower()
    return any(marker in value for marker in (
        "t.me/+", "t.me/joinchat/", "telegram.me/+", "telegram.me/joinchat/"
    ))


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


async def verify_pyrogram(
    api_id: int,
    api_hash: str,
    token: str,
    target: str,
    expected_chat_id: int,
    peer_source: str = "",
) -> bool:
    session_string = os.environ.get("PYROGRAM_SESSION_STRING", "").strip()
    access_hash_text = os.environ.get("PYROGRAM_CHANNEL_ACCESS_HASH", "").strip()

    if session_string:
        app = Client(
            "telegram-verification",
            api_id=api_id,
            api_hash=api_hash,
            session_string=session_string,
            in_memory=True,
        )
    else:
        app = Client(
            "telegram-verification",
            api_id=api_id,
            api_hash=api_hash,
            bot_token=token,
            in_memory=True,
        )

    try:
        async with app:
            me = await app.get_me()
            if not me.is_bot:
                print("FAIL PYROGRAM_SESSION_STRING belongs to a user account, not a bot.")
                return False
            print(f"PASS Pyrogram bot authentication: @{me.username or 'no_username'} (id={me.id})")

            # A public username supplies the real peer information. Telegram's
            # private invite check is user-only and cannot be used by bot sessions.
            if peer_source and not _is_invite_link(peer_source):
                try:
                    chat = await app.get_chat(peer_source)
                    if int(chat.id) != expected_chat_id:
                        print(
                            f"FAIL PYROGRAM_PEER_SOURCE resolved ID {chat.id}, "
                            f"expected {expected_chat_id}."
                        )
                        return False
                    peer = await app.resolve_peer(chat.id)
                    if hasattr(peer, "access_hash") and not getattr(peer, "access_hash", 0):
                        print("FAIL Public peer resolution returned no usable channel access hash.")
                        return False
                    print(
                        f"PASS Pyrogram peer resolved via public peer source: "
                        f"title={getattr(chat, 'title', None)!r}, type={chat.type}, id={chat.id}"
                    )
                    return True
                except Exception as exc:
                    print(f"INFO Public peer-source lookup failed: {type(exc).__name__}: {exc}")

            target_text = str(target).strip()
            if target_text.startswith("-100") and target_text[1:].isdigit():
                if not session_string:
                    print(
                        "FAIL Private-channel MTProto upload requires a persistent bot session. "
                        "A fresh bot-token session cannot derive the channel access hash from "
                        "the Bot API numeric ID."
                    )
                    return False
                if not access_hash_text:
                    print("FAIL Missing PYROGRAM_CHANNEL_ACCESS_HASH (real, non-zero channel hash).")
                    return False
                try:
                    access_hash = int(access_hash_text)
                except ValueError:
                    print("FAIL PYROGRAM_CHANNEL_ACCESS_HASH must be an integer.")
                    return False
                if access_hash == 0:
                    print("FAIL PYROGRAM_CHANNEL_ACCESS_HASH must be non-zero; zero hash was rejected by Telegram.")
                    return False

                channel_id = int(target_text[4:])
                await app.storage.update_peers(
                    [(expected_chat_id, access_hash, "channel", None, None)]
                )
                peer = await app.resolve_peer(expected_chat_id)
                if getattr(peer, "channel_id", None) != channel_id:
                    print("FAIL Pyrogram resolved a peer that does not match TELEGRAM_TARGET.")
                    return False
                if getattr(peer, "access_hash", None) != access_hash:
                    print("FAIL Pyrogram did not load the configured channel access hash.")
                    return False
                print(
                    f"PASS Pyrogram loaded private-channel peer for persistent bot session: "
                    f"channel_id={channel_id}, real access hash configured."
                )
                return True

            try:
                peer = await app.resolve_peer(
                    int(target_text) if target_text.lstrip("-").isdigit() else target_text
                )
                print(f"PASS Pyrogram destination peer resolved directly: {peer!r}")
                return True
            except Exception as exc:
                print(f"FAIL Pyrogram direct destination resolution: {type(exc).__name__}: {exc}")
                return False
    except Exception as exc:
        print(f"FAIL Pyrogram bot authorization/peer resolution: {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    try:
        api_id = int(required("API_ID"))
        api_hash = required("API_HASH")
        token = required("BOT_TOKEN")
        target = required("TELEGRAM_TARGET")

        chat = verify_bot_api(token, target)
        peer_source = os.environ.get("PYROGRAM_PEER_SOURCE", "").strip()
        pyrogram_ok = asyncio.run(
            verify_pyrogram(api_id, api_hash, token, target, int(chat["id"]), peer_source)
        )
        if not pyrogram_ok:
            print(
                "RESULT: FAIL — Bot API credentials/permissions are valid, but a usable "
                "MTProto peer was not verified."
            )
            return 1
        print("RESULT: PASS — Bot API permissions and Pyrogram destination peer resolution succeeded.")
        return 0
    except Exception as exc:
        print(f"FAIL Telegram verification: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
