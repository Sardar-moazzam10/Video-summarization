"""
Translation Service — NLLB-200 (200 languages, free, local, no API key).

Primary:  facebook/nllb-200-distilled-600M via HuggingFace transformers.
          Single model covering 200 languages (vs. one MarianMT file per language pair).
          Model size: ~2.4 GB (one-time HuggingFace cache download).
          RAM needed: ~2 GB for inference on CPU.

Fallback: deep-translator GoogleTranslator (web scraping, no API key, rate-limited).

NLLB uses FLORES-200 language codes (e.g. "fra_Latn" for French).
ISO 639-1 → FLORES-200 mapping is in ISO_TO_FLORES below.

Setup (automatic on first use):
    python -c "from transformers import AutoModelForSeq2SeqLM, AutoTokenizer; \\
               AutoModelForSeq2SeqLM.from_pretrained('facebook/nllb-200-distilled-600M'); \\
               AutoTokenizer.from_pretrained('facebook/nllb-200-distilled-600M')"
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# =====================================================
# LANGUAGE CODE MAPPING
# =====================================================

# ISO 639-1 → FLORES-200 codes used by NLLB-200
ISO_TO_FLORES: dict[str, str] = {
    "ar": "arb_Arab",  # Arabic
    "bn": "ben_Beng",  # Bengali
    "cs": "ces_Latn",  # Czech
    "de": "deu_Latn",  # German
    "es": "spa_Latn",  # Spanish
    "fa": "pes_Arab",  # Persian / Farsi
    "fr": "fra_Latn",  # French
    "hi": "hin_Deva",  # Hindi
    "id": "ind_Latn",  # Indonesian
    "it": "ita_Latn",  # Italian
    "ja": "jpn_Jpan",  # Japanese
    "ko": "kor_Hang",  # Korean
    "nl": "nld_Latn",  # Dutch
    "pl": "pol_Latn",  # Polish
    "pt": "por_Latn",  # Portuguese
    "ro": "ron_Latn",  # Romanian
    "ru": "rus_Cyrl",  # Russian
    "sv": "swe_Latn",  # Swedish
    "th": "tha_Thai",  # Thai
    "tr": "tur_Latn",  # Turkish
    "uk": "ukr_Cyrl",  # Ukrainian
    "ur": "urd_Arab",  # Urdu
    "vi": "vie_Latn",  # Vietnamese
    "zh": "zho_Hans",  # Chinese (Simplified)
    "zh-cn": "zho_Hans",
    "zh-tw": "zho_Hant",
}

NLLB_MODEL_ID = "facebook/nllb-200-distilled-600M"
TARGET_FLORES = "eng_Latn"  # English

# Module-level cache: single (tokenizer, model) pair shared across all calls
_nllb_tokenizer = None
_nllb_model = None


# =====================================================
# MODEL LOADING
# =====================================================

def _load_nllb() -> Optional[Tuple]:
    """
    Lazy-load and cache the NLLB-200 model + tokenizer.
    Returns (tokenizer, model) or None on failure.
    Thread-safe via Python GIL for read-after-write.
    """
    global _nllb_tokenizer, _nllb_model

    if _nllb_model is not None:
        return _nllb_tokenizer, _nllb_model

    try:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        print(f"[Translation] Loading NLLB-200: {NLLB_MODEL_ID} (~2.4 GB, one-time download)")
        _nllb_tokenizer = AutoTokenizer.from_pretrained(NLLB_MODEL_ID)
        _nllb_model = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL_ID)
        _nllb_model.eval()
        # Clear the model's baked-in max_length=200 so max_new_tokens is the sole limit
        _nllb_model.generation_config.max_length = None
        print(f"[Translation] NLLB-200 loaded: {NLLB_MODEL_ID}")
        return _nllb_tokenizer, _nllb_model
    except Exception as e:
        print(f"[Translation] Failed to load NLLB-200: {e}")
        return None


# =====================================================
# CORE TRANSLATION
# =====================================================

def translate_to_english(text: str, src_lang: str) -> str:
    """
    Translate text to English.

    Tries NLLB-200 first (local, free, 200 languages).
    Falls back to deep-translator if NLLB is unavailable or language unsupported.

    Args:
        text:     Text to translate (any length; batched internally).
        src_lang: ISO 639-1 source language code (e.g. "fr", "ar").

    Returns:
        Translated English text, or original text on any failure.
    """
    if not text.strip() or src_lang in ("en", "en-us", "en-gb"):
        return text

    flores_code = ISO_TO_FLORES.get(src_lang.lower())

    # NLLB-200 path (primary)
    if flores_code:
        pair = _load_nllb()
        if pair:
            try:
                return _translate_with_nllb(text, flores_code, *pair)
            except Exception as e:
                print(f"[Translation] NLLB error: {e} — falling back to deep-translator")

    # deep-translator fallback
    return _translate_with_deep_translator(text)


def _translate_with_nllb(
    text: str,
    src_flores: str,
    tokenizer,
    model,
) -> str:
    """
    Translate using NLLB-200. Splits on sentence boundaries (300-char batches)
    to stay within the 512-token model limit.
    """
    import torch

    sentences = _split_for_translation(text, max_chars=300)
    translated_parts: list[str] = []

    # Process in batches of 4 (larger batches use more RAM)
    for batch in _chunk_list(sentences, batch_size=4):
        try:
            # Each call needs src_lang set on the tokenizer
            tokenizer.src_lang = src_flores
            inputs = tokenizer(
                batch,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
            )
            # lang_code_to_id was removed in newer transformers; convert_tokens_to_ids is universal
            target_id = tokenizer.convert_tokens_to_ids(TARGET_FLORES)

            with torch.no_grad():
                output_ids = model.generate(
                    **inputs,
                    forced_bos_token_id=target_id,
                    max_new_tokens=128,   # short sentences only need ~50 tokens; 128 is plenty
                    num_beams=1,          # greedy decode — 4x faster than beam=4, fine for transcript translation
                )

            decoded = tokenizer.batch_decode(output_ids, skip_special_tokens=True)
            translated_parts.extend(decoded)

        except Exception as e:
            print(f"[Translation] NLLB batch error: {e} — passing through original")
            translated_parts.extend(batch)

    return " ".join(translated_parts)


def _translate_with_deep_translator(text: str) -> str:
    """Fallback using deep-translator (no API key, web scraping)."""
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source="auto", target="en")
        chunks = [text[i:i + 4500] for i in range(0, len(text), 4500)]
        return " ".join(translator.translate(chunk) or chunk for chunk in chunks)
    except Exception as e:
        print(f"[Translation] deep-translator fallback failed: {e}")
        return text


# =====================================================
# TRANSCRIPT-LEVEL TRANSLATION
# =====================================================

def translate_transcript_to_english(
    transcript: list,
    src_lang: str = "auto",
) -> list:
    """
    Translate a list of transcript segment dicts to English in-place.

    This replaces TranscriptService._translate_transcript_to_english().

    Args:
        transcript: List of {text, start, duration} dicts.
        src_lang:   Detected source language (ISO 639-1) or "auto".

    Returns:
        Same list with text fields translated.
    """
    if not transcript:
        return transcript

    # Detect language if not provided
    if src_lang in ("auto", ""):
        try:
            from langdetect import detect
            combined = " ".join(s.get("text", "") for s in transcript if s.get("text"))
            src_lang = detect(combined[:3000]) if combined.strip() else "en"
        except Exception:
            src_lang = "en"

    if src_lang == "en":
        return transcript

    # Translate all segment texts in one batched call
    all_texts = [seg.get("text", "") for seg in transcript]
    combined = "\n".join(all_texts)

    translated = translate_to_english(combined, src_lang)
    translated_lines = translated.split("\n")

    # Re-assign translated lines back to segments (best-effort alignment)
    for i, seg in enumerate(transcript):
        if i < len(translated_lines) and translated_lines[i].strip():
            seg["text"] = translated_lines[i].strip()

    print(f"[Translation] Translated {len(transcript)} segments from '{src_lang}' → en")
    return transcript


# =====================================================
# HELPERS
# =====================================================

def _split_for_translation(text: str, max_chars: int = 300) -> list[str]:
    """Split text into sentence-aligned chunks under max_chars."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    result: list[str] = []
    current = ""
    for s in sentences:
        if len(current) + len(s) + 1 <= max_chars:
            current = (current + " " + s).strip() if current else s
        else:
            if current:
                result.append(current)
            current = s
    if current:
        result.append(current)
    return result or [text]


def _chunk_list(lst: list, batch_size: int) -> list[list]:
    """Split a list into sub-lists of batch_size."""
    return [lst[i:i + batch_size] for i in range(0, len(lst), batch_size)]
