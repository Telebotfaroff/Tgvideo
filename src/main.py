from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from src.downloader import download_video
from src.scanner import discover_channel_entries
from src.telegram_uploader import upload_video

ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "database"
LOG_DIR = ROOT / "logs"
MANIFEST_DIR = DB_DIR / "channels"
DOWNLOAD_DIR = ROOT / "tmp" / "downloads"
for directory in (LOG_DIR, MANIFEST_DIR, DOWNLOAD_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    line = f"[{now()}] {message}"
    print(line, flush=True)
    with (LOG_DIR / "pipeline.log").open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Refusing to overwrite invalid JSON: {path}") from exc


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def channel_key(url: str) -> str:
    parsed = urlparse(url)
    slug = parsed.path.strip("/").split("/")[-1] or parsed.netloc
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", slug).strip("-").lower()
    return slug[:100] or "channel"


def validate_channel_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("CHANNEL_URL must be a valid HTTPS URL")


def manifest_path(key: str) -> Path:
    return MANIFEST_DIR / f"{key}.json"


def persist_checkpoint(path: Path, manifest: dict, *, push: bool = False) -> None:
    manifest["updated_at"] = now()
    manifest["total_discovered"] = len(manifest.get("videos", []))
    atomic_json(path, manifest)
    # In Actions, push the checkpoint after each item's terminal state so a
    # runner timeout does not lose the entire batch's progress.
    if push and os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=ROOT, check=True)
        subprocess.run([
            "git", "config", "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
        ], cwd=ROOT, check=True)
        subprocess.run(["git", "add", str(path.relative_to(ROOT))], cwd=ROOT, check=True)
        staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
        if staged.returncode == 1:
            subprocess.run(["git", "commit", "-m", "chore: checkpoint channel processing"], cwd=ROOT, check=True)
            subprocess.run(["git", "push"], cwd=ROOT, check=True)
        elif staged.returncode > 1:
            raise RuntimeError("Could not inspect staged checkpoint changes.")


def scan(channel_url: str, key: str) -> dict:
    path = manifest_path(key)
    existing = read_json(path, {
        "schema_version": 1,
        "channel_key": key,
        "source_url": channel_url,
        "created_at": now(),
        "updated_at": now(),
        "total_discovered": 0,
        "videos": [],
    })
    discovered = discover_channel_entries(channel_url)
    known = {str(item["source_id"]): item for item in existing.get("videos", []) if item.get("source_id")}
    added = 0
    for item in discovered:
        source_id = str(item.get("source_id", "")).strip()
        page_url = str(item.get("page_url", "")).strip()
        if not source_id or not page_url:
            log("Skipping source entry without stable source_id or page_url")
            continue
        if source_id in known:
            known[source_id].update({
                "title": item.get("title") or known[source_id].get("title", ""),
                "page_url": page_url,
                "last_seen_at": now(),
            })
            continue
        record = {
            "source_id": source_id,
            "title": item.get("title", ""),
            "page_url": page_url,
            "status": "pending",
            "attempts": 0,
            "telegram_message_id": None,
            "last_error": None,
            "discovered_at": now(),
            "last_seen_at": now(),
        }
        existing.setdefault("videos", []).append(record)
        known[source_id] = record
        added += 1
    existing["source_url"] = channel_url
    existing["last_scan_at"] = now()
    existing["total_discovered"] = len(existing["videos"])
    counts = {
        status: sum(1 for video in existing["videos"] if video.get("status") == status)
        for status in ("pending", "downloading", "downloaded", "uploading", "completed", "failed")
    }
    log(
        f"Scan complete: pages are enumerated by scanner; found={len(discovered)}, "
        f"new={added}, manifest_total={len(existing['videos'])}, states={counts}"
    )
    # A scan always saves its inventory, including when dry_run=true; dry_run
    # only disables download and Telegram upload.
    persist_checkpoint(manifest_path(key), existing, push=True)
    return existing


def _select_queue(manifest: dict, operation: str, batch_size: int) -> list[dict]:
    statuses = {
        "process": {"pending"},
        "resume": {"pending", "downloading", "downloaded"},
        "retry_failed": {"failed"},
    }
    allowed = statuses.get(operation, set())
    return [v for v in manifest.get("videos", []) if v.get("status") in allowed][:batch_size]


def process_batch(key: str, operation: str, batch_size: int, dry_run: bool) -> None:
    path = manifest_path(key)
    if not path.exists():
        raise RuntimeError("No channel manifest exists. Run operation=scan first.")
    manifest = read_json(path, {})
    queue = _select_queue(manifest, operation, batch_size)
    log(f"Queue size for operation={operation}: {len(queue)} (batch limit={batch_size})")
    if not queue:
        log("No eligible entries in this batch.")
        return

    for video in queue:
        source_id = str(video["source_id"])
        title = str(video.get("title") or source_id)
        page_url = str(video["page_url"])
        if dry_run:
            log(f"DRY RUN: would download/upload {source_id} — {title}")
            continue

        media_path: Path | None = None
        try:
            video["attempts"] = int(video.get("attempts", 0)) + 1
            video["status"] = "downloading"
            video["last_error"] = None
            persist_checkpoint(path, manifest, push=True)

            media_path = download_video(page_url, DOWNLOAD_DIR)
            if not media_path.is_file() or media_path.stat().st_size < 1:
                raise RuntimeError("Downloader returned an empty or missing file.")

            video["status"] = "downloaded"
            video["downloaded_bytes"] = media_path.stat().st_size
            persist_checkpoint(path, manifest, push=True)

            # Mark uploading before the network call. If the runner dies in the
            # upload/commit window, do not auto-retry this uncertain state.
            video["status"] = "uploading"
            video["upload_started_at"] = now()
            persist_checkpoint(path, manifest, push=True)
            message_id = upload_video(media_path, title)

            video["telegram_message_id"] = message_id
            video["uploaded_at"] = now()
            video["status"] = "completed"
            video["last_error"] = None
            persist_checkpoint(path, manifest, push=True)
            log(f"Completed {source_id}; Telegram message_id={message_id}")

        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"[:1500]
            # An invalid bot token fails during Telegram authorization, before
            # send_video is attempted. It is safe to mark this item failed so
            # retry_failed can process it after BOT_TOKEN is corrected.
            definite_auth_failure = (
                "ACCESS_TOKEN_INVALID" in error_text
                or "auth.ImportBotAuthorization" in error_text
            )
            # Other failures after entering 'uploading' remain ambiguous: the
            # request may have reached Telegram, so avoid automatic duplicates.
            if video.get("status") != "uploading" or definite_auth_failure:
                video["status"] = "failed"
            video["last_error"] = error_text
            video["failed_at"] = now()
            persist_checkpoint(path, manifest, push=True)
            log(f"Failed {source_id}: {video['last_error']}")
        finally:
            if media_path and media_path.exists():
                try:
                    media_path.unlink()
                    log(f"Removed temporary media for {source_id}")
                except OSError as cleanup_error:
                    log(f"WARNING: could not delete {media_path.name}: {cleanup_error}")
            # Remove fragments and sidecar files belonging to this item.
            for candidate in DOWNLOAD_DIR.iterdir():
                if candidate.is_file() and candidate.suffix in {".part", ".ytdl", ".temp"}:
                    try:
                        candidate.unlink()
                    except OSError:
                        pass

    completed = sum(1 for v in manifest["videos"] if v.get("status") == "completed")
    pending = sum(1 for v in manifest["videos"] if v.get("status") == "pending")
    failed = sum(1 for v in manifest["videos"] if v.get("status") == "failed")
    uncertain = sum(1 for v in manifest["videos"] if v.get("status") == "uploading")
    log(f"Batch summary: completed={completed}, pending={pending}, failed={failed}, needs_reconciliation={uncertain}")


def main() -> int:
    channel_url = os.environ.get("CHANNEL_URL", "").strip()
    operation = os.environ.get("OPERATION", "scan").strip()
    dry_run = os.environ.get("DRY_RUN", "true").lower() in {"1", "true", "yes"}
    try:
        batch_size = int(os.environ.get("BATCH_SIZE", "10"))
    except ValueError as exc:
        raise ValueError("BATCH_SIZE must be an integer") from exc
    if not 1 <= batch_size <= 100:
        raise ValueError("BATCH_SIZE must be between 1 and 100")
    if operation not in {"scan", "process", "resume", "retry_failed"}:
        raise ValueError(f"Unsupported operation: {operation}")
    validate_channel_url(channel_url)
    key = channel_key(channel_url)
    log(f"Starting operation={operation}, channel={key}, dry_run={dry_run}")
    if operation == "scan":
        scan(channel_url, key)
    else:
        process_batch(key, operation, batch_size, dry_run)
    log("Run finished.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"ERROR: {type(exc).__name__}: {exc}")
        raise
