"""
Merge API Routes - Video fusion and summarization endpoints

Endpoints:
- POST /api/v1/merge - Create new merge job
- GET /api/v1/merge/{job_id} - Get job status
- GET /api/v1/merge/{job_id}/result - Get completed job result (with rich_output)
- GET /api/v1/merge/{job_id}/audio - Download audio MP3
- GET /api/v1/merge/{job_id}/subtitles - Download SRT subtitles
- GET /api/v1/merge/{job_id}/export?format=text|pdf - Export summary
- GET /api/v1/merge/{job_id}/stream - SSE progress stream
- GET /api/v1/merge/profiles - Get available duration profiles
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from typing import Dict, List, Optional
import asyncio
import json
from datetime import datetime
import os

from ..models.job import (
    MergeJobCreate,
    MergeJob,
    MergeJobResponse,
    JobStatus,
    FusionMetadata,
    RichOutput,
    get_duration_style,
)
from ..services.duration_profiles import (
    DURATION_PROFILES, get_all_profiles, get_profile,
)
from ..services.media_probe import format_duration, get_durations
from ..services.transcript_service import extract_video_id
from ..services.fusion_engine import get_fusion_engine
from ..core.database import get_database
from ..core.config import get_settings

router = APIRouter(prefix="/api/v1/merge", tags=["merge"])
settings = get_settings()


# =====================================================
# LOCAL ENRICHMENT FALLBACK (used when Ollama is unavailable)
# =====================================================

def _extract_top_sentences(sentences: list, n: int = 5) -> list:
    """Extract top-N sentences by TF-IDF importance score."""
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer

    if len(sentences) <= n:
        return sentences
    try:
        vec = TfidfVectorizer(stop_words='english', max_features=300)
        matrix = vec.fit_transform(sentences)
        scores = np.asarray(matrix.sum(axis=1)).flatten()
        top_idx = scores.argsort()[::-1][:n]
        # Return in original order for readability
        return [sentences[i] for i in sorted(top_idx)]
    except Exception:
        return sentences[:n]


def _generate_local_enrichment(summary_text: str, style: str) -> RichOutput:
    """
    Generate basic structured output (TLDR, key takeaways, chapters)
    from the BART summary text when Ollama is unavailable.

    Uses: first-2-sentences for TLDR, TF-IDF for takeaways,
    even splits for chapters. No new models required.
    """
    import re

    sentences = [
        s.strip()
        for s in re.split(r'(?<=[.!?])\s+', summary_text.strip())
        if len(s.split()) >= 6
    ]

    if not sentences:
        return RichOutput(summary=summary_text, style_applied=style)

    # TLDR: first 2 sentences
    tldr = ' '.join(sentences[:2])

    # Key Takeaways: top-5 TF-IDF sentences
    takeaways = _extract_top_sentences(sentences, n=5)

    # Chapters: divide sentences into 3 equal sections
    n = len(sentences)
    third = max(1, n // 3)
    chapter_groups = [
        sentences[:third],
        sentences[third:2 * third],
        sentences[2 * third:],
    ]
    chapters = []
    chapter_titles = ["Introduction & Overview", "Core Discussion", "Conclusions & Key Points"]
    for title, group in zip(chapter_titles, chapter_groups):
        if group:
            chapters.append({"title": title, "text": ' '.join(group)})

    print(f"[LocalEnrich] Generated TLDR ({len(tldr.split())}w), "
          f"{len(takeaways)} takeaways, {len(chapters)} chapters")

    return RichOutput(
        summary=summary_text,
        tldr=tldr,
        key_takeaways=takeaways,
        chapters=chapters,
        style_applied=style,
    )


# =====================================================
# IN-MEMORY JOB TRACKING (for quick access)
# Jobs are also persisted to MongoDB
# =====================================================
_active_jobs: Dict[str, MergeJob] = {}


async def get_jobs_collection():
    """Get MongoDB jobs collection."""
    db = await get_database()
    return db["jobs"]


# =====================================================
# ENDPOINTS
# =====================================================

@router.get("/profiles")
async def get_duration_profiles():
    """
    Get available duration profiles for frontend display.

    Returns list of duration options with descriptions.
    """
    return {
        "profiles": get_all_profiles(),
        "default": settings.DEFAULT_DURATION_MINUTES,
        "min": settings.MIN_DURATION_MINUTES,
        "max": settings.MAX_DURATION_MINUTES,
    }


def eligible_durations(source_seconds: float) -> List[int]:
    """
    Which duration profiles a source of this length can actually produce.

    A summary cannot be longer than the material it is made from — asking for
    30 minutes of highlights from a 5-minute video is not a preference the
    optimizer can satisfy, it is an impossible request.

    Shared by the validation path and the endpoint the picker reads, so the
    disabled options in the UI and the ones the API rejects are computed by the
    same function and cannot drift apart.
    """
    return [m for m in sorted(DURATION_PROFILES) if m * 60 <= source_seconds]


def _duration_error(source_seconds: float, requested_minutes: int) -> Dict:
    """The SUMMARY_DURATION_EXCEEDS_VIDEO payload, in one place."""
    allowed = eligible_durations(source_seconds)
    pretty = format_duration(source_seconds)
    if allowed:
        message = (
            f"This video is only {pretty} long. "
            f"Please choose {max(allowed)} minutes or less."
        )
    else:
        shortest = min(DURATION_PROFILES)
        message = (
            f"This video is only {pretty} long — shorter than the smallest "
            f"summary length ({shortest} minutes), so it cannot be summarised."
        )
    return {
        "error_code": "SUMMARY_DURATION_EXCEEDS_VIDEO",
        "message": message,
        "source_duration_seconds": round(float(source_seconds), 1),
        "requested_duration_minutes": int(requested_minutes),
        "max_allowed_minutes": max(allowed) if allowed else None,
        "allowed_durations": allowed,
    }


@router.get("/video-durations")
async def get_video_durations(video_ids: str):
    """
    Real media duration for each requested video, and which summary lengths
    that makes possible.

    The picker calls this once the user's selection is known so it can disable
    the impossible options with a reason, instead of letting them start a job
    that the API will refuse. Comma-separated ids, e.g.
    `/video-durations?video_ids=abc123,def456`.

    Frontend use is a convenience only — create_merge_job re-checks this
    server-side, so a client that skips or fakes the call gains nothing.
    """
    ids = [v.strip() for v in (video_ids or "").split(",") if v.strip()]
    if not ids:
        raise HTTPException(400, "At least one video_id is required")
    if len(ids) > 10:
        raise HTTPException(400, "Maximum 10 videos allowed")

    resolved = await asyncio.to_thread(get_durations, ids)
    known = [d for d in resolved.values() if d]
    # Combined, because _allocate_budgets splits the reel across every source
    # in proportion to its length — the material available is the pool, not
    # any single video. Matching that here keeps validation and production
    # behaviour consistent for multi-video jobs.
    combined = float(sum(known)) if known else 0.0

    return {
        "durations": {vid: (round(d, 1) if d else None) for vid, d in resolved.items()},
        "unresolved": [vid for vid, d in resolved.items() if not d],
        "combined_duration_seconds": round(combined, 1),
        "combined_duration_label": format_duration(combined) if combined else None,
        "allowed_durations": eligible_durations(combined) if known else sorted(DURATION_PROFILES),
        "all_durations": sorted(DURATION_PROFILES),
    }


@router.post("", response_model=MergeJobResponse)
async def create_merge_job(
    request: MergeJobCreate,
    background_tasks: BackgroundTasks,
):
    """
    Create a new merge job.

    The job will be processed in the background.
    Use GET /merge/{job_id} to check status.
    """
    # Validate video count
    if len(request.video_ids) < 1:
        raise HTTPException(400, "At least 1 video required")
    if len(request.video_ids) > 10:
        raise HTTPException(400, "Maximum 10 videos allowed")

    # Duration feasibility — checked BEFORE the job exists, because everything
    # after this point is expensive (download, transcribe, embed, summarise)
    # and an impossible request cannot be rescued by any of it. The user is
    # told no rather than being silently given a shorter summary than the one
    # they asked for.
    #
    # Enforced here rather than only in the picker: this is the boundary a
    # client cannot bypass.
    clean_ids = [extract_video_id(v) for v in request.video_ids]
    resolved = await asyncio.to_thread(get_durations, clean_ids)
    known = [d for d in resolved.values() if d]

    if not known:
        # Unknown length is not permission to proceed. Running the pipeline
        # would spend minutes to maybe discover the same problem later.
        raise HTTPException(422, detail={
            "error_code": "SOURCE_DURATION_UNAVAILABLE",
            "message": (
                "Could not determine how long the selected video(s) are, so the "
                "requested summary length cannot be verified. Please try again."
            ),
            "requested_duration_minutes": request.target_duration_minutes,
            "unresolved_video_ids": [v for v, d in resolved.items() if not d],
        })

    combined = float(sum(known))
    if request.target_duration_minutes * 60 > combined:
        raise HTTPException(422, detail=_duration_error(
            combined, request.target_duration_minutes
        ))

    # The reel IS the output, so the user's chosen length drives it directly.
    # Previously target_duration_minutes only sized the TTS script and the reel
    # inherited whatever length that narration happened to be; with TTS gone the
    # two settings collapse into one. An explicit highlight_duration_seconds is
    # still honoured for callers that want the reel to differ from the summary.
    reel_seconds = request.highlight_duration_seconds
    if reel_seconds == 120:  # untouched default → follow the duration picker
        # 1800 = the 30-minute "Comprehensive Summary" ceiling.
        reel_seconds = min(request.target_duration_minutes * 60, 1800)

    # Create job
    job = MergeJob(
        video_ids=request.video_ids,
        target_duration_minutes=request.target_duration_minutes,
        duration_style=get_duration_style(request.target_duration_minutes),
        generate_audio=request.generate_audio,
        generate_video=request.generate_video,
        highlight_duration_seconds=reel_seconds,
        style=request.style,
    )

    # Store in memory and database
    _active_jobs[job.job_id] = job

    jobs_collection = await get_jobs_collection()
    await jobs_collection.insert_one(job.model_dump())

    # Start background processing
    background_tasks.add_task(process_merge_job, job.job_id)

    # Estimate time (rough: 30s per video + 60s for fusion)
    estimated_seconds = len(request.video_ids) * 30 + 60

    return MergeJobResponse(
        job_id=job.job_id,
        status=job.status,
        progress_percent=job.progress_percent,
        stage_message=job.stage_message,
        estimated_seconds=estimated_seconds,
    )


@router.get("/{job_id}", response_model=MergeJobResponse)
async def get_job_status(job_id: str):
    """
    Get current status of a merge job.

    Poll this endpoint to track progress.
    """
    # Check memory first
    if job_id in _active_jobs:
        job = _active_jobs[job_id]
        return MergeJobResponse(
            job_id=job.job_id,
            status=job.status,
            progress_percent=job.progress_percent,
            stage_message=job.stage_message,
            error=job.error,
            warning=job.warning,
        )

    # Check database
    jobs_collection = await get_jobs_collection()
    job_data = await jobs_collection.find_one({"job_id": job_id})

    if not job_data:
        raise HTTPException(404, "Job not found")

    return MergeJobResponse(
        job_id=job_data["job_id"],
        status=job_data["status"],
        progress_percent=job_data["progress_percent"],
        stage_message=job_data["stage_message"],
        error=job_data.get("error"),
        warning=job_data.get("warning"),
    )


@router.get("/{job_id}/result")
async def get_job_result(job_id: str):
    """
    Get the result of a completed merge job.

    Only available when status is 'completed'.
    """
    jobs_collection = await get_jobs_collection()
    job_data = await jobs_collection.find_one({"job_id": job_id})

    if not job_data:
        raise HTTPException(404, "Job not found")

    if job_data["status"] not in {JobStatus.COMPLETED.value, JobStatus.PARTIAL_SUCCESS.value}:
        raise HTTPException(
            400,
            f"Job not completed. Current status: {job_data['status']}"
        )

    return {
        "job_id": job_data["job_id"],
        "status": job_data["status"],
        "summary_text": job_data.get("summary_text", ""),
        "rich_output": job_data.get("rich_output"),
        "audio_url": f"/api/v1/merge/{job_id}/audio" if job_data.get("audio_path") else None,
        "video_url": f"/api/v1/merge/{job_id}/video" if job_data.get("video_path") else None,
        "subtitle_url": f"/api/v1/merge/{job_id}/subtitles" if job_data.get("subtitle_path") else None,
        "video_ids": job_data.get("video_ids", []),
        # Echoed back so a follow-up job (e.g. the highlight re-compile on the
        # player page) can reuse this job's settings instead of hardcoding them.
        "target_duration_minutes": job_data.get("target_duration_minutes"),
        "highlight_segments": job_data.get("highlight_segments", []),
        "keyframes_extracted": job_data.get("keyframes_extracted", {}),
        # Semantic pipeline output. Absent on jobs produced before this
        # pipeline existed, so the frontend must treat all of it as optional.
        "concepts": job_data.get("concepts", []),
        "selection_metrics": job_data.get("selection_metrics"),
        "selection_trace": job_data.get("selection_trace", []),
        "summarization_decision": job_data.get("summarization_decision"),
        "selection_mode": job_data.get("selection_mode", "legacy"),
        "warning": job_data.get("warning"),
        "error": job_data.get("error"),
        "metadata": job_data.get("fusion_metadata", {}),
        "created_at": job_data["created_at"],
        "completed_at": job_data.get("completed_at"),
    }


@router.get("/{job_id}/evaluate")
async def evaluate_job_quality(job_id: str, llm: bool = False):
    """
    Quality scorecard for a completed job — two separate scores:

      check_a (summary side): is the AI summary a faithful summary of the
          original video(s)?  (summary vs original transcript)
      check_b (video side): do the generated highlight clips represent the
          summary?  (clip transcripts vs summary) — expected to be high.

    The result is cached on the job document, and the pipeline precomputes the
    llm=false scorecard as soon as a job completes, so this is normally a read.

    Query params:
        llm=false (default): keyword + SBERT coverage. Roughly 100s to compute
                             for a 25-minute video — the earlier "<1s" here was
                             wrong by two orders of magnitude, which is how the
                             event-loop stall it caused went unnoticed. Cached
                             after the first run.
        llm=true           : also runs the Ollama judge (30-90s on top).
                             Use for the on-demand "detailed analysis" button.
    """
    jobs_collection = await get_jobs_collection()
    job_data = await jobs_collection.find_one({"job_id": job_id})

    if not job_data:
        raise HTTPException(404, "Job not found")

    if job_data["status"] not in {JobStatus.COMPLETED.value, JobStatus.PARTIAL_SUCCESS.value}:
        raise HTTPException(400, f"Job not completed. Current status: {job_data['status']}")

    cache_field = _QUALITY_CACHE_FIELD_LLM if llm else _QUALITY_CACHE_FIELD
    cached = job_data.get(cache_field)
    if cached:
        return cached

    report = await _build_quality_report(job_data, use_llm=bool(llm))
    await jobs_collection.update_one({"job_id": job_id}, {"$set": {cache_field: report}})
    return report


# Where a computed scorecard is parked on the job document. A completed job is
# immutable, so its scores are too — recomputing them per page view is pure cost.
_QUALITY_CACHE_FIELD = "quality_report"
_QUALITY_CACHE_FIELD_LLM = "quality_report_llm"


def _run_coroutine_blocking(coro):
    """Drive a coroutine to completion on its own loop. For use inside a thread."""
    return asyncio.run(coro)


async def _build_quality_report(job_data: dict, use_llm: bool) -> dict:
    """
    Score a completed job: summary-vs-transcript and clips-vs-summary.

    The scoring is CPU-bound — it SBERT-embeds the transcript chunks and the
    summary sentences twice over, measured at 103 seconds for a 25-minute
    video. It used to run directly on the event loop, and because this is an
    `async def` endpoint that meant the entire backend stopped answering for
    the duration: /health, /video and /audio range requests included. Opening a
    finished job from History therefore looked like a broken player — the reel
    would not start until the scoring finished, whether or not the machine was
    online. The work runs in a worker thread now so everything else keeps
    serving while it computes.
    """
    summary_text = job_data.get("summary_text", "")
    if not summary_text.strip():
        raise HTTPException(400, "Job has no summary to evaluate")

    # Reuse the same transcript fetch the pipeline uses (cached in MongoDB)
    video_ids = job_data.get("video_ids", [])
    _, segments_map = await fetch_transcripts_with_segments(video_ids)
    transcript_segments = []
    for segs in segments_map.values():
        transcript_segments.extend(segs)

    if not transcript_segments:
        raise HTTPException(400, "Original transcript unavailable — cannot evaluate")

    # The selected highlight clips carry their transcript text (Check B input)
    clips = job_data.get("highlight_segments", []) or []

    # Import the standalone evaluator's scoring logic (single source of truth)
    import sys as _sys
    import os as _os
    _root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    from evaluate_summary import evaluate as _evaluate

    report = await asyncio.to_thread(
        _run_coroutine_blocking,
        _evaluate(
            transcript_segments=transcript_segments,
            summary_text=summary_text,
            clips=clips,
            use_llm=use_llm,
        ),
    )

    # Frontend-friendly shape: two scores + the detail blocks
    return {
        "job_id": job_data.get("job_id"),
        "llm_used": use_llm,
        "summary_score": report["check_a"]["score"],
        "video_score": report["check_b"]["score"],
        "check_a": report["check_a"],
        "check_b": report["check_b"],
        "source_words": report["source_words"],
        "summary_words": report["summary_words"],
        "num_clips": report["num_clips"],
    }


@router.get("/{job_id}/audio")
async def get_job_audio(job_id: str):
    """
    Get the generated audio file for a completed job.
    """
    jobs_collection = await get_jobs_collection()
    job_data = await jobs_collection.find_one({"job_id": job_id})

    if not job_data:
        raise HTTPException(404, "Job not found")

    audio_path = job_data.get("audio_path")
    if not audio_path or not os.path.exists(audio_path):
        raise HTTPException(404, "Audio not available")

    return FileResponse(
        audio_path,
        media_type="audio/mpeg",
        filename=f"summary_{job_id}.mp3"
    )


@router.get("/{job_id}/video")
async def get_job_video(job_id: str):
    """
    Download the generated highlight reel video.
    """
    jobs_collection = await get_jobs_collection()
    job_data = await jobs_collection.find_one({"job_id": job_id})

    if not job_data:
        raise HTTPException(404, "Job not found")

    video_path = job_data.get("video_path")
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(404, "Video highlight reel not available")

    return FileResponse(
        video_path,
        media_type="video/mp4",
        filename=f"highlights_{job_id}.mp4"
    )


@router.get("/{job_id}/subtitles")
async def get_job_subtitles(job_id: str):
    """Download SRT subtitle file for a completed job."""
    jobs_collection = await get_jobs_collection()
    job_data = await jobs_collection.find_one({"job_id": job_id})

    if not job_data:
        raise HTTPException(404, "Job not found")

    subtitle_path = job_data.get("subtitle_path")
    if not subtitle_path or not os.path.exists(subtitle_path):
        raise HTTPException(404, "Subtitles not available")

    return FileResponse(
        subtitle_path,
        media_type="application/x-subrip",
        filename=f"summary_{job_id}.srt"
    )


@router.get("/{job_id}/export")
async def export_job(job_id: str, format: str = "text"):
    """
    Export summary as text or PDF.

    Query params:
        format: "text" or "pdf"
    """
    jobs_collection = await get_jobs_collection()
    job_data = await jobs_collection.find_one({"job_id": job_id})

    if not job_data:
        raise HTTPException(404, "Job not found")

    if job_data["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(400, "Job not completed")

    summary_text = job_data.get("summary_text", "")
    rich_output = job_data.get("rich_output")

    from ..services.export_service import format_as_text, generate_pdf

    if format == "pdf":
        pdf_bytes = bytes(generate_pdf(summary_text, rich_output))
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=summary_{job_id}.pdf"}
        )
    else:
        text = format_as_text(summary_text, rich_output)
        return StreamingResponse(
            iter([text.encode("utf-8")]),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=summary_{job_id}.txt"}
        )


@router.get("/{job_id}/stream")
async def stream_job_progress(job_id: str):
    """
    SSE endpoint for real-time job progress.
    The browser connects once and receives updates every ~1 second.
    Closes automatically when the job completes or errors.
    """
    async def event_generator():
        while True:
            job = _active_jobs.get(job_id)

            if job:
                data = {
                    "status": job.status.value if hasattr(job.status, "value") else job.status,
                    "progress_percent": job.progress_percent,
                    "stage_message": job.stage_message,
                }
            else:
                # Fallback: check database
                jobs_collection = await get_jobs_collection()
                job_data = await jobs_collection.find_one({"job_id": job_id})
                if not job_data:
                    yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
                    return
                data = {
                    "status": job_data["status"],
                    "progress_percent": job_data["progress_percent"],
                    "stage_message": job_data["stage_message"],
                }

            yield f"data: {json.dumps(data)}\n\n"

            if data["status"] in ("completed", "error"):
                return

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =====================================================
# HELPERS
# =====================================================

def _extract_audio_from_reel(video_path: str, job_id: str) -> Optional[str]:
    """
    Pull the audio track out of the finished highlight reel into an MP3.

    This is what the audio player and the Download Audio button serve. Because
    the reel carries the original speaker audio, the MP3 is the real voices from
    the source videos — no synthesis involved. Stream copy is not used: the reel
    is AAC, and the player expects MP3.

    Returns the MP3 path, or None if extraction failed (audio is optional; a
    failure here must not fail the job).
    """
    if not video_path or not os.path.exists(video_path):
        return None

    audio_dir = "audio_cache"
    os.makedirs(audio_dir, exist_ok=True)
    out_path = os.path.join(audio_dir, f"summary_{job_id}.mp3")

    try:
        import subprocess as _sp
        _sp.run(
            [
                "ffmpeg", "-y", "-i", video_path,
                "-vn",                      # drop the video stream
                "-acodec", "libmp3lame", "-b:a", "192k",
                out_path,
            ],
            capture_output=True, timeout=180, check=True,
        )
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            print(f"[Audio] Extracted original audio from reel -> {out_path}")
            return out_path
        print("[Audio] ffmpeg produced no audio file")
    except Exception as e:
        print(f"[Audio] Could not extract audio from reel: {e}")
    return None


def _fit_to_duration(highlights: list, target_seconds: int) -> list:
    """Select highlights that fit within the time budget."""
    selected = []
    total = 0.0
    for h in highlights:
        dur = h["end_time"] - h["start_time"]
        if dur <= 0:
            continue
            
        # Prevent overlapping segments from the same video to ensure summary diversity
        is_overlapping = False
        for s in selected:
            if h.get("video_id") == s.get("video_id"):
                if max(h["start_time"], s["start_time"]) < min(h["end_time"], s["end_time"]):
                    is_overlapping = True
                    break
        if is_overlapping:
            continue

        if total + dur <= target_seconds:
            selected.append(h)
            total += dur
        if total >= target_seconds:
            break
    return selected


async def _legacy_select_highlights(
    job,
    video_paths: Dict[str, str],
    raw_segments: Dict[str, list],
    summary_text: str,
    update_status,
    keyframes_extracted: Dict[str, int],
) -> list:
    """
    The original clip scorer, kept as a fallback.

    Unchanged behaviour: group transcript entries into ~20-90s blocks, score them
    with the 4-signal hybrid (SBERT + TF-IDF + audio energy + temporal attention)
    and take the top scorers that fit. It runs only when the semantic pipeline
    cannot produce a selection — a transcript with no usable timestamps, or one
    too short to segment — or when ENABLE_SEMANTIC_SELECTION is turned off.

    Its known weakness is the reason the semantic path exists: the score has no
    memory and no notion of WHERE in the video a candidate came from, so a
    front-loaded ranking stays front-loaded.
    """
    from ..services.visual_keyframe_extractor import extract_keyframes_for_segments
    from ..services.segment_extractor import extract_highlight_segments, group_transcript_segments

    all_highlights: list = []
    per_video_seconds = job.highlight_duration_seconds // max(len(video_paths), 1)

    for vid, vid_path in video_paths.items():
        segs = raw_segments.get(vid, [])
        if not segs:
            continue

        # Step 2a: Group transcript segments, then extract ONE frame per group.
        # This replaces the old PySceneDetect full-video scan (20-60 min) with
        # N direct seeks — one per segment midpoint — completing in seconds.
        await update_status(
            JobStatus.GENERATING_VIDEO, 98,
            f"Extracting keyframes for {vid} (fast: 1 frame per segment)..."
        )
        # GUARD: skip the visual stage entirely when the narration-driven
        # path will be used. That path (extract_highlights_narration_driven)
        # matches narration sentences to transcript segments with SBERT and
        # never reads visual_keyframes — so extracting them is pure cost.
        #
        # The cost is significant: keyframe extraction calls
        # augment_keyframes_with_temporal(), which loads CLIP to embed frames
        # when no clip_embedding is present. Worse, asyncio.wait_for() cannot
        # kill a thread started by asyncio.to_thread() — so on timeout the
        # job continued while that thread kept loading CLIP and embedding
        # frames in the background, stealing CPU from every later stage.
        #
        # Trade-off: if narration-driven selection later returns nothing
        # (e.g. SBERT unavailable), the fallback scorer runs without visual
        # signal and degrades to its SBERT+TF-IDF weighting — still correct,
        # just without the audio/temporal blend.
        # Previously gated on the TTS subtitle file, which no longer
        # exists. Keyframe/CLIP extraction stays off by default: it is
        # the most expensive stage in the pipeline and the scorer
        # accepts visual_keyframes=None, falling back to SBERT+TF-IDF.
        # Set MERGE_ENABLE_VISUAL_SCORING=1 to opt back in.
        skip_visual_stage = os.getenv("MERGE_ENABLE_VISUAL_SCORING", "0") != "1"

        if skip_visual_stage:
            visual_keyframes = []
            print(f"[Video] {vid}: visual scoring disabled "
                  f"— using SBERT+TF-IDF selection")
        else:
            transcript_groups = group_transcript_segments(segs)
            try:
                visual_keyframes = await asyncio.wait_for(
                    asyncio.to_thread(
                        extract_keyframes_for_segments, vid, vid_path, transcript_groups
                    ),
                    timeout=90.0,
                )
            except asyncio.TimeoutError:
                print(f"[Video] Keyframe extraction timed out for {vid} — skipping visual stage")
                visual_keyframes = []
        keyframes_extracted[vid] = len(visual_keyframes)

        # Step 2b: Audio energy scoring (replaces CLIP for podcast content).
        # CLIP scores are nearly flat for talking-head videos (diff < 0.005
        # measured on real data). Audio energy gives 250x more variance by
        # scoring RMS loudness + spectral flux + ZCR — capturing emphasis
        # and speaking pace, which are the real signals of importance in a
        # single-speaker podcast. Populates the same "clip_score" field so
        # _score_segments_hybrid() needs no changes.
        if visual_keyframes:
            try:
                from ..services.audio_energy_scorer import augment_keyframes_with_audio_energy
                await asyncio.wait_for(
                    asyncio.to_thread(
                        augment_keyframes_with_audio_energy,
                        visual_keyframes,
                        vid_path,
                    ),
                    timeout=120.0,
                )
            except asyncio.TimeoutError:
                print(f"[Video] Audio energy scoring timed out for {vid} — using default scores")
            except Exception as ae_err:
                print(f"[Video] Audio energy scoring failed: {ae_err} — using default scores")
            print(
                f"[Video] {vid}: {len(visual_keyframes)} keyframes "
                f"→ audio energy + temporal scores ready"
            )

        # Clip selection is score-based. The narration-driven path was
        # removed with TTS: it matched each synthesized sentence to a
        # transcript segment, which has no meaning now that the reel
        # carries the speakers' own words.
        highlights = []
        _used_narration_driven = False

        if not _used_narration_driven:
            # Fallback: 4-signal hybrid scoring (SBERT + TF-IDF + audio + temporal)
            # min_segment_duration=20s ensures clips are long enough to be coherent
            # — short choppy clips feel like channel surfing, not a highlight reel.
            highlights = extract_highlight_segments(
                video_id=vid,
                transcript_segments=segs,
                summary_text=summary_text,
                target_duration_seconds=per_video_seconds,
                context_padding_seconds=1.5,
                min_segment_duration=20.0,
                max_segment_duration=90.0,
                visual_keyframes=visual_keyframes or None,
            )

        all_highlights.extend(highlights)

    return all_highlights


# =====================================================
# SEMANTIC SELECTION PIPELINE
# =====================================================

def _source_duration(segments: list) -> float:
    """Length of a source video, inferred from its last transcript entry."""
    if not segments:
        return 0.0
    last = segments[-1]
    try:
        return float(last.get("start", 0)) + float(last.get("duration", 0))
    except (TypeError, ValueError):
        return 0.0


def _allocate_budgets(durations: Dict[str, float], total_budget: float) -> Dict[str, float]:
    """
    Split the time budget across videos in proportion to their length.

    The old code divided the budget equally (`per_video_seconds = budget //
    len(videos)`), which gives a 5-minute clip and a 90-minute podcast the same
    share of the summary. Proportional allocation matches how much content each
    source actually contains. Equal split is kept as the fallback for the case
    where no duration is known.
    """
    total_source = sum(durations.values())
    if total_source <= 0:
        share = total_budget / max(len(durations), 1)
        return {vid: share for vid in durations}
    return {vid: total_budget * (dur / total_source) for vid, dur in durations.items()}


async def run_semantic_selection(
    job,
    raw_segments: Dict[str, list],
    summary_text: str,
    progress=None,
) -> Optional[Dict]:
    """
    The coverage-aware selection pipeline.

        transcript -> sentences -> semantic segments   (semantic_segmenter)
                   -> concepts                          (concept_extractor)
                   -> budgeted submodular selection     (coverage_selector)
                   -> metrics                           (summary_metrics)

    Returns None when it cannot produce a usable selection, which tells the
    caller to run the legacy scorer instead. It never raises: a failure here
    must degrade the job, not fail it.

    Args:
        job: the MergeJob being processed
        raw_segments: {video_id: [{text, start, duration}]}
        summary_text: the finished summary, used as the relevance reference
        progress: optional async callback(message) for status updates
    """
    from ..services.semantic_segmenter import build_semantic_segments
    from ..services.concept_extractor import extract_concepts
    from ..services.coverage_selector import SelectionWeights, select_segments
    from ..services.summary_metrics import compute_selection_metrics, format_metrics_report

    async def say(message: str):
        print(f"[Semantic] {message}")
        if progress:
            try:
                await progress(message)
            except Exception:
                pass

    budget = float(job.highlight_duration_seconds)
    weights = SelectionWeights.from_settings(settings)

    durations = {vid: _source_duration(segs) for vid, segs in raw_segments.items() if segs}
    if not durations:
        return None
    budgets = _allocate_budgets(durations, budget)

    # --- Reference vector for the relevance term ---
    # The summary is the best statement of what the video is "about", but it is
    # only used as a *reference*, never as the sole ranking signal — that is
    # precisely what made selection beginning-heavy.
    summary_embedding = None
    try:
        from ..services.fusion_engine import get_sentence_transformer
        embedder = get_sentence_transformer()
        if summary_text.strip():
            summary_embedding = embedder.encode(
                [summary_text[:4000]], show_progress_bar=False
            )[0]
    except Exception as exc:
        print(f"[Semantic] Embedder unavailable ({exc}) — continuing without a summary reference")

    all_selected = []
    baselines = []
    all_concepts = []
    all_trace = []
    per_video = {}

    for vid, segs in raw_segments.items():
        if not segs:
            continue

        # --- 1. semantic segmentation ---
        await say(f"Building semantic segments for {vid}...")
        segments = await asyncio.to_thread(
            build_semantic_segments,
            segs,
            vid,
            settings.SEGMENT_MIN_SECONDS,
            settings.SEGMENT_MAX_SECONDS,
        )
        if not segments:
            print(f"[Semantic] {vid}: no semantic segments (unusable timestamps) — skipping")
            continue
        print(f"[Semantic] {vid}: {len(segs)} caption entries -> {len(segments)} complete thoughts "
              f"(avg {sum(s.duration for s in segments) / len(segments):.0f}s)")

        # --- 2. concept extraction ---
        await say(f"Extracting key concepts from {vid}...")
        try:
            concepts = await extract_concepts(
                segments,
                total_duration=durations.get(vid, 0.0),
                top_k=settings.CONCEPT_TOP_K,
                use_llm=settings.ENABLE_CONCEPT_LLM,
                per_chunk_timeout=settings.CONCEPT_CHUNK_TIMEOUT_SECONDS,
                total_timeout=settings.CONCEPT_TOTAL_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            print(f"[Semantic] Concept extraction failed for {vid}: {exc}")
            concepts = []

        # An empty concept list is NOT a normal outcome to pass over quietly.
        # The concept term carries the largest single weight in the optimizer,
        # so with no concepts the selection silently degrades to relevance +
        # temporal coverage only — which is what produced a reel that spread
        # evenly across the timeline and cut an important discussion in half.
        # Say so explicitly rather than letting "0/0 concepts covered" read
        # like a successful concept-driven run.
        if not concepts:
            print(f"[Semantic] WARNING: 0 concepts extracted for {vid} — "
                  f"concept-driven selection is DISABLED for this video; "
                  f"falling back to relevance + temporal coverage only")

        # --- 3. budgeted selection ---
        await say(f"Selecting the best {budgets[vid]:.0f}s from {vid}...")
        result = await asyncio.to_thread(
            select_segments,
            segments,
            budgets[vid],
            concepts,
            weights,
            summary_embedding,
            None,
            durations.get(vid, 0.0),
        )
        if not result.segments:
            print(f"[Semantic] {vid}: optimizer returned nothing — skipping")
            continue

        baselines.append(result.baseline_similarity)
        all_selected.extend(result.segments)
        all_concepts.extend(concepts)
        all_trace.extend(result.trace)
        per_video[vid] = {
            "candidates": len(segments),
            "selected": len(result.segments),
            "seconds": round(result.total_duration, 1),
            "budget": round(budgets[vid], 1),
            "concepts_found": len(concepts),
            "concepts_covered": result.concepts_covered,
            # Distinguishes "concepts were used" from "there were none", so a
            # 0/0 result can never be presented as concept-driven selection.
            "concept_signal": result.concept_signal,
            "concepts_completed": result.concepts_completed,
            "concepts_omitted_for_budget": result.concepts_omitted_for_budget,
        }

    if not all_selected:
        return None

    # --- 4. metrics over a virtual concatenated timeline ---
    # Offsetting each video by the cumulative length of the ones before it lets a
    # multi-video job report a single coherent coverage histogram instead of
    # overlaying unrelated timelines on top of each other.
    offsets, running = {}, 0.0
    for vid in raw_segments:
        offsets[vid] = running
        running += durations.get(vid, 0.0)

    class _Shifted:
        __slots__ = ("start_time", "end_time", "duration")

        def __init__(self, seg, offset):
            self.start_time = seg.start_time + offset
            self.end_time = seg.end_time + offset
            self.duration = seg.duration

    shifted = [_Shifted(s, offsets.get(s.video_id, 0.0)) for s in all_selected]

    vectors = None
    embeddings = [getattr(s, "embedding", None) for s in all_selected]
    if all(e is not None for e in embeddings):
        import numpy as _np
        matrix = _np.asarray(embeddings, dtype=float)
        norms = _np.linalg.norm(matrix, axis=1, keepdims=True)
        vectors = matrix / _np.where(norms < 1e-9, 1e-9, norms)

    covered = set()
    for info in per_video.values():
        covered.update(info["concepts_covered"])

    metrics = compute_selection_metrics(
        selected=shifted,
        total_duration=max(running, 1.0),
        requested_seconds=budget,
        concepts=all_concepts,
        concepts_covered=sorted(covered),
        segment_vectors=vectors,
        baseline_similarity=(
            sum(b for b in baselines if b is not None) / len([b for b in baselines if b is not None])
            if any(b is not None for b in baselines) else None
        ),
    )
    metrics["per_video"] = per_video
    metrics["weights"] = weights.__dict__.copy()
    print(format_metrics_report(metrics, "Semantic selection"))

    # --- 5. hand back segments in the shape the reel builder expects ---
    highlights = []
    for seg in sorted(all_selected, key=lambda s: (s.video_id, s.start_time)):
        highlights.append({
            "video_id": seg.video_id,
            # No padding is applied. The segment already begins at a sentence
            # start and ends at a sentence end, so padding would only pull in
            # the tail of the previous thought — the very artefact this change
            # exists to remove.
            "start_time": round(max(0.0, seg.start_time), 3),
            "end_time": round(seg.end_time, 3),
            "importance_score": round(float(seg.boundary_confidence), 4),
            "reason": "Complete semantic segment selected by coverage-aware optimizer",
            "text": seg.text,
        })

    return {
        "highlights": highlights,
        "concepts": [c.to_dict() for c in all_concepts],
        "metrics": metrics,
        "trace": all_trace,
    }


# =====================================================
# BACKGROUND PROCESSING
# =====================================================

async def process_merge_job(job_id: str):
    """
    Process a merge job in the background.

    Stages:
    1. Fetch transcripts
    2. Analyze content
    3. Fuse transcripts
    4. Generate summary
    5. Generate audio (optional)
    """
    jobs_collection = await get_jobs_collection()

    try:
        job = _active_jobs.get(job_id)
        if not job:
            return

        # Update status helper
        async def update_status(
            status: JobStatus,
            progress: int,
            message: str
        ):
            job.status = status
            job.progress_percent = progress
            job.stage_message = message
            job.updated_at = datetime.utcnow()

            await jobs_collection.update_one(
                {"job_id": job_id},
                {"$set": {
                    "status": status.value,
                    "progress_percent": progress,
                    "stage_message": message,
                    "updated_at": job.updated_at,
                }}
            )

        # STAGE 1: Transcribing (0-30%)
        await update_status(
            JobStatus.TRANSCRIBING,
            5,
            "Fetching video transcripts..."
        )

        # Real (not synthetic) mid-stage signal: translation/re-transcription
        # of non-English captions can take a while, and previously left the
        # UI showing "5%" with no visible change for that whole window. Each
        # call nudges progress forward (capped below the 30% "fetched"
        # checkpoint) rather than jumping to a fixed value, since a video can
        # report more than one stage (e.g. "translating" then "re-
        # transcribing with Whisper"). Monotonic — never regresses — because
        # videos fetch concurrently and callbacks can arrive interleaved.
        async def _transcript_progress(message: str):
            if job.progress_percent < 28:
                await update_status(
                    JobStatus.TRANSCRIBING, min(job.progress_percent + 5, 28), message
                )

        transcripts, raw_segments = await fetch_transcripts_with_segments(
            job.video_ids, progress_cb=_transcript_progress
        )

        await update_status(
            JobStatus.TRANSCRIBING,
            30,
            f"Fetched {len(transcripts)} transcripts"
        )

        if not transcripts:
            raise Exception("Could not fetch any transcripts")

        # Language check — reports non-English transcripts that survived
        # fetch_transcripts_with_segments() untranslated.
        #
        # This used to retry translation here via NLLB on the flat text —
        # a SECOND translation attempt stacked on top of the one
        # TranscriptService.get_transcript() already made (Google, then a
        # size-gated NLLB attempt, then a duration-gated Whisper
        # re-transcribe). For a transcript too long for the first NLLB
        # attempt to be worth it, this retry was just as slow and just as
        # doomed — exactly the "expensive fallback cascade" that turned one
        # bad translation into several minutes of stacked bad translations.
        # get_transcript() is the single place that decides how far to chase
        # a translation; this stage only surfaces the result.
        # Survives the try/except below so the final job warning can tell the
        # user their summary text is not trustworthy.
        untranslated_langs: Dict[str, str] = {}
        try:
            from langdetect import detect
            non_english = {}
            for vid, text in transcripts.items():
                sample = text[:3000]
                try:
                    lang = detect(sample)
                except Exception:
                    lang = "en"  # Assume English if detection fails
                if lang != "en":
                    non_english[vid] = lang
                    print(f"[WARN] Transcript for {vid} detected as '{lang}' (not English)")

            untranslated_langs = dict(non_english)
            if non_english:
                lang_list = ", ".join(f"{lang}" for _, lang in non_english.items())
                await update_status(
                    JobStatus.TRANSCRIBING,
                    30,
                    f"Warning: {len(non_english)} transcript(s) ({lang_list}) could not "
                    f"be fully translated to English. Summary quality may be reduced."
                )
                print(f"[WARN] Proceeding with non-English transcripts for: {list(non_english)}")
            else:
                await update_status(
                    JobStatus.TRANSCRIBING,
                    30,
                    "All transcripts are in English"
                )
        except ImportError:
            print("[WARN] langdetect not installed — skipping language check")
        except Exception as e:
            print(f"[WARN] Language detection skipped: {e}")

        # Index transcripts in FAISS for semantic search (best-effort).
        # Skip videos whose transcript is non-English and untranslated: their
        # text is not in the embedding model's language so the index entries
        # would corrupt semantic search results for subsequent English jobs.
        try:
            from ..services.vector_store import get_vector_store
            store = get_vector_store()
            for vid, text in transcripts.items():
                if vid in untranslated_langs:
                    print(f"[WARN] Skipping FAISS indexing for {vid} — untranslated '{untranslated_langs[vid]}' text")
                    continue
                segs = raw_segments.get(vid, [])
                if not store.is_video_indexed(vid):
                    if segs:
                        store.add_transcript_with_timestamps(vid, vid, segs)
                    else:
                        store.add_transcript(vid, vid, text)
        except Exception as e:
            print(f"[WARN] FAISS indexing skipped: {e}")

        # ── LANGUAGE CAPABILITY GATE ─────────────────────────────────────────
        # When the transcript cannot be translated every downstream text stage
        # (fusion, BART, enrichment, quality scorecard) is English-only and
        # will either:
        #   (a) produce 0 output — Hindi uses "।" not ".!?", so sentence
        #       splitting returns 0 sentences → narrative = "" → 0 words, or
        #   (b) fabricate English — distilbart-cnn-12-6 byte-fragments
        #       Devanagari and emits confident, invented English text.
        #
        # Neither case should be presented to the user as a summary.
        # Skip the whole pipeline and jump directly to video generation, which
        # operates on raw timestamped segments and embeddings — it does NOT
        # need a summary to be valid.
        if untranslated_langs:
            langs = ", ".join(sorted(set(untranslated_langs.values())))
            print(f"[WARN] LANGUAGE CAPABILITY ABORT: transcripts are '{langs}' and could "
                  f"not be translated — skipping fusion, summarization, and enrichment "
                  f"(English-only stages). Video generation will proceed.")
            await update_status(
                JobStatus.ANALYZING, 35,
                f"Transcript language '{langs}' is not supported by the summarizer — "
                f"written summary unavailable. Generating highlight video only."
            )

            # summary_text is intentionally left as None here, not "", so
            # the result page can distinguish 'job ran but language unsupported'
            # from 'summarizer returned empty text'.
            summary_text: Optional[str] = None
            rich_output = None
            fusion_metadata = FusionMetadata(
                total_source_words=sum(len(t.split()) for t in transcripts.values()),
                output_words=0,
                compression_ratio=0.0,
                topics_found=[],
                clusters_created=0,
                dedup_ratio=0.0,
                processing_time_seconds=0.0,
                video_count=len(transcripts),
            )
            summarization_decision = None

            # Jump directly to video generation — reuses the same code block
            # below by letting execution fall through with summary_text=None.
            # All the variables that block expects are set here to safe defaults.
            audio_path = None
            subtitle_path = None
            video_path = None
            job_warning = (
                f"This video's transcript is in '{langs}' and could not be translated. "
                f"The written summary, TL;DR and key points are UNAVAILABLE for this language — "
                f"the summarizer only supports English. The highlight video is unaffected."
            )
            highlight_segments_result = []
            keyframes_extracted: Dict[str, int] = {}
            job_concepts: list = []
            selection_metrics: Optional[Dict] = None
            selection_trace: list = []
            selection_mode = "legacy"

            # Emit a partial-success result now, BEFORE video generation,
            # so the UI shows a clear language-unavailable state even if
            # video generation is also skipped.
            job.status = JobStatus.PARTIAL_SUCCESS
            job.stage_message = (
                f"Written summary unavailable ('{langs}' transcript). "
                f"Generating video highlights..."
            )
            job.warning = job_warning
            await jobs_collection.update_one(
                {"job_id": job_id},
                {"$set": {
                    "status": job.status.value,
                    "stage_message": job.stage_message,
                    "warning": job_warning,
                }}
            )

            # Fall through to video generation below.
            # The `if job.generate_video:` block uses summary_text only as
            # an optional semantic reference — it handles None gracefully
            # (semantic_selection skips the summary embedding when summary is empty).
            #
            # We jump to the STAGE 6 block by skipping everything between here
            # and it.  All variables the stage-6 block reads are set above.
            # noinspection PyUnreachableCode  (intentional fall-through)
            _language_abort = True
        else:
            _language_abort = False

        if not _language_abort:
            # STAGE 2: Analyzing (30-40%)
            await update_status(
                JobStatus.ANALYZING,
                35,
                "Analyzing content structure..."
            )

            # Get duration profile
            profile = get_profile(job.target_duration_minutes)
            target_words = profile.target_words

            await update_status(
                JobStatus.ANALYZING,
                40,
                f"Target: {target_words} words ({profile.style.value} style)"
            )

            # STAGE 3: Fusing (40-70%)
            await update_status(
                JobStatus.FUSING,
                45,
                "Fusing content from multiple sources..."
            )

            # Run fusion engine
            # raw_segments carries the per-video timestamped caption lists that
            # fetch_transcripts_with_segments() already built.  Passing them here
            # activates Tier 1 (segment-boundary chunking) in _extract_sentences(),
            # which is the fix for 0-sentence extraction on English auto-captions.
            fusion_engine = get_fusion_engine()
            fusion_result = fusion_engine.fuse_transcripts(
                transcripts=transcripts,
                target_words=target_words,
                include_sources=profile.include_sources,
                include_transitions=profile.include_transitions,
                raw_segments=raw_segments,
            )

            await update_status(
                JobStatus.FUSING,
                70,
                f"Fusion complete: {len(fusion_result.topics)} topics identified"
            )

        if not _language_abort:
            # STAGE 4: Summarizing (70-85%) - BART-large-CNN Hierarchical
            await update_status(
                JobStatus.SUMMARIZING,
                75,
                "Running BART-large-CNN hierarchical summarization..."
            )

            from ..services.summarization_service import get_summarization_service
            summarizer_svc = get_summarization_service()
            # summarize_with_policy() also reports WHY it took the path it did, so a
            # bypass can never again go unnoticed the way the old
            # `if word_count <= target_words: return text` shortcut did.
            summary_text, summarization_decision = await asyncio.to_thread(
                summarizer_svc.summarize_with_policy,
                fusion_result.narrative,
                target_words,
                profile,
            )

            # Store metadata
            fusion_metadata = FusionMetadata(
                total_source_words=fusion_result.metadata.get("total_source_words", 0),
                output_words=fusion_result.metadata.get("output_words", 0),
                compression_ratio=fusion_result.metadata.get("compression_ratio", 0),
                topics_found=fusion_result.topics,
                clusters_created=fusion_result.metadata.get("clusters_created", 0),
                dedup_ratio=fusion_result.metadata.get("dedup_ratio", 0),
                processing_time_seconds=fusion_result.metadata.get("processing_time_seconds", 0),
                video_count=len(transcripts),
            )

            await update_status(
                JobStatus.SUMMARIZING,
                80,
                f"BART summary ready: {len(summary_text.split())} words"
            )

            # STAGE 4.5: Ollama AI Enrichment (80-90%)
            rich_output = None
            _OLLAMA_WALL_TIMEOUT = 120  # hard cap so job never blocks >2 min on this stage
            try:
                from ..services.ollama_service import get_ollama_service
                ollama = get_ollama_service()

                if not settings.ENABLE_OLLAMA_ENRICHMENT:
                    # Skipped by default — on CPU this stage times out (~100s) and
                    # returns None, after which the local TF-IDF enrichment below
                    # produces the TLDR/takeaways/chapters anyway. Skipping removes
                    # the dead time without changing the job's output.
                    # The Quality Panel's LLM judge is unaffected and still uses Ollama.
                    print("[Ollama] Merge-path enrichment disabled "
                          "(ENABLE_OLLAMA_ENRICHMENT=false) — using local TF-IDF enrichment")
                elif ollama.is_available():
                    await update_status(
                        JobStatus.ENRICHING,
                        82,
                        f"AI enriching with Ollama/{settings.OLLAMA_MODEL} (chapters, takeaways, quotes)..."
                    )

                    video_titles = ", ".join(job.video_ids)
                    rich_output = await asyncio.wait_for(
                        ollama.generate_rich_summary(
                            narrative=fusion_result.narrative,
                            target_words=target_words,
                            style=job.style,
                            video_titles=video_titles,
                        ),
                        timeout=_OLLAMA_WALL_TIMEOUT,
                    )

                    if rich_output:
                        # Patch BART summary in if Ollama's summary is too short
                        if not rich_output.summary or len(rich_output.summary.split()) < 50:
                            rich_output.summary = summary_text
                        else:
                            summary_text = rich_output.summary
                        await update_status(
                            JobStatus.ENRICHING,
                            90,
                            f"AI enrichment done: {len(rich_output.chapters)} chapters, "
                            f"{len(rich_output.key_takeaways)} takeaways"
                        )
                    else:
                        print("[Ollama] returned None — using local fallback")
                else:
                    print(f"[Ollama] Not available. Run: ollama pull {settings.OLLAMA_MODEL}")

            except asyncio.TimeoutError:
                print(f"[Ollama] Hard timeout ({_OLLAMA_WALL_TIMEOUT}s) — using local TF-IDF fallback")
                rich_output = None
            except Exception as e:
                print(f"[WARN] Ollama enrichment failed: {e}")

            # Always fall back to local TF-IDF if Ollama produced no structured output
            if not rich_output or not rich_output.tldr or not rich_output.key_takeaways:
                print("[LocalEnrich] Generating TLDR+takeaways locally (TF-IDF)...")
                rich_output = _generate_local_enrichment(summary_text, job.style)

        # STAGE 5: Audio (90-97%)
        #
        # The summary audio is the ORIGINAL speaker audio taken from the highlight
        # reel, not synthesized narration. TTS was removed deliberately: the product
        # promise is authentic source audio, and the reel already preserves it
        # (see video_service.py). audio_path is therefore filled in AFTER the reel
        # is built, by _extract_audio_from_reel() further down.
        #
        # subtitle_path stays None. It only ever held the TTS narration's SRT, and
        # nothing in the UI consumes /subtitles.
        if not _language_abort:
            audio_path = None
            subtitle_path = None

        # STAGE 6: Video Highlight Generation (97-99%) - Optional
        # Free-only pipeline: PySceneDetect + CLIP ViT-B/16 + temporal attention
        # When _language_abort is True, these are already initialized above;
        # skip the re-initialization so the language-abort branch values survive.
        if not _language_abort:
            video_path = None
            job_warning = None
            highlight_segments_result = []
            keyframes_extracted = {}
            job_concepts = []
            selection_metrics = None
            selection_trace = []
            selection_mode = "legacy"
        if job.generate_video:
            await update_status(
                JobStatus.GENERATING_VIDEO,
                97,
                "Generating video highlight reel (CLIP + temporal attention pipeline)..."
            )

            try:
                from ..services.video_service import get_video_service
                from ..services.visual_keyframe_extractor import extract_keyframes_for_segments
                from ..services.segment_extractor import extract_highlight_segments, group_transcript_segments

                video_svc = get_video_service()

                # Step 1: Download source videos
                await update_status(
                    JobStatus.GENERATING_VIDEO, 97,
                    "Downloading source videos for highlight extraction..."
                )
                unique_video_ids = list(raw_segments.keys())

                async def video_progress(msg):
                    await update_status(JobStatus.GENERATING_VIDEO, 98, msg)

                # Derive total source duration from the transcript timestamps.
                # This is the same data raw_segments holds: sum of all per-video
                # durations gives the overall source length, which drives the
                # per-video download timeout inside download_videos().
                _total_source_seconds = sum(
                    _source_duration(raw_segments.get(v, []))
                    for v in unique_video_ids
                )

                # download_videos() now owns the per-video timeout; the old
                # global 300s asyncio.wait_for wrapper is removed because it
                # was sized for 20-min videos and silently failed for 95-min
                # content.  Each video gets a proportional budget inside
                # _download_single() instead.
                video_paths = await video_svc.download_videos(
                    unique_video_ids,
                    job_id=job_id,
                    progress_callback=video_progress,
                    source_duration_seconds=_total_source_seconds,
                )

                if not video_paths:
                    raise Exception("Could not download any source videos")

                # ---------------------------------------------------------
                # SELECTION — coverage-aware semantic path, legacy fallback
                # ---------------------------------------------------------
                # The semantic path chooses COMPLETE THOUGHTS under a time budget
                # using concept coverage, temporal coverage and a redundancy
                # penalty. The legacy path below sorts candidate clips by score
                # and takes them until the budget fills, which is what produced
                # the beginning-heavy reels (measured: 80% of a 5-minute summary
                # in the first half of a 24.8-minute source, last two deciles
                # empty). It is kept as a fallback for transcripts the semantic
                # path cannot handle — no timestamps, or too short to segment.
                semantic = None
                if settings.ENABLE_SEMANTIC_SELECTION:
                    await update_status(
                        JobStatus.GENERATING_VIDEO, 98,
                        "Analyzing concepts and selecting complete semantic segments..."
                    )
                    try:
                        semantic = await run_semantic_selection(
                            job=job,
                            raw_segments={v: raw_segments.get(v, []) for v in video_paths},
                            summary_text=summary_text,
                            progress=video_progress,
                        )
                    except Exception as sel_err:
                        print(f"[Semantic] Pipeline failed ({sel_err}) — falling back to legacy scorer")
                        import traceback
                        traceback.print_exc()
                        semantic = None

                if semantic and semantic["highlights"]:
                    highlight_segments_result = semantic["highlights"]
                    job_concepts = semantic["concepts"]
                    selection_metrics = semantic["metrics"]
                    selection_trace = semantic["trace"]
                    selection_mode = "semantic"
                    all_highlights = list(highlight_segments_result)
                else:
                    if settings.ENABLE_SEMANTIC_SELECTION:
                        print("[Semantic] No usable selection — running legacy scorer")
                    all_highlights = await _legacy_select_highlights(
                        job=job,
                        video_paths=video_paths,
                        raw_segments=raw_segments,
                        summary_text=summary_text,
                        update_status=update_status,
                        keyframes_extracted=keyframes_extracted,
                    )

                if all_highlights:
                    if selection_mode != "semantic":
                        # Legacy path only. The semantic optimizer has ALREADY
                        # solved the budget problem: it selected against the
                        # budget with a coverage and redundancy objective, so
                        # re-running a score-sorted greedy over its output would
                        # undo exactly what it optimised for and re-impose the
                        # front-loading this change removes.
                        all_highlights.sort(
                            key=lambda h: h.get("importance_score", 0), reverse=True
                        )
                        highlight_segments_result = _fit_to_duration(
                            all_highlights, job.highlight_duration_seconds
                        )
                        highlight_segments_result.sort(
                            key=lambda h: (h["video_id"], h["start_time"])
                        )
                    _reel_seconds = sum(
                        h["end_time"] - h["start_time"] for h in highlight_segments_result
                    )
                    print(f"[Video] {len(highlight_segments_result)} clips kept "
                          f"({_reel_seconds:.0f}s) for a {job.highlight_duration_seconds}s reel "
                          f"[{selection_mode} selection]")

                    # Step 3: Generate the highlight reel
                    await update_status(
                        JobStatus.GENERATING_VIDEO, 99,
                        f"Cutting and stitching {len(highlight_segments_result)} highlight clips..."
                    )

                    video_path = await video_svc.generate_highlight_reel(
                        job_id=job.job_id,
                        highlight_segments=highlight_segments_result,
                        video_paths=video_paths,
                        audio_path=None,   # never overlaid; reel keeps source audio
                        progress_callback=video_progress,
                    )

                    print(f"[Video] Highlight reel generated: {video_path}")

                    # The reel's own audio IS the summary audio. Extract it so the
                    # player and Download Audio serve real voices, not synthesis.
                    if job.generate_audio and video_path:
                        audio_path = await asyncio.to_thread(
                            _extract_audio_from_reel, video_path, job.job_id
                        )
                else:
                    job_warning = "Video generation skipped because no highlight segments were identified."
                    print(f"[Video] {job_warning}")

            except Exception as e:
                job_warning = f"Video generation failed: {e}"
                print(f"[WARN] {job_warning}")
                import traceback
                traceback.print_exc()
                video_path = None

            finally:
                import shutil as _shutil
                _dl_dir = os.path.join("audio_cache", "video_downloads", job_id)
                if os.path.isdir(_dl_dir):
                    _shutil.rmtree(_dl_dir, ignore_errors=True)
                    print(f"[Video] Cleaned up download dir: {_dl_dir}")

        # COMPLETED
        # Note: when _language_abort is True, job.status and job_warning were
        # already set to PARTIAL_SUCCESS before video generation — preserve them.
        if not _language_abort:
            if job.generate_video and not video_path:
                job.status = JobStatus.PARTIAL_SUCCESS
                job.stage_message = job_warning or "Summary ready, but video highlights were unavailable."
            else:
                job.status = JobStatus.COMPLETED
                job.stage_message = "Your summary is ready!"
        # Language-abort jobs already have status=PARTIAL_SUCCESS and a
        # language-specific warning set; only update if video succeeded.
        elif video_path:
            job.stage_message = "Highlight video ready — written summary unavailable for this language."
        job.progress_percent = 100
        # summary_text is None (not "") when the language is unsupported. The
        # result page checks for None/empty to show the language-unavailable state
        # instead of "Your summary is ready".
        job.summary_text = summary_text
        job.rich_output = rich_output
        job.fusion_metadata = fusion_metadata
        job.audio_path = audio_path
        job.subtitle_path = subtitle_path
        job.video_path = video_path
        job.highlight_segments = highlight_segments_result
        job.keyframes_extracted = keyframes_extracted
        job.concepts = job_concepts
        job.selection_metrics = selection_metrics
        job.selection_trace = selection_trace
        job.summarization_decision = summarization_decision
        job.selection_mode = selection_mode
        job.warning = job_warning
        job.completed_at = datetime.utcnow()

        rich_output_dict = rich_output.model_dump() if rich_output else None

        await jobs_collection.update_one(
            {"job_id": job_id},
            {"$set": {
                "status": job.status.value if hasattr(job.status, "value") else job.status,
                "progress_percent": 100,
                "stage_message": job.stage_message,
                "summary_text": summary_text,
                "rich_output": rich_output_dict,
                "fusion_metadata": fusion_metadata.model_dump(),
                "audio_path": audio_path,
                "subtitle_path": subtitle_path,
                "video_path": video_path,
                "highlight_segments": highlight_segments_result,
                "keyframes_extracted": keyframes_extracted,
                "concepts": job_concepts,
                "selection_metrics": selection_metrics,
                "selection_trace": selection_trace,
                "summarization_decision": summarization_decision,
                "selection_mode": selection_mode,
                "warning": job_warning,
                "completed_at": job.completed_at,
            }}
        )

        # Precompute the quality scorecard now that the job is already marked
        # complete. The results page requests it the moment it mounts, and
        # computing it takes ~100s — doing it here turns that request into a
        # cache read instead of a wait, and the user spends the interval
        # reading the summary rather than watching a spinner.
        #
        # Deliberately after the status update and inside its own try: a
        # scorecard is a nice-to-have, and a failure here must never turn a
        # finished job into a failed one.
        #
        # Language-abort jobs have summary_text=None, which causes
        # _build_quality_report to raise 400 "Job has no summary to evaluate".
        # Skip precompute to avoid that predictable 400 showing up in logs;
        # the evaluate endpoint will surface the same 400 when called on-demand.
        if not _language_abort:
            try:
                job_doc = await jobs_collection.find_one({"job_id": job_id})
                if job_doc:
                    quality_report = await _build_quality_report(job_doc, use_llm=False)
                    await jobs_collection.update_one(
                        {"job_id": job_id},
                        {"$set": {_QUALITY_CACHE_FIELD: quality_report}},
                    )
                    print(f"[Quality] Scorecard cached for {job_id} "
                          f"(summary={quality_report['summary_score']}%, "
                          f"video={quality_report['video_score']}%)")
            except Exception as quality_err:
                print(f"[Quality] Scorecard precompute skipped: {quality_err}")
        else:
            print(f"[Quality] Scorecard precompute skipped for {job_id} "
                  f"— language-unsupported job has no summary to score")

    except Exception as e:
        # Handle error
        error_msg = str(e)
        print(f"[ERROR] Job {job_id} failed: {error_msg}")

        if job_id in _active_jobs:
            job = _active_jobs[job_id]
            job.status = JobStatus.ERROR
            job.error = error_msg

        await jobs_collection.update_one(
            {"job_id": job_id},
            {"$set": {
                "status": JobStatus.ERROR.value,
                "error": error_msg,
                "updated_at": datetime.utcnow(),
            }}
        )

    finally:
        # Clean up memory after some time
        await asyncio.sleep(300)  # Keep in memory for 5 minutes
        _active_jobs.pop(job_id, None)


async def fetch_transcripts_with_segments(video_ids: list, progress_cb=None):
    """
    Fetch transcripts for multiple videos in parallel.
    Returns BOTH flat text and raw segments with timestamps.

    Uses the 3-tier transcript service (YouTube API → yt-dlp → Whisper).

    Args:
        video_ids: Raw video ids/URLs to fetch.
        progress_cb: Optional async callback(message) forwarded to
            TranscriptService.get_transcript, invoked when a per-video stage
            (e.g. non-English caption translation) starts. Videos fetch
            concurrently, so callbacks can arrive interleaved/out of order —
            callers should treat them as "something is happening" signals, not
            a strict sequence.

    Returns:
        Tuple of:
        - Dict[video_id, flat_text]
        - Dict[video_id, list_of_segments] where each segment has {text, start, duration}
    """
    from ..services.transcript_service import get_transcript_service, extract_video_id

    service = await get_transcript_service()

    async def _fetch_one(raw_id: str):
        video_id = extract_video_id(raw_id)
        try:
            result = await service.get_transcript(video_id, progress_cb=progress_cb)
            if result and result.get("transcript"):
                source = result.get("source", "unknown")
                segments = []
                if isinstance(result["transcript"], list):
                    segments = result["transcript"]
                    text = " ".join(
                        seg.get("text", "") for seg in segments
                    )
                else:
                    text = str(result["transcript"])

                if text.strip():
                    print(f"[Merge] Got transcript for {video_id} via {source} ({len(text.split())} words, {len(segments)} segments)")
                    return (video_id, text, segments)
        except Exception as e:
            print(f"[WARN] Could not fetch transcript for {video_id}: {e}")
        return None

    results = await asyncio.gather(*[_fetch_one(raw_id) for raw_id in video_ids])

    text_map = {}
    segments_map = {}
    for r in results:
        if r is not None:
            vid, text, segs = r
            text_map[vid] = text
            segments_map[vid] = segs

    return text_map, segments_map
