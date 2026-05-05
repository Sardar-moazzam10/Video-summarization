"""
Temporal Scorer — Pure numpy self-attention (PGL-SUM style).

Implements simplified PGL-SUM temporal importance scoring.
No model download, no training, no GPU required.

Research basis:
  PGL-SUM (Apostolidis et al., 2021): F1 55.6% SumMe, 61.0% TVSum.
  Algorithm: scaled dot-product self-attention over frame embeddings;
             column-mean of attention matrix = importance per frame.

Pipeline role (Step 3 — Temporal Modeling):
    Frame embeddings [T, D] → softmax(E @ E.T / sqrt(D)) → [T] scores
    Called from visual_keyframe_extractor.py BEFORE summary is known.
    Scores are stored in keyframe["temporal_score"] for use in Stage 6.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import numpy as np


# =====================================================
# CORE ALGORITHM
# =====================================================

def score_temporal_importance(embeddings: np.ndarray) -> np.ndarray:
    """
    Compute PGL-SUM-style temporal importance scores.

    Args:
        embeddings: Float array of shape [T, D] — one embedding per frame.
                    Should be L2-normalized (CLIP or other).

    Returns:
        Float array of shape [T] with values in [0, 1].
        Returns uniform 0.5 scores if input is invalid.
    """
    if embeddings is None or embeddings.ndim != 2 or embeddings.shape[0] < 2:
        t = embeddings.shape[0] if embeddings is not None and embeddings.ndim >= 1 else 0
        return np.full(max(t, 1), 0.5)

    T, D = embeddings.shape

    # Scaled dot-product self-attention: A[i,j] = exp(e_i · e_j / sqrt(D)) / Z
    scale = np.sqrt(max(D, 1))
    raw = (embeddings @ embeddings.T) / scale  # [T, T]

    # Numerically stable softmax over rows
    raw -= raw.max(axis=1, keepdims=True)
    exp_raw = np.exp(raw)
    attention = exp_raw / (exp_raw.sum(axis=1, keepdims=True) + 1e-9)  # [T, T]

    # Column mean: how much total attention each frame receives
    scores = attention.mean(axis=0)  # [T]

    # Normalize to [0, 1]
    s_min, s_max = scores.min(), scores.max()
    if s_max - s_min < 1e-9:
        return np.full(T, 0.5)

    return (scores - s_min) / (s_max - s_min)


# =====================================================
# KEYFRAME AUGMENTATION
# =====================================================

def augment_keyframes_with_temporal(keyframes: List[dict]) -> List[dict]:
    """
    Add a "temporal_score" field to each keyframe dict (in-place).

    Embeddings are read from keyframe["clip_embedding"] if present,
    otherwise falls back to loading the frame image via CLIP (if available),
    otherwise uses motion-based visual_score as a proxy.

    Called from visual_keyframe_extractor.py before summary_text is known,
    so CLIP text embeddings are NOT used here — only frame embeddings.

    Args:
        keyframes: List of keyframe dicts (modified in-place).

    Returns:
        Same list with temporal_score added to each entry.
    """
    if not keyframes:
        return keyframes

    embeddings = _collect_embeddings(keyframes)

    if embeddings is not None and len(embeddings) == len(keyframes):
        scores = score_temporal_importance(embeddings)
    else:
        # Fallback: use visual_score as surrogate temporal weight
        print("[Temporal] No embeddings available — using visual_score as temporal proxy")
        raw = np.array([kf.get("visual_score", 0.5) for kf in keyframes], dtype=float)
        s_min, s_max = raw.min(), raw.max()
        if s_max - s_min < 1e-9:
            scores = np.full(len(keyframes), 0.5)
        else:
            scores = (raw - s_min) / (s_max - s_min)

    for kf, score in zip(keyframes, scores):
        kf["temporal_score"] = float(score)

    print(f"[Temporal] Scored {len(keyframes)} keyframes (mean={scores.mean():.3f})")
    return keyframes


# =====================================================
# EMBEDDING COLLECTION
# =====================================================

def _collect_embeddings(keyframes: List[dict]) -> Optional[np.ndarray]:
    """
    Gather frame embeddings from keyframes.

    Priority:
      1. keyframe["clip_embedding"] — pre-computed numpy array
      2. keyframe["frame_path"]     — load via CLIP if available

    Returns [T, D] numpy array or None if unavailable.
    """
    # Try pre-computed embeddings first
    if all("clip_embedding" in kf for kf in keyframes):
        try:
            embs = [np.asarray(kf["clip_embedding"], dtype=float) for kf in keyframes]
            stacked = np.stack(embs)
            if stacked.ndim == 2 and stacked.shape[0] == len(keyframes):
                print("[Temporal] Using pre-computed CLIP embeddings")
                return stacked
        except Exception:
            pass

    # Try loading frame images via CLIP
    try:
        from .clip_feature_extractor import get_frame_embedding, is_clip_available

        if not is_clip_available():
            return None

        embs = []
        for kf in keyframes:
            frame_path = kf.get("frame_path", "")
            if frame_path and Path(frame_path).exists():
                emb = get_frame_embedding(frame_path)
                if emb is not None:
                    embs.append(emb)
                    kf["clip_embedding"] = emb.tolist()  # Cache for later
                    continue
            embs.append(None)

        if all(e is not None for e in embs):
            return np.stack(embs)

        # Partial embeddings — fill missing with zeros (treated as low importance)
        D = next((e.shape[0] for e in embs if e is not None), 512)
        filled = [e if e is not None else np.zeros(D) for e in embs]
        return np.stack(filled)

    except Exception as e:
        print(f"[Temporal] Could not load CLIP embeddings: {e}")
        return None
