import pytest

from backend.models.output_contracts import EvidenceManifest
from backend.services.text_output_service import (
    build_evidence_matrix,
    generate_extractive_fallback,
    generate_structured_text,
)


def manifest(scope="keyword", sources="multi"):
    return EvidenceManifest.model_validate({
        "job_id": "job-text",
        "intent": {
            "summary_scope": scope,
            "source_scope": sources,
            "keywords": ["overfitting", "cross validation"] if scope == "keyword" else [],
            "target_duration_minutes": 5,
            "style": "educational",
        },
        "sources": [{"video_id": "a"}, {"video_id": "b"}],
        "segments": [
            {
                "segment_id": "a:0", "order": 0, "video_id": "a",
                "start_time": 0, "end_time": 20,
                "text": "Overfitting causes a model to memorize training examples instead of generalizing.",
                "keyword_matches": ["overfitting"],
                "keyword_scores": {"overfitting": 0.92, "cross validation": 0.21},
                "importance": 0.9,
            },
            {
                "segment_id": "b:0", "order": 1, "video_id": "b",
                "start_time": 30, "end_time": 55,
                "text": "Cross validation estimates performance by evaluating the model on held-out folds.",
                "keyword_matches": ["cross validation"],
                "keyword_scores": {"overfitting": 0.28, "cross validation": 0.94},
                "importance": 0.85,
            },
            {
                "segment_id": "b:1", "order": 2, "video_id": "b",
                "start_time": 60, "end_time": 82,
                "text": "Regularization and early stopping reduce the risk of memorizing noisy data.",
                "keyword_scores": {"overfitting": 0.71, "cross validation": 0.32},
                "importance": 0.75,
            },
        ],
    })


def test_matrix_never_averages_independent_keywords():
    matrix = build_evidence_matrix(manifest())
    assert matrix["by_keyword"]["overfitting"] == ["a:0", "b:1"]
    assert matrix["by_keyword"]["cross validation"] == ["b:0"]


def test_keyword_matching_is_case_insensitive_across_manifest_producers():
    value = manifest()
    value.segments[0].keyword_scores = {"OVERFITTING": 0.92}
    value.segments[0].keyword_matches = ["OverFitting"]
    matrix = build_evidence_matrix(value)
    assert "a:0" in matrix["by_keyword"]["overfitting"]


def test_keyword_fallback_balances_keywords_and_is_grounded():
    result = generate_extractive_fallback(manifest())
    assert result.mode == "keyword_multi"
    assert result.validation["valid"] is True
    assert len(result.tldr.text.split()) <= 45
    assert {item.keyword: item.status for item in result.keyword_coverage} == {
        "overfitting": "supported",
        "cross validation": "supported",
    }
    assert result.summary[0].evidence_ids == ["a:0"]
    assert result.summary[1].evidence_ids == ["b:0"]
    assert all(item.evidence_ids for item in result.key_takeaways)


def test_unsupported_keyword_is_reported_not_invented():
    value = manifest()
    value.intent.keywords.append("quantum chromodynamics")
    result = generate_extractive_fallback(value)
    coverage = {item.keyword: item.status for item in result.keyword_coverage}
    assert coverage["quantum chromodynamics"] == "unsupported"


def test_primary_generator_changes_only_summary_and_keeps_grounded_contract():
    class Summarizer:
        def summarize_with_policy(self, text, target_words, profile, embedder, content_type):
            assert "Overfitting" in text
            assert "Cross validation" in text
            return (
                "Overfitting prevents reliable generalization on unseen examples. "
                "Cross validation estimates performance using held-out folds.",
                {"action": "compress", "reason": "test"},
            )

    result = generate_structured_text(manifest(), summarizer=Summarizer())
    assert result.generation_mode == "generated"
    assert result.validation["valid"] is True
    assert result.validation["summarization_decision"]["action"] == "compress"
    assert result.summary[0].evidence_ids
    assert set(result.summary[0].evidence_ids) <= {"a:0", "b:0", "b:1"}
    assert len(result.summary[0].evidence_ids) <= 3


def test_primary_generator_failure_uses_safe_fallback():
    class BrokenSummarizer:
        def summarize_with_policy(self, *args, **kwargs):
            raise RuntimeError("model unavailable")

    result = generate_structured_text(manifest(), summarizer=BrokenSummarizer())
    assert result.generation_mode == "extractive_fallback"
    assert result.validation["valid"] is True


@pytest.mark.parametrize(
    ("scope", "source_scope", "expected_mode"),
    [
        ("overall", "single", "overall_single"),
        ("overall", "multi", "overall_multi"),
        ("keyword", "single", "keyword_single"),
        ("keyword", "multi", "keyword_multi"),
    ],
)
def test_all_intent_shapes_publish_their_explicit_contract(
    scope, source_scope, expected_mode
):
    value = manifest(scope=scope, sources=source_scope)
    if source_scope == "single":
        value.sources = [value.sources[0]]
        value.segments = [value.segments[0]]
    result = generate_extractive_fallback(value)
    assert result.mode == expected_mode
    assert result.validation["valid"] is True
