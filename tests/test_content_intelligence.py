from types import SimpleNamespace

from backend.services.content_intelligence import (
    build_content_plan,
    detect_content_type,
    enrich_summary,
    refine_narrative_summary,
)


def segment(text, start=0, end=10):
    return SimpleNamespace(text=text, start_time=start, end_time=end, video_id="v1")


def test_dialogue_heavy_content_is_narrative():
    items = [
        segment("Hello sir, how are you?"),
        segment("I am fine. Why are you late again?"),
        segment("No sir, I went to the gym."),
        segment("Okay, you can start working now."),
    ]
    result = detect_content_type(items)
    assert result.content_type == "narrative"


def test_long_repaired_dialogue_block_is_still_narrative():
    items = [segment(
        "Good morning sir. Yes sir, I brought the new book. Have you read it? "
        "No sir, I started yesterday. Okay, thank you. Why are you late again? "
        "Sir, I changed my gym schedule, so I reached the office late."
    )]
    assert detect_content_type(items).content_type == "narrative"


def test_raw_dialogue_structure_survives_semantic_consolidation():
    raw = [
        {"video_id": "v1", "start_time": index * 2, "end_time": index * 2 + 1.5, "text": text}
        for index, text in enumerate([
            "Where are you going?", "To work.", "No, you stay here.",
            "Why?", "I need your help.", "All right, I will stay.",
        ])
    ]
    consolidated = [segment(" ".join(item["text"] for item in raw), 0, 12)]
    result = detect_content_type(consolidated, structural_segments=raw)
    assert result.content_type == "narrative"
    assert result.signals["structural_segment_count"] == 6
    assert result.signals["semantic_segment_count"] == 1


def test_conversational_educational_interview_is_not_blindly_narrative():
    turns = [
        "Why does regularization help the model?",
        "It helps because the penalty reduces overfitting and improves generalization.",
        "Can you give an example?",
        "For example, ridge regression adds an L2 penalty to the loss function.",
        "So what should practitioners do?",
        "They should validate the method and compare the evidence.",
    ]
    raw = [
        {"video_id": "v1", "start_time": index * 2, "end_time": index * 2 + 1.5, "text": text}
        for index, text in enumerate(turns)
    ]
    result = detect_content_type([segment(" ".join(turns))], structural_segments=raw)
    assert result.content_type == "explanatory"


def test_explanatory_content_remains_explanatory():
    items = [
        segment("Regularization is a method that reduces model overfitting."),
        segment("It works because the penalty discourages excessive parameter values."),
        segment("For example, ridge regression adds an L2 penalty."),
    ]
    assert detect_content_type(items).content_type == "explanatory"


def test_content_plan_removes_stage_directions_and_keeps_metadata():
    plan = build_content_plan([
        {"video_id": "v1", "start_time": 2, "end_time": 7, "order": 0,
         "text": "[Music] The team arrives at the office.",
         "canonical_concepts": ["office arrival"]},
    ], "narrative", 0.8)
    assert "Music" not in plan.bart_input
    assert plan.blocks[0].video_id == "v1"
    assert plan.blocks[0].start_time == 2


def test_dialogue_blocks_are_not_merged_without_incomplete_clause_evidence():
    plan = build_content_plan([
        {"video_id": "v1", "start_time": 0, "end_time": 3, "order": 0,
         "text": "Where are you going?"},
        {"video_id": "v1", "start_time": 3.1, "end_time": 6, "order": 1,
         "text": "I am going to the office."},
    ], "narrative")
    assert len(plan.blocks) == 2


def test_valid_short_dialogue_is_preserved_without_cross_speaker_merge():
    plan = build_content_plan([
        {"video_id": "v1", "start_time": 0, "end_time": 1, "text": "Why?"},
        {"video_id": "v1", "start_time": 1.1, "end_time": 2, "text": "No."},
        {"video_id": "v1", "start_time": 2.1, "end_time": 3, "text": "To work."},
    ], "narrative")
    assert [block.clean_text for block in plan.blocks] == ["Why?", "No.", "To work."]


def test_honorific_caption_continuation_is_repaired_without_invention():
    plan = build_content_plan([{
        "video_id": "v1", "start_time": 0, "end_time": 3,
        "text": "I would appreciate the job, Mrs. Courtney.",
    }], "narrative")
    assert plan.bart_input == "I would appreciate the job, Mrs Courtney."


def test_provenance_metadata_never_enters_bart_text():
    plan = build_content_plan([{
        "video_id": "abc123XYZ", "start_time": 0, "end_time": 3,
        "text": "The manager asks everyone to return to work.",
    }], "narrative")
    assert "abc123XYZ" not in plan.bart_input


def test_narrative_refinement_keeps_events_not_arbitrary_dialogue():
    text = (
        "I have no time to write more. "
        "Anna writes about her life in England. "
        "Why are you late? "
        "The inspector arrives to check the evening classes. "
        "No. "
        "Mr Brown explains his teaching methods to the inspector."
    )
    refined = refine_narrative_summary(text)
    assert "Anna writes" in refined
    assert "inspector arrives" in refined
    assert "Mr Brown explains" in refined
    assert "I have no time" not in refined


def test_global_tldr_is_not_forced_to_first_two_sentences():
    summary = (
        "The hosts greet each other at the office. "
        "They briefly discuss a new book. "
        "A delayed employee explains that the gym changed his schedule. "
        "The manager asks everyone to return to work. "
        "Later, the group resolves the scheduling confusion."
    )
    plan = build_content_plan([
        {"video_id": "v1", "start_time": 0, "end_time": 5, "text": sentence, "order": index}
        for index, sentence in enumerate(summary.split(". "))
    ], "narrative")
    output, _topics = enrich_summary(summary, plan, "informative")
    assert output.tldr
    assert len(output.tldr.split(". ")) >= 2
    assert output.chapters


def test_topics_reject_conversational_garbage():
    plan = build_content_plan([
        {"video_id": "v1", "start_time": 0, "end_time": 5, "order": 0,
         "text": "doo doo doo I am working turn left",
         "canonical_concepts": ["doo doo doo", "i'm working", "turn left"]},
        {"video_id": "v1", "start_time": 5, "end_time": 10, "order": 1,
         "text": "The emotional cycle changes motivation over time.",
         "canonical_concepts": ["emotional cycle"]},
    ], "explanatory")
    output, topics = enrich_summary(
        "The emotional cycle changes motivation over time. People respond differently during each stage.",
        plan,
        "informative",
    )
    assert output.key_takeaways
    assert not {"doo doo doo", "i'm working", "turn left"} & {item.casefold() for item in topics}
    assert "emotional cycle" in {item.casefold() for item in topics}


def test_narrative_knowledge_plan_does_not_emit_educational_roles():
    from backend.services.concept_extractor import Concept
    from backend.services.knowledge_plan import build_knowledge_plan

    item = segment("The manager asked why he arrived late and then the employee left.", 0, 8)
    item.embedding = None
    plan = build_knowledge_plan(
        [item], [Concept(name="office conversation", importance=0.9, reason="recurs")],
        content_type="narrative",
    )
    roles = {unit.role for unit in plan.units if unit.role != "semantic_thought"}
    assert roles <= {"event", "interaction", "development"}
    assert not roles & {"definition", "mechanism_cause", "limitation_pitfall"}
