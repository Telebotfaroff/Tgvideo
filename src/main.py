from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "database"
LOG_DIR = ROOT / "logs"
MANIFEST_DIR = DB_DIR / "channels"
STATE_DIR = DB_DIR / "state"
LOG_DIR.mkdir(parents=True, exist_ok=True)
MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)


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
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def channel_key(url: str) -> str:
    parsed = urlparse(url)
    slug = parsed.path.strip("/").split("/")[-1] or parsed.netloc
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", slug).strip("-").lower()
    return slug[:100] or "channel"


def validate_channel_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("CHANNEL_URL must be an HTTPS URL")


def discover_channel_entries(channel_url: str) -> list[dict]:
    """Source adapter placeholder.

    Implement this for the target website after confirming its current page
    structure and supported access method. It must return entries with stable
    IDs and canonical page URLs. Never return guessed or fabricated entries.
    """
    raise NotImplementedError(
        "The source-specific channel adapter is not implemented yet. "
        "Implement discover_channel_entries() before running scan/process."
    )


def manifest_path(key: str) -> Path:
    return MANIFEST_DIR / f"{key}.json"


def scan(channel_url: str, key: str, dry_run: bool) -> dict:
    path = manifest_path(key)
    existing = read_json(path, {
        "channel_key": key,
        "source_url": channel_url,
        "created_at": now(),
        "updated_at": now(),
        "total_discovered": 0,
        "videos": [],
    })
    discovered = discover_channel_entries(channel_url)
    known = {item["source_id"]: item for item in existing["videos"] if item.get("source_id")}
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
        existing["videos"].append(record)
        known[source_id] = record
        added += 1
    existing["source_url"] = channel_url
    existing["updated_at"] = now()
    existing["total_discovered"] = len(existing["videos"])
    counts = {status: sum(1 for v in existing["videos"] if v.get("status") == status)
              for status in ("pending", "downloading", "downloaded", "uploading", "completed", "failed")}
    log(f"Discovered {len(discovered)} entries; added {added}; manifest total {len(existing['videos'])}; states={counts}")
    if not dry_run:
        atomic_json(path, existing)
    return existing


def process_batch(channel_url: str, key: str, operation: str, batch_size: int, dry_run: bool) -> None:
    path = manifest_path(key)
    if not path.exists():
        raise RuntimeError("No channel manifest exists. Run operation=scan first.")
    manifest = read_json(path, {})
    statuses = {
        "process": {"pending"},
        "resume": {"pending", "downloaded", "uploading"},
        "retry_failed": {"failed"},
    }
    allowed = statuses.get(operation, set())
    queue = [v for v in manifest.get("videos", []) if v.get("status") in allowed][:batch_size]
    log(f"Queue size for operation={operation}: {len(queue)} (batch limit={batch_size})")
    if dry_run:
        for item in queue:
            log(f"DRY RUN: would process {item.get('source_id')} — {item.get('title', '')}")
        return
    if queue:
        raise NotImplementedError(
            "Download/upload adapters are not implemented yet. The workflow "
            "currently supports manifest scaffolding only; no video has been "
            "downloaded or uploaded."
        )
    log("No eligible entries in this batch.")


def main() -> int:
    channel_url = os.environ.get("CHANNEL_URL", "").strip()
    operation = os.environ.get("OPERATION", "scan").strip()
    dry_run = os.environ.get("DRY_RUN", "true").lower() in {"1", "true", "yes"}
    try:
        batch_size = int(os.environ.get("BATCH_SIZE", "10"))
    except ValueError:
        raise ValueError("BATCH_SIZE must be an integer")
    if not 1 <= batch_size <= 100:
        raise ValueError("BATCH_SIZE must be between 1 and 100")
    if operation not in {"scan", "process", "resume", "retry_failed"}:
        raise ValueError(f"Unsupported operation: {operation}")
    validate_channel_url(channel_url)
    key = channel_key(channel_url)
    log(f"Starting operation={operation}, channel={key}, dry_run={dry_run}")
    if operation == "scan":
        scan(channel_url, key, dry_run)
    else:
        process_batch(channel_url, key, operation, batch_size, dry_run)
    log("Run finished.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"ERROR: {type(exc).__name__}: {exc}")
        raise
