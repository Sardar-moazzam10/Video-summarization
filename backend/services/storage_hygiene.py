"""
Storage hygiene service - Automated cleanup and retention enforcement.
Prevents disk exhaustion from interrupted ffmpeg scratch folders,
orphaned download directories, and unbounded highlight reels.
"""

import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

try:
    from ..core.config import get_settings
except Exception:
    get_settings = None


def cleanup_temp_scratch(max_age_minutes: int = 30) -> Dict[str, Any]:
    """
    Remove orphaned FFmpeg highlight scratch directories from /tmp.
    Only removes directories older than max_age_minutes to ensure no
    actively running FFmpeg job is disrupted.
    """
    temp_dir = tempfile.gettempdir()
    cleaned_count = 0
    freed_bytes = 0
    now = time.time()
    cutoff_seconds = max_age_minutes * 60

    try:
        for entry in os.listdir(temp_dir):
            if not entry.startswith("highlight_"):
                continue
            full_path = os.path.join(temp_dir, entry)
            if not os.path.isdir(full_path):
                continue

            try:
                mtime = os.path.getmtime(full_path)
                if now - mtime > cutoff_seconds:
                    # Calculate directory size before removal
                    dir_size = 0
                    for root, _, files in os.walk(full_path):
                        for f in files:
                            try:
                                dir_size += os.path.getsize(os.path.join(root, f))
                            except Exception:
                                pass
                    shutil.rmtree(full_path, ignore_errors=True)
                    cleaned_count += 1
                    freed_bytes += dir_size
            except Exception as e:
                print(f"[StorageHygiene] Failed to clean temp dir {full_path}: {e}")
    except Exception as e:
        print(f"[StorageHygiene] Error listing temp directory: {e}")

    return {
        "cleaned_dirs": cleaned_count,
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
    }


def cleanup_download_scratch(
    max_age_minutes: int = 30,
    base_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Remove orphaned job directories in audio_cache/video_downloads/.
    These are created during source acquisition and are meant to be deleted
    in finally: blocks; if a process crashes, they are safely reaped here.
    """
    dl_dir = base_dir or Path("audio_cache/video_downloads")
    cleaned_count = 0
    freed_bytes = 0
    now = time.time()
    cutoff_seconds = max_age_minutes * 60

    if not dl_dir.exists() or not dl_dir.is_dir():
        return {"cleaned_dirs": 0, "freed_mb": 0.0}

    try:
        for item in dl_dir.iterdir():
            if not item.is_dir():
                continue
            try:
                mtime = item.stat().st_mtime
                if now - mtime > cutoff_seconds:
                    dir_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                    shutil.rmtree(str(item), ignore_errors=True)
                    cleaned_count += 1
                    freed_bytes += dir_size
            except Exception as e:
                print(f"[StorageHygiene] Failed to clean download dir {item}: {e}")
    except Exception as e:
        print(f"[StorageHygiene] Error reading download cache dir: {e}")

    return {
        "cleaned_dirs": cleaned_count,
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
    }


def prune_highlights_cache(
    max_size_gb: float = 10.0,
    max_age_days: int = 14,
    highlights_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Enforce LRU eviction and age limits on rendered highlight MP4s in audio_cache/highlights/.
    Ensures that accumulated highlight reels never exceed disk quota.
    """
    target_dir = highlights_dir or Path("audio_cache/highlights")
    if not target_dir.exists() or not target_dir.is_dir():
        return {"removed_count": 0, "freed_mb": 0.0, "remaining_count": 0, "remaining_mb": 0.0}

    files = []
    total_size = 0

    try:
        for f in target_dir.iterdir():
            if f.is_file() and not f.name.startswith("."):
                try:
                    stat = f.stat()
                    total_size += stat.st_size
                    files.append({
                        "path": f,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                        "name": f.name
                    })
                except Exception:
                    pass
    except Exception as e:
        print(f"[StorageHygiene] Error listing highlights directory: {e}")
        return {"removed_count": 0, "freed_mb": 0.0, "remaining_count": 0, "remaining_mb": 0.0}

    # Sort oldest first (LRU order based on modification/creation time)
    files.sort(key=lambda x: x["mtime"])

    max_size_bytes = max_size_gb * 1024 * 1024 * 1024
    cutoff_time = time.time() - (max_age_days * 86400)
    removed_count = 0
    freed_bytes = 0

    for entry in files:
        should_remove = False
        # Condition 1: Older than max age
        if entry["mtime"] < cutoff_time:
            should_remove = True
        # Condition 2: Over quota size limit (evict oldest until under budget)
        elif total_size > max_size_bytes:
            should_remove = True

        if should_remove:
            try:
                entry["path"].unlink(missing_ok=True)
                removed_count += 1
                freed_bytes += entry["size"]
                total_size -= entry["size"]

                # Clean matching extracted audio if present
                job_name = entry["name"]
                if job_name.startswith("highlight_") and job_name.endswith(".mp4"):
                    job_id = job_name[len("highlight_"):-4]
                    companion_audio = target_dir.parent / f"summary_{job_id}.mp3"
                    if companion_audio.exists():
                        try:
                            companion_audio.unlink(missing_ok=True)
                        except Exception:
                            pass
            except Exception as e:
                print(f"[StorageHygiene] Could not remove highlight {entry['path']}: {e}")

    remaining_count = len(files) - removed_count
    return {
        "removed_count": removed_count,
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
        "remaining_count": remaining_count,
        "remaining_mb": round(total_size / (1024 * 1024), 2),
    }


def enforce_video_cache_limit() -> Dict[str, Any]:
    """
    Invoke the VideoCacheManager LRU cleaner to keep audio_cache/video_cache/ under quota.
    """
    try:
        from video_cache_manager import get_video_cache_manager
        manager = get_video_cache_manager()
        return manager.cleanup_old_cache()
    except Exception as e:
        print(f"[StorageHygiene] Video cache manager cleanup failed: {e}")
        return {"error": str(e)}


def run_storage_hygiene() -> Dict[str, Any]:
    """
    Run the full suite of storage hygiene checks.
    Invoked during startup, periodic intervals, and after job completion.
    """
    max_size_gb = 10.0
    max_age_days = 14
    scratch_age_minutes = 30

    if get_settings:
        try:
            settings = get_settings()
            max_size_gb = getattr(settings, "HIGHLIGHTS_MAX_SIZE_GB", 10.0)
            max_age_days = getattr(settings, "HIGHLIGHTS_MAX_AGE_DAYS", 14)
            scratch_age_minutes = getattr(settings, "TEMP_SCRATCH_MAX_AGE_MINUTES", 30)
        except Exception:
            pass

    temp_res = cleanup_temp_scratch(max_age_minutes=scratch_age_minutes)
    dl_res = cleanup_download_scratch(max_age_minutes=scratch_age_minutes)
    hl_res = prune_highlights_cache(max_size_gb=max_size_gb, max_age_days=max_age_days)
    vc_res = enforce_video_cache_limit()

    return {
        "temp_scratch": temp_res,
        "download_scratch": dl_res,
        "highlights": hl_res,
        "video_cache": vc_res,
    }
