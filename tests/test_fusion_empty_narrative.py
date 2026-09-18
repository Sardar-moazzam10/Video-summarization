import pytest
from backend.services.fusion_engine import FusionEngine, SourcedSentence, TopicCluster

def test_fusion_engine_never_returns_empty_narrative():
    engine = FusionEngine()
    
    # Simulate a scenario where the first (and only) cluster has more words 
    # than the target_words * 1.1 limit.
    # E.g. target_words = 10 (limit = 11)
    # Cluster has 20 words.
    
    long_sentence = " ".join(["word"] * 20)
    
    cluster = TopicCluster(
        cluster_id=0,
        sentences=[
            SourcedSentence(text=long_sentence, video_id="vid1", video_title="Title1", position=0)
        ],
        representative=long_sentence
    )
    
    narrative = engine._synthesize_narrative(
        clusters=[cluster],
        conflicts=[],
        target_words=10,
        include_sources=False,
        include_transitions=False
    )
    
    assert len(narrative.strip()) > 0, "Narrative should not be empty even if the first cluster exceeds target budget"
    assert len(narrative.split()) == 20, "The first cluster should be fully included"

