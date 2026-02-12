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
import json
import subprocess
import tempfile
import time
from datetime import datetime
from typing import Optional, List, Dict, Tuple

from youtube_transcript_api import YouTubeTranscriptApi
from transformers import pipeline
from deep_translator import GoogleTranslator

# Lazy-loaded models
_summarizer = None


def get_summarizer():
    global _summarizer
    if _summarizer is None:
        _summarizer = pipeline("summarization", model="t5-small", tokenizer="t5-small")
    return _summarizer


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

        # Check cache first
        cached = await self.transcripts.find_one({"video_id": video_id})
        if cached:
            return {
                "transcript": cached["transcript"],
                "source": cached.get("source", "cache"),
                "cached": True,
            }

        # Tier 1: YouTube Transcript API (fastest)
        transcript = self._fetch_youtube_api(video_id)
        source = "youtube_api"

        # Tier 2: yt-dlp subtitle extraction
        if not transcript:
            transcript = self._fetch_ytdlp(video_id)
            source = "yt_dlp"

        # Tier 3: Whisper speech-to-text (last resort)
        if not transcript:
            transcript = self._fetch_whisper(video_id)
            source = "whisper"

        if not transcript:
            return None

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
        for attempt in range(max_retries + 1):
            try:
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

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
                            print(f"[Transcript] Fetched {transcript.language_code}, translating to English for {video_id}")
                            return self._translate_transcript_to_english(normalized)
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
        import shutil

        if not shutil.which("yt-dlp"):
            print("[Transcript] yt-dlp not found in PATH, skipping tier 2")
            return None

        url = f"https://www.youtube.com/watch?v={video_id}"

        # Approach 1: Download subtitle file to temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            for sub_lang in ["en", "en.*", "hi", "ur", "es", "fr", "de", ".*"]:
                try:
                    out_template = os.path.join(tmpdir, "sub")
                    cmd = [
                        "yt-dlp",
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
                                if sub_lang not in ("en", "en.*"):
                                    print(f"[Transcript] Translating yt-dlp {sub_lang} subs to English")
                                    transcript = self._translate_transcript_to_english(transcript)
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
                "yt-dlp",
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
        import shutil

        if not shutil.which("yt-dlp"):
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
                    "yt-dlp",
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
                    self._whisper_model = whisper.load_model("base")
                    print("[Transcript] Loaded Whisper base model")

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

    @staticmethod
    def _translate_transcript_to_english(transcript: list) -> list:
        """
        Translate transcript segments to English using Google Translate (free).
        Batches text to stay within API limits (5000 chars per request).
        """
        try:
            translator = GoogleTranslator(source="auto", target="en")
            # Batch segments to translate efficiently
            batch_texts = []
            batch_indices = []
            current_batch = ""
            current_indices = []

            for i, seg in enumerate(transcript):
                text = seg.get("text", "").strip()
                if not text:
                    continue
                # Google Translate limit is ~5000 chars per request
                if len(current_batch) + len(text) + 1 > 4500 and current_batch:
                    batch_texts.append(current_batch)
                    batch_indices.append(current_indices)
                    current_batch = text
                    current_indices = [i]
                else:
                    current_batch += ("\n" + text) if current_batch else text
                    current_indices.append(i)

            if current_batch:
                batch_texts.append(current_batch)
                batch_indices.append(current_indices)

            # Translate each batch
            for batch_idx, batch_text in enumerate(batch_texts):
                translated = translator.translate(batch_text)
                if translated:
                    translated_lines = translated.split("\n")
                    indices = batch_indices[batch_idx]
                    for j, idx in enumerate(indices):
                        if j < len(translated_lines):
                            transcript[idx]["text"] = translated_lines[j]

            print(f"[Transcript] Translated {len(transcript)} segments to English")
            return transcript
        except Exception as e:
            print(f"[Transcript] Google Translate failed: {e}, returning original")
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
            print(f"[ERROR] Summarization failed: {e}")
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
