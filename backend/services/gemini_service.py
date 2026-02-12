"""
Gemini AI Service — Primary intelligence engine for rich summarization.

Uses Google's Gemini (1M token context) via the new google.genai SDK
to produce structured JSON output with chapters, takeaways, quotes,
and style-controlled summaries.

Falls back to BART-large-CNN if Gemini is unavailable.
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
# SERVICE
# =====================================================

class GeminiService:
    """Wraps Google Gemini API for rich structured summarization."""

    def __init__(self):
        self._client = None
        self._api_key = settings.GEMINI_API_KEY
        self._model_name = settings.GEMINI_MODEL
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
# SINGLETON
# =====================================================

_service = None


def get_gemini_service() -> GeminiService:
    """Get singleton Gemini service."""
    global _service
    if _service is None:
        _service = GeminiService()
    return _service
