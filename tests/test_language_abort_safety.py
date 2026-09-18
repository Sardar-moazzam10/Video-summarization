import pytest
import asyncio
from unittest.mock import patch, MagicMock
from backend.api.merge import process_merge_job
from backend.models.job import MergeJobCreate
import uuid

@pytest.mark.asyncio
async def test_language_abort_safety_handles_none():
    job_id = str(uuid.uuid4())
    req = MergeJobCreate(
        video_ids=["vid1"],
        target_duration_minutes=5,
        generate_audio=False,
        generate_video=False,
        style="educational"
    )
    
    with patch("backend.api.merge.transcription_service") as mock_transcription:
        # Mock a Hindi transcript
        mock_transcription.get_transcript.return_value = [{"text": "namaste", "start": 0.0, "duration": 5.0}]
        mock_transcription.detect_language.return_value = "hi"
        
        with patch("backend.api.merge.update_status"):
            with patch("backend.api.merge.get_fusion_engine") as mock_fusion:
                with patch("backend.api.merge.SemanticSegment") as mock_seg:
                    with patch("backend.api.merge.concept_extractor") as mock_concept:
                        with patch("backend.api.merge.select_segments") as mock_select:
                            # Mock the selector to return empty to finish quickly
                            mock_result = MagicMock()
                            mock_result.segments = []
                            mock_result.selected_duration = 0
                            mock_result.total_duration = 0
                            mock_select.return_value = mock_result
                            
                            with patch("backend.api.merge.summary_metrics") as mock_metrics:
                                mock_metrics.evaluate_selection.return_value = {"score": 100}
                                # Execute
                                try:
                                    await process_merge_job(job_id, req)
                                except UnboundLocalError:
                                    pytest.fail("UnboundLocalError raised! _language_abort safety failed.")
                                except Exception:
                                    # Other exceptions might be raised due to mocking, but we specifically check for UnboundLocalError
                                    pass
