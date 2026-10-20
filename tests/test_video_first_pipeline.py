"""
Regression tests for the video-first pipeline restructuring in
process_merge_job (backend/api/merge.py).

Before: selection -> FFmpeg -> persist video_path + VIDEO_READY -> BART ->
        enrichment -> complete.
After:  selection -> (FFmpeg || BART/enrichment) -> join -> complete.

Everything I/O-heavy is mocked (MongoDB, video download/render, transcript
fetch, BART) so these run fast and don't touch the network, ffmpeg, or a
real BART model — same mocking pattern as
tests/test_scorecard_critical_path.py and tests/test_language_capability_gate.py.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backend.api.merge import process_merge_job, _active_jobs
from backend.models.job import MergeJob, JobStatus


EN_TEXT = (
    "This is a completely normal English sentence that will correctly be "
    "detected as English by the language detector. It has several more "
    "words so BART and the local enrichment fallback have something to work with."
)


def _make_highlight(video_id="test_vid"):
    return {
        "video_id": video_id,
        "start_time": 0.0,
        "end_time": 5.0,
        "text": "Highlight transcript text.",
        "importance_score": 0.9,
    }


def _make_job(job_id, generate_video=True):
    job = MergeJob(
        job_id=job_id,
        video_ids=["test_vid"],
        target_duration_minutes=5,
        generate_video=generate_video,
        generate_audio=False,
    )
    _active_jobs[job_id] = job
    return job


async def _run(job, *, summarize_side_effect=None, reel_side_effect=None, call_order=None):
    """
    Runs process_merge_job for `job` with the standard set of mocks.
    Returns the list of every $set payload written to the DB, in order.

    `call_order`, if given, is a list that gets a "video_ready" marker
    appended when the VIDEO_READY checkpoint is written, and a "bart"
    marker appended when summarize_with_policy is invoked — so tests can
    assert which happened first.
    """
    db_writes = []

    async def fake_update_one(query, update, **kw):
        s = update.get("$set", {})
        db_writes.append(s)
        if call_order is not None and "rights_snapshot" in s:
            call_order.append("rights_snapshot")
        if call_order is not None and s.get("status") == "video_ready":
            call_order.append("video_ready")

    jobs_collection = AsyncMock()
    jobs_collection.update_one = fake_update_one
    jobs_collection.find_one = AsyncMock(return_value=None)

    highlight = _make_highlight()

    async def fake_run_semantic_selection(**kw):
        return {"highlights": [highlight], "concepts": [], "metrics": {}, "trace": []}

    fake_fusion_result = MagicMock()
    fake_fusion_result.narrative = "A reconstructed narrative from the selected segments."
    fake_fusion_result.topics = ["topic1"]
    fake_fusion_result.metadata = {
        "total_source_words": 40, "output_words": 20,
        "compression_ratio": 0.5, "clusters_created": 1,
        "dedup_ratio": 0.0, "processing_time_seconds": 0.05,
    }
    fake_fusion_engine = MagicMock()
    fake_fusion_engine.fuse_transcripts = MagicMock(return_value=fake_fusion_result)
    fake_vector_store = MagicMock()
    fake_vector_store.is_video_indexed.return_value = True

    def fake_summarize(*args, **kwargs):
        if call_order is not None:
            call_order.append("bart")
        if summarize_side_effect is not None:
            raise summarize_side_effect
        return ("Final AI summary text.", {"action": "pass"})

    async def fake_generate_highlight_reel(*args, **kwargs):
        if reel_side_effect is not None:
            raise reel_side_effect
        return "video.mp4"

    async def fake_freeze_rights(job_arg, collection):
        snapshot = {
            "schema_version": "1.0",
            "policy_version": "rights-v1-fail-closed",
            "evaluated_at": "2026-01-01T00:00:00+00:00",
            "snapshot_origin": "job_evaluation",
            "sources": [],
            "aggregate": {
                "publication_gate_status": "eligible_by_recorded_rights",
                "warnings": [],
                "source_count": 1,
            },
        }
        job_arg.rights_snapshot = snapshot
        job_arg.publication_gate_status = "eligible_by_recorded_rights"
        job_arg.rights_summary = snapshot["aggregate"]
        await collection.update_one(
            {"job_id": job_arg.job_id},
            {"$set": {"rights_snapshot": snapshot}},
        )
        return snapshot

    with patch("backend.api.merge.get_jobs_collection", new_callable=AsyncMock) as mock_get_collection, \
         patch("backend.api.merge.fetch_transcripts_with_segments", new_callable=AsyncMock) as mock_fetch, \
         patch("backend.api.merge.get_fusion_engine", return_value=fake_fusion_engine), \
         patch("backend.services.vector_store.get_vector_store", return_value=fake_vector_store), \
         patch("backend.api.merge.run_semantic_selection", side_effect=fake_run_semantic_selection), \
         patch("backend.services.video_service.VideoService.download_videos", new_callable=AsyncMock) as mock_dl, \
         patch("backend.services.video_service.VideoService.generate_highlight_reel",
               side_effect=fake_generate_highlight_reel), \
         patch("backend.services.summarization_service.SummarizationService.summarize_with_policy",
               side_effect=fake_summarize), \
         patch("backend.api.merge._freeze_job_rights", side_effect=fake_freeze_rights), \
         patch("backend.api.merge.create_shadow_job_decisions", new_callable=AsyncMock), \
         patch("backend.api.merge.finalize_shadow_manifest", new_callable=AsyncMock), \
         patch("backend.api.merge.append_event", new_callable=AsyncMock), \
         patch("backend.api.merge.set_observation_context", return_value="dummy_token"), \
         patch("backend.api.merge.reset_observation_context"), \
         patch("backend.api.merge.load_job_decision_ids", new_callable=AsyncMock), \
         patch("asyncio.sleep", new_callable=AsyncMock):

        mock_get_collection.return_value = jobs_collection
        mock_fetch.return_value = ({"test_vid": EN_TEXT}, {"test_vid": []})
        mock_dl.return_value = {"test_vid": "path.mp4"}

        with patch("asyncio.sleep", new_callable=AsyncMock):

            await process_merge_job(job.job_id)

    return db_writes


@pytest.mark.asyncio
class TestVideoFirstPipeline:

    async def test_bart_and_video_branches_overlap(self):
        """
        BART must start without waiting for the independent render branch.
        The video branch still freezes rights before exposing VIDEO_READY.
        """
        job = _make_job("test-video-first-order")
        call_order = []
        try:
            await _run(job, call_order=call_order)
        finally:
            _active_jobs.pop(job.job_id, None)

        assert "bart" in call_order, "BART (summarize_with_policy) was never called"
        if "video_ready" in call_order:
            assert call_order.index("rights_snapshot") < call_order.index("video_ready"), (
                f"rights snapshot must be persisted before VIDEO_READY, got order: {call_order}"
            )
            assert call_order.index("bart") < call_order.index("video_ready"), (
                f"BART must run while the video branch is still rendering, "
                f"got order: {call_order}"
            )

    async def test_media_checkpoint_has_video_path_and_no_summary(self):
        """
        The early media write must carry a real video_path and must not write
        an empty summary over the independently running text branch.
        """
        job = _make_job("test-video-first-checkpoint")
        try:
            db_writes = await _run(job)
        finally:
            _active_jobs.pop(job.job_id, None)

        media_writes = [w for w in db_writes if w.get("video_path") == "video.mp4"]
        assert media_writes, f"expected an early media checkpoint, got {db_writes}"
        checkpoint = media_writes[0]
        assert checkpoint["video_path"] == "video.mp4"
        assert "summary_text" not in checkpoint

    async def test_completed_returns_all_final_outputs(self):
        """The final write, once BART/enrichment finish, must be COMPLETED with every output populated."""
        job = _make_job("test-video-first-completed")
        try:
            db_writes = await _run(job)
        finally:
            _active_jobs.pop(job.job_id, None)

        final = db_writes[-1]
        assert final["status"] == JobStatus.COMPLETED.value
        assert final["summary_text"] == "Final AI summary text."
        assert final["video_path"] == "video.mp4"
        assert final["rich_output"] is not None
        assert job.status == JobStatus.COMPLETED.value

    async def test_partial_success_meaning_unchanged_when_video_fails(self):
        """
        Pre-existing PARTIAL_SUCCESS meaning (video failed, summary ok) must
        still work exactly as before the video-first change.
        """
        job = _make_job("test-video-first-video-fails")
        try:
            db_writes = await _run(job, reel_side_effect=RuntimeError("ffmpeg exploded"))
        finally:
            _active_jobs.pop(job.job_id, None)

        final = db_writes[-1]
        assert final["status"] == JobStatus.PARTIAL_SUCCESS.value
        assert final["video_path"] is None
        assert final["summary_text"] == "Final AI summary text."
        # Unchanged existing behavior: stage_message/warning surface the
        # specific video failure reason (job_warning), not a generic one.
        assert "ffmpeg exploded" in final["stage_message"]
        assert final["warning"] and "ffmpeg exploded" in final["warning"]
        # No VIDEO_READY checkpoint should ever have been written — video never succeeded.
        assert not any(w.get("status") == "video_ready" for w in db_writes)

    async def test_summary_failure_does_not_remove_generated_video(self):
        """
        Requirement 4: if BART/enrichment fails AFTER the video was already
        persisted (VIDEO_READY), the job must land on PARTIAL_SUCCESS with
        the video still intact — not ERROR, and not video_path=None.
        """
        job = _make_job("test-video-first-summary-fails")
        try:
            db_writes = await _run(job, summarize_side_effect=RuntimeError("BART exploded"))
        finally:
            _active_jobs.pop(job.job_id, None)

        media_writes = [w for w in db_writes if w.get("video_path") == "video.mp4"]
        assert media_writes, "video must be persisted even when BART fails"

        final = db_writes[-1]
        assert final["status"] == JobStatus.PARTIAL_SUCCESS.value, (
            f"expected partial_success with video preserved, got {final['status']!r}"
        )
        assert final["video_path"] == "video.mp4", "video_path must survive a later summary failure"
        assert final["summary_text"] is None
        assert "AI summary generation failed" in final["stage_message"]

    async def test_summary_failure_without_video_still_errors(self):
        """
        Regression guard: when there is no video to preserve (generate_video
        disabled), a text-pipeline failure must still behave exactly as it
        did before this change — a hard job failure (status=ERROR) — not a
        silently swallowed exception.
        """
        job = _make_job("test-no-video-job", generate_video=False)
        try:
            db_writes = await _run(job, summarize_side_effect=RuntimeError("BART exploded"))
            final = db_writes[-1] if db_writes else {}
            assert final.get("status") == JobStatus.ERROR.value
            assert job.status == JobStatus.ERROR.value
        finally:
            _active_jobs.pop(job.job_id, None)
