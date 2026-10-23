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

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..core.config import get_settings
from .duration_profiles import DurationProfile, get_summarization_config
from .grounding_check import check_grounding

settings = get_settings()

# =====================================================
# OUTPUT-SIDE DEGENERATION GUARD
# =====================================================
#
# assess_coherence() in summarization_policy.py only ever looks at the text
# BEFORE it reaches BART (fusion-connective density, fragments, adjacent
# restatement in the fused narrative). Nothing anywhere inspected what BART
# actually generated, so beam-search degeneration reached users unfiltered —
# e.g. a real 30-minute COMPRESS job producing "...not to worry. You're not
# to fear. You're not in fear. I just want to be scared. I'm scared...":
# different token sequences each time, so no_repeat_ngram_size=3 (which only
# blocks an exact repeated 3-gram) never caught it, and repetition_penalty
# was silently never applied (see the bug fixed in _get_pipeline above).
#
# Below MIN_WORDS_TO_JUDGE, both n-gram and sentence stats are too noisy to
# judge reliably — a 20-word chunk naturally repeats "the"/"a" a lot, and
# short chunks are skipped by the caller anyway.
DEGENERATION_MIN_WORDS = 40

# n-gram repetition ratio = (occurrences beyond the first) / (total n-grams).
# n=4/n=6 do NOT work here: this degeneration is paraphrase-level ("not to
# worry" / "not to fear" / "not in fear" — different words, same 2-word
# skeleton), so exact 4+ word repeats never occur even in the real sample.
# Bigrams separate cleanly, measured directly on real text:
#   the real garbled paragraph reproduced in the module docstring above: 0.183
#   a paragraph that deliberately reuses one key phrase for emphasis:    0.036
#   ordinary multi-sentence prose:                                       0.000
#   a literal 8x repeated sentence (unambiguous degeneration):           0.873
# 0.10 sits between legitimate reuse and the real failure case.
NGRAM_REPETITION_THRESHOLDS = {2: 0.10, 3: 0.06}

# A run of near-duplicate short sentences ("I'm scared. You don't want to
# worry about it...") collapses sentence-level diversity even when no single
# n-gram repeats often enough to trip the threshold above. Only checked once
# there are enough sentences for the ratio to mean something.
MIN_SENTENCES_FOR_CHECK = 6
MIN_UNIQUE_SENTENCE_RATIO = 0.7

# "Compression" that returns >85% of the input length AND >1.5x the requested
# target is not a summary — it's BART failing to compress and echoing the
# input back with cosmetic edits.
NEAR_COPY_LENGTH_RATIO = 0.85
NEAR_COPY_TARGET_MULTIPLE = 1.5

# =====================================================
# INPUT-AWARE GENERATION-LENGTH CAP
# =====================================================
#
# A style's min_output_length (e.g. COMPREHENSIVE=450) is a per-style output
# floor, not a promise that any given input actually contains 450 words of
# non-redundant content. On the real anchor case (job YIszsqhLGIs, 745-word
# fusion narrative, COMPREHENSIVE target=450), that floor forced BART's
# min_length to 450 tokens when the input only supported ~150-200 words of
# genuine extractive summary. Once the model exhausted real content, beam
# search (length_penalty=2.5 for COMPREHENSIVE actively discourages an early
# EOS) couldn't stop, and it fell back to memorised CNN/DailyMail
# fine-tuning boilerplate ("Back to Mail Online home...") to reach the
# floor. See grounding_check.py's docstring for the full trace.
#
# The fix: never let min_length exceed a fraction of what THIS input
# actually contains, regardless of what the style nominally wants. 0.35 was
# tried first against the live YIszsqhLGIs job (745-word/849-token
# narrative) and still left BART hallucinating on the first attempt — the
# grounding-check retry/fallback caught it (no boilerplate reached the
# user), but every long-style summary on this input degraded to a blunt
# truncation instead of a real compression. Sentence-level grounding
# calibration on that same job put drift onset around ~180 words in, so
# 0.25 (~212 tokens here) was tried next to leave headroom above that.
# Tighten further if a future real job still leaks boilerplate under it.
MAX_MIN_LENGTH_INPUT_FRACTION = 0.35
ABSOLUTE_MIN_LENGTH_TOKENS = 20


def _ngram_repetition_ratio(words: list, n: int) -> float:
    if len(words) < n + 1:
        return 0.0
    grams = [tuple(w.lower() for w in words[i:i + n]) for i in range(len(words) - n + 1)]
    counts = Counter(grams)
    repeated_occurrences = sum(c - 1 for c in counts.values() if c > 1)
    return repeated_occurrences / len(grams)


def _looks_degenerate(
    text: str,
    input_word_count: int = None,
    target_words: int = None,
    mode: str = "compress",
) -> str:
    """
    Returns a human-readable reason if `text` looks like BART degeneration,
    else "".

    Deliberately conservative: a real sentence or phrase repeated once or
    twice (normal in spoken-word transcripts and in genuine emphasis) must
    NOT trip this. It exists to catch loops, not repetition per se.
    """
    words = text.split()
    if len(words) < DEGENERATION_MIN_WORDS:
        return ""

    for n, threshold in NGRAM_REPETITION_THRESHOLDS.items():
        ratio = _ngram_repetition_ratio(words, n)
        if ratio > threshold:
            return f"{n}-gram repetition ratio {ratio:.2f} > {threshold}"

    sentences = _split_sentences(text)
    if len(sentences) >= MIN_SENTENCES_FOR_CHECK:
        unique_ratio = len({s.lower().strip() for s in sentences}) / len(sentences)
        if unique_ratio < MIN_UNIQUE_SENTENCE_RATIO:
            return f"unique-sentence ratio {unique_ratio:.2f} < {MIN_UNIQUE_SENTENCE_RATIO}"

    if mode == "compress" and input_word_count and target_words:
        if (len(words) > input_word_count * NEAR_COPY_LENGTH_RATIO
                and len(words) > target_words * NEAR_COPY_TARGET_MULTIPLE):
            return (f"near-copy: {len(words)}w output is "
                    f"{len(words) / input_word_count:.0%} of the {input_word_count}w input "
                    f"despite a {target_words}w compress target")

    return ""

# Lazy-loaded model + tokenizer (direct API — transformers 5.x removed "summarization" pipeline task)
_model = None
_tokenizer = None

# HuggingFace's fast (Rust) tokenizer is NOT safe to call concurrently from
# multiple threads on the same instance — it raises "Already borrowed" when
# two threads invoke it at once. _recursive_summarize's multi-chunk path
# runs _summarize_chunk() for each chunk in a ThreadPoolExecutor, and every
# chunk touches this SAME module-global _tokenizer (via _summarize()'s
# encode/decode below, and via _count_tokens()) — so two chunks summarizing
# in parallel can race on it. Confirmed live: a real 956-word job with 2
# chunks hit "Already borrowed" on one chunk, which silently fell back to
# plain truncation instead of a real BART summary (caught by
# _summarize_chunk's exception handler, so the job didn't crash — but the
# output for that chunk wasn't a real compression).
#
# The model itself is NOT locked here — model.generate() is not the source
# of this error and serializing it would remove the parallelism the
# ThreadPoolExecutor exists for. Only the tokenizer's encode/decode calls —
# fast, so serializing them costs very little — need the lock.
_tokenizer_lock = threading.Lock()
_init_lock = threading.Lock()


def _get_pipeline():
    """Lazy-load BART model and tokenizer for summarization."""
    global _model, _tokenizer
    if _model is None:
        with _init_lock:
            if _model is None:
                import warnings
                from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
                from ..core.config import get_hf_token
                model_name = settings.SUMMARIZATION_MODEL  # "facebook/bart-large-cnn"
                hf_token = get_hf_token()  # None when unset → anonymous, same as before
                print(f"[Summarizer] Loading model: {model_name}")
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    _tokenizer = AutoTokenizer.from_pretrained(model_name, token=hf_token)
                    _model = AutoModelForSeq2SeqLM.from_pretrained(model_name, token=hf_token)
                import torch
                import os
                try:
                    torch.set_num_threads(min(4, os.cpu_count() or 4))
                except Exception:
                    pass
                _model.eval()
                # Fix BART generation config warning: forced_bos_token_id must be 0 for BART
                if hasattr(_model, "generation_config"):
                    _model.generation_config.forced_bos_token_id = 0
                print(f"[Summarizer] Model loaded: {model_name}")

    # Return a callable that mimics the old pipeline interface:
    # pipeline(text, max_length=..., min_length=..., ...) → [{"summary_text": "..."}]
    #
    # Every generation-shaping argument is a real parameter here, not a
    # swallowed **kwarg. The previous version accepted num_beams/length_penalty/
    # early_stopping through **kwargs and then ignored them, always generating
    # with hardcoded num_beams=4, early_stopping=True, no_repeat_ngram_size=3 —
    # so the per-style values computed from DURATION_PROFILES (e.g. the 2.5
    # length_penalty for COMPREHENSIVE) never reached the model.
    def _summarize(text: str, max_length: int = 150, min_length: int = 40,
                   do_sample: bool = False, num_beams: int = 4,
                   length_penalty: float = 2.0, early_stopping: bool = True,
                   no_repeat_ngram_size: int = 3, repetition_penalty: float = 1.0,
                   **kwargs):
        import torch
        with _tokenizer_lock:
            inputs = _tokenizer(
                text, return_tensors="pt",
                max_length=1024, truncation=True, padding=True,
            )
        with torch.inference_mode():
            ids = _model.generate(
                inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
                max_length=max_length,
                min_length=min_length,
                do_sample=do_sample,
                num_beams=num_beams,
                length_penalty=length_penalty,
                early_stopping=early_stopping,
                no_repeat_ngram_size=no_repeat_ngram_size,
                repetition_penalty=repetition_penalty,
            )
        with _tokenizer_lock:
            summary = _tokenizer.decode(ids[0], skip_special_tokens=True)
        return [{"summary_text": summary}]

    return _summarize


def _count_tokens(text: str) -> int:
    """
    Real tokenizer length of `text`, for computing generation bounds from
    actual input size rather than a word-count estimate. Forces
    return_tensors="pt" so the shape is uniform between the real tokenizer
    and tests' FakeTokenizer (both yield a (1, n) tensor this way).
    """
    _get_pipeline()  # ensures _tokenizer is loaded
    with _tokenizer_lock:
        ids = _tokenizer(text, return_tensors="pt", truncation=True, max_length=4096)["input_ids"]
    return int(ids.shape[-1])


class SummarizationService:
    """
    Hierarchical summarization service using BART-large-CNN.

    Handles arbitrarily long inputs by chunking, summarizing per-chunk,
    then recursively summarizing the merged result until the target
    word count is reached.
    """

    def __init__(self):
        self.max_chunk_words = 400  # Smaller sections retain more topic coverage.
        self.max_recursion = 3      # Prevent infinite recursion

    def hierarchical_summarize(
        self,
        text: str,
        target_words: int,
        profile: DurationProfile,
        embedder=None,
    ) -> str:
        """
        Main entry point. Applies the summarization POLICY, then acts on it.

        This used to open with `if word_count <= target_words: return text`,
        which conflated "short enough" with "good enough" and shipped raw fused
        narrative — complete with the fusion engine's "Additionally,/Furthermore,
        /Moreover," scaffolding — whenever the narrative happened to land under
        the target. Measured on this repo's real jobs, that hit every 10-minute
        run (820 words against a 1500-word target, 19 connective artifacts) while
        5-minute runs (757 against 750) narrowly escaped it.

        Compression and coherence are now decided separately. See
        summarization_policy.decide() for the full rationale.

        Args:
            text: Full text to summarize (can be any length)
            target_words: Target output word count
            profile: Duration profile with style parameters
            embedder: optional SBERT-like object; injected by tests

        Returns:
            Coherent text approximately matching target_words
        """
        return self.summarize_with_policy(text, target_words, profile, embedder)[0]

    def summarize_with_policy(
        self,
        text: str,
        target_words: int,
        profile: DurationProfile,
        embedder=None,
        content_type: str = "explanatory",
        progress_callback=None,
    ):
        """
        Same as hierarchical_summarize() but also returns the decision.

        Returns:
            (summary_text, decision_dict) — the dict is stored on the job so the
            results page and the evaluation script can show WHY the text took
            the path it did.
        """
        from .summarization_policy import (
            clean_text as _policy_clean,
            decide as _policy_decide,
            deduplicate_sentences as _policy_dedup,
        )

        if not text or not text.strip():
            return "", {"action": "pass", "reason": "empty input"}

        text = self._clean_text(text)
        decision = _policy_decide(
            text, target_words, embedder=embedder, content_type=content_type
        )
        print(f"[Summarizer] Policy: {decision.action.upper()} — {decision.reason}")

        config = get_summarization_config(profile)

        # Scaffolding is removed on every path: it is never wanted in the output,
        # and feeding it to BART only spends input tokens on filler.
        text = "\n\n".join(_policy_clean(p) for p in text.split("\n\n") if p.strip())

        if decision.action == "compress":
            result = self._recursive_summarize(text, target_words, config, depth=0, progress_callback=progress_callback)

        elif decision.action == "rewrite":
            # Short enough to keep, but reads like machine-glued fragments.
            # Drop restatements first, then run BART at roughly the input length
            # so it smooths phrasing instead of compressing away content.
            deduped = _policy_dedup(text, embedder=embedder)
            dropped = len(text.split()) - len(deduped.split())
            if dropped > 0:
                print(f"[Summarizer] Rewrite: removed {dropped} words of restatement")
            result = self._smooth(deduped, config, progress_callback=progress_callback)

        else:  # "clean" or "pass"
            result = text

        return result.strip(), decision.to_dict()

    def _smooth(self, text: str, config, progress_callback=None) -> str:
        """
        Length-preserving BART pass: fix phrasing, keep the content.

        Chunks are summarized to ~92% of their own length rather than to a
        compression target, so the model rewrites rather than cuts. If a chunk
        comes back suspiciously short the original is kept — a smoothing pass
        that loses half the text has failed, and silently shipping the loss is
        worse than shipping slightly rough prose.
        """
        chunks = self._split_into_chunks(text, self.max_chunk_words)
        if not chunks:
            return text

        out = []
        for i, chunk in enumerate(chunks):
            words = len(chunk.split())
            if words < 60:
                # Too short to be worth a model call, and BART's min_length
                # floor would pad it with invention.
                out.append(chunk)
                continue
            rewritten = self._summarize_chunk(chunk, max(50, int(words * 0.92)), config, mode="rewrite")
            out.append(rewritten if len(rewritten.split()) >= words * 0.45 else chunk)
            if progress_callback:
                try:
                    progress_callback(i + 1, len(chunks))
                except Exception:
                    pass

        return " ".join(out)

    def _recursive_summarize(
        self,
        text: str,
        target_words: int,
        config,
        depth: int,
        progress_callback=None,
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
            res = self._summarize_chunk(chunks[0], target_words, config)
            if progress_callback:
                try:
                    progress_callback(1, 1)
                except Exception:
                    pass
            return res

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
            completed_count = 0
            for future in as_completed(futures):
                idx = futures[future]
                summaries[idx] = future.result()
                completed_count += 1
                if progress_callback:
                    try:
                        progress_callback(completed_count, len(chunk_tasks))
                    except Exception:
                        pass

        # Merge chunk summaries
        merged = " ".join(summaries)
        merged_words = len(merged.split())

        # A second global model pass can discard entire later sections. Keep
        # complete sentences from every chunk before spending the remaining
        # budget on detail. The word target is soft when the first sentences
        # alone exceed it; preserving coverage beats silently dropping topics.
        if merged_words > target_words * 1.15:
            return self._balance_chunk_summaries(summaries, target_words)

        return merged

    @staticmethod
    def _balance_chunk_summaries(summaries, target_words):
        sections = [_split_sentences(s) for s in summaries if s and s.strip()]
        sections = [s for s in sections if s]
        selected = [[s[0]] for s in sections]
        used = sum(len(s[0].split()) for s in sections)
        # Coverage sentences are protected even when they exceed the target,
        # but optional detail must fit the requested budget.  Spending the
        # 15% soft overrun on an early section biases the result before later
        # sections have any opportunity to contribute detail.
        budget = int(target_words)
        for index in range(1, max((len(s) for s in sections), default=0)):
            for section, kept in zip(sections, selected):
                if index < len(section):
                    sentence = section[index]
                    size = len(sentence.split())
                    if used + size <= budget:
                        kept.append(sentence)
                        used += size
        return " ".join(sentence for section in selected for sentence in section)

    def _summarize_chunk(self, text: str, target_words: int, config, mode: str = "compress") -> str:
        """
        Summarize a single chunk using BART, with a degeneration guard.

        Args:
            text: Text chunk (should be within model's token limit)
            target_words: Approximate target word count for this chunk
            config: SummarizationConfig with model parameters
            mode: "compress" (recursive path — near-copy check applies) or
                  "rewrite" (smoothing path — output is meant to stay near
                  input length, so near-copy is not a defect there)
        """
        pipe = _get_pipeline()

        # Word counts are not tokenizer counts. An unpunctuated caption or
        # technical vocabulary can exceed BART's context even below 800 words.
        # Split before generation so truncation never silently drops the tail.
        if _count_tokens(text) > 1024:
            words = text.split()
            midpoint = len(words) // 2
            if midpoint:
                left = " ".join(words[:midpoint])
                right = " ".join(words[midpoint:])
                return " ".join(self._summarize_chunk(part, max(25, target_words // 2), config, mode)
                                for part in (left, right))

        # Convert word targets to token estimates (1 word ≈ 1.3 tokens)
        # Give ample headroom (2.0x) so model emits EOS naturally instead of hitting a hard ceiling.
        max_length = min(config.max_output_length, max(int(target_words * 2.0), 150))

        # The style wants at least this many tokens... but never more than a
        # fraction of what THIS input actually contains — see
        # MAX_MIN_LENGTH_INPUT_FRACTION's comment above. Forcing a floor the
        # input can't support is what causes forced-length hallucination.
        style_min = max(config.min_output_length, int(target_words * 0.5))
        input_token_count = _count_tokens(text)
        input_cap = max(ABSOLUTE_MIN_LENGTH_TOKENS, int(input_token_count * MAX_MIN_LENGTH_INPUT_FRACTION))
        min_length = max(min(style_min, input_cap), ABSOLUTE_MIN_LENGTH_TOKENS)

        # Ensure min < max
        if min_length >= max_length:
            min_length = max(ABSOLUTE_MIN_LENGTH_TOKENS, max_length // 2)

        input_word_count = len(text.split())

        def _generate(repetition_penalty: float, no_repeat_ngram_size: int, length_penalty: float) -> str:
            result = pipe(
                text,
                max_length=max_length,
                min_length=min_length,
                num_beams=config.num_beams,
                length_penalty=length_penalty,
                early_stopping=config.early_stopping,
                no_repeat_ngram_size=no_repeat_ngram_size,
                repetition_penalty=repetition_penalty,
                do_sample=False,
            )
            return self._ensure_complete_sentences(result[0]["summary_text"])

        def _fallback() -> str:
            # The pre-existing safe path: a plain truncation carries no risk of
            # inventing or looping text, unlike another model call.
            # Truncated safely at sentence boundary to avoid broken thoughts.
            words = text.split()
            truncated = " ".join(words[:target_words])
            return self._ensure_complete_sentences(truncated)

        def _quality_issue(candidate: str) -> str:
            # Loop degeneration (existing guard) first — cheap, purely lexical.
            reason = _looks_degenerate(candidate, input_word_count, target_words, mode)
            if reason:
                return reason
            # Then grounding: catches a structurally different failure the
            # lexical guard can't see (lexically-diverse hallucinated
            # boilerplate — see grounding_check.py). Only meaningful on the
            # compress path; _smooth()'s rewrite output is expected to stay
            # near-verbatim to its own input, which trivially grounds.
            if mode == "compress":
                grounding = check_grounding(candidate, text)
                if not grounding.is_grounded:
                    return "; ".join(grounding.reasons)
            return ""

        try:
            summary = _generate(config.repetition_penalty, 3, config.length_penalty)
        except Exception as e:
            print(f"[Summarizer] Chunk summarization failed: {e}")
            return _fallback()

        reason = _quality_issue(summary)
        if not reason:
            return summary

        print(f"[Summarizer] Quality issue detected ({reason}) — retrying with safer settings")
        try:
            # Safer settings: a stronger repetition penalty, a tighter
            # no-repeat window, and length_penalty relaxed to 1.0 so the model
            # isn't pushed to keep generating once it has run out of new
            # content to say — the same mechanism implicated in the original
            # degenerate sample.
            retry = _generate(repetition_penalty=1.8, no_repeat_ngram_size=2, length_penalty=1.0)
        except Exception as e:
            print(f"[Summarizer] Retry generation failed: {e}")
            return _fallback()

        if not _quality_issue(retry):
            return retry

        print("[Summarizer] Retry still failed quality checks — falling back to truncated original")
        return _fallback()

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
                    # Auto captions often contain no punctuation at all.
                    # Enforce the bound even when one "sentence" is huge.
                    if sent_words > max_words:
                        words = sent.split()
                        for start in range(0, len(words), max_words):
                            chunks.append(" ".join(words[start:start + max_words]))
                    else:
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
        paragraphs = [re.sub(r'\s+', ' ', p).strip() for p in text.split('\n\n')]
        return '\n\n'.join(p for p in paragraphs if p).strip()

    @staticmethod
    def _ensure_complete_sentences(text: str) -> str:
        text = text.strip()
        if not text:
            return text
        if text[-1] in ".!?":
            return text
            
        import re
        # Find the last valid sentence boundary (punctuation followed by space or end of string)
        matches = list(re.finditer(r'[.!?](?:\s+|$)', text))
        if matches:
            last_idx = matches[-1].start() + 1
            return text[:last_idx].strip()
            
        if ' ' in text:
            return text.rsplit(' ', 1)[0] + "..."
        return text + "..."


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
