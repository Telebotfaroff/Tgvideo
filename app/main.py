"""Process a manifest of direct media URLs and upload them to Telegram.

Only add media you own or are authorized to redistribute.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.errors import FloodWait

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("tgvideo-uploader")
USER_AGENT = "TgvideoAutoUploader/1.0"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, path)


def load_manifest(path: Path) -> list[dict]:
    data = read_json(path, {"items": []})
    if not isinstance(data.get("items"), list):
        raise ValueError("Manifest must contain an 'items' array")
    items = []
    seen = set()
    for index, item in enumerate(data["items"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Manifest item #{index} must be an object")
        item_id = str(item.get("id", "")).strip()
        url = str(item.get("url", "")).strip()
        parsed = urlparse(url)
        if not item_id:
            raise ValueError(f"Manifest item #{index} is missing 'id'")
        if item_id in seen:
            raise ValueError(f"Duplicate manifest ID: {item_id}")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Item {item_id!r} needs a valid HTTP(S) URL")
        seen.add(item_id)
        items.append({**item, "id": item_id, "url": url})
    return items


def safe_filename(title: str, item_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("._")
    return (value or item_id or "video")[:100]


def download_file(url: str, destination: Path, referer: str | None = None) -> None:
    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer
    with requests.get(url, headers=headers, stream=True, timeout=(30, 120)) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("Download produced an empty file")


def probe_duration(path: Path) -> int | None:
    try:
        output = subprocess.check_output(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return max(0, int(float(output)))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def upload_one(client: Client, target: str, item: dict, checkpoint: dict) -> None:
    item_id = item["id"]
    title = str(item.get("title") or item_id)
    checkpoint["items"][item_id] = {
        **checkpoint["items"].get(item_id, {}),
        "status": "processing",
        "title": title,
        "attempts": int(checkpoint["items"].get(item_id, {}).get("attempts", 0)) + 1,
        "updated_at": now(),
    }
    write_json_atomic(ROOT / "database/processed.json", checkpoint)

    with tempfile.TemporaryDirectory(prefix="tgvideo-") as temp:
        media_path = Path(temp) / (safe_filename(title, item_id) + ".mp4")
        download_file(item["url"], media_path, item.get("source_url"))
        thumb_path = None
        thumb_url = str(item.get("thumbnail") or "").strip()
        if thumb_url:
            try:
                thumb_path = Path(temp) / "thumbnail.jpg"
                download_file(thumb_url, thumb_path, item.get("source_url"))
                if thumb_path.stat().st_size > 200_000:
                    thumb_path.unlink(missing_ok=True)
                    thumb_path = None
            except Exception as exc:
                LOG.warning("Thumbnail unavailable for %s: %s", item_id, exc)
                thumb_path = None

        while True:
            try:
                message = client.send_video(
                    chat_id=target,
                    video=str(media_path),
                    caption=title[:1024],
                    thumb=str(thumb_path) if thumb_path else None,
                    duration=probe_duration(media_path),
                    supports_streaming=True,
                )
                break
            except FloodWait as exc:
                wait = max(1, int(getattr(exc, "value", 1)))
                LOG.warning("Telegram FloodWait: sleeping %s seconds", wait)
                time.sleep(wait)

    checkpoint["items"][item_id] = {
        **checkpoint["items"].get(item_id, {}),
        "status": "completed",
        "title": title,
        "message_id": str(message.id),
        "completed_at": now(),
        "updated_at": now(),
    }
    write_json_atomic(ROOT / "database/processed.json", checkpoint)
    LOG.info("Uploaded %s as Telegram message %s", item_id, message.id)


def main() -> int:
    load_dotenv(ROOT / ".env")
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    manifest_path = Path(os.getenv("MANIFEST_PATH", "database/authorized_media.json"))
    checkpoint_path = Path(os.getenv("CHECKPOINT_PATH", "database/processed.json"))
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    if not checkpoint_path.is_absolute():
        checkpoint_path = ROOT / checkpoint_path

    target = (os.getenv("TELEGRAM_TARGET") or "").strip()
    required = ["API_ID", "API_HASH", "BOT_TOKEN"]
    missing = [name for name in required if not os.getenv(name)]
    if not target:
        missing.append("TELEGRAM_TARGET")
    if missing:
        LOG.error("Missing environment variables: %s", ", ".join(missing))
        return 2

    try:
        items = load_manifest(manifest_path)
        checkpoint = read_json(checkpoint_path, {"schema_version": 1, "items": {}})
        if not isinstance(checkpoint.get("items"), dict):
            raise ValueError("Checkpoint must contain an 'items' object")
    except Exception:
        LOG.exception("Could not load manifest/checkpoint")
        return 2

    max_attempts = max(1, int(os.getenv("MAX_ITEM_ATTEMPTS", "5")))
    failures = 0
    client = Client(
        "tgvideo_auto_uploader",
        api_id=int(os.environ["API_ID"]),
        api_hash=os.environ["API_HASH"],
        bot_token=os.environ["BOT_TOKEN"],
        in_memory=True,
    )
    with client:
        for item in items:
            item_id = item["id"]
            previous = checkpoint["items"].get(item_id, {})
            if previous.get("status") == "completed":
                LOG.info("Skipping already uploaded item %s", item_id)
                continue
            if int(previous.get("attempts", 0)) >= max_attempts:
                LOG.warning("Skipping %s: maximum attempts reached", item_id)
                failures += 1
                continue
            try:
                upload_one(client, target, item, checkpoint)
            except Exception as exc:
                failures += 1
                checkpoint["items"][item_id] = {
                    **checkpoint["items"].get(item_id, {}),
                    "status": "failed",
                    "title": str(item.get("title") or item_id),
                    "error": f"{type(exc).__name__}: {exc}"[:1500],
                    "updated_at": now(),
                }
                write_json_atomic(checkpoint_path, checkpoint)
                LOG.exception("Failed item %s", item_id)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
