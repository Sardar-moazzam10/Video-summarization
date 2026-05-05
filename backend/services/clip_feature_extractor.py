"""
CLIP Feature Extractor — openai/clip-vit-base-patch16 (ViT-B/16).

Provides cross-modal image-text scoring for the video summarization pipeline.
ViT-B/16 is 17% better than ViT-B/32 on COCO at the same inference cost.

Model size: ~400 MB (one-time HuggingFace cache download).
Output:     512-dim L2-normalized embeddings.

Pipeline role (Step 2 — Feature Extraction):
    Frame images  → get_frame_embedding()  → 512-dim vector
    Summary text  → get_text_embedding()   → 512-dim vector
    cosine sim    → rescaled [0, 1]         → clip_score per keyframe

Called from merge.py Stage 6 after summary text is finalized.
(temporal_scorer.py is called earlier, from visual_keyframe_extractor.py,
 because it requires no summary text.)
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

# =====================================================
# MODEL CACHE
# =====================================================

_clip_model = None
_clip_processor = None
_clip_device = None


# =====================================================
# MODEL LOADING
# =====================================================

def _load_clip() -> Optional[Tuple]:
    """
    Lazy-load and cache CLIPModel + CLIPProcessor.
    Returns (model, processor, device) or None on failure.
    """
    global _clip_model, _clip_processor, _clip_device

    if _clip_model is not None:
        return _clip_model, _clip_processor, _clip_device

    try:
        import torch
        from transformers import CLIPModel, CLIPProcessor
        from ..core.config import get_settings

        settings = get_settings()
        model_id = settings.CLIP_MODEL  # "openai/clip-vit-base-patch16"

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[CLIP] Loading {model_id} on {device}...")

        _clip_processor = CLIPProcessor.from_pretrained(model_id)
        _clip_model = CLIPModel.from_pretrained(model_id).to(device)
        _clip_model.eval()
        _clip_device = device

        print(f"[CLIP] Loaded: {model_id} (512-dim ViT-B/16)")
        return _clip_model, _clip_processor, _clip_device

    except Exception as e:
        print(f"[CLIP] Failed to load model: {e}")
        return None


def is_clip_available() -> bool:
    """
    Check if transformers + PIL are importable (no model load).
    Used by main.py startup check.
    """
    try:
        import transformers  # noqa
        from PIL import Image  # noqa
        return True
    except ImportError:
        return False


# =====================================================
# EMBEDDING FUNCTIONS
# =====================================================

def get_frame_embedding(image_path: str) -> Optional[np.ndarray]:
    """
    Extract L2-normalized 512-dim CLIP embedding from an image file.

    Args:
        image_path: Path to a JPEG/PNG keyframe image.

    Returns:
        numpy array of shape (512,), L2-normalized, or None on failure.
    """
    loaded = _load_clip()
    if loaded is None:
        return None

    model, processor, device = loaded

    try:
        import torch
        from PIL import Image

        img = Image.open(image_path).convert("RGB")
        inputs = processor(images=img, return_tensors="pt").to(device)

        with torch.no_grad():
            # Use vision_model + visual_projection directly — robust across transformers versions
            vision_out = model.vision_model(pixel_values=inputs["pixel_values"])
            pooled = vision_out.pooler_output          # [1, hidden_dim]
            image_features = model.visual_projection(pooled)  # [1, 512]

        embedding = image_features.squeeze(0).cpu().numpy()
        norm = np.linalg.norm(embedding)
        return embedding / norm if norm > 1e-8 else embedding

    except Exception as e:
        print(f"[CLIP] Frame embedding failed for {image_path}: {e}")
        return None


def get_text_embedding(text: str) -> Optional[np.ndarray]:
    """
    Extract L2-normalized 512-dim CLIP embedding from text.

    CLIP tokenizer has a 77-token limit. Pass only the first 300 chars
    of summary text — longer text is silently truncated by the tokenizer.

    Args:
        text: Any text string (first 300 chars used).

    Returns:
        numpy array of shape (512,), L2-normalized, or None on failure.
    """
    loaded = _load_clip()
    if loaded is None:
        return None

    model, processor, device = loaded

    try:
        import torch

        # Respect CLIP's 77-token / ~300-char limit
        text = text[:300].strip()
        if not text:
            return None

        inputs = processor(text=[text], return_tensors="pt", padding=True, truncation=True).to(device)

        with torch.no_grad():
            # Use text_model + text_projection directly — robust across transformers versions
            text_out = model.text_model(
                input_ids=inputs["input_ids"],
                attention_mask=inputs.get("attention_mask"),
            )
            pooled = text_out.pooler_output              # [1, hidden_dim]
            text_features = model.text_projection(pooled)  # [1, 512]

        embedding = text_features.squeeze(0).cpu().numpy()
        norm = np.linalg.norm(embedding)
        return embedding / norm if norm > 1e-8 else embedding

    except Exception as e:
        print(f"[CLIP] Text embedding failed: {e}")
        return None


# =====================================================
# SCORING
# =====================================================

def _cosine_to_score(similarity: float) -> float:
    """Rescale cosine similarity from [-1, 1] to [0, 1]."""
    return float(max(0.0, min(1.0, (similarity + 1.0) / 2.0)))


def score_keyframes_vs_summary(
    keyframes: List[dict],
    summary_text: str,
) -> List[float]:
    """
    Compute CLIP cross-modal scores for a list of keyframes against summary text.

    Args:
        keyframes:    List of keyframe dicts with a "frame_path" key.
        summary_text: Summarized text used as the text query.

    Returns:
        List of float scores in [0, 1], one per keyframe.
        Returns [0.5, ...] on any failure so downstream scoring degrades gracefully.
    """
    n = len(keyframes)
    default = [0.5] * n

    if not keyframes or not summary_text:
        return default

    text_emb = get_text_embedding(summary_text)
    if text_emb is None:
        return default

    scores: List[float] = []
    for kf in keyframes:
        frame_path = kf.get("frame_path", "")
        if not frame_path or not Path(frame_path).exists():
            scores.append(0.5)
            continue

        img_emb = get_frame_embedding(frame_path)
        if img_emb is None:
            scores.append(0.5)
            continue

        # Both vectors are L2-normalized → dot product = cosine similarity
        cosine = float(np.dot(img_emb, text_emb))
        scores.append(_cosine_to_score(cosine))

    return scores


# =====================================================
# KEYFRAME AUGMENTATION
# =====================================================

def augment_keyframes_with_clip(
    keyframes: List[dict],
    summary_text: str,
) -> List[dict]:
    """
    Add a "clip_score" field to each keyframe dict (in-place).

    Called from merge.py Stage 6 after summary_text is finalized.
    Skips gracefully if CLIP is unavailable.

    When ENABLE_FRAME_CAPTIONS=True (in config), also calls
    frame_caption_service.augment_keyframes_with_captions() and blends
    the LLaVA caption-SBERT score into the final clip_score:
        clip_score = 0.6 * raw_clip_score + 0.4 * caption_score

    This LLMVS-inspired blending improves highlight selection for
    visually ambiguous frames (e.g., talking-head shots).

    Args:
        keyframes:    List of keyframe dicts (modified in-place).
        summary_text: Final summary text for cross-modal matching.

    Returns:
        Same list with clip_score added.
    """
    if not keyframes:
        return keyframes

    if not is_clip_available():
        print("[CLIP] Not available — setting clip_score=0.5 for all keyframes")
        for kf in keyframes:
            kf.setdefault("clip_score", 0.5)
    else:
        print(f"[CLIP] Scoring {len(keyframes)} keyframes against summary...")
        scores = score_keyframes_vs_summary(keyframes, summary_text)
        for kf, score in zip(keyframes, scores):
            kf["clip_score"] = score
        scored = sum(1 for s in scores if s != 0.5)
        print(f"[CLIP] Done: {scored}/{len(keyframes)} keyframes scored")

    # Optional: blend in LLaVA caption-based semantic score (LLMVS-inspired)
    try:
        from ..core.config import get_settings
        if get_settings().ENABLE_FRAME_CAPTIONS:
            from .frame_caption_service import augment_keyframes_with_captions
            augment_keyframes_with_captions(keyframes, summary_text)
            # Blend: final_clip_score = 0.6 * clip + 0.4 * caption
            for kf in keyframes:
                clip_s = kf.get("clip_score", 0.5)
                cap_s = kf.pop("caption_score", None)
                if cap_s is not None:
                    kf["clip_score"] = round(0.6 * clip_s + 0.4 * cap_s, 4)
            print("[CLIP] Blended CLIP + caption scores")
    except Exception as e:
        print(f"[CLIP] Caption blend skipped: {e}")

    return keyframes
