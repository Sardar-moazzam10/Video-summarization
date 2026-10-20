from types import SimpleNamespace

import pytest

from backend.models.output_contracts import (
    ComponentStatus,
    EvidenceManifest,
    OutputComponentState,
    derive_output_status,
)
from backend.services.evidence_manifest import build_evidence_manifest


def state(status):
    return OutputComponentState(status=status)


@pytest.mark.parametrize(
    ("video", "text", "expected"),
    [
        (ComponentStatus.RUNNING, ComponentStatus.RUNNING, "processing"),
        (ComponentStatus.READY, ComponentStatus.RUNNING, "partial_ready"),
        (ComponentStatus.READY, ComponentStatus.FAILED, "partial_success"),
        (ComponentStatus.FAILED, ComponentStatus.FAILED, "failed"),
        (ComponentStatus.READY, ComponentStatus.READY, "completed"),
    ],
)
def test_component_status_is_derived_without_cross_branch_coupling(video, text, expected):
    assert derive_output_status(state(video), state(text)) == expected


def test_manifest_preserves_independent_keywords_and_provenance():
    job = SimpleNamespace(
        job_id="job-1",
        video_ids=["a", "b"],
        source_durations={"a": 120.0, "b": 240.0},
        summary_scope="keyword",
        selected_keywords=["overfitting", "cross validation"],
        target_duration_minutes=5,
        style="educational",
    )
    clips = [{
        "segment_id": "a:10:20",
        "video_id": "a",
        "start_time": 10,
        "end_time": 20,
        "text": "Cross validation measures generalization error.",
        "keyword_matches": ["cross validation"],
        "keyword_scores": {
            "overfitting": 0.22,
            "cross validation": 0.91,
        },
        "canonical_concepts": ["model evaluation"],
        "completeness": 1.0,
    }]

    manifest = build_evidence_manifest(job, clips)

    assert manifest.manifest_version == 1
    assert manifest.intent.keywords == ["overfitting", "cross validation"]
    assert manifest.intent.source_scope == "multi"
    assert manifest.segments[0].keyword_scores == {
        "overfitting": 0.22,
        "cross validation": 0.91,
    }
    assert manifest.segments[0].segment_id == "a:10:20"


def test_manifest_rejects_mutated_order():
    with pytest.raises(ValueError, match="order"):
        EvidenceManifest.model_validate({
            "job_id": "job-1",
            "intent": {
                "summary_scope": "overall",
                "source_scope": "single",
                "target_duration_minutes": 5,
            },
            "sources": [{"video_id": "a"}],
            "segments": [{
                "segment_id": "a:0:5", "order": 2, "video_id": "a",
                "start_time": 0, "end_time": 5, "text": "Complete evidence sentence.",
            }],
        })
