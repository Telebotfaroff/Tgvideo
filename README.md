# Tgvideo

Workflow-first channel inventory and batch-processing pipeline powered by GitHub Actions.

## Current behavior

- Accepts an HTTPS Javtiful channel URL such as `https://javtiful.com/channel/s1-no1-style`.
- Scans paginated channel listings and builds a persistent JSON manifest.
- Uses stable source IDs to avoid adding the same catalogue entry twice.
- Processes a configurable batch (default 10) one item at a time.
- Downloads each item with yt-dlp, uploads it to a Telegram destination with Pyrogram, checkpoints state, and deletes temporary media.
- Records errors and allows failed items to be retried.
- Preserves ambiguous `uploading` states for manual reconciliation rather than automatically risking duplicate Telegram uploads.
- Commits state changes during a run so a runner timeout does not discard the entire batch's progress.

## Workflow

Open **Actions → Tgvideo pipeline → Run workflow**.

Inputs:
- `channel_url`: a Javtiful channel page.
- `operation`: `scan`, `process`, `resume`, or `retry_failed`.
- `batch_size`: number of entries to process, from 1 to 100.
- `dry_run`: when enabled, process operations only preview the queue. A `scan` still saves the inventory.

Recommended first run: choose `scan` and leave `dry_run` enabled. Check the manifest and logs before processing. For a real upload run, configure the required secrets and set `dry_run` to false.

## GitHub Secrets

Configure these under **Settings → Secrets and variables → Actions**:
- `API_ID`: Telegram API ID (integer).
- `API_HASH`: Telegram API hash.
- `BOT_TOKEN`: Telegram bot token.
- `TELEGRAM_TARGET`: destination channel ID or username. The bot must have permission to post there.

Never commit credentials, Telegram session files, cookies, or media files.

## Repository state

Channel manifests are saved under `database/channels/<channel-slug>.json`. They store IDs, titles, page URLs, status, retry count, and Telegram message IDs—not video bytes.

Statuses include `pending`, `downloading`, `downloaded`, `uploading`, `completed`, and `failed`. If a run dies while status is `uploading`, inspect the destination channel before manually changing the state; Telegram may have accepted the file even if the runner did not receive the response.

## Limits and source adapter

The scanner uses HTML selectors for the currently known Javtiful catalogue structure. If the site changes its markup or returns a challenge page, the scanner intentionally fails rather than silently saving an incomplete inventory. Verify the first scan's count against the channel page before processing a large queue.

The downloader depends on yt-dlp having a supported extractor for the individual page. Some pages may not expose a downloadable media source to yt-dlp; those items will be marked failed and can be retried after the adapter is updated.

The uploader rejects files larger than 2,000,000,000 bytes. Large-file splitting is not enabled yet; it should be added only with a tested ffmpeg split/Telegram delivery strategy.

## Tests

Run locally:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m compileall -q src
```
