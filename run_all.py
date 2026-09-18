"""Run the full YT Auto Bot pipeline: edit -> source intelligence -> upload."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable


def run(script: str, env: dict[str, str]) -> int:
    print("\n" + "=" * 70)
    print(f"RUNNING {script}")
    print("=" * 70)
    result = subprocess.run([PYTHON, str(PROJECT_DIR / script)], cwd=PROJECT_DIR, env=env)
    return result.returncode


def main() -> int:
    env = os.environ.copy()
    env.setdefault("YT_AUTO_BOT_PAUSE", "0")

    mode = "".join(sys.argv[1:2]).lower()
    if mode in {"local", "--local"}:
        env["YT_AUTO_BOT_SOURCE_MODE"] = "local"
        env["YT_AUTO_BOT_AUTO_LOCAL"] = "1"
    elif mode.startswith("http://") or mode.startswith("https://"):
        env["YT_AUTO_BOT_SOURCE_MODE"] = "youtube"
        env["YT_AUTO_BOT_YOUTUBE_URL"] = mode
    elif mode in {"youtube", "--youtube"}:
        url = input("YouTube URL: ").strip()
        env["YT_AUTO_BOT_SOURCE_MODE"] = "youtube"
        env["YT_AUTO_BOT_YOUTUBE_URL"] = url
    else:
        print("Usage:")
        print("  python run_all.py local")
        print("  python run_all.py <YouTube URL>")
        print("  python run_all.py youtube")
        print("\nThe last form prompts for a URL.")
        return 2

    # Keep uploads interactive unless the user explicitly opts into unattended mode.
    if os.environ.get("YT_AUTO_BOT_AUTO_UPLOAD") == "1":
        env["YT_AUTO_BOT_AUTO_UPLOAD"] = "1"

    code = run("main.py", env)
    if code != 0:
        print(f"main.py failed with exit code {code}.")
        return code

    code = run("youtube_automator.py", env)
    if code != 0:
        print(f"youtube_automator.py failed with exit code {code}.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
