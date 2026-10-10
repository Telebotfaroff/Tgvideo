# Tgvideo — Telegram Auto Uploader

A standalone GitHub Actions worker that reads a JSON manifest of direct media URLs, downloads each authorized item, uploads it to a Telegram channel, and records progress so completed items are skipped on later runs.

## Environment variables

Configure these repository secrets under **Settings → Secrets and variables → Actions**:

- `API_ID`
- `API_HASH`
- `BOT_TOKEN`
- `TELEGRAM_TARGET` — destination channel ID (for example, a `-100...` ID) or channel username.

The bot must be a member of the destination channel and have permission to post.

For local runs, copy `.env.example` to `.env` and fill in your values. Never commit `.env` or session files.

## Manifest

Edit `database/authorized_media.json`:

```json
{
  "items": [
    {
      "id": "sample-001",
      "url": "https://cdn.example.org/sample.mp4",
      "title": "Sample video",
      "thumbnail": "https://cdn.example.org/sample.jpg",
      "source_url": "https://example.org/sample-page"
    }
  ]
}
```

Use a unique, stable `id` for every item. The media `url` must be a direct HTTP(S) URL. Example URLs are placeholders and will not upload.

## Run

- Manual: open **Actions → Telegram Auto Uploader → Run workflow**.
- Automatic: runs hourly from the repository's default branch.

GitHub scheduled workflows run only from the default branch. The workflow commits `database/processed.json` after a run so successful items are skipped next time.

## Recovery behavior

- Successful items are marked `completed` and skipped in later runs.
- Failed items can retry on later runs up to `MAX_ITEM_ATTEMPTS` (default 5).
- A crash after Telegram accepts an upload but before the checkpoint is saved can cause a duplicate on a later run; exactly-once delivery cannot be guaranteed.
- Start with one small media item before adding a larger batch.

## Scope and limits

- This repository is independent of the scraper project and does not crawl websites or extract media links.
- It processes only supplied direct URLs for media you own or are authorized to redistribute.
- Very large uploads depend on Telegram/Pyrogram limits and the file format/source server.
