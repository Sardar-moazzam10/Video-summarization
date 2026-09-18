import pytest
from backend.services.coverage_selector import select_segments, SelectionWeights
from backend.services.semantic_segmenter import SemanticSegment
from unittest.mock import MagicMock

def test_selector_stops_early_for_negative_gain():
    budget = 600.0
    w = SelectionWeights(min_budget_fill=0.6, duration_penalty=0.1)
    segments = []
    for i in range(40):
        segments.append(SemanticSegment("vid1", i*10.0, (i+1)*10.0, f"good {i}"))
    segments.append(SemanticSegment("vid1", 400.0, 900.0, "bad filler"))
    
    mock_embedder = MagicMock()
    # mock encode to return dummy embeddings so it doesn't download model
    import numpy as np
    mock_embedder.encode.return_value = np.zeros((41, 768))

    res = select_segments(segments, budget, concepts=[], summary_embedding=None, weights=w, embedder=mock_embedder)
    assert res.selected_duration < budget
    assert res.selected_duration >= budget * 0.6
