
import json
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from seo_generator import generate_metadata as generate_contextual_metadata
import config as bot_config

# ============================================================
# CONFIG
#
# Paths and logging now come from config.py (derived from the project
# folder itself, not a hardcoded "E:\YT Auto Bot" path). Variable names are
# kept the same as before so the rest of this file does not need to change.
# ============================================================

PROJECT_DIR = bot_config.PROJECT_DIR
OUTPUT_DIR = bot_config.OUTPUT_DIR
TEMP_DIR = bot_config.CACHE_DIR  # "cache" on disk; kept as TEMP_DIR in code below.

CLIENT_SECRETS = Path(os.environ.get("YT_AUTO_BOT_CLIENT_SECRETS", str(PROJECT_DIR / "client_secret.json")))
TOKEN_FILE = Path(os.environ.get("YT_AUTO_BOT_TOKEN_FILE", str(PROJECT_DIR / "youtube_token.json")))

bot_config.setup_logging("youtube_automator")

# This scope is required for uploads. It also lets us upload a
# YouTube caption track through captions.insert.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

NUMBER_OF_SHORTS = 5

# Scheduled uploads are spaced this many hours apart.
# PowerShell override: $env:YT_AUTO_BOT_INTERVAL_HOURS="12"
SCHEDULE_INTERVAL_HOURS = float(os.environ.get("YT_AUTO_BOT_INTERVAL_HOURS", "12"))
SCHEDULE_INTERVAL_MINUTES = int(SCHEDULE_INTERVAL_HOURS * 60)
START_DELAY_MINUTES = int(os.environ.get("YT_AUTO_BOT_START_DELAY_MINUTES", "10"))
LATEST_UPLOAD_PUBLIC = True

# "private" is strongly recommended for the first test.
# Change to "public" only after you verify the generated metadata.
PRIVACY_STATUS = "scheduled"

CATEGORY_ID = "22"  # People & Blogs
DEFAULT_LANGUAGE = "en"
DEFAULT_CHANNEL_KEYWORDS = [
    "shorts",
    "youtube shorts",
]

# Add your own permanent channel keywords here.
CHANNEL_KEYWORDS = [
    # "your niche",
    # "your channel topic",
]

# If True, a .srt subtitle track is uploaded in addition to the
# burned-in captions already present in the rendered video.
UPLOAD_YOUTUBE_CAPTIONS = True

# Interactive by default. Set YT_AUTO_BOT_AUTO_UPLOAD=1 for unattended runs.
AUTO_UPLOAD = os.environ.get("YT_AUTO_BOT_AUTO_UPLOAD", "1") == "1"

# Prevent duplicate uploads by recording uploaded files.
UPLOAD_LOG = Path(os.environ.get("YT_AUTO_BOT_UPLOAD_LOG", str(TEMP_DIR / "youtube_upload_log.json")))


# ============================================================
# UTILITIES
# ============================================================

def normalize(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clean_title(text):
    text = normalize(text)
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\n", " ")
    return text[:100].rstrip(" -:;,") or "Interesting Moment"


def clean_tag(tag):
    tag = normalize(tag).strip("#,")
    if not tag:
        return ""
    if re.search(r"https?://\S+|www\.\S+", tag, re.I):
        return ""
    if '"' in tag or "\n" in tag or "\r" in tag:
        return ""
    tag = re.sub(r"\s+", " ", tag).strip(" ,;|")
    if not tag or len(tag) > 60:
        return ""
    if not re.search(r"[A-Za-z0-9]", tag):
        return ""
    return tag


def youtube_tag_cost(tag, include_comma=False):
    tag = normalize(tag)
    cost = len(tag) + (2 if " " in tag else 0)
    return cost + (1 if include_comma else 0)


def youtube_tags_character_count(tags):
    return sum(
        youtube_tag_cost(tag, include_comma=i > 0)
        for i, tag in enumerate(tags)
    )


def validate_and_normalize_tags(tags, max_chars=470, allowed_phrases=None):
    """Final defense before videos.insert: normalize, dedupe and budget tags."""
    out = []
    seen = set()
    total = 0
    allowed = {
        normalize(x).casefold()
        for x in (allowed_phrases or [])
        if normalize(x)
    }

    for raw in tags or []:
        tag = clean_tag(str(raw))
        if not tag:
            continue

        key = tag.casefold()
        if key in seen:
            continue

        # A final payload validator must also reject phrases that did not come
        # from the confirmed source/entity context. This catches stale or
        # accidental transcript phrases even if an upstream generator changes.
        low = tag.casefold()
        supported = (
            low in allowed
            or any(
                phrase in low
                for phrase in allowed
                if len(phrase) >= 4
            )
        )
        generic_allowed = low in {
            "shorts", "youtube shorts", "tv clips", "web series",
            "entertainment", "clips",
        }

        if len(tag.split()) == 1 and not supported and not generic_allowed:
            continue
        if len(tag.split()) >= 2 and not supported and not generic_allowed:
            continue

        cost = youtube_tag_cost(tag, include_comma=bool(out))
        if total + cost > max_chars:
            continue

        seen.add(key)
        out.append(tag)
        total += cost

    return out


def load_json(path, default=None):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ============================================================
# AUTHENTICATION
# ============================================================

def get_youtube_service():
    if not CLIENT_SECRETS.exists():
        print()
        print("=" * 70)
        print("MISSING YOUTUBE OAUTH CREDENTIALS")
        print("=" * 70)
        print()
        print("Put your downloaded Google OAuth desktop-app JSON here:")
        print(CLIENT_SECRETS)
        print()
        print("Rename it to:")
        print("client_secret.json")
        sys.exit(1)

    credentials = None

    if TOKEN_FILE.exists():
        try:
            credentials = Credentials.from_authorized_user_file(
                str(TOKEN_FILE),
                SCOPES,
            )
        except Exception:
            credentials = None

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRETS),
            SCOPES,
        )
        credentials = flow.run_local_server(port=0)

        save_json(
            TOKEN_FILE,
            json.loads(credentials.to_json()),
        )

    return build(
        "youtube",
        "v3",
        credentials=credentials,
    )


# ============================================================
# TRANSCRIPT / CLIP DATA
# ============================================================

def find_latest_selection():
    files = sorted(
        TEMP_DIR.glob("selected_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def find_transcript_for_selection(selection_path, selected=None):
    if not selection_path:
        return None

    # New selection files carry the exact source_id/run_id in each clip.
    if selected:
        transcript_file = selected[0].get("transcript_file")
        if transcript_file:
            path = Path(transcript_file)
            if path.exists():
                return path

        source_id = selected[0].get("source_id", "")
    else:
        source_id = ""

    if not source_id:
        # Legacy selection filename fallback.
        name = selection_path.name
        source_id = name.removeprefix("selected_").removesuffix(".json")

    path = TEMP_DIR / f"transcript_{source_id}.json"
    return path if path.exists() else None


def load_all_clip_data():
    """Load clip metadata for every processing run we can find.

    main.py stores each run in output/<source_id>/<run_id>/ and writes the
    exact output directory into each selected_*.json file.  The old uploader
    only loaded the newest selection, which meant Shorts in older output
    folders were invisible to the uploader.
    """
    selections = {}
    latest_path = find_latest_selection()

    selection_files = sorted(
        TEMP_DIR.glob("selected_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for selection_path in selection_files:
        selected = load_json(selection_path, [])
        if not selected:
            continue

        transcript_path = find_transcript_for_selection(selection_path, selected)
        transcript = load_json(transcript_path, []) if transcript_path else []

        # A selection file can contain clips from one output directory.
        output_directory = selected[0].get("output_directory")
        if output_directory:
            key = str(Path(output_directory).resolve())
            # Newest selection for a directory wins.
            if key not in selections:
                selections[key] = {
                    "selection_path": selection_path,
                    "selected": selected,
                    "transcript": transcript,
                }

    if not selections:
        raise FileNotFoundError(
            "No usable selected_*.json files found in the temp folder. "
            "Run main.py first."
        )

    # Backward-compatible fallback data for files that do not have matching
    # selection metadata.
    if latest_path:
        latest_selected = load_json(latest_path, [])
        latest_transcript_path = find_transcript_for_selection(
            latest_path, latest_selected
        )
        latest_transcript = (
            load_json(latest_transcript_path, [])
            if latest_transcript_path
            else []
        )
    else:
        latest_selected = []
        latest_transcript = []

    return selections, (latest_path, latest_selected, latest_transcript)


def words_for_clip(transcript, start, end):
    words = []

    for segment in transcript:
        for word in segment.get("words", []):
            if word["start"] < end and word["end"] > start:
                words.append(word)

    return words


# ============================================================
# LOCAL SEO METADATA GENERATOR
# ============================================================

def generate_metadata(clip, index, transcript, project_dir=None, channel_keywords=None, default_channel_keywords=None, privacy_status=None):
    return generate_contextual_metadata(
        clip=clip,
        index=index,
        transcript=transcript,
        project_dir=project_dir or PROJECT_DIR,
        channel_keywords=channel_keywords if channel_keywords is not None else CHANNEL_KEYWORDS,
        default_channel_keywords=default_channel_keywords if default_channel_keywords is not None else DEFAULT_CHANNEL_KEYWORDS,
        privacy_status=privacy_status or PRIVACY_STATUS,
    )


# ============================================================
# SRT CAPTIONS
# ============================================================

def format_srt_time(seconds):
    seconds = max(0, float(seconds))
    millis = int(round((seconds - int(seconds)) * 1000))
    whole = int(seconds)

    if millis >= 1000:
        whole += 1
        millis = 0

    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60

    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def create_srt(clip, transcript, index, clip_key=""):
    start = float(clip["start"])
    end = float(clip["end"])

    words = words_for_clip(transcript, start, end)

    if not words:
        return None

    groups = []
    group = []
    chars = 0

    for word in words:
        text = normalize(word["text"])
        if not text:
            continue

        group.append(word)
        chars += len(text) + 1

        punctuation = text.endswith((".", "?", "!", ",", ";", ":"))

        if len(group) >= 4 or chars >= 42 or punctuation:
            groups.append(group)
            group = []
            chars = 0

    if group:
        groups.append(group)

    lines = []
    number = 1

    for group in groups:
        gs = max(start, group[0]["start"])
        ge = min(end, group[-1]["end"])

        if ge <= gs:
            continue

        text = " ".join(normalize(w["text"]) for w in group)

        lines.extend([
            str(number),
            f"{format_srt_time(gs - start)} --> {format_srt_time(ge - start)}",
            text,
            "",
        ])
        number += 1

    if not lines:
        return None

    # Filename is scoped by clip_key (the clip's clip_id when available,
    # otherwise the selection file's own name) plus index -- not index alone.
    # Index alone collides: two different runs/sources can each have a
    # "short #1", and previously both wrote to the same
    # cache/youtube_caption_01.srt path.
    safe_key = re.sub(r"[^A-Za-z0-9_-]+", "_", clip_key or "clip")[:80]
    srt_path = TEMP_DIR / f"youtube_caption_{safe_key}_{index:02d}.srt"
    srt_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    return srt_path


# ============================================================
# UPLOAD + SCHEDULING
# ============================================================

def iso_to_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_channel_uploads(youtube):
    channel = youtube.channels().list(
        part="contentDetails",
        mine=True,
    ).execute()
    items = channel.get("items", [])
    if not items:
        raise RuntimeError("OAuth account has no accessible YouTube channel.")

    playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    videos = []
    page = None

    while True:
        data = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=page,
        ).execute()

        ids = [x["contentDetails"]["videoId"] for x in data.get("items", [])]
        if ids:
            for i in range(0, len(ids), 50):
                chunk = ids[i:i + 50]
                videos.extend(
                    youtube.videos().list(
                        part="snippet,status,processingDetails",
                        id=",".join(chunk),
                    ).execute().get("items", [])
                )

        page = data.get("nextPageToken")
        if not page:
            break

    return videos


def reconcile_due_schedules(youtube, videos):
    now = datetime.now(timezone.utc)

    for video in videos:
        status = video.get("status", {})
        publish_at = iso_to_dt(status.get("publishAt"))

        if (
            publish_at
            and publish_at <= now
            and status.get("privacyStatus") == "private"
        ):
            video_id = video["id"]
            print(f"Publishing overdue scheduled video: {video_id}")
            youtube.videos().update(
                part="status",
                body={
                    "id": video_id,
                    "status": {"privacyStatus": "public"},
                },
            ).execute()


def reconcile_upload_log(youtube, upload_log):
    """Reconcile local upload state with YouTube before scheduling.

    The local log is only a duplicate-protection cache; YouTube is the source
    of truth for whether a video still exists. If a user deletes a video in
    YouTube Studio, its video ID is no longer returned by videos.list(), so the
    corresponding local-log entry is removed and the rendered Short becomes
    uploadable again.

    If the API check fails, keep the log untouched rather than risking a
    duplicate upload.
    """
    if not upload_log:
        return upload_log, []

    items = list(upload_log.items())
    video_ids = [
        str(entry.get("video_id") or "").strip()
        for _, entry in items
        if str(entry.get("video_id") or "").strip()
    ]
    if not video_ids:
        return upload_log, []

    live_ids = set()
    try:
        for offset in range(0, len(video_ids), 50):
            chunk = video_ids[offset:offset + 50]
            response = youtube.videos().list(
                part="id,status",
                id=",".join(chunk),
            ).execute()
            live_ids.update(
                str(item.get("id"))
                for item in response.get("items", [])
                if item.get("id")
            )
    except Exception as exc:
        print()
        print("WARNING: Could not reconcile upload log with YouTube.")
        print(f"         Keeping local log unchanged: {exc}")
        return upload_log, []

    cleaned = {}
    deleted = []
    for path_key, entry in items:
        video_id = str(entry.get("video_id") or "").strip()
        if video_id and video_id not in live_ids:
            deleted.append((path_key, video_id, entry))
            continue
        cleaned[path_key] = entry

    if deleted:
        print()
        print("YOUTUBE STATE RECONCILIATION")
        print("=" * 70)
        for path_key, video_id, _entry in deleted:
            print(f"Deleted on YouTube -> reopening local Short: {video_id}")
            print(f"  {path_key}")
        save_upload_log(cleaned)

    return cleaned, deleted


def next_schedule_slots(videos, count):
    """Return the earliest free future publishing slots.

    Existing scheduled videos occupy their publishAt slots. Unlike the old
    max(publishAt) + interval approach, this deliberately fills holes created
    when a user deletes a scheduled video in YouTube Studio.
    """
    if count <= 0:
        return []

    now = datetime.now(timezone.utc)
    cursor = now + timedelta(minutes=START_DELAY_MINUTES)
    occupied = set()

    for video in videos:
        status = video.get("status", {})
        publish_at = iso_to_dt(status.get("publishAt"))
        if (
            publish_at
            and publish_at > now
            and status.get("privacyStatus") == "private"
        ):
            # Normalize to the scheduler's minute precision.
            occupied.add(publish_at.replace(second=0, microsecond=0))

    slots = []
    while len(slots) < count:
        candidate = cursor.replace(second=0, microsecond=0)
        if candidate not in occupied:
            slots.append(candidate)
            occupied.add(candidate)
        cursor = candidate + timedelta(minutes=SCHEDULE_INTERVAL_MINUTES)

    return slots


def validate_before_upload(video_path, metadata):
    """Validate the exact metadata that will be sent to videos.insert."""
    problems = []

    if not video_path.exists():
        problems.append(f"Input file does not exist: {video_path}")
    else:
        if video_path.stat().st_size <= 0:
            problems.append(f"Output file is empty (0 bytes): {video_path}")
        if video_path.suffix.lower() != ".mp4":
            problems.append(f"Output file is not an .mp4: {video_path}")

    try:
        video_path.resolve().relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        problems.append(f"Output file is not under the output/ directory: {video_path}")

    if not normalize(metadata.get("title")):
        problems.append("No title was generated.")
    if not normalize(metadata.get("description")):
        problems.append("No description was generated.")

    public_text = " ".join([
        normalize(metadata.get("title")),
        normalize(metadata.get("description")),
        " ".join(metadata.get("tags") or []),
    ])
    if re.search(r"https?://\S+|www\.\S+", public_text, re.I):
        problems.append("A URL was found in public metadata (title/description/tags).")

    # Re-normalize the FINAL metadata immediately before upload. This protects
    # against future SEO changes and guarantees the payload itself is safe.
    original_tags = metadata.get("tags") or []
    context = metadata.get("source_context") or {}
    allowed_phrases = [
        context.get("title", ""),
        *context.get("characters", [])[:8],
        *context.get("actors", [])[:8],
        *context.get("keywords", [])[:20],
        "shorts",
        "youtube shorts",
    ]
    final_tags = validate_and_normalize_tags(
        original_tags,
        max_chars=470,
        allowed_phrases=allowed_phrases,
    )
    metadata["tags"] = final_tags

    tag_chars = youtube_tags_character_count(final_tags)
    metadata["tag_character_count"] = tag_chars

    if not final_tags:
        problems.append("No valid YouTube tags remain after final validation.")
    if tag_chars > 500:
        problems.append(f"YouTube tag budget exceeded: {tag_chars}/500.")
    if len(final_tags) < 10:
        problems.append(
            f"Only {len(final_tags)} valid tag(s) remain after validation; "
            "expected approximately 10+ relevant candidates."
        )

    # Verify the exact list is internally clean.
    lowered = [t.casefold() for t in final_tags]
    if len(lowered) != len(set(lowered)):
        problems.append("Duplicate tags remain after final normalization.")

    return (not problems), problems

def check_cache_isolation():
    """Sanity check: nothing that looks like a generated cache/temp file is
    sitting in input/ or output/, which would defeat the point of separating
    them. This only warns -- it never deletes anything.
    """
    suspicious_suffixes = {".ass", ".srt", ".json"}
    input_dir = bot_config.INPUT_DIR
    offenders = [
        p for p in input_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in suspicious_suffixes
        and not p.name.endswith((".url.txt", ".metadata.json"))
    ]
    if offenders:
        print()
        print("WARNING: possible cache/processing files found inside input/:")
        for p in offenders:
            print(f"  {p}")


def upload_video(youtube, video_path, metadata, publish_at=None):
    privacy = metadata["privacyStatus"]

    status = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": False,
    }

    if publish_at:
        if privacy != "private":
            raise ValueError("A scheduled YouTube video must be private.")
        status["publishAt"] = publish_at.isoformat().replace("+00:00", "Z")

    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata["tags"],
            "categoryId": metadata["categoryId"],
            "defaultLanguage": metadata["defaultLanguage"],
        },
        "status": status,
    }

    print()
    print(f"Uploading: {video_path.name}")
    print(f"Privacy: {privacy}")
    if publish_at:
        print(
            "Scheduled public time:",
            publish_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        )

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        progress, response = request.next_chunk()
        if progress:
            print(f"Upload progress: {progress.progress() * 100:.1f}%")

    return response


def verify_video(youtube, video_id):
    items = youtube.videos().list(
        part="status,processingDetails,snippet",
        id=video_id,
    ).execute().get("items", [])
    return items[0] if items else None



def upload_caption(youtube, video_id, srt_path):
    """Upload an SRT subtitle track without failing the video upload.

    The previous v8 file called this function but did not define it, which
    caused the automator to stop immediately after a successful video upload.
    """
    if not srt_path or not srt_path.exists():
        return False

    print("Uploading YouTube subtitle track...")

    media = MediaFileUpload(
        str(srt_path),
        mimetype="application/x-subrip",
        resumable=False,
    )

    body = {
        "snippet": {
            "videoId": video_id,
            "language": DEFAULT_LANGUAGE,
            "name": "English",
            "isDraft": False,
        }
    }

    try:
        youtube.captions().insert(
            part="snippet",
            body=body,
            media_body=media,
        ).execute()
        print("YouTube caption track uploaded.")
        return True
    except HttpError as error:
        # A caption failure should never undo/fail the video upload.
        print()
        print("Caption upload failed (video upload is still successful):")
        print(error)
        return False

# ============================================================
# DUPLICATE PROTECTION
# ============================================================

def load_upload_log():
    return load_json(UPLOAD_LOG, {})


def save_upload_log(data):
    save_json(UPLOAD_LOG, data)


# ============================================================
# MAIN
# ============================================================

def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)

    print()
    print("=" * 70)
    print("YOUTUBE SHORTS AUTOMATOR")
    print("=" * 70)
    print(f"Account: {os.environ.get("YT_AUTO_BOT_ACCOUNT_NAME", "Default YouTube account")}")
    print(f"Schedule interval: {SCHEDULE_INTERVAL_HOURS:g} hours")
    print("Newest pending Short: PUBLIC immediately")

    check_cache_isolation()

    selection_map, fallback_data = load_all_clip_data()
    latest_selection_path, latest_selected, latest_transcript = fallback_data

    print()
    print("Selection metadata loaded for output folders:")
    for folder in sorted(selection_map):
        print(f"  {folder}")
    if latest_selection_path:
        print("Latest selection file:")
        print(latest_selection_path)

    youtube = get_youtube_service()
    upload_log = load_upload_log()

    # YouTube is the source of truth. If a Short was manually deleted from
    # YouTube Studio, remove only that stale local-log entry so the rendered
    # file can be uploaded again on the next pass.
    upload_log, deleted_log_entries = reconcile_upload_log(youtube, upload_log)
    if deleted_log_entries:
        print(
            f"Reopened {len(deleted_log_entries)} deleted Short(s) for scheduling."
        )

    # IMPORTANT: scan recursively. main.py creates:
    # output/<source_id>/<run_id>/short_XX.mp4
    # so glob("short_*.mp4") at OUTPUT_DIR only sees files directly in the
    # output root and misses all Shorts inside source/run subfolders.
    output_files = sorted(
        OUTPUT_DIR.rglob("short_*.mp4"),
        key=lambda p: (p.stat().st_mtime, str(p).lower()),
    )
    if not output_files:
        raise FileNotFoundError(
            f"No rendered Shorts found anywhere under {OUTPUT_DIR}. "
            "Run main.py first."
        )

    # Dashboard selection support. When the web UI supplies absolute output
    # paths, upload only those files. With no selection variable, preserve the
    # original behavior and process every pending rendered Short.
    selected_raw = os.environ.get("YT_AUTO_BOT_SELECTED_FILES", "").strip()
    if selected_raw:
        requested = {
            str(Path(item).resolve())
            for item in selected_raw.split(os.pathsep)
            if item.strip()
        }
        output_files = [p for p in output_files if str(p.resolve()) in requested]
        print()
        print(f"Dashboard-selected Shorts: {len(output_files)}")
        for selected in output_files:
            print(f"  {selected}")
        if not output_files:
            print("No selected Shorts were found under output/. Nothing to upload.")
            return

    print()
    print(f"Rendered Shorts found (all folders): {len(output_files)}")

    # Check the channel first so scheduling continues after already scheduled
    # videos instead of creating overlapping/duplicate slots.
    existing = get_channel_uploads(youtube)
    reconcile_due_schedules(youtube, existing)

    pending = []

    for video_path in output_files:
        key = str(video_path.resolve())

        if key in upload_log:
            print(
                f"Skipping already-uploaded file: {video_path.name} "
                f"-> {upload_log[key].get('video_id')}"
            )
            continue

        match = re.search(r"short_(\d+)", video_path.stem)
        index = int(match.group(1)) if match else 1

        # Match this Short to the selection/transcript belonging to its own
        # output/<source_id>/<run_id> folder. This preserves the better SEO
        # context and captions for older runs too.
        folder_key = str(video_path.parent.resolve())
        run_data = selection_map.get(folder_key)

        if run_data:
            run_selected = run_data["selected"]
            run_transcript = run_data["transcript"]
            run_selection_path = run_data["selection_path"]
        else:
            run_selected = latest_selected
            run_transcript = latest_transcript
            run_selection_path = latest_selection_path
            print(
                f"WARNING: No selection metadata found for {video_path.parent}. "
                "Using the latest selection as fallback."
            )

        clip = (
            run_selected[index - 1]
            if index <= len(run_selected)
            else {"start": 0, "end": 60, "text": ""}
        )

        pending.append(
            (video_path, index, clip, key, run_transcript, run_selection_path)
        )

    if not pending:
        print("Nothing new to upload.")
        return

    scheduled_count = max(0, len(pending) - (1 if LATEST_UPLOAD_PUBLIC else 0))
    schedule_slots = next_schedule_slots(existing, scheduled_count)
    schedule_index = 0

    for position, (video_path, index, clip, key, transcript, selection_path) in enumerate(pending):
        # Preserve the requested behavior: the newest upload in this batch is
        # public immediately; older pending uploads are scheduled.
        is_latest = position == len(pending) - 1 and LATEST_UPLOAD_PUBLIC

        if is_latest:
            privacy = "public"
            publish_at = None
        else:
            privacy = "private"
            publish_at = schedule_slots[schedule_index]
            schedule_index += 1

        metadata = generate_metadata(
            clip=clip,
            index=index,
            transcript=transcript,
            project_dir=PROJECT_DIR,
            channel_keywords=CHANNEL_KEYWORDS,
            default_channel_keywords=DEFAULT_CHANNEL_KEYWORDS,
            privacy_status=privacy,
        )

        metadata_path = (
            TEMP_DIR
            / f"youtube_metadata_{selection_path.stem}_{index:02d}.json"
        )
        save_json(metadata_path, metadata)

        print()
        print("-" * 70)
        print(f"SHORT #{index}")
        print("-" * 70)
        print(f"MODE: {'PUBLIC NOW' if is_latest else 'SCHEDULED -> PUBLIC'}")

        # Final validation mutates only metadata["tags"] and its derived count,
        # so the report below is exactly the payload that will be uploaded.
        ok, problems = validate_before_upload(video_path, metadata)

        context = metadata.get("source_context") or {}
        series = normalize(context.get("title")) or "Unknown"
        characters = [
            normalize(x) for x in context.get("characters", [])[:4]
            if normalize(x)
        ]

        print()
        print("=" * 50)
        print("FINAL YOUTUBE METADATA")
        print("=" * 50)
        print()
        print("Clip ID:")
        print(clip.get("clip_id") or f"{selection_path.stem}_{index:02d}")
        print()
        print("Series / Source:")
        print(series)
        print()
        print("Characters:")
        print(", ".join(characters) if characters else "None confirmed")
        print()
        print("TITLE:")
        print(metadata["title"])
        print()
        print("DESCRIPTION:")
        print(metadata["description"])
        print()
        print("TAGS:")
        for tag_number, tag in enumerate(metadata.get("tags", []), 1):
            print(f"{tag_number}. {tag}")

        print()
        print(f"Tag count: {len(metadata.get('tags', []))}")
        print(f"Tag character budget: {metadata.get('tag_character_count', 0)} / 500")
        print(f"YouTube tag validation: {'PASS' if ok else 'FAIL'}")
        print("=" * 50)

        # Save the post-validation metadata so the JSON report matches the
        # exact tag list that is about to enter the API request.
        save_json(metadata_path, metadata)

        if not ok:
            print()
            print("VALIDATION FAILED -- skipping this Short (not uploaded):")
            for problem in problems:
                print(f"  - {problem}")
            continue

        print()
        print("Validation passed:")
        print("  input file exists, output file exists and is valid,")
        print(f"  title/description generated, {len(metadata['tags'])} final tags,")
        print(f"  YouTube tag budget: {metadata['tag_character_count']} / 500,")
        print("  output file is under output/.")


        # Upload automatically. No Y/N prompt.
        print("\nAUTO_UPLOAD is enabled; uploading without confirmation.")

        response = upload_video(
            youtube,
            video_path,
            metadata,
            publish_at=publish_at,
        )
        video_id = response["id"]

        caption_uploaded = False
        if UPLOAD_YOUTUBE_CAPTIONS and transcript:
            clip_key = clip.get("clip_id") or f"{selection_path.stem}"
            srt_path = create_srt(clip, transcript, index, clip_key=clip_key)
            caption_uploaded = upload_caption(youtube, video_id, srt_path)

        verified = verify_video(youtube, video_id)
        actual = verified.get("status", {}) if verified else {}

        print()
        print("YouTube verification:")
        print("Video ID:", video_id)
        print("Privacy:", actual.get("privacyStatus"))
        print("PublishAt:", actual.get("publishAt", "none"))

        if is_latest and actual.get("privacyStatus") != "public":
            print()
            print("WARNING: YouTube did not leave the newest upload PUBLIC.")
            print("This can happen when the API project/account is restricted.")
            print("The bot cannot bypass a YouTube API restriction.")

        upload_log[key] = {
            "video_id": video_id,
            "title": metadata["title"],
            "privacyStatus": privacy,
            "publishAt": (
                publish_at.isoformat().replace("+00:00", "Z")
                if publish_at
                else None
            ),
            "caption_uploaded": caption_uploaded,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        save_upload_log(upload_log)

        print()
        print("Done:")
        print(f"https://www.youtube.com/shorts/{video_id}")

    print()
    print("=" * 70)
    print("UPLOAD / SCHEDULING COMPLETE")
    print("=" * 70)
    print(f"Interval: {SCHEDULE_INTERVAL_HOURS:g} hours")
    print("Newest pending upload: PUBLIC immediately")
    print("Older pending uploads: scheduled PRIVATE -> PUBLIC")
    print("Deleted YouTube slots: automatically reused on the next run")


if __name__ == "__main__":
    try:
        main()
    except HttpError as error:
        print()
        print("YouTube API error:")
        print(error)
        sys.exit(1)
    except Exception as error:
        print()
        print("ERROR:")
        print(error)
        sys.exit(1)
