"""Phase-1 knowledge plan and unit-level novelty regressions."""

import numpy as np

from backend.services.concept_extractor import Concept
from backend.services.coverage_selector import SelectionWeights, select_segments
from backend.services.knowledge_plan import build_knowledge_plan
from backend.services.semantic_segmenter import SemanticSegment


def _segments(embedder, specs):
    result = []
    for video_id, start, end, text, boundary, complete in specs:
        result.append(SemanticSegment(
            video_id, start, end, text,
            embedding=embedder.encode([text])[0],
            boundary_confidence=boundary,
            completeness=complete,
        ))
    return result


def _concept(embedder):
    concept = Concept("Overfitting", importance=1.0)
    concept.embedding = embedder.encode(["Overfitting model generalization"])[0]
    return concept


def _weights():
    return SelectionWeights(
        concept=1.0,
        semantic=0.05,
        coverage=0.0,
        coherence=0.1,
        redundancy=0.15,
        duration_penalty=0.02,
        min_budget_fill=0.0,
    )


def test_duplicate_definition_is_suppressed_but_prevention_survives(embedder):
    segments = _segments(embedder, [
        ("a", 0, 40, "Overfitting means a model memorizes training data.", 1.0, 1.0),
        ("b", 0, 42, "Overfitting is defined as memorizing training examples.", 1.0, 1.0),
        ("c", 0, 45, "Regularization and early stopping prevent overfitting.", 1.0, 1.0),
    ])
    concept = _concept(embedder)
    plan = build_knowledge_plan(segments, [concept], query="overfitting")
    result = select_segments(
        segments, 100, [concept], _weights(), embedder=embedder,
        total_duration={"a": 40, "b": 42, "c": 45},
        knowledge_units=plan.units,
    )
    texts = " ".join(segment.text for segment in result.segments).lower()
    definitions = sum("means" in s.text.lower() or "defined as" in s.text.lower()
                      for s in result.segments)
    assert definitions == 1
    assert "prevent" in texts


def test_best_clear_complete_explanation_wins(embedder):
    segments = _segments(embedder, [
        ("poor", 0, 90, "Welcome to today's lecture um uh you know. Overfitting means memorizing data. Subscribe.", 0.2, 0.7),
        ("clear", 0, 45, "Overfitting means the model memorizes training data and fails to generalize to unseen examples.", 1.0, 1.0),
        ("repeat", 0, 50, "Overfitting means overfitting means memorizing memorizing training training data data.", 0.6, 1.0),
    ])
    concept = _concept(embedder)
    plan = build_knowledge_plan(segments, [concept], query="overfitting")
    result = select_segments(
        segments, 45, [concept], _weights(), embedder=embedder,
        total_duration={"poor": 90, "clear": 45, "repeat": 50},
        knowledge_units=plan.units,
    )
    assert [segment.video_id for segment in result.segments] == ["clear"]


def test_useful_budget_stops_before_irrelevant_filler(embedder):
    useful = [
        ("a", 0, 60, "Overfitting means a model memorizes training data and fails on new data.", 1.0, 1.0),
        ("b", 0, 60, "Regularization and early stopping prevent overfitting in deployed models.", 1.0, 1.0),
    ]
    filler = [
        (f"f{i}", 0, 60, f"Welcome subscribe office hours unrelated filler section {i}.", 0.2, 1.0)
        for i in range(4)
    ]
    segments = _segments(embedder, useful + filler)
    concept = _concept(embedder)
    plan = build_knowledge_plan(segments, [concept], query="overfitting")
    result = select_segments(
        segments, 300, [concept], _weights(), embedder=embedder,
        total_duration={s.video_id: s.duration for s in segments},
        knowledge_units=plan.units,
    )
    assert result.total_duration == 120
    assert result.useful_fill_ratio == 0.4
    assert result.early_stop_reason == "remaining_marginal_knowledge_gain_below_threshold"
    assert all(not segment.video_id.startswith("f") for segment in result.segments)


def test_query_none_uses_same_optional_plan_path(embedder):
    segments = _segments(embedder, [
        ("a", 0, 40, "Overfitting means memorizing training data.", 1.0, 1.0),
    ])
    concept = _concept(embedder)
    plan = build_knowledge_plan(segments, [concept], query=None)
    result = select_segments(
        segments, 60, [concept], _weights(), embedder=embedder,
        total_duration=40, knowledge_units=plan.units,
    )
    assert result.segments
    assert plan.query == ""


def test_keyword_query_and_automatic_mode_share_the_plan(embedder):
    segments = _segments(embedder, [
        ("a", 0, 40, "Overfitting means memorizing training data.", 1.0, 1.0),
        ("b", 0, 40, "A bread recipe uses flour and water.", 1.0, 1.0),
    ])
    concept = _concept(embedder)
    keyword_plan = build_knowledge_plan(segments, [concept], query="overfitting")
    automatic_plan = build_knowledge_plan(segments, [concept], query=None)
    assert type(keyword_plan) is type(automatic_plan)
    query_embedding = embedder.encode(["overfitting"])
    result = select_segments(
        segments, 40, [concept], _weights(), embedder=embedder,
        query_embedding=query_embedding, total_duration={"a": 40, "b": 40},
        knowledge_units=keyword_plan.units,
    )
    assert result.segments[0].video_id == "a"
    assert result.segments[0].query_relevance is not None


def test_duration_profiles_unlock_depth_without_removing_essentials(embedder):
    segments = _segments(embedder, [
        ("base", 0, 40, "Supervised learning means fitting labeled data to map features X to labels Y for classification.", 1.0, 1.0),
        ("core", 0, 40, "The model does not generalize to new situations and overfits the training set.", 1.0, 1.0),
        ("applied", 0, 40, "Dropout and regularization prevent overfitting in this practical example.", 1.0, 1.0),
    ])
    concept = Concept("Supervised Machine Learning", importance=1.0, source="query")
    concept.embedding = embedder.encode(["Supervised Machine Learning"])[0]
    plans = [
        build_knowledge_plan(
            segments, [concept], query="Supervised Machine Learning",
            query_embedding=concept.embedding, budget_seconds=minutes * 60,
        )
        for minutes in (5, 10, 15)
    ]
    unit_sets = [{unit.unit_id for unit in plan.units} for plan in plans]
    assert unit_sets[0] <= unit_sets[1] <= unit_sets[2]
    assert not any("overfitting" in unit for unit in unit_sets[0])
    assert any("overfitting" in unit for unit in unit_sets[1])
    assert any("mitigation_prevention" in unit for unit in unit_sets[2])
    assert max(unit.tier for unit in plans[0].units) == 1
    assert max(unit.tier for unit in plans[1].units) == 2
    assert max(unit.tier for unit in plans[2].units) == 3


def test_specific_subtopic_bypasses_only_broad_query_gate(embedder):
    segments = _segments(embedder, [
        ("core", 159, 186, "It does not generalize to new situations very well.", 1.0, 1.0),
        ("mitigation", 2820, 2894, "Dropout is an effective technique to prevent overfitting.", 1.0, 1.0),
    ])
    concept = Concept("Supervised Machine Learning", importance=1.0, source="query")
    # Deliberately orthogonal: lexical unit evidence, not a broad root cosine,
    # must preserve these supported subtopics.
    concept.embedding = np.asarray([1.0, 0.0])
    for segment in segments:
        segment.embedding = np.asarray([0.0, 1.0])
    plan = build_knowledge_plan(
        segments, [concept], query="Supervised Machine Learning",
        query_embedding=concept.embedding, budget_seconds=15 * 60,
    )
    scores = set().union(*(segment.knowledge_unit_scores for segment in segments))
    assert "supervised_machine_learning::generalization" in scores
    assert "supervised_machine_learning::overfitting" in scores
    assert "supervised_machine_learning::mitigation_prevention" in scores


def test_semantic_knowledge_plan_rejects_lexical_junk(embedder):
    concept = Concept("Functional Requirements", importance=1.0, source="query")
    concept.embedding = embedder.encode(["Functional requirements define system behavior."])[0]
    junk = SemanticSegment(
        "junk", 0, 28,
        "car using seen working minutes user eat",
        embedding=embedder.encode(["car using seen working minutes user eat"])[0],
        boundary_confidence=1.0,
        completeness=1.0,
    )
    useful = SemanticSegment(
        "good", 0, 30,
        "Functional requirements describe system behavior, while non-functional requirements constrain quality attributes like security and performance.",
        embedding=embedder.encode(["Functional requirements describe system behavior, while non-functional requirements constrain quality attributes like security and performance."])[0],
        boundary_confidence=1.0,
        completeness=1.0,
    )
    plan = build_knowledge_plan([junk, useful], [concept], query="functional requirements")
    assert "car" not in " ".join(unit.unit_id for unit in plan.units).lower()
    assert any("functional" in unit.unit_id.lower() for unit in plan.units)
    assert any(getattr(segment, "semantic_knowledge_unit", "") for segment in [junk, useful])


def test_same_source_overlap_is_rejected_in_selection(embedder):
    segments = [
        SemanticSegment("A", 0, 60, "Functional requirements describe system behavior and user-visible actions.", embedding=np.asarray([1.0, 0.0], dtype=float), boundary_confidence=1.0, completeness=1.0),
        SemanticSegment("A", 50, 90, "Non-functional requirements constrain quality attributes such as security and reliability.", embedding=np.asarray([0.95, 0.1], dtype=float), boundary_confidence=1.0, completeness=1.0),
    ]
    result = select_segments(
        segments,
        120,
        concepts=[Concept("Functional Requirements", importance=1.0)],
        weights=SelectionWeights(concept=1.0, semantic=0.2, coverage=0.1, coherence=0.3, redundancy=0.4, duration_penalty=0.0, min_budget_fill=0.0),
        embedder=embedder,
        total_duration={"A": 90},
    )
    assert len(result.segments) == 1
    assert result.same_source_overlap == 0


def test_semantic_redundancy_is_measured_by_similarity_not_lexical_count(embedder):
    segs = [
        SemanticSegment("A", 0, 30, "Functional requirements describe what the system should do and how users interact with it.", embedding=np.asarray([1.0, 0.0], dtype=float), boundary_confidence=1.0, completeness=1.0),
        SemanticSegment("B", 0, 30, "Functional requirements describe the actions the system must perform and the user behavior it supports.", embedding=np.asarray([0.98, 0.1], dtype=float), boundary_confidence=1.0, completeness=1.0),
        SemanticSegment("C", 0, 30, "Security is a non-functional requirement that protects data confidentiality and service availability.", embedding=np.asarray([0.0, 1.0], dtype=float), boundary_confidence=1.0, completeness=1.0),
    ]
    result = select_segments(
        segs,
        120,
        concepts=[Concept("Functional Requirements", importance=1.0), Concept("Security", importance=1.0)],
        weights=SelectionWeights(concept=1.0, semantic=0.3, coverage=0.1, coherence=0.2, redundancy=0.4, duration_penalty=0.0, min_budget_fill=0.0),
        embedder=embedder,
        total_duration={"A": 30, "B": 30, "C": 30},
    )
    assert hasattr(result, "semantic_redundancy")
    assert 0.0 <= result.semantic_redundancy <= 1.0
    assert len(result.segments) >= 2
