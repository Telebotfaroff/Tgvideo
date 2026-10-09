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
    """Verify the bot can resolve the destination for MTProto uploads."""
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

            # A public username is the best peer source. Telegram's invite-check
            # method is user-only, so a private invite link cannot be resolved
            # by a bot via get_chat(). For bots, Telegram supports access_hash=0
            # when the channel ID is known but no access hash has been cached.
            if peer_source and not (
                "t.me/+" in peer_source or "t.me/joinchat/" in peer_source
                or "telegram.me/+" in peer_source or "telegram.me/joinchat/" in peer_source
            ):
                try:
                    chat = await app.get_chat(peer_source)
                    if int(chat.id) != expected_chat_id:
                        print(
                            f"FAIL PYROGRAM_PEER_SOURCE resolved ID {chat.id}, "
                            f"expected {expected_chat_id}."
                        )
                        return False
                    await app.resolve_peer(chat.id)
                    print(
                        f"PASS Pyrogram peer resolved via PYROGRAM_PEER_SOURCE: "
                        f"title={getattr(chat, 'title', None)!r}, type={chat.type}, id={chat.id}"
                    )
                    return True
                except Exception as exc:
                    print(f"INFO Public peer-source lookup failed: {type(exc).__name__}: {exc}")

            # Private Bot API channel IDs have the form -100<channel_id>.
            # Telegram's MTProto peer database explicitly permits zero access
            # hashes for bots when no access hash is available.
            target_text = str(target).strip()
            if target_text.startswith("-100") and target_text[1:].isdigit():
                channel_id = int(target_text[4:])
                await app.storage.update_peers(
                    [(expected_chat_id, 0, "channel", None, None)]
                )
                peer = await app.resolve_peer(expected_chat_id)
                if getattr(peer, "channel_id", None) != channel_id:
                    print("FAIL Pyrogram resolved a peer that does not match TELEGRAM_TARGET.")
                    return False
                print(
                    f"PASS Pyrogram private-channel peer seeded for bot authorization: "
                    f"channel_id={channel_id}, access_hash=0"
                )
                return True

            # Public usernames and non-channel destinations can still resolve
            # directly from TELEGRAM_TARGET.
            try:
                peer = await app.resolve_peer(int(target_text) if target_text.lstrip("-").isdigit() else target_text)
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
                "RESULT: FAIL — Bot API credentials/permissions are valid, but Pyrogram "
                "could not resolve the destination peer."
            )
            return 1
        print("RESULT: PASS — Bot API permissions and Pyrogram destination peer resolution succeeded.")
        return 0
    except Exception as exc:
        print(f"FAIL Telegram verification: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
