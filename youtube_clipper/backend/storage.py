"""Conservative storage inventory: only recognized, disposable files qualify."""

import os
import re
import shutil
import time
from pathlib import Path


def inventory(root, min_age_days=30):
    if isinstance(min_age_days, bool) or not isinstance(min_age_days, int) or not 0 <= min_age_days <= 3650:
        raise ValueError("Age must be a whole number between 0 and 3650 days.")
    root = Path(root).resolve()
    cutoff = time.time() - min_age_days * 86400
    groups = {name: {"bytes": 0, "files": 0} for name in ("output", "cache", "input", "logs")}
    candidates = []
    errors = []
    for name, totals in groups.items():
        base = root / name
        if not base.exists() or base.is_symlink() or base.resolve() != base:
            continue
        for directory, dirs, files in os.walk(base, followlinks=False):
            # Also exclude Windows junctions and other redirected directories.
            dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()
                       and (Path(directory) / d).resolve() == Path(directory) / d]
            for filename in files:
                path = Path(directory) / filename
                if path.is_symlink() or path.resolve() != path:
                    continue
                try:
                    stat = path.stat()
                    totals["bytes"] += stat.st_size
                    totals["files"] += 1
                    relative = path.relative_to(root)
                    category = None
                    if name == "output" and re.fullmatch(r"short_\d+\.(?:source|clean)\.mp4", filename, re.I):
                        category = "masters"
                    elif name == "cache" and len(relative.parts) > 2 and relative.parts[1] == "render" and re.fullmatch(r"(?:cropped|fullframe)_\d+\.mp4", filename):
                        category = "scratch"
                    if category and stat.st_mtime <= cutoff:
                        candidates.append({"path": relative.as_posix(), "category": category,
                                           "bytes": stat.st_size, "mtime_ns": str(stat.st_mtime_ns)})
                except OSError as exc:
                    errors.append({"path": str(path.relative_to(root)), "error": str(exc)})
    disk = shutil.disk_usage(root)
    return {"groups": groups, "disk": {"total": disk.total, "free": disk.free},
            "candidates": sorted(candidates, key=lambda x: x["path"]), "errors": errors}


def cleanup(root, selected, min_age_days=30):
    """Revalidate a reviewed snapshot; never accept arbitrary filesystem paths."""
    if not isinstance(selected, list) or not selected:
        raise ValueError("Select at least one file to clean up.")
    current = {item["path"]: item for item in inventory(root, min_age_days)["candidates"]}
    validated = []
    seen = set()
    for item in selected:
        if not isinstance(item, dict) or item.get("path") not in current:
            raise ValueError("A selected file is no longer eligible. Refresh the storage preview.")
        fresh = current[item["path"]]
        if fresh != item:
            raise ValueError("A selected file has changed. Refresh the storage preview.")
        if item["path"] not in seen:
            validated.append(fresh)
            seen.add(item["path"])
    deleted, errors, freed = [], [], 0
    root = Path(root).resolve()
    for item in validated:
        path = root / item["path"]
        try:
            if path.resolve() != path or path.is_symlink():
                raise ValueError("File location changed.")
            stat = path.stat()
            if str(stat.st_mtime_ns) != item["mtime_ns"] or stat.st_size != item["bytes"]:
                raise ValueError("File changed since preview.")
            path.unlink()
            deleted.append(item["path"])
            freed += item["bytes"]
        except (OSError, ValueError) as exc:
            errors.append({"path": item["path"], "error": str(exc)})
    return {"deleted": deleted, "freed_bytes": freed, "errors": errors}
