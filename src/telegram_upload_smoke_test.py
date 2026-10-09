"""Perform a real, tiny Telegram upload to verify the configured MTProto peer.

Run only when you intend to post a test video to TELEGRAM_TARGET.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from src.telegram_uploader import upload_video


def main() -> int:
    required = ("API_ID", "API_HASH", "BOT_TOKEN", "TELEGRAM_TARGET")
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise SystemExit("Missing required secrets/environment values: " + ", ".join(missing))

    run_id = os.environ.get("GITHUB_RUN_ID", "manual")
    caption = f"Tgvideo upload smoke test · run {run_id}"

    with tempfile.TemporaryDirectory(prefix="tgvideo-smoke-") as tmp:
        video = Path(tmp) / "tgvideo-smoke-test.mp4"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=320x240:r=15:d=2",
                "-frames:v", "30", "-an", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(video),
            ],
            check=True,
        )
        if not video.is_file() or video.stat().st_size == 0:
            raise RuntimeError("FFmpeg did not produce the smoke-test video.")

        message_id = upload_video(video, caption)
        print(f"PASS: real Telegram upload completed; message_id={message_id}")
        print("Check TELEGRAM_TARGET for the 2-second 'Tgvideo upload smoke test' video.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
