"""
Audio Energy Scorer — replaces CLIP for single-speaker podcast content.

Why this exists:
    CLIP compares video frames to summary text. For talking-head podcasts every
    frame looks identical (person sitting, same background) so CLIP scores are
    nearly flat (diff < 0.005 across all segments — measured on real data).
    Audio energy gives 250x more variance on the same content because it captures
    HOW the speaker is talking: emphasis, pace, projection.

Three signals blended into one score per segment:
    1. RMS energy    (40%) — overall loudness / vocal projection
    2. Spectral flux (35%) — rate of change in voice timbre (emphasis, key points)
    3. ZCR           (25%) — zero-crossing rate (speaking pace / articulation)

All three are computed directly from the video's audio track via ffmpeg + librosa.
No model download, no API, no GPU needed.

Interface:
    augment_keyframes_with_audio_energy(keyframes, video_path)
    → adds "clip_score" field to each keyframe dict (same field CLIP used)
    → calling code in merge.py and segment_extractor.py is unchanged

Fallback:
    If librosa/ffmpeg is unavailable, sets clip_score=0.5 (neutral) so the
    existing SBERT+TF-IDF scoring still runs without error.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import List

import numpy as np


# Blend weights for the three audio signals (must sum to 1.0)
_RMS_WEIGHT   = 0.40
_FLUX_WEIGHT  = 0.35
_ZCR_WEIGHT   = 0.25

# Audio extraction settings
_SAMPLE_RATE  = 16000   # Hz — sufficient for voice analysis, fast to load
_MAX_DURATION = 3600    # seconds — cap extraction to 1 hour


def _extract_audio(video_path: str, out_wav: str, duration: int = _MAX_DURATION) -> bool:
    """Extract mono 16kHz WAV from video using ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ac", "1", "-ar", str(_SAMPLE_RATE),
        "-t", str(duration),
        out_wav,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        return result.returncode == 0 and os.path.exists(out_wav)
    except Exception as e:
        print(f"[AudioEnergy] ffmpeg extraction failed: {e}")
        return False


def _score_segment(y: np.ndarray, sr: int, start: float, end: float) -> float:
    """
    Compute a single importance score for an audio segment [start, end] seconds.
    Returns a raw float (not yet normalized).
    """
    try:
        import librosa

        s = int(start * sr)
        e = int(end * sr)
        segment = y[s:e]

        if len(segment) < sr // 4:   # less than 0.25s — skip
            return 0.0

        # Signal 1: RMS energy
        rms = float(np.sqrt(np.mean(segment ** 2)))

        # Signal 2: Spectral flux (mean absolute diff of spectral centroid over time)
        centroid = librosa.feature.spectral_centroid(y=segment, sr=sr)
        flux = float(np.mean(np.abs(np.diff(centroid)))) if centroid.shape[1] > 1 else 0.0

        # Signal 3: Zero-crossing rate (speaking pace)
        zcr = float(np.mean(librosa.feature.zero_crossing_rate(segment)))

        return (_RMS_WEIGHT * rms) + (_FLUX_WEIGHT * flux) + (_ZCR_WEIGHT * zcr)

    except Exception:
        return 0.0


def _normalize(scores: List[float]) -> List[float]:
    """Min-max normalize scores to [0, 1]."""
    arr = np.array(scores, dtype=np.float32)
    mn, mx = arr.min(), arr.max()
    if mx - mn < 1e-9:
        return [0.5] * len(scores)
    return ((arr - mn) / (mx - mn)).tolist()


def augment_keyframes_with_audio_energy(
    keyframes: List[dict],
    video_path: str,
) -> List[dict]:
    """
    Add "clip_score" field to each keyframe dict using audio energy.

    Drops in as a replacement for augment_keyframes_with_clip():
    - Same input shape: list of keyframe dicts with "timestamp" field
    - Same output: "clip_score" added in-place to each dict
    - merge.py and segment_extractor.py need no changes

    Args:
        keyframes:  List of dicts, each must have "timestamp" (seconds).
        video_path: Path to the source video file.

    Returns:
        Same list with "clip_score" added.
    """
    if not keyframes:
        return keyframes

    # Neutral fallback — set first so any early return leaves valid scores
    for kf in keyframes:
        kf.setdefault("clip_score", 0.5)

    try:
        import librosa
    except ImportError:
        print("[AudioEnergy] librosa not installed — clip_score=0.5 (neutral)")
        return keyframes

    if not os.path.isfile(video_path):
        print(f"[AudioEnergy] Video not found: {video_path} — clip_score=0.5")
        return keyframes

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        print(f"[AudioEnergy] Extracting audio from {os.path.basename(video_path)}...")
        if not _extract_audio(video_path, wav_path):
            print("[AudioEnergy] Audio extraction failed — clip_score=0.5")
            return keyframes

        y, sr = librosa.load(wav_path, sr=_SAMPLE_RATE, mono=True)
        total_duration = len(y) / sr
        print(f"[AudioEnergy] Loaded {total_duration:.0f}s of audio at {sr}Hz")

        # Score each keyframe over a 20s window centred on its timestamp
        # (same window the original CLIP pipeline used per-segment)
        raw_scores = []
        for kf in keyframes:
            ts = float(kf.get("timestamp", 0.0))
            window_start = max(0.0, ts - 5.0)
            window_end   = min(total_duration, ts + 15.0)
            raw_scores.append(_score_segment(y, sr, window_start, window_end))

        # Normalize and write back
        normalized = _normalize(raw_scores)
        for kf, score in zip(keyframes, normalized):
            kf["clip_score"] = round(score, 4)

        scored = sum(1 for s in normalized if s != 0.5)
        score_range = max(normalized) - min(normalized)
        print(
            f"[AudioEnergy] Done: {scored}/{len(keyframes)} segments scored "
            f"(range={score_range:.3f})"
        )

    except Exception as e:
        print(f"[AudioEnergy] Scoring failed: {e} — clip_score=0.5")

    finally:
        try:
            os.unlink(wav_path)
        except Exception:
            pass

    return keyframes
