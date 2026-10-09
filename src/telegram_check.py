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


async def verify_pyrogram(
    api_id: int,
    api_hash: str,
    token: str,
    target: str,
    expected_chat_id: int,
    peer_source: str = "",
) -> bool:
    """Verify this fresh bot-authorized MTProto session can resolve the private channel."""
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

            # MTProto needs a channel access_hash, not just the Bot API's numeric ID.
            # A private invite link may allow Pyrogram to fetch/cache that peer.
            candidates = []
            if peer_source:
                candidates.append(("PYROGRAM_PEER_SOURCE", peer_source))
            candidates.append(("TELEGRAM_TARGET", target))

            for source_name, source_value in candidates:
                try:
                    chat = await app.get_chat(source_value)
                    if int(chat.id) != expected_chat_id:
                        print(f"INFO {source_name} resolved ID {chat.id}, expected {expected_chat_id}; skipping.")
                        continue
                    await app.resolve_peer(chat.id)
                    print(
                        f"PASS Pyrogram peer resolved via {source_name}: "
                        f"title={getattr(chat, 'title', None)!r}, type={chat.type}, id={chat.id}"
                    )
                    print("PASS Pyrogram resolved the channel InputPeer/access hash.")
                    return True
                except Exception as exc:
                    print(f"INFO Pyrogram lookup via {source_name} failed: {type(exc).__name__}: {exc}")

            print(
                "FAIL Pyrogram cannot resolve the private channel from this fresh bot session. "
                "Set GitHub secret PYROGRAM_PEER_SOURCE to a valid private invite link for this "
                "channel (bot must already be a member/admin), or to its public @username. "
                "It must resolve to the same channel as TELEGRAM_TARGET."
            )
            return False
    except Exception as exc:
        print(f"FAIL Pyrogram bot authorization: {type(exc).__name__}: {exc}")
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
                "RESULT: FAIL — Bot API credentials/permissions are valid, but Pyrogram upload "
                "readiness is not verified. Configure PYROGRAM_PEER_SOURCE and rerun this test."
            )
            return 1
        print("RESULT: PASS — Bot API permissions and Pyrogram private-channel peer resolution succeeded.")
        return 0
    except Exception as exc:
        print(f"FAIL Telegram verification: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
