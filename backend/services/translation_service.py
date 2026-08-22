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
        from ..core.config import get_hf_token

        hf_token = get_hf_token()  # None when unset → anonymous, same as before
        print(f"[Translation] Loading NLLB-200: {NLLB_MODEL_ID} (~2.4 GB, one-time download)")
        _nllb_tokenizer = AutoTokenizer.from_pretrained(NLLB_MODEL_ID, token=hf_token)
        _nllb_model = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL_ID, token=hf_token)
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


def translate_segments(texts: list[str], src_lang: str) -> list[str]:
    """
    Translate a list of strings and return EXACTLY one output per input, in order.

    This is the only safe way to translate transcript segments. The previous
    approach joined them with "\n", translated the blob, and split the result
    back on "\n" — which assumed the translator preserves newlines. Neither
    backend does: the NLLB path joins its chunks with a space, and the
    deep-translator path joins its 4500-char chunks the same way. So the split
    returned a SINGLE line, segment[0] received the entire translation, and
    every other segment silently kept its original-language text.

    NLLB is fed the list directly instead: the tokenizer batches it and
    batch_decode returns one string per input, so the 1:1 mapping is guaranteed
    by the model API rather than reconstructed afterwards.

    Args:
        texts:    Segment texts, in order.
        src_lang: ISO 639-1 source language code (e.g. "hi").

    Returns:
        A list of the same length as `texts`. Any item that could not be
        translated is passed through unchanged.
    """
    if not texts:
        return []
    if src_lang.lower() in ("en", "en-us", "en-gb"):
        return list(texts)

    # Fast path first. Google batches ~64 segments per request and finishes a
    # full transcript in about 30 seconds; NLLB is a local 600M model that takes
    # minutes on CPU for the same work. NLLB stays as the offline fallback for
    # when there is no network or Google rate-limits us.
    google = _translate_segments_google(texts, src_lang)
    if google is not None and len(google) == len(texts):
        return google

    flores_code = ISO_TO_FLORES.get(src_lang.lower())
    if flores_code:
        pair = _load_nllb()
        if pair:
            try:
                print("[Translation] Falling back to local NLLB-200")
                return _translate_segments_nllb(texts, flores_code, *pair)
            except Exception as e:
                print(f"[Translation] NLLB segment error: {e}")

    return list(texts)


# Measured against the free Google endpoint on a 630-segment Hindi transcript:
# 500/1000/1500/2000-char requests all succeeded 3/3, 3000-char requests failed
# 3/3 with RequestError. 2000 is the largest size with headroom left.
_GOOGLE_MAX_CHARS = 2000
_GOOGLE_PAUSE_SECONDS = 1.0   # keeps a 10-request transcript under the rate limit


def _translate_segments_google(texts: list[str], src_lang: str) -> Optional[list[str]]:
    """
    Batched Google translation — the fast path, ~30s for a 630-segment transcript.

    Segments are joined with newlines, translated in one request per chunk, and
    split back apart. Google does preserve the newlines, but that is observed
    behaviour and not a contract, so every chunk's line count is compared against
    what was sent. A chunk that returns the wrong count is redone one segment at
    a time instead of being written back misaligned — an off-by-one here would
    shift every later segment's text onto the wrong timestamp, which is the exact
    corruption this module used to ship.

    Returns None when more than half the chunks fail, so the caller can fall back
    to NLLB (offline) or Whisper rather than accept a half-translated transcript.
    """
    import time

    try:
        from deep_translator import GoogleTranslator
    except Exception as e:
        print(f"[Translation] deep-translator unavailable: {e}")
        return None

    source = src_lang.lower() if src_lang and src_lang.lower() != "auto" else "auto"
    try:
        translator = GoogleTranslator(source=source, target="en")
    except Exception as e:
        print(f"[Translation] GoogleTranslator init failed for '{source}': {e}")
        return None

    result: list[str] = []
    chunks = 0
    failed = 0
    i = 0

    while i < len(texts):
        # Chunk on segment boundaries, never mid-segment: a split inside a
        # segment cannot be reassembled into the right line afterwards.
        j, size = i, 0
        while j < len(texts) and size + len(texts[j]) + 1 <= _GOOGLE_MAX_CHARS:
            size += len(texts[j]) + 1
            j += 1
        j = max(j, i + 1)          # always consume at least one segment
        batch = texts[i:j]
        chunks += 1

        translated_batch = None
        try:
            out = translator.translate("\n".join(batch))
            lines = (out or "").split("\n")
            if len(lines) == len(batch):
                translated_batch = lines
            else:
                print(f"[Translation] chunk {chunks}: sent {len(batch)} lines, "
                      f"got {len(lines)} — redoing segment by segment")
        except Exception as e:
            print(f"[Translation] chunk {chunks} failed ({type(e).__name__}) — "
                  f"redoing segment by segment")

        if translated_batch is None:
            per_segment = []
            for t in batch:
                if not t.strip():
                    per_segment.append(t)
                    continue
                try:
                    per_segment.append(translator.translate(t) or t)
                except Exception:
                    per_segment.append(t)     # untranslated, but in the right slot
                    failed += 1
            translated_batch = per_segment

        result.extend(translated_batch)
        i = j
        if i < len(texts):
            time.sleep(_GOOGLE_PAUSE_SECONDS)

    if failed > len(texts) // 2:
        print(f"[Translation] Google path failed for {failed}/{len(texts)} segments — giving up")
        return None

    print(f"[Translation] Google translated {len(result)} segments in {chunks} requests")
    return result


def _translate_segments_nllb(
    texts: list[str],
    src_flores: str,
    tokenizer,
    model,
) -> list[str]:
    """Batch-translate a list of segments, preserving order and length."""
    import torch

    translated: list[str] = []
    target_id = tokenizer.convert_tokens_to_ids(TARGET_FLORES)

    for batch in _chunk_list(list(texts), batch_size=8):
        # Blank segments would waste a model slot and can confuse generation.
        non_empty = [(i, t) for i, t in enumerate(batch) if t.strip()]
        if not non_empty:
            translated.extend(batch)
            continue

        try:
            tokenizer.src_lang = src_flores
            inputs = tokenizer(
                [t for _, t in non_empty],
                return_tensors="pt", padding=True,
                truncation=True, max_length=512,
            )
            with torch.no_grad():
                output_ids = model.generate(
                    **inputs,
                    forced_bos_token_id=target_id,
                    max_new_tokens=128,
                    num_beams=1,
                )
            decoded = tokenizer.batch_decode(output_ids, skip_special_tokens=True)

            merged = list(batch)
            for (idx, _), out in zip(non_empty, decoded):
                merged[idx] = out
            translated.extend(merged)

        except Exception as e:
            print(f"[Translation] NLLB batch error: {e} — passing through original")
            translated.extend(batch)

    return translated


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

    all_texts = [seg.get("text", "") for seg in transcript]
    translated = translate_segments(all_texts, src_lang)

    # Hard guard. A length mismatch means the 1:1 contract broke, and writing
    # the result back would corrupt the timeline — one segment ending up with
    # the whole transcript while the rest keep their original language. That is
    # exactly the failure this function used to ship, so refuse instead.
    if len(translated) != len(all_texts):
        print(
            f"[Translation] ABORT: got {len(translated)} translations for "
            f"{len(all_texts)} segments — keeping the original text"
        )
        return transcript

    changed = 0
    for seg, new_text in zip(transcript, translated):
        if new_text.strip():
            if new_text.strip() != seg.get("text", ""):
                changed += 1
            seg["text"] = new_text.strip()

    print(f"[Translation] Translated {changed}/{len(transcript)} segments from '{src_lang}' → en")
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
