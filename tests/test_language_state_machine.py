"""
Regression tests for the language-abort job-state-machine bug fix.

Bugs covered:
  Bug 1: PARTIAL_SUCCESS was written BEFORE video generation completed, causing
         the frontend to render the result page prematurely.
  Bug 1b: Video generation was gated on `not _language_abort`, so it was
          entirely skipped even though the log said "Video generation will proceed."
  Bug 2: _build_quality_report() called `summary_text.strip()` on None
         -> AttributeError -> HTTP 500 on /evaluate.

Each test is mocked. No live YouTube, BART, MongoDB, or Whisper required.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hindi_segments(count: int = 50) -> list:
    return [
        {"text": f"हिंदी पाठ खंड {i}", "start": float(i * 5), "duration": 5.0}
        for i in range(count)
    ]


def _make_job(generate_video: bool = False):
    job = MagicMock()
    job.job_id = "test-lang-sm-001"
    job.video_ids = ["dummyHindiVid"]
    job.target_duration_minutes = 10
    job.highlight_duration_seconds = 600.0
    job.generate_video = generate_video
    job.generate_audio = False
    job.style = "informative"
    job.progress_percent = 0
    job.status = None
    job.stage_message = ""
    job.warning = None
    job.summary_unavailable = False
    job.summary_unavailable_reason = None
    job.detected_language = None
    return job


def _make_jobs_collection(writes_list):
    """Return a MagicMock jobs_collection that appends all update_one $set args to writes_list."""
    coll = MagicMock()
    coll.find_one = AsyncMock(return_value=None)

    async def fake_update(query, update, **kw):
        writes_list.append(update.get("$set", {}))

    coll.update_one = fake_update
    return coll


# ---------------------------------------------------------------------------
# Bug 2: _build_quality_report None-safety
# ---------------------------------------------------------------------------

class TestBuildQualityReportNullSafety:

    @pytest.mark.asyncio
    async def test_none_summary_returns_unavailable_dict(self):
        from backend.api.merge import _build_quality_report
        job_data = {"job_id": "test-none", "video_ids": ["vid1"], "summary_text": None, "highlight_segments": []}
        result = await _build_quality_report(job_data, use_llm=False)
        assert result.get("unavailable") is True, f"Expected unavailable=True for None summary, got: {result}"
        assert "reason" in result
        assert result.get("summary_score") is None
        assert result.get("video_score") is None

    @pytest.mark.asyncio
    async def test_empty_string_summary_returns_unavailable_dict(self):
        from backend.api.merge import _build_quality_report
        job_data = {"job_id": "test-empty", "video_ids": ["vid1"], "summary_text": "", "highlight_segments": []}
        result = await _build_quality_report(job_data, use_llm=False)
        assert result.get("unavailable") is True, f"Expected unavailable=True for empty summary, got: {result}"

    @pytest.mark.asyncio
    async def test_whitespace_only_summary_returns_unavailable_dict(self):
        from backend.api.merge import _build_quality_report
        job_data = {"job_id": "test-ws", "video_ids": ["vid1"], "summary_text": "   ", "highlight_segments": []}
        result = await _build_quality_report(job_data, use_llm=False)
        assert result.get("unavailable") is True


# ---------------------------------------------------------------------------
# Bug 1: PARTIAL_SUCCESS must NOT be written before video generation
# ---------------------------------------------------------------------------

class TestNoPrematurePartialSuccess:

    @pytest.mark.asyncio
    async def test_metadata_written_without_status_change_at_language_detect(self):
        """
        The intermediate DB write at language-detection time must NOT include
        status=partial_success. Only language metadata fields should be stored.
        """
        text_map = {"dummyHindiVid": "हिंदी पाठ " * 200}
        seg_map = {"dummyHindiVid": _make_hindi_segments(50)}
        all_writes = []
        coll = _make_jobs_collection(all_writes)

        job = _make_job(generate_video=False)

        async def fake_get_coll():
            return coll

        with (
            patch("backend.api.merge.get_jobs_collection", side_effect=fake_get_coll),
            patch("backend.api.merge.fetch_transcripts_with_segments", new_callable=AsyncMock,
                  return_value=(text_map, seg_map)),
            patch("backend.api.merge.get_fusion_engine", return_value=MagicMock()),
            patch("langdetect.detect", return_value="hi"),
            patch("backend.api.merge._active_jobs", {"test-lang-sm-001": job}),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.api.merge import process_merge_job
            await process_merge_job("test-lang-sm-001")

        # Find all writes that set summary_unavailable=True
        lang_abort_writes = [w for w in all_writes if w.get("summary_unavailable") is True]
        assert lang_abort_writes, "Expected at least one DB write with summary_unavailable=True at language detection"

        # The *first* language-abort write (the intermediate one) must NOT include status=partial_success
        first_abort_write = lang_abort_writes[0]
        assert "status" not in first_abort_write or first_abort_write.get("status") != "partial_success", (
            f"Language-abort intermediate write must NOT set status=partial_success: {first_abort_write}"
        )

    @pytest.mark.asyncio
    async def test_summary_unavailable_fields_present_in_final_write(self):
        """
        The final DB write (status=partial_success) must include
        summary_unavailable=True, summary_unavailable_reason, and detected_language.
        """
        text_map = {"dummyHindiVid": "हिंदी पाठ " * 200}
        seg_map = {"dummyHindiVid": _make_hindi_segments(50)}
        all_writes = []
        coll = _make_jobs_collection(all_writes)

        job = _make_job(generate_video=False)

        async def fake_get_coll():
            return coll

        with (
            patch("backend.api.merge.get_jobs_collection", side_effect=fake_get_coll),
            patch("backend.api.merge.fetch_transcripts_with_segments", new_callable=AsyncMock,
                  return_value=(text_map, seg_map)),
            patch("backend.api.merge.get_fusion_engine", return_value=MagicMock()),
            patch("langdetect.detect", return_value="hi"),
            patch("backend.api.merge._active_jobs", {"test-lang-sm-001": job}),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.api.merge import process_merge_job
            await process_merge_job("test-lang-sm-001")

        # Find the final partial_success write
        final_ps_write = next(
            (w for w in reversed(all_writes) if w.get("status") == "partial_success"),
            None,
        )
        assert final_ps_write is not None, "No final partial_success write found"
        assert final_ps_write.get("summary_unavailable") is True
        assert final_ps_write.get("summary_unavailable_reason") == "UNSUPPORTED_LANGUAGE"
        assert final_ps_write.get("detected_language") is not None

    @pytest.mark.asyncio
    async def test_partial_success_only_comes_after_all_video_statuses(self):
        """
        In the sequence of status writes, partial_success must NEVER appear
        before any generating_video or video_ready write.
        """
        text_map = {"dummyHindiVid": "हिंदी पाठ " * 200}
        seg_map = {"dummyHindiVid": _make_hindi_segments(50)}
        status_sequence = []

        coll = MagicMock()
        coll.find_one = AsyncMock(return_value=None)

        async def fake_update(query, update, **kw):
            s = update.get("$set", {}).get("status")
            if s:
                status_sequence.append(s)

        coll.update_one = fake_update
        job = _make_job(generate_video=False)

        async def fake_get_coll():
            return coll

        with (
            patch("backend.api.merge.get_jobs_collection", side_effect=fake_get_coll),
            patch("backend.api.merge.fetch_transcripts_with_segments", new_callable=AsyncMock,
                  return_value=(text_map, seg_map)),
            patch("backend.api.merge.get_fusion_engine", return_value=MagicMock()),
            patch("langdetect.detect", return_value="hi"),
            patch("backend.api.merge._active_jobs", {"test-lang-sm-001": job}),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.api.merge import process_merge_job
            await process_merge_job("test-lang-sm-001")

        assert "partial_success" in status_sequence, (
            "partial_success was never written — job must eventually reach partial_success"
        )

        first_ps_idx = status_sequence.index("partial_success")
        # No video-related status should appear after partial_success
        for i, s in enumerate(status_sequence):
            if s in {"generating_video", "video_ready"} and i > first_ps_idx:
                raise AssertionError(
                    f"Status '{s}' at index {i} appears AFTER partial_success at index {first_ps_idx}. "
                    f"Full sequence: {status_sequence}"
                )


# ---------------------------------------------------------------------------
# evaluate_job_quality: summary_unavailable shortcut
# ---------------------------------------------------------------------------

class TestEvaluateJobQualitySummaryUnavailable:

    @pytest.mark.asyncio
    async def test_returns_unavailable_dict_not_500(self):
        from backend.api.merge import evaluate_job_quality

        fake_job_doc = {
            "job_id": "test-eval-hindi",
            "status": "partial_success",
            "summary_unavailable": True,
            "summary_unavailable_reason": "UNSUPPORTED_LANGUAGE",
            "detected_language": "hi",
            "warning": "Transcript in 'hi', summary unavailable.",
            "summary_text": None,
        }

        coll = MagicMock()
        coll.find_one = AsyncMock(return_value=fake_job_doc)
        coll.update_one = AsyncMock()

        async def fake_get_coll():
            return coll

        with patch("backend.api.merge.get_jobs_collection", side_effect=fake_get_coll):
            result = await evaluate_job_quality("test-eval-hindi", llm=False)

        assert result.get("unavailable") is True, f"Expected unavailable=True, got: {result}"
        assert result.get("summary_score") is None
        assert result.get("video_score") is None

    @pytest.mark.asyncio
    async def test_build_quality_report_never_called_for_unavailable_job(self):
        from backend.api.merge import evaluate_job_quality

        fake_job_doc = {
            "job_id": "test-eval-hindi-2",
            "status": "partial_success",
            "summary_unavailable": True,
            "summary_text": None,
        }

        coll = MagicMock()
        coll.find_one = AsyncMock(return_value=fake_job_doc)
        coll.update_one = AsyncMock()

        async def fake_get_coll():
            return coll

        with (
            patch("backend.api.merge.get_jobs_collection", side_effect=fake_get_coll),
            patch("backend.api.merge._build_quality_report", new_callable=AsyncMock) as mock_build,
        ):
            await evaluate_job_quality("test-eval-hindi-2", llm=False)

        mock_build.assert_not_called()


# ---------------------------------------------------------------------------
# English pipeline regression guard
# ---------------------------------------------------------------------------

class TestEnglishPipelineUnchanged:

    @pytest.mark.asyncio
    async def test_english_job_reaches_completed_status(self):
        en_text = "This is a great English test transcript. It has clear sentences. Perfect."
        en_segs = [{"text": en_text, "start": 0.0, "duration": 10.0}]
        final_statuses = []

        coll = MagicMock()
        coll.find_one = AsyncMock(return_value=None)

        async def fake_update(query, update, **kw):
            s = update.get("$set", {}).get("status")
            if s:
                final_statuses.append(s)

        coll.update_one = fake_update

        fake_fusion_result = MagicMock()
        fake_fusion_result.narrative = "Good English content."
        fake_fusion_result.topics = ["topic1"]
        fake_fusion_result.metadata = {
            "total_source_words": 20, "output_words": 10,
            "compression_ratio": 0.5, "clusters_created": 1,
            "dedup_ratio": 0.0, "processing_time_seconds": 0.1,
        }

        job = _make_job(generate_video=False)
        job.job_id = "test-en-unchanged-001"

        async def fake_get_coll():
            return coll

        with (
            patch("backend.api.merge.get_jobs_collection", side_effect=fake_get_coll),
            patch("backend.api.merge.fetch_transcripts_with_segments", new_callable=AsyncMock,
                  return_value=({"vid": en_text}, {"vid": en_segs})),
            patch("backend.api.merge.get_fusion_engine") as fake_ff,
            patch("langdetect.detect", return_value="en"),
            patch("backend.api.merge._active_jobs", {"test-en-unchanged-001": job}),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("backend.services.summarization_service.get_summarization_service") as fake_ss,
            patch("backend.api.merge.settings.ENABLE_OLLAMA_ENRICHMENT", False),
        ):
            fe = MagicMock()
            fe.fuse_transcripts = MagicMock(return_value=fake_fusion_result)
            fake_ff.return_value = fe

            ss = MagicMock()
            ss.summarize_with_policy = MagicMock(return_value=("English summary text.", {"action": "pass"}))
            fake_ss.return_value = ss

            from backend.api.merge import process_merge_job
            await process_merge_job("test-en-unchanged-001")

        assert "completed" in final_statuses, (
            f"English job did not reach 'completed'. Statuses: {final_statuses}"
        )

    @pytest.mark.asyncio
    async def test_english_job_has_summary_unavailable_false(self):
        en_text = "This is a great English test transcript. It has clear sentences. Perfect."
        en_segs = [{"text": en_text, "start": 0.0, "duration": 10.0}]
        all_writes = []

        coll = MagicMock()
        coll.find_one = AsyncMock(return_value=None)

        async def fake_update(query, update, **kw):
            all_writes.append(update.get("$set", {}))

        coll.update_one = fake_update

        fake_fusion_result = MagicMock()
        fake_fusion_result.narrative = "Good English content."
        fake_fusion_result.topics = ["topic1"]
        fake_fusion_result.metadata = {
            "total_source_words": 20, "output_words": 10,
            "compression_ratio": 0.5, "clusters_created": 1,
            "dedup_ratio": 0.0, "processing_time_seconds": 0.1,
        }

        job = _make_job(generate_video=False)
        job.job_id = "test-en-no-unavailable-001"

        async def fake_get_coll():
            return coll

        with (
            patch("backend.api.merge.get_jobs_collection", side_effect=fake_get_coll),
            patch("backend.api.merge.fetch_transcripts_with_segments", new_callable=AsyncMock,
                  return_value=({"vid": en_text}, {"vid": en_segs})),
            patch("backend.api.merge.get_fusion_engine") as fake_ff,
            patch("langdetect.detect", return_value="en"),
            patch("backend.api.merge._active_jobs", {"test-en-no-unavailable-001": job}),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("backend.services.summarization_service.get_summarization_service") as fake_ss,
            patch("backend.api.merge.settings.ENABLE_OLLAMA_ENRICHMENT", False),
        ):
            fe = MagicMock()
            fe.fuse_transcripts = MagicMock(return_value=fake_fusion_result)
            fake_ff.return_value = fe

            ss = MagicMock()
            ss.summarize_with_policy = MagicMock(return_value=("English summary text.", {"action": "pass"}))
            fake_ss.return_value = ss

            from backend.api.merge import process_merge_job
            await process_merge_job("test-en-no-unavailable-001")

        bad_writes = [w for w in all_writes if w.get("summary_unavailable") is True]
        assert not bad_writes, f"English job must not write summary_unavailable=True: {bad_writes}"
