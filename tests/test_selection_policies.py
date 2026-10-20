import numpy as np
import pytest

from backend.services.coverage_selector import (
    SelectionWeights,
    resolve_selection_policy,
    select_segments,
)
from backend.services.knowledge_plan import KnowledgeUnit
from backend.services.semantic_segmenter import SemanticSegment


BASE = SelectionWeights(
    concept=0.32,
    semantic=0.20,
    coverage=0.28,
    coherence=0.10,
    redundancy=0.25,
    duration_penalty=0.05,
    min_budget_fill=0.90,
)


def segment(source, start, text, vector, *, filler=0.0):
    item = SemanticSegment(
        source, start, start + 30.0, text,
        embedding=np.asarray(vector, dtype=float),
        boundary_confidence=1.0,
        completeness=1.0,
    )
    item.information_density = 1.0 - filler
    item.filler_penalty = filler
    return item


def policy(scope, sources):
    return resolve_selection_policy(scope, sources, BASE)


def test_four_policy_identities_and_milestone_one_weights():
    expected = {
        ("overall", "single"): ("overall_single", 0.20, 0.28, 0.0),
        ("overall", "multi"): ("overall_multi", 0.20, 0.28, 0.07),
        ("keyword", "single"): ("keyword_single", 0.32, 0.16, 0.0),
        ("keyword", "multi"): ("keyword_multi", 0.32, 0.16, 0.06),
    }
    for key, values in expected.items():
        resolved = policy(*key)
        name, semantic, coverage, diversity = values
        assert resolved.name == name
        assert resolved.weights.semantic == pytest.approx(semantic)
        assert resolved.weights.coverage == pytest.approx(coverage)
        assert resolved.source_diversity_weight == pytest.approx(diversity)


def test_overall_single_favors_broad_timeline_coverage():
    items = [
        segment("a", index * 60, f"topic {index}", np.eye(10)[index])
        for index in range(10)
    ]
    result = select_segments(
        items, 90,
        total_duration=600, policy=policy("overall", "single"),
    )
    starts = [item.start_time for item in result.segments]
    assert max(starts) - min(starts) >= 120
    assert len({int(start / 60) for start in starts}) == len(starts)


def test_keyword_single_can_focus_without_artificial_timeline_fill():
    items = [
        segment("a", 0, "irrelevant introduction", [0.0, 1.0]),
        segment("a", 270, "query definition", [1.0, 0.0]),
        segment("a", 300, "query explanatory example", [0.99, 0.1]),
        segment("a", 570, "irrelevant conclusion", [0.0, 1.0]),
    ]
    result = select_segments(
        items, 60, summary_embedding=np.asarray([1.0, 0.0]),
        query_embedding=np.asarray([[1.0, 0.0]]), total_duration=600,
        policy=policy("keyword", "single"),
    )
    assert all(item.start_time in {270, 300} for item in result.segments)
    assert len(result.segments) == 2
    assert all(float(item.query_relevance) >= 0.95 for item in result.segments)


def test_overall_multi_rewards_useful_unique_underrepresented_source():
    items = [
        segment("a", 0, "shared strong explanation", [1.0, 0.0]),
        segment("a", 60, "another moderate detail", [0.70, 0.714]),
        segment("b", 0, "useful unique evidence", [0.90, 0.44]),
    ]
    result = select_segments(
        items, 60, summary_embedding=np.asarray([1.0, 0.0]),
        total_duration={"a": 90, "b": 30},
        policy=policy("overall", "multi"),
    )
    assert {item.video_id for item in result.segments} == {"a", "b"}
    b_trace = next(item for item in result.trace if item["video_id"] == "b")
    assert b_trace["source_diversity_bonus"] > 0
    assert b_trace["final_gain"] > b_trace["base_weighted_gain"]


def test_keyword_multi_selects_complementary_query_evidence():
    items = [
        segment("a", 0, "query definition", [1.0, 0.0]),
        segment("a", 60, "query definition repeated", [0.999, 0.02]),
        segment("b", 0, "query worked example", [0.92, 0.39]),
    ]
    result = select_segments(
        items, 60, summary_embedding=np.asarray([1.0, 0.0]),
        query_embedding=np.asarray([[1.0, 0.0]]),
        total_duration={"a": 90, "b": 30},
        policy=policy("keyword", "multi"),
    )
    assert {item.video_id for item in result.segments} == {"a", "b"}


def test_genuine_cross_source_paraphrase_remains_hard_rejected():
    items = [
        segment("a", 0, "a neural network learns weighted patterns from data", [1.0, 0.0]),
        segment("b", 0, "a neural network learns weighted patterns from data", [1.0, 0.0]),
    ]
    result = select_segments(
        items, 60, summary_embedding=np.asarray([1.0, 0.0]),
        total_duration={"a": 30, "b": 30},
        policy=policy("keyword", "multi"),
    )
    assert len(result.segments) == 1
    assert result.duplicates_rejected == 1
    assert result.early_stop_reason == "no_eligible_candidates_after_filtering"


def test_useless_source_is_not_selected_for_diversity_and_no_quota_exists():
    items = [
        segment("a", 0, "useful primary evidence", [1.0, 0.0]),
        segment("a", 60, "useful complementary evidence", [0.85, 0.53]),
        segment("b", 0, "um uh unrelated", [0.0, 1.0], filler=0.9),
        segment("c", 0, "more unrelated filler", [0.0, 1.0], filler=0.9),
    ]
    result = select_segments(
        items, 60, summary_embedding=np.asarray([1.0, 0.0]),
        total_duration={"a": 90, "b": 30, "c": 30},
        policy=policy("overall", "multi"),
    )
    assert {item.video_id for item in result.segments} == {"a"}


def test_overall_early_stop_uses_full_objective_not_unit_only():
    items = [
        segment("a", 0, "topic definition", [1.0, 0.0]),
        segment("a", 570, "valuable late synthesis", [0.9, 0.44]),
    ]
    items[0].knowledge_unit_scores = {"topic::definition": 1.0}
    unit = KnowledgeUnit(
        unit_id="topic::definition", concept="topic", role="definition",
        importance=1.0, essential=True, tier=1,
    )
    result = select_segments(
        items, 60, summary_embedding=np.asarray([1.0, 0.0]),
        total_duration=600, knowledge_units=[unit],
        policy=policy("overall", "single"),
    )
    assert len(result.segments) == 2
    assert result.early_stop_reason != "remaining_marginal_knowledge_gain_below_threshold"
