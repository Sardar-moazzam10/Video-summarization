"""
Visual Keyframe Extractor — Detects scene boundaries and scores keyframes.

Pipeline:
    1. Detect scene boundaries with PySceneDetect (content-aware).
    2. For each scene, save the middle frame as a JPEG to disk.
    3. Score each keyframe by motion energy within its scene
       (mean of cv2.absdiff between sampled frames).
    4. Return [{timestamp, visual_score, scene_id, frame_path, ...}]
       — consumed by segment_extractor.py to blend into segment selection.

Pure-function module: takes a video file path, returns data + writes JPEGs.
No DB calls, no API calls, no global state.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Dict, Optional


KEYFRAMES_ROOT = Path("audio_cache/keyframes")
MOTION_SAMPLE_FPS = 2.0


def extract_keyframes(
    video_id: str,
    video_path: str,
    output_root: Optional[Path] = None,
    scene_threshold: float = 27.0,
    min_scene_seconds: float = 1.5,
) -> List[Dict]:
    """
    Detect scenes in a video, save one keyframe per scene, score by motion.

    Args:
        video_id: Stable identifier (e.g. YouTube ID) used as the output subdir.
        video_path: Path to the source video file (any format FFmpeg/OpenCV can read).
        output_root: Where to write keyframe JPEGs. Defaults to audio_cache/keyframes/.
        scene_threshold: PySceneDetect ContentDetector threshold. Lower = more scenes.
        min_scene_seconds: Drop scenes shorter than this (likely flicker/noise).

    Returns:
        List of dicts, one per detected scene:
        [{
            "scene_id": int,
            "timestamp": float,        # middle of the scene, seconds
            "start_time": float,
            "end_time": float,
            "visual_score": float,     # 0..1, motion-based
            "frame_path": str,         # absolute path to saved JPEG
        }, ...]

        Empty list on failure (callers must treat the visual stage as optional).
    """
    if not os.path.isfile(video_path):
        print(f"[Keyframes] Video not found: {video_path}")
        return []

    try:
        import cv2
    except ImportError:
        print("[Keyframes] opencv-python-headless not installed — skipping visual stage")
        return []

    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector
    except ImportError:
        print("[Keyframes] scenedetect not installed — skipping visual stage")
        return []

    out_dir = (output_root or KEYFRAMES_ROOT) / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Return cached keyframes if they already exist — avoids re-running
    # scene detection (20-60 min on long videos) on every merge job.
    cached = _load_cached_keyframes(out_dir)
    if cached:
        print(f"[Keyframes] {video_id}: reusing {len(cached)} cached keyframes from {out_dir}")
        return cached

    try:
        scenes = _detect_scenes(video_path, scene_threshold, min_scene_seconds)
    except Exception as e:
        print(f"[Keyframes] Scene detection failed for {video_id}: {e}")
        return []

    if not scenes:
        print(f"[Keyframes] No scenes detected in {video_id}")
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[Keyframes] OpenCV could not open {video_path}")
        return []

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        results: List[Dict] = []

        for idx, (start_s, end_s) in enumerate(scenes):
            mid_s = (start_s + end_s) / 2.0
            frame_path = _save_frame(cap, mid_s, out_dir, idx)
            if frame_path is None:
                continue

            motion = _measure_motion(cap, start_s, end_s, fps)

            results.append({
                "scene_id": idx,
                "timestamp": round(mid_s, 3),
                "start_time": round(start_s, 3),
                "end_time": round(end_s, 3),
                "visual_score": motion,  # normalized after the loop
                "frame_path": str(frame_path),
            })
    finally:
        cap.release()

    _normalize_scores(results)

    # Temporal attention scoring (PGL-SUM style) — requires no summary text
    try:
        from .temporal_scorer import augment_keyframes_with_temporal
        augment_keyframes_with_temporal(results)
        print(f"[Keyframes] Temporal attention scores computed for {len(results)} keyframes")
    except Exception as e:
        print(f"[Keyframes] Temporal augmentation skipped: {e}")
        for kf in results:
            kf.setdefault("temporal_score", 0.5)
    # Note: clip_score is added later in merge.py via
    # audio_energy_scorer.augment_keyframes_with_audio_energy().

    print(f"[Keyframes] {video_id}: extracted {len(results)} keyframes -> {out_dir}")
    return results


def _detect_scenes(
    video_path: str,
    threshold: float,
    min_scene_seconds: float,
) -> List[tuple]:
    """Returns list of (start_seconds, end_seconds) for each detected scene."""
    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import ContentDetector

    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=threshold))
    scene_manager.detect_scenes(video, show_progress=False)

    raw = scene_manager.get_scene_list()
    if not raw:
        # PySceneDetect returns [] when the whole video is one scene.
        # Fall back to the full duration so we still produce one keyframe.
        duration = video.duration.get_seconds() if video.duration else 0.0
        if duration <= 0:
            return []
        return [(0.0, duration)]

    scenes = []
    for start, end in raw:
        s, e = start.get_seconds(), end.get_seconds()
        if e - s >= min_scene_seconds:
            scenes.append((s, e))
    return scenes


def _ffmpeg_extract_frame(video_path: str, timestamp_s: float, out_dir: Path, scene_idx: int) -> Optional[Path]:
    """
    Extract a single frame at timestamp_s using FFmpeg fast keyframe seeking.
    -ss before -i uses keyframe-aligned seeking (millisecond seek, not full decode),
    making this ~100x faster than OpenCV cap.set(POS_MSEC) for large files.
    """
    import subprocess

    filename = f"scene_{scene_idx:03d}_t{timestamp_s:07.2f}.jpg"
    out_path = out_dir / filename

    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", f"{timestamp_s:.3f}",
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "4",
                "-f", "image2",
                str(out_path),
            ],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            return out_path
    except Exception as e:
        print(f"[Keyframes] FFmpeg frame extract failed at {timestamp_s:.1f}s: {e}")
    return None


def _save_frame(cap, timestamp_s: float, out_dir: Path, scene_idx: int) -> Optional[Path]:
    """Seek to timestamp, save JPEG. Returns path on success, None on failure."""
    import cv2

    cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_s * 1000.0)
    ok, frame = cap.read()
    if not ok or frame is None:
        return None

    filename = f"scene_{scene_idx:03d}_t{timestamp_s:07.2f}.jpg"
    path = out_dir / filename
    cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return path


def _measure_motion(cap, start_s: float, end_s: float, fps: float) -> float:
    """
    Mean per-pixel absolute difference between consecutive sampled frames.
    Higher = more action / scene change within the segment.
    Returns raw value; normalized later across all scenes of the video.
    """
    import cv2
    import numpy as np

    duration = max(end_s - start_s, 0.1)
    n_samples = max(2, min(8, int(duration * MOTION_SAMPLE_FPS)))
    timestamps = np.linspace(start_s, end_s, n_samples)

    prev_gray = None
    diffs = []

    for t in timestamps:
        cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        # Downscale before grayscale for speed; absolute values stay comparable
        small = cv2.resize(frame, (160, 90))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        if prev_gray is not None:
            diff = cv2.absdiff(prev_gray, gray)
            diffs.append(float(diff.mean()))

        prev_gray = gray

    if not diffs:
        return 0.0
    return sum(diffs) / len(diffs)


def _normalize_scores(keyframes: List[Dict]) -> None:
    """Scale visual_score to [0, 1] across this video's keyframes (in place)."""
    if not keyframes:
        return
    scores = [k["visual_score"] for k in keyframes]
    lo, hi = min(scores), max(scores)
    if hi <= lo:
        for k in keyframes:
            k["visual_score"] = 0.5
        return
    span = hi - lo
    for k in keyframes:
        k["visual_score"] = round((k["visual_score"] - lo) / span, 4)


def extract_keyframes_for_segments(
    video_id: str,
    video_path: str,
    transcript_groups: List[Dict],
    output_root: Optional[Path] = None,
) -> List[Dict]:
    """
    Fast keyframe extraction: seeks directly to the midpoint of each
    pre-grouped transcript segment instead of scanning every video frame.

    PySceneDetect scans all 244k frames of a 2h49m video (20-60 min).
    This function does N direct seeks (one per segment) — takes seconds.
    The transcript already tells us where spoken content is, so we don't
    need scene detection to discover "interesting moments".
    """
    if not os.path.isfile(video_path) or not transcript_groups:
        return []

    out_dir = (output_root or KEYFRAMES_ROOT) / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    cached = _load_cached_keyframes(out_dir)
    if cached:
        print(f"[Keyframes] {video_id}: reusing {len(cached)} cached segment-keyframes")
        return cached

    results: List[Dict] = []
    for idx, seg in enumerate(transcript_groups):
        start_s = float(seg.get("start_time", seg.get("start", 0)))
        end_s   = float(seg.get("end_time",   start_s + float(seg.get("duration", 0))))
        mid_s   = (start_s + end_s) / 2.0

        frame_path = _ffmpeg_extract_frame(video_path, mid_s, out_dir, idx)
        if frame_path is None:
            continue

        results.append({
            "scene_id":   idx,
            "timestamp":  round(mid_s,   3),
            "start_time": round(start_s, 3),
            "end_time":   round(end_s,   3),
            "visual_score": 0.5,
            "frame_path": str(frame_path),
        })

    if not results:
        return []

    try:
        from .temporal_scorer import augment_keyframes_with_temporal
        augment_keyframes_with_temporal(results)
    except Exception:
        for kf in results:
            kf.setdefault("temporal_score", 0.5)

    print(f"[Keyframes] {video_id}: {len(results)} segment-keyframes extracted (fast path)")
    return results


def _load_cached_keyframes(out_dir: Path) -> List[Dict]:
    """
    Reload previously extracted keyframes from disk JPEGs.

    Parses timestamp from filenames written by _save_frame:
      scene_{idx:03d}_t{timestamp:07.2f}.jpg

    Returns an empty list if no valid keyframes are found,
    so the caller falls through to full scene detection.
    """
    jpegs = sorted(out_dir.glob("scene_*.jpg"))
    if not jpegs:
        return []

    results: List[Dict] = []
    for jpeg in jpegs:
        try:
            # Filename: scene_000_t0003.50.jpg  →  timestamp = 3.50
            parts = jpeg.stem.split("_t")
            if len(parts) != 2:
                continue
            scene_id = int(parts[0].replace("scene_", ""))
            timestamp = float(parts[1])
            results.append({
                "scene_id": scene_id,
                "timestamp": timestamp,
                "start_time": max(0.0, timestamp - 1.0),
                "end_time": timestamp + 1.0,
                "visual_score": 0.5,   # re-scored by temporal_scorer below
                "frame_path": str(jpeg),
            })
        except (ValueError, IndexError):
            continue

    if not results:
        return []

    # Re-apply temporal scoring on the cached embeddings/frames
    try:
        from .temporal_scorer import augment_keyframes_with_temporal
        augment_keyframes_with_temporal(results)
    except Exception:
        for kf in results:
            kf.setdefault("temporal_score", 0.5)

    return results
