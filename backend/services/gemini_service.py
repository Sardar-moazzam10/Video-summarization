"""
Gemini AI Service — Primary intelligence engine for rich summarization
and video highlight extraction.

Uses Google's Gemini via the google.genai SDK:
- Gemini 2.0 Flash: Rich text summarization (chapters, takeaways, quotes)
- Gemini 3 Pro: Native video understanding + Thinking mode for highlight identification

Falls back to BART-large-CNN / transcript heuristics if Gemini is unavailable.
"""

import json
import re
import time
import asyncio
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

from google import genai
from google.genai import types

from ..core.config import get_settings

settings = get_settings()

# =====================================================
# OUTPUT MODELS
# =====================================================

@dataclass
class QuoteInfo:
    text: str
    speaker: str = ""

@dataclass
class ChapterInfo:
    title: str
    text: str

@dataclass
class RichSummaryOutput:
    summary: str = ""
    key_takeaways: list = field(default_factory=list)
    best_quotes: list = field(default_factory=list)
    chapters: list = field(default_factory=list)
    who_should_watch: str = ""
    who_can_skip: str = ""
    action_steps: list = field(default_factory=list)
    tldr: str = ""
    style_applied: str = "educational"

    def to_dict(self) -> dict:
        return asdict(self)


# =====================================================
# STYLE PRESETS
# =====================================================

STYLE_INSTRUCTIONS = {
    "educational": (
        "Use a clear, structured teaching tone. Explain concepts step by step. "
        "Use analogies where helpful. Organize into logical learning sections."
    ),
    "casual": (
        "Use a conversational, podcast-style tone. Be engaging and relatable. "
        "Use informal language, rhetorical questions, and natural transitions."
    ),
    "executive": (
        "Use a concise, business-briefing tone. Lead with conclusions. "
        "Focus on decisions, ROI, and actionable outcomes. No fluff."
    ),
    "beginner": (
        "Use simple language with zero jargon. Explain every concept as if the "
        "reader is encountering it for the first time. Use everyday analogies."
    ),
    "detailed": (
        "Provide thorough, nuanced analysis. Include context, caveats, and "
        "multiple perspectives. Don't oversimplify — depth matters."
    ),
}


# =====================================================
# PROMPT TEMPLATE
# =====================================================

RICH_SUMMARY_PROMPT = """You are an expert content analyst and summarizer. Analyze this transcript and produce a structured summary.

**RULES:**
- The "summary" field must be approximately {target_words} words (within ±15%).
- Write in {style_name} style: {style_instruction}
- Return ONLY valid JSON, no markdown, no code fences.
- All text must be in English.

**SOURCE VIDEOS:** {video_titles}

**Return this exact JSON structure:**
{{
  "summary": "The main summary at approximately {target_words} words",
  "key_takeaways": ["3-7 bullet points of the most valuable insights"],
  "best_quotes": [{{"text": "Notable quote from the content", "speaker": "Speaker name if known"}}],
  "chapters": [{{"title": "Chapter title", "text": "Chapter content - 2-4 sentences"}}],
  "who_should_watch": "1-2 sentences on who benefits from the full video",
  "who_can_skip": "1-2 sentences on who can skip",
  "action_steps": ["Concrete action items the viewer can take"],
  "tldr": "Single sentence ultra-summary"
}}

**TRANSCRIPT:**
{narrative}"""


# =====================================================
# HIGHLIGHT EXTRACTION PROMPT (Gemini 3 Pro + Video)
# =====================================================

HIGHLIGHT_PROMPT = """Analyze this video and identify exactly {num_highlights} of the most compelling, important, or entertaining moments that would make an excellent highlight reel.

**RULES:**
- Total highlight duration must be approximately {target_seconds} seconds.
- Each clip should be between 5 and 30 seconds long.
- Choose moments that are visually or verbally impactful: key arguments, dramatic reveals, humor, demonstrations, important conclusions.
- Ensure the transitions between clips are logical for a cohesive summary.
- Spread clips across different parts of the video for variety.
- Return ONLY valid JSON, no markdown, no code fences.
- Timestamps must be in seconds (float).

**Return this exact JSON structure:**
{{
  "highlights": [
    {{
      "start": 45.0,
      "end": 65.0,
      "reason": "Brief explanation of why this is a highlight",
      "importance_score": 0.95
    }}
  ]
}}"""


# =====================================================
# CHAT PROMPT (for "Chat with Video" feature)
# =====================================================

CHAT_ANSWER_PROMPT = """Answer this question based ONLY on the provided video transcript context.
If the answer is not in the context, say "This information was not covered in the videos."

Be concise (2-4 sentences) and cite which video the information comes from when possible.

**Question:** {question}

**Context from videos:**
{context}

**Answer:**"""


# =====================================================
# SERVICE
# =====================================================

class GeminiService:
    """Wraps Google Gemini API for rich structured summarization."""

    def __init__(self):
        self._client = None
        self._api_key = settings.GEMINI_API_KEY
        self._model_name = settings.GEMINI_MODEL
        self._video_model_name = settings.GEMINI_VIDEO_MODEL
        self._max_retries = 3

    def is_available(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    def _get_client(self):
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
            print(f"[Gemini] Client initialized: {self._model_name}")
        return self._client

    async def generate_rich_summary(
        self,
        narrative: str,
        target_words: int,
        style: str = "educational",
        video_titles: str = "",
    ) -> RichSummaryOutput:
        """
        Send full narrative to Gemini and get structured JSON output.

        Args:
            narrative: Full transcript/fusion text (can be any length)
            target_words: Target word count for the summary
            style: One of: educational, casual, executive, beginner, detailed
            video_titles: Comma-separated video titles for context

        Returns:
            RichSummaryOutput with all structured fields
        """
        if not self.is_available():
            print("[Gemini] Not available — no API key configured")
            return RichSummaryOutput(style_applied=style)

        style_instruction = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS["educational"])

        prompt = RICH_SUMMARY_PROMPT.format(
            target_words=target_words,
            style_name=style,
            style_instruction=style_instruction,
            video_titles=video_titles or "Unknown",
            narrative=narrative,
        )

        # Run in thread to avoid blocking async loop
        result = await asyncio.to_thread(
            self._call_with_retry, prompt, style
        )
        return result

    def _call_with_retry(self, prompt: str, style: str) -> RichSummaryOutput:
        """Call Gemini with retries that respect server retry-after hints."""
        client = self._get_client()

        for attempt in range(self._max_retries):
            try:
                print(f"[Gemini] Attempt {attempt + 1}/{self._max_retries}...")
                response = client.models.generate_content(
                    model=self._model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.7,
                        max_output_tokens=8192,
                    ),
                )

                if not response.text:
                    print(f"[Gemini] Empty response on attempt {attempt + 1}")
                    continue

                return self._parse_response(response.text, style)

            except Exception as e:
                error_msg = str(e)
                print(f"[Gemini] Attempt {attempt + 1} failed: {error_msg[:200]}")

                # Quota errors: no point retrying, fail fast immediately
                if '429' in error_msg or 'RESOURCE_EXHAUSTED' in error_msg:
                    print("[Gemini] Quota limit hit — skipping retries, using local fallback")
                    break

                if attempt < self._max_retries - 1:
                    # Parse retry delay from error if available
                    wait = self._parse_retry_delay(error_msg, default=2 ** (attempt + 1))
                    # Cap at 60s to not hang forever
                    wait = min(wait, 60)
                    print(f"[Gemini] Retrying in {wait}s...")
                    time.sleep(wait)

        print("[Gemini] All retries exhausted — returning empty output")
        return RichSummaryOutput(style_applied=style)

    @staticmethod
    def _parse_retry_delay(error_msg: str, default: float) -> float:
        """Extract retry delay from Gemini 429 error message."""
        match = re.search(r'retry in (\d+(?:\.\d+)?)s', error_msg, re.IGNORECASE)
        if match:
            return float(match.group(1)) + 1  # Add 1s buffer
        return default

    def _parse_response(self, text: str, style: str) -> RichSummaryOutput:
        """Parse Gemini JSON response into RichSummaryOutput."""
        # Try direct JSON parse first
        try:
            data = json.loads(text)
            return self._dict_to_output(data, style)
        except json.JSONDecodeError:
            pass

        # Fallback: extract JSON from markdown code fences
        json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                return self._dict_to_output(data, style)
            except json.JSONDecodeError:
                pass

        # Last resort: find first { to last }
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        if first_brace != -1 and last_brace > first_brace:
            try:
                data = json.loads(text[first_brace:last_brace + 1])
                return self._dict_to_output(data, style)
            except json.JSONDecodeError:
                pass

        print(f"[Gemini] Failed to parse JSON response, using raw text as summary")
        return RichSummaryOutput(summary=text.strip(), style_applied=style)

    @staticmethod
    def _dict_to_output(data: dict, style: str) -> RichSummaryOutput:
        """Convert parsed dict to RichSummaryOutput safely."""
        output = RichSummaryOutput(
            summary=data.get("summary", ""),
            key_takeaways=data.get("key_takeaways", []),
            who_should_watch=data.get("who_should_watch", ""),
            who_can_skip=data.get("who_can_skip", ""),
            action_steps=data.get("action_steps", []),
            tldr=data.get("tldr", ""),
            style_applied=style,
        )

        # Parse quotes
        raw_quotes = data.get("best_quotes", [])
        output.best_quotes = []
        for q in raw_quotes:
            if isinstance(q, dict):
                output.best_quotes.append({
                    "text": q.get("text", ""),
                    "speaker": q.get("speaker", ""),
                })
            elif isinstance(q, str):
                output.best_quotes.append({"text": q, "speaker": ""})

        # Parse chapters
        raw_chapters = data.get("chapters", [])
        output.chapters = []
        for ch in raw_chapters:
            if isinstance(ch, dict):
                output.chapters.append({
                    "title": ch.get("title", ""),
                    "text": ch.get("text", ""),
                })

        print(f"[Gemini] Parsed: {len(output.summary.split())} words, "
              f"{len(output.chapters)} chapters, "
              f"{len(output.key_takeaways)} takeaways")
        return output

    # =====================================================
    # GEMINI 3 PRO — VIDEO HIGHLIGHT EXTRACTION
    # =====================================================

    async def identify_highlights_from_video(
        self,
        video_id: str,
        video_file_path: str,
        target_seconds: int = 120,
        num_highlights: int = 8,
    ) -> list:
        """
        Upload video to Gemini File API, then use Gemini 3 Pro
        with Thinking mode (high) to identify the best highlight clips.

        Args:
            video_id: YouTube video ID (for tagging results)
            video_file_path: Local path to downloaded video file
            target_seconds: Target total highlight duration in seconds
            num_highlights: Number of clips to identify

        Returns:
            List of dicts: [{video_id, start_time, end_time, reason, importance_score}]
        """
        if not self.is_available():
            print("[Gemini3] Not available — using transcript fallback")
            return []

        try:
            result = await asyncio.to_thread(
                self._identify_highlights_sync,
                video_id, video_file_path, target_seconds, num_highlights,
            )
            return result
        except Exception as e:
            print(f"[Gemini3] Video analysis failed: {e}")
            return []

    def _identify_highlights_sync(
        self,
        video_id: str,
        video_file_path: str,
        target_seconds: int,
        num_highlights: int,
    ) -> list:
        """Synchronous implementation of video highlight identification."""
        client = self._get_client()

        # Step 1: Upload video to Gemini File API
        print(f"[Gemini3] Uploading video {video_id} to File API...")
        video_file = client.files.upload(path=video_file_path)
        print(f"[Gemini3] Upload complete: {video_file.name}")

        # Step 2: Wait for file processing if needed
        import time as _time
        max_wait = 120  # Max 2 minutes
        waited = 0
        while video_file.state and str(video_file.state) == "PROCESSING" and waited < max_wait:
            _time.sleep(5)
            waited += 5
            video_file = client.files.get(name=video_file.name)
            print(f"[Gemini3] Waiting for file processing... ({waited}s)")

        # Step 3: Build prompt
        prompt = HIGHLIGHT_PROMPT.format(
            num_highlights=num_highlights,
            target_seconds=target_seconds,
        )

        # Step 4: Send video + prompt with Thinking mode
        print(f"[Gemini3] Analyzing video with {self._video_model_name} (thinking: high)...")
        for attempt in range(self._max_retries):
            try:
                response = client.models.generate_content(
                    model=self._video_model_name,
                    contents=[video_file, prompt],
                    config=types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(
                            thinking_level="high",
                        ),
                        response_mime_type="application/json",
                        max_output_tokens=4096,
                    ),
                )

                if not response.text:
                    print(f"[Gemini3] Empty response on attempt {attempt + 1}")
                    continue

                # Step 5: Parse response
                highlights = self._parse_highlights(response.text, video_id)
                print(f"[Gemini3] Identified {len(highlights)} highlights for {video_id}")

                # Clean up uploaded file
                try:
                    client.files.delete(name=video_file.name)
                except Exception:
                    pass

                return highlights

            except Exception as e:
                error_msg = str(e)
                print(f"[Gemini3] Attempt {attempt + 1} failed: {error_msg[:200]}")
                if attempt < self._max_retries - 1:
                    wait = self._parse_retry_delay(error_msg, default=2 ** (attempt + 2))
                    wait = min(wait, 60)
                    print(f"[Gemini3] Retrying in {wait}s...")
                    _time.sleep(wait)

        print("[Gemini3] All retries exhausted")
        return []

    def _parse_highlights(self, text: str, video_id: str) -> list:
        """Parse highlight JSON from Gemini response."""
        # Try direct parse
        data = None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try extracting from code fences
            match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
            if match:
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass

            if data is None:
                first = text.find('{')
                last = text.rfind('}')
                if first != -1 and last > first:
                    try:
                        data = json.loads(text[first:last + 1])
                    except json.JSONDecodeError:
                        pass

        if not data:
            print(f"[Gemini3] Failed to parse highlight JSON")
            return []

        raw_highlights = data.get("highlights", [])
        parsed = []
        for h in raw_highlights:
            if isinstance(h, dict) and "start" in h and "end" in h:
                parsed.append({
                    "video_id": video_id,
                    "start_time": float(h["start"]),
                    "end_time": float(h["end"]),
                    "reason": h.get("reason", ""),
                    "importance_score": float(h.get("importance_score", 0.5)),
                })

        return parsed

    def identify_highlights_from_transcript(
        self,
        video_id: str,
        segments: list,
        target_seconds: int = 120,
    ) -> list:
        """
        Fallback: Select highlights from transcript segments using
        text-length heuristic (information density proxy).

        Used when Gemini is unavailable or video upload fails.
        """
        if not segments:
            return []

        # Score by text length (more words = more information)
        scored = []
        for seg in segments:
            text = seg.get("text", "")
            start = float(seg.get("start", 0))
            duration = float(seg.get("duration", 5))
            scored.append({
                "video_id": video_id,
                "start_time": start,
                "end_time": start + duration,
                "reason": "High information density",
                "importance_score": len(text.split()) / 50.0,
                "text_len": len(text),
            })

        # Sort by text length descending
        scored.sort(key=lambda s: s["text_len"], reverse=True)

        selected = []
        total_duration = 0.0
        for seg in scored:
            if total_duration >= target_seconds:
                break
            dur = seg["end_time"] - seg["start_time"]
            if dur < 2 or dur > 60:
                continue
            selected.append({
                "video_id": seg["video_id"],
                "start_time": seg["start_time"],
                "end_time": seg["end_time"],
                "reason": seg["reason"],
                "importance_score": min(seg["importance_score"], 1.0),
            })
            total_duration += dur

        # Sort chronologically
        selected.sort(key=lambda s: s["start_time"])
        return selected

    # =====================================================
    # CHAT WITH VIDEO — Answer questions using context
    # =====================================================

    async def answer_question(self, question: str, context: str) -> str:
        """
        Generate a concise answer to a question using transcript context.

        Uses Gemini Flash for speed (not Pro — chat should be fast).
        """
        if not self.is_available():
            return context[:500] if context else "No information available."

        prompt = CHAT_ANSWER_PROMPT.format(
            question=question,
            context=context[:15000],
        )

        result = await asyncio.to_thread(self._call_simple, prompt)
        return result

    def _call_simple(self, prompt: str) -> str:
        """Simple text generation (no JSON parsing needed)."""
        client = self._get_client()
        try:
            response = client.models.generate_content(
                model=self._model_name,  # Use Flash for speed
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=500,
                ),
            )
            return response.text or "Unable to generate answer."
        except Exception as e:
            print(f"[Gemini] Chat answer failed: {e}")
            return "Unable to generate answer at this time."


# =====================================================
# SINGLETON
# =====================================================

_service = None


def get_gemini_service() -> GeminiService:
    """Get singleton Gemini service."""
    global _service
    if _service is None:
        _service = GeminiService()
    return _service
