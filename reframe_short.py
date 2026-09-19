"""Re-render a generated Short from its retained full-frame editing master."""

from __future__ import annotations

import json
import math
import os
import subprocess
import uuid
from pathlib import Path

import config as bot_config


OUTPUT = bot_config.OUTPUT_DIR.resolve()
WIDTH = 1080
HEIGHT = 1920


def _inside_output(raw_path, *, suffix=None):
    path = Path(raw_path).resolve()
    path.relative_to(OUTPUT)
    if suffix and path.suffix.lower() != suffix:
        raise ValueError(f"Expected a {suffix} file.")
    return path


def crop_geometry(source_width, source_height, center_x, center_y, zoom):
    """Return a clamped 9:16 crop rectangle in source pixels."""
    if source_width < 2 or source_height < 2:
        raise ValueError("The editing master has invalid dimensions.")
    center_x, center_y, zoom = normalize_framing(center_x, center_y, zoom)

    crop_height = source_height / zoom
    crop_width = crop_height * 9 / 16
    if crop_width > source_width:
        crop_width = source_width / zoom
        crop_height = crop_width * 16 / 9

    crop_width = max(2, min(source_width, int(round(crop_width))))
    crop_height = max(2, min(source_height, int(round(crop_height))))
    left = int(round(source_width * center_x - crop_width / 2))
    top = int(round(source_height * center_y - crop_height / 2))
    left = max(0, min(source_width - crop_width, left))
    top = max(0, min(source_height - crop_height, top))
    return left, top, crop_width, crop_height


def normalize_framing(center_x, center_y, zoom):
    try:
        values = [float(center_x), float(center_y), float(zoom)]
    except (TypeError, ValueError) as exc:
        raise ValueError("Framing values must be numbers.") from exc
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Framing values must be finite numbers.")
    return (
        min(1.0, max(0.0, values[0])),
        min(1.0, max(0.0, values[1])),
        min(3.0, max(1.0, values[2])),
    )


def reframe_short(video_path, center_x, center_y, zoom):
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "OpenCV is required for manual framing. Install the project requirements first."
        ) from exc

    center_x, center_y, zoom = normalize_framing(center_x, center_y, zoom)
    output_file = _inside_output(video_path, suffix=".mp4")
    if not output_file.is_file() or not output_file.name.lower().endswith(".mp4"):
        raise ValueError("The selected Short no longer exists.")

    manifest_path = output_file.with_suffix(".manifest.json")
    if not manifest_path.is_file():
        raise ValueError("This Short has no editing manifest. Regenerate it first.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_master = _inside_output(manifest.get("source_master_file", ""), suffix=".mp4")
    if not source_master.is_file():
        raise ValueError("The full-frame editing master is missing. Regenerate this Short.")

    caption_file = Path(manifest.get("caption_file", "")).resolve()
    try:
        caption_file.relative_to(bot_config.PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("The caption file is outside the project folder.") from exc
    if not caption_file.is_file():
        raise ValueError("The caption layout is missing. Regenerate this Short.")

    cap = cv2.VideoCapture(str(source_master))
    source_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    source_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if not cap.isOpened() or source_width < 2 or source_height < 2:
        cap.release()
        raise ValueError("The full-frame editing master could not be opened.")

    left, top, crop_width, crop_height = crop_geometry(
        source_width, source_height, center_x, center_y, zoom
    )
    token = uuid.uuid4().hex[:10]
    cropped_temp = output_file.with_name(f".{output_file.stem}.{token}.video.mp4")
    final_temp = output_file.with_name(f".{output_file.stem}.{token}.final.mp4")
    writer = cv2.VideoWriter(
        str(cropped_temp), cv2.VideoWriter_fourcc(*"mp4v"), fps, (WIDTH, HEIGHT)
    )
    if not writer.isOpened():
        cap.release()
        raise ValueError("Could not create the manually framed video.")

    frames = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            cropped = frame[top:top + crop_height, left:left + crop_width]
            resized = cv2.resize(cropped, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
            writer.write(resized)
            frames += 1
    finally:
        cap.release()
        writer.release()

    if frames == 0:
        cropped_temp.unlink(missing_ok=True)
        raise ValueError("No frames could be decoded from the editing master.")

    try:
        relative_caption = caption_file.relative_to(bot_config.PROJECT_ROOT).as_posix()
        command = [
            bot_config.FFMPEG,
            "-y",
            "-i", str(cropped_temp),
            "-i", str(output_file),
            "-vf", f"ass={relative_caption}",
            "-map", "0:v:0",
            "-map", "1:a:0?",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "19",
            "-c:a", "copy",
            "-shortest",
            "-movflags", "+faststart",
            str(final_temp),
        ]
        result = subprocess.run(
            command,
            cwd=str(bot_config.PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not final_temp.is_file():
            detail = (result.stderr or result.stdout or "FFmpeg failed.")[-1200:]
            raise RuntimeError(detail)
        os.replace(final_temp, output_file)
    finally:
        cropped_temp.unlink(missing_ok=True)
        final_temp.unlink(missing_ok=True)

    manifest["schema_version"] = max(2, int(manifest.get("schema_version", 1)))
    manifest["framing"] = {
        "mode": "manual",
        "center_x": round(float(center_x), 5),
        "center_y": round(float(center_y), 5),
        "zoom": round(float(zoom), 3),
        "crop_pixels": {
            "left": left,
            "top": top,
            "width": crop_width,
            "height": crop_height,
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest["framing"]
