"""
Tests for summarization_service — the dropped generation-kwargs bug and the
output-side degeneration guard.

Anchor case: a real 30-minute COMPRESS job (1023 words vs a 600-word target,
video YIszsqhLGIs) shipped a garbled, paraphrase-looping paragraph to the
user: "...It's not to worry. You're not to fear. You're not in fear. I just
want to be scared. I'm scared. You don't want to worry about it...". Two
causes, both fixed here:

  1. _get_pipeline()'s inner _summarize() accepted num_beams/length_penalty/
     early_stopping/repetition_penalty only through **kwargs and then called
     model.generate() with hardcoded num_beams=4, early_stopping=True,
     no_repeat_ngram_size=3 — the caller's values, computed from
     DURATION_PROFILES, never reached the model.
  2. Nothing anywhere inspected what BART actually generated. The existing
     assess_coherence() check (summarization_policy.py) only looks at the
     PRE-BART fused text, and only on the rewrite path.

The degeneration-detector thresholds below are not guesses — they were
measured directly against the real garbled text (see GARBLED_SAMPLE, which
reproduces it) and against normal prose, using the exact tokenisation
_ngram_repetition_ratio uses (plain str.split(), lowercased, punctuation
still attached — matching real sentence-ending tokens like "worry."):

    text                                              2-gram ratio
    -----------------------------------------------   ------------
    GARBLED_SAMPLE (the real degenerate output)        0.183
    a paragraph deliberately reusing one key phrase     0.036
    ordinary multi-sentence prose                       0.000
    a literal sentence repeated 8x                      0.873
"""

import re
import threading
import time

import pytest

from backend.services import summarization_service as svc
from backend.services.duration_profiles import get_profile, get_summarization_config
from backend.services.grounding_check import GroundingResult


GARBLED_SAMPLE = (
    "I'm not in favour of working from home. It's not to be afraid. "
    "It's not to worry. You're not to fear. You're not in fear. "
    "I just want to be scared. I'm scared. You don't want to worry about it. "
    "You want to know what you've got to know. You need to be worried about "
    "it'll be scared of it. It doesn't afraid of it, you'd like it. "
    "I want to get it. What'm not scared. What you need to get to it. "
    "We need to worry. You have to be crafty about it."
)

CLEAN_SAMPLE = (
    "Failure is treated as shameful in many cultures because success is prized "
    "publicly while setbacks are hidden from view. A more resilient approach "
    "treats failure as information rather than as an identity. People who "
    "protect their time carefully tend to build stronger relationships over "
    "years, because consistency compounds in a way that a single grand gesture "
    "never does. Investors and collaborators notice who did the homework before "
    "reaching out, and who simply copied a generic template."
)

# Unique wording throughout (no repeated bigrams), used to isolate the
# near-copy check from the n-gram checks.
LONG_UNIQUE_TEXT = (
    "Machine learning systems infer rules from examples rather than being "
    "programmed with them directly. A model trained on labelled photographs "
    "eventually recognises objects it has never encountered before. That "
    "generalisation is the whole point of the exercise. When it fails, the "
    "usual culprit is a training set too narrow to represent the real world. "
    "Engineers address this by collecting more diverse data, by regularising "
    "the model so it cannot simply memorise, and by holding out a validation "
    "set that never influences training decisions."
)

# Deliberately reuses one key phrase for emphasis — must NOT be flagged.
EMPHASIS_SAMPLE = (
    "Regularisation is the single most important idea in this lecture. We will "
    "return to regularisation again and again because every technique here is "
    "a form of regularisation in disguise. Dropout is regularisation. Weight "
    "decay is regularisation. Early stopping is regularisation. By the end you "
    "should be able to explain any trick in the field as regularisation."
)


class FakeTokenizer:
    """Deterministic stand-in — no download, no real tokenisation."""

    def __init__(self, output: str = "fake summary"):
        self._output = output

    def __call__(self, text, return_tensors=None, max_length=None, truncation=None, padding=None):
        import torch
        n = max(len(text.split()), 1)
        return {"input_ids": torch.zeros((1, n), dtype=torch.long),
                "attention_mask": torch.ones((1, n), dtype=torch.long)}

    def decode(self, ids, skip_special_tokens=True):
        return self._output


class FakeModel:
    """Records every generate() call's kwargs; never touches a real checkpoint."""

    def __init__(self):
        self.calls = []

    def generate(self, input_ids, attention_mask=None, **kwargs):
        self.calls.append(kwargs)
        import torch
        return torch.zeros((1, 1), dtype=torch.long)


class RaceDetectingTokenizer(FakeTokenizer):
    """
    Mimics HF's real fast (Rust) tokenizer's actual failure mode: it raises
    if two threads call it (encode OR decode) at the same time, without
    needing the real — slow — tokenizer to reproduce the race. A short sleep
    inside the critical section widens the window so two racing threads
    reliably overlap instead of the test being flaky by luck. Whether this
    ever raises is the direct, deterministic proof that _tokenizer_lock in
    summarization_service.py serializes every call site.
    """

    def __init__(self, output: str = "fake summary"):
        super().__init__(output)
        self._in_use = False
        self._guard = threading.Lock()  # protects the flag itself only — not a stand-in for the real fix

    def __call__(self, text, return_tensors=None, max_length=None, truncation=None, padding=None):
        self._enter()
        try:
            time.sleep(0.02)
            return super().__call__(text, return_tensors=return_tensors, max_length=max_length,
                                     truncation=truncation, padding=padding)
        finally:
            self._exit()

    def decode(self, ids, skip_special_tokens=True):
        self._enter()
        try:
            time.sleep(0.02)
            return super().decode(ids, skip_special_tokens=skip_special_tokens)
        finally:
            self._exit()

    def _enter(self):
        with self._guard:
            if self._in_use:
                raise RuntimeError("Already borrowed")
            self._in_use = True

    def _exit(self):
        with self._guard:
            self._in_use = False


class SlowFakeModel(FakeModel):
    """generate() sleeps briefly so concurrent chunk summaries actually overlap in time."""

    def generate(self, input_ids, attention_mask=None, **kwargs):
        time.sleep(0.02)
        return super().generate(input_ids, attention_mask=attention_mask, **kwargs)


@pytest.fixture
def fake_backend(monkeypatch):
    """
    Install a fake model/tokenizer so _get_pipeline() never loads a real
    model, and a permissive grounding stub so these (mostly grounding-
    unrelated) tests don't pull in the real SBERT embedder or get an
    unpredictable similarity score against synthetic filler text like
    "word " * 200. Tests that specifically exercise grounding override
    this stub themselves — see TestGroundingIntegration below.
    """
    tokenizer = FakeTokenizer()
    model = FakeModel()
    monkeypatch.setattr(svc, "_model", model)
    monkeypatch.setattr(svc, "_tokenizer", tokenizer)
    monkeypatch.setattr(svc, "check_grounding", lambda *a, **kw: GroundingResult(is_grounded=True))
    return model, tokenizer


# =====================================================================
# Fix 1 — generation kwargs actually reach model.generate()
# =====================================================================

class TestGenerationKwargsForwarded:
    def test_pipeline_forwards_caller_kwargs_to_generate(self, fake_backend):
        """
        THE BUG: the old _summarize() took num_beams/length_penalty/
        early_stopping/repetition_penalty through **kwargs and never used
        them, always generating with hardcoded num_beams=4,
        early_stopping=True, no_repeat_ngram_size=3.
        """
        model, _ = fake_backend
        pipe = svc._get_pipeline()

        pipe(
            "some text to summarize",
            max_length=77, min_length=33,
            num_beams=6, length_penalty=3.3, early_stopping=False,
            no_repeat_ngram_size=5, repetition_penalty=1.9,
        )

        assert len(model.calls) == 1
        call = model.calls[0]
        assert call["num_beams"] == 6
        assert call["length_penalty"] == 3.3
        assert call["early_stopping"] is False
        assert call["no_repeat_ngram_size"] == 5
        assert call["repetition_penalty"] == 1.9
        assert call["max_length"] == 77
        assert call["min_length"] == 33

    def test_pipeline_keeps_prior_defaults_when_caller_passes_nothing(self, fake_backend):
        """Backward compatible: a call site with no explicit kwargs still works."""
        model, _ = fake_backend
        svc._get_pipeline()("some text")
        call = model.calls[0]
        assert call["num_beams"] == 4
        assert call["early_stopping"] is True
        assert call["no_repeat_ngram_size"] == 3
        assert call["repetition_penalty"] == 1.0

    def test_summarize_chunk_forwards_profile_config_to_pipeline(self, fake_backend):
        """
        End-to-end: a duration profile's SummarizationConfig (num_beams,
        length_penalty, repetition_penalty) actually reaches model.generate()
        through SummarizationService._summarize_chunk().
        """
        model, tokenizer = fake_backend
        tokenizer._output = CLEAN_SAMPLE  # clean output: no retry triggered

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(30))  # COMPREHENSIVE: distinct values

        service._summarize_chunk("word " * 200, target_words=100, config=config)

        assert len(model.calls) == 1, "should not have retried on clean output"
        call = model.calls[0]
        assert call["num_beams"] == config.num_beams
        assert call["length_penalty"] == config.length_penalty
        assert call["early_stopping"] == config.early_stopping
        assert call["repetition_penalty"] == config.repetition_penalty
        assert config.repetition_penalty != 1.0, "fixture must use a real, non-default value"


# =====================================================================
# Fix 2 — output-side degeneration guard
# =====================================================================

class TestDegenerationDetector:
    def test_flags_the_real_garbled_sample(self):
        reason = svc._looks_degenerate(GARBLED_SAMPLE)
        assert reason

    def test_accepts_clean_prose(self):
        assert svc._looks_degenerate(CLEAN_SAMPLE) == ""

    def test_accepts_long_unique_prose(self):
        assert svc._looks_degenerate(LONG_UNIQUE_TEXT) == ""

    def test_does_not_flag_short_text(self):
        # Real repetition, but under the length floor — too little signal to judge.
        assert svc._looks_degenerate("very very important very very important") == ""

    def test_does_not_flag_deliberate_emphasis(self):
        """A key phrase reused on purpose across a real paragraph must not trip this."""
        assert svc._looks_degenerate(EMPHASIS_SAMPLE) == ""

    def test_flags_an_exact_repeated_sentence(self):
        text = "The model performs very well on this benchmark task. " * 8
        assert svc._looks_degenerate(text)

    def test_flags_near_copy_when_compression_requested(self):
        reason = svc._looks_degenerate(
            LONG_UNIQUE_TEXT,
            input_word_count=len(LONG_UNIQUE_TEXT.split()),
            target_words=20,
            mode="compress",
        )
        assert reason
        assert "near-copy" in reason

    def test_does_not_flag_near_copy_in_rewrite_mode(self):
        """_smooth() intentionally keeps output near input length — not a defect there."""
        reason = svc._looks_degenerate(
            LONG_UNIQUE_TEXT,
            input_word_count=len(LONG_UNIQUE_TEXT.split()),
            target_words=20,
            mode="rewrite",
        )
        assert reason == ""

    def test_does_not_flag_a_real_good_compression(self):
        short_summary = "The passage explains how models generalise from limited, diverse training data."
        reason = svc._looks_degenerate(
            short_summary,
            input_word_count=len(LONG_UNIQUE_TEXT.split()),
            target_words=20,
            mode="compress",
        )
        assert reason == ""


# =====================================================================
# Fix 2 — retry-once-then-fallback behaviour
# =====================================================================

class TestRetryAndFallback:
    def test_degenerate_output_triggers_one_retry_with_safer_settings(self, fake_backend):
        model, tokenizer = fake_backend
        outputs = iter([GARBLED_SAMPLE, CLEAN_SAMPLE])
        tokenizer.decode = lambda ids, skip_special_tokens=True: next(outputs)

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(10))

        result = service._summarize_chunk("word " * 200, target_words=100, config=config)

        assert result == CLEAN_SAMPLE
        assert len(model.calls) == 2, "must retry exactly once, not loop"
        first, retry = model.calls
        assert retry["repetition_penalty"] > first["repetition_penalty"]
        assert retry["no_repeat_ngram_size"] < first["no_repeat_ngram_size"]

    def test_still_degenerate_after_retry_falls_back_to_truncation(self, fake_backend):
        model, tokenizer = fake_backend
        tokenizer.decode = lambda ids, skip_special_tokens=True: GARBLED_SAMPLE

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(10))
        source_text = "word" + " word2" * 199  # 200 words, distinct-looking

        result = service._summarize_chunk(source_text, target_words=30, config=config)

        assert len(model.calls) == 2, "should try once, retry once, then stop"
        assert result == " ".join(source_text.split()[:30]).rsplit(" ", 1)[0] + "..."

    def test_clean_output_is_not_retried(self, fake_backend):
        model, tokenizer = fake_backend
        tokenizer._output = CLEAN_SAMPLE

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(10))

        result = service._summarize_chunk("word " * 100, target_words=60, config=config)

        assert result == CLEAN_SAMPLE
        assert len(model.calls) == 1

    def test_generation_exception_falls_back_without_crashing(self, fake_backend, monkeypatch):
        model, _ = fake_backend

        def raise_err(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(model, "generate", raise_err)

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(10))
        source_text = "word" + " word2" * 49

        result = service._summarize_chunk(source_text, target_words=20, config=config)
        assert result == " ".join(source_text.split()[:20]).rsplit(" ", 1)[0] + "..."

    def test_smooth_path_uses_rewrite_mode_so_near_copy_is_not_flagged(self, fake_backend):
        """
        _smooth() (the REWRITE path) intentionally targets ~92% of input
        length — i.e. it always returns something close to a near-copy by
        design. If _summarize_chunk ran it in "compress" mode, the near-copy
        check would misfire on every single smoothing pass.
        """
        model, tokenizer = fake_backend
        tokenizer._output = LONG_UNIQUE_TEXT  # smoothing returns ~the same content back

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(10))

        out = service._smooth(LONG_UNIQUE_TEXT, config)

        assert len(model.calls) == 1, "near-copy false-positive must not trigger a retry here"
        assert out.strip() == LONG_UNIQUE_TEXT.strip()


# =====================================================================
# Fix 4 — min_length is capped by actual input size, not just the style's
# nominal word target (the forced-length hallucination fix)
# =====================================================================

class TestInputAwareLengthBounds:
    def test_short_input_cannot_be_forced_past_its_own_length(self, fake_backend):
        """
        A short (~40-word) input against the COMPREHENSIVE style (which wants
        a 450-word/token floor) must not be forced to generate anywhere near
        450 — that's exactly the forced-length hallucination bug. min_length
        must be capped relative to what this input actually contains.
        """
        model, tokenizer = fake_backend
        tokenizer._output = CLEAN_SAMPLE

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(20))  # COMPREHENSIVE, min_output_length=450
        short_text = "word " * 40

        service._summarize_chunk(short_text, target_words=450, config=config)

        call = model.calls[0]
        # FakeTokenizer's token count == word count, so input has 40 tokens.
        assert call["min_length"] <= max(
            svc.ABSOLUTE_MIN_LENGTH_TOKENS, int(40 * svc.MAX_MIN_LENGTH_INPUT_FRACTION)
        )
        assert call["min_length"] < 450, "must not force the full style-nominal floor on a short input"

    def test_min_length_respects_input_fraction_cap(self, fake_backend):
        """Directly verifies the formula: min_length <= input_tokens * MAX_MIN_LENGTH_INPUT_FRACTION."""
        model, tokenizer = fake_backend
        tokenizer._output = CLEAN_SAMPLE

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(20))
        input_words = 100
        text = "word " * input_words

        service._summarize_chunk(text, target_words=450, config=config)

        call = model.calls[0]
        expected_cap = max(svc.ABSOLUTE_MIN_LENGTH_TOKENS, int(input_words * svc.MAX_MIN_LENGTH_INPUT_FRACTION))
        assert call["min_length"] <= expected_cap

    def test_target_words_is_not_passed_through_as_a_raw_token_count(self, fake_backend):
        """
        Regression for the exact anchor-case mechanism: style min_output_length
        (word-scale, e.g. 450) must never reach model.generate()'s min_length
        unmodified when the input can't support it.
        """
        model, tokenizer = fake_backend
        tokenizer._output = CLEAN_SAMPLE

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(20))
        assert config.min_output_length == 450

        service._summarize_chunk("word " * 50, target_words=450, config=config)

        call = model.calls[0]
        assert call["min_length"] != 450
        assert call["min_length"] < 450

    def test_generous_input_still_gets_a_reasonable_floor(self, fake_backend):
        """The cap must not starve legitimately long, content-rich input."""
        model, tokenizer = fake_backend
        tokenizer._output = CLEAN_SAMPLE

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(20))
        text = "word " * 2000  # plenty of input to support a real 450-word floor

        service._summarize_chunk(text, target_words=450, config=config)

        call = model.calls[0]
        # Each half must fit the 1024-token context; its own input size caps
        # the floor. The previous assertion forced truncation of a 2000-token input.
        assert len(model.calls) >= 2
        assert 300 <= call["min_length"] <= 350

    def test_count_tokens_matches_tokenizer_output_length(self, fake_backend):
        """Word/token conversion sanity: _count_tokens reflects the real tokenizer, not len(text.split())-by-assumption."""
        _, tokenizer = fake_backend
        text = "one two three four five"
        assert svc._count_tokens(text) == 5  # FakeTokenizer: token count == word count


# =====================================================================
# Fix 5 — grounding check wired into the same retry-once-then-fallback path
# =====================================================================

class TestGroundingIntegration:
    def test_ungrounded_output_triggers_one_retry(self, fake_backend, monkeypatch):
        model, tokenizer = fake_backend
        outputs = iter(["hallucinated boilerplate", CLEAN_SAMPLE])
        tokenizer.decode = lambda ids, skip_special_tokens=True: next(outputs)

        results = iter([
            GroundingResult(is_grounded=False, reasons=["domain-like garbage: ['tom.com']"]),
            GroundingResult(is_grounded=True),
        ])
        monkeypatch.setattr(svc, "check_grounding", lambda *a, **kw: next(results))

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(20))

        result = service._summarize_chunk("word " * 200, target_words=100, config=config)

        assert result == CLEAN_SAMPLE
        assert len(model.calls) == 2, "must retry exactly once on ungrounded output"

    def test_ungrounded_after_retry_falls_back_to_truncation(self, fake_backend, monkeypatch):
        model, tokenizer = fake_backend
        tokenizer.decode = lambda ids, skip_special_tokens=True: "still hallucinated"
        monkeypatch.setattr(
            svc, "check_grounding",
            lambda *a, **kw: GroundingResult(is_grounded=False, reasons=["forced-fail for test"]),
        )

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(20))
        source_text = "word" + " word2" * 199

        result = service._summarize_chunk(source_text, target_words=30, config=config)

        assert len(model.calls) == 2, "should try once, retry once, then stop — never loop"
        assert result == " ".join(source_text.split()[:30]).rsplit(" ", 1)[0] + "..."

    def test_grounded_output_is_not_retried(self, fake_backend, monkeypatch):
        model, tokenizer = fake_backend
        tokenizer._output = CLEAN_SAMPLE
        monkeypatch.setattr(svc, "check_grounding", lambda *a, **kw: GroundingResult(is_grounded=True))

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(20))

        result = service._summarize_chunk("word " * 100, target_words=60, config=config)

        assert result == CLEAN_SAMPLE
        assert len(model.calls) == 1

    def test_grounding_is_not_checked_on_rewrite_path(self, fake_backend, monkeypatch):
        """_smooth() output is expected to stay near-verbatim to its input — grounding is compress-only."""
        model, tokenizer = fake_backend
        tokenizer._output = LONG_UNIQUE_TEXT
        calls = []
        monkeypatch.setattr(
            svc, "check_grounding",
            lambda *a, **kw: calls.append(1) or GroundingResult(is_grounded=True),
        )

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(20))

        service._smooth(LONG_UNIQUE_TEXT, config)

        assert calls == [], "grounding should not run on the rewrite/_smooth path"


# =====================================================================
# Fix 3 — is recursive summarization actually needed at real sizes?
# =====================================================================

class TestRecursionNecessity:
    """
    Does the recursive multi-pass path in _recursive_summarize() actually
    fire for a realistically sized selected transcript, or does a single
    _summarize_chunk call suffice? Recursion only triggers once
    _split_into_chunks produces more than one chunk, i.e. once the text
    exceeds max_chunk_words (800).
    """

    def test_single_chunk_path_needs_no_recursion(self, fake_backend):
        """
        A ~700-word narrative (realistic for a 10-minute selection after
        selection+fusion — see the real 12-segment/598s job in this repo's
        own logs) fits in one chunk, so _recursive_summarize must take the
        len(chunks) == 1 branch and call the model exactly once, never
        recursing to depth 1.
        """
        model, tokenizer = fake_backend
        tokenizer._output = CLEAN_SAMPLE

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(10))
        text = " ".join(f"word{i}" for i in range(service.max_chunk_words - 20))

        service._recursive_summarize(text, target_words=250, config=config, depth=0)

        assert len(model.calls) == 1, (
            "a selection within the chunk limit should resolve in a single BART call — "
            "recursion is unnecessary at this size"
        )

    def test_oversized_input_does_trigger_chunking(self, fake_backend):
        """
        The 30-minute profile is the case that actually needs it: a real job
        in this repo produced a 1023-word narrative against a 600-word
        target, which exceeds max_chunk_words (800) and must chunk.
        """
        model, tokenizer = fake_backend
        tokenizer._output = "short clean summary text here that is not degenerate at all"

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(30))
        # Real sentence boundaries are required: _split_into_chunks only
        # splits an over-long paragraph on sentences (via _split_sentences,
        # which looks for '.'/'!'/'?'), so a period-free wall of words would
        # come back as a single unsplittable "sentence" and never chunk.
        sentences = [" ".join(f"word{i}_{j}" for j in range(10)) + "." for i in range(103)]
        text = " ".join(sentences)
        assert len(text.split()) > service.max_chunk_words

        service._recursive_summarize(text, target_words=600, config=config, depth=0)

        assert len(model.calls) >= 2, (
            "a 1023-word selection exceeds max_chunk_words and must be split "
            "into multiple chunks, unlike the 10-minute case above"
        )


# =====================================================================
# Fix 6 — tokenizer thread-safety ("Already borrowed")
# =====================================================================
#
# Real bug, found live: a real 956-word narrative split into 2 chunks by
# _recursive_summarize's multi-chunk path, summarized in parallel via
# ThreadPoolExecutor. Both chunks touch the SAME module-global _tokenizer
# (encode inside _summarize(), decode inside _summarize(), encode inside
# _count_tokens()). HuggingFace's fast (Rust) tokenizer is not safe for
# concurrent calls on one instance — two chunks racing on it raised
# `RuntimeError: Already borrowed` on one of them. _summarize_chunk's
# existing exception handler caught it and fell back to plain truncation
# for that chunk — the job didn't crash, but that chunk was never actually
# summarized by BART, silently degrading a "real" summary into a partial
# truncation with no visible error.

class TestTokenizerConcurrencySafety:
    def test_concurrent_chunk_summaries_do_not_race_on_the_tokenizer(self, monkeypatch):
        """
        Drives the real production path (_recursive_summarize's multi-chunk
        ThreadPoolExecutor branch) with a race-detecting fake tokenizer that
        raises "Already borrowed" the instant two threads touch it at once.
        If _tokenizer_lock is doing its job, this must complete cleanly no
        matter how many chunks run concurrently.
        """
        tokenizer = RaceDetectingTokenizer(output="short clean summary text that is not degenerate at all")
        model = SlowFakeModel()
        monkeypatch.setattr(svc, "_model", model)
        monkeypatch.setattr(svc, "_tokenizer", tokenizer)
        monkeypatch.setattr(svc, "check_grounding", lambda *a, **kw: GroundingResult(is_grounded=True))

        service = svc.SummarizationService()
        config = get_summarization_config(get_profile(30))
        # Enough sentences to split into several concurrent chunks (see the
        # oversized-input test above for why real sentence boundaries matter).
        sentences = [" ".join(f"word{i}_{j}" for j in range(10)) + "." for i in range(200)]
        text = " ".join(sentences)
        assert len(text.split()) > service.max_chunk_words * 2, "must force multiple chunks, not just two"

        # No "Already borrowed" (or anything else) may escape here.
        result = service._recursive_summarize(text, target_words=600, config=config, depth=0)

        assert len(model.calls) >= 3, "expected several chunks to actually run concurrently"
        # The fake model always returns the same fixed summary text regardless
        # of input, so any literal "wordN_M" source token surviving into the
        # merged result can only mean some chunk's fallback truncation fired
        # (_fallback() slices the raw source text) — i.e. that chunk was
        # never actually summarized by (fake) BART.
        assert not re.search(r'\bword\d+_\d+\b', result), (
            "result contains raw source tokens — a chunk silently fell back "
            "to truncation instead of going through generate()"
        )
        assert "short clean summary text" in result

    def test_tokenizer_lock_serializes_encode_and_decode_under_load(self):
        """
        Lower-level stress test independent of the summarization service:
        hammer the same RaceDetectingTokenizer instance's encode+decode from
        many threads through summarization_service's real _tokenizer_lock,
        proving the lock — not luck — is what prevents the race.
        """
        tokenizer = RaceDetectingTokenizer()
        errors = []

        def worker(n):
            try:
                for i in range(15):
                    with svc._tokenizer_lock:
                        tokenizer(f"sample text {n} {i}")
                    with svc._tokenizer_lock:
                        tokenizer.decode([1, 2, 3])
            except Exception as e:  # pragma: no cover - failure path under test
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"tokenizer access raced despite the lock: {errors!r}"

    def test_without_the_lock_the_race_is_real(self):
        """
        Control case: proves RaceDetectingTokenizer actually detects the real
        race (i.e. this test suite isn't just trivially green) — calling it
        concurrently WITHOUT going through _tokenizer_lock must reproduce
        "Already borrowed".
        """
        tokenizer = RaceDetectingTokenizer()
        errors = []

        def worker(n):
            try:
                for i in range(15):
                    tokenizer(f"sample text {n} {i}")  # no lock — the bug, unguarded
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors, "expected the unguarded fake tokenizer to race under concurrent load"
        assert any("Already borrowed" in str(e) for e in errors)

class TestTruncation:

    def test_ensure_complete_sentences_removes_trailing_fragment(self):
        # A partial word cut
        text = "This is a sentence. And here is another that gets cut mid-wo"
        assert svc.SummarizationService._ensure_complete_sentences(text) == "This is a sentence."
        
        # A full word cut mid-thought
        text2 = "This is a sentence. And here is another that gets"
        assert svc.SummarizationService._ensure_complete_sentences(text2) == "This is a sentence."
        
        # Ends with punctuation
        text3 = "This is a sentence. This is fine."
        assert svc.SummarizationService._ensure_complete_sentences(text3) == "This is a sentence. This is fine."
        
        # No punctuation at all
        text4 = "a fragment with no punctuation at all"
        assert svc.SummarizationService._ensure_complete_sentences(text4) == "a fragment with no punctuation at..."
        
    def test_fallback_truncates_at_sentence_boundary(self, fake_backend, monkeypatch):
        # Trigger fallback by simulating generation exception
        import pytest
        def fail(*args, **kwargs):
            raise RuntimeError("Fake generation error")
        monkeypatch.setattr(fake_backend[0], 'generate', fail)
        
        service = svc.get_summarization_service()
        config = get_summarization_config(get_profile(30))
        
        input_text = "Here is sentence one. Here is sentence two. Here is sentence three. Here is sentence four."
        # We want to truncate to exactly 10 words. 
        # "Here is sentence one. Here is sentence two. Here is" (10 words)
        # Should truncate back to sentence two.
        result = service._summarize_chunk(input_text, target_words=10, config=config, mode="compress")
        assert result == "Here is sentence one. Here is sentence two."
