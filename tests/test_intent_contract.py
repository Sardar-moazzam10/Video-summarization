"""Milestone 1 intent-contract regression coverage."""
from types import SimpleNamespace

import pytest

from backend.api.merge import (
    _final_per_video_metrics,
    _resolve_intent_contract,
    _semantic_intent_terms,
)
from backend.models.job import MergeJob
from backend.services.clip_manifest import freeze_manifest
from backend.services.semantic_segmenter import SemanticSegment


@pytest.mark.parametrize(
    ("video_ids", "expected_source_scope"),
    [(["a"], "single"), (["a", "b"], "multi")],
)
def test_title_discovery_never_activates_keyword_mode(video_ids, expected_source_scope):
    request = SimpleNamespace(
        video_ids=video_ids,
        summary_scope="overall",
        source_scope=expected_source_scope,
        discovery_query="mind your language",
        summary_query=None,
        query=None,
        selected_keywords=[],
    )
    intent = _resolve_intent_contract(request)
    job = MergeJob(
        video_ids=video_ids,
        target_duration_minutes=5,
        **intent,
    )

    assert intent["summary_scope"] == "overall"
    assert intent["source_scope"] == expected_source_scope
    assert intent["discovery_query"] == "mind your language"
    assert intent["summary_query"] is None
    assert _semantic_intent_terms(job) == []


@pytest.mark.parametrize(
    ("video_ids", "expected_source_scope"),
    [(["a"], "single"), (["a", "b"], "multi")],
)
def test_keyword_workflow_activates_keyword_mode(video_ids, expected_source_scope):
    request = SimpleNamespace(
        video_ids=video_ids,
        summary_scope="keyword",
        source_scope=expected_source_scope,
        discovery_query=None,
        summary_query="machine learning",
        query=None,
        selected_keywords=["machine learning"],
    )
    intent = _resolve_intent_contract(request)
    job = MergeJob(
        video_ids=video_ids,
        target_duration_minutes=5,
        **intent,
    )

    assert intent["source_scope"] == expected_source_scope
    assert _semantic_intent_terms(job) == ["machine learning"]


def test_explicit_overall_scope_overrides_legacy_query_field():
    """A discovery query cannot become learning intent on explicit new jobs."""
    job = MergeJob(
        video_ids=["a"],
        target_duration_minutes=5,
        summary_scope="overall",
        discovery_query="show title",
        query="legacy discovery value",
    )
    assert _semantic_intent_terms(job) == []


def test_legacy_query_only_job_remains_keyword_compatible():
    job = MergeJob(
        video_ids=["a"],
        target_duration_minutes=5,
        query="legacy keyword",
    )
    assert _semantic_intent_terms(job) == ["legacy keyword"]


def test_source_usage_is_computed_from_final_frozen_manifest():
    candidate_a = SemanticSegment("a", 0, 30, "A", boundary_confidence=1.0)
    candidate_b = SemanticSegment("b", 0, 40, "B", boundary_confidence=1.0)
    candidate_b.concept_scores = {"unique-b": 0.9}
    manifest = freeze_manifest([candidate_b])
    selection_result = SimpleNamespace(
        concept_signal="available",
        concepts_omitted_for_budget=[],
    )

    metrics = _final_per_video_metrics(
        manifest,
        [candidate_a, candidate_b],
        {"a": [{}], "b": [{}]},
        ["concept"],
        selection_result,
    )

    assert metrics["a"]["selected"] == 0
    assert metrics["a"]["seconds"] == 0
    assert metrics["b"]["selected"] == 1
    assert metrics["b"]["seconds"] == 40.0
    assert metrics["b"]["concepts_covered"] == ["unique-b"]
