import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from backend.api.merge import process_merge_job, _active_jobs
from backend.models.job import MergeJob
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
import os

@pytest.fixture
def mock_db():
    with patch("backend.api.merge.get_jobs_collection") as mock_get_collection:
        mock_collection = AsyncMock()
        mock_get_collection.return_value = mock_collection
        # simulate find_one returning a valid job
        mock_collection.find_one.return_value = {"job_id": "test_scorecard_job", "status": "completed"}
        yield mock_collection

@pytest.fixture
def active_job():
    job_id = "test_scorecard_job"
    job = MergeJob(
        job_id=job_id,
        video_ids=["test_vid"],
        target_duration_minutes=1,
        highlight_duration_seconds=60,
    )
    _active_jobs[job_id] = job
    yield job
    _active_jobs.pop(job_id, None)

@pytest.mark.asyncio
async def test_process_merge_job_does_not_await_scorecard(mock_db, active_job):
    """
    Test that process_merge_job completes without awaiting _build_quality_report.
    """
    with patch("backend.api.merge._build_quality_report", new_callable=AsyncMock) as mock_report:
        # We need to stub out the heavy parts so the test runs fast.
        with patch("backend.services.video_service.VideoService.download_videos", new_callable=AsyncMock) as mock_dl, \
             patch("backend.api.merge.fetch_transcripts_with_segments", new_callable=AsyncMock) as mock_fetch, \
             patch("backend.api.merge.get_fusion_engine") as mock_fusion, patch("backend.services.vector_store.get_vector_store", new_callable=AsyncMock), \
             patch("backend.api.merge.run_semantic_selection", new_callable=AsyncMock) as mock_select, \
             patch("backend.services.summarization_service.SummarizationService.summarize_with_policy") as mock_sum_policy, \
             patch("backend.services.summarization_service.SummarizationService.hierarchical_summarize") as mock_sum_hier, \
             patch("backend.services.video_service.VideoService.generate_highlight_reel", new_callable=AsyncMock) as mock_reel, \
             patch("backend.api.merge._extract_audio_from_reel", return_value="audio.mp3"):
            
            # Setup mocks
            mock_fetch.return_value = ({"test_vid": "This is a completely normal English sentence that will correctly be detected as English by the language detector."}, {"test_vid": []})
            mock_select.return_value = {"highlights": []}
            
            fake_fusion_result = MagicMock()
            fake_fusion_result.metadata = {"total_source_words": 1, "clusters_created": 0, "dedup_ratio": 0.0, "processing_time_seconds": 0.0}
            fake_fusion_result.topics = []
            fake_fusion_result.narrative = ""
            mock_fusion.return_value.fuse_transcripts.return_value = fake_fusion_result
            
            mock_sum_hier.return_value = "Summary"
            mock_sum_policy.return_value = ("Summary", {"action": "pass"})
            mock_dl.return_value = {"test_vid": "path.mp4"}
            mock_reel.return_value = "video.mp4"

            
            # Since we sleep for 300s at the end of process_merge_job, we must patch asyncio.sleep
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await process_merge_job("test_scorecard_job")
                
                # Check that _build_quality_report was NOT called during the job
                mock_report.assert_not_called()
                
                # Check that it reached the end (sleep was called)
                mock_sleep.assert_called_once_with(300)
                
                # Check that the job status is COMPLETED
                assert active_job.status.value == "completed"
