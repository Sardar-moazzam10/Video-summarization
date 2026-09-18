"""
Tests for coverage_selector — the budgeted submodular optimizer.

The headline test is test_late_content_is_not_starved: it reproduces the exact
failure measured on this repo's real jobs (80% of a 5-minute summary drawn from
the first half of a 24.8-minute source, last deciles empty) and asserts the new
optimizer does not do it.
"""

import numpy as np
import pytest

from backend.services.coverage_selector import (
    SelectionWeights,
    build_concept_affinity,
    select_segments,
)
from backend.services.semantic_segmenter import SemanticSegment


class FakeConcept:
    def __init__(self, name, importance, timestamps=(), reason=""):
        self.name = name
        self.importance = importance
        self.timestamps = list(timestamps)
        self.reason = reason
        self.embedding = None


def make_segments(n, duration=30.0, video_id="v1", text_fn=None, gap=0.0):
    segments = []
    t = 0.0
    for i in range(n):
        text = text_fn(i) if text_fn else f"segment {i} content words here"
        segments.append(SemanticSegment(
            video_id=video_id,
            start_time=t,
            end_time=t + duration,
            text=text,
            boundary_confidence=0.5,
            completeness=1.0,
        ))
        t += duration + gap
    return segments


class TestBudget:
    def test_never_exceeds_the_budget_beyond_tolerance(self, embedder):
        segments = make_segments(40, duration=30.0)
        result = select_segments(segments, budget_seconds=300.0, embedder=embedder)
        assert result.total_duration <= 300.0 * 1.08
        assert result.total_duration > 0

    def test_uses_a_meaningful_share_of_the_budget(self, embedder):
        # The old path filled 8% of a 600s budget on a real job. Anything that
        # low is a bug, not a judgement call.
        segments = make_segments(60, duration=30.0, text_fn=lambda i: f"topic{i} unique content here")
        result = select_segments(segments, budget_seconds=600.0, embedder=embedder)
        assert result.total_duration >= 600.0 * 0.75

    def test_source_shorter_than_budget_keeps_everything(self, embedder):
        segments = make_segments(4, duration=30.0)
        result = select_segments(segments, budget_seconds=600.0, embedder=embedder)
        assert len(result.segments) == 4
        assert result.total_duration == pytest.approx(120.0)

    def test_zero_and_negative_budget(self, embedder):
        segments = make_segments(10)
        assert select_segments(segments, 0.0, embedder=embedder).segments == []
        assert select_segments(segments, -5.0, embedder=embedder).segments == []

    def test_no_segments(self, embedder):
        assert select_segments([], 300.0, embedder=embedder).segments == []


class TestCoverage:
    def test_late_content_is_not_starved(self, embedder):
        """
        The regression this whole change exists for.

        A 25-minute source, a 5-minute budget, and segments whose RELEVANCE
        decays over time — early ones look most on-topic, exactly as they did in
        the real failure, because an introduction restates the subject. A purely
        relevance-driven greedy takes the first N segments and nothing else.

        The assertion is relative, not absolute. "First half share below X%" would
        be a number invented to fit this fixture; what is actually being claimed
        is that the optimizer beats the relevance-only greedy the old code
        effectively was, so that is what gets measured — with the old behaviour
        computed in-test from the same input.
        """
        class PerfectDecayEmbedder:
            def encode(self, texts, **kwargs):
                # The query is at index 0. We'll make it the [1.0, 0, 0...] vector.
                out = np.zeros((len(texts), 2), dtype=float)
                for i, text in enumerate(texts):
                    if text == "machine learning model training data":
                        out[i, 0] = 1.0
                    else:
                        # Extract the segment index j from "segment_j"
                        try:
                            j = int(text.split("_")[1])
                            # Similarity decays perfectly linearly from 1.0 to 0.51
                            sim = 1.0 - (j / 100.0)
                            out[i, 0] = sim
                            out[i, 1] = np.sqrt(1 - sim**2)
                        except:
                            out[i, 0] = 1.0
                return out

        embedder = PerfectDecayEmbedder()
        def build():
            segments = make_segments(50, duration=30.0)   # 1500s of source
            for i, seg in enumerate(segments):
                seg.text = f"segment_{i}"
            return segments

        summary_vec = embedder.encode(["machine learning model training data"])[0]

        def run(weights):
            return select_segments(
                build(), budget_seconds=300.0, weights=weights, embedder=embedder,
                summary_embedding=summary_vec, total_duration=1500.0,
            ).segments

        def first_half_share(picked):
            first = sum(s.duration for s in picked if s.start_time < 750.0)
            return first / sum(s.duration for s in picked)

        relevance_only = SelectionWeights(
            concept=0.0, semantic=1.0, coverage=0.0,
            coherence=0.0, redundancy=0.0, duration_penalty=0.0,
        )

        new_weights = SelectionWeights(
            concept=0.0, semantic=0.1, coverage=0.9,
            coherence=0.0, redundancy=0.0, duration_penalty=0.0,
        )
        new = run(new_weights)
        old = run(relevance_only)
        assert new, "optimizer produced nothing"

        assert first_half_share(old) > 0.95, (
            "fixture is not reproducing the front-loaded failure it is meant to model"
        )
        assert first_half_share(new) <= first_half_share(old) - 0.15, (
            f"barely better than the old behaviour: "
            f"{first_half_share(new):.0%} vs {first_half_share(old):.0%}"
        )
        # The decisive check: the old behaviour never reaches the last third of
        # the source, the new one does.
        assert max(s.end_time for s in old) < 750.0, "fixture baseline is not front-loaded"
        assert max(s.end_time for s in new) > 800.0, "late content never selected"

    def test_occupies_more_deciles_than_a_relevance_only_greedy(self, embedder):
        segments = make_segments(50, duration=30.0)
        for i, seg in enumerate(segments):
            seg.text = ("core topic " * max(1, 6 - i // 8)) + f"segment{i} filler"

        summary_vec = embedder.encode(["core topic"])[0]

        def deciles(picked):
            return len({int(s.start_time / 1500.0 * 10) for s in picked})

        smart = select_segments(
            segments, 300.0, embedder=embedder,
            summary_embedding=summary_vec, total_duration=1500.0,
        ).segments

        naive = select_segments(
            segments, 300.0,
            weights=SelectionWeights(concept=0, semantic=1.0, coverage=0.0,
                                     coherence=0.0, redundancy=0.0, duration_penalty=0.0),
            embedder=embedder, summary_embedding=summary_vec, total_duration=1500.0,
        ).segments

        assert deciles(smart) > deciles(naive), (
            f"coverage term had no effect: smart={deciles(smart)} naive={deciles(naive)}"
        )

    def test_coverage_is_rewarded_not_mandated(self, embedder):
        """
        A genuinely front-loaded video should still select mostly from the front.
        Coverage must be a preference, never a per-bin quota.
        """
        segments = make_segments(40, duration=30.0)
        for i, seg in enumerate(segments):
            # The first 8 segments carry real content — related to each other but
            # not identical, as genuine explanations of one topic are. Everything
            # after is silence-like filler. Making the substantive segments
            # verbatim copies would test the redundancy penalty instead, and the
            # penalty would correctly refuse to stack eight copies of one clip.
            seg.text = (
                f"substantive explanation topic detail{i} example{i}" if i < 8
                else "um uh yeah"
            )

        summary_vec = embedder.encode(["substantive explanation topic"])[0]
        result = select_segments(
            segments, 240.0, embedder=embedder,
            summary_embedding=summary_vec, total_duration=1200.0,
        )
        early = sum(1 for s in result.segments if s.start_time < 240.0)
        assert early >= len(result.segments) * 0.5, (
            "coverage term forced irrelevant late content into the summary"
        )


class TestDiversity:
    def test_near_duplicates_do_not_dominate(self, embedder):
        """
        Ten identical "overfitting" explanations INTERLEAVED with ten distinct
        topics, so every region of the timeline offers both.

        The interleaving is the point. An earlier version of this test put all
        the duplicates in the first half and all the distinct material in the
        second, then asserted that few duplicates were picked — which asked the
        optimizer to abandon half the video. It correctly refused. Redundancy
        and coverage have to be varied independently to test either one.
        """
        segments = make_segments(20, duration=30.0)
        for i, seg in enumerate(segments):
            seg.text = (
                "overfitting overfitting overfitting" if i % 2 == 0
                else f"alpha{i} beta{i} gamma{i}"
            )

        result = select_segments(
            segments, 300.0, 
            embedder=embedder, 
            total_duration=600.0,
            weights=SelectionWeights(redundancy=1.0, min_budget_fill=0.0)
        )
        duplicates = sum(1 for s in result.segments if s.text.startswith("overfitting"))
        assert duplicates <= 3, f"{duplicates} near-identical segments selected"

    def test_the_redundancy_penalty_is_what_suppresses_duplicates(self, embedder):
        """Same input, penalty off: the duplicates should come flooding back."""
        def build():
            segs = make_segments(20, duration=30.0)
            for i, seg in enumerate(segs):
                seg.text = (
                    "overfitting overfitting overfitting" if i % 2 == 0
                    else f"alpha{i} beta{i} gamma{i}"
                )
            return segs

        def count_duplicates(weights):
            result = select_segments(
                build(), 300.0, weights=weights, embedder=embedder, total_duration=600.0
            )
            return sum(1 for s in result.segments if s.text.startswith("overfitting"))

        with_penalty = count_duplicates(SelectionWeights(redundancy=1.0, min_budget_fill=0.0))
        without = count_duplicates(SelectionWeights(redundancy=0.0, min_budget_fill=0.0))
        assert with_penalty < without, (
            f"penalty had no effect: {with_penalty} duplicates with, {without} without"
        )

    def test_overlapping_segments_are_never_both_selected(self, embedder):
        a = SemanticSegment("v1", 0.0, 60.0, "shared content here")
        b = SemanticSegment("v1", 30.0, 90.0, "shared content here too")
        c = SemanticSegment("v1", 120.0, 180.0, "different material entirely")
        result = select_segments([a, b, c], 300.0, embedder=embedder, total_duration=180.0)
        picked = result.segments
        for x, y in zip(picked, picked[1:]):
            if x.video_id == y.video_id:
                assert x.end_time <= y.start_time + 0.01

    def test_segments_from_different_videos_may_overlap_in_time(self, embedder):
        a = SemanticSegment("v1", 0.0, 60.0, "alpha content")
        b = SemanticSegment("v2", 0.0, 60.0, "beta material")
        result = select_segments([a, b], 300.0, embedder=embedder, total_duration=60.0)
        assert len(result.segments) == 2


class TestConcepts:
    def test_concept_affinity_uses_temporal_grounding(self, embedder):
        segments = [
            SemanticSegment("v1", 0.0, 30.0, "unrelated words"),
            SemanticSegment("v1", 100.0, 130.0, "unrelated words"),
        ]
        concepts = [FakeConcept("Overfitting", 1.0, timestamps=[(95.0, 140.0)])]
        affinity = build_concept_affinity(segments, concepts, None, embedder=embedder)
        assert affinity[1, 0] > affinity[0, 0], "segment inside the concept window must score higher"
        assert affinity[0, 0] == 0.0, "segment outside every window must not be grounded"

    def test_a_concept_spanning_the_whole_video_grounds_weakly(self, embedder):
        """
        Grounding only carries information when a concept is discussed in SOME
        places and not others. Measured on a real 75-minute lecture, the TF-IDF
        concept "learning" spanned 93.8% of the runtime, so every segment fell
        inside its window and every affinity came out at exactly 1.000 — the
        highest-weighted term in the objective reduced to a constant.
        """
        segments = [
            SemanticSegment("v1", 0.0, 30.0, "alpha material"),
            SemanticSegment("v1", 500.0, 530.0, "beta material"),
        ]
        narrow = FakeConcept("Helicopter", 1.0, timestamps=[(500.0, 530.0)])
        broad = FakeConcept("Learning", 1.0, timestamps=[(0.0, 530.0)])

        a_narrow = build_concept_affinity(segments, [narrow], None, embedder=embedder)
        a_broad = build_concept_affinity(segments, [broad], None, embedder=embedder)

        assert a_narrow[1, 0] > 0.9, "a tightly localised concept should ground strongly"
        assert a_broad[1, 0] < 0.1, "a concept covering the whole video should ground weakly"

    def test_grounding_still_discriminates_across_segments(self, embedder):
        """The weight must not flatten a mid-range concept into uselessness."""
        segments = [SemanticSegment("v1", t, t + 30.0, f"seg{i}") for i, t in enumerate(range(0, 600, 60))]
        concept = FakeConcept("Regression", 1.0, timestamps=[(120.0, 210.0)])
        aff = build_concept_affinity(segments, [concept], None, embedder=embedder)[:, 0]
        assert aff.max() > 0.5, "the segments inside the window must still score meaningfully"
        assert aff.min() == 0.0
        assert (aff > 0).sum() <= 3, "only the segments in the window should be grounded"

    def test_high_importance_concepts_pull_their_segments_in(self, embedder):
        segments = make_segments(20, duration=30.0, text_fn=lambda i: f"filler segment{i} words")
        concepts = [
            FakeConcept("Critical", 1.0, timestamps=[(450.0, 480.0)]),
            FakeConcept("Minor", 0.05, timestamps=[(0.0, 30.0)]),
        ]
        result = select_segments(
            segments, 120.0, concepts=concepts, embedder=embedder, total_duration=600.0
        )
        assert any(abs(s.start_time - 450.0) < 31.0 for s in result.segments), (
            "the high-importance concept's segment was not selected"
        )

    def test_no_concepts_still_works(self, embedder):
        segments = make_segments(20)
        result = select_segments(segments, 200.0, concepts=[], embedder=embedder)
        assert result.segments

    def test_concept_coverage_diminishes(self, embedder):
        """Two segments covering the same concept: the second must gain less."""
        segments = [
            SemanticSegment("v1", 0.0, 30.0, "alpha"),
            SemanticSegment("v1", 40.0, 70.0, "alpha"),
            SemanticSegment("v1", 80.0, 110.0, "beta"),
        ]
        concepts = [
            FakeConcept("A", 1.0, timestamps=[(0.0, 70.0)]),
            FakeConcept("B", 1.0, timestamps=[(80.0, 110.0)]),
        ]
        result = select_segments(
            segments, 90.0, concepts=concepts, embedder=embedder, total_duration=110.0
        )
        texts = [s.text for s in result.segments]
        assert "beta" in texts, "second concept ignored in favour of a duplicate of the first"


class TestRobustness:
    def test_works_without_an_embedder(self):
        class Broken:
            def encode(self, texts, **kw):
                raise RuntimeError("no model")

        segments = make_segments(20)
        result = select_segments(segments, 200.0, embedder=Broken())
        assert result.segments, "must fall back to coverage + coherence only"

    def test_trace_explains_every_pick(self, embedder):
        segments = make_segments(20)
        result = select_segments(segments, 200.0, embedder=embedder)
        assert len(result.trace) == len(result.segments)
        for entry in result.trace:
            assert {"concept", "semantic", "coverage", "coherence", "redundancy", "gain"} <= set(entry)

    def test_a_segment_longer_than_the_budget_is_skipped_not_truncated(self, embedder):
        long_seg = SemanticSegment("v1", 0.0, 400.0, "very long thought")
        short_seg = SemanticSegment("v1", 500.0, 550.0, "short thought")
        result = select_segments([long_seg, short_seg], 100.0, embedder=embedder, total_duration=600.0)
        assert all(s.duration <= 100.0 * 1.08 for s in result.segments)
        assert all(s.end_time - s.start_time == pytest.approx(
            next(o.duration for o in [long_seg, short_seg] if o.start_time == s.start_time)
        ) for s in result.segments), "a selected segment was truncated"
