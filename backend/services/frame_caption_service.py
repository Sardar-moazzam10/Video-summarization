"""
Frame Caption Service — LLMVS-inspired keyframe captioning via Ollama LLaVA.

Implements the core idea from LLMVS (CVPR 2025): use a vision-language model
to generate semantic descriptions of video keyframes, then score those
descriptions against the video summary for more accurate highlight selection.

Activation:
    1. ollama pull llava:7b
    2. Set ENABLE_FRAME_CAPTIONS=True in .env (or config.py)

If unavailable, `augment_keyframes_with_captions()` returns the list unchanged
so the rest of the pipeline runs as before (CLIP-only visual scoring).

The caption_score is blended into the CLIP score in clip_feature_extractor.py:
    final_visual_score = 0.6 * clip_score + 0.4 * caption_score
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import List, Optional

import numpy as np

# =====================================================
# AVAILABILITY CHECK
# =====================================================

def is_caption_service_available() -> bool:
    """Return True if frame captioning is enabled in config and llava is reachable."""
    try:
        from ..core.config import get_settings
        settings = get_settings()
        if not settings.ENABLE_FRAME_CAPTIONS:
            return False
        import httpx
        r = httpx.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=3.0)
        if r.status_code != 200:
            return False
        models = [m["name"] for m in r.json().get("models", [])]
        return any(settings.CAPTION_MODEL in m for m in models)
    except Exception:
        return False


# =====================================================
# CAPTIONING
# =====================================================

def _encode_image_b64(image_path: str) -> Optional[str]:
    """Read image file and return base64-encoded string."""
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None


def _caption_frame(image_path: str, ollama_base_url: str, model: str) -> Optional[str]:
    """Send one keyframe to Ollama LLaVA and return a one-sentence description."""
    b64 = _encode_image_b64(image_path)
    if b64 is None:
        return None

    try:
        import httpx
        payload = {
            "model": model,
            "prompt": (
                "Describe what is happening in this video frame in one concise sentence. "
                "Focus on actions, objects, and any text visible."
            ),
            "images": [b64],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 60},
        }
        response = httpx.post(
            f"{ollama_base_url}/api/generate",
            json=payload,
            timeout=30.0,
        )
        if response.status_code == 200:
            return response.json().get("response", "").strip()
    except Exception as e:
        print(f"[FrameCaption] Ollama call failed: {e}")
    return None


def _score_captions_vs_summary(captions: List[str], summary_text: str) -> List[float]:
    """
    Score each caption against the summary via SBERT cosine similarity.
    Returns a list of floats in [0, 1].
    """
    if not captions or not summary_text:
        return [0.5] * len(captions)

    try:
        from .fusion_engine import get_sentence_transformer
        model = get_sentence_transformer()
    except Exception:
        return [0.5] * len(captions)

    all_texts = [summary_text] + captions
    all_embeddings = model.encode(all_texts, show_progress_bar=False)

    summary_emb = all_embeddings[0]
    caption_embs = all_embeddings[1:]

    summary_norm = summary_emb / (np.linalg.norm(summary_emb) + 1e-9)
    scores = []
    for emb in caption_embs:
        norm = np.linalg.norm(emb)
        if norm < 1e-9:
            scores.append(0.5)
            continue
        cosine = float(np.dot(emb / norm, summary_norm))
        # Rescale from [-1, 1] to [0, 1]
        scores.append(max(0.0, min(1.0, (cosine + 1.0) / 2.0)))

    return scores


# =====================================================
# PUBLIC API
# =====================================================

def augment_keyframes_with_captions(
    keyframes: List[dict],
    summary_text: str,
) -> List[dict]:
    """
    Add a "caption_score" field to each keyframe (in-place).

    Calls Ollama LLaVA to describe each keyframe, then scores descriptions
    against summary_text via SBERT. Silently skips if captioning is disabled
    or unavailable.

    Args:
        keyframes:    List of keyframe dicts with "frame_path" key.
        summary_text: Final summary used as semantic anchor.

    Returns:
        Same list with caption_score added (0.5 default on failure).
    """
    if not keyframes:
        return keyframes

    try:
        from ..core.config import get_settings
        settings = get_settings()
        if not settings.ENABLE_FRAME_CAPTIONS:
            return keyframes
        ollama_url = settings.OLLAMA_BASE_URL
        caption_model = settings.CAPTION_MODEL
    except Exception:
        return keyframes

    if not is_caption_service_available():
        print(f"[FrameCaption] Skipped — run: ollama pull {caption_model}")
        return keyframes

    print(f"[FrameCaption] Captioning {len(keyframes)} frames with {caption_model}...")
    captions: List[str] = []
    valid_indices: List[int] = []

    for i, kf in enumerate(keyframes):
        frame_path = kf.get("frame_path", "")
        if frame_path and Path(frame_path).exists():
            caption = _caption_frame(frame_path, ollama_url, caption_model)
            if caption:
                captions.append(caption)
                valid_indices.append(i)
            else:
                kf.setdefault("caption_score", 0.5)
        else:
            kf.setdefault("caption_score", 0.5)

    if captions:
        scores = _score_captions_vs_summary(captions, summary_text)
        for idx, score in zip(valid_indices, scores):
            keyframes[idx]["caption_score"] = score

    captioned = len(valid_indices)
    print(f"[FrameCaption] Done: {captioned}/{len(keyframes)} frames captioned")
    return keyframes
