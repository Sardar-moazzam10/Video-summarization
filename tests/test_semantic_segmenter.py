"""Tests for semantic_segmenter — sentence reconstruction and boundary finding."""

import pytest

from backend.services.semantic_segmenter import (
    Sentence,
    build_semantic_segments,
    build_sentences,
    segment_semantically,
)


class TestBuildSentences:
    def test_rejoins_a_sentence_split_across_caption_entries(self):
        raw = [
            {"text": "Overfitting happens when a model", "start": 0.0, "duration": 2.0},
            {"text": "memorises the training data", "start": 2.0, "duration": 2.0},
            {"text": "instead of generalising.", "start": 4.0, "duration": 2.0},
            {"text": "So you regularise.", "start": 6.0, "duration": 2.0},
        ]
        sentences = build_sentences(raw)
        assert len(sentences) == 2
        assert sentences[0].text.endswith("generalising.")
        assert sentences[0].start == 0.0
        assert sentences[0].end == 6.0

    def test_splits_multiple_sentences_inside_one_entry(self):
        raw = [{"text": "Right. So what is overfitting? Let me explain.",
                "start": 10.0, "duration": 6.0}]
        sentences = build_sentences(raw)
        assert len(sentences) == 3
        assert sentences[0].start == 10.0
        # Spans are contiguous and end exactly where the entry ended.
        assert sentences[-1].end == pytest.approx(16.0)
        for a, b in zip(sentences, sentences[1:]):
            assert a.end == pytest.approx(b.start)

    def test_unpunctuated_transcript_falls_back_to_length_and_pauses(self):
        # Auto-captions: no punctuation anywhere.
        raw = [
            {"text": f"word{i} filler text here", "start": i * 2.0, "duration": 2.0}
            for i in range(20)
        ]
        sentences = build_sentences(raw)
        assert len(sentences) > 1, "must not return one giant sentence"
        assert all(s.word_count > 0 for s in sentences)
        # Nothing is dropped: every source word survives somewhere.
        assert sum(s.word_count for s in sentences) == 20 * 4

    def test_a_real_pause_breaks_a_sentence(self):
        raw = [
            {"text": "first thought here", "start": 0.0, "duration": 2.0},
            {"text": "second thought here", "start": 10.0, "duration": 2.0},
        ]
        sentences = build_sentences(raw)
        assert len(sentences) == 2

    def test_entries_without_timestamps_are_skipped_not_defaulted_to_zero(self):
        raw = [
            {"text": "has a timestamp", "start": 5.0, "duration": 2.0},
            {"text": "has none"},
            {"text": "also none", "start": None},
        ]
        sentences = build_sentences(raw)
        assert len(sentences) == 1
        assert sentences[0].start == 5.0

    def test_empty_input(self):
        assert build_sentences([]) == []
        assert build_sentences(None) == []


class TestSegmentSemantically:
    def _sentences(self, topics, words_each=8, seconds_each=6.0):
        out, t = [], 0.0
        for topic in topics:
            for i in range(words_each):
                out.append(Sentence(text=f"{topic} concept detail {i}", start=t, end=t + seconds_each))
                t += seconds_each
        return out

    def test_finds_a_boundary_between_two_distinct_topics(self, embedder):
        sentences = self._sentences(["overfitting regularisation", "transformers attention"])
        segments = segment_semantically(
            sentences, video_id="v1", min_duration=20.0, max_duration=90.0, embedder=embedder
        )
        assert len(segments) >= 2
        # The topic switch is at t = 8 * 6.0 = 48s; some boundary should be near it.
        assert any(abs(s.start_time - 48.0) < 15.0 for s in segments[1:])

    def test_segments_never_start_or_end_mid_sentence(self, embedder):
        sentences = self._sentences(["alpha beta", "gamma delta", "epsilon zeta"])
        segments = segment_semantically(sentences, "v1", 20.0, 90.0, embedder)
        starts = {round(s.start, 3) for s in sentences}
        ends = {round(s.end, 3) for s in sentences}
        for seg in segments:
            assert round(seg.start_time, 3) in starts
            assert round(seg.end_time, 3) in ends
            assert seg.completeness == 1.0

    def test_respects_the_duration_ceiling(self, embedder):
        # One uniform topic: no valley will ever be found, so only the forced
        # max_duration cut can split it.
        sentences = self._sentences(["identical text"], words_each=40, seconds_each=6.0)
        segments = segment_semantically(sentences, "v1", 20.0, 60.0, embedder)
        assert len(segments) > 1
        # A forced cut lands on a sentence boundary, so a segment can end
        # slightly past the ceiling rather than truncating mid-sentence.
        assert all(s.duration <= 60.0 + 6.0 for s in segments)

    def test_no_segment_is_below_the_floor_unless_it_is_the_only_one(self, embedder):
        sentences = self._sentences(["alpha beta", "gamma delta"], words_each=6, seconds_each=6.0)
        segments = segment_semantically(sentences, "v1", 25.0, 90.0, embedder)
        if len(segments) > 1:
            assert all(s.duration >= 25.0 for s in segments)

    def test_nothing_is_lost(self, embedder):
        sentences = self._sentences(["alpha", "beta", "gamma"], words_each=10, seconds_each=4.0)
        segments = segment_semantically(sentences, "v1", 20.0, 90.0, embedder)
        assert sum(len(s.sentences) for s in segments) == len(sentences)
        assert segments[0].start_time == sentences[0].start
        assert segments[-1].end_time == sentences[-1].end

    def test_single_sentence(self, embedder):
        segments = segment_semantically(
            [Sentence("only one", 0.0, 5.0)], "v1", 20.0, 90.0, embedder
        )
        assert len(segments) == 1

    def test_survives_a_broken_embedder(self):
        class Broken:
            def encode(self, texts, **kw):
                raise RuntimeError("model gone")

        sentences = self._sentences(["alpha"], words_each=20, seconds_each=5.0)
        segments = segment_semantically(sentences, "v1", 20.0, 60.0, Broken())
        assert segments, "must degrade to duration-only boundaries, not fail"


class TestEndToEnd:
    def test_build_semantic_segments(self, embedder, transcript_factory):
        raw = transcript_factory(
            [("overfitting", "regularisation"), ("transformers", "attention"), ("evaluation", "metrics")],
            entries_per_topic=20,
        )
        segments = build_semantic_segments(raw, "vid1", 20.0, 90.0, embedder)
        assert len(segments) >= 2
        assert all(s.video_id == "vid1" for s in segments)
        assert all(s.duration > 0 for s in segments)
        # Chronological and non-overlapping.
        for a, b in zip(segments, segments[1:]):
            assert a.end_time <= b.start_time + 0.01

    def test_unusable_transcript_returns_empty_for_the_caller_to_fall_back(self, embedder):
        assert build_semantic_segments([], "v", embedder=embedder) == []
        assert build_semantic_segments([{"text": "no timestamp"}], "v", embedder=embedder) == []


class TestSegmentationCache:
    """
    Requirement: the five duration modes of one video must share ONE semantic
    analysis. Segmentation embeds every sentence of the transcript (61-69s for a
    75-minute lecture), and that work does not depend on the requested summary
    length, so paying for it five times is pure waste.
    """

    def setup_method(self):
        from backend.services.semantic_segmenter import clear_segment_cache
        clear_segment_cache()

    def teardown_method(self):
        from backend.services.semantic_segmenter import clear_segment_cache
        clear_segment_cache()

    def _raw(self, n=60):
        return [{"text": f"topic{i // 10} sentence body words here.", "start": i * 3.0,
                 "duration": 3.0} for i in range(n)]

    def test_five_duration_modes_embed_the_transcript_once(self, embedder):
        raw = self._raw()
        results = [
            build_semantic_segments(raw, "v1", 20.0, 90.0, embedder)
            for _ in range(5)          # 5, 10, 15, 20, 30 minute requests
        ]
        assert embedder.calls == 1, (
            f"transcript was embedded {embedder.calls} times for 5 duration modes"
        )
        for r in results[1:]:
            assert [(s.video_id, s.start_time, s.end_time, s.text) for s in r] == [
                (s.video_id, s.start_time, s.end_time, s.text) for s in results[0]]
            assert r is not results[0], "job-specific concept scores must not mutate the cache"

    def test_a_different_transcript_is_not_served_from_cache(self, embedder):
        build_semantic_segments(self._raw(60), "v1", 20.0, 90.0, embedder)
        build_semantic_segments(self._raw(90), "v2", 20.0, 90.0, embedder)
        assert embedder.calls == 2

    def test_different_duration_bounds_are_a_different_analysis(self, embedder):
        raw = self._raw()
        build_semantic_segments(raw, "v1", 20.0, 90.0, embedder)
        build_semantic_segments(raw, "v1", 30.0, 120.0, embedder)
        assert embedder.calls == 2, "bounds change the segmentation, so they must not share a key"

    def test_cache_can_be_bypassed(self, embedder):
        raw = self._raw()
        build_semantic_segments(raw, "v1", 20.0, 90.0, embedder)
        build_semantic_segments(raw, "v1", 20.0, 90.0, embedder, use_cache=False)
        assert embedder.calls == 2

    def test_cache_is_bounded(self, embedder):
        from backend.services.semantic_segmenter import _SEGMENT_CACHE, _SEGMENT_CACHE_MAX
        for i in range(_SEGMENT_CACHE_MAX + 4):
            build_semantic_segments(self._raw(60 + i), f"v{i}", 20.0, 90.0, embedder)
        assert len(_SEGMENT_CACHE) <= _SEGMENT_CACHE_MAX, "unbounded cache is a leak"
