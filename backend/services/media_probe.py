"""
Source media duration probe.

Answers one question: how long is the actual video?

This is deliberately separate from transcript length. A transcript ends at the
last caption cue, which is not the end of the media — measured on
aircAruvnKk the captions end at 1105s while the media runs 1120s, a 15-second
gap. Validating a requested summary length against caption length would
therefore accept or reject requests on the wrong number, so the media duration
is resolved directly from the source.

yt-dlp is asked for metadata only (--skip-download), which costs one HTTP
round trip (~3s measured) and no disk. Results are cached per process because
the duration of a published video does not change.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import time
from typing import Dict, List, Optional

# video_id -> (duration_seconds, fetched_at_monotonic)
_CACHE: Dict[str, tuple] = {}
_CACHE_TTL_SECONDS = 24 * 3600

DEFAULT_PROBE_TIMEOUT = 20.0


def _ytdlp_cmd() -> Optional[List[str]]:
    """
    Command prefix for yt-dlp, or None when it is unavailable.

    Prefers `<current interpreter> -m yt_dlp` so the venv's package is used
    whether or not venv/bin is on PATH; falls back to a PATH lookup for
    installs that ship the standalone binary (e.g. the Docker image).
    """
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    exe = shutil.which("yt-dlp")
    return [exe] if exe else None


def get_video_duration_seconds(
    video_id: str,
    timeout: float = DEFAULT_PROBE_TIMEOUT,
) -> Optional[float]:
    """
    Real media duration in seconds, or None when it cannot be determined.

    None is a meaningful answer, not an error to swallow: the caller has to
    decide what to do when the source length is unknown, and silently
    substituting a guess is what this module exists to avoid.
    """
    if not video_id:
        return None

    cached = _CACHE.get(video_id)
    if cached and (time.monotonic() - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    cmd = _ytdlp_cmd()
    if cmd is None:
        print("[MediaProbe] yt-dlp unavailable — cannot resolve duration")
        return None

    try:
        proc = subprocess.run(
            cmd + [
                "--no-warnings", "--quiet", "--no-playlist",
                "--skip-download", "--print", "duration",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"[MediaProbe] timed out after {timeout}s for {video_id}")
        return None
    except Exception as exc:
        print(f"[MediaProbe] probe failed for {video_id}: {type(exc).__name__}")
        return None

    raw = (proc.stdout or "").strip().splitlines()
    if not raw:
        print(f"[MediaProbe] no duration returned for {video_id}")
        return None

    try:
        duration = float(raw[0].strip())
    except (TypeError, ValueError):
        print(f"[MediaProbe] unparseable duration {raw[0]!r} for {video_id}")
        return None

    # A live stream or a failed extraction can report 0; that is "unknown",
    # not "zero-length", and must not be treated as a real measurement.
    if duration <= 0:
        return None

    _CACHE[video_id] = (duration, time.monotonic())
    return duration


def get_durations(video_ids: List[str], timeout: float = DEFAULT_PROBE_TIMEOUT) -> Dict[str, Optional[float]]:
    """Duration per video id; the value is None where it could not be resolved."""
    return {vid: get_video_duration_seconds(vid, timeout=timeout) for vid in video_ids}


def format_duration(seconds: float) -> str:
    """`320` -> `5m 20s`, matching the wording used in user-facing errors."""
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    if minutes and secs:
        return f"{minutes}m {secs}s"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"


def prime_duration_cache(video_id: str, duration_seconds: Optional[float]) -> None:
    """Trust and reuse verified YouTube Data API contentDetails duration."""
    if video_id and duration_seconds and float(duration_seconds) > 0:
        _CACHE[video_id] = (float(duration_seconds), time.monotonic())


def clear_cache() -> None:
    _CACHE.clear()
