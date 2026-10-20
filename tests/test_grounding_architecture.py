"""
Grounding architecture regression tests.

Validates the Select-First → Summarize-Selected pipeline:

1. run_semantic_selection accepts semantic_bias_text.
2. process_merge_job can call it successfully.
3. semantic selection is actually executed (mock was called).
4. legacy scorer is NOT called when semantic selection raises a
   programmer/integration error (TypeError / AttributeError).
5. selected transcript is produced after semantic selection.
6. final summarization receives selected transcript, NOT the full transcript.
"""

import inspect
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from backend.api.merge import process_merge_job, run_semantic_selection
from backend.models.job import MergeJob


# ─── Helpers ────────────────────────────────────────────────────────────────

FULL_TEXT = (
    "Topic A is great. Topic B is ignored. "
    "Topic C is important. Topic D is skipped."
)

RAW_SEGMENTS = {
    "vid1": [
        {"text": "Topic A is great.", "start": 0, "duration": 5},
        {"text": "Topic B is ignored.", "start": 5, "duration": 5},
        {"text": "Topic C is important.", "start": 10, "duration": 5},
        {"text": "Topic D is skipped.", "start": 15, "duration": 5},
    ]
}

SELECTION_RESULT = {
    "highlights": [
        {"video_id": "vid1", "text": "Topic A is great.", "start_time": 0, "end_time": 5},
        {"video_id": "vid1", "text": "Topic C is important.", "start_time": 10, "end_time": 15},
    ],
    "concepts": [],
    "metrics": {},
    "trace": [],
}


def _make_job(job_id="test_grounding"):
    job = MergeJob(
        job_id=job_id,
        video_ids=["vid1"],
        target_duration_minutes=1,
        generate_video=True,
    )
    job.highlight_duration_seconds = 10
    job.style = "analytical"
    return job


def _make_db_mock(job_id="test_grounding", video_ids=None):
    db_mock = MagicMock()

    async def mock_find_one(*args, **kwargs):
        return {
            "job_id": job_id,
            "video_ids": video_ids or ["vid1"],
            "target_duration_minutes": 1,
            "highlight_duration_seconds": 10,
            "style": "analytical",
            "generate_video": True,
            "generate_audio": False,
            "include_sources": False,
        }

    async def mock_update_one(*args, **kwargs):
        pass

    db_mock.find_one.side_effect = mock_find_one
    db_mock.update_one.side_effect = mock_update_one
    return db_mock


# ─── Test 1 ── run_semantic_selection accepts semantic_bias_text ─────────────

def test_run_semantic_selection_accepts_semantic_bias_text():
    """
    REQUIREMENT 1: run_semantic_selection must accept semantic_bias_text.

    Inspect the actual signature — no mocks, no execution.
    """
    sig = inspect.signature(run_semantic_selection)
    assert "semantic_bias_text" in sig.parameters, (
        "run_semantic_selection does NOT accept 'semantic_bias_text'. "
        "The parameter is named incorrectly — this is the integration bug."
    )
    assert "summary_text" not in sig.parameters, (
        "run_semantic_selection still has the OLD 'summary_text' parameter. "
        "Rename it to 'semantic_bias_text' to match the caller."
    )


# ─── Shared integration fixture ───────────────────────────────────────────────

@pytest.fixture
def integration_mocks():
    """
    Patches every I/O-bound dependency so process_merge_job can run in-process.
    Yields a dict of the important mock objects for assertions.
    """
    mock_selection = AsyncMock(return_value=SELECTION_RESULT)

    mock_fusion = MagicMock()

    def side_effect_fuse(transcripts, *args, **kwargs):
        result = MagicMock()
        # Return whatever text was given — lets the test see which transcript
        # was passed to the second (selected) fusion call.
        result.narrative = " ".join(transcripts.values())
        result.topics = []
        result.metadata = {}
        return result

    mock_fusion.fuse_transcripts.side_effect = side_effect_fuse

    mock_summarizer = MagicMock()
    mock_summarizer.summarize_with_policy.side_effect = (
        lambda narrative, target, profile, *args, **kwargs: (narrative, "TEST_POLICY")
    )

    mock_rich = MagicMock()
    mock_rich.summary = "Topic A and Topic C summary"
    mock_rich.tldr = "Topic A and C TLDR"
    mock_rich.key_takeaways = ["Takeaway A", "Takeaway C"]
    mock_rich.chapters = ["Chapter A", "Chapter C"]

    video_svc = MagicMock()
    video_svc.download_videos = AsyncMock(return_value={"vid1": "/tmp/vid1.mp4"})
    video_svc.generate_highlight_reel = AsyncMock(return_value="/tmp/out.mp4")

    async def immediate_to_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    with (
        patch("backend.api.merge.fetch_transcripts_with_segments",
              return_value=({"vid1": FULL_TEXT}, RAW_SEGMENTS)),
        patch("backend.api.merge.run_semantic_selection", mock_selection),
        patch("backend.api.merge._generate_local_enrichment", return_value=mock_rich),
        patch("backend.api.merge.get_fusion_engine", return_value=mock_fusion),
        patch("backend.services.summarization_service.get_summarization_service",
              return_value=mock_summarizer),
        patch("backend.services.video_service.get_video_service",
              return_value=video_svc),
        patch("backend.api.merge.settings.ENABLE_SEMANTIC_SELECTION", True),
        patch("backend.api.merge.create_shadow_job_decisions", new_callable=AsyncMock, return_value=[]),
        patch("backend.api.merge.append_event", new_callable=AsyncMock),
        patch("backend.api.merge.finalize_shadow_manifest", new_callable=AsyncMock),
        patch("backend.api.merge._freeze_job_rights", new_callable=AsyncMock, return_value={}),
        patch("backend.services.vector_store.get_vector_store") as vector_store,
        patch("backend.services.manifest_boundary_repair.probe_rendered_duration", return_value=None),
        patch("backend.api.merge.asyncio.to_thread", side_effect=immediate_to_thread),
        patch("backend.api.merge.asyncio.sleep", new_callable=AsyncMock),
    ):
        vector_store.return_value.is_video_indexed.return_value = True
        yield {
            "selection": mock_selection,
            "fusion": mock_fusion,
            "summarizer": mock_summarizer,
            "enrich": mock_rich,
            "video_svc": video_svc,
        }


async def _run_job(job_id="test_grounding", video_ids=None):
    from backend.api.merge import _active_jobs
    job = _make_job(job_id)
    if video_ids:
        job.video_ids = list(video_ids)
    _active_jobs[job_id] = job
    with patch("backend.api.merge.get_jobs_collection",
               return_value=_make_db_mock(job_id, video_ids)):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await process_merge_job(job_id)
    return job


# ─── Test 2 ── process_merge_job can call run_semantic_selection successfully ─

@pytest.mark.asyncio
async def test_process_merge_job_calls_semantic_selection_successfully(integration_mocks):
    """
    REQUIREMENT 2: process_merge_job must invoke run_semantic_selection without
    raising an exception (the old bug raised TypeError immediately).
    """
    await _run_job()
    # If we reach here without an exception the call succeeded.
    assert integration_mocks["selection"].called, (
        "run_semantic_selection was never called — ENABLE_SEMANTIC_SELECTION "
        "may be False or the code path was not reached."
    )


@pytest.mark.parametrize("video_ids", [("vid1",), ("vid1", "vid2")])
@pytest.mark.asyncio
async def test_single_and_multi_video_merge_complete_without_ollama(video_ids, integration_mocks):
    text_map = {video_id: FULL_TEXT for video_id in video_ids}
    segment_map = {
        video_id: [dict(segment, video_id=video_id) for segment in RAW_SEGMENTS["vid1"]]
        for video_id in video_ids
    }
    job_id = f"test_no_ollama_{len(video_ids)}"

    with (
        patch("backend.api.merge.fetch_transcripts_with_segments",
              return_value=(text_map, segment_map)),
        patch("backend.api.merge.create_shadow_job_decisions", new_callable=AsyncMock, return_value=[]),
        patch("backend.api.merge._freeze_job_rights", new_callable=AsyncMock, return_value={}),
        patch.dict("sys.modules", {"backend.services.ollama_service": None}),
    ):
        job = await _run_job(job_id, video_ids)

    assert job.status.value == "completed"


# ─── Test 3 ── semantic selection is actually executed ───────────────────────

@pytest.mark.asyncio
async def test_semantic_selection_is_executed(integration_mocks):
    """
    REQUIREMENT 3: run_semantic_selection must be called exactly once per job,
    with the correct keyword argument name.
    """
    await _run_job()

    mock_sel = integration_mocks["selection"]
    assert mock_sel.call_count == 1, (
        f"Expected run_semantic_selection to be called once; got {mock_sel.call_count}"
    )

    call_kwargs = mock_sel.call_args.kwargs
    assert "semantic_bias_text" in call_kwargs, (
        f"run_semantic_selection was not called with 'semantic_bias_text'. "
        f"Got kwargs: {list(call_kwargs)}"
    )
    assert "summary_text" not in call_kwargs, (
        "Caller is still passing the OLD 'summary_text' keyword."
    )


# ─── Test 4 ── integration errors MUST NOT silently fall back ─────────────────

@pytest.mark.asyncio
async def test_integration_error_does_not_silently_fall_back_to_legacy(integration_mocks):
    """
    REQUIREMENT 4: If run_semantic_selection raises TypeError or AttributeError
    (programmer/integration bugs), process_merge_job MUST NOT silently route to
    the legacy scorer.  It must propagate as a hard error.
    """
    broken_selection = AsyncMock(
        side_effect=TypeError(
            "run_semantic_selection() got an unexpected keyword argument 'semantic_bias_text'"
        )
    )

    mock_legacy = AsyncMock(return_value=[])
    mock_fusion = MagicMock()
    mock_fusion.fuse_transcripts.return_value = MagicMock(
        narrative=FULL_TEXT, topics=[], metadata={}
    )

    video_svc = MagicMock()
    video_svc.download_videos = AsyncMock(return_value={"vid1": "/tmp/vid1.mp4"})
    video_svc.generate_highlight_reel = AsyncMock(return_value="/tmp/out.mp4")

    with (
        patch("backend.api.merge.fetch_transcripts_with_segments",
              return_value=({"vid1": FULL_TEXT}, RAW_SEGMENTS)),
        patch("backend.api.merge.run_semantic_selection", broken_selection),
        patch("backend.api.merge._legacy_select_highlights", mock_legacy),
        patch("backend.api.merge.get_fusion_engine", return_value=mock_fusion),
        patch("backend.services.video_service.get_video_service",
              return_value=video_svc),
        patch("backend.api.merge.settings.ENABLE_SEMANTIC_SELECTION", True),
        patch("backend.api.merge.asyncio.sleep", new_callable=AsyncMock),
    ):
        from backend.api.merge import _active_jobs
        _active_jobs["test_integration_err"] = _make_job("test_integration_err")
        with patch("backend.api.merge.get_jobs_collection",
                   return_value=_make_db_mock("test_integration_err")):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await process_merge_job("test_integration_err")
            # The job must complete in an error state — we check that the
            # legacy scorer was NOT called (i.e. no silent fallback).

    assert mock_legacy.call_count == 0, (
        "Legacy scorer was called after a TypeError in run_semantic_selection. "
        "Integration errors must NOT silently fall back — they must propagate "
        "so the test can detect the broken code path."
    )


# ─── Test 5 ── selected transcript is produced after semantic selection ───────

@pytest.mark.asyncio
async def test_selected_transcript_produced_after_semantic_selection(integration_mocks):
    """
    REQUIREMENT 5: After semantic selection returns 2 highlights (A and C),
    the second fusion call must receive ONLY the selected text, not the full
    transcript.
    """
    await _run_job()

    fusion_mock = integration_mocks["fusion"]
    assert fusion_mock.fuse_transcripts.call_count == 2, (
        f"Expected 2 fusion calls (baseline + selected); "
        f"got {fusion_mock.fuse_transcripts.call_count}"
    )

    # Second fusion call = selected segments only
    call2_kwargs = fusion_mock.fuse_transcripts.call_args_list[1][1]
    selected_text = call2_kwargs["transcripts"].get("vid1", "")

    assert "Topic A is great." in selected_text
    assert "Topic C is important." in selected_text
    assert "Topic B" not in selected_text, (
        "Topic B (discarded segment) leaked into the selected transcript."
    )
    assert "Topic D" not in selected_text, (
        "Topic D (discarded segment) leaked into the selected transcript."
    )


# ─── Test 6 ── summarizer receives ONLY selected transcript ──────────────────

@pytest.mark.asyncio
async def test_summarizer_receives_selected_transcript_not_full(integration_mocks):
    """
    REQUIREMENT 6: summarize_with_policy must be called with a narrative that
    contains ONLY selected topics (A and C), never the full transcript.
    """
    await _run_job()

    summarizer_mock = integration_mocks["summarizer"]
    assert summarizer_mock.summarize_with_policy.called, (
        "summarize_with_policy was never called."
    )

    narrative_passed = summarizer_mock.summarize_with_policy.call_args[0][0]

    assert "Topic A" in narrative_passed
    assert "Topic C" in narrative_passed
    assert "Topic B" not in narrative_passed, (
        "Full transcript leaked into summarization: Topic B should have been "
        "excluded by semantic selection."
    )
    assert "Topic D" not in narrative_passed, (
        "Full transcript leaked into summarization: Topic D should have been "
        "excluded by semantic selection."
    )


# ─── Consolidated end-to-end assertion (mirrors old test_grounding_architecture) ─

@pytest.mark.asyncio
async def test_grounding_architecture(integration_mocks):
    """
    End-to-end: confirms the full Select-First → Summarize-Selected pipeline
    runs correctly and both fusion calls carry the right text.
    """
    await _run_job()

    fusion_mock = integration_mocks["fusion"]
    summarizer_mock = integration_mocks["summarizer"]

    # Two fusion passes
    assert fusion_mock.fuse_transcripts.call_count == 2

    # First pass: full transcript
    call1_args = fusion_mock.fuse_transcripts.call_args_list[0][1]
    assert "Topic B is ignored." in call1_args["transcripts"]["vid1"]

    # Second pass: selected only
    call2_args = fusion_mock.fuse_transcripts.call_args_list[1][1]
    selected_text = call2_args["transcripts"]["vid1"]
    assert "Topic A is great." in selected_text
    assert "Topic C is important." in selected_text
    assert "Topic B" not in selected_text
    assert "Topic D" not in selected_text

    # Summarizer sees selected text
    sum_call = summarizer_mock.summarize_with_policy.call_args[0][0]
    assert "Topic B" not in sum_call
    assert "Topic D" not in sum_call
