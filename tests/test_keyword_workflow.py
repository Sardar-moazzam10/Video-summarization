"""Keyword requests use the shared multi-video selector."""
import numpy as np

from backend.models.job import MergeJob, MergeJobCreate
from backend.services.coverage_selector import SelectionWeights, select_segments
from backend.services.semantic_segmenter import SemanticSegment


class KeywordEmbedder:
    def encode(self, texts, **kwargs):
        return np.asarray([[1.0, 0.0, 0.0, 0.0] if "machine learning" in text.lower()
                           else [0.0, 1.0, 0.0, 0.0] for text in texts])


def candidates(video_ids):
    result = []
    for video_id in video_ids:
        for i, text in enumerate(("Machine learning model explanation", "Bread recipe and cooking")):
            result.append(SemanticSegment(
                video_id, i * 30.0, (i + 1) * 30.0, text,
                embedding=KeywordEmbedder().encode([text])[0],
                boundary_confidence=1.0, completeness=1.0,
            ))
    return result


def weights():
    return SelectionWeights(concept=0.0, semantic=1.0, coverage=0.1,
                            coherence=0.0, redundancy=0.2, duration_penalty=0.0)


def test_job_models_retain_selected_keywords():
    request = MergeJobCreate(video_ids=["a", "b"], selected_keywords=["machine learning"])
    job = MergeJob(video_ids=request.video_ids, target_duration_minutes=5,
                   selected_keywords=request.selected_keywords)
    assert job.selected_keywords == ["machine learning"]


def test_keyword_priority_uses_shared_selector():
    result = select_segments(candidates(["a"]), 30, weights=weights(),
                             embedder=KeywordEmbedder(), query_embedding=np.array([[1, 0, 0, 0]]))
    assert len(result.segments) == 1
    assert "machine learning" in result.segments[0].text.lower()
    assert result.trace[0]["query_relevance"] == 1.0


def test_keyword_duplicates_compete_across_sources():
    result = select_segments(candidates(["a", "b", "c"]), 30, weights=weights(),
                             embedder=KeywordEmbedder(), query_embedding=np.array([[1, 0, 0, 0]]),
                             total_duration={video_id: 60 for video_id in ["a", "b", "c"]})
    assert len(result.segments) == 1
    assert "machine learning" in result.segments[0].text.lower()


def test_automatic_mode_remains_supported():
    result = select_segments(candidates(["a", "b"]), 60, weights=weights(),
                             embedder=KeywordEmbedder(), query_embedding=None,
                             total_duration={"a": 60, "b": 60})
    assert result.segments
    assert all(item["query_relevance"] is None for item in result.trace)
