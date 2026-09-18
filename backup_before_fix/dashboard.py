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
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config as bot_config

ROOT = bot_config.PROJECT_ROOT
OUTPUT = bot_config.OUTPUT_DIR
CACHE = bot_config.CACHE_DIR
LOGS = bot_config.LOGS_DIR
DASHBOARD_DIR = ROOT / "dashboard"
ACCOUNTS_FILE = ROOT / "config" / "accounts.json"
DB_FILE = CACHE / "dashboard.db"
HOST = os.environ.get("YT_AUTO_BOT_DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("YT_AUTO_BOT_DASHBOARD_PORT", "8765"))

DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)

INDEX = DASHBOARD_DIR / "index.html"
STYLE = DASHBOARD_DIR / "style.css"
APPJS = DASHBOARD_DIR / "app.js"


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
            source_url TEXT
        )
    """)
    # Backward-compatible migration for the first dashboard version.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    if "job_type" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN job_type TEXT NOT NULL DEFAULT 'upload'")
    if "source_url" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN source_url TEXT")
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


def update_job(job_id, **fields):
    if not fields:
        return
    assignments = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [job_id]
    with db() as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id=?", values)


def run_process_job(job_id, command, env, log_path):
    update_job(job_id, status="running", started_at=utc_now(), log_file=str(log_path))
    try:
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        update_job(
            job_id,
            status="success" if process.returncode == 0 else "failed",
            finished_at=utc_now(),
            exit_code=process.returncode,
        )
    except Exception as exc:
        update_job(
            job_id,
            status="failed",
            finished_at=utc_now(),
            exit_code=-1,
            error=str(exc),
        )


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


def start_upload(platform, account, selected):
    job_id = uuid.uuid4().hex[:12]
    with db() as conn:
        conn.execute(
            """INSERT INTO jobs
               (id,created_at,account_id,platform,selected_files,status,job_type)
               VALUES (?,?,?,?,?,?,?)""",
            (job_id, utc_now(), account["id"], platform, json.dumps(selected), "queued", "upload"),
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
    env["YT_AUTO_BOT_AUTO_UPLOAD"] = "1"
    env["YT_AUTO_BOT_PAUSE"] = "0"
    env["PYTHONUNBUFFERED"] = "1"

    thread = threading.Thread(
        target=run_process_job,
        args=(job_id, [sys.executable, str(ROOT / "youtube_automator.py")], env, log_path),
        daemon=True,
    )
    thread.start()
    return job_id


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


def valid_youtube_url(url):
    return bool(re.match(r"^https?://(www\.)?(youtube\.com|youtu\.be)/", url, re.I))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
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
        if parsed.path not in {"/api/upload", "/api/generate"}:
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            account = account_by_id(body.get("account_id"))
            if not account:
                return json_response(self, {"error": "Unknown account"}, 400)

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
            job_id = start_upload(platform, account, selected)
            return json_response(self, {"ok": True, "job_id": job_id})
        except Exception as exc:
            return json_response(self, {"error": str(exc)}, 400)


def main():
    for p in (INDEX, STYLE, APPJS):
        if not p.exists():
            raise SystemExit(f"Missing dashboard asset: {p}")
    db().close()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("=" * 64)
    print("YT AUTO BOT DASHBOARD")
    print("=" * 64)
    print(f"Open: http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
