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

import re
import os
import sys
import json
import shutil
import importlib.util
import subprocess
import tempfile
import time
from datetime import datetime
from typing import Optional, List

from youtube_transcript_api import YouTubeTranscriptApi


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

_summarizer_model = None
_summarizer_tokenizer = None

_SUMMARIZER_MODEL_NAME = "t5-small"
_SUMMARIZER_PREFIX = "summarize: "   # T5 is prefix-conditioned; without this it copies input
_SUMMARIZER_MAX_INPUT_TOKENS = 512   # t5-small's encoder window


def _load_summarizer():
    """Lazy-load the T5 tokenizer + model once per process."""
    global _summarizer_model, _summarizer_tokenizer

    if _summarizer_model is None:
        import warnings
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        from ..core.config import get_hf_token

        hf_token = get_hf_token()  # None when unset → anonymous, same as before
        print(f"[Transcript] Loading summarizer: {_SUMMARIZER_MODEL_NAME}")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
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

    async def get_transcript(self, video_id: str) -> Optional[dict]:
        """
        Get transcript with caching and 3-tier fallbacks.

        Args:
            video_id: YouTube video ID or full URL

        Returns:
            Dict with transcript, source, and cached flag, or None
        """
        # Extract clean video ID from URL if needed
        video_id = extract_video_id(video_id)

        # Check cache first. A cached transcript is only reusable if it still
        # holds a plausible timeline — see _transcript_is_sane(). Entries written
        # by the old newline-realignment translator do not, and reusing them
        # silently reproduces the original corruption on every later run.
        cached = await self.transcripts.find_one({"video_id": video_id})
        if cached:
            if self._transcript_is_sane(cached.get("transcript")):
                return {
                    "transcript": cached["transcript"],
                    "source": cached.get("source", "cache"),
                    "cached": True,
                }
            print(f"[Transcript] Cached transcript for {video_id} failed the sanity "
                  f"check — refetching instead of reusing it")

        # Tier 1: YouTube Transcript API (fastest)
        transcript = self._fetch_youtube_api(video_id)
        source = "youtube_api"

        # Tier 2: yt-dlp subtitle extraction
        if not transcript:
            transcript = self._fetch_ytdlp(video_id)
            source = "yt_dlp"

        # Language gate.
        #
        # Captions come back in whatever language the uploader published. The rest
        # of the pipeline is English-only: BGE embeddings, BART, the TF-IDF scorer
        # and the FAISS index are all English models, and a summary written in the
        # source language is not what the user asked for.
        #
        # Two paths, cheapest first, because this runs inside a user-facing job:
        #
        #   1. Translate the captions in place (~30s for a 630-segment
        #      transcript — batched, see translation_service).
        #   2. Re-transcribe the audio with Whisper's translate task (~7 minutes
        #      for a 25-minute video at 3.4x realtime on CPU).
        #
        # Whisper produces better text — its segments end on sentence boundaries
        # and are punctuated, where translated captions keep YouTube's arbitrary
        # mid-sentence cuts. But that is the same fragmentation every English
        # video already goes through, so the fast path lands a non-English video
        # at parity with an English one, and 7 minutes of extra job latency is
        # not worth buying more than parity by default.
        #
        # Whisper therefore runs only when the fast path did not actually produce
        # English — no network, a rate limit, or a translator that passed the text
        # through unchanged. The result is verified rather than assumed.
        if transcript:
            lang = self._detect_transcript_language(transcript)
            if lang != "en":
                print(f"[Transcript] {video_id} captions are '{lang}' — translating captions")
                transcript = self._translate_transcript_to_english(transcript, lang)

                if self._detect_transcript_language(transcript) == "en":
                    source = f"{source}+translated"
                else:
                    print("[Transcript] Caption translation did not yield English — "
                          "re-transcribing with Whisper (task=translate)")
                    whisper_transcript = self._fetch_whisper(video_id)
                    if whisper_transcript:
                        transcript = whisper_transcript
                        source = "whisper_translate"
                    else:
                        print("[Transcript] Whisper unavailable too — keeping the "
                              "best-effort translation")
                        source = f"{source}+partial"

        # Tier 3: Whisper speech-to-text (last resort)
        if not transcript:
            transcript = self._fetch_whisper(video_id)
            source = "whisper"

        if not transcript:
            return None

        if not self._transcript_is_sane(transcript):
            print(f"[Transcript] WARNING: transcript for {video_id} looks malformed "
                  f"(source={source}); caching it anyway but downstream quality will suffer")

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

        return {"transcript": transcript, "source": source, "cached": False}

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
    def _fetch_ytdlp(self, video_id: str) -> Optional[list]:
        """
        Fallback: Download subtitles via yt-dlp.
        Tries auto-subs in multiple languages.
        """
        ytdlp = _ytdlp_cmd()
        if ytdlp is None:
            print("[Transcript] yt-dlp not installed (pip install yt-dlp), skipping tier 2")
            return None

        url = f"https://www.youtube.com/watch?v={video_id}"

        # Approach 1: Download subtitle file to temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            for sub_lang in ["en", "en.*", "hi", "ur", "es", "fr", "de", ".*"]:
                try:
                    out_template = os.path.join(tmpdir, "sub")
                    cmd = [
                        *ytdlp,
                        "--write-auto-sub",
                        "--skip-download",
                        "--sub-lang", sub_lang,
                        "--sub-format", "json3",
                        "--output", out_template,
                        "--no-warnings",
                        "--quiet",
                        url,
                    ]

                    if os.path.exists(self.cookie_path):
                        cmd.extend(["--cookies", self.cookie_path])

                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=90
                    )

                    if result.returncode != 0:
                        continue

                    # Find the downloaded subtitle file
                    for fname in os.listdir(tmpdir):
                        if fname.endswith(".json3"):
                            fpath = os.path.join(tmpdir, fname)
                            with open(fpath, "r", encoding="utf-8") as f:
                                data = json.load(f)

                            transcript = self._parse_json3_subtitles(data)
                            if transcript:
                                print(f"[Transcript] yt-dlp got subs (lang={sub_lang}) for {video_id}")
                                # Original language kept — get_transcript() decides.
                                return transcript

                except subprocess.TimeoutExpired:
                    print(f"[Transcript] yt-dlp timed out for lang={sub_lang}")
                    continue
                except Exception as e:
                    print(f"[Transcript] yt-dlp error for lang={sub_lang}: {e}")
                    continue

        # Approach 2: Try --print subtitle (older yt-dlp fallback)
        try:
            cmd = [
                *ytdlp,
                "--write-auto-sub", "--skip-download",
                "--sub-lang", "en", "--sub-format", "json3",
                "--no-warnings", "--quiet", "--print", "subtitle",
                url,
            ]
            if os.path.exists(self.cookie_path):
                cmd.extend(["--cookies", self.cookie_path])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
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
    def _fetch_whisper(self, video_id: str) -> Optional[list]:
        """
        Last resort: Download audio and transcribe with OpenAI Whisper.
        Slower but works for any video with audio.
        """
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

            # Download audio only
            try:
                cmd = [
                    *ytdlp,
                    "--extract-audio",
                    "--audio-format", "mp3",
                    "--audio-quality", "5",  # Medium quality (faster download)
                    "--output", f"{audio_out}.%(ext)s",
                    "--no-warnings",
                    "--quiet",
                    "--no-playlist",
                    url,
                ]
                if os.path.exists(self.cookie_path):
                    cmd.extend(["--cookies", self.cookie_path])

                subprocess.run(cmd, capture_output=True, text=True, timeout=300)

                # Find the downloaded audio file
                actual_audio = None
                for fname in os.listdir(tmpdir):
                    if fname.endswith((".mp3", ".m4a", ".wav", ".webm", ".opus")):
                        actual_audio = os.path.join(tmpdir, fname)
                        break

                if not actual_audio or not os.path.exists(actual_audio):
                    print(f"[Transcript] Audio download failed for {video_id}")
                    return None

                print(f"[Transcript] Audio downloaded, running Whisper for {video_id}...")

            except subprocess.TimeoutExpired:
                print(f"[Transcript] Audio download timed out for {video_id}")
                return None
            except Exception as e:
                print(f"[Transcript] Audio download error: {e}")
                return None

            # Transcribe with Whisper
            try:
                if self._whisper_model is None:
                    model_name = _whisper_model_name()
                    self._whisper_model = whisper.load_model(model_name)
                    print(f"[Transcript] Loaded Whisper {model_name} model")

                result = self._whisper_model.transcribe(
                    actual_audio,
                    task="translate",
                    fp16=False,
                )

                transcript = []
                for segment in result.get("segments", []):
                    transcript.append({
                        "text": segment["text"].strip(),
                        "start": segment["start"],
                        "duration": segment["end"] - segment["start"],
                    })

                if transcript:
                    print(f"[Transcript] Whisper transcribed {len(transcript)} segments for {video_id}")
                    return transcript

            except Exception as e:
                print(f"[Transcript] Whisper transcription failed: {e}")

        return None

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

    def summarize(self, text: str, max_length: int = 150, min_length: int = 50) -> str:
        """Summarize text using T5-small (legacy endpoint)."""
        if not text or len(text) < 100:
            return text

        text = " ".join(text.split())[:4000]

        try:
            summarizer = get_summarizer()
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
