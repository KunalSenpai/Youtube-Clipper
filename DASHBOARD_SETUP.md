# YT Auto Bot Dashboard

This is a small local control panel around the existing bot. It does not replace
`main.py`, source detection, SEO generation, or the YouTube scheduling logic.

## Install

Copy these files/folders into the project:

- `dashboard.py`
- `dashboard/index.html`
- `dashboard/style.css`
- `dashboard/app.js`
- `config/accounts.json` (copy from `accounts.example.json` and edit)

The dashboard uses only Python's standard library, so no new pip package is
required.

## Start

PowerShell:

```powershell
.\venv\Scripts\python.exe dashboard.py
```

Open:

```text
http://127.0.0.1:8765
```

## Accounts

For each YouTube account, authorize once and store its OAuth token in a
different file:

```json
{
  "accounts": [
    {
      "id": "youtube_main",
      "name": "YouTube Main",
      "platform": "youtube",
      "token_file": "youtube_token_main.json",
      "upload_log": "cache/youtube_upload_log_youtube_main.json"
    },
    {
      "id": "youtube_clips",
      "name": "YouTube Clips",
      "platform": "youtube",
      "token_file": "youtube_token_clips.json",
      "upload_log": "cache/youtube_upload_log_youtube_clips.json"
    }
  ]
}
```

The dashboard passes the selected account's token and upload log to the
existing `youtube_automator.py`. Your original default token/log behavior is
unchanged when the uploader is run normally.

## Selection

Select individual rendered `short_XX.mp4` files in the dashboard. The uploader
receives only those paths through `YT_AUTO_BOT_SELECTED_FILES`.

## Instagram

The destination selector is included, but Instagram publishing is deliberately
not faked. Meta/Instagram publishing requires the appropriate professional
account, permissions and media-delivery configuration. A local Windows file
cannot simply be handed to the Instagram Graph API as if it were a public URL.

The UI therefore exposes Instagram as a destination while the backend reports
it as not configured until a real publisher is added.

## Important

Keep `client_secret.json`, OAuth tokens, API credentials and account secrets
out of source control.
