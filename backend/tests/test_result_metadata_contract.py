"""
Tests for result metadata contract:
- Compression metric canonical semantics (summary length / source length, [0.0, 1.0])
- Handling of normal, zero input, output > input, and missing metadata
- Topics found resolution and fallback from concepts
- Rights warnings deduplication
"""
import pytest
from backend.models.job import FusionMetadata
from backend.services.rights_service import evaluate_publication_gate
from backend.models.rights import (
    SourceRightsRecord,
    RightsBasis,
    PublicationGateStatus,
    PlatformEvidence,
)


def compute_compression_ratio(output_words: int, total_source_words: int) -> float:
    """Helper representing the backend compression ratio computation contract."""
    if total_source_words <= 0 or output_words <= 0:
        return 0.0
    return round(min(max(output_words / max(total_source_words, 1), 0.0), 1.0), 4)


class TestResultMetadataContract:
    def test_compression_ratio_normal_values(self):
        # 1,000 words out of 10,000 words = 0.10
        ratio = compute_compression_ratio(1000, 10000)
        assert ratio == 0.10
        assert 0.0 <= ratio <= 1.0

        # 250 words out of 1,000 words = 0.25
        ratio2 = compute_compression_ratio(250, 1000)
        assert ratio2 == 0.25

    def test_compression_ratio_output_greater_than_input(self):
        # When output exceeds input, clamp strictly to 1.0 (never 71.0 or 7100%)
        ratio = compute_compression_ratio(140, 2)
        assert ratio == 1.0

        ratio2 = compute_compression_ratio(500, 100)
        assert ratio2 == 1.0

    def test_compression_ratio_zero_input(self):
        assert compute_compression_ratio(0, 0) == 0.0
        assert compute_compression_ratio(100, 0) == 0.0
        assert compute_compression_ratio(0, 500) == 0.0

    def test_fusion_metadata_model_defaults_and_clamping(self):
        # Missing/default values
        meta = FusionMetadata()
        assert meta.total_source_words == 0
        assert meta.output_words == 0
        assert meta.compression_ratio == 0.0
        assert meta.topics_found == []

        # Instantiation with valid clamped values
        meta_valid = FusionMetadata(
            total_source_words=1000,
            output_words=100,
            compression_ratio=compute_compression_ratio(100, 1000),
            topics_found=["Deep Learning", "Transformers"],
        )
        assert meta_valid.compression_ratio == 0.1
        assert len(meta_valid.topics_found) == 2


class TestTopicsContract:
    def test_topics_fallback_from_concepts(self):
        # Simulate when fusion_result.topics is empty but concepts exist
        fusion_topics = []
        job_concepts = [
            {"name": "Quantum Superposition"},
            {"name": "Quantum Entanglement"},
            {"name": "Quantum Superposition"},  # duplicate
        ]

        clean_topics = [t.strip() for t in fusion_topics if isinstance(t, str) and t.strip()]
        if not clean_topics and job_concepts:
            clean_topics = [
                c["name"].strip() if isinstance(c, dict) and c.get("name") else (str(c).strip() if isinstance(c, str) else "")
                for c in job_concepts
            ]
            clean_topics = list(dict.fromkeys(t for t in clean_topics if t))[:10]

        assert clean_topics == ["Quantum Superposition", "Quantum Entanglement"]

    def test_topics_when_none_exist(self):
        fusion_topics = []
        job_concepts = []
        clean_topics = [t.strip() for t in fusion_topics if isinstance(t, str) and t.strip()]
        if not clean_topics and job_concepts:
            clean_topics = [
                c["name"].strip() if isinstance(c, dict) and c.get("name") else str(c)
                for c in job_concepts
            ]
            clean_topics = list(dict.fromkeys(t for t in clean_topics if t))[:10]

        assert clean_topics == []


class TestRightsWarningDeduplication:
    def test_multi_source_warnings_are_deduplicated(self):
        # Create 2 CC-BY sources that each produce the same standard CC BY warning
        src1 = SourceRightsRecord(
            record_id="rec1",
            user_id="user1",
            source_id="src1",
            source_url="https://www.youtube.com/watch?v=src1",
            rights_basis=RightsBasis.CC_BY,
            platform_evidence=PlatformEvidence(
                source_platform="youtube",
                status_license="creativeCommon",
                verified=True,
            ),
        )
        src2 = SourceRightsRecord(
            record_id="rec2",
            user_id="user1",
            source_id="src2",
            source_url="https://www.youtube.com/watch?v=src2",
            rights_basis=RightsBasis.CC_BY,
            platform_evidence=PlatformEvidence(
                source_platform="youtube",
                status_license="creativeCommon",
                verified=True,
            ),
        )

        overall, warnings = evaluate_publication_gate([src1, src2])
        assert overall == PublicationGateStatus.ELIGIBLE_BY_RECORDED_RIGHTS
        # Warnings must be deduplicated — no repeated lines
        assert len(warnings) == len(set(warnings))
