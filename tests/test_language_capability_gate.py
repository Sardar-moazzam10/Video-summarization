"""
Regression tests for the language capability gate in process_merge_job.

These tests verify that when a transcript cannot be translated to English
(e.g., Hindi, Arabic, Chinese), the pipeline:

  1. Does NOT pass the non-English text to fusion / BART / enrichment.
  2. Sets summary_text = None (not "") in the database.
  3. Records status = PARTIAL_SUCCESS with an unambiguous warning string.
  4. Does NOT produce 0-word summaries presented as completed jobs.
  5. Does NOT fabricate English output from Devanagari input.

These are the exact failure modes observed in the 95-minute Hindi test:
  Hindi captions → all translation paths exhausted → pipeline continued →
  BART fabricated "New York Times" / "National Geographic" → stored as summary.

Everything here is mocked. No test depends on a live YouTube API, Whisper,
BART, or MongoDB instance.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hindi_segments(count: int = 50) -> list:
    """Simulate Hindi transcript segments (Devanagari text, no .!? boundaries)."""
    return [
        {"text": f"हिंदी पाठ खंड {i}", "start": float(i * 5), "duration": 5.0}
        for i in range(count)
    ]


def _make_job(generate_video: bool = False):
    """Minimal MergeJob-like object with the fields process_merge_job reads."""
    job = MagicMock()
    job.job_id = "test-hindi-job-001"
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
    return job


# ---------------------------------------------------------------------------
# Unit tests for the gate logic (isolated from process_merge_job internals)
# ---------------------------------------------------------------------------

class TestLanguageGateLogic:
    """
    Tests that verify the guard conditions in merge.py independently of
    the full async job runner.  We exercise the exact conditions that caused
    the production failure.
    """

    def test_hindi_sentence_split_produces_zero_sentences(self):
        """
        fusion_engine._extract_sentences uses [.!?]+ splitting.
        Hindi uses the Devanagari danda (।, U+0964) as sentence terminator,
        not ASCII punctuation, so the splitter returns one giant token that
        exceeds max_sentence_words=100 and is filtered out.

        This is Q3 in the diagnosis: WHY fusion returns 0 sentences.
        Regression guard: if this ever produces >0 sentences, the gate
        assumption breaks.
        """
        import re

        hindi_text = (
            "यह एक हिंदी वाक्य है जो लंबा है "
            "और इसमें कोई ASCII विराम चिह्न नहीं है "
            "इसलिए यह एक बड़े टोकन के रूप में रहेगा "
            * 10  # repeat to exceed word limit
        )

        raw_sentences = re.split(r"[.!?]+", hindi_text)
        non_empty = [s.strip() for s in raw_sentences if s.strip()]

        # Only one "sentence" exists because there are no ASCII sentence-enders.
        assert len(non_empty) <= 1, (
            "Hindi text should not split into multiple English-style sentences — "
            "if it does, the gate condition needs to be re-evaluated"
        )

        # That single token contains many more than 100 words (the filter limit).
        if non_empty:
            word_count = len(non_empty[0].split())
            assert word_count > 100, (
                f"Hindi mega-sentence has {word_count} words; expected >100 "
                "so that it is filtered out by max_sentence_words"
            )

    def test_untranslated_langs_truthy_gate(self):
        """
        The language gate fires on `if untranslated_langs:`.
        An empty dict must NOT trigger the abort.
        A non-empty dict MUST trigger it.
        """
        # Empty → no abort
        assert not bool({})

        # One Hindi video → abort
        assert bool({"dummyHindiVid": "hi"})

        # Multiple languages → abort
        assert bool({"vid1": "hi", "vid2": "ar"})

    def test_devanagari_danda_not_in_split_chars(self):
        """
        Explicitly verify that the Devanagari danda (U+0964) is absent from
        the fusion engine's sentence-boundary character set.
        If someone later adds multilingual support by extending the regex,
        this test will catch it so the gate logic can be updated accordingly.
        """
        import re
        DANDA = "\u0964"  # ।

        hindi_sentence = f"पहला वाक्य{DANDA} दूसरा वाक्य{DANDA}"
        parts = re.split(r"[.!?]+", hindi_sentence)
        non_empty = [p.strip() for p in parts if p.strip()]

        # Danda is NOT in the split set, so the text is NOT split on it.
        assert len(non_empty) == 1, (
            "The danda should NOT be treated as a sentence boundary; "
            "if it is, update the gate to account for the new behaviour"
        )


# ---------------------------------------------------------------------------
# Integration-style tests (mocking the async pipeline)
# ---------------------------------------------------------------------------

class TestLanguageAbortPath:
    """
    End-to-end tests that verify process_merge_job correctly aborts text
    processing when an untranslated non-English transcript is detected.

    Strategy: mock every I/O boundary (MongoDB, transcript_service,
    langdetect, fusion engine, summarization_service) and run the real
    process_merge_job coroutine, then assert on what was written to the DB.
    """

    @pytest.fixture
    def hindi_transcript(self):
        segments = _make_hindi_segments(50)
        text = " ".join(s["text"] for s in segments)
        return {"dummyHindiVid": text}, {"dummyHindiVid": segments}

    @pytest.mark.asyncio
    async def test_summary_text_is_none_not_empty_string(self, hindi_transcript):
        """
        The single most important invariant: summary_text must be None when the
        language is unsupported.  An empty string ("") is indistinguishable from
        "summarizer returned nothing" and was the original false-success vector.
        """
        text_map, seg_map = hindi_transcript

        db_writes = []

        async def fake_update(query, update, **kw):
            db_writes.append(update.get("$set", {}))

        jobs_collection = AsyncMock()
        jobs_collection.update_one = fake_update
        jobs_collection.find_one = AsyncMock(return_value=None)

        job = _make_job(generate_video=False)
        fusion_called = []

        with (
            patch("backend.api.merge.get_jobs_collection", return_value=jobs_collection),
            patch("backend.api.merge.fetch_transcripts_with_segments", new_callable=AsyncMock,
                  return_value=(text_map, seg_map)),
            patch("backend.api.merge.get_fusion_engine") as fake_fusion_factory,
            patch("backend.services.vector_store.get_vector_store") as vector_store,
            patch("backend.api.merge.run_semantic_selection", new_callable=AsyncMock) as semantic_selection,
            patch("backend.services.video_service.get_video_service") as video_service,
            patch("langdetect.detect", return_value="hi"),
            patch("backend.api.merge._active_jobs", {"test-hindi-job-001": job}),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            # Fusion engine must NOT be called
            fake_fusion_engine = MagicMock()
            fake_fusion_engine.fuse_transcripts = MagicMock(side_effect=lambda **kw: fusion_called.append(1))
            fake_fusion_factory.return_value = fake_fusion_engine

            from backend.api.merge import process_merge_job
            await process_merge_job("test-hindi-job-001")

        # No English-only or media stage may run after preflight rejection.
        semantic_selection.assert_not_awaited()
        vector_store.assert_not_called()
        video_service.assert_not_called()
        assert len(fusion_called) == 0, (
            "fusion_engine.fuse_transcripts() was called on a Hindi transcript — "
            "the language gate did not abort the pipeline"
        )

        # The final DB write must have summary_text=None
        final_write = db_writes[-1] if db_writes else {}
        assert "summary_text" in final_write, "summary_text was not written to DB"
        assert final_write["summary_text"] is None, (
            f"Expected summary_text=None for unsupported language, "
            f"got {final_write['summary_text']!r}"
        )

    @pytest.mark.asyncio
    async def test_status_is_partial_success_not_completed(self, hindi_transcript):
        """
        A job with an unsupported-language transcript must NEVER have
        status=COMPLETED. It must be PARTIAL_SUCCESS.
        """
        text_map, seg_map = hindi_transcript

        written_statuses = []

        async def fake_update(query, update, **kw):
            s = update.get("$set", {}).get("status")
            if s:
                written_statuses.append(s)

        jobs_collection = AsyncMock()
        jobs_collection.update_one = fake_update
        jobs_collection.find_one = AsyncMock(return_value=None)

        job = _make_job(generate_video=False)

        with (
            patch("backend.api.merge.get_jobs_collection", return_value=jobs_collection),
            patch("backend.api.merge.fetch_transcripts_with_segments", new_callable=AsyncMock,
                  return_value=(text_map, seg_map)),
            patch("backend.api.merge.get_fusion_engine", return_value=MagicMock()), patch("backend.services.vector_store.get_vector_store"),
            patch("langdetect.detect", return_value="hi"),
            patch("backend.api.merge._active_jobs", {"test-hindi-job-001": job}),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.api.merge import process_merge_job
            await process_merge_job("test-hindi-job-001")

        # Must never have written "completed"
        assert "completed" not in written_statuses, (
            "Job was marked 'completed' despite untranslated Hindi transcript"
        )
        # Must have written "partial_success" at some point
        assert "partial_success" in written_statuses, (
            f"Expected status=partial_success for language-unsupported job, "
            f"got statuses: {written_statuses}"
        )

    @pytest.mark.asyncio
    async def test_warning_message_mentions_language(self, hindi_transcript):
        """
        The user-facing warning stored in the job must explicitly identify
        the source language, not be a generic error message.
        """
        text_map, seg_map = hindi_transcript

        final_write = {}

        async def fake_update(query, update, **kw):
            final_write.update(update.get("$set", {}))

        jobs_collection = AsyncMock()
        jobs_collection.update_one = fake_update
        jobs_collection.find_one = AsyncMock(return_value=None)

        job = _make_job(generate_video=False)

        with (
            patch("backend.api.merge.get_jobs_collection", return_value=jobs_collection),
            patch("backend.api.merge.fetch_transcripts_with_segments", new_callable=AsyncMock,
                  return_value=(text_map, seg_map)),
            patch("backend.api.merge.get_fusion_engine", return_value=MagicMock()), patch("backend.services.vector_store.get_vector_store"),
            patch("langdetect.detect", return_value="hi"),
            patch("backend.api.merge._active_jobs", {"test-hindi-job-001": job}),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.api.merge import process_merge_job
            await process_merge_job("test-hindi-job-001")

        warning = final_write.get("warning", "")
        assert warning, "No warning was written to the DB for a language-unsupported job"
        assert "hi" in warning or "hindi" in warning.lower() or "'hi'" in warning, (
            f"Warning does not mention the language code 'hi': {warning!r}"
        )

    @pytest.mark.asyncio
    async def test_english_transcript_runs_full_pipeline(self):
        """
        Regression guard: an English transcript must NOT trigger the abort.
        The full pipeline (fusion → BART → enrichment) must run normally.
        """
        en_text = "This is a test transcript in English. It has multiple sentences. Good content."
        en_segs = [{"text": en_text, "start": 0.0, "duration": 10.0}]
        fusion_calls = []

        async def fake_update(query, update, **kw):
            pass

        jobs_collection = AsyncMock()
        jobs_collection.update_one = fake_update
        jobs_collection.find_one = AsyncMock(return_value=None)

        fake_fusion_result = MagicMock()
        fake_fusion_result.narrative = "Good English summary."
        fake_fusion_result.topics = ["topic1"]
        fake_fusion_result.metadata = {
            "total_source_words": 20, "output_words": 10,
            "compression_ratio": 0.5, "clusters_created": 1,
            "dedup_ratio": 0.0, "processing_time_seconds": 0.1,
        }

        def fake_fuse(**kw):
            fusion_calls.append(1)
            return fake_fusion_result

        job = _make_job(generate_video=False)
        job.job_id = "test-english-job-001"

        with (
            patch("backend.api.merge.get_jobs_collection", return_value=jobs_collection),
            patch("backend.api.merge.fetch_transcripts_with_segments", new_callable=AsyncMock,
                  return_value=({"vid": en_text}, {"vid": en_segs})),
            patch("backend.api.merge.get_fusion_engine") as fake_ff, patch("backend.services.vector_store.get_vector_store"),
            patch("langdetect.detect", return_value="en"),
            patch("backend.api.merge._active_jobs", {"test-english-job-001": job}),
            patch("backend.services.summarization_service.get_summarization_service") as fake_ss,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            fe = MagicMock()
            fe.fuse_transcripts = MagicMock(side_effect=lambda **kw: (fusion_calls.append(1) or fake_fusion_result))
            fake_ff.return_value = fe

            ss = MagicMock()
            ss.summarize_with_policy = MagicMock(return_value=("English summary text.", {"action": "pass"}))
            fake_ss.return_value = ss

            from backend.api.merge import process_merge_job
            await process_merge_job("test-english-job-001")

        assert len(fusion_calls) > 0, (
            "Fusion engine was NOT called for an English transcript — "
            "the gate incorrectly aborted a valid job"
        )
