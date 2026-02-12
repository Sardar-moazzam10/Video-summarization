"""
Hierarchical Summarization Service - BART-large-CNN

Replaces the simple T5-small single-pass approach with a multi-pass
hierarchical strategy using BART-large-CNN (1024 token input limit).

Pipeline:
  1. Split text into chunks of ~800-900 words (within BART's limit)
  2. Summarize each chunk independently with style-specific params
  3. Concatenate chunk summaries
  4. If combined text exceeds target, run a second summarization pass
  5. Return final text matching the duration profile's target_words
"""

from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from transformers import pipeline as hf_pipeline
from ..core.config import get_settings
from .duration_profiles import DurationProfile, get_summarization_config

settings = get_settings()

# Lazy-loaded model
_summarization_pipeline = None


def _get_pipeline():
    """Lazy load BART-large-CNN summarization pipeline."""
    global _summarization_pipeline
    if _summarization_pipeline is None:
        model_name = settings.SUMMARIZATION_MODEL  # "facebook/bart-large-cnn"
        print(f"[Summarizer] Loading model: {model_name}")
        _summarization_pipeline = hf_pipeline(
            "summarization",
            model=model_name,
            tokenizer=model_name,
        )
        print(f"[Summarizer] Model loaded successfully")
    return _summarization_pipeline


class SummarizationService:
    """
    Hierarchical summarization service using BART-large-CNN.

    Handles arbitrarily long inputs by chunking, summarizing per-chunk,
    then recursively summarizing the merged result until the target
    word count is reached.
    """

    def __init__(self):
        self.max_chunk_words = 800  # Safe limit for BART's 1024 tokens
        self.max_recursion = 3      # Prevent infinite recursion

    def hierarchical_summarize(
        self,
        text: str,
        target_words: int,
        profile: DurationProfile,
    ) -> str:
        """
        Main entry point for hierarchical summarization.

        Args:
            text: Full text to summarize (can be any length)
            target_words: Target output word count
            profile: Duration profile with style parameters

        Returns:
            Summarized text approximately matching target_words
        """
        if not text or not text.strip():
            return ""

        text = self._clean_text(text)
        word_count = len(text.split())

        # If text is already shorter than target, return as-is
        if word_count <= target_words:
            return text

        # Get style-specific model parameters
        config = get_summarization_config(profile)

        # Run hierarchical summarization
        result = self._recursive_summarize(text, target_words, config, depth=0)

        return result

    def _recursive_summarize(
        self,
        text: str,
        target_words: int,
        config,
        depth: int,
    ) -> str:
        """
        Recursively summarize text until target_words is reached.

        Level 0: Chunk original text → summarize each chunk
        Level 1: If merged summaries still too long → summarize again
        Level N: Stop at max_recursion or when target is met
        """
        word_count = len(text.split())

        # Base case: text is short enough or max depth reached
        if word_count <= target_words * 1.15 or depth >= self.max_recursion:
            # Final pass: if still over target, do one tight summarize
            if word_count > target_words * 1.15 and word_count <= self.max_chunk_words * 1.2:
                return self._summarize_chunk(text, target_words, config)
            return text

        # Split into chunks
        chunks = self._split_into_chunks(text, self.max_chunk_words)

        if len(chunks) == 1:
            # Single chunk: direct summarization
            # Calculate per-chunk target proportionally
            return self._summarize_chunk(chunks[0], target_words, config)

        # Multi-chunk: summarize each chunk in parallel
        chunk_target = max(50, target_words // len(chunks))
        chunk_tasks = []

        for i, chunk in enumerate(chunks):
            chunk_words = len(chunk.split())
            adjusted_target = max(50, int(chunk_target * (chunk_words / (word_count / len(chunks)))))
            adjusted_target = min(adjusted_target, chunk_words)
            chunk_tasks.append((chunk, adjusted_target))

        summaries = [None] * len(chunk_tasks)
        with ThreadPoolExecutor(max_workers=min(len(chunk_tasks), 3)) as executor:
            futures = {
                executor.submit(self._summarize_chunk, chunk, target, config): idx
                for idx, (chunk, target) in enumerate(chunk_tasks)
            }
            for future in as_completed(futures):
                idx = futures[future]
                summaries[idx] = future.result()

        # Merge chunk summaries
        merged = " ".join(summaries)
        merged_words = len(merged.split())

        # If merged is still too long, recurse
        if merged_words > target_words * 1.15:
            return self._recursive_summarize(merged, target_words, config, depth + 1)

        return merged

    def _summarize_chunk(self, text: str, target_words: int, config) -> str:
        """
        Summarize a single chunk using BART-large-CNN.

        Args:
            text: Text chunk (should be within model's token limit)
            target_words: Approximate target word count for this chunk
            config: SummarizationConfig with model parameters
        """
        pipe = _get_pipeline()

        # Convert word targets to token estimates (1 word ≈ 1.3 tokens)
        max_length = min(config.max_output_length, max(int(target_words * 1.3), 100))
        min_length = max(config.min_output_length, int(target_words * 0.5))

        # Ensure min < max
        if min_length >= max_length:
            min_length = max(10, max_length // 2)

        try:
            result = pipe(
                text,
                max_length=max_length,
                min_length=min_length,
                num_beams=config.num_beams,
                length_penalty=config.length_penalty,
                early_stopping=config.early_stopping,
                do_sample=False,
            )
            return result[0]["summary_text"]
        except Exception as e:
            print(f"[Summarizer] Chunk summarization failed: {e}")
            # Fallback: return truncated text
            words = text.split()
            return " ".join(words[:target_words])

    @staticmethod
    def _split_into_chunks(text: str, max_words: int) -> list:
        """
        Split text into chunks of approximately max_words.
        Tries to split on paragraph/sentence boundaries.
        """
        # First try paragraph-level splitting
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        if not paragraphs:
            paragraphs = [text]

        chunks = []
        current_chunk = []
        current_words = 0

        for para in paragraphs:
            para_words = len(para.split())

            # If single paragraph is too long, split on sentences
            if para_words > max_words:
                # Flush current chunk
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = []
                    current_words = 0

                # Split long paragraph on sentences
                sentences = _split_sentences(para)
                for sent in sentences:
                    sent_words = len(sent.split())
                    if current_words + sent_words > max_words and current_chunk:
                        chunks.append(" ".join(current_chunk))
                        current_chunk = []
                        current_words = 0
                    current_chunk.append(sent)
                    current_words += sent_words
                continue

            # Normal paragraph: add to current chunk
            if current_words + para_words > max_words and current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_words = 0

            current_chunk.append(para)
            current_words += para_words

        # Don't forget the last chunk
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks

    @staticmethod
    def _clean_text(text: str) -> str:
        """Clean text for summarization."""
        import re
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove very short lines (often artifacts)
        lines = text.split('\n')
        lines = [l.strip() for l in lines if len(l.strip()) > 10]
        return ' '.join(lines).strip()


def _split_sentences(text: str) -> list:
    """Split text into sentences."""
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


# =====================================================
# SINGLETON
# =====================================================

_service = None


def get_summarization_service() -> SummarizationService:
    """Get singleton summarization service."""
    global _service
    if _service is None:
        _service = SummarizationService()
    return _service
