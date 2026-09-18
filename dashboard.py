"""
YT Auto Bot - local dashboard/control center.

The dashboard is a thin local control panel around the existing automation engine.
It launches main.py for generation and youtube_automator.py for publishing.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import uuid
import signal
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config as bot_config

ROOT = bot_config.PROJECT_ROOT
OUTPUT = bot_config.OUTPUT_DIR
CACHE = bot_config.CACHE_DIR
LOGS = bot_config.LOGS_DIR
REPORTS = OUTPUT / "dry-run-reports"
DASHBOARD_DIR = ROOT / "dashboard"
ACCOUNTS_FILE = ROOT / "config" / "accounts.json"
DB_FILE = CACHE / "dashboard.db"
HOST = os.environ.get("YT_AUTO_BOT_DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("YT_AUTO_BOT_DASHBOARD_PORT", "8765"))

DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)

INDEX = DASHBOARD_DIR / "index.html"
STYLE = DASHBOARD_DIR / "style.css"
APPJS = DASHBOARD_DIR / "app.js"

# Live subprocess registry. Threads alone cannot terminate a child process;
# keeping Popen handles lets the Stop button terminate the complete process tree.
PROCESS_LOCK = threading.RLock()
ACTIVE_PROCESSES: dict[str, subprocess.Popen] = {}
CANCELLED_JOBS: set[str] = set()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            account_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            selected_files TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            exit_code INTEGER,
            log_file TEXT,
            error TEXT,
            job_type TEXT NOT NULL DEFAULT 'upload',
            source_url TEXT,
            report_file TEXT
        )
    """)
    # Backward-compatible migration for the first dashboard version.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    if "job_type" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN job_type TEXT NOT NULL DEFAULT 'upload'")
    if "source_url" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN source_url TEXT")
    if "report_file" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN report_file TEXT")
    conn.commit()
    return conn


def load_accounts():
    if not ACCOUNTS_FILE.exists():
        return {"accounts": [{
            "id": "youtube_main",
            "name": "YouTube Main",
            "platform": "youtube",
            "token_file": "youtube_token.json",
            "upload_log": "cache/youtube_upload_log_youtube_main.json",
        }]}
    try:
        data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {"accounts": []}
    except Exception:
        return {"accounts": []}


def account_by_id(account_id):
    for account in load_accounts().get("accounts", []):
        if str(account.get("id")) == str(account_id):
            return account
    return None


def content_account_id(path: Path):
    """Return the account encoded by output/accounts/<account_id>/..., or None for legacy output."""
    try:
        rel = path.resolve().relative_to(OUTPUT.resolve())
        parts = rel.parts
        if len(parts) >= 3 and parts[0].lower() == "accounts":
            return parts[1]
    except Exception:
        pass
    return None


def all_videos(account_id=None):
    rows = []
    for path in sorted(OUTPUT.rglob("short_*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        owner = content_account_id(path)
        if account_id and owner not in {account_id, None}:
            continue
        stat = path.stat()
        try:
            folder = str(path.parent.relative_to(OUTPUT))
        except ValueError:
            folder = path.parent.name
        rows.append({
            "path": str(path.resolve()),
            "name": path.name,
            "folder": folder,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "content_account_id": owner,
            "legacy": owner is None,
        })
    return rows


def account_log_path(account):
    configured = account.get("upload_log")
    if configured:
        return ROOT / configured
    return CACHE / f"youtube_upload_log_{account['id']}.json"


def load_log(account):
    path = account_log_path(account)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def job_rows():
    with db() as conn:
        return [dict(x) for x in conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 150"
        )]


def reconcile_stale_jobs():
    """Reset jobs left RUNNING when the dashboard/backend was force-killed."""
    with db() as conn:
        rows = conn.execute("SELECT id, status FROM jobs WHERE status='running'").fetchall()
    stale=[]
    with PROCESS_LOCK:
        live=set(ACTIVE_PROCESSES)
    for row in rows:
        if row[0] not in live:
            stale.append(row[0])
    for job_id in stale:
        update_job(job_id, status="cancelled", finished_at=utc_now(), exit_code=-15, error="Backend was stopped before the job completed.")


def update_job(job_id, **fields):
    if not fields:
        return
    assignments = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [job_id]
    with db() as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id=?", values)


def run_process_job(job_id, command, env, log_path):
    update_job(job_id, status="running", started_at=utc_now(), log_file=str(log_path))
    process = None
    try:
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                start_new_session=(os.name != "nt"),
            )
            with PROCESS_LOCK:
                ACTIVE_PROCESSES[job_id] = process
            while process.poll() is None:
                threading.Event().wait(0.25)
            rc = process.returncode
        with PROCESS_LOCK:
            was_cancelled = job_id in CANCELLED_JOBS
            ACTIVE_PROCESSES.pop(job_id, None)
            CANCELLED_JOBS.discard(job_id)
        if was_cancelled:
            update_job(job_id, status="cancelled", finished_at=utc_now(), exit_code=rc, error="Stopped from dashboard.")
        else:
            update_job(job_id, status="success" if rc == 0 else "failed", finished_at=utc_now(), exit_code=rc)
    except Exception as exc:
        with PROCESS_LOCK:
            ACTIVE_PROCESSES.pop(job_id, None)
            was_cancelled = job_id in CANCELLED_JOBS
            CANCELLED_JOBS.discard(job_id)
        update_job(job_id, status="cancelled" if was_cancelled else "failed", finished_at=utc_now(), exit_code=-15 if was_cancelled else -1, error="Stopped from dashboard." if was_cancelled else str(exc))


def start_generation(account, source_url):
    job_id = uuid.uuid4().hex[:12]
    log_path = LOGS / f"dashboard_{job_id}.log"
    with db() as conn:
        conn.execute(
            """INSERT INTO jobs
               (id,created_at,account_id,platform,selected_files,status,job_type,source_url)
               VALUES (?,?,?,?,?,?,?,?)""",
            (job_id, utc_now(), account["id"], "youtube", "[]", "queued", "generate", source_url),
        )

    env = os.environ.copy()
    env["YT_AUTO_BOT_SOURCE_MODE"] = "youtube"
    env["YT_AUTO_BOT_YOUTUBE_URL"] = source_url
    env["YT_AUTO_BOT_ACCOUNT_ID"] = account["id"]
    env["YT_AUTO_BOT_ACCOUNT_NAME"] = account.get("name", account["id"])
    env["YT_AUTO_BOT_PAUSE"] = "0"
    env["PYTHONUNBUFFERED"] = "1"

    thread = threading.Thread(
        target=run_process_job,
        args=(job_id, [sys.executable, str(ROOT / "main.py")], env, log_path),
        daemon=True,
    )
    thread.start()
    return job_id


def start_upload(platform, account, selected, dry_run=False, approved_report=None):
    job_id = uuid.uuid4().hex[:12]
    report_path = REPORTS / f"dashboard_review_{job_id}.json" if dry_run else None
    job_type = "prepare" if dry_run else "upload"
    with db() as conn:
        conn.execute(
            """INSERT INTO jobs
               (id,created_at,account_id,platform,selected_files,status,job_type,report_file)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                job_id, utc_now(), account["id"], platform,
                json.dumps(selected), "queued", job_type,
                str(report_path.resolve()) if report_path else None,
            ),
        )

    if platform != "youtube":
        update_job(
            job_id,
            status="failed",
            finished_at=utc_now(),
            exit_code=-1,
            error="Instagram publishing is not configured yet.",
        )
        return job_id

    log_path = LOGS / f"dashboard_{job_id}.log"
    env = os.environ.copy()
    env["YT_AUTO_BOT_TOKEN_FILE"] = str((ROOT / account["token_file"]).resolve())
    env["YT_AUTO_BOT_UPLOAD_LOG"] = str(account_log_path(account).resolve())
    env["YT_AUTO_BOT_ACCOUNT_NAME"] = account.get("name", account["id"])
    env["YT_AUTO_BOT_SELECTED_FILES"] = os.pathsep.join(selected)
    if dry_run:
        env["YT_AUTO_BOT_DRY_RUN"] = "1"
        env["YT_AUTO_BOT_DRY_RUN_REPORT"] = str(report_path.resolve())
        env["YT_AUTO_BOT_AUTO_UPLOAD"] = "0"
    else:
        env["YT_AUTO_BOT_AUTO_UPLOAD"] = "1"
    if approved_report:
        env["YT_AUTO_BOT_APPROVED_REPORT"] = str(Path(approved_report).resolve())
    env["YT_AUTO_BOT_PAUSE"] = "0"
    env["PYTHONUNBUFFERED"] = "1"

    thread = threading.Thread(
        target=run_process_job,
        args=(job_id, [sys.executable, str(ROOT / "youtube_automator.py")], env, log_path),
        daemon=True,
    )
    thread.start()
    return job_id


def stop_job(job_id):
    with PROCESS_LOCK:
        process = ACTIVE_PROCESSES.get(job_id)
        if not process:
            return False, "Job is no longer running."
        if process.poll() is not None:
            ACTIVE_PROCESSES.pop(job_id, None)
            return False, "Job has already finished."
        CANCELLED_JOBS.add(job_id)
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True)
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except Exception as exc:
        with PROCESS_LOCK:
            CANCELLED_JOBS.discard(job_id)
        return False, str(exc)
    update_job(job_id, status="cancelled", finished_at=utc_now(), exit_code=-15, error="Stopped from dashboard.")
    return True, "Job stopped."


def delete_shorts(paths):
    """Delete selected rendered Shorts and their local derivative metadata.

    Removes the MP4, exact manifest, matching caption SRTs, and upload-log
    entries. Source downloads/transcripts are deliberately retained so a
    future regeneration can reuse the expensive transcription cache.
    """
    valid=[]
    for raw in paths:
        p=safe_output_file(raw)
        if p: valid.append(p)
    if not valid: return {"deleted":[],"errors":[]}
    targets={str(p.resolve()) for p in valid}
    # Derive the historical clip id as a fallback for Shorts created before
    # manifests were introduced.
    clip_ids=set()
    for p in valid:
        m=re.search(r"short_(\d+)$", p.stem, re.I)
        if m and p.parent.parent.name:
            clip_ids.add(f"{p.parent.parent.name}_clip_{int(m.group(1)):02d}")
    # Never delete a file currently used by an active upload/generation job.
    for j in job_rows():
        if j["status"] in {"running","queued"}:
            files=JSONSafe(j.get("selected_files")) if isinstance(j.get("selected_files"),str) else []
            if any(str(Path(x).resolve()) in targets for x in (files or [])):
                raise RuntimeError(f"Cannot delete a Short while job {j['id']} is running or queued.")
    deleted=[]; errors=[]
    for p in valid:
        try:
            manifest=p.with_suffix(".manifest.json")
            if manifest.exists():
                try:
                    data=json.loads(manifest.read_text(encoding="utf-8"))
                    cid=str(data.get("clip_id") or data.get("clip",{}).get("clip_id") or "")
                    if cid: clip_ids.add(cid)
                except Exception: pass
            p.unlink(missing_ok=True)
            if manifest.exists(): manifest.unlink(missing_ok=True)
            deleted.append(str(p))
        except Exception as exc: errors.append({"path":str(p),"error":str(exc)})
    # Remove caption derivatives by exact clip id; legacy index names are also
    # removed when the filename contains the source/run-derived clip id.
    for srt in CACHE.glob("youtube_caption_*.srt"):
        if any(re.sub(r"[^A-Za-z0-9_-]+","_",cid) in srt.name for cid in clip_ids):
            try:srt.unlink()
            except Exception as exc:errors.append({"path":str(srt),"error":str(exc)})
    # Remove deleted files from every account upload log so the local duplicate
    # cache cannot retain references to files that no longer exist.
    for account in load_accounts().get("accounts",[]):
        path=account_log_path(account); data=load_log(account)
        changed=False
        for key in list(data):
            if str(Path(key).resolve()) in targets:
                data.pop(key,None); changed=True
        if changed:
            path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    # Remove dashboard execution logs whose job referenced one of the deleted
    # Shorts. The SQLite history itself remains intact for auditability.
    for j in job_rows():
        raw=j.get("selected_files") or "[]"
        files=JSONSafe(raw) if isinstance(raw,str) else []
        if files and any(str(Path(x).resolve()) in targets for x in files):
            lp=j.get("log_file")
            if lp:
                try: Path(lp).unlink(missing_ok=True)
                except Exception as exc: errors.append({"path":str(lp),"error":str(exc)})

    # Remove now-empty run selection files associated with deleted output runs.
    for p in valid:
        parent=p.parent
        if not list(parent.glob("short_*.mp4")):
            m=re.match(r"selected_(.+)_(\d{8}_\d{6}_\d+)\.json$", "")
            for sel in CACHE.glob("selected_*.json"):
                try:
                    if parent.name in sel.name and not list(parent.glob("short_*.mp4")): sel.unlink()
                except Exception: pass
    return {"deleted":deleted,"errors":errors}


def JSONSafe(value):
    try:return json.loads(value)
    except Exception:return None


def json_response(handler, data, code=200):
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    try:
        handler.wfile.write(raw)
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
        pass


def safe_output_file(raw_path):
    try:
        path = Path(raw_path).resolve()
        path.relative_to(OUTPUT.resolve())
        if path.is_file() and path.suffix.lower() == ".mp4":
            return path
    except Exception:
        pass
    return None


def safe_report_file(raw_path):
    try:
        path = Path(raw_path).resolve()
        path.relative_to(REPORTS.resolve())
        if path.is_file() and path.suffix.lower() == ".json":
            return path
    except Exception:
        pass
    return None


def review_job(job_id):
    row = next((x for x in job_rows() if x["id"] == job_id), None)
    if not row or row.get("job_type") != "prepare":
        return None, "Review job not found."
    if row.get("status") != "success":
        return row, None
    path = safe_report_file(row.get("report_file"))
    if not path:
        return row, "Review report is missing."
    report = JSONSafe(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        return row, "Review report is invalid."
    row["report"] = report
    return row, None


def approve_review(account, review_job_id, edits):
    row, error = review_job(review_job_id)
    if error:
        raise ValueError(error)
    if not row or row.get("status") != "success":
        raise ValueError("The review is not ready yet.")
    if row.get("account_id") != account.get("id"):
        raise ValueError("The review belongs to a different account.")

    report = row["report"]
    items = report.get("items") or []
    edit_map = {
        str(Path(item.get("video_path", "")).resolve()): item
        for item in (edits or [])
        if isinstance(item, dict) and item.get("video_path")
    }
    approved_items = []
    for item in items:
        if not isinstance(item, dict) or not item.get("validation", {}).get("passed"):
            continue
        video_path = str(Path(item.get("video_path", "")).resolve())
        if not safe_output_file(video_path):
            raise ValueError("A reviewed Short is no longer available.")
        edit = edit_map.get(video_path, {})
        request = (item.get("planned_api_requests") or {}).get("videos.insert") or {}
        body = request.get("body") or {}
        snippet = body.get("snippet") or {}
        status = body.get("status") or {}

        title = str(edit.get("title", snippet.get("title", ""))).strip()
        description = str(edit.get("description", snippet.get("description", ""))).strip()
        raw_tags = edit.get("tags", snippet.get("tags", []))
        if not isinstance(raw_tags, list):
            raise ValueError(f"Tags must be a list for {Path(video_path).name}.")
        tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
        visibility = str(edit.get("visibility", "scheduled" if status.get("publishAt") else status.get("privacyStatus", "private"))).lower()
        if not title or len(title) > 100:
            raise ValueError(f"Title must be 1-100 characters for {Path(video_path).name}.")
        if not description or len(description) > 5000:
            raise ValueError(f"Description must be 1-5000 characters for {Path(video_path).name}.")
        if not tags:
            raise ValueError(f"At least one tag is required for {Path(video_path).name}.")
        if visibility not in {"scheduled", "private", "public"}:
            raise ValueError("Visibility must be scheduled, private, or public.")
        if visibility == "scheduled" and not status.get("publishAt"):
            raise ValueError("This review has no scheduled time to preserve.")

        snippet.update({"title": title, "description": description, "tags": tags})
        if visibility == "scheduled":
            status["privacyStatus"] = "private"
        else:
            status = {
                "privacyStatus": visibility,
                "selfDeclaredMadeForKids": False,
            }
        body["snippet"] = snippet
        body["status"] = status
        request["body"] = body
        item["planned_api_requests"]["videos.insert"] = request
        item["planned_action"] = (
            "SCHEDULED -> PUBLIC" if visibility == "scheduled"
            else ("PUBLIC NOW" if visibility == "public" else "PRIVATE")
        )
        item["planned_publish_at"] = status.get("publishAt")
        if isinstance(item.get("metadata"), dict):
            item["metadata"].update({
                "title": title,
                "description": description,
                "tags": tags,
                "privacyStatus": status["privacyStatus"],
            })
        approved_items.append(item)

    if not approved_items:
        raise ValueError("No validated Shorts are available to approve.")
    approved_path = REPORTS / f"approved_{uuid.uuid4().hex[:12]}.json"
    approved_report = dict(report)
    approved_report.update({
        "approved": True,
        "approved_at": utc_now(),
        "source_review_job_id": review_job_id,
        "items": approved_items,
    })
    approved_path.write_text(
        json.dumps(approved_report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    selected = [item["video_path"] for item in approved_items]
    return start_upload("youtube", account, selected, approved_report=approved_path)


def valid_youtube_url(url):
    return bool(re.match(r"^https?://(www\.)?(youtube\.com|youtu\.be)/", url, re.I))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        reconcile_stale_jobs()
        parsed = urlparse(self.path)

        if parsed.path == "/api/state":
            accounts = load_accounts().get("accounts", [])
            videos = all_videos()
            for video in videos:
                video["uploaded_accounts"] = [
                    account["id"] for account in accounts
                    if video["path"] in load_log(account)
                ]
            jobs = job_rows()
            json_response(self, {
                "accounts": accounts,
                "videos": videos,
                "jobs": jobs,
                "stats": {
                    "videos": len(videos),
                    "uploaded": sum(bool(v["uploaded_accounts"]) for v in videos),
                    "pending": sum(not v["uploaded_accounts"] for v in videos),
                    "running": sum(j["status"] == "running" for j in jobs),
                    "generating": sum(j["job_type"] == "generate" and j["status"] == "running" for j in jobs),
                },
            })
            return

        if parsed.path == "/api/log":
            job_id = parse_qs(parsed.query).get("id", [""])[0]
            row = next((x for x in job_rows() if x["id"] == job_id), None)
            if not row:
                json_response(self, {"error": "Job not found"}, 404)
                return
            log = ""
            if row.get("log_file") and Path(row["log_file"]).exists():
                log = Path(row["log_file"]).read_text(encoding="utf-8", errors="replace")
            json_response(self, {"job": row, "log": log})
            return

        if parsed.path == "/api/review":
            job_id = parse_qs(parsed.query).get("id", [""])[0]
            row, error = review_job(job_id)
            if not row:
                return json_response(self, {"error": error}, 404)
            if error:
                return json_response(self, {"error": error, "job": row}, 409)
            if row.get("status") in {"queued", "running"}:
                return json_response(self, {"ready": False, "job": row}, 202)
            if row.get("status") != "success":
                return json_response(
                    self,
                    {"error": row.get("error") or "Review preparation failed.", "job": row},
                    409,
                )
            return json_response(self, {"ready": True, "job": row, "report": row["report"]})

        if parsed.path == "/media":
            raw = parse_qs(parsed.query).get("path", [""])[0]
            path = safe_output_file(raw)
            if not path:
                self.send_error(404)
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass
            return

        if parsed.path in {"/", "/index.html"}:
            return self.serve(INDEX, "text/html; charset=utf-8")
        if parsed.path == "/style.css":
            return self.serve(STYLE, "text/css; charset=utf-8")
        if parsed.path == "/app.js":
            return self.serve(APPJS, "application/javascript; charset=utf-8")
        self.send_error(404)

    def serve(self, path, content_type):
        if not path.exists():
            self.send_error(404, "Dashboard file missing")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in {
            "/api/upload", "/api/prepare", "/api/approve",
            "/api/generate", "/api/stop", "/api/delete",
        }:
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if parsed.path == "/api/stop":
                ok, message = stop_job(str(body.get("job_id", "")))
                return json_response(self, {"ok": ok, "message": message}, 200 if ok else 409)
            if parsed.path == "/api/delete":
                result = delete_shorts(body.get("files", []))
                return json_response(self, {"ok": True, **result})

            account = account_by_id(body.get("account_id"))
            if not account:
                return json_response(self, {"error": "Unknown account"}, 400)

            if parsed.path == "/api/approve":
                if account.get("platform") != "youtube":
                    return json_response(self, {"error": "Only YouTube reviews can be approved."}, 400)
                job_id = approve_review(
                    account,
                    str(body.get("review_job_id", "")),
                    body.get("items", []),
                )
                return json_response(self, {"ok": True, "job_id": job_id})

            if parsed.path == "/api/generate":
                if account.get("platform") != "youtube":
                    return json_response(self, {"error": "Short generation currently uses a YouTube source and must be assigned to a YouTube account."}, 400)
                url = str(body.get("url", "")).strip()
                if not valid_youtube_url(url):
                    return json_response(self, {"error": "Enter a valid YouTube URL."}, 400)
                if any(j["status"] == "running" and j["job_type"] == "generate" for j in job_rows()):
                    return json_response(self, {"error": "Another Short generation job is already running. Wait for it to finish."}, 409)
                job_id = start_generation(account, url)
                return json_response(self, {"ok": True, "job_id": job_id})

            platform = body.get("platform", "youtube")
            selected = [str(Path(x).resolve()) for x in body.get("files", [])]
            if not selected:
                return json_response(self, {"error": "Select at least one Short."}, 400)
            if platform != account.get("platform"):
                return json_response(self, {"error": "Platform and account do not match."}, 400)
            valid_set = {str(p.resolve()) for p in OUTPUT.rglob("short_*.mp4")}
            selected = [x for x in selected if x in valid_set]
            if not selected:
                return json_response(self, {"error": "Selected files are no longer valid output Shorts."}, 400)
            job_id = start_upload(
                platform,
                account,
                selected,
                dry_run=parsed.path == "/api/prepare",
            )
            return json_response(self, {"ok": True, "job_id": job_id})
        except Exception as exc:
            return json_response(self, {"error": str(exc)}, 400)


class LocalDashboardServer(ThreadingHTTPServer):
    allow_reuse_address = False


def main():
    reconcile_stale_jobs()
    for p in (INDEX, STYLE, APPJS):
        if not p.exists():
            raise SystemExit(f"Missing dashboard asset: {p}")
    db().close()
    server = LocalDashboardServer((HOST, PORT), Handler)
    print("=" * 64)
    print("YT AUTO BOT DASHBOARD")
    print("=" * 64)
    print(f"Open: http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
