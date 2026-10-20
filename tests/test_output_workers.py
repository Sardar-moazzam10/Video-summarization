from pathlib import Path

import pytest

from backend.workers import text_worker, video_worker
from backend.models.output_contracts import EvidenceManifest
from backend.services.text_output_service import generate_extractive_fallback


def manifest_payload():
    return {
        "manifest_version": 1,
        "job_id": "job-worker",
        "intent": {
            "summary_scope": "keyword",
            "source_scope": "single",
            "keywords": ["validation"],
            "target_duration_minutes": 5,
            "style": "educational",
        },
        "sources": [{"video_id": "source-a", "duration_seconds": 120}],
        "segments": [{
            "segment_id": "source-a:0:20",
            "order": 0,
            "video_id": "source-a",
            "start_time": 0,
            "end_time": 20,
            "text": "Validation measures whether a model generalizes to unseen examples.",
            "keyword_matches": ["validation"],
            "keyword_scores": {"validation": 0.95},
            "importance": 0.9,
        }],
    }


class Result:
    modified_count = 1
    matched_count = 1


class Collection:
    def __init__(self, docs=None):
        self.docs = docs or []

    async def find_one(self, query):
        return next((doc for doc in self.docs if all(doc.get(k) == v for k, v in query.items())), None)

    async def update_one(self, query, update, **kwargs):
        job_id = query.get("job_id")
        doc = next((item for item in self.docs if item.get("job_id") == job_id), None)
        if doc:
            doc.update(update.get("$set", {}))
        return Result()


class Database(dict):
    def __missing__(self, key):
        self[key] = Collection()
        return self[key]


def database_with_job(generate_video=True):
    database = Database()
    database["jobs"] = Collection([{
        "job_id": "job-worker",
        "user_id": "user-1",
        "generate_video": generate_video,
        "status": "generating_video",
        "evidence_manifest": manifest_payload(),
        "video_component": {"status": "queued"},
        "text_component": {"status": "queued"},
    }])
    return database


@pytest.mark.asyncio
async def test_text_worker_consumes_manifest_and_publishes_compatible_result(monkeypatch):
    database = database_with_job(generate_video=False)
    task = {
        "task_id": "task-text", "job_id": "job-worker",
        "manifest_version": 1, "attempts": 1,
    }
    finished = []

    async def claim(*args, **kwargs):
        return task

    async def finish(*args, **kwargs):
        finished.append(kwargs)
        return True

    monkeypatch.setattr(text_worker, "claim_output_task", claim)
    monkeypatch.setattr(text_worker, "finish_output_task", finish)
    expected = generate_extractive_fallback(
        EvidenceManifest.model_validate(manifest_payload())
    )
    monkeypatch.setattr(text_worker, "generate_structured_text", lambda manifest: expected)
    async def immediate_to_thread(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr(text_worker.asyncio, "to_thread", immediate_to_thread)

    assert await text_worker.process_one(database) is True
    job = database["jobs"].docs[0]
    assert job["text_component"]["status"] == "ready"
    assert job["structured_text_output"]["validation"]["valid"] is True
    assert job["summary_text"]
    assert job["rich_output"]["tldr"]
    assert finished[-1]["succeeded"] is True


@pytest.mark.asyncio
async def test_video_worker_renders_only_manifest_intervals_and_freezes_rights(monkeypatch, tmp_path):
    database = database_with_job(generate_video=True)
    task = {
        "task_id": "task-video", "job_id": "job-worker",
        "manifest_version": 1, "attempts": 1,
    }
    calls = {}
    output = tmp_path / "highlight.mp4"
    output.write_bytes(b"video")

    class Service:
        async def download_videos(self, ids, **kwargs):
            calls["download_ids"] = ids
            return {"source-a": str(tmp_path / "source.mp4")}

        async def generate_highlight_reel(self, **kwargs):
            calls["clips"] = kwargs["highlight_segments"]
            return str(output)

    async def claim(*args, **kwargs):
        return task

    async def finish(*args, **kwargs):
        calls["finished"] = kwargs
        return True

    async def freeze(**kwargs):
        calls["rights"] = kwargs["video_ids"]
        return {"aggregate": {}}

    monkeypatch.setattr(video_worker, "claim_output_task", claim)
    monkeypatch.setattr(video_worker, "finish_output_task", finish)
    monkeypatch.setattr(video_worker, "get_video_service", lambda: Service())
    monkeypatch.setattr(video_worker, "freeze_job_rights_snapshot", freeze)

    assert await video_worker.process_one(database) is True
    job = database["jobs"].docs[0]
    assert calls["download_ids"] == ["source-a"]
    assert [(clip["start_time"], clip["end_time"]) for clip in calls["clips"]] == [(0.0, 20.0)]
    assert calls["rights"] == ["source-a"]
    assert calls["finished"]["succeeded"] is True
    assert job["video_component"]["status"] == "ready"
    assert job["video_path"] == str(output)
