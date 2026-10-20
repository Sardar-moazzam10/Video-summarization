import pytest
import asyncio
import logging
from unittest.mock import AsyncMock, patch, MagicMock
from backend.services.acquisition_service import (
    create_shadow_job_decisions,
    ensure_acquisition_indexes,
    set_observation_context,
    reset_observation_context,
    append_event,
    finalize_shadow_manifest,
    _event_locks
)
from backend.models.acquisition import AcquisitionDecisionStatus
from pymongo.errors import DuplicateKeyError

class FakeCursor:
    def __init__(self, data):
        self.data = data
    async def __aiter__(self):
        for item in self.data:
            yield item
    def sort(self, *args, **kwargs):
        return self

class FakeCollection:
    def __init__(self):
        self.docs = []
        self.indexes = {}

    @staticmethod
    def _value(doc, dotted_key):
        value = doc
        for part in dotted_key.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value

    def _matches(self, doc, query):
        return all(self._value(doc, key) == value for key, value in query.items())

    async def create_index(self, keys, **kwargs):
        normalized = [(keys, 1)] if isinstance(keys, str) else list(keys)
        name = kwargs.get("name") or "_".join(f"{key}_{order}" for key, order in normalized)
        self.indexes[name] = {"key": normalized, **kwargs}
        return name
        
    async def insert_one(self, doc):
        for d in self.docs:
            if d.get("decision_id") == doc.get("decision_id") and "decision_hash" in doc:
                raise DuplicateKeyError("dup")
            if d.get("event_id") == doc.get("event_id"):
                raise DuplicateKeyError("dup")
            if d.get("manifest_id") == doc.get("manifest_id") and doc.get("manifest_id"):
                raise DuplicateKeyError("dup")
        self.docs.append(doc)
        return doc

    async def update_one(self, query, update, upsert=False):
        existing = await self.find_one(query)
        if existing:
            return MagicMock(matched_count=1, upserted_id=None)
        if not upsert:
            return MagicMock(matched_count=0, upserted_id=None)
        payload = dict(update.get("$setOnInsert", {}))
        await self.insert_one(payload)
        return MagicMock(matched_count=0, upserted_id=payload.get("decision_id"))
        
    async def find_one(self, query, projection=None):
        for d in self.docs:
            if self._matches(d, query):
                return d
        return None
        
    async def find_one_and_update(self, query, update, return_document=True):
        doc = await self.find_one(query)
        if doc:
            if "$inc" in update:
                for k, v in update["$inc"].items():
                    doc[k] = doc.get(k, 0) + v
            return doc
        return None

    def find(self, query, *args, **kwargs):
        results = []
        for d in self.docs:
            if self._matches(d, query):
                results.append(d)
        return FakeCursor(results)

class FakeDB:
    def __init__(self):
        self.cols = {
            "acquisition_decisions": FakeCollection(),
            "acquisition_events": FakeCollection(),
            "acquisition_manifests": FakeCollection()
        }
    def __getitem__(self, name):
        return self.cols[name]

@pytest.fixture
def fake_db():
    return FakeDB()

@pytest.fixture(autouse=True)
def reset_locks():
    _event_locks.clear()

@pytest.mark.asyncio
async def test_shadow_decision_is_write_once(fake_db):
    with patch("backend.services.acquisition_service.get_database", return_value=fake_db):
        res1 = await create_shadow_job_decisions(job_id="j1", user_id="u1", source_ids=["s1"])
        assert len(fake_db["acquisition_decisions"].docs) == 1
        # Second call should not insert new document or error out
        res2 = await create_shadow_job_decisions(job_id="j1", user_id="u1", source_ids=["s1"])
        assert len(fake_db["acquisition_decisions"].docs) == 1
        assert res1["s1"] == res2["s1"]


@pytest.mark.asyncio
async def test_concurrent_shadow_decision_creation_reuses_one_logical_decision(fake_db):
    with patch("backend.services.acquisition_service.get_database", return_value=fake_db):
        results = await asyncio.gather(*[
            create_shadow_job_decisions(job_id="browser-regression", user_id="u1", source_ids=["s1"])
            for _ in range(8)
        ])

    assert len(fake_db["acquisition_decisions"].docs) == 1
    assert {result["s1"] for result in results} == {
        fake_db["acquisition_decisions"].docs[0]["decision_id"]
    }


@pytest.mark.asyncio
async def test_reused_shadow_decision_is_immutable(fake_db):
    with patch("backend.services.acquisition_service.get_database", return_value=fake_db):
        await create_shadow_job_decisions(job_id="j1", user_id="original", source_ids=["s1"])
        original = dict(fake_db["acquisition_decisions"].docs[0])
        await create_shadow_job_decisions(job_id="j1", user_id="different", source_ids=["s1"])

    assert fake_db["acquisition_decisions"].docs[0] == original


@pytest.mark.asyncio
async def test_acquisition_indexes_are_named_unique_and_idempotent(fake_db):
    with patch("backend.services.acquisition_service.get_database", return_value=fake_db):
        await ensure_acquisition_indexes()
        first = {name: dict(spec) for collection in fake_db.cols.values() for name, spec in collection.indexes.items()}
        await ensure_acquisition_indexes()
        second = {name: dict(spec) for collection in fake_db.cols.values() for name, spec in collection.indexes.items()}

    assert first == second
    assert set(first) == {
        "acq_decision_id_uq",
        "acq_decision_job_source_policy_mode_uq",
        "acq_event_id_uq",
        "acq_event_decision_sequence_uq",
        "acq_manifest_id_uq",
        "acq_manifest_job_policy_mode_uq",
    }
    assert all(spec["unique"] is True for spec in first.values())


@pytest.mark.asyncio
async def test_manifest_finalization_is_idempotent(fake_db):
    with patch("backend.services.acquisition_service.get_database", return_value=fake_db):
        await create_shadow_job_decisions(job_id="j1", user_id="u1", source_ids=["s1"])
        first = await finalize_shadow_manifest("j1", "job_completed")
        second = await finalize_shadow_manifest("j1", "job_completed")

    assert len(fake_db["acquisition_manifests"].docs) == 1
    assert first["manifest_id"] == second["manifest_id"]

@pytest.mark.asyncio
async def test_events_append_monotonic(fake_db):
    with patch("backend.services.acquisition_service.get_database", return_value=fake_db):
        decisions = await create_shadow_job_decisions(job_id="j1", user_id="u1", source_ids=["s1"])
        token = set_observation_context(job_id="j1", user_id="u1", decision_ids=decisions)
        
        await append_event(source_id="s1", operation="caption_read", phase="attempted", method="yt_dlp", outcome_code="started")
        await append_event(source_id="s1", operation="caption_read", phase="succeeded", method="yt_dlp", outcome_code="success")
        
        events = fake_db["acquisition_events"].docs
        assert len(events) == 2
        assert events[0]["sequence"] == 1
        assert events[1]["sequence"] == 2
        assert events[1]["previous_event_hash"] == events[0]["event_hash"]
        reset_observation_context(token)

@pytest.mark.asyncio
async def test_observer_db_unavailable_fails_open(fake_db):
    # Simulate DB failure
    with patch("backend.services.acquisition_service.get_database", side_effect=Exception("DB Down")):
        # Should not raise exception
        res = await create_shadow_job_decisions(job_id="j1", user_id="u1", source_ids=["s1"])
        assert "s1" in res  # Still returns mock decision ID
        
        token = set_observation_context(job_id="j1", user_id="u1", decision_ids=res)
        
        evt = await append_event(source_id="s1", operation="caption_read", phase="attempted", method="test", outcome_code="test")
        assert evt is None  # Fails open, returns None
        
        mf = await finalize_shadow_manifest("j1", "job_completed")
        assert mf is None
        reset_observation_context(token)

@pytest.mark.asyncio
async def test_cancelled_manifest_persists_cancelled_reason(fake_db):
    with patch("backend.services.acquisition_service.get_database", return_value=fake_db):
        await create_shadow_job_decisions(
            job_id="cancelled-job", user_id="u1", source_ids=["s1"]
        )
        manifest = await finalize_shadow_manifest("cancelled-job", "job_cancelled")

    assert manifest["finalization_reason"] == "job_cancelled"
    assert fake_db["acquisition_manifests"].docs[0]["finalization_reason"] == "job_cancelled"


@pytest.mark.asyncio
async def test_shadow_mode_cannot_authorize(fake_db):
    with patch("backend.services.acquisition_service.get_database", return_value=fake_db):
        await create_shadow_job_decisions(job_id="j1", user_id="u1", source_ids=["s1"])
        doc = fake_db["acquisition_decisions"].docs[0]
        assert doc["evaluation_mode"] == "shadow"
        assert doc["authorization_effect"] == "none"
        assert doc["status"] == AcquisitionDecisionStatus.SHADOW_ONLY.value

@pytest.mark.asyncio
async def test_cancellation_propagates():
    from backend.api.merge import process_merge_job
    from backend.models.job import JobStatus

    job = MagicMock()
    job.status = JobStatus.PENDING
    jobs_collection = AsyncMock()

    with (
        patch("backend.api.merge.get_jobs_collection", return_value=jobs_collection),
        patch("backend.api.merge._active_jobs", {"j1": job}) as active_jobs,
        patch(
            "backend.api.merge.create_shadow_job_decisions",
            side_effect=asyncio.CancelledError(),
        ),
        patch("backend.api.merge.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(process_merge_job("j1"), timeout=0.25)

    sleep.assert_not_awaited()
    assert job.status == JobStatus.CANCELLED
    assert job.error == "Job was cancelled"
    assert "j1" not in active_jobs
    persisted = jobs_collection.update_one.await_args.args[1]["$set"]
    assert persisted["status"] == JobStatus.CANCELLED.value
    assert persisted["error"] == "Job was cancelled"
    assert "error_message" not in persisted


@pytest.mark.asyncio
async def test_cancellation_persistence_failure_preserves_cancellation(caplog):
    from backend.api.merge import process_merge_job
    from backend.models.job import JobStatus

    job = MagicMock()
    job.status = JobStatus.PENDING
    jobs_collection = AsyncMock()
    jobs_collection.update_one.side_effect = RuntimeError("mongo unavailable")

    with (
        patch("backend.api.merge.get_jobs_collection", return_value=jobs_collection),
        patch("backend.api.merge._active_jobs", {"j1": job}),
        patch(
            "backend.api.merge.create_shadow_job_decisions",
            side_effect=asyncio.CancelledError(),
        ),
        caplog.at_level(logging.WARNING, logger="backend.api.merge"),
    ):
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(process_merge_job("j1"), timeout=0.25)

    assert job.status == JobStatus.CANCELLED
    assert "Cancellation state persistence failed" in caplog.text


@pytest.mark.asyncio
async def test_cancelled_manifest_and_observer_failure_preserve_cancellation(caplog):
    from backend.api.merge import process_merge_job
    from backend.models.job import JobStatus

    job = MagicMock()
    job.job_id = "cancel-manifest-job"
    job.user_id = "user1"
    job.video_ids = ["vid1"]
    job.status = JobStatus.PENDING
    jobs_collection = AsyncMock()

    with (
        patch("backend.api.merge.get_jobs_collection", return_value=jobs_collection),
        patch("backend.api.merge._active_jobs", {job.job_id: job}),
        patch("backend.api.merge.create_shadow_job_decisions", return_value={}),
        patch("backend.api.merge.set_observation_context", return_value=object()),
        patch("backend.api.merge.reset_observation_context") as reset_context,
        patch(
            "backend.api.merge.fetch_transcripts_with_segments",
            side_effect=asyncio.CancelledError(),
        ),
        patch(
            "backend.api.merge.finalize_shadow_manifest",
            side_effect=RuntimeError("observer unavailable"),
        ) as finalize,
        patch("backend.api.merge.asyncio.sleep", new_callable=AsyncMock) as sleep,
        caplog.at_level(logging.WARNING, logger="backend.api.merge"),
    ):
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(process_merge_job(job.job_id), timeout=0.25)

    finalize.assert_awaited_once_with(job.job_id, "job_cancelled")
    reset_context.assert_called_once()
    sleep.assert_not_awaited()
    assert job.status == JobStatus.CANCELLED
    assert "Acquisition manifest finalization failed" in caplog.text


@pytest.mark.asyncio
async def test_processing_error_remains_error_and_finalizes_failed():
    from backend.api.merge import process_merge_job
    from backend.models.job import JobStatus

    job = MagicMock()
    job.job_id = "failed-job"
    job.user_id = "user1"
    job.video_ids = ["vid1"]
    job.status = JobStatus.PENDING
    jobs_collection = AsyncMock()

    with (
        patch("backend.api.merge.get_jobs_collection", return_value=jobs_collection),
        patch("backend.api.merge._active_jobs", {job.job_id: job}),
        patch("backend.api.merge.create_shadow_job_decisions", return_value={}),
        patch("backend.api.merge.set_observation_context", return_value=object()),
        patch("backend.api.merge.reset_observation_context"),
        patch(
            "backend.api.merge.fetch_transcripts_with_segments",
            side_effect=RuntimeError("processing failed"),
        ),
        patch("backend.api.merge.finalize_shadow_manifest", new_callable=AsyncMock) as finalize,
        patch("backend.api.merge.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        await process_merge_job(job.job_id)

    assert job.status == JobStatus.ERROR
    assert job.error == "processing failed"
    finalize.assert_awaited_once_with(job.job_id, "job_failed")
    sleep.assert_awaited_once_with(300)


@pytest.mark.asyncio
async def test_cancelled_error_survives_database_reload():
    from backend.api.merge import get_job_status

    stored_job = {
        "job_id": "cancelled-job",
        "status": "cancelled",
        "progress_percent": 10,
        "stage_message": "Stopping",
        "error": "Job was cancelled",
        "user_id": "user1",
    }
    with (
        patch("backend.api.merge._active_jobs", {}),
        patch("backend.api.merge._get_owned_job", return_value=stored_job),
    ):
        response = await get_job_status(
            "cancelled-job", current_user={"sub": "user1"}
        )

    assert response.status == "cancelled"
    assert response.error == "Job was cancelled"


@pytest.mark.asyncio
async def test_legacy_error_message_is_still_read_by_status_endpoint():
    from backend.api.merge import get_job_status

    stored_job = {
        "job_id": "legacy-job",
        "status": "cancelled",
        "progress_percent": 10,
        "stage_message": "Stopping",
        "error_message": "Legacy cancellation message",
        "user_id": "user1",
    }
    with (
        patch("backend.api.merge._active_jobs", {}),
        patch("backend.api.merge._get_owned_job", return_value=stored_job),
    ):
        response = await get_job_status(
            "legacy-job", current_user={"sub": "user1"}
        )

    assert response.error == "Legacy cancellation message"


@pytest.mark.asyncio
async def test_integration_pipeline_creates_shadow_events(fake_db):
    from backend.api.merge import process_merge_job
    from backend.models.job import JobStatus
    
    # Mock all the external stuff to let the pipeline run successfully
    async def fake_update(*args, **kwargs): pass
    jobs_collection = AsyncMock()
    jobs_collection.update_one = fake_update
    
    job = MagicMock()
    job.job_id = "integration-job-1"
    job.user_id = "user1"
    job.video_ids = ["vid1"]
    job.generate_video = False
    job.generate_audio = False
    job.target_duration_minutes = 5.0
    job.style = "concise"
    
    fake_fusion_result = MagicMock()
    fake_fusion_result.narrative = "Done"
    fake_fusion_result.topics = []
    fake_fusion_result.metadata = {"total_source_words": 1, "output_words": 1, "compression_ratio": 1.0, "clusters_created": 1, "dedup_ratio": 0.0, "processing_time_seconds": 0.1}

    # Mock the internal logic so process_merge_job runs through
    with (
        patch("backend.api.merge.get_database", return_value=fake_db),
            patch("backend.services.acquisition_service.get_database", return_value=fake_db),
        patch("backend.api.merge.get_jobs_collection", return_value=jobs_collection),
        patch("backend.api.merge._active_jobs", {"integration-job-1": job}),
        patch("backend.api.merge.fetch_transcripts_with_segments", new_callable=AsyncMock, return_value=({"vid1": "text"}, {"vid1": [{"text": "text", "start": 0, "duration": 1}]})),
        patch("backend.api.merge.get_fusion_engine") as fake_ff,
        patch("backend.services.vector_store.get_vector_store"),
        patch("backend.services.summarization_service.get_summarization_service") as fake_ss,
        patch("backend.api.merge.asyncio.sleep", new_callable=AsyncMock),
    ):
        fe = MagicMock()
        fe.fuse_transcripts = MagicMock(return_value=fake_fusion_result)
        fake_ff.return_value = fe
        
        ss = MagicMock()
        ss.summarize_with_policy = MagicMock(return_value=("Summary", {"action": "pass"}))
        fake_ss.return_value = ss
        
        await process_merge_job("integration-job-1")
    
    # Verify shadow decision was created
    decisions = fake_db["acquisition_decisions"].docs
    assert len(decisions) == 1
    assert decisions[0]["job_id"] == "integration-job-1"
    assert decisions[0]["source_ref"]["source_id"] == "vid1"
    
    # Verify manifest was created
    manifests = fake_db["acquisition_manifests"].docs
    assert len(manifests) == 1
    assert manifests[0]["job_id"] == "integration-job-1"
    assert manifests[0]["finalization_reason"] == "job_completed"
    
    # We didn't actually run transcript_service because fetch_transcripts_with_segments was mocked.
    # But this proves the pipeline wrapper (decisions, manifest) works in integration!
