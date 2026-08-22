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
from typing import Dict, Optional
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
from ..services.duration_profiles import get_all_profiles, get_profile
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

    # The reel IS the output, so the user's chosen length drives it directly.
    # Previously target_duration_minutes only sized the TTS script and the reel
    # inherited whatever length that narration happened to be; with TTS gone the
    # two settings collapse into one. An explicit highlight_duration_seconds is
    # still honoured for callers that want the reel to differ from the summary.
    reel_seconds = request.highlight_duration_seconds
    if reel_seconds == 120:  # untouched default → follow the duration picker
        reel_seconds = min(request.target_duration_minutes * 60, 1200)

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

        transcripts, raw_segments = await fetch_transcripts_with_segments(job.video_ids)

        await update_status(
            JobStatus.TRANSCRIBING,
            30,
            f"Fetched {len(transcripts)} transcripts"
        )

        if not transcripts:
            raise Exception("Could not fetch any transcripts")

        # Language check — detect non-English transcripts and retry translation
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

            if non_english:
                lang_list = ", ".join(f"{lang}" for _, lang in non_english.items())
                await update_status(
                    JobStatus.TRANSCRIBING,
                    30,
                    f"Non-English transcripts detected ({lang_list}). Translating via NLLB-200..."
                )

                try:
                    from ..services.translation_service import translate_to_english as _nllb_translate
                    for vid, lang in non_english.items():
                        try:
                            translated = await asyncio.wait_for(
                                asyncio.to_thread(_nllb_translate, transcripts[vid], lang),
                                timeout=120.0,
                            )
                            transcripts[vid] = translated
                            print(f"[Transcript] NLLB translation: {vid} ({lang} → en)")
                        except asyncio.TimeoutError:
                            print(f"[WARN] NLLB translation timed out for {vid} — proceeding with original")
                except Exception as e:
                    print(f"[WARN] NLLB translation failed: {e}")

                # Final check — warn user if still non-English
                still_non_english = []
                for vid in non_english:
                    try:
                        if detect(transcripts[vid][:3000]) != "en":
                            still_non_english.append(vid)
                    except Exception:
                        pass

                if still_non_english:
                    await update_status(
                        JobStatus.TRANSCRIBING,
                        30,
                        f"Warning: {len(still_non_english)} transcript(s) could not be translated to English. Summary quality may be reduced."
                    )
                    print(f"[WARN] Proceeding with non-English transcripts for: {still_non_english}")
                else:
                    await update_status(
                        JobStatus.TRANSCRIBING,
                        30,
                        "All transcripts translated to English successfully"
                    )
        except ImportError:
            print("[WARN] langdetect not installed — skipping language check")
        except Exception as e:
            print(f"[WARN] Language detection skipped: {e}")

        # Index transcripts in FAISS for semantic search (best-effort)
        try:
            from ..services.vector_store import get_vector_store
            store = get_vector_store()
            for vid, text in transcripts.items():
                segs = raw_segments.get(vid, [])
                if not store.is_video_indexed(vid):
                    if segs:
                        store.add_transcript_with_timestamps(vid, vid, segs)
                    else:
                        store.add_transcript(vid, vid, text)
        except Exception as e:
            print(f"[WARN] FAISS indexing skipped: {e}")

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
        fusion_engine = get_fusion_engine()
        fusion_result = fusion_engine.fuse_transcripts(
            transcripts=transcripts,
            target_words=target_words,
            include_sources=profile.include_sources,
            include_transitions=profile.include_transitions,
        )

        await update_status(
            JobStatus.FUSING,
            70,
            f"Fusion complete: {len(fusion_result.topics)} topics identified"
        )

        # STAGE 4: Summarizing (70-85%) - BART-large-CNN Hierarchical
        await update_status(
            JobStatus.SUMMARIZING,
            75,
            "Running BART-large-CNN hierarchical summarization..."
        )

        from ..services.summarization_service import get_summarization_service
        summarizer_svc = get_summarization_service()
        summary_text = summarizer_svc.hierarchical_summarize(
            text=fusion_result.narrative,
            target_words=target_words,
            profile=profile,
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
        audio_path = None
        subtitle_path = None

        # STAGE 6: Video Highlight Generation (97-99%) - Optional
        # Free-only pipeline: PySceneDetect + CLIP ViT-B/16 + temporal attention
        video_path = None
        job_warning = None
        highlight_segments_result = []
        keyframes_extracted: Dict[str, int] = {}
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

                try:
                    video_paths = await asyncio.wait_for(
                        video_svc.download_videos(
                            unique_video_ids, job_id=job_id, progress_callback=video_progress
                        ),
                        timeout=300.0,
                    )
                except asyncio.TimeoutError:
                    raise Exception("Video download timed out after 5 minutes — skipping video generation")

                if not video_paths:
                    raise Exception("Could not download any source videos")

                all_highlights = []
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

                if all_highlights:
                    # Rank by importance, keep what fits the user's time budget,
                    # then play back in source order so each speaker's argument
                    # runs forwards instead of jumping around.
                    all_highlights.sort(
                        key=lambda h: h.get("importance_score", 0), reverse=True
                    )
                    highlight_segments_result = _fit_to_duration(
                        all_highlights, job.highlight_duration_seconds
                    )
                    highlight_segments_result.sort(
                        key=lambda h: (h["video_id"], h["start_time"])
                    )
                    print(f"[Video] {len(highlight_segments_result)} clips kept "
                          f"for a {job.highlight_duration_seconds}s reel")

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
        if job.generate_video and not video_path:
            job.status = JobStatus.PARTIAL_SUCCESS
            job.stage_message = job_warning or "Summary ready, but video highlights were unavailable."
        else:
            job.status = JobStatus.COMPLETED
            job.stage_message = "Your summary is ready!"
        job.progress_percent = 100
        job.summary_text = summary_text
        job.rich_output = rich_output
        job.fusion_metadata = fusion_metadata
        job.audio_path = audio_path
        job.subtitle_path = subtitle_path
        job.video_path = video_path
        job.highlight_segments = highlight_segments_result
        job.keyframes_extracted = keyframes_extracted
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


async def fetch_transcripts_with_segments(video_ids: list):
    """
    Fetch transcripts for multiple videos in parallel.
    Returns BOTH flat text and raw segments with timestamps.

    Uses the 3-tier transcript service (YouTube API → yt-dlp → Whisper).

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
            result = await service.get_transcript(video_id)
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
