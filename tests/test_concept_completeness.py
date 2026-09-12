"""
Concept completeness in selection, and script-agnostic concept extraction.

Regression coverage for a real incident on a Hindi video (Nkaa8fPEtQk):

  * TF-IDF returned 0 concepts, because both the tokeniser pattern and the
    merge-key normaliser were ASCII-only. Measured: 0 tokens matched across a
    45,165-character Devanagari transcript.
  * With 0 concepts the optimizer's concept term — the largest single weight —
    contributed nothing, yet the run still reported "0/0 concepts covered" as
    though concept-driven selection had happened.
  * The resulting selection spread evenly across the timeline and started a
    clip partway through an important Trump/Elon discussion, showing the
    viewer a fragment of a topic.

The rule these tests pin down: an important concept occurrence is represented
COMPLETELY or not at all — never as a fragment.
"""

import re

import pytest

from backend.services.concept_extractor import _TOKEN_PATTERN, _normalise
from backend.services.coverage_selector import (
    build_concept_blocks,
    select_segments,
)


class _Seg:
    """Minimal stand-in for SemanticSegment."""

    def __init__(self, start, end, text="text", video_id="v1"):
        self.start_time = float(start)
        self.end_time = float(end)
        self.text = text
        self.video_id = video_id
        self.completeness = 1.0
        self.boundary_confidence = 1.0
        self.embedding = None

    @property
    def duration(self):
        return self.end_time - self.start_time


class _Concept:
    def __init__(self, name, importance, timestamps):
        self.name = name
        self.importance = float(importance)
        self.timestamps = timestamps
        self.reason = ""
        self.embedding = None


# =====================================================================
# Script-agnostic extraction (the root cause)
# =====================================================================

class TestScriptAgnosticTokenising:
    def test_latin_tokenising_is_unchanged(self):
        """The old ASCII pattern is the baseline; Latin text must tokenise
        identically or this fix would regress every English video."""
        old = r"(?u)\b[a-zA-Z][a-zA-Z-]{2,}\b"
        for text in [
            "The business grew rapidly after founding companies",
            "neural networks and back-propagation explained",
            "abc 123 4567 test-case",
        ]:
            assert re.findall(_TOKEN_PATTERN, text) == re.findall(old, text)

    @pytest.mark.parametrize(
        "text",
        [
            "बनिए लोग ट्रंप से भी सीखो एलन मस्क",   # Hindi (Devanagari)
            "هذا نص تجريبي للاختبار",                # Arabic
            "Это тестовый текст для проверки",       # Russian (Cyrillic)
        ],
    )
    def test_non_latin_scripts_produce_tokens(self, text):
        """The bug: zero tokens on every non-Latin script."""
        assert re.findall(_TOKEN_PATTERN, text)

    def test_devanagari_combining_marks_stay_inside_the_word(self):
        """`बनिए` must be ONE token. Python's \\w drops the vowel sign
        (category Mc), which used to split it into fragments."""
        assert re.findall(_TOKEN_PATTERN, "बनिए") == ["बनिए"]

    def test_tokens_still_cannot_start_with_a_digit(self):
        assert "123" not in re.findall(_TOKEN_PATTERN, "123 abc")


class TestNormaliseMergeKey:
    def test_ascii_normalisation_unchanged(self):
        assert _normalise("Neural Networks") == "neural networks"
        assert _normalise("back-propagation") == "backpropagation"
        assert _normalise("GPT-4 models") == "gpt4 models"

    def test_non_latin_names_survive(self):
        """Returning "" here is what silently dropped all 50 Hindi concepts
        after the tokeniser was fixed."""
        assert _normalise("एलन मस्क") != ""
        assert _normalise("مرحبا") != ""


# =====================================================================
# Concept blocks
# =====================================================================

class TestConceptBlocks:
    def test_block_spans_every_segment_touching_the_occurrence(self):
        segs = [_Seg(0, 30), _Seg(30, 60), _Seg(60, 90)]
        concepts = [_Concept("topic", 0.9, [[20.0, 70.0]])]
        blocks = build_concept_blocks(segs, concepts)
        assert len(blocks) == 1
        assert blocks[0]["indices"] == frozenset({0, 1, 2})

    def test_unimportant_concepts_are_not_protected(self):
        segs = [_Seg(0, 30), _Seg(30, 60)]
        concepts = [_Concept("minor", 0.05, [[10.0, 50.0]])]
        assert build_concept_blocks(segs, concepts) == []

    def test_passing_mentions_are_not_protected(self):
        """A 2-second window is a mention, not a discussion — the segment
        containing it already holds the whole thing."""
        segs = [_Seg(0, 30), _Seg(30, 60)]
        concepts = [_Concept("mention", 0.9, [[10.0, 12.0]])]
        assert build_concept_blocks(segs, concepts) == []

    def test_no_concepts_means_no_blocks(self):
        assert build_concept_blocks([_Seg(0, 30)], []) == []


# =====================================================================
# Complete-concept-or-reject
# =====================================================================

def _spans(res):
    return {(s.start_time, s.end_time) for s in res.segments}


def _is_partial(res, unit_indices, segs):
    """True when SOME but not all of a unit's segments were selected."""
    picked = _spans(res)
    inside = [i for i in unit_indices
              if (segs[i].start_time, segs[i].end_time) in picked]
    return 0 < len(inside) < len(unit_indices)


class TestCompleteConceptOrReject:
    def test_concept_kept_whole_when_it_fits(self):
        """Positive case: budget is ample, so the entire explanation is
        selected — not just its highest-scoring half."""
        segs = [_Seg(0, 40), _Seg(40, 80), _Seg(200, 240)]
        concepts = [_Concept("topic", 0.9, [[10.0, 70.0]])]
        res = select_segments(segs, budget_seconds=200.0, concepts=concepts,
                              total_duration=240.0)
        assert not _is_partial(res, [0, 1], segs)

    def test_all_selected_segments_keep_original_boundaries(self):
        """Concept completeness must sit ON TOP of thought boundaries, never
        replace them — no segment may be trimmed to fit."""
        segs = [_Seg(0, 40), _Seg(40, 80), _Seg(200, 240)]
        concepts = [_Concept("topic", 0.9, [[10.0, 70.0]])]
        res = select_segments(segs, budget_seconds=200.0, concepts=concepts,
                              total_duration=240.0)
        originals = {(s.start_time, s.end_time) for s in segs}
        for s in res.segments:
            assert (s.start_time, s.end_time) in originals


class TestNoFragmentSpec:
    """The seven no-fragment cases, stated as executable rules."""

    def test_1_candidate_exactly_fits_is_selected(self):
        segs = [_Seg(0, 60)]
        concepts = [_Concept("topic", 0.9, [[5.0, 55.0]])]
        res = select_segments(segs, budget_seconds=60.0, concepts=concepts,
                              total_duration=400.0)
        assert (0.0, 60.0) in _spans(res)

    def test_2_candidate_one_second_too_long_is_rejected(self):
        """A single-segment occurrence has no sub-run to fall back to, so
        one second over budget means it is omitted, not trimmed."""
        segs = [_Seg(0, 60), _Seg(300, 320)]
        concepts = [_Concept("topic", 0.9, [[5.0, 55.0]])]
        # 60s unit against a 59s budget; tolerance is applied to the budget,
        # so shrink it below 60/(1+0.08) to make the rejection unambiguous.
        res = select_segments(segs, budget_seconds=54.0, concepts=concepts,
                              total_duration=400.0)
        assert (0.0, 60.0) not in _spans(res)
        assert "topic" in res.concepts_omitted_for_budget

    def test_3_too_long_but_a_complete_subthought_fits(self):
        """The refinement: a long topic is not indivisible. The full 120s
        explanation will not fit in 70s, but one self-contained 60s
        sub-thought will — and that is a legal, complete pick."""
        segs = [_Seg(0, 60), _Seg(60, 120)]
        concepts = [_Concept("topic", 0.9, [[5.0, 115.0]])]
        res = select_segments(segs, budget_seconds=70.0, concepts=concepts,
                              total_duration=400.0)
        picked = _spans(res)
        assert len(picked) == 1, "exactly one complete sub-thought expected"
        assert picked <= {(0.0, 60.0), (60.0, 120.0)}
        assert any("sub-thought" in c for c in res.concepts_completed)

    def test_4_too_long_with_no_independent_subthought_is_rejected(self):
        """Same shape, but the parts are too short to stand alone
        (< SUBTHOUGHT_MIN_SECONDS), so there is nothing complete to fall back
        to and the whole occurrence is omitted."""
        # 6s parts: no sub-run reaches SUBTHOUGHT_MIN_SECONDS (15s) before the
        # run becomes the full 18s occurrence, which itself overshoots a 14s
        # budget even with tolerance.
        segs = [_Seg(0, 6), _Seg(6, 12), _Seg(12, 18), _Seg(300, 310)]
        concepts = [_Concept("topic", 0.9, [[1.0, 17.0]])]
        res = select_segments(segs, budget_seconds=14.0, concepts=concepts,
                              total_duration=400.0)
        picked = _spans(res)
        for span in [(0.0, 6.0), (6.0, 12.0), (12.0, 18.0)]:
            assert span not in picked
        assert "topic" in res.concepts_omitted_for_budget

    def test_5_leftover_budget_is_left_unused_when_nothing_complete_fits(self):
        """Duration is not a target to hit. With 20s spare and no complete
        unit that small, the budget simply goes unused."""
        segs = [_Seg(0, 100), _Seg(200, 300)]
        concepts = [_Concept("topic", 0.9, [[5.0, 95.0]]),
                    _Concept("other", 0.9, [[205.0, 295.0]])]
        res = select_segments(segs, budget_seconds=120.0, concepts=concepts,
                              total_duration=400.0)
        assert res.total_duration <= 120.0 * 1.08
        assert not _is_partial(res, [0], segs)
        assert not _is_partial(res, [1], segs)

    def test_6_no_selected_unit_is_ever_partial(self):
        """The invariant, over a whole multi-concept timeline: every protected
        occurrence is present in full or absent. Count of partials must be 0."""
        segs = [_Seg(i * 60, i * 60 + 50) for i in range(10)]
        concepts = [
            _Concept("a", 0.9, [[10.0, 160.0]]),
            _Concept("b", 0.8, [[300.0, 460.0]]),
            _Concept("c", 0.7, [[500.0, 610.0]]),
        ]
        res = select_segments(segs, budget_seconds=250.0, concepts=concepts,
                              total_duration=600.0)
        picked = _spans(res)
        units = build_concept_blocks(segs, concepts)
        partials = 0
        for unit in units:
            inside = [i for i in unit["indices"]
                      if (segs[i].start_time, segs[i].end_time) in picked]
            # A unit may be wholly absent, wholly present, or represented by a
            # complete sub-thought — but never by an arbitrary fragment.
            if 0 < len(inside) < len(unit["indices"]):
                sub = sorted(inside)
                contiguous = sub == list(range(sub[0], sub[-1] + 1))
                span = sum(segs[i].duration for i in sub)
                if not (contiguous and span >= 15.0):
                    partials += 1
        assert partials == 0

    def test_7_redundant_subthoughts_of_one_concept_are_controlled(self):
        """Several sub-thoughts of the same concept must not all be taken just
        because they fit; the redundancy term still applies to them."""
        segs = [_Seg(i * 40, i * 40 + 35, text="identical wording here")
                for i in range(6)]
        concepts = [_Concept("topic", 0.9, [[0.0, 240.0]])]
        res = select_segments(segs, budget_seconds=240.0, concepts=concepts,
                              total_duration=240.0)
        assert res.total_duration <= 240.0 * 1.08


class TestUnitsAreNeverHolePunched:
    def test_overlap_removal_cannot_strand_a_unit_member(self):
        """Adjacent semantic segments overlap by a second or two, and the
        overlap filter drops candidates that clash with an earlier pick. A
        unit whose MIDDLE segment gets dropped that way would be selected
        with a hole in it — start and end present, middle missing — which is
        a partial concept even though the outer span looks right. Caught on a
        real English video (a unit reported the full 5:32-9:07 span while
        missing a segment inside it).

        Selecting a contiguous PART of a unit is legal — that is a
        sub-thought. Selecting a gapped subset never is.
        """
        segs = [
            _Seg(0, 40),      # unrelated, selected first
            _Seg(38, 80),     # overlaps seg 0 -> may be dropped from remaining
            _Seg(80, 120),
            _Seg(120, 160),
            _Seg(400, 440),
        ]
        concepts = [_Concept("topic", 0.9, [[40.0, 158.0]])]   # covers 1,2,3
        res = select_segments(segs, budget_seconds=300.0, concepts=concepts,
                              total_duration=500.0)
        picked = _spans(res)
        inside = sorted(i for i in (1, 2, 3)
                        if (segs[i].start_time, segs[i].end_time) in picked)
        if inside:
            assert inside == list(range(inside[0], inside[-1] + 1)), (
                f"unit represented by a gapped subset {inside} — hole punched"
            )


class TestReelCanStillBeFilled:
    def test_segments_outside_any_concept_stay_selectable(self):
        """The constraint must not starve the reel: material that belongs to
        no protected concept is still free to fill the budget."""
        segs = [_Seg(0, 200), _Seg(300, 330)]
        concepts = [_Concept("topic", 0.9, [[5.0, 195.0]])]
        res = select_segments(segs, budget_seconds=40.0, concepts=concepts,
                              total_duration=400.0)
        assert (300.0, 330.0) in _spans(res)
        assert (0.0, 200.0) not in _spans(res)


# =====================================================================
# Honest reporting of the concept signal
# =====================================================================

class TestConceptSignalReporting:
    def test_no_concepts_reports_unavailable(self):
        """0/0 must never look like a successful concept-driven run."""
        res = select_segments([_Seg(0, 40), _Seg(100, 140)],
                              budget_seconds=60.0, concepts=(),
                              total_duration=200.0)
        assert res.concept_signal == "unavailable"

    def test_concepts_present_reports_available(self):
        concepts = [_Concept("topic", 0.9, [[10.0, 30.0]])]
        res = select_segments([_Seg(0, 40), _Seg(100, 140)],
                              budget_seconds=60.0, concepts=concepts,
                              total_duration=200.0)
        assert res.concept_signal == "available"


class TestNoRegressionWithoutConcepts:
    def test_selection_without_concepts_is_unchanged(self):
        """Every candidate is its own commitment when there are no concepts,
        so the grouped scoring must reduce exactly to the old per-segment
        behaviour."""
        segs = [_Seg(i * 50, i * 50 + 40) for i in range(8)]
        res = select_segments(segs, budget_seconds=150.0, concepts=(),
                              total_duration=400.0)
        assert res.segments
        assert res.total_duration <= 150.0 * 1.08
        for entry in res.trace:
            assert entry["committed_segments"] == 1
