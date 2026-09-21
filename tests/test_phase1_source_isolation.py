import pytest
import numpy as np
from backend.services.concept_extractor import (
    build_chunks,
    extract_concepts_tfidf,
    Concept,
    ConceptOccurrence,
    Chunk,
)
from backend.services.semantic_segmenter import SemanticSegment
from backend.services.coverage_selector import (
    build_candidate_units,
    build_concept_affinity,
    select_segments,
)
from backend.models.job import ConceptInfo


def test_chunking_never_spans_multiple_videos():
    """Invariant 1 & 2: A chunk must never contain segments from more than one video_id, and start <= end."""
    # Video A: 250s to 310s (ends around 310s)
    # Video B: 0s to 60s (starts at 0s)
    segments = [
        SemanticSegment("vidA", 250.0, 280.0, "video A segment one discussion on topic alpha"),
        SemanticSegment("vidA", 280.0, 310.0, "video A segment two discussion concluding alpha"),
        SemanticSegment("vidB", 0.0, 30.0, "video B segment one fresh introduction to beta"),
        SemanticSegment("vidB", 30.0, 60.0, "video B segment two continuing discussion of beta"),
    ]

    chunks = build_chunks(segments, chunk_words=100)
    assert len(chunks) >= 2, "Must produce at least one chunk per video"

    for chunk in chunks:
        # Check start <= end
        assert chunk.start <= chunk.end, f"Chunk has inverted timestamps: start={chunk.start} > end={chunk.end}"
        # Check that text does not combine alpha and beta
        if "alpha" in chunk.text:
            assert "beta" not in chunk.text, "Chunk crossed boundary: contained both alpha (vidA) and beta (vidB)"
            assert chunk.video_id == "vidA"
        if "beta" in chunk.text:
            assert "alpha" not in chunk.text, "Chunk crossed boundary: contained both beta (vidB) and alpha (vidA)"
            assert chunk.video_id == "vidB"


def test_concept_occurrences_retain_source_identity():
    """Invariant 3: Extracted concept occurrences retain source video identity."""
    chunks = [
        Chunk("overfitting regularisation dropout in neural models", 30.0, 50.0, 0, video_id="vidA"),
        Chunk("unrelated database indexing btree queries", 30.0, 50.0, 1, video_id="vidB"),
    ]

    concepts = extract_concepts_tfidf(chunks, max_concepts=10)
    overfit_concepts = [c for c in concepts if "overfitting" in c.name.lower()]
    assert len(overfit_concepts) >= 1

    c = overfit_concepts[0]
    assert hasattr(c, "occurrences")
    assert len(c.occurrences) > 0
    # The occurrence must point specifically to vidA
    assert c.occurrences[0].video_id == "vidA"
    assert c.occurrences[0].start == 30.0
    assert c.occurrences[0].end == 50.0
    # Backwards compatibility check
    assert len(c.timestamps) > 0
    assert c.timestamps[0] == (30.0, 50.0)


def test_zero_temporal_grounding_across_unrelated_videos_with_identical_timestamps():
    """Invariant 6: Video B at 30-50s MUST receive ZERO temporal grounding from Video A's concept at 30-50s."""
    seg_a = SemanticSegment("vidA", 30.0, 50.0, "we discuss overfitting in depth here")
    seg_b = SemanticSegment("vidB", 30.0, 50.0, "completely unrelated material about cooking recipes")
    segments = [seg_a, seg_b]

    # Concept belongs strictly to vidA
    concept = Concept(
        name="Overfitting",
        importance=1.0,
        occurrences=[ConceptOccurrence("vidA", 30.0, 50.0)],
        timestamps=[(30.0, 50.0)],
        reason="Overfitting discussion",
    )

    affinity = build_concept_affinity(segments, [concept], segment_vectors=None)
    # affinity has shape (n_segments, n_concepts) = (2, 1)
    affinity_a = affinity[0, 0]
    affinity_b = affinity[1, 0]

    assert affinity_a > 0.0, "Video A segment inside the window must receive temporal grounding"
    assert affinity_b == 0.0, f"Video B segment must receive ZERO grounding from Video A concept, got {affinity_b}"


def test_candidate_units_never_span_multiple_videos():
    """Invariant 4 & 5: CandidateUnit belongs to exactly one video and never merges across videos."""
    # Two videos with contiguous segments
    segments = [
        SemanticSegment("vidA", 10.0, 25.0, "intro to neural nets part one"),
        SemanticSegment("vidA", 25.0, 45.0, "intro to neural nets part two"),
        SemanticSegment("vidB", 10.0, 25.0, "intro to neural nets in another course part one"),
        SemanticSegment("vidB", 25.0, 45.0, "intro to neural nets in another course part two"),
    ]

    concept = Concept(
        name="neural nets",
        importance=1.0,
        occurrences=[ConceptOccurrence("vidA", 10.0, 45.0)],
        timestamps=[(10.0, 45.0)],
        reason="Neural nets introduction",
    )

    units = build_candidate_units(segments, [concept], min_importance=0.1, min_seconds=5.0)
    assert len(units) > 0, "Should generate candidate units for vidA"

    for u in units:
        assert hasattr(u, "video_id"), "CandidateUnit must have video_id attribute"
        assert u.video_id == "vidA", f"Expected vidA, got {u.video_id}"
        # All members must belong to vidA
        member_vids = {segments[i].video_id for i in u.indices}
        assert member_vids == {"vidA"}, f"Candidate unit crossed video boundaries! members: {member_vids}"


def test_single_video_backward_compatibility():
    """Invariant 7: Single-video behavior with legacy 2-tuple timestamps functions identically."""
    segments = [
        SemanticSegment("vid1", 0.0, 30.0, "introductory words"),
        SemanticSegment("vid1", 30.0, 60.0, "main explanation of topic"),
        SemanticSegment("vid1", 60.0, 90.0, "concluding remarks"),
    ]

    # Legacy concept without occurrences, only 2-tuple timestamps
    concept = Concept(
        name="Topic",
        importance=0.9,
        timestamps=[(30.0, 60.0)],
        reason="Main topic",
    )

    affinity = build_concept_affinity(segments, [concept], segment_vectors=None)
    assert affinity[1, 0] > 0.0, "Middle segment must get grounded"
    assert affinity[0, 0] == 0.0, "First segment outside window must be 0"
    assert affinity[2, 0] == 0.0, "Third segment outside window must be 0"

    units = build_candidate_units(segments, [concept], min_importance=0.1, min_seconds=5.0)
    assert len(units) > 0
    assert all(u.video_id == "vid1" for u in units)


def test_unqualified_legacy_timestamp_is_ignored_in_multi_video_pool():
    """An ambiguous clock position must never be applied to every source."""
    segments = [
        SemanticSegment("vidA", 30.0, 50.0, "alpha explanation"),
        SemanticSegment("vidB", 30.0, 50.0, "beta explanation"),
    ]
    concept = Concept(
        name="Legacy concept",
        importance=1.0,
        timestamps=[(30.0, 50.0)],
    )

    affinity = build_concept_affinity(segments, [concept], segment_vectors=None)
    assert np.all(affinity == 0.0)
    assert build_candidate_units(
        segments, [concept], min_importance=0.1, min_seconds=5.0
    ) == []


def test_invalid_intervals_never_become_chunks_or_occurrences():
    chunks = build_chunks([
        {"video_id": "vidA", "text": "invalid", "start": 50.0, "duration": -20.0},
        {"video_id": "vidA", "text": "valid", "start": 60.0, "duration": 10.0},
    ])
    assert len(chunks) == 1
    assert chunks[0].start == 60.0
    assert chunks[0].end == 70.0

    occurrence = ConceptOccurrence("vidA", 50.0, 20.0)
    assert occurrence.start <= occurrence.end


def test_source_occurrences_survive_job_schema_serialization():
    concept = Concept(
        name="Grounded concept",
        importance=0.9,
        occurrences=[ConceptOccurrence("vidA", 12.0, 34.0)],
    )
    persisted = ConceptInfo.model_validate(concept.to_dict()).model_dump()
    assert persisted["occurrences"] == [
        {"video_id": "vidA", "start": 12.0, "end": 34.0}
    ]
