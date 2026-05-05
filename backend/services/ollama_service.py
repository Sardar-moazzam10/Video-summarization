"""
Ollama Service — Free local LLM enrichment and chat.

Replaces Gemini for:
  - Structured summary enrichment (chapters, takeaways, quotes, TLDR)
  - "Chat with video" Q&A answer generation

Requires Ollama running locally: https://ollama.com/
Default model: llama3.2:3b (2 GB RAM, runs on CPU, ~5-15s per response)

Setup (one-time):
    curl -fsSL https://ollama.com/install.sh | sh
    ollama pull llama3.2:3b     # smallest, fastest
    # OR: ollama pull mistral:7b  # better quality, needs 8 GB RAM
    ollama serve                  # starts automatically on most systems

Override model via .env:
    OLLAMA_MODEL=mistral:7b
    OLLAMA_BASE_URL=http://localhost:11434
"""

import json
import re
import asyncio
from typing import Optional

import httpx

from ..core.config import get_settings

settings = get_settings()


# =====================================================
# PROMPTS
# =====================================================

RICH_SUMMARY_PROMPT = """You are an expert content analyst. Output ONLY valid JSON — no markdown, no code fences, no explanation.

Analyze the transcript narrative below and produce a JSON object with EXACTLY these keys:
- "summary": string (~{target_words} words, written in {style} style: {style_instruction})
- "key_takeaways": array of 3-7 concise strings (the most valuable insights)
- "best_quotes": array of objects with "text" and "speaker" (use "" for unknown speaker)
- "chapters": array of objects with "title" and "text" (2-3 sentences each chapter)
- "tldr": string (one sentence ultra-summary)
- "who_should_watch": string (1-2 sentences on who benefits from the full video)
- "who_can_skip": string (1-2 sentences on who can skip it)
- "action_steps": array of 2-5 concrete action strings

Source videos: {video_titles}

TRANSCRIPT NARRATIVE:
{narrative}

JSON output:"""


CHAT_PROMPT = """Answer the question using ONLY the context provided below. If the answer is not covered in the context, say exactly: "This information was not covered in the videos."
Be concise (2-4 sentences). When possible, cite which video the information comes from.

Question: {question}

Context from video transcripts:
{context}

Answer:"""


STYLE_INSTRUCTIONS = {
    "educational": "clear structured teaching tone, step-by-step explanations, use analogies",
    "casual": "conversational podcast-style, engaging and relatable, informal language",
    "executive": "concise business-briefing tone, lead with conclusions, focus on decisions and ROI",
    "beginner": "simple language with zero jargon, explain every concept as if reader is completely new",
    "detailed": "thorough nuanced analysis, include context, caveats, and multiple perspectives",
}


# =====================================================
# SERVICE
# =====================================================

class OllamaService:
    """
    Local LLM service via Ollama REST API (http://localhost:11434).

    Provides the same interface as GeminiService so it can be used
    as a drop-in replacement throughout the pipeline.

    All methods are async-friendly — synchronous HTTP calls are
    wrapped with asyncio.to_thread() to avoid blocking the event loop.
    """

    def __init__(self):
        self._base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self._model = settings.OLLAMA_MODEL
        self._timeout = settings.OLLAMA_TIMEOUT_SECONDS
        self._available: Optional[bool] = None  # Cached after first check

    def is_available(self) -> bool:
        """
        Check if Ollama daemon is running and the configured model is pulled.
        Result is cached after the first call.
        """
        if self._available is not None:
            return self._available

        try:
            resp = httpx.get(f"{self._base_url}/api/tags", timeout=3.0)
            if resp.status_code != 200:
                self._available = False
                print(f"[Ollama] Daemon returned HTTP {resp.status_code}")
                return False

            tags = resp.json().get("models", [])
            base_model = self._model.split(":")[0]
            found = any(
                base_model in t.get("name", "") or self._model in t.get("name", "")
                for t in tags
            )
            self._available = found

            if not found:
                pulled = [t.get("name", "") for t in tags]
                print(
                    f"[Ollama] Model '{self._model}' not found in pulled models: {pulled}\n"
                    f"         Run: ollama pull {self._model}"
                )
            else:
                print(f"[Ollama] Ready — model: {self._model}")

            return self._available

        except Exception as e:
            self._available = False
            print(f"[Ollama] Not reachable at {self._base_url}: {e}")
            return False

    # --------------------------------------------------
    # Core generation
    # --------------------------------------------------

    def _generate(self, prompt: str, expect_json: bool = False) -> str:
        """Synchronous Ollama /api/generate call. Run via asyncio.to_thread()."""
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.35,
                "num_predict": 1536,
            },
        }
        if expect_json:
            payload["format"] = "json"

        try:
            resp = httpx.post(
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")

        except httpx.TimeoutException:
            print(f"[Ollama] Timed out after {self._timeout}s — try a smaller model or increase OLLAMA_TIMEOUT_SECONDS")
            self._available = None  # reset so next request re-checks
            return ""
        except Exception as e:
            print(f"[Ollama] Generation error: {e}")
            self._available = None  # reset so next request re-checks
            return ""

    def _parse_json(self, text: str) -> Optional[dict]:
        """
        Parse JSON from Ollama response, handling the three most common
        formatting issues: plain JSON, markdown code fences, stray prefix text.
        """
        text = text.strip()

        # Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strip markdown code fences  ```json ... ```
        match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Find first { to last }
        first = text.find('{')
        last = text.rfind('}')
        if first != -1 and last > first:
            try:
                return json.loads(text[first:last + 1])
            except json.JSONDecodeError:
                pass

        return None

    # --------------------------------------------------
    # Rich summary enrichment (replaces GeminiService.generate_rich_summary)
    # --------------------------------------------------

    async def generate_rich_summary(
        self,
        narrative: str,
        target_words: int,
        style: str = "educational",
        video_titles: str = "",
    ):
        """
        Generate structured summary enrichment using local Ollama LLM.

        Returns a RichOutput instance (same model used by merge.py)
        or None if the call fails so the caller can use the TF-IDF fallback.
        """
        from ..models.job import RichOutput

        if not self.is_available():
            return None

        style_instruction = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS["educational"])

        words = narrative.split()
        # Truncate to 1500 words — llama3.2:3b on CPU needs a manageable context to prevent 360s timeouts
        if len(words) > 1500:
            narrative = " ".join(words[:1500])
            print(f"[Ollama] Narrative truncated to 1500 words for context window")

        prompt = RICH_SUMMARY_PROMPT.format(
            target_words=target_words,
            style=style,
            style_instruction=style_instruction,
            video_titles=video_titles or "Unknown",
            narrative=narrative,
        )

        print(f"[Ollama] Generating rich summary ({self._model}, style={style})...")
        raw = await asyncio.to_thread(self._generate, prompt, True)

        if not raw:
            print("[Ollama] Empty response")
            return None

        data = self._parse_json(raw)
        if not data:
            print("[Ollama] Could not parse JSON from response")
            return None

        summary = data.get("summary", "")
        print(
            f"[Ollama] Done: {len(summary.split())} words, "
            f"{len(data.get('chapters', []))} chapters, "
            f"{len(data.get('key_takeaways', []))} takeaways"
        )

        # Normalise quotes (can come as strings or dicts)
        raw_quotes = data.get("best_quotes", [])
        quotes = []
        for q in raw_quotes:
            if isinstance(q, dict):
                quotes.append({"text": q.get("text", ""), "speaker": q.get("speaker", "")})
            elif isinstance(q, str):
                quotes.append({"text": q, "speaker": ""})

        # Normalise chapters
        raw_chapters = data.get("chapters", [])
        chapters = [
            {"title": ch.get("title", ""), "text": ch.get("text", "")}
            for ch in raw_chapters
            if isinstance(ch, dict)
        ]

        return RichOutput(
            summary=summary,
            tldr=data.get("tldr", ""),
            key_takeaways=data.get("key_takeaways", []),
            best_quotes=quotes,
            chapters=chapters,
            who_should_watch=data.get("who_should_watch", ""),
            who_can_skip=data.get("who_can_skip", ""),
            action_steps=data.get("action_steps", []),
            style_applied=style,
        )

    # --------------------------------------------------
    # Chat Q&A (replaces GeminiService.answer_question)
    # --------------------------------------------------

    async def answer_question(self, question: str, context: str) -> Optional[str]:
        """
        Answer a natural-language question using retrieved transcript context.

        Returns None when unavailable so the caller falls back to raw FAISS segments.
        """
        if not self.is_available():
            return None

        prompt = CHAT_PROMPT.format(
            question=question,
            context=context[:8000],
        )

        print(f"[Ollama] Answering: {question[:80]}...")
        answer = await asyncio.to_thread(self._generate, prompt, False)
        return answer.strip() if answer else None


# =====================================================
# SINGLETON
# =====================================================

_service: Optional[OllamaService] = None


def get_ollama_service() -> OllamaService:
    """Get singleton Ollama service instance."""
    global _service
    if _service is None:
        _service = OllamaService()
    return _service
