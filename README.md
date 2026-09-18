YouTube Shorts Automator

A local, privacy-focused automation tool for turning long-form video
into short-form vertical videos and managing YouTube Shorts uploads from
a simple dashboard.

Important: Only process and publish video content that you own or
are authorized/licensed to use. This project does not bypass copyright
restrictions or platform policies.

Features

🎬 Automatic Short Generation

Process local video files or download supported YouTube sources with
yt-dlp.

Transcribe the complete source using Faster-Whisper.

Cache transcripts so the same source does not need to be transcribed
repeatedly.

Detect the broader video/source context before generating metadata.

Find content-driven moments instead of cutting at arbitrary fixed
intervals.

Prefer coherent conversation/story segments with natural sentence
and pause boundaries.

Avoid excessive overlap and duplicate moments.

Generate vertical 1080 × 1920 Shorts.

Apply speaker-aware framing with restrained face cropping/zoom.

Generate synchronized .srt captions for each Short.

🧠 Context-Aware SEO

The SEO system is designed around the larger context of the source,
rather than blindly converting transcript words into tags.

Metadata generation considers information such as: - Series/source
name - Source type - Season/episode information when available -
Verified source-level context - Clip-specific context where it can be
established reliably

The generated title includes the series/source name, for example:

Butlerger, how may we help you? | The Office

Tags are validated before upload and are not artificially padded with
unrelated transcript words just to reach a target count.

📤 YouTube Upload Automation

Upload generated Shorts automatically.

Upload captions to the exact corresponding YouTube video.

Maintain per-account upload logs.

Prevent accidental duplicate uploads.

Support immediate publishing and scheduled publishing.

Reconcile local logs with the current YouTube channel state.

🗓️ Intelligent Scheduling

The scheduler uses existing upload/scheduling state rather than blindly
making every new Short public immediately.

Current policy:

No future scheduled video
        ↓
First pending Short → PUBLIC NOW
Remaining Shorts    → scheduled at the configured interval

Future scheduled video already exists
        ↓
New Shorts → scheduled into available slots

The default interval is 12 hours.

If a previously scheduled video is deleted from YouTube Studio, the
local upload state can be reconciled so the released slot can be reused.

👥 Multiple YouTube Accounts

The bot supports separate YouTube accounts with: - Separate OAuth token
files - Separate upload logs - Separate duplicate protection -
Account-specific upload history

Example:

YouTube Main
YouTube Account 2

OAuth credentials and tokens remain local and should never be committed
to Git.

🖥️ Local Dashboard

The dashboard provides: - Video discovery - Video selection - Account
selection - Upload destination selection - Upload queue - Generation
jobs - Upload history - Job status - Retry/failed-job handling - Stop
running generation/upload jobs - Delete generated Shorts and related
generated metadata - Live technical progress

The Live Technical Progress panel displays: - Current processing
stage - Job status - Elapsed time - Approximate progress - Recent
backend log output

The raw technical console is the authoritative source for detailed
progress.

🧹 Generated-Short Cleanup

The dashboard can delete generated Shorts and their associated generated
artifacts while preserving source material needed for future processing.

The cleanup system is designed to avoid unnecessarily deleting: -
Original source downloads - Cached source transcripts

Project Structure

YT Auto Bot/
│
├── main.py
├── youtube_automator.py
├── dashboard.py
├── config.py
├── seo_generator.py
├── source_detector.py
├── run_all.py
├── requirements.txt
│
├── dashboard/
│   ├── index.html
│   ├── app.js
│   └── style.css
│
├── config/
│   ├── accounts.json
│   └── accounts.example.json
│
├── cache/
│   ├── transcripts
│   ├── upload logs
│   └── OAuth token files
│
├── output/
│   └── generated Shorts
│
└── logs/
    └── execution/job logs

Requirements

Software

Windows 10/11

Python 3.10+ recommended

FFmpeg

Deno

Google/YouTube OAuth credentials

Internet connection for YouTube downloads/uploads

Faster-Whisper dependencies

Hardware

The bot can run on CPU, although transcription is significantly faster
with a suitable GPU.

The current configuration can use:

Whisper model: small
Device: CPU
Compute type: int8

This can be adjusted in the project configuration if you have hardware
suitable for another Whisper configuration.

Installation

1. Clone or copy the project

Place the project somewhere such as:

D:\Personal\YT Auto Bot

Avoid hard-coding the project location into source files; the
application derives paths relative to the project.

2. Create a virtual environment

From PowerShell:

cd "D:\Personal\YT Auto Bot"

python -m venv venv
.\venv\Scripts\activate

3. Install Python dependencies

python -m pip install --upgrade pip
pip install -r requirements.txt

If the project requires the current yt-dlp EJS dependencies:

python -m pip install -U "yt-dlp[default]"

4. Install FFmpeg

Make sure ffmpeg is available from PowerShell:

ffmpeg -version

If the command is not found, install FFmpeg and add its bin directory
to PATH.

5. Install Deno

Deno is used by yt-dlp for YouTube JavaScript challenge solving.

Official installation:

irm https://deno.land/install.ps1 | iex

Close and reopen PowerShell after installation.

Verify:

deno --version
where.exe deno

If Deno is installed but not on PATH, the downloader can be configured
to use the executable path directly.

YouTube OAuth Setup

Create YouTube API OAuth credentials in Google Cloud and download the
OAuth client configuration required by the project.

Do not commit: - OAuth client secrets - Access tokens - Refresh
tokens - Browser cookies - Cookie exports - API keys

The project stores account-specific authentication locally.

Example account configuration:

{
  "accounts": [
    {
      "id": "youtube_main",
      "name": "YouTube Main",
      "platform": "youtube",
      "token_file": "youtube_token.json",
      "upload_log": "cache/youtube_upload_log_youtube_main.json"
    },
    {
      "id": "youtube_account2",
      "name": "YouTube Account 2",
      "platform": "youtube",
      "token_file": "youtube_token_account2.json",
      "upload_log": "cache/youtube_upload_log_account2.json"
    }
  ]
}

Use your actual configuration structure from config/accounts.json.

Running the Bot

Dashboard

Start the local dashboard using the project's normal launcher:

.\venv\Scripts\activate
python dashboard.py

Then open the local dashboard address shown by the application.

Direct generation

For direct/manual operation:

python main.py

The command-line interface can process a local video or a supported
YouTube URL.

Full launcher

If using the provided launcher:

python run_all.py

Typical Workflow

Select source
     ↓
Download / locate source
     ↓
Transcribe complete source
     ↓
Cache transcript
     ↓
Detect source context
     ↓
Find semantic moments
     ↓
Select high-quality moments
     ↓
Render vertical Shorts
     ↓
Generate captions
     ↓
Generate context-aware metadata
     ↓
Validate metadata
     ↓
Select YouTube account
     ↓
Check upload history / current schedule
     ↓
Upload immediately or schedule
     ↓
Upload captions
     ↓
Record result in upload history

Source Detection

The source detector attempts to identify the broader context of the
video.

Example:

Source type: webseries
Detected source: The Office
Confidence: 97%

Source context is intentionally kept separate from the individual clip
transcript.

This prevents a random phrase from a transcript from being treated as
the name of a series, character, actor, or other entity.

Clip Selection

The selector is content-driven.

It aims to identify moments containing things such as: - A setup and
response - A complete exchange - A punchline - A reaction - A meaningful
statement - A coherent conversational unit

It does not require every source to produce exactly 5 or 10 Shorts.

The configured target range is a quality target, not a quota.

A source may therefore produce fewer Shorts when there are not enough
strong moments.

Captions

Each generated Short receives its own caption file.

Conceptually:

source/
└── run/
    ├── short_01.mp4
    ├── youtube_caption_<clip-id>_01.srt
    ├── short_02.mp4
    └── youtube_caption_<clip-id>_02.srt

When a video is uploaded, its caption file is associated with the exact
returned YouTube videoId.

This prevents captions from one Short being attached to another.

SEO Rules

The metadata system follows several principles:

Titles

Short, readable hook

Series/source included

No unrelated entities

No fabricated context

Tags

Series-level tags are allowed when relevant.

Source-type/context tags can be used when relevant.

Season/episode tags are used only when supported.

Character tags require reliable context.

Transcript words are not automatically converted into tags.

Duplicate tags are removed.

Invalid/empty tags are removed.

The final tag list respects YouTube's tag character limit.

Descriptions

The intended description format is deliberately simple:

Series - "The Office"

#tags -
#TheOffice #TheOfficeclips #TheOfficeshorts ...

No transcript dump, unrelated character list, source-detection
explanation, or generated filler should be inserted into the
description.

Scheduling

The default publishing interval is:

12 hours

The scheduler considers: - Existing local upload logs - Existing YouTube
videos - Future publishAt values - Deleted videos - Pending Shorts -
Account-specific history

Example:

Existing schedule:
10:00 PM
10:00 AM
10:00 PM

New Shorts:
→ next available slot
→ next available slot
→ next available slot

A deleted scheduled video should release its slot for future scheduling
after reconciliation.

Upload States

The dashboard tracks job and upload states separately.

Common states include:

READY
SELECTED
QUEUED
UPLOADING
UPLOADED
SCHEDULED
FAILED
CANCELLED

A failed upload can be retried without regenerating the Short
unnecessarily.

Troubleshooting

UnicodeEncodeError: cp1252

If Windows PowerShell displays an error involving:

UnicodeEncodeError
'charmap' codec can't encode character

the problem is usually Windows console encoding.

The project includes UTF-8-safe output handling so Unicode characters
such as arrows and other symbols do not terminate the job.

YouTube 429 Too Many Requests

A 429 is a YouTube-side rate-limit response.

Do not repeatedly retry the same URL in a tight loop.

If YouTube asks you to sign in or verify that you are not a bot, use an
authenticated browser session where appropriate and comply with
YouTube's requirements.

No supported JavaScript runtime could be found

Check:

deno --version
where.exe deno

Then restart PowerShell if Deno was just installed.

Upload validation fails

Check the technical log immediately before upload.

The bot should report: - Final title - Description - Tags - Tag count -
Tag character budget - Validation errors

Do not solve a validation problem by adding irrelevant tags.

A scheduled video is missing

The scheduler reconciles local state with YouTube.

Check: 1. Whether the video still exists on YouTube. 2. Whether the
local upload log contains its video ID. 3. Whether the video has a
future publishAt. 4. Whether the correct YouTube account is selected.

Dashboard shows a different number of Shorts

The dashboard and uploader may use different selection/discovery states.

The uploader reports selected files and missing paths in its technical
log so the discrepancy can be diagnosed without silently uploading the
wrong files.

Security

Keep the following files private:

cache/*token*.json
cache/*credentials*.json
client_secret*.json
*.cookies

Privacy

The bot is designed to run locally.

Source videos, generated Shorts, transcripts, logs, OAuth tokens, and
upload history remain on the local machine unless the application sends
data to an external service as part of an explicitly requested operation
such as YouTube uploading.

Limitations

YouTube can change its extraction and anti-bot behavior without
notice.

YouTube API limits and channel upload limits are controlled by
YouTube.

Scheduled publishing requires YouTube to accept the requested
publishAt.

Source detection is probabilistic and should be reviewed when
confidence is low.

Semantic clip selection is designed for coherent moments, but
automated selection is not equivalent to human editorial review.

SEO generation cannot reliably infer facts that are not supported by
the available source context.

Instagram upload functionality depends on the configured integration
and is not represented as working merely because it appears in the
UI.

Responsible Use

This software is intended as an automation and editing tool.

You are responsible for: - Having rights to the source material -
Complying with YouTube's Terms of Service and API policies - Complying
with copyright law - Reviewing generated metadata - Reviewing Shorts
before publication - Respecting platform upload and rate limits

Development Philosophy

The project prioritizes:

Context over keyword stuffing

Content quality over a fixed number of Shorts

Reliable upload/account separation

Persistent logs and recoverable jobs

Exact caption-to-video binding

Safe scheduling based on actual channel state

Local control of credentials and generated files

Transparent technical progress instead of fake percentages

This project is currently for personal use. No redistribution license is granted unless explicitly stated by the author.