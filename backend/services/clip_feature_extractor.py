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

get_frame_embedding() / is_clip_available() are used as a fallback by
temporal_scorer.py's _collect_embeddings() whenever the narration path
is unavailable (audio_energy_scorer covers the primary path).
"""

from __future__ import annotations

from typing import Optional, Tuple

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
        from ..core.config import get_settings, get_hf_token

        settings = get_settings()
        model_id = settings.CLIP_MODEL  # "openai/clip-vit-base-patch16"
        hf_token = get_hf_token()  # None when unset → anonymous, same as before

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[CLIP] Loading {model_id} on {device}...")

        _clip_processor = CLIPProcessor.from_pretrained(model_id, token=hf_token)
        _clip_model = CLIPModel.from_pretrained(model_id, token=hf_token).to(device)
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
