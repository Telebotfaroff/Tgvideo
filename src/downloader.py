from __future__ import annotations

import subprocess
from pathlib import Path


def download_video(page_url: str, output_dir: Path) -> Path:
    """Download one video page using yt-dlp; returns the resulting media file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    template = str(output_dir / "%(id)s.%(ext)s")
    command = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "--retries", "3",
        "--fragment-retries", "3",
        "--socket-timeout", "30",
        "--restrict-filenames",
        "--output", template,
        "--print", "after_move:filepath",
        page_url,
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    candidates = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]
    for candidate in reversed(candidates):
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    # Fallback for extractors that do not emit after_move:filepath.
    media = [
        p for p in output_dir.iterdir()
        if p.is_file() and p.suffix.lower() not in {".part", ".ytdl", ".json", ".description"}
    ]
    if not media:
        detail = (result.stderr or result.stdout or "yt-dlp produced no output file")[-2000:]
        raise RuntimeError(f"Download completed without a discoverable media file: {detail}")
    return max(media, key=lambda p: p.stat().st_mtime)
