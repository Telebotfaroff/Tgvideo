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
- `PYROGRAM_PEER_SOURCE` (optional): a public `@username` for the same destination. Private invite links cannot be resolved by a bot session.
- `PYROGRAM_SESSION_STRING` (required for private numeric channel uploads): a persistent Pyrogram session string created while logged in as this bot.
- `PYROGRAM_CHANNEL_ACCESS_HASH` (required with the session string for private numeric channel uploads): the real non-zero access hash for the destination channel, obtained using the same bot session.

### Setting up a private channel for MTProto uploads

Telegram's Bot API can confirm that a bot is an admin, but it does not expose the MTProto channel access hash. The previous zero-hash workaround was rejected by Telegram with `CHANNEL_INVALID`. A numeric `-100...` ID alone is not enough for a fresh MTProto session. See the official [Telegram peer database documentation](https://core.telegram.org/api/peers) and [Pyrogram chat ID documentation](https://docs.pyrogram.org/topics/advanced-usage).

To create a persistent **bot-authorized** session and retrieve the real access hash:

1. Temporarily assign the destination channel a public `@username`. **While it has a username, the channel is public and its contents may be visible to anyone. Do not do this if that exposure is unacceptable.**
2. On a trusted device with Python and the repository dependencies, run `python -m pip install -r requirements.txt`, then `python -m src.bootstrap_pyrogram_session`.
3. Enter `API_ID`, `API_HASH`, `BOT_TOKEN`, the numeric `TELEGRAM_TARGET`, and the temporary public `@username`. The script verifies the username matches the destination and prints `PYROGRAM_SESSION_STRING` and `PYROGRAM_CHANNEL_ACCESS_HASH`.
4. Restore the channel's private setting if desired. Add both printed values as GitHub Actions secrets with those exact names.
5. Keep the session string private. It is an authentication credential. Use the session string and access hash together; the hash is tied to the bot's MTProto authorization session.
6. Run **Actions → Verify Telegram Bot and Channel**. Peer-resolution PASS is not a substitute for a real upload test.

If you cannot temporarily make the channel public, do not guess an access hash or use zero. The bot must first receive a valid MTProto channel constructor through an authorized update or another supported resolution route. The standard hosted Bot API is an alternative only for files within its much smaller upload limit.

### Test a real upload

After adding the required secrets, open **Actions → Test Telegram Upload → Run workflow**. This manual workflow first checks Bot API permissions and MTProto peer resolution, then uploads a generated two-second test video to `TELEGRAM_TARGET`. It prints the Telegram message ID on success. This is the important end-to-end test: a peer-resolution PASS alone does not prove Telegram will accept the upload. The test video is posted to the destination channel, so run it only when that is okay.

Never commit credentials, private invite links, session strings, access hashes, cookies, or media files.

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
