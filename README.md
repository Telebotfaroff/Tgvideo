# Tgvideo

Workflow-first channel video processing with GitHub Actions.

## Processing model

1. **Scan** a channel URL and persist a manifest of discovered entries.
2. **Batch** pending entries using the configured batch size.
3. **Process one item at a time**: download, validate, upload to Telegram, checkpoint, and remove temporary files.
4. **Resume** from persisted state on a later run.
5. **Deduplicate** by stable source ID, with URL normalization as a fallback.

The repository stores metadata and state only; video files belong in temporary runner storage and must be removed after successful processing.

## Current implementation status

This repository starts with the workflow/orchestration foundation. A source adapter for the target website must be implemented and tested against its current page structure before production use. The pipeline must not treat a channel page as a direct video URL.

## GitHub Actions

Open **Actions → Tgvideo pipeline → Run workflow**.

Inputs:
- `channel_url`: channel/studio listing URL.
- `operation`: `scan`, `process`, `resume`, or `retry_failed`.
- `batch_size`: maximum entries processed in this run.
- `dry_run`: discover and validate work without downloading or uploading.

## Required repository secrets

- `API_ID`: Telegram API ID.
- `API_HASH`: Telegram API hash.
- `BOT_TOKEN`: Telegram bot token.
- `TELEGRAM_TARGET`: destination channel ID or username.

Do not commit credentials, session files, downloaded media, or private cookies.

## State and checkpoints

State is stored under `database/`. GitHub Actions concurrency prevents two pipeline runs from mutating the same state simultaneously. The workflow commits state changes after the scan and processing batch.

A crash can occur after Telegram accepts a file but before the local checkpoint is committed. Such entries must be reconciled before retrying; no local-only design can promise exactly-once delivery across that failure window.

## Development

Python 3.11+ is recommended. Install dependencies from `requirements.txt`.

The source adapter should return stable IDs, title, canonical page URL, and any supported downloadable media URL. Keep source-specific extraction isolated from queue, checkpoint, upload, and cleanup logic.
