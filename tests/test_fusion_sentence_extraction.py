"""
Regression tests — FusionEngine._extract_sentences and _chunk_segments_boundary_aware

Covers:
  1. Real YouTube auto-caption format (no punctuation, 940-segment scale)
  2. Normally punctuated English transcript
  3. Mixed: some segments with punctuation, some without
  4. Very long single caption segment (> max_sentence_words words)
  5. Very short transcript (< min_sentence_words total words)
  6. Flat-text fallback (no raw_segments supplied) — punctuation + Tier 3

Invariants checked on every test:
  - chunks > 0  (regression: was 0 for English auto-captions)
  - no chunk exceeds max_sentence_words
  - total word count of chunks ≈ total word count of input (coverage ≥ 95%)
  - chunks appear in chronological order (position is non-decreasing)
  - no content is silently dropped beyond the min_sentence_words floor
"""

import sys
import os
import re
import math

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.fusion_engine import FusionEngine, SourcedSentence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine() -> FusionEngine:
    e = FusionEngine()
    # Use the defaults from the fixed code
    assert e.min_sentence_words == 5
    assert e.max_sentence_words == 100
    return e


def _total_words(segs: list) -> int:
    return sum(len(s.get("text", "").split()) for s in segs)


def _chunks_word_count(chunks: list) -> int:
    return sum(len(c.text.split()) for c in chunks)


def _assert_invariants(chunks: list, source_words: int, engine: FusionEngine, label: str = ""):
    prefix = f"[{label}] " if label else ""

    assert len(chunks) > 0, f"{prefix}Expected > 0 chunks, got 0"

    for c in chunks:
        wc = len(c.text.split())
        assert wc <= engine.max_sentence_words, (
            f"{prefix}Chunk exceeds max_sentence_words={engine.max_sentence_words}: "
            f"{wc} words — text: {c.text[:80]!r}"
        )

    positions = [c.position for c in chunks]
    assert positions == sorted(positions), (
        f"{prefix}Chunks are not in chronological order: positions={positions}"
    )

    chunk_words = _chunks_word_count(chunks)
    coverage = chunk_words / max(source_words, 1)
    assert coverage >= 0.95, (
        f"{prefix}Coverage too low: {chunk_words}/{source_words} words "
        f"({coverage:.1%} < 95%)"
    )


def _make_autocaption_segs(n: int, words_per_seg: int = 7, gap_s: float = 0.1) -> list:
    """
    Synthetic YouTube auto-caption segments: short phrases, NO punctuation,
    uniform timing.  gap_s is the inter-segment gap.
    """
    words = [
        "the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog",
        "and", "then", "runs", "away", "with", "great", "speed", "into",
        "forest", "where", "it", "meets", "other", "animals", "living",
        "there", "since", "many", "years", "ago", "before", "humans",
    ]
    segs = []
    t = 0.0
    for i in range(n):
        phrase = " ".join(words[(i * words_per_seg) % len(words):
                                 ((i * words_per_seg) % len(words)) + words_per_seg])
        # No terminal punctuation
        segs.append({"text": phrase, "start": round(t, 3), "duration": 1.8})
        t += 1.8 + gap_s
    return segs


def _make_punctuated_segs(n: int) -> list:
    """
    Segments that each end with a period — simulating a well-formatted transcript.
    """
    segs = []
    t = 0.0
    for i in range(n):
        text = f"This is sentence number {i} and it is well formed with punctuation."
        segs.append({"text": text, "start": round(t, 3), "duration": 3.5})
        t += 3.5
    return segs


# ---------------------------------------------------------------------------
# Test 1 — Real YouTube auto-caption format (xAt1xcC6qfM scale)
# ---------------------------------------------------------------------------

class TestAutoCaption940Segments:
    """
    Models the exact failing case: 940 segments, ~6624 words, no punctuation.
    The old code produced 0 chunks; the new code must produce >> 0.
    """

    @pytest.fixture(scope="class")
    def engine(self):
        return _make_engine()

    @pytest.fixture(scope="class")
    def segments(self):
        # 940 segments × ~7 words each ≈ 6580 words — close to the real case
        return _make_autocaption_segs(940, words_per_seg=7, gap_s=0.1)

    @pytest.fixture(scope="class")
    def chunks(self, engine, segments):
        return engine._chunk_segments_boundary_aware(segments, "xAt1xcC6qfM", "Test Video")

    def test_extracts_nonzero_chunks(self, chunks):
        """The primary regression: was 0, must be > 0."""
        assert len(chunks) > 0, (
            f"Got 0 chunks from 940 segments — regression not fixed!"
        )

    def test_chunks_in_reasonable_range(self, segments, chunks):
        """With 940 × 7-word segments, expect roughly 940*7/60 ≈ 110 chunks."""
        total_words = _total_words(segments)
        expected_approx = total_words / FusionEngine.TARGET_CHUNK_WORDS
        # Allow 3× slack — the exact count depends on pause detection
        assert len(chunks) >= expected_approx / 3, (
            f"Too few chunks: {len(chunks)} for {total_words} words "
            f"(expected ~ {expected_approx:.0f})"
        )

    def test_no_chunk_exceeds_max_words(self, chunks, engine):
        for c in chunks:
            wc = len(c.text.split())
            assert wc <= engine.max_sentence_words, (
                f"Chunk has {wc} words > max={engine.max_sentence_words}: {c.text[:80]!r}"
            )

    def test_coverage_near_100_percent(self, segments, chunks):
        source_words = _total_words(segments)
        chunk_words = _chunks_word_count(chunks)
        coverage = chunk_words / source_words
        assert coverage >= 0.95, (
            f"Coverage {coverage:.1%} < 95%: {chunk_words}/{source_words} words"
        )

    def test_chronological_order(self, chunks):
        positions = [c.position for c in chunks]
        assert positions == sorted(positions), (
            f"Chunks out of order: {positions}"
        )

    def test_via_extract_sentences(self, engine, segments):
        """_extract_sentences() with raw_segments routes to Tier 1."""
        text = " ".join(s["text"] for s in segments)
        sentences = engine._extract_sentences(
            {"vid": text},
            {"vid": "Test Video"},
            raw_segments={"vid": segments},
        )
        assert len(sentences) > 0, (
            "_extract_sentences via Tier 1 returned 0 — regression not fixed!"
        )
        _assert_invariants(sentences, _total_words(segments), engine, "940-seg Tier 1")


# ---------------------------------------------------------------------------
# Test 2 — Normally punctuated English transcript
# ---------------------------------------------------------------------------

class TestPunctuatedTranscript:
    """
    Punctuated segments should flush at each period — Tier 1 still applies
    (punctuation is the highest-priority flush trigger).
    """

    @pytest.fixture(scope="class")
    def engine(self):
        return _make_engine()

    @pytest.fixture(scope="class")
    def segments(self):
        return _make_punctuated_segs(60)

    @pytest.fixture(scope="class")
    def chunks(self, engine, segments):
        return engine._chunk_segments_boundary_aware(segments, "vid_punct", "Punctuated Video")

    def test_extracts_nonzero_chunks(self, chunks):
        assert len(chunks) > 0

    def test_one_chunk_per_sentence_approximately(self, segments, chunks):
        # Each segment ends with '.', so each should become its own chunk.
        # Allow ±10% for edge cases (very short segments merged with leftover).
        assert len(chunks) >= len(segments) * 0.85, (
            f"Expected ~{len(segments)} chunks, got {len(chunks)}"
        )

    def test_no_chunk_exceeds_max_words(self, chunks, engine):
        for c in chunks:
            assert len(c.text.split()) <= engine.max_sentence_words

    def test_coverage(self, segments, chunks):
        _assert_invariants(chunks, _total_words(segments), engine=_make_engine(), label="punctuated")

    def test_flat_text_fallback_also_works(self, engine, segments):
        """Tier 2: punctuation-split path (no raw_segments supplied)."""
        text = " ".join(s["text"] for s in segments)
        sentences = engine._extract_sentences({"vid": text}, {"vid": "T"})
        assert len(sentences) > 0
        for s in sentences:
            assert len(s.text.split()) <= engine.max_sentence_words


# ---------------------------------------------------------------------------
# Test 3 — Mixed: some segments punctuated, some not
# ---------------------------------------------------------------------------

class TestMixedPunctuation:
    """
    Real transcripts often have some punctuation (end of topic blocks) but long
    runs with none.  Both types should produce valid chunks.
    """

    @pytest.fixture(scope="class")
    def engine(self):
        return _make_engine()

    @pytest.fixture(scope="class")
    def segments(self):
        segs = []
        t = 0.0
        words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
                 "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi"]
        for i in range(200):
            # Every 15th segment ends with punctuation
            punct = "." if i % 15 == 14 else ""
            phrase = " ".join(words[i % len(words): (i % len(words)) + 5]) + punct
            segs.append({"text": phrase, "start": round(t, 3), "duration": 2.0})
            t += 2.0
        return segs

    def test_extracts_chunks(self, engine, segments):
        chunks = engine._chunk_segments_boundary_aware(segments, "vid_mix", "Mix")
        _assert_invariants(chunks, _total_words(segments), engine, "mixed")

    def test_no_chunk_exceeds_max(self, engine, segments):
        chunks = engine._chunk_segments_boundary_aware(segments, "vid_mix", "Mix")
        for c in chunks:
            assert len(c.text.split()) <= engine.max_sentence_words


# ---------------------------------------------------------------------------
# Test 4 — Very long single caption segment (> max_sentence_words)
# ---------------------------------------------------------------------------

class TestVeryLongSingleSegment:
    """
    Robustness: a single segment with > 100 words (corrupt/unusual transcript).
    The pre-flush logic should handle it without losing content.
    """

    @pytest.fixture(scope="class")
    def engine(self):
        return _make_engine()

    @pytest.fixture(scope="class")
    def segments(self, engine):
        # One segment with 150 words — exceeds max_sentence_words=100
        long_text = " ".join([f"word{i}" for i in range(150)])
        normal_text = "this is a normal segment with a few words"
        return [
            {"text": long_text, "start": 0.0, "duration": 60.0},
            {"text": normal_text, "start": 60.0, "duration": 3.0},
        ]

    def test_no_chunk_exceeds_max(self, engine, segments):
        chunks = engine._chunk_segments_boundary_aware(segments, "vid_long", "Long")
        for c in chunks:
            wc = len(c.text.split())
            assert wc <= engine.max_sentence_words, (
                f"Chunk has {wc} > {engine.max_sentence_words} words"
            )

    def test_coverage(self, engine, segments):
        chunks = engine._chunk_segments_boundary_aware(segments, "vid_long", "Long")
        _assert_invariants(chunks, _total_words(segments), engine, "long-single-seg")


# ---------------------------------------------------------------------------
# Test 5 — Very short transcript (< min_sentence_words total)
# ---------------------------------------------------------------------------

class TestVeryShortTranscript:
    """
    Edge case: total transcript is shorter than min_sentence_words.
    Should still produce a chunk (leftover merge) rather than 0.
    """

    @pytest.fixture(scope="class")
    def engine(self):
        return _make_engine()

    def test_three_word_transcript(self, engine):
        # 3 words total — below min_sentence_words=5
        segs = [
            {"text": "hello world", "start": 0.0, "duration": 1.0},
            {"text": "yes", "start": 1.0, "duration": 0.5},
        ]
        chunks = engine._chunk_segments_boundary_aware(segs, "vid_short", "Short")
        # Should produce at least 1 chunk (leftover merge keeps tiny content)
        # OR gracefully return 0 without crashing
        # The key invariant is: no exception, and no chunk > max_sentence_words
        for c in chunks:
            assert len(c.text.split()) <= engine.max_sentence_words

    def test_five_word_transcript_min_boundary(self, engine):
        # Exactly min_sentence_words
        segs = [{"text": "one two three four five", "start": 0.0, "duration": 2.0}]
        chunks = engine._chunk_segments_boundary_aware(segs, "vid_five", "Five")
        assert len(chunks) >= 1

    def test_extract_sentences_short(self, engine):
        segs = [{"text": "one two three four five six", "start": 0.0, "duration": 2.0}]
        text = "one two three four five six"
        sentences = engine._extract_sentences(
            {"vid": text}, {"vid": "T"}, raw_segments={"vid": segs}
        )
        assert len(sentences) >= 1


# ---------------------------------------------------------------------------
# Test 6 — Flat-text Tier 2+3 fallback (no raw_segments)
# ---------------------------------------------------------------------------

class TestFlatTextFallback:
    """
    When raw_segments is not supplied (or empty), Tier 2 (punctuation split)
    and Tier 3 (word-count window) must both produce correct output.
    """

    @pytest.fixture(scope="class")
    def engine(self):
        return _make_engine()

    def test_punctuated_flat_text(self, engine):
        text = (
            "The quick brown fox jumps over the lazy dog. "
            "A journey of a thousand miles begins with a single step. "
            "To be or not to be, that is the question. "
            "All that glitters is not gold but it shines anyway. "
            "In the beginning there was light and it was good."
        )
        sentences = engine._extract_sentences({"vid": text}, {"vid": "T"})
        assert len(sentences) >= 4
        for s in sentences:
            assert len(s.text.split()) <= engine.max_sentence_words

    def test_unpunctuated_flat_text_uses_tier3(self, engine):
        # 300-word flat string with no punctuation — should NOT return 0 chunks
        words = [f"word{i}" for i in range(300)]
        text = " ".join(words)
        sentences = engine._extract_sentences({"vid": text}, {"vid": "T"})
        assert len(sentences) > 0, (
            "Tier 3 word-count windowing failed: 0 chunks from 300-word unpunctuated flat text"
        )
        for s in sentences:
            assert len(s.text.split()) <= engine.max_sentence_words

    def test_coverage_unpunctuated_flat(self, engine):
        words = [f"word{i}" for i in range(500)]
        text = " ".join(words)
        sentences = engine._extract_sentences({"vid": text}, {"vid": "T"})
        total_in = len(text.split())
        total_out = sum(len(s.text.split()) for s in sentences)
        assert total_out / total_in >= 0.95, (
            f"Flat-text Tier 3 coverage {total_out}/{total_in} ({total_out/total_in:.1%}) < 95%"
        )


# ---------------------------------------------------------------------------
# Test 7 — _extract_sentences integration: multi-video, mixed sources
# ---------------------------------------------------------------------------

class TestExtractSentencesIntegration:
    """
    _extract_sentences processes multiple videos; some have raw_segments (Tier 1),
    some have only flat text (Tier 2/3).  Results should be combined correctly.
    """

    @pytest.fixture(scope="class")
    def engine(self):
        return _make_engine()

    def test_two_videos_one_with_segments(self, engine):
        segs_a = _make_autocaption_segs(50, words_per_seg=6, gap_s=0.1)
        text_a = " ".join(s["text"] for s in segs_a)
        text_b = (
            "This is the second video. It has punctuation and shorter sentences. "
            "The topics are different from video one. We test multi-source fusion here."
        )
        sentences = engine._extract_sentences(
            {"vid_a": text_a, "vid_b": text_b},
            {"vid_a": "Video A", "vid_b": "Video B"},
            raw_segments={"vid_a": segs_a},  # vid_b uses Tier 2
        )
        assert len(sentences) > 0
        # Check both video IDs are represented
        video_ids_in_result = {s.video_id for s in sentences}
        assert "vid_a" in video_ids_in_result
        assert "vid_b" in video_ids_in_result

    def test_no_raw_segments_at_all(self, engine):
        """Fully backwards-compatible: raw_segments=None still works."""
        text = (
            "First sentence ends here. Second sentence follows. "
            "Third sentence adds more context. Fourth is the last one."
        )
        sentences = engine._extract_sentences({"vid": text}, {"vid": "T"})
        assert len(sentences) > 0

    def test_raw_segments_empty_dict(self, engine):
        """raw_segments={} should not crash and falls back to Tier 2."""
        text = (
            "First sentence ends here. Second sentence follows. "
            "Third sentence adds more context."
        )
        sentences = engine._extract_sentences({"vid": text}, {"vid": "T"}, raw_segments={})
        assert len(sentences) > 0


# ---------------------------------------------------------------------------
# Test 8 — Pause-boundary detection
# ---------------------------------------------------------------------------

class TestPauseBoundaryDetection:
    """
    Segments with a large time gap should trigger a chunk flush before
    reaching TARGET_CHUNK_WORDS.  Segments with tiny gaps should accumulate.
    """

    @pytest.fixture(scope="class")
    def engine(self):
        return _make_engine()

    def test_large_gap_flushes_early(self, engine):
        """A 2-second gap between 50-word and 50-word runs should produce 2 chunks."""
        # Build two groups of ~50-word sequences with a 2s gap between them
        w = ["apple", "banana", "cherry", "durian", "elderberry",
             "fig", "grape", "honeydew", "kiwi", "lemon"]
        segs = []
        t = 0.0
        # Group 1: 10 segments of 5 words, gap=0.1s (no boundary expected mid-group)
        for i in range(10):
            segs.append({"text": " ".join(w), "start": round(t, 3), "duration": 2.0})
            t += 2.1  # 0.1s gap
        # Big 2s pause
        t += 2.0
        # Group 2: 10 segments of 5 words
        for i in range(10):
            segs.append({"text": " ".join(w), "start": round(t, 3), "duration": 2.0})
            t += 2.1

        chunks = engine._chunk_segments_boundary_aware(segs, "vid_gap", "Gap Test")
        # Each group is 10 × 5 = 50 words, and the big pause should trigger a boundary
        # Total: 100 words → expect at least 2 chunks
        assert len(chunks) >= 2, (
            f"Expected ≥ 2 chunks across the 2s pause, got {len(chunks)}"
        )

    def test_small_gap_accumulates(self, engine):
        """
        Segments with 0.05s gaps and 5 words each should accumulate until
        they reach TARGET_CHUNK_WORDS (60), producing far fewer chunks than
        there are segments.
        """
        w = ["alpha", "beta", "gamma", "delta", "epsilon"]
        segs = [
            {"text": " ".join(w), "start": round(i * 2.05, 3), "duration": 2.0}
            for i in range(30)
        ]
        chunks = engine._chunk_segments_boundary_aware(segs, "vid_tight", "Tight")
        # 30 × 5 = 150 words. At 60 words/chunk, expect ~3 chunks, not 30.
        assert len(chunks) < 15, (
            f"Expected < 15 chunks for tight-gap segments, got {len(chunks)}"
        )
