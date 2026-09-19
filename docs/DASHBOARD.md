# Dashboard guide

The dashboard is a private control panel around the existing generation and
YouTube publishing pipeline. It uses Python's standard library and does not add
a web-framework dependency.

## Start the dashboard

```bash
python dashboard.py
```

Open <http://127.0.0.1:8765>.

## Accounts

Account definitions live in `config/accounts.json`. Each YouTube account should
use a separate token file and upload log:

```json
{
  "accounts": [
    {
      "id": "youtube_main",
      "name": "YouTube Main",
      "platform": "youtube",
      "token_file": "youtube_token.json",
      "upload_log": "cache/youtube_upload_log_youtube_main.json"
    }
  ]
}
```

Token files and upload logs remain local and are excluded from Git.

## Generation

The Generate view launches `main.py` for a supported YouTube URL. Output is
grouped under the selected account. Live job progress and recent process output
are available in the Activity view.

## Review and publishing

1. For a newly rendered Short, choose **Adjust frame** if the automatic
   face-tracked crop needs correction. Drag the 9:16 outline on the full-frame
   source, set zoom, and choose **Save and re-render**. The source master is
   retained for later revisions.
2. Select one or more rendered `short_XX.mp4` files.
3. Choose **Prepare upload**.
4. Review or edit the title, description, tags, and visibility.
5. Confirm the validation result and planned publishing action.
6. Choose **Approve and upload**.

The preparation step runs without OAuth or YouTube API calls. Approval stores
the exact reviewed request, and the uploader stops if its final request differs
from the approved copy.

## Remote access

The dashboard does not implement user authentication. Keep it bound to
localhost and use a trusted private proxy or VPN for remote access. The
[Proxmox deployment guide](PROXMOX_DEPLOYMENT.md) uses Tailscale Serve.

## Instagram

Instagram appears as an unavailable destination. Publishing is intentionally
not simulated because the Instagram Graph API requires an eligible
professional account, permissions, and publicly accessible media delivery.
