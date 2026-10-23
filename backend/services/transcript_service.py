"""
Transcript Service - Robust YouTube transcript fetching with 3-tier fallbacks

Reliability tiers:
  1. YouTube Transcript API (fastest, most accurate)
  2. yt-dlp subtitle extraction (works when API is blocked)
  3. Whisper speech-to-text (last resort, works for any audio)

Also handles:
  - Video ID extraction from URLs
  - MongoDB caching
  - Multi-language support with English translation
  - Retry logic for transient failures
"""
from .acquisition_service import append_event

from .source_media_policy import SOURCE_AUDIO_FORMAT, SOURCE_AUDIO_OPTIONS

import asyncio
import re
import os
import sys
import json
import shutil
import importlib.util
import subprocess
import signal
import tempfile
import threading
import time
import difflib
from datetime import datetime
from typing import Awaitable, Callable, Optional, List

from youtube_transcript_api import YouTubeTranscriptApi


def run_subprocess_safe(cmd: List[str], timeout: Optional[float] = None, **kwargs) -> subprocess.CompletedProcess:
    """
    Subprocess-safe execution using start_new_session=True and process-group termination (os.killpg).
    Guarantees that on timeout, the entire process tree (yt-dlp + child procs)
    is terminated with SIGTERM followed by SIGKILL, preventing orphaned zombie processes.
    """
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs.setdefault("text", True)
    kwargs.setdefault("start_new_session", os.getenv("VIDFUSION_WHISPER_WORKER") != "1")

    proc = subprocess.Popen(cmd, **kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args=cmd, returncode=proc.returncode, stdout=stdout, stderr=stderr)
    except subprocess.TimeoutExpired:
        try:
            if kwargs["start_new_session"]:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                time.sleep(0.2)
                os.killpg(pgid, signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.communicate(timeout=1.0)
        except Exception:
            pass
        raise subprocess.TimeoutExpired(cmd, timeout)


def _ytdlp_cmd() -> Optional[List[str]]:
    """
    Command prefix for invoking yt-dlp, or None if it is unavailable.

    Prefers `<current interpreter> -m yt_dlp` so the venv's installed package is
    used regardless of whether venv/bin is on the server process's PATH — the
    console script is only reachable when the venv is activated, the module is
    always reachable from the interpreter that imported this file.
    Falls back to a PATH lookup for environments where yt-dlp is installed as a
    standalone binary (e.g. the Docker image, which curls it into /usr/local/bin).
    """
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    exe = shutil.which("yt-dlp")
    return [exe] if exe else None


# =====================================================
# SUMMARIZER (T5-small)
# =====================================================
#
# transformers 5.x removed the "summarization" pipeline task — SUPPORTED_TASKS
# no longer contains it, so pipeline("summarization", ...) raises
# `KeyError: Unknown task summarization`. The model is therefore driven directly
# through AutoModelForSeq2SeqLM.generate(), which behaves identically on
# transformers 4.x and 5.x and bypasses task-registry validation entirely.
# Mirrors the approach already used in services/summarization_service.py.

# =============================================================================
# DEAD CODE — T5-small summarizer
#
# TranscriptService.summarize() is the only caller of get_summarizer() /
# _load_summarizer(). As of the Phase 1 audit (2026-09-12), TranscriptService
# .summarize() has ZERO callers in any production code path (confirmed by grep
# across all backend/*.py and api/*.py). The method is labelled "legacy endpoint"
# in its own docstring — it was never migrated off, just abandoned.
#
# T5-small loads ~240 MB on first call. That call never happens in the live
# pipeline. The model sits here as dead weight.
#
# Safe to delete after a full route-handler audit confirms no /summarize
# endpoint calls it. Tracked: Phase 1 stabilization / task 4.
# =============================================================================
_summarizer_model = None
_summarizer_tokenizer = None

_SUMMARIZER_MODEL_NAME = "t5-small"
_SUMMARIZER_PREFIX = "summarize: "   # T5 is prefix-conditioned; without this it copies input
_SUMMARIZER_MAX_INPUT_TOKENS = 512   # t5-small's encoder window


def _load_summarizer():
    """Lazy-load the T5 tokenizer + model once per process.

    .. deprecated::
        Supports TranscriptService.summarize(), which has no active callers in
        the production pipeline. Do not add new callers. See dead-code note above.
        Scheduled for deletion in Phase 2 after route-handler audit.
    """
    import warnings
    warnings.warn(
        "_load_summarizer() called — T5-small is considered dead code. "
        "TranscriptService.summarize() should not be called from production paths. "
        "See the dead-code comment in transcript_service.py.",
        DeprecationWarning,
        stacklevel=2,
    )
    global _summarizer_model, _summarizer_tokenizer

    if _summarizer_model is None:
        import warnings as _w
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        from ..core.config import get_hf_token

        hf_token = get_hf_token()  # None when unset → anonymous, same as before
        print(f"[Transcript] Loading summarizer: {_SUMMARIZER_MODEL_NAME}")
        with _w.catch_warnings():
            _w.simplefilter("ignore")
            _summarizer_tokenizer = AutoTokenizer.from_pretrained(_SUMMARIZER_MODEL_NAME, token=hf_token)
            _summarizer_model = AutoModelForSeq2SeqLM.from_pretrained(_SUMMARIZER_MODEL_NAME, token=hf_token)
        _summarizer_model.eval()
        print(f"[Transcript] Summarizer loaded: {_SUMMARIZER_MODEL_NAME}")

    return _summarizer_tokenizer, _summarizer_model


def get_summarizer():
    """
    Return a callable with the old pipeline signature:

        summarizer(text, max_length=..., min_length=...) -> [{"summary_text": ...}]

    Kept shape-compatible so existing callers need no changes.
    """
    tokenizer, model = _load_summarizer()

    def _summarize(
        text: str,
        max_length: int = 150,
        min_length: int = 50,
        do_sample: bool = False,
        **kwargs,
    ):
        import torch

        # A caller passing min > max would make generate() hang on the constraint.
        min_length = min(min_length, max(1, max_length - 1))

        inputs = tokenizer(
            _SUMMARIZER_PREFIX + text,
            return_tensors="pt",
            max_length=_SUMMARIZER_MAX_INPUT_TOKENS,
            truncation=True,
        )

        with torch.no_grad():
            ids = model.generate(
                inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
                max_length=max_length,
                min_length=min_length,
                num_beams=4,
                length_penalty=2.0,
                no_repeat_ngram_size=3,
                early_stopping=True,
                do_sample=do_sample,
            )

        return [{"summary_text": tokenizer.decode(ids[0], skip_special_tokens=True)}]

    return _summarize


# =====================================================
# VIDEO ID EXTRACTION
# =====================================================

_YT_PATTERNS = [
    # Standard: youtube.com/watch?v=ID
    re.compile(r'(?:youtube\.com/watch\?.*v=)([a-zA-Z0-9_-]{11})'),
    # Short: youtu.be/ID
    re.compile(r'(?:youtu\.be/)([a-zA-Z0-9_-]{11})'),
    # Embed: youtube.com/embed/ID
    re.compile(r'(?:youtube\.com/embed/)([a-zA-Z0-9_-]{11})'),
    # Shorts: youtube.com/shorts/ID
    re.compile(r'(?:youtube\.com/shorts/)([a-zA-Z0-9_-]{11})'),
    # Live: youtube.com/live/ID
    re.compile(r'(?:youtube\.com/live/)([a-zA-Z0-9_-]{11})'),
]

_BARE_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{11}$')


def _whisper_model_name() -> str:
    """Whisper size from settings (WHISPER_MODEL in .env), defaulting to base."""
    try:
        from ..core.config import get_settings
        return getattr(get_settings(), "WHISPER_MODEL", "") or "base"
    except Exception:
        return "base"


def extract_video_id(video_id_or_url: str) -> str:
    """
    Extract YouTube video ID from a URL or return as-is if already an ID.

    Handles:
      - https://www.youtube.com/watch?v=dQw4w9WgXcQ
      - https://youtu.be/dQw4w9WgXcQ
      - https://youtube.com/embed/dQw4w9WgXcQ
      - https://youtube.com/shorts/dQw4w9WgXcQ
      - dQw4w9WgXcQ (bare ID)
    """
    text = video_id_or_url.strip()

    # Already a bare video ID
    if _BARE_ID_PATTERN.match(text):
        return text

    # Try URL patterns
    for pattern in _YT_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)

    # Last resort: return as-is (let downstream handle errors)
    return text


# =====================================================
# TRANSCRIPT SERVICE
# =====================================================

class TranscriptService:
    """
    Robust transcript fetcher with 3-tier fallback strategy.

    Tier 1: YouTube Transcript API (fast, cached by YouTube)
    Tier 2: yt-dlp subtitle download (works when API blocks)
    Tier 3: Whisper speech-to-text (always works if audio exists)
    """

    def __init__(self, db):
        self.transcripts = db["transcripts"]
        self.cookie_path = os.path.abspath("cookies.txt")
        self._whisper_model = None
        self._whisper_lock = threading.Lock()

    @staticmethod
    def _canonicalize_segments(
        transcript: list,
        video_id: str,
        *,
        language: str = "en",
        original_language: Optional[str] = None,
        provenance: str,
        translation_method: Optional[str] = None,
    ) -> list:
        """Attach provenance without changing the legacy start/duration contract."""
        canonical = []
        for raw in transcript or []:
            text = str(raw.get("text", "")).strip()
            if not text:
                continue
            start = max(0.0, float(raw.get("start", 0.0) or 0.0))
            duration = max(0.0, float(raw.get("duration", 0.0) or 0.0))
            end = max(start, float(raw.get("end", start + duration) or start + duration))
            item = dict(raw)
            item.update({
                "text": text, "start": start, "end": end,
                "duration": end - start, "source_video_id": video_id,
                "language": language, "provenance": provenance,
            })
            if original_language:
                item["original_language"] = original_language
            if translation_method:
                item["translation_method"] = translation_method
            canonical.append(item)
        return canonical

    @staticmethod
    def _whisper_cache_identity() -> str:
        from ..core.config import get_settings
        settings = get_settings()
        return (
            f"openai-whisper:{_whisper_model_name()}:translate:"
            f"chunk={float(settings.WHISPER_CHUNK_SECONDS):g}:"
            f"overlap={float(settings.WHISPER_CHUNK_OVERLAP_SECONDS):g}:v1"
        )

    def _cached_transcript_is_reusable(self, cached: dict) -> bool:
        if not self._transcript_is_sane(cached.get("transcript")):
            return False
        source = str(cached.get("source", ""))
        if source.startswith("whisper_translate"):
            return cached.get("whisper_cache_identity") == self._whisper_cache_identity()
        return True

    async def get_transcript(
        self,
        video_id: str,
        progress_cb: Optional[Callable[[str], Awaitable[None]]] = None,
        allow_whisper: bool = True,
        fast_search: bool = False,
    ) -> Optional[dict]:
        """Single-flight wrapper: one acquisition pipeline per video/mode."""
        video_id = extract_video_id(video_id)
        key = (video_id, bool(allow_whisper), bool(fast_search))
        if not hasattr(self, "_inflight"):
            self._inflight = {}
        task = self._inflight.get(key)
        if task is None or task.done():
            task = asyncio.create_task(self._get_transcript_impl(
                video_id, progress_cb=progress_cb,
                allow_whisper=allow_whisper, fast_search=fast_search,
            ))
            self._inflight[key] = task
            task.add_done_callback(lambda done, k=key: self._inflight.pop(k, None))
        if not hasattr(self, "_inflight_waiters"):
            self._inflight_waiters = {}
        self._inflight_waiters[task] = self._inflight_waiters.get(task, 0) + 1
        try:
            return await asyncio.shield(task)
        finally:
            self._inflight_waiters[task] -= 1
            if not self._inflight_waiters[task]:
                self._inflight_waiters.pop(task, None)
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def _get_transcript_impl(
        self,
        video_id: str,
        progress_cb: Optional[Callable[[str], Awaitable[None]]] = None,
        allow_whisper: bool = True,
        fast_search: bool = False,
    ) -> Optional[dict]:
        """
        Get transcript with caching and 3-tier fallbacks.

        Args:
            video_id: YouTube video ID or full URL
            progress_cb: Optional async callback(message) invoked at points a
                caller might want to surface as job progress (e.g. before the
                translation stage, which can take up to
                TRANSCRIPT_TRANSLATION_TIMEOUT_SECONDS). Best-effort — a
                failing callback is swallowed so it can never break the fetch.
                caller might want to surface as job progress.
            allow_whisper: Whether to fall back to Whisper STT when captions are missing.
            fast_search: Dedicated fast mode for Keyword / Deep Search. English captions only,
                no Whisper, no audio downloads, no translation, fails fast on missing captions.

        Returns:
            Dict with transcript, source, and cached flag, or None
        """
        # Extract clean video ID from URL if needed
        video_id = extract_video_id(video_id)

        # Check cache first. A cached transcript is only reusable if it still
        # holds a plausible timeline — see _transcript_is_sane(). Entries written
        # by the old newline-realignment translator do not, and reusing them
        # silently reproduces the original corruption on every later run.
        await append_event(
            source_id=video_id,
            operation="metadata_read",
            phase="attempted",
            method="transcript_cache",
            outcome_code="started",
        )
        cached = await self.transcripts.find_one({"video_id": video_id})
        if cached and self._cached_transcript_is_reusable(cached):
            cached_transcript = cached.get("transcript")
            cached_lang = self._detect_transcript_language(cached_transcript)
            if fast_search and cached_lang != "en":
                print(f"[Transcript] Fast search: cached transcript for {video_id} is non-English — skipping")
                return None

            await append_event(
                source_id=video_id,
                operation="metadata_read",
                phase="succeeded",
                method="transcript_cache",
                outcome_code="success",
                cache_result="hit",
            )
            if cached_lang == "en":
                return {
                    "transcript": cached_transcript,
                    "source": cached.get("source", "cache"),
                    "cached": True,
                }

            print(f"[Transcript] Cached transcript for {video_id} is '{cached_lang}' — recovering canonical English")
            transcript = cached_transcript
            source = cached.get("source", "cache")
        elif cached:
            print(f"[Transcript] Cached transcript for {video_id} is stale or malformed — refetching")
            transcript = None
            source = "cache"
        else:
            transcript = None
            source = "cache"

        await append_event(
            source_id=video_id,
            operation="metadata_read",
            phase="succeeded",
            method="transcript_cache",
            outcome_code="not_found",
            cache_result="miss",
        )

        # Fast search mode: English captions only, zero Whisper/translation/download
        if fast_search:
            transcript = await asyncio.wait_for(
                asyncio.to_thread(self._fetch_fast_english_transcript, video_id),
                timeout=12.0,
            )
            if not transcript:
                return None

            source = "youtube_api_fast"
            # Cache in MongoDB
            await self.transcripts.update_one(
                {"video_id": video_id},
                {"$set": {
                    "video_id": video_id,
                    "transcript": transcript,
                    "fetched_at": datetime.utcnow().isoformat(),
                    "source": source,
                }},
                upsert=True,
            )
            return {
                "transcript": transcript,
                "source": source,
                "cached": False,
            }

        # Tier 1: YouTube Transcript API (fastest). Off the event loop —
        # this makes network calls with time.sleep backoff, and running it
        # inline would block every other request on this process for the
        # full retry duration (same class of bug fixed for translation/
        # Whisper below).
        await append_event(
            source_id=video_id,
            operation="caption_read",
            phase="attempted",
            method="youtube_api",
            outcome_code="started",
        )
        if transcript is None:
            if progress_cb:
                await progress_cb(f"Checking YouTube captions for {video_id}...")
            try:
                transcript = await asyncio.wait_for(
                    asyncio.to_thread(self._fetch_youtube_api, video_id), timeout=25.0
                )
            except asyncio.TimeoutError:
                transcript = None
                print(f"[Transcript] YouTube caption provider timed out for {video_id}")
            source = "youtube_api"
        await append_event(
            source_id=video_id,
            operation="caption_read",
            phase="succeeded" if transcript else "failed",
            method="youtube_api",
            outcome_code="success" if transcript else "not_found",
            provider="youtube",
        )

        # Tier 2: yt-dlp subtitle extraction. Off the event loop — this
        # shells out via subprocess.run with up to a 90s timeout per
        # language tried, which would otherwise stall the whole server.
        if not transcript:
            await append_event(
                source_id=video_id,
                operation="caption_read",
                phase="attempted",
                method="yt_dlp_subtitles",
                outcome_code="started",
            )
            if progress_cb:
                await progress_cb(f"Trying subtitle fallback for {video_id}...")
            try:
                transcript = await asyncio.wait_for(
                    asyncio.to_thread(self._fetch_ytdlp, video_id), timeout=40.0
                )
            except asyncio.TimeoutError:
                transcript = None
                print(f"[Transcript] Subtitle fallback timed out for {video_id}")
            source = "yt_dlp"
            await append_event(
                source_id=video_id,
                operation="caption_read",
                phase="succeeded" if transcript else "failed",
                method="yt_dlp_subtitles",
                outcome_code="success" if transcript else "not_found",
                fallback_from_event_id=None,
            )

        # Language gate.
        #
        # Captions come back in whatever language the uploader published. The rest
        # of the pipeline is English-only: BGE embeddings, BART, the TF-IDF scorer
        # and the FAISS index are all English models, and a summary written in the
        # source language is not what the user asked for.
        #
        if transcript:
            lang = self._detect_transcript_language(transcript)
            if lang != "en":
                from ..core.config import get_settings
                settings = get_settings()
                print(f"[Transcript] {video_id} captions are '{lang}' — attempting fast text translation first")
                if progress_cb:
                    try:
                        await progress_cb(f"Translating '{lang}' captions to English for {video_id}...")
                    except Exception:
                        pass

                timeout = settings.TRANSCRIPT_TRANSLATION_TIMEOUT_SECONDS
                translated = None
                try:
                    translated = await asyncio.wait_for(
                        asyncio.to_thread(self._translate_transcript_to_english, transcript, lang),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    print(f"[Transcript] Text translation timed out after {timeout}s for {video_id}")
                except Exception as e:
                    print(f"[Transcript] Text translation error for {video_id}: {e}")

                if translated and self._detect_transcript_language(translated) == "en":
                    transcript = self._canonicalize_segments(
                        translated, video_id, original_language=lang,
                        provenance=source, translation_method="text_translation",
                    )
                    source = f"{source}+translated"
                    print(f"[Transcript] Successfully translated '{lang}' captions to English for {video_id}")
                else:
                    # Text translation failed or was incomplete. Fall back to Whisper only if allowed
                    # and video duration does not exceed CPU capability limits.
                    whisper_transcript = None
                    if allow_whisper:
                        from .media_probe import get_video_duration_seconds
                        dur = get_video_duration_seconds(video_id)
                        max_duration = getattr(settings, "MAX_WHISPER_AUDIO_DURATION_SECONDS", 1200.0)
                        if dur and dur > max_duration:
                            print(f"[Transcript] Video {video_id} is {dur:.1f}s (> {max_duration:.1f}s) — skipping Whisper STT to prevent CPU freeze")
                        else:
                            if progress_cb:
                                try:
                                    await progress_cb(f"Recovering '{lang}' audio with Whisper for {video_id}...")
                                except Exception:
                                    pass
                            await append_event(source_id=video_id, operation="audio_download", phase="attempted", method="yt_dlp_audio", outcome_code="started")
                            whisper_transcript = await self._recover_whisper(video_id, lang, progress_cb)
                            await append_event(source_id=video_id, operation="audio_download", phase="succeeded" if whisper_transcript else "failed", method="yt_dlp_audio", outcome_code="success" if whisper_transcript else "not_found")

                    if whisper_transcript and self._detect_transcript_language(whisper_transcript) == "en":
                        transcript = whisper_transcript
                        source = "whisper_translate"
                    else:
                        source = f"{source}+partial"
            else:
                transcript = self._canonicalize_segments(
                    transcript, video_id, provenance=source,
                    translation_method="youtube" if "youtube" in source else None,
                )

        # Tier 3: Whisper speech-to-text (last resort). Off the event loop —
        # this is the slowest, most CPU-bound path (audio download + local
        # transcription); running it inline blocks the entire process, so
        # every other in-flight request (including other videos in the same
        # search) appears frozen until this one finishes.
        if not transcript and allow_whisper:
            from .media_probe import get_video_duration_seconds
            dur = get_video_duration_seconds(video_id)
            from ..core.config import get_settings
            settings = get_settings()
            max_duration = getattr(settings, "MAX_WHISPER_AUDIO_DURATION_SECONDS", 1200.0)
            if dur and dur > max_duration:
                print(f"[Transcript] Video {video_id} duration ({dur:.1f}s) exceeds max Whisper limit ({max_duration:.1f}s) — skipping Whisper STT to prevent CPU freeze")
            else:
                if progress_cb:
                    await progress_cb(f"Trying Whisper recovery for {video_id}...")
                await append_event(
                    source_id=video_id,
                    operation="audio_download",
                    phase="attempted",
                    method="yt_dlp_audio",
                    outcome_code="started",
                )
                transcript = await self._recover_whisper(video_id, None, progress_cb)
                source = "whisper_translate"
                await append_event(
                    source_id=video_id,
                    operation="audio_download",
                    phase="succeeded" if transcript else "failed",
                    method="yt_dlp_audio",
                    outcome_code="success" if transcript else "not_found",
                )

        if not transcript:
            return None

        if not self._transcript_is_sane(transcript):
            print(f"[Transcript] WARNING: transcript for {video_id} looks malformed "
                  f"(source={source}); caching it anyway but downstream quality will suffer")

        cache_payload = {
            "video_id": video_id,
            "transcript": transcript,
            "fetched_at": datetime.utcnow().isoformat(),
            "source": source,
            "language": next(
                (seg.get("language") for seg in transcript if seg.get("language")),
                None,
            ) or self._detect_transcript_language(transcript),
        }
        if source.startswith("whisper_translate"):
            cache_payload["translation_method"] = "whisper"
            cache_payload["whisper_cache_identity"] = self._whisper_cache_identity()
        await self.transcripts.update_one(
            {"video_id": video_id},
            {"$set": cache_payload},
            upsert=True,
        )

        return {"transcript": transcript, "source": source, "cached": False}

    # -------------------------------------------------
    # FAST SEARCH: English-only fast caption fetcher
    # -------------------------------------------------
    def _fetch_fast_english_transcript(self, video_id: str) -> Optional[list]:
        """
        Dedicated fast English caption fetcher for Keyword / Deep Search.

        Invariants:
          - Only manual English or auto-generated English captions.
          - Never attempts translation on non-English captions; skips them immediately.
          - Never invokes yt-dlp, Whisper, audio download, NLLB, BART, Llama, or FFmpeg.
          - Fails fast on disabled/unavailable subtitles without retries.
        """
        try:
            _ytt = YouTubeTranscriptApi()
            transcript_list = _ytt.list(video_id)

            # Strategy 1: Manual English (including dialect codes)
            try:
                fetched = transcript_list.find_manually_created_transcript(
                    ["en", "en-US", "en-GB", "en-CA", "en-AU", "en-IN"]
                ).fetch()
                normalized = self._normalize_transcript(fetched)
                if normalized:
                    print(f"[Transcript] Fast search: manual English found for {video_id}")
                    return normalized
            except Exception:
                pass

            # Strategy 2: Auto-generated English
            try:
                fetched = transcript_list.find_generated_transcript(
                    ["en", "en-US", "en-GB", "en-CA", "en-AU", "en-IN"]
                ).fetch()
                normalized = self._normalize_transcript(fetched)
                if normalized:
                    print(f"[Transcript] Fast search: auto-generated English found for {video_id}")
                    return normalized
            except Exception:
                pass

            # If captions exist but none are English: skip immediately without translation
            langs = [getattr(t, "language_code", str(t)) for t in transcript_list]
            print(f"[Transcript] Fast search: {video_id} has non-English captions only ({langs}) — skipping without translation")
            return None

        except Exception as e:
            # TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, etc.
            print(f"[Transcript] Fast search: captions unavailable for {video_id} ({e.__class__.__name__}) — skipping")
            return None

    # -------------------------------------------------
    # TIER 1: YouTube Transcript API
    # -------------------------------------------------
    def _fetch_youtube_api(self, video_id: str, max_retries: int = 2) -> Optional[list]:
        """
        Primary method: YouTube Transcript API with multi-language support.

        Tries in order:
          1. Manual English transcript
          2. Auto-generated English transcript
          3. Any transcript translated to English
          4. Any transcript in original language
        """
        _ytt = YouTubeTranscriptApi()  # v1.x requires instance, not static methods
        for attempt in range(max_retries + 1):
            try:
                transcript_list = _ytt.list(video_id)

                # Strategy 1: Manual English
                try:
                    fetched = transcript_list.find_manually_created_transcript(["en"]).fetch()
                    print(f"[Transcript] Manual English found for {video_id}")
                    return self._normalize_transcript(fetched)
                except Exception:
                    pass

                # Strategy 2: Auto-generated English
                try:
                    fetched = transcript_list.find_generated_transcript(["en"]).fetch()
                    print(f"[Transcript] Auto-generated English found for {video_id}")
                    return self._normalize_transcript(fetched)
                except Exception:
                    pass

                # Strategy 3: Any language, translate to English via YouTube
                try:
                    for transcript in transcript_list:
                        try:
                            fetched = transcript.translate("en").fetch()
                            print(f"[Transcript] Translated {transcript.language_code}->en for {video_id}")
                            return self._normalize_transcript(fetched)
                        except Exception:
                            continue
                except Exception:
                    pass

                # Strategy 4: Fetch in original language, translate via Google Translate
                try:
                    for transcript in transcript_list:
                        fetched = transcript.fetch()
                        normalized = self._normalize_transcript(fetched)
                        if normalized:
                            # Returned in its ORIGINAL language on purpose. get_transcript()
                            # owns the language decision now, because the good answer for a
                            # non-English video is Whisper's translate task, not a
                            # post-hoc translation of caption fragments.
                            print(f"[Transcript] Fetched {transcript.language_code} captions for {video_id}")
                            return normalized
                except Exception:
                    pass

                return None

            except Exception as e:
                err_str = str(e).lower()
                if "subtitles are disabled" in err_str or "no transcript" in err_str or "transcriptsdisabled" in err_str or "could not retrieve a transcript" in err_str:
                    print(f"[Transcript] YouTube API: captions unavailable for {video_id} ({e.__class__.__name__}), skipping retries")
                    return None

                if attempt < max_retries:
                    wait = 2 ** attempt
                    print(f"[Transcript] YouTube API attempt {attempt+1} failed, retrying in {wait}s: {e}")
                    time.sleep(wait)
                else:
                    print(f"[Transcript] YouTube API failed after {max_retries+1} attempts: {e}")
                    return None

    # -------------------------------------------------
    # TIER 2: yt-dlp subtitles
    # -------------------------------------------------
    def _fetch_ytdlp(self, video_id: str, timeout: float = 25.0) -> Optional[list]:
        """
        Fallback: Download subtitles via yt-dlp.
        Bounded latency: single-shot subtitle fetch with process-group cleanup on timeout.
        """
        ytdlp = _ytdlp_cmd()
        if ytdlp is None:
            print("[Transcript] yt-dlp not installed (pip install yt-dlp), skipping tier 2")
            return None

        url = f"https://www.youtube.com/watch?v={video_id}"

        # Approach 1: Fast single-shot download of available subtitles to temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                out_template = os.path.join(tmpdir, "sub")
                cmd = [
                    *ytdlp,
                    "--write-auto-sub",
                    "--write-sub",
                    "--skip-download",
                    "--sub-langs", "en.*,en,hi,ur,es,fr,de",
                    "--sub-format", "json3",
                    "--output", out_template,
                    "--no-warnings",
                    "--quiet",
                    "--socket-timeout", "10",
                    "--retries", "1",
                    "--fragment-retries", "1",
                    url,
                ]

                if os.path.exists(self.cookie_path):
                    cmd.extend(["--cookies", self.cookie_path])

                result = run_subprocess_safe(cmd, timeout=timeout)
                if result.returncode == 0:
                    for fname in os.listdir(tmpdir):
                        if fname.endswith(".json3"):
                            fpath = os.path.join(tmpdir, fname)
                            with open(fpath, "r", encoding="utf-8") as f:
                                data = json.load(f)

                            transcript = self._parse_json3_subtitles(data)
                            if transcript:
                                print(f"[Transcript] yt-dlp got subs ({fname}) for {video_id}")
                                return transcript
            except subprocess.TimeoutExpired:
                print(f"[Transcript] yt-dlp timed out ({timeout}s) for {video_id}")
            except Exception as e:
                print(f"[Transcript] yt-dlp error for {video_id}: {e}")

        # Approach 2: Fast print-subtitle fallback
        try:
            cmd = [
                *ytdlp,
                "--write-auto-sub", "--skip-download",
                "--sub-lang", "en", "--sub-format", "json3",
                "--no-warnings", "--quiet", "--print", "subtitle",
                "--socket-timeout", "10",
                "--retries", "1",
                url,
            ]
            if os.path.exists(self.cookie_path):
                cmd.extend(["--cookies", self.cookie_path])

            result = run_subprocess_safe(cmd, timeout=12.0)
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                transcript = self._parse_json3_subtitles(data)
                if transcript:
                    print(f"[Transcript] yt-dlp --print fallback worked for {video_id}")
                    return transcript
        except Exception:
            pass

        return None

    # -------------------------------------------------
    # TIER 3: Whisper speech-to-text
    # -------------------------------------------------
    async def _recover_whisper(self, video_id, language=None, progress_cb=None):
        from .media_probe import get_video_duration_seconds
        from ..core.config import get_settings
        dur = get_video_duration_seconds(video_id)
        settings = get_settings()
        max_duration = getattr(settings, "MAX_WHISPER_AUDIO_DURATION_SECONDS", 1200.0)
        if dur and dur > max_duration:
            print(f"[Transcript] Video {video_id} duration ({dur:.1f}s) exceeds max CPU Whisper limit ({max_duration:.1f}s) — skipping Whisper recovery")
            return None
        from .whisper_recovery import recover_audio
        return await recover_audio(self, video_id, language, progress_cb)

    def _fetch_whisper(self, video_id: str, original_language: Optional[str] = None) -> Optional[list]:
        """
        Last resort: Download audio and transcribe with OpenAI Whisper.
        Slower but works for any video with audio. Bounded download timeout.
        """
        from ..core.config import get_settings
        settings = get_settings()
        from .media_probe import get_video_duration_seconds
        dur = get_video_duration_seconds(video_id)
        max_duration = getattr(settings, "MAX_WHISPER_AUDIO_DURATION_SECONDS", 1200.0)
        if dur and dur > max_duration:
            print(f"[Transcript] Video {video_id} duration ({dur:.1f}s) exceeds max CPU Whisper limit ({max_duration:.1f}s) — skipping audio download")
            return None

        ytdlp = _ytdlp_cmd()
        if ytdlp is None:
            print("[Transcript] yt-dlp needed for audio download, skipping Whisper")
            return None

        try:
            import whisper
        except ImportError:
            print("[Transcript] openai-whisper not installed, skipping tier 3")
            return None

        url = f"https://www.youtube.com/watch?v={video_id}"

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_out = os.path.join(tmpdir, "audio")

            # Download audio only with bounded timeout (60s)
            try:
                from ..core.config import get_settings
                settings = get_settings()
                node = settings.NODE_PATH or shutil.which("node")
                cmd = [
                    *ytdlp,
                    *SOURCE_AUDIO_OPTIONS,
                    "-f", SOURCE_AUDIO_FORMAT,
                    "--extract-audio",
                    "--audio-format", "mp3",
                    "--audio-quality", "5",  # Medium quality (faster download)
                    "--output", f"{audio_out}.%(ext)s",
                    "--no-warnings",
                    "--quiet",
                    "--no-playlist",
                    "--socket-timeout", "15",
                    "--retries", "1",
                    "--fragment-retries", "1",
                    url,
                ]
                if node:
                    cmd.extend(["--js-runtimes", f"node:{node}", "--remote-components", "ejs:github"])
                if settings.FFMPEG_PATH:
                    cmd.extend(["--ffmpeg-location", settings.FFMPEG_PATH])
                if os.path.exists(self.cookie_path):
                    cmd.extend(["--cookies", self.cookie_path])

                proc = run_subprocess_safe(cmd, timeout=float(settings.WHISPER_AUDIO_DOWNLOAD_TIMEOUT_SECONDS))
                
                if proc.returncode != 0:
                    print(f"[Transcript] yt-dlp audio download failed for {video_id}: {proc.stderr.strip()}")
                    return None

                # Find the downloaded audio file
                actual_audio = None
                for fname in os.listdir(tmpdir):
                    if fname.endswith((".mp3", ".m4a", ".wav", ".webm", ".opus")):
                        actual_audio = os.path.join(tmpdir, fname)
                        break

                if not actual_audio or not os.path.exists(actual_audio) or os.path.getsize(actual_audio) < 1024:
                    print(f"[Transcript] Audio download failed (or file empty) for {video_id}")
                    return None

                print(f"[Transcript] Audio downloaded, running chunked Whisper translate for {video_id}...")

            except subprocess.TimeoutExpired:
                print(f"[Transcript] Audio download timed out for {video_id}")
                return None
            except Exception as e:
                print(f"[Transcript] Audio download error: {e}")
                return None

            # Transcribe with Whisper
            try:
                with self._whisper_lock:
                    if self._whisper_model is None:
                        model_name = _whisper_model_name()
                        self._whisper_model = whisper.load_model(model_name)
                        print(f"[Transcript] Loaded Whisper {model_name} model")

                    transcript, chunk_count = self._transcribe_audio_chunks(
                        actual_audio, video_id, original_language
                    )

                if transcript:
                    print(f"[Transcript] Whisper translated {len(transcript)} segments across {chunk_count} chunk(s) for {video_id}")
                    return transcript

            except Exception as e:
                print(f"[Transcript] Whisper transcription failed: {e}")

        return None

    @staticmethod
    def _audio_duration_seconds(audio_path: str) -> Optional[float]:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None
        try:
            proc = run_subprocess_safe([
                ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", audio_path,
            ], timeout=20.0)
            value = float((proc.stdout or "").strip())
            return value if value > 0 else None
        except Exception:
            return None

    @staticmethod
    def _segments_duplicate(left: dict, right: dict) -> bool:
        a = re.sub(r"[^a-z0-9 ]+", "", str(left.get("text", "")).lower()).strip()
        b = re.sub(r"[^a-z0-9 ]+", "", str(right.get("text", "")).lower()).strip()
        if not a or not b:
            return False
        similarity = difflib.SequenceMatcher(None, a, b).ratio()
        overlap = min(float(left["end"]), float(right["end"])) - max(float(left["start"]), float(right["start"]))
        return similarity >= 0.82 and overlap >= -0.35

    def _transcribe_audio_chunks(
        self,
        audio_path: str,
        video_id: str,
        original_language: Optional[str],
    ) -> tuple[list, int]:
        """Translate bounded audio chunks and project local times to source time."""
        from ..core.config import get_settings
        settings = get_settings()
        duration = self._audio_duration_seconds(audio_path)
        chunk_seconds = max(60.0, float(settings.WHISPER_CHUNK_SECONDS))
        overlap = min(max(0.0, float(settings.WHISPER_CHUNK_OVERLAP_SECONDS)), chunk_seconds / 4)
        if duration is None:
            raise RuntimeError("audio duration is required for safe Whisper chunking")
        max_duration = getattr(settings, "MAX_WHISPER_AUDIO_DURATION_SECONDS", 1200.0)
        if duration > max_duration:
            print(f"[Transcript] Audio duration ({duration:.1f}s) exceeds max CPU Whisper limit ({max_duration:.1f}s) — skipping Whisper chunking to avoid CPU lock")
            return [], 0
        ranges = []
        start = 0.0
        while start < duration:
            length = min(chunk_seconds, duration - start)
            ranges.append((start, length))
            if start + length >= duration:
                break
            start += chunk_seconds - overlap

        ffmpeg = getattr(settings, "FFMPEG_PATH", "") or shutil.which("ffmpeg")
        final: list = []
        with tempfile.TemporaryDirectory() as chunk_dir:
            for index, (offset, length) in enumerate(ranges):
                chunk_path = audio_path
                if len(ranges) > 1:
                    if not ffmpeg:
                        raise RuntimeError("ffmpeg is required for long-audio Whisper chunking")
                    chunk_path = os.path.join(chunk_dir, f"chunk-{index:04d}.wav")
                    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{offset:.3f}", "-i", audio_path]
                    if length is not None:
                        cmd.extend(["-t", f"{length:.3f}"])
                    cmd.extend(["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-y", chunk_path])
                    proc = run_subprocess_safe(cmd, timeout=max(120.0, float(length or chunk_seconds) * 0.25))
                    if proc.returncode != 0:
                        raise RuntimeError(f"ffmpeg chunk {index + 1} failed: {(proc.stderr or '').strip()}")

                end_label = offset + (length or 0.0)
                print(f"[Transcript] Whisper chunk {index + 1}/{len(ranges)} ({offset:.1f}s..{end_label:.1f}s)")
                decode_options = {"task": "translate", "fp16": False}
                if original_language:
                    decode_options["language"] = original_language
                result = self._whisper_model.transcribe(chunk_path, **decode_options)
                for segment in result.get("segments", []):
                    local_start = max(0.0, float(segment.get("start", 0.0) or 0.0))
                    local_end = max(local_start, float(segment.get("end", local_start) or local_start))
                    absolute_start = offset + local_start
                    absolute_end = offset + local_end
                    if duration is not None:
                        absolute_start = min(absolute_start, duration)
                        absolute_end = min(max(absolute_start, absolute_end), duration)
                    candidate = {
                        "text": str(segment.get("text", "")).strip(),
                        "start": absolute_start,
                        "end": absolute_end,
                        "duration": absolute_end - absolute_start,
                    }
                    if not candidate["text"] or candidate["duration"] <= 0:
                        continue
                    if final and self._segments_duplicate(final[-1], candidate):
                        continue
                    final.append(candidate)

        final.sort(key=lambda item: (item["start"], item["end"], item["text"]))
        return self._canonicalize_segments(
            final, video_id, original_language=original_language,
            provenance="whisper_audio_translation", translation_method="whisper",
        ), len(ranges)

    # -------------------------------------------------
    # HELPERS
    # -------------------------------------------------
    @staticmethod
    def _normalize_transcript(fetched) -> Optional[list]:
        """
        Normalize transcript output to a consistent list-of-dicts format.
        Handles both youtube-transcript-api v0.x and v1.x formats.
        """
        result = []
        for item in fetched:
            # v1.x: FetchedTranscriptSnippet with attributes
            if hasattr(item, "text"):
                result.append({
                    "text": item.text,
                    "start": getattr(item, "start", 0),
                    "duration": getattr(item, "duration", 0),
                })
            # v0.x or already a dict
            elif isinstance(item, dict):
                result.append({
                    "text": item.get("text", ""),
                    "start": item.get("start", 0),
                    "duration": item.get("duration", 0),
                })
        return result if result else None

    # A segment cannot carry more words than its duration allows. Fast human
    # speech tops out near 5 words/second; 12 leaves generous headroom for
    # timing jitter while still catching a segment that swallowed the whole
    # transcript (the old translator produced 1557 words in a 2.5s segment).
    _MAX_WORDS_PER_SECOND = 12.0

    @classmethod
    def _transcript_is_sane(cls, transcript) -> bool:
        """
        True when the transcript's text plausibly fits its own timeline.

        Guards against the corruption mode where a translation step collapses
        every segment's text into one entry: that entry then holds thousands of
        words against a duration of a second or two, and every clip timestamp
        derived from it is wrong.
        """
        if not transcript or not isinstance(transcript, list):
            return False
        for seg in transcript:
            if not isinstance(seg, dict):
                return False
            words = len(str(seg.get("text", "")).split())
            duration = float(seg.get("duration", 0) or 0)
            if words > 30 and duration > 0 and (words / duration) > cls._MAX_WORDS_PER_SECOND:
                return False
        return True

    @staticmethod
    def _detect_transcript_language(transcript: list) -> str:
        """
        ISO 639-1 language of the transcript, or "en" when undetectable.

        Sampled across the whole transcript rather than the first N characters:
        a mixed-language transcript whose opening happens to be English would
        otherwise be misread as English and skip translation entirely.
        """
        try:
            from langdetect import detect
            texts = [str(s.get("text", "")) for s in transcript if s.get("text")]
            if not texts:
                return "en"
            # Each sampled segment is truncated before joining. Without that, one
            # oversized segment fills the whole sample and decides the answer on
            # its own — which is how a transcript whose first entry had swallowed
            # an English translation still read as English while 630 Hindi
            # segments followed it.
            step = max(1, len(texts) // 40)
            sample = " ".join(t[:120] for t in texts[::step])[:3000]
            return detect(sample) if sample.strip() else "en"
        except Exception:
            return "en"

    @staticmethod
    def _translate_transcript_to_english(transcript: list, src_lang: str = "") -> list:
        """
        Translate transcript segments to English via NLLB-200 (local, 200 languages).
        Falls back to deep-translator if NLLB is unavailable.
        """
        if not src_lang:
            try:
                from langdetect import detect
                combined = " ".join(seg.get("text", "") for seg in transcript if seg.get("text"))
                src_lang = detect(combined[:3000]) if combined.strip() else "en"
            except Exception:
                src_lang = "auto"

        try:
            from .translation_service import translate_transcript_to_english
            return translate_transcript_to_english(transcript, src_lang=src_lang)
        except Exception as e:
            print(f"[Transcript] NLLB translation failed: {e}, returning original")
            return transcript

    @staticmethod
    def _parse_json3_subtitles(data: dict) -> Optional[list]:
        """Parse yt-dlp json3 subtitle format into transcript segments."""
        transcript = []
        for event in data.get("events", []):
            if "segs" in event:
                text = "".join(seg.get("utf8", "") for seg in event["segs"]).strip()
                if not text or text == "\n":
                    continue
                start = float(event.get("tStartMs", 0)) / 1000
                duration = float(event.get("dDurationMs", 0)) / 1000
                transcript.append({
                    "text": text,
                    "start": start,
                    "duration": duration,
                })
        return transcript if transcript else None

    async def preflight_source(self, raw_video_id: str, per_source_timeout: float = 20.0) -> dict:
        """
        Bounded transcript-availability preflight for a single video.
        Determines acquisition viability before launching an expensive multi-video job.
        """
        video_id = extract_video_id(raw_video_id)
        t0 = time.perf_counter()

        def ready_result(transcript: list, status: str, method: str) -> dict:
            """Classify transcript capability without hard-rejecting a non-English transcript
            before the existing English-normalization/Whisper fallback has had a chance to run.
            """
            detected_language = self._detect_transcript_language(transcript)
            supported_languages = ["en"]
            supported = detected_language in supported_languages
            if supported:
                final_status = "english_ready"
                ready = True
            elif detected_language and detected_language != "en":
                final_status = "translation_required"
                ready = True
            else:
                final_status = "unsupported_transcript_language"
                ready = False
            warning = f"Transcript is in '{detected_language}' (will be translated to English)" if (detected_language and detected_language != "en") else None
            return {
                "video_id": video_id,
                "source_id": video_id,
                "status": final_status,
                "ready": ready,
                "method": method,
                "time_seconds": round(time.perf_counter() - t0, 3),
                "error": None if ready else "Transcript language is not supported",
                "error_code": None if ready else "UNSUPPORTED_TRANSCRIPT_LANGUAGE",
                "warning": warning,
                "detected_language": detected_language,
                "supported_languages": supported_languages,
            }

        # 1. Cache check
        try:
            cached = await self.transcripts.find_one({"video_id": video_id})
            if cached and self._transcript_is_sane(cached.get("transcript")):
                return ready_result(cached["transcript"], "cached_transcript", "cache")
        except Exception as e:
            print(f"[Preflight] Cache check error for {video_id}: {e}")

        # 2. Fast YouTube Transcript API check (max 1 retry)
        try:
            transcript = await asyncio.wait_for(
                asyncio.to_thread(self._fetch_youtube_api, video_id, 1),
                timeout=min(per_source_timeout, 10.0),
            )
            if transcript and self._transcript_is_sane(transcript):
                return ready_result(transcript, "caption_ready", "youtube_api")
        except Exception:
            pass

        # 3. Fast yt-dlp subtitle check (bounded timeout)
        try:
            ytdlp_timeout = max(5.0, per_source_timeout - (time.perf_counter() - t0))
            transcript = await asyncio.to_thread(self._fetch_ytdlp, video_id, timeout=min(ytdlp_timeout, 12.0))
            if transcript and self._transcript_is_sane(transcript):
                return ready_result(transcript, "caption_ready", "yt_dlp")
        except Exception:
            pass

        # If captions are not fast-available, slow recovery (Whisper) would be required
        t_elapsed = round(time.perf_counter() - t0, 3)
        from .media_probe import get_video_duration_seconds
        dur = get_video_duration_seconds(video_id)
        from ..core.config import get_settings
        settings = get_settings()
        max_duration = getattr(settings, "MAX_WHISPER_AUDIO_DURATION_SECONDS", 1200.0)
        if dur and dur > max_duration:
            return {
                "video_id": video_id,
                "source_id": video_id,
                "status": "unsupported_video_too_long_for_whisper",
                "ready": False,
                "method": "whisper_exceeded",
                "time_seconds": t_elapsed,
                "error": f"Captions unavailable and video length ({int(dur // 60)}m) exceeds audio transcription limit ({int(max_duration // 60)}m)",
                "error_code": "AUDIO_TRANSCRIPTION_EXCEEDED",
                "detected_language": None,
                "supported_languages": ["en"],
                "duration_seconds": dur,
            }
        return {
            "video_id": video_id,
            "source_id": video_id,
            "status": "slow_recovery_required",
            "ready": False,
            "method": "whisper_required",
            "time_seconds": t_elapsed,
            "error": "Fast captions unavailable (audio download + Whisper recovery required)",
            "error_code": "TRANSCRIPT_UNAVAILABLE",
            "detected_language": None,
            "supported_languages": ["en"],
        }

    async def preflight_sources(self, video_ids: List[str], per_source_timeout: float = 20.0) -> dict:
        """
        Bounded concurrent preflight across all requested videos.
        Returns dict keyed by video_id with preflight status.
        """
        tasks = [self.preflight_source(vid, per_source_timeout) for vid in video_ids]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return {r["video_id"]: r for r in results}

    def summarize(self, text: str, max_length: int = 150, min_length: int = 40) -> str:
        """Summarize text using preloaded BART pipeline."""
        if not text or len(text) < 100:
            return text

        text = " ".join(text.split())[:4000]

        try:
            from .summarization_service import _get_pipeline
            summarizer = _get_pipeline()
            result = summarizer(
                text,
                max_length=max_length,
                min_length=min_length,
                do_sample=False,
            )
            return result[0]["summary_text"]
        except Exception as e:
            # Degrade to a truncated excerpt rather than failing the request —
            # but name the exception type, since a silent fallback here is what
            # masked the pipeline("summarization") failure for so long.
            print(f"[ERROR] Summarization failed ({type(e).__name__}): {e}")
            return text[:500] + "..."


# =====================================================
# SINGLETON FACTORY
# =====================================================

_service_instance = None


async def get_transcript_service():
    """Get or create TranscriptService singleton."""
    global _service_instance
    if _service_instance is None:
        from ..core.database import get_database
        db = await get_database()
        _service_instance = TranscriptService(db)
    return _service_instance
