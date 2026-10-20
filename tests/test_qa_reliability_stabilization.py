import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.models.job import JobStatus
from backend.services.job_recovery import heartbeat_is_stale, recover_orphaned_jobs
from backend.services.media_probe import clear_cache, get_video_duration_seconds, prime_duration_cache
from backend.services.text_normalization import sanitize_asr_fragment, sanitize_asr_items
from backend.services.transcript_service import TranscriptService


@pytest.mark.asyncio
async def test_restart_marks_unsafe_workers_recoverable_and_preserves_render_checkpoint():
    collection = SimpleNamespace(update_many=AsyncMock(side_effect=[
        SimpleNamespace(modified_count=1), SimpleNamespace(modified_count=3)
    ]))
    result = await recover_orphaned_jobs(collection)
    assert result == {"render_checkpoints_preserved": 1, "recoverable_failures": 3}
    first_filter, first_update = collection.update_many.await_args_list[0].args
    assert first_filter["status"] == JobStatus.VIDEO_READY.value
    assert first_filter["output_execution_mode"] == {"$ne": "durable_workers"}
    assert first_update["$set"]["status"] == JobStatus.PARTIAL_SUCCESS.value
    assert first_update["$set"]["recovery_state"] == "render_checkpoint_preserved"
    second_update = collection.update_many.await_args_list[1].args[1]["$set"]
    second_filter = collection.update_many.await_args_list[1].args[0]
    assert second_filter["output_execution_mode"] == {"$ne": "durable_workers"}
    assert second_update["status"] == JobStatus.ERROR.value
    assert second_update["recoverable"] is True


def test_worker_heartbeat_staleness_is_deterministic():
    now = datetime.utcnow()
    assert heartbeat_is_stale(None, now=now)
    assert heartbeat_is_stale(now - timedelta(seconds=121), now=now, stale_after_seconds=120)
    assert not heartbeat_is_stale(now - timedelta(seconds=30), now=now, stale_after_seconds=120)


@pytest.mark.asyncio
async def test_transcript_singleflight_deduplicates_identical_calls():
    service = TranscriptService.__new__(TranscriptService)
    service._inflight = {}
    calls = 0
    async def impl(*args, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return {"transcript": [{"text": "ready"}]}
    service._get_transcript_impl = impl
    a, b = await asyncio.gather(
        service.get_transcript("abcdefghijk"),
        service.get_transcript("abcdefghijk"),
    )
    assert calls == 1
    assert a == b


@pytest.mark.asyncio
async def test_merge_fanout_enforces_per_source_timeout(monkeypatch):
    from backend.api import merge
    async def slow_transcript(*args, **kwargs):
        await asyncio.sleep(60)
    service = SimpleNamespace(get_transcript=AsyncMock(side_effect=slow_transcript))
    async def factory(): return service
    monkeypatch.setattr("backend.services.transcript_service.get_transcript_service", factory)
    record = {}
    text, segments = await merge.fetch_transcripts_with_segments(
        ["abcdefghijk"], per_source_timeout=0.01, preflight_record=record
    )
    assert text == {} and segments == {}
    assert record["abcdefghijk"]["method"] == "timeout"


def test_verified_metadata_primes_duration_without_probe(monkeypatch):
    clear_cache()
    prime_duration_cache("abcdefghijk", 1234)
    monkeypatch.setattr("backend.services.media_probe.subprocess.run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("probe called")))
    assert get_video_duration_seconds("abcdefghijk") == 1234


def test_asr_noise_never_becomes_topic_or_takeaway():
    assert sanitize_asr_fragment("[NOISE]") == ""
    assert sanitize_asr_fragment("[inaudible] ...") == ""
    assert sanitize_asr_fragment("!!!") == ""
    assert sanitize_asr_items(["[music]", "...", "gradient descent optimization"], min_words=2) == ["gradient descent optimization"]
