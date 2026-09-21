"""Production multi-source contracts, using deterministic vectors and no downloads."""
import copy
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock

import numpy as np
import pytest

from backend.services.clip_manifest import freeze_manifest, validate_manifest
from backend.services.concept_extractor import Chunk, Concept, ConceptOccurrence, _cache_key
from backend.services.coverage_selector import select_segments, OVERSHOOT_TOLERANCE
from backend.services.fusion_engine import FusionEngine
from backend.services.narrative_sorter import sort_segments
from backend.services.summarization_service import SummarizationService
from backend.services.semantic_segmenter import SemanticSegment, _segment_cache_key
from backend.services.video_service import VideoService
from backend.services.manifest_boundary_repair import (
    assess_end_boundary,
    assess_start_boundary,
    explanation_completeness,
    project_semantic_boundaries,
    reconcile_physical_duration,
    rebuild_final_texts,
    repair_explanation_boundaries,
    repair_physical_boundaries,
    stitch_caption_entries,
    probe_rendered_duration,
    non_content_hits,
    normalize_caption_timeline,
)
from backend.services.concept_block_organizer import organize_concept_blocks


def segment(vid, text, vector, start=0, duration=30):
    return SemanticSegment(vid, start, start + duration, text,
                           embedding=np.asarray(vector, dtype=float),
                           boundary_confidence=1.0, completeness=1.0)


def test_duplicate_sources_do_not_fill_budget_with_repetition(embedder):
    candidates = [segment(v, "Definition of overfitting.", [1, 0, 0]) for v in "ABC"]
    result = select_segments(candidates, 120, embedder=embedder,
                             total_duration={v: 30 for v in "ABC"})
    assert len(result.segments) == 1
    assert result.duplicates_rejected == 2


def test_complementary_sources_and_complete_boundaries(embedder):
    candidates = [segment(v, text, np.eye(3)[i], start=100 * i)
                  for i, (v, text) in enumerate(zip("ABC", ["Definition.", "Example.", "Limitations."]))]
    result = select_segments(candidates, 90, embedder=embedder,
                             total_duration={s.video_id: s.end_time for s in candidates})
    assert {s.video_id for s in result.segments} == set("ABC")
    assert result.total_duration <= 90 * (1 + OVERSHOOT_TOLERANCE)
    assert {(s.video_id, s.start_time, s.end_time, s.text) for s in result.segments} == {
        (s.video_id, s.start_time, s.end_time, s.text) for s in candidates}


def test_keyword_priority_and_duplicate_competition(embedder):
    candidates = [segment("A", "Unrelated cooking.", [0, 1, 0]),
                  segment("B", "Overfitting explanation.", [1, 0, 0]),
                  segment("C", "Overfitting explanation.", [1, 0, 0])]
    result = select_segments(candidates, 30, embedder=embedder,
                             query_embedding=np.array([[1, 0, 0]]),
                             total_duration={v: 30 for v in "ABC"})
    assert len(result.segments) == 1
    assert result.segments[0].video_id in {"B", "C"}


def test_budget_never_slices_a_thought(embedder):
    candidates = [segment("A", "Long explanation.", [1, 0], duration=40),
                  segment("B", "Short explanation.", [0, 1], duration=25)]
    result = select_segments(candidates, 30, embedder=embedder)
    assert [(s.video_id, s.start_time, s.end_time) for s in result.segments] == [("B", 0, 25)]


def test_order_uses_topics_and_retains_local_chronology():
    a = segment("A", "Example.", [1, 0], start=0)
    b = segment("B", "Definition.", [0, 1], start=500)
    c = segment("B", "Continuation.", [0, 1], start=540)
    for s in [a, b, c]:
        s.concept_scores = {"definition": 0.4, "example": 0.4}
    a.concept_scores["example"] = 0.9
    b.concept_scores["definition"] = 0.9
    c.concept_scores["definition"] = 0.8
    assert sort_segments([a, c, b]) == [b, c, a]


def test_fusion_selected_evidence_preserves_interleaved_manifest_order():
    selected = [
        {"video_id": "A", "start_time": 10, "end_time": 20, "text": "A first statement."},
        {"video_id": "B", "start_time": 20, "end_time": 30, "text": "B first statement."},
        {"video_id": "A", "start_time": 40, "end_time": 50, "text": "A second statement."},
        {"video_id": "B", "start_time": 60, "end_time": 70, "text": "B second statement."},
    ]
    result = FusionEngine().fuse_transcripts(
        {},
        target_words=200,
        include_sources=False,
        include_transitions=False,
        selected_evidence=selected,
    )
    assert result.metadata["selected_evidence_order"] == [
        ("A", 10, 20),
        ("B", 20, 30),
        ("A", 40, 50),
        ("B", 60, 70),
    ]


def test_fusion_selected_evidence_ignores_source_local_timestamp_reordering():
    selected = [
        {"video_id": "A", "start_time": 300, "end_time": 360, "text": "A late passage."},
        {"video_id": "B", "start_time": 20, "end_time": 40, "text": "B early passage."},
        {"video_id": "A", "start_time": 500, "end_time": 560, "text": "A final passage."},
        {"video_id": "B", "start_time": 200, "end_time": 240, "text": "B middle passage."},
    ]
    result = FusionEngine().fuse_transcripts(
        {},
        target_words=200,
        include_sources=False,
        include_transitions=False,
        selected_evidence=selected,
    )
    assert result.metadata["selected_evidence_order"] == [
        ("A", 300, 360),
        ("B", 20, 40),
        ("A", 500, 560),
        ("B", 200, 240),
    ]


def test_fusion_selected_evidence_is_deterministic():
    selected = [
        {"video_id": "A", "start_time": 10, "end_time": 20, "text": "Alpha."},
        {"video_id": "B", "start_time": 20, "end_time": 30, "text": "Beta."},
    ]
    first = FusionEngine().fuse_transcripts(
        {},
        target_words=200,
        include_sources=False,
        include_transitions=False,
        selected_evidence=selected,
    )
    second = FusionEngine().fuse_transcripts(
        {},
        target_words=200,
        include_sources=False,
        include_transitions=False,
        selected_evidence=selected,
    )
    assert first.metadata["selected_evidence_order"] == second.metadata["selected_evidence_order"]


def test_manifest_and_fusion2_evidence_follow_same_order():
    manifest = [
        {"video_id": "A", "start_time": 10, "end_time": 20, "text": "A first."},
        {"video_id": "B", "start_time": 20, "end_time": 30, "text": "B first."},
        {"video_id": "A", "start_time": 40, "end_time": 50, "text": "A second."},
    ]
    ordered = [
        {"video_id": item["video_id"], "start_time": item["start_time"], "end_time": item["end_time"], "text": item["text"]}
        for item in manifest
    ]
    result = FusionEngine().fuse_transcripts(
        {},
        target_words=200,
        include_sources=False,
        include_transitions=False,
        selected_evidence=ordered,
    )
    manifest_order = [(item["video_id"], item["start_time"], item["end_time"]) for item in manifest]
    fusion_order = result.metadata["selected_evidence_order"]
    assert manifest_order == [(v, s, e) for v, s, e in fusion_order]


def test_fusion_selected_evidence_rejects_mismatched_manifest_order():
    ordered = [
        {"video_id": "A", "start_time": 10, "end_time": 20, "text": "A first."},
        {"video_id": "B", "start_time": 20, "end_time": 30, "text": "B first."},
    ]
    reordered = [
        {"video_id": "B", "start_time": 20, "end_time": 30, "text": "B first."},
        {"video_id": "A", "start_time": 10, "end_time": 20, "text": "A first."},
    ]
    with pytest.raises(ValueError, match="selected evidence order"):
        FusionEngine().fuse_transcripts(
            {},
            target_words=200,
            include_sources=False,
            include_transitions=False,
            selected_evidence=reordered,
            expected_order=ordered,
        )


def test_selected_evidence_narrative_preserves_manifest_order():
    selected = [
        {"video_id": "A", "start_time": 10, "end_time": 20, "text": "A-FIRST"},
        {"video_id": "B", "start_time": 20, "end_time": 30, "text": "B-SECOND"},
        {"video_id": "A", "start_time": 40, "end_time": 50, "text": "A-THIRD"},
        {"video_id": "B", "start_time": 60, "end_time": 70, "text": "B-FOURTH"},
    ]
    result = FusionEngine().fuse_transcripts(
        {},
        target_words=200,
        include_sources=False,
        include_transitions=False,
        selected_evidence=selected,
    )
    markers = ["A-FIRST", "B-SECOND", "A-THIRD", "B-FOURTH"]
    actual = [m for m in markers if m in result.narrative]
    assert result.narrative.index("A-FIRST") < result.narrative.index("B-SECOND")
    assert result.narrative.index("B-SECOND") < result.narrative.index("A-THIRD")
    assert result.narrative.index("A-THIRD") < result.narrative.index("B-FOURTH")
    assert actual == markers


def test_selected_evidence_cluster_trap_keeps_manifest_order():
    selected = [
        {"video_id": "A", "start_time": 10, "end_time": 20, "text": "A-FIRST"},
        {"video_id": "B", "start_time": 20, "end_time": 30, "text": "B-SECOND"},
        {"video_id": "A", "start_time": 40, "end_time": 50, "text": "A-THIRD"},
        {"video_id": "B", "start_time": 60, "end_time": 70, "text": "B-FOURTH"},
    ]
    result = FusionEngine().fuse_transcripts(
        {},
        target_words=200,
        include_sources=False,
        include_transitions=False,
        selected_evidence=selected,
    )
    assert result.narrative.index("B-SECOND") < result.narrative.index("A-THIRD")
    assert result.narrative.index("A-THIRD") < result.narrative.index("B-FOURTH")


def test_selected_evidence_stable_dedup_keeps_earliest_manifest_occurrence(monkeypatch):
    selected = [
        {"video_id": "A", "start_time": 10, "end_time": 20, "text": "A-ORIGINAL"},
        {"video_id": "B", "start_time": 20, "end_time": 30, "text": "B-MIDDLE"},
        {"video_id": "A", "start_time": 25, "end_time": 35, "text": "A-ORIGINAL"},
        {"video_id": "C", "start_time": 40, "end_time": 50, "text": "C-END"},
    ]
    result = FusionEngine().fuse_transcripts(
        {},
        target_words=200,
        include_sources=False,
        include_transitions=False,
        selected_evidence=selected,
    )
    order = [m for m in ["A-ORIGINAL", "B-MIDDLE", "C-END"] if m in result.narrative]
    assert order == ["A-ORIGINAL", "B-MIDDLE", "C-END"]
    assert result.narrative.index("A-ORIGINAL") < result.narrative.index("B-MIDDLE")
    assert result.narrative.index("B-MIDDLE") < result.narrative.index("C-END")


def test_selected_evidence_bart_input_uses_canonical_manifest_order(monkeypatch):
    selected = [
        {"video_id": "A", "start_time": 10, "end_time": 20, "text": "A-FIRST"},
        {"video_id": "B", "start_time": 20, "end_time": 30, "text": "B-SECOND"},
        {"video_id": "A", "start_time": 40, "end_time": 50, "text": "A-THIRD"},
        {"video_id": "B", "start_time": 60, "end_time": 70, "text": "B-FOURTH"},
    ]
    captured = {}

    def fake_summarize_with_policy(self, text, target_words, profile, embedder=None):
        captured["text"] = text
        return text, {"action": "pass", "reason": "captured"}

    monkeypatch.setattr(SummarizationService, "summarize_with_policy", fake_summarize_with_policy)
    result = FusionEngine().fuse_transcripts(
        {},
        target_words=200,
        include_sources=False,
        include_transitions=False,
        selected_evidence=selected,
    )
    service = SummarizationService()
    service.summarize_with_policy(result.narrative, 200, None)
    assert captured["text"].index("A-FIRST") < captured["text"].index("B-SECOND")
    assert captured["text"].index("B-SECOND") < captured["text"].index("A-THIRD")
    assert captured["text"].index("A-THIRD") < captured["text"].index("B-FOURTH")


def test_manifest_is_immutable_and_exact():
    s = segment("A", "Full text.", [1, 0], start=0.123456, duration=30.123456)
    clip = freeze_manifest([s])[0]
    with pytest.raises(FrozenInstanceError):
        clip.start_time = 99
    assert (clip.start_time, clip.end_time, clip.segment_id) == (s.start_time, s.end_time, s.segment_id)
    with pytest.raises(ValueError, match="unavailable"):
        validate_manifest([clip.to_dict()], {})


def test_real_job_overlaps_are_merged_to_zero():
    """Fixture from real job 59017be2-3a69-47d2-9284-e140b065582f."""
    clips = [
        segment("ukzFI9rgwfU", "example ending and that's", [1, 0], 65.280, 53.839),
        segment("ukzFI9rgwfU", "where machine learning comes in", [1, 0], 117.200, 60.080),
        segment("qYNweeDHiyU", "complementary source", [0, 1], 62.359, 21.881),
        segment("PeMlggyqz0Y", "the first step in", [1, 0], 0.120, 41.560),
        segment("PeMlggyqz0Y", "the process", [1, 0], 39.320, 21.879),
        segment("PeMlggyqz0Y", "underlying problem", [1, 0], 59.000, 22.759),
        segment("PeMlggyqz0Y", "weights to features", [1, 0], 79.880, 24.519),
        segment("PeMlggyqz0Y", "predictions", [1, 0], 102.399, 22.441),
        segment("PeMlggyqz0Y", "out there", [1, 0], 123.439, 32.440),
    ]
    for clip in clips:
        clip.concept_scores = {"machine learning": 1.0}
    repaired, stats = repair_physical_boundaries(clips)
    assert stats.overlap_count_before == 6
    assert stats.overlapping_seconds_before == pytest.approx(11.758, abs=0.001)
    assert stats.overlap_count_after == 0
    assert stats.overlapping_seconds_after == 0
    assert stats.adjacent_intervals_merged == 6
    assert [(c.video_id, round(c.start_time, 3), round(c.end_time, 3)) for c in repaired] == [
        ("ukzFI9rgwfU", 65.280, 177.280),
        ("qYNweeDHiyU", 62.359, 84.240),
        ("PeMlggyqz0Y", 0.120, 155.879),
    ]
    validate_manifest([c.to_dict() for c in freeze_manifest(repaired)])


def test_manifest_rejects_adjacent_same_source_overlap():
    clips = [segment("A", "one", [1, 0], 0, 10), segment("A", "two", [0, 1], 9, 10)]
    with pytest.raises(ValueError, match="Overlapping adjacent source intervals"):
        validate_manifest([{"order": i, "video_id": c.video_id,
                            "start_time": c.start_time, "end_time": c.end_time}
                           for i, c in enumerate(clips)])


def test_boundary_expansion_clamps_same_source_neighbors_before_manifest_freeze():
    left = segment("A", "We use", [1, 0], start=0, duration=4)
    right = segment("A", "context window", [0, 1], start=20, duration=6)
    raw = {"A": [
        {"text": "We use", "start": 0, "duration": 4},
        {"text": "tokens and context window", "start": 4, "duration": 12},
        {"text": "to encode the sentence", "start": 16, "duration": 8},
        {"text": "context window", "start": 20, "duration": 6},
        {"text": "governs the model limits", "start": 26, "duration": 8},
    ]}

    repaired, _ = repair_explanation_boundaries([left, right], raw, [])
    assert repaired[0].end_time <= repaired[1].start_time
    assert repaired[0].video_id == repaired[1].video_id == "A"
    validate_manifest([c.to_dict() for c in freeze_manifest(repaired)])


@pytest.mark.parametrize("fragment", [
    "and that's", "the first step in", "features that better represent the",
    "every one of these algorithms learns to get better by comparing its",
])
def test_real_dangling_endings_are_incomplete(fragment):
    assert explanation_completeness("A valid opening " + fragment) < 1.0


def test_selected_fragment_expands_to_smallest_bounded_caption_completion():
    selected = segment("A", "The first step in", [1, 0], 0, 4)
    raw = {"A": [
        {"text": "The first step in", "start": 0, "duration": 4},
        {"text": "the process is collecting data", "start": 3, "duration": 4},
        {"text": "before training begins.", "start": 6, "duration": 3},
        {"text": "A different topic starts", "start": 20, "duration": 4},
    ]}
    repaired, expansions = repair_explanation_boundaries([selected], raw)
    repaired = rebuild_final_texts(repaired, raw)
    assert expansions == 1
    assert repaired[0].end_time == 9
    assert repaired[0].text.endswith("before training begins.")
    assert repaired[0].completeness == 1.0


def test_boundary_expansion_is_bounded():
    selected = segment("A", "We finish by comparing its", [1, 0], 0, 4)
    raw = {"A": [{"text": "continuation without completion", "start": i, "duration": 1}
                 for i in range(4, 40)]}
    repaired, _ = repair_explanation_boundaries([selected], raw)
    assert repaired[0].end_time <= 64


@pytest.mark.parametrize("ending", [
    "many supporting Frameworks out there to make the process",
    "this technology machine learning is particularly useful for us and machine",
    "hence the learning with unlabeled data is",
])
def test_real_unpunctuated_endings_require_positive_contextual_closure(ending):
    selected = segment("A", ending, [1, 0], 0, 4)
    raw = [
        {"text": ending, "start": 0, "duration": 4},
        {"text": "the explanation continues here", "start": 4, "duration": 4},
    ]
    decision = assess_end_boundary(selected, raw, [selected])
    assert decision.is_complete is False
    assert decision.needs_expansion is True
    assert decision.reasons


def test_unpunctuated_caption_can_close_on_positive_pause_evidence():
    selected = segment("A", "the model now produces a prediction", [1, 0], 0, 4)
    raw = [
        {"text": selected.text, "start": 0, "duration": 4},
        {"text": "a new topic begins", "start": 6, "duration": 3},
    ]
    decision = assess_end_boundary(selected, raw, [selected])
    assert decision.is_complete is True
    assert "meaningful_pause" in decision.reasons


def test_soft_safe_end_without_punctuation_but_with_semantic_transition():
    selected = segment("A", "the model was trained on labeled data", [1, 0], 0, 4)
    next_seg = segment("A", "now we evaluate on validation metrics", [0, 1], 4, 3)
    raw = [
        {"text": selected.text, "start": 0, "duration": 4},
        {"text": next_seg.text, "start": 4, "duration": 3},
    ]
    decision = assess_end_boundary(selected, raw, [selected, next_seg])
    assert decision.is_complete is True
    assert decision.classification in {"SOFT_SAFE", "SAFE"}


def test_soft_safe_start_without_punctuation_for_new_explanation_stage():
    prev = segment("A", "the data is prepared for training", [1, 0], 0, 4)
    selected = segment("A", "now we evaluate the model", [1, 0], 4, 3)
    raw = [
        {"text": prev.text, "start": 0, "duration": 4},
        {"text": selected.text, "start": 4, "duration": 3},
    ]
    decision = assess_start_boundary(selected, raw, [prev, selected])
    assert decision.is_complete is True
    assert decision.classification in {"SOFT_SAFE", "SAFE"}


def test_rejects_phrase_completion_that_is_not_a_boundary():
    selected = segment("A", "the first step in", [1, 0], 0, 4)
    raw = [
        {"text": selected.text, "start": 0, "duration": 4},
        {"text": "the process is to collect and clean the data", "start": 4, "duration": 4},
    ]
    decision = assess_end_boundary(selected, raw, [selected])
    assert decision.is_complete is False
    assert decision.classification == "UNSAFE"


def test_rejects_mid_thought_start():
    prev = segment("A", "the data is cleaned and split into", [1, 0], 0, 4)
    selected = segment("A", "training and testing sets", [1, 0], 4, 3)
    raw = [
        {"text": prev.text, "start": 0, "duration": 4},
        {"text": selected.text, "start": 4, "duration": 3},
    ]
    decision = assess_start_boundary(selected, raw, [prev, selected])
    assert decision.is_complete is False
    assert decision.classification == "UNSAFE"


def test_ignores_cta_after_valid_content():
    selected = segment("A", "the model learns from data and improves over time", [1, 0], 0, 4)
    raw = [
        {"text": selected.text, "start": 0, "duration": 4},
        {"text": "like and subscribe to the channel", "start": 4, "duration": 3},
        {"text": "thanks for watching", "start": 7, "duration": 2},
    ]
    decision = assess_end_boundary(selected, raw, [selected])
    assert decision.is_complete is True
    assert decision.classification in {"SOFT_SAFE", "SAFE"}


def test_accepts_new_stage_even_without_pause_when_semantic_shift_is_strong():
    selected = segment("A", "the model makes predictions", [1, 0], 0, 4)
    next_seg = segment("A", "now we evaluate the model against a validation set", [0, 1], 4, 3)
    raw = [
        {"text": selected.text, "start": 0, "duration": 4},
        {"text": next_seg.text, "start": 4, "duration": 3},
    ]
    decision = assess_end_boundary(selected, raw, [selected, next_seg])
    assert decision.is_complete is True
    assert decision.classification in {"SOFT_SAFE", "SAFE"}


def test_rejects_next_caption_that_directly_completes_current_phrase():
    selected = segment("A", "the model uses", [1, 0], 0, 4)
    raw = [
        {"text": selected.text, "start": 0, "duration": 4},
        {"text": "a loss function to compare predictions", "start": 4, "duration": 3},
    ]
    decision = assess_end_boundary(selected, raw, [selected])
    assert decision.is_complete is False
    assert decision.classification == "UNSAFE"


def test_unresolved_boundary_is_not_falsely_promoted_to_complete():
    selected = segment("A", "hence the learning with unlabeled data is", [1, 0], 0, 4)
    raw = {"A": [
        {"text": selected.text, "start": 0, "duration": 4},
        *[{"text": "continuation without closure", "start": i, "duration": 1}
          for i in range(4, 30)],
    ]}
    repaired, _ = repair_explanation_boundaries([selected], raw)
    rebuilt = rebuild_final_texts(repaired, raw)
    assert rebuilt[0].completeness == 0.0
    assert rebuilt[0].boundary_evidence["needs_expansion"] is True


def test_nearest_safe_boundary_stops_before_outro():
    selected = segment("A", "The model returns a prediction", [1, 0], 0, 4)
    raw = {"A": [
        {"text": "The model returns a prediction.", "start": 0, "duration": 4},
        {"text": "Like and subscribe to the channel", "start": 4, "duration": 4},
        {"text": "Thanks for watching", "start": 8, "duration": 3},
    ]}
    repaired, _ = repair_explanation_boundaries([selected], raw)
    assert repaired[0].end_time == 4
    assert repaired[0].completeness == 1.0
    assert not non_content_hits(repaired[0].text)


def test_mid_proposition_start_searches_backward_for_safe_boundary():
    core = segment("A", "to hear it in their voice", [1, 0], 4, 4)
    prior = segment("A", "You are able to hear it in their voice", [1, 0], 0, 8)
    raw = {"A": [
        {"text": "You are able", "start": 0, "duration": 4},
        {"text": "to hear it in their voice.", "start": 4, "duration": 4},
        {"text": "Next topic begins", "start": 10, "duration": 3},
    ]}
    repaired, _ = repair_explanation_boundaries([core], raw, [prior])
    assert repaired[0].start_time == 0
    assert repaired[0].start_boundary_evidence["is_complete"] is True
    assert repaired[0].text.startswith("You are able")


def test_reconciliation_rejects_non_content_fill_candidate():
    selected = [segment("A", "Educational explanation.", [1, 0], 0, 70)]
    outro = segment("B", "Like and subscribe to the channel.", [0, 1], 0, 25)
    raw = {
        "A": [{"text": selected[0].text, "start": 0, "duration": 70}],
        "B": [{"text": outro.text, "start": 0, "duration": 25}],
    }
    reconciled, stats = reconcile_physical_duration(
        selected, selected + [outro], raw, selected + [outro], 100, min_fill=.9
    )
    assert reconciled == selected
    assert stats["non_content_candidates_rejected"] == 1


def test_real_rolling_caption_fixture_normalizes_to_valid_transition():
    raw = [
        {"text": "and there are many supporting Frameworks", "start": 121.920, "duration": 2.920},
        {"text": "out there to make the process", "start": 123.439, "duration": 2.921},
        {"text": "approachable the end result of the", "start": 124.840, "duration": 3.559},
    ]
    units, stats = normalize_caption_timeline(raw, "PeMlggyqz0Y")
    assert [(u.effective_start, u.effective_end) for u in units] == pytest.approx([
        (121.920, 123.439), (123.439, 124.840), (124.840, 128.399),
    ])
    assert stats.raw_temporal_overlap_count == 2
    assert stats.normalized_overlap_count == 0
    probe = segment("PeMlggyqz0Y", "out there to make the process", [1, 0],
                    123.439, 1.401)
    decision = assess_end_boundary(probe, raw)
    assert "boundary_inside_normalized_speech_unit" not in decision.reasons


def test_normalization_removes_rolling_text_and_preserves_provenance():
    raw = [
        {"text": "we train the model", "start": 0, "duration": 4},
        {"text": "the model using data", "start": 2, "duration": 4},
    ]
    units, stats = normalize_caption_timeline(raw, "A")
    assert [u.text for u in units] == ["we train the model", "using data"]
    assert units[1].raw_caption_ids == (1,)
    assert units[1].textual_overlap_removed is True
    assert stats.textual_rolling_overlaps_resolved == 1


def test_normalization_prefers_rolling_correction():
    raw = [
        {"text": "the model make prediction", "start": 0, "duration": 4},
        {"text": "model makes predictions today", "start": 2, "duration": 4},
    ]
    units, stats = normalize_caption_timeline(raw, "A")
    combined = " ".join(unit.text for unit in units)
    assert combined == "the model makes predictions today"
    assert stats.textual_corrections_resolved == 1
    assert {raw_id for unit in units for raw_id in unit.raw_caption_ids} == {0, 1}


def test_normalization_preserves_real_pause_and_source_order():
    raw = [
        {"text": "first thought", "start": 0, "duration": 2},
        {"text": "second thought", "start": 4, "duration": 2},
    ]
    units, stats = normalize_caption_timeline(raw, "A")
    assert [(u.effective_start, u.effective_end) for u in units] == [(0, 2), (4, 6)]
    assert stats.preserved_genuine_pause_count == 1
    assert stats.normalized_overlap_count == 0


def test_normalized_core_still_stops_before_cta():
    core = segment("A", "Useful lesson.", [1, 0], 0, 3)
    raw = {"A": [
        {"text": "Useful lesson.", "start": 0, "duration": 3},
        {"text": "Like and subscribe to the channel", "start": 2, "duration": 4},
    ]}
    repaired, _ = repair_explanation_boundaries([core], raw)
    assert repaired[0].end_time == 2
    assert not non_content_hits(repaired[0].text)


def test_physical_budget_reconciliation_adds_and_removes_whole_explanations():
    selected = [segment("A", "Primary explanation.", [1, 0], 0, 70)]
    extra = segment("B", "Complementary example.", [0, 1], 0, 25)
    raw = {
        "A": [{"text": selected[0].text, "start": 0, "duration": 70}],
        "B": [{"text": extra.text, "start": 0, "duration": 25}],
    }
    reconciled, stats = reconcile_physical_duration(
        selected, selected + [extra], raw, selected + [extra], 100, min_fill=.9
    )
    assert sum(item.duration for item in reconciled) == 95
    assert stats["candidates_added_during_underfill_reconciliation"] == 1
    over = [segment("A", "High value.", [1, 0], 0, 70),
            segment("B", "Low value.", [0, 1], 0, 50)]
    over[0].concept_scores = {"topic": 1.0}
    trimmed, stats = reconcile_physical_duration(over, over, raw, over, 100)
    assert [(item.video_id, item.duration) for item in trimmed] == [("A", 70)]
    assert stats["budget_blocks_removed"] == 1


def test_caption_stitch_removes_exact_and_partial_overlap_only_when_time_overlaps():
    assert stitch_caption_entries([
        (0, 4, "creates additional features"),
        (2, 6, "additional features automatically"),
    ]) == "creates additional features automatically"
    assert stitch_caption_entries([
        (0, 4, "we use training data"),
        (3, 7, "data to fit the model"),
    ]) == "we use training data to fit the model"
    assert stitch_caption_entries([(0, 2, "first thought"), (2, 4, "next thought")]) == \
        "first thought next thought"
    # Non-overlapping timestamps mean the speaker may genuinely be repeating.
    assert stitch_caption_entries([(0, 2, "very very"), (2.1, 4, "very important")]) == \
        "very very very important"


def test_final_text_is_rebuilt_once_with_exclusive_caption_ownership():
    clips = [segment("A", "stale duplicate text", [1, 0], 0, 6)]
    raw = {"A": [
        {"text": "creates additional features", "start": 0, "duration": 4},
        {"text": "additional features automatically.", "start": 2, "duration": 4},
    ]}
    rebuilt = rebuild_final_texts(clips, raw)
    assert rebuilt[0].text == "creates additional features automatically."
    assert rebuilt[0].completeness == 1.0


def test_rendered_duration_probe_reports_local_media(monkeypatch):
    class Result:
        returncode = 0
        stdout = "233.321333\n"
    monkeypatch.setattr("backend.services.manifest_boundary_repair.shutil.which", lambda _: "/ffprobe")
    monkeypatch.setattr("backend.services.manifest_boundary_repair.subprocess.run", lambda *a, **k: Result())
    assert probe_rendered_duration("result.mp4") == pytest.approx(233.321333)


def test_concept_block_rejects_cross_source_paraphrase_and_keeps_new_example():
    primary = segment("A", "Overfitting means memorising training data.", [1, 0], 0, 30)
    paraphrase = segment("B", "Overfitting memorises the training data.", [1, 0], 0, 30)
    example = segment("C", "For example a model fails on unseen patients.", [0.7, 0.7], 0, 30)
    for item in (primary, paraphrase, example):
        item.canonical_concepts = ["overfitting"]
        item.information_density = 0.8
        item.knowledge_unit_scores = {"overfitting::definition": 0.9}
    example.knowledge_unit_scores = {"overfitting::example": 0.9}
    ordered, stats = organize_concept_blocks([primary, paraphrase, example],
                                              [primary, paraphrase, example], [])
    assert {item.video_id for item in ordered} == {"A", "C"}
    assert stats.duplicate_concept_rejections == 1
    assert stats.complementary_cross_source_additions == 1
    assert {item.video_id: getattr(item, "concept_block_role", None) for item in ordered} == {"A": "PRIMARY", "C": "COMPLEMENTARY"}


def test_concept_block_order_keeps_related_units_together():
    def mk(video_id, concept, text, start):
        item = segment(video_id, text, [1, 0], start=start, duration=20)
        item.canonical_concepts = [concept]
        item.knowledge_unit_scores = {f"{concept}::definition": 0.9}
        return item

    a = mk("A", "overfitting", "Overfitting means memorising training data.", 0)
    b = mk("A", "overfitting", "The model fits noise instead of signal.", 25)
    c = mk("B", "overfitting", "A common example is a tiny dataset.", 0)
    ordered, _ = organize_concept_blocks([a, b, c], [a, b, c], [])
    assert ordered[:2] == [a, b]
    assert getattr(c, "concept_block_role", None) == "COMPLEMENTARY"


def test_project_semantic_boundaries_use_provenance_despite_timestamp_shift():
    raw = {
        "A": [
            {"text": "first topic idea", "start": 0.0, "duration": 2.0},
            {"text": "continuation remains", "start": 1.5, "duration": 2.0},
            {"text": "second topic begins", "start": 5.0, "duration": 2.0},
        ]
    }
    left = segment("A", "first topic idea", [1, 0], 0.0, 2.0)
    right = segment("A", "second topic begins", [0, 1], 6.5, 2.0)
    projected = project_semantic_boundaries(raw, [left, right])
    assert len(projected) == 1
    assert projected[0].mapping_method == "provenance"
    assert projected[0].right_raw_caption_ids == (2,)
    assert projected[0].projected_normalized_timestamp <= 5.0
    assert projected[0].projection_distance <= 5.0


def test_project_semantic_boundaries_map_overlap_window_to_normalized_transition():
    raw = {
        "A": [
            {"text": "the key idea", "start": 0.0, "duration": 2.0},
            {"text": "idea continues here", "start": 1.8, "duration": 2.2},
            {"text": "next idea starts", "start": 4.0, "duration": 2.0},
        ]
    }
    left = segment("A", "the key idea", [1, 0], 0.0, 2.8)
    right = segment("A", "next idea starts", [0, 1], 4.0, 2.0)
    projected = project_semantic_boundaries(raw, [left, right])
    assert projected[0].mapping_method == "provenance"
    assert projected[0].right_raw_caption_ids == (2,)
    assert projected[0].projection_distance <= 3.0


def test_project_semantic_boundaries_falls_back_to_nearest_safe_transition():
    raw = {
        "A": [
            {"text": "feature one", "start": 0.0, "duration": 2.0},
            {"text": "feature two", "start": 1.5, "duration": 2.0},
            {"text": "feature three", "start": 3.6, "duration": 2.0},
        ]
    }
    left = segment("A", "feature one", [1, 0], 0.0, 2.0)
    right = segment("A", "feature three", [0, 1], 5.0, 2.0)
    projected = project_semantic_boundaries(raw, [left, right], max_distance=3.0)
    assert projected[0].mapping_method in {"provenance", "bounded_timestamp_fallback"}
    assert projected[0].projected_normalized_timestamp >= 2.0
    assert projected[0].projection_distance <= 3.0


def test_project_semantic_boundaries_unmap_when_no_safe_transition_exists():
    raw = {
        "A": [
            {"text": "core point", "start": 0.0, "duration": 2.0},
            {"text": "next sentence", "start": 2.0, "duration": 2.0},
        ]
    }
    left = segment("A", "core point", [1, 0], 80.0, 2.0)
    right = segment("A", "next sentence", [0, 1], 82.0, 2.0)
    projected = project_semantic_boundaries(raw, [left, right], max_distance=0.25)
    assert projected == []


def test_project_semantic_boundaries_reject_cta_before_fallback():
    raw = {
        "A": [
            {"text": "the lesson ends here", "start": 0.0, "duration": 2.0},
            {"text": "like and subscribe to the channel", "start": 2.0, "duration": 2.0},
            {"text": "thanks for watching", "start": 4.0, "duration": 2.0},
        ]
    }
    left = segment("A", "the lesson ends here", [1, 0], 0.0, 2.0)
    right = segment("A", "thanks for watching", [0, 1], 6.0, 2.0)
    projected = project_semantic_boundaries(raw, [left, right], max_distance=3.0)
    assert projected == []


def test_project_semantic_boundaries_keep_multiple_raw_units_with_shared_provenance():
    raw = {
        "A": [
            {"text": "first block", "start": 0.0, "duration": 2.0},
            {"text": "continuation", "start": 1.8, "duration": 2.0},
            {"text": "new block", "start": 4.0, "duration": 2.0},
        ]
    }
    left = segment("A", "first block", [1, 0], 0.0, 2.0)
    right = segment("A", "new block", [0, 1], 4.0, 2.0)
    projected = project_semantic_boundaries(raw, [left, right])
    assert projected[0].left_raw_caption_ids[0] in {0, 1}
    assert projected[0].right_raw_caption_ids == (2,)


def test_project_semantic_boundaries_can_resolve_start_and_end_with_normalized_units():
    raw = {"A": [
        {"text": "intro before the topic", "start": 0.0, "duration": 3.0},
        {"text": "main point explanation", "start": 3.0, "duration": 3.0},
        {"text": "wrap up conclusion", "start": 6.0, "duration": 3.0},
    ]}
    core = segment("A", "main point explanation", [1, 0], 3.0, 3.0)
    repaired, _ = repair_explanation_boundaries([core], raw, [core])
    assert repaired[0].start_time == pytest.approx(0.0)
    assert repaired[0].end_time == pytest.approx(6.0)


def test_concepts_are_contiguous_and_source_chronology_is_preserved():
    definition_a = segment("A", "Definition one", [1, 0], 0, 20)
    definition_b = segment("A", "Definition two", [1, 0], 30, 20)
    example = segment("B", "Example", [0, 1], 100, 20)
    for item in (definition_a, definition_b):
        item.canonical_concepts = ["definition"]
    example.canonical_concepts = ["example"]
    ordered, stats = organize_concept_blocks(
        [example, definition_b, definition_a], [definition_a, definition_b, example], []
    )
    assert ordered == [definition_a, definition_b, example]
    assert stats.concept_block_count == 2


@pytest.mark.asyncio
async def test_renderer_receives_manifest_order_and_intervals(monkeypatch, tmp_path):
    svc = VideoService()
    svc.output_dir = tmp_path
    candidates = [segment("B", "First.", [1, 0], start=100),
                  segment("A", "Second.", [0, 1], start=20)]
    manifest = [c.to_dict() for c in freeze_manifest(candidates)]
    original = copy.deepcopy(manifest)
    seen = []

    async def trim(clip, paths, work, idx):
        seen.append((idx, clip["video_id"], clip["start_time"], clip["end_time"]))
        return str(idx)

    async def concat(clips, job, work):
        assert clips == ["0", "1"]
        return "rendered.mp4"

    monkeypatch.setattr(svc, "_trim_and_normalize_segment", trim)
    monkeypatch.setattr(svc, "_concat_with_transitions", concat)
    monkeypatch.setattr("backend.services.video_service.shutil.copy2", lambda *a: None)
    await svc.generate_highlight_reel("manifest-test", manifest, {"A": "a.mp4", "B": "b.mp4"})
    assert seen == [(0, "B", 100, 130), (1, "A", 20, 50)]
    assert manifest == original


@pytest.mark.asyncio
async def test_renderer_refuses_partial_manifest(monkeypatch):
    svc = VideoService()
    monkeypatch.setattr(svc, "_trim_segments_bounded", AsyncMock(return_value=["one.mp4"]))
    clips = [c.to_dict() for c in freeze_manifest([
        segment("A", "One.", [1, 0]), segment("B", "Two.", [0, 1])])]
    with pytest.raises(RuntimeError, match="all be trimmed"):
        await svc.generate_highlight_reel("failed-manifest", clips, {"A": "a", "B": "b"})


def test_concept_cache_full_content_exact_intervals_and_settings():
    a = Chunk("x" * 401 + "alpha", 1.001, 30, 0, video_id="A")
    key = _cache_key([a], False, 25, model="base")
    for attr, value in [("text", "x" * 401 + "beta"), ("start", 1.002), ("end", 31), ("video_id", "B")]:
        b = copy.copy(a)
        setattr(b, attr, value)
        assert key != _cache_key([b], False, 25, model="base")
    assert key != _cache_key([a], False, 25, model="other")


def test_segment_cache_hashes_unsampled_entries_and_end():
    entries = [{"text": "x" * 121 + str(i), "start": i, "duration": 1} for i in range(100)]
    key = _segment_cache_key(entries, "A", 20, 90)
    entries[1]["text"] += " changed"
    assert key != _segment_cache_key(entries, "A", 20, 90)
    key = _segment_cache_key(entries, "A", 20, 90)
    entries[1]["duration"] = 1.001
    assert key != _segment_cache_key(entries, "A", 20, 90)


def test_all_occurrence_evidence_survives_serialization():
    occurrences = [ConceptOccurrence(str(i), 0.12345, 12.34567) for i in range(12)]
    result = Concept("topic", occurrences=occurrences).to_dict()
    assert len(result["occurrences"]) == 12
    assert result["occurrences"][-1] == {"video_id": "11", "start": 0.12345, "end": 12.34567}


@pytest.mark.asyncio
async def test_global_pipeline_keyword_manifest_and_timings(monkeypatch, embedder):
    from backend.api.merge import run_semantic_selection
    from backend.models.job import MergeJob
    texts = {"A": "Cooking vegetables with oil.", "B": "Overfitting model training explanation.",
             "C": "Overfitting model training explanation."}
    candidates = {vid: SemanticSegment(vid, 1.123456, 31.123456, text,
                                       embedding=embedder.encode([text])[0],
                                       boundary_confidence=1.0) for vid, text in texts.items()}
    monkeypatch.setattr("backend.services.fusion_engine.get_sentence_transformer", lambda: embedder)
    monkeypatch.setattr("backend.services.semantic_segmenter.build_semantic_segments",
                        lambda segs, vid, *args: [candidates[vid]])
    monkeypatch.setattr("backend.services.concept_extractor.extract_concepts", AsyncMock(return_value=[]))
    job = MergeJob(video_ids=list(texts), target_duration_minutes=5,
                   highlight_duration_seconds=30, selected_keywords=["overfitting model training"])
    raw = {vid: [{"text": text, "start": 1.123456, "duration": 30}] for vid, text in texts.items()}
    result = await run_semantic_selection(job, raw, "")
    assert len(result["highlights"]) == 1
    clip = result["highlights"][0]
    assert clip["video_id"] in {"B", "C"}
    assert clip["start_time"] == 1.123456
    assert clip["keyword_matches"] == job.selected_keywords
    assert clip["order"] == 0
    assert result["metrics"]["candidate_count"] == 3
    assert result["metrics"]["selection_mode"] == "keyword"
    assert all(result["metrics"]["stage_timings_seconds"][name] >= 0 for name in
               ["segmentation", "concept_extraction", "embedding", "selection", "ordering"])


def test_unrelated_keyword_is_not_reported_as_coverage():
    """Moderate BGE-like cosine must not become a user-facing evidence claim."""
    from backend.api.merge import _keyword_evidence_matches

    assert _keyword_evidence_matches(
        ["quantum chromodynamics"], [0.55], "Machine learning model training."
    ) == []
    assert _keyword_evidence_matches(
        ["machine learning"], [0.55], "A MACHINE LEARNING explanation."
    ) == ["machine learning"]
    assert _keyword_evidence_matches(
        ["neural networks"], [0.78], "Representation learning explanation."
    ) == ["neural networks"]


def test_incremental_redundancy_matches_cosine_of_selected_set(embedder):
    candidates = [segment(str(i % 3), str(i), [1, i + 1, i * i + 1], start=i * 40)
                  for i in range(5)]
    result = select_segments(candidates, 90, embedder=embedder)
    chosen = []
    for pick in result.trace:
        current = next(s for s in candidates if s.video_id == pick["video_id"] and s.start_time == pick["start_time"])
        vector = current.embedding / np.linalg.norm(current.embedding)
        expected = max([0.0] + [float(vector @ (s.embedding / np.linalg.norm(s.embedding))) for s in chosen])
        assert pick["redundancy"] == pytest.approx(expected, abs=1e-4)
        chosen.append(current)
