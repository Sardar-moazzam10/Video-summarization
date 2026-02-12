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

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.responses import FileResponse, StreamingResponse
from typing import Optional, Dict, Any
import asyncio
import json
from datetime import datetime
import os

from ..models.job import (
    MergeJobCreate,
    MergeJob,
    MergeJobResponse,
    MergeJobResult,
    JobStatus,
    FusionMetadata,
    RichOutput,
    get_duration_style,
    DURATION_CONFIGS,
)
from ..services.duration_profiles import get_all_profiles, get_profile
from ..services.fusion_engine import get_fusion_engine
from ..core.database import get_database
from ..core.config import get_settings

router = APIRouter(prefix="/api/v1/merge", tags=["merge"])
settings = get_settings()


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

    # Create job
    job = MergeJob(
        video_ids=request.video_ids,
        target_duration_minutes=request.target_duration_minutes,
        duration_style=get_duration_style(request.target_duration_minutes),
        voice_id=request.voice_id,
        generate_audio=request.generate_audio,
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

    if job_data["status"] != JobStatus.COMPLETED.value:
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
        "subtitle_url": f"/api/v1/merge/{job_id}/subtitles" if job_data.get("subtitle_path") else None,
        "metadata": job_data.get("fusion_metadata", {}),
        "created_at": job_data["created_at"],
        "completed_at": job_data.get("completed_at"),
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
        pdf_bytes = generate_pdf(summary_text, rich_output)
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

        transcripts = await fetch_transcripts(job.video_ids)

        await update_status(
            JobStatus.TRANSCRIBING,
            30,
            f"Fetched {len(transcripts)} transcripts"
        )

        if not transcripts:
            raise Exception("Could not fetch any transcripts")

        # Index transcripts in FAISS for semantic search (best-effort)
        try:
            from ..services.vector_store import get_vector_store
            store = get_vector_store()
            for vid, text in transcripts.items():
                if not store.is_video_indexed(vid):
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

        # STAGE 4.5: Gemini AI Enrichment (80-90%)
        rich_output = None
        try:
            from ..services.gemini_service import get_gemini_service
            gemini = get_gemini_service()

            if gemini.is_available():
                await update_status(
                    JobStatus.ENRICHING,
                    82,
                    "AI enriching with Gemini (chapters, takeaways, quotes)..."
                )

                # Gather video titles for context
                video_titles = ", ".join(
                    seg.title or seg.video_id
                    for seg in job.segments
                ) if job.segments else ", ".join(job.video_ids)

                # Send FULL narrative to Gemini (bypassing BART's chunking loss)
                gemini_result = await gemini.generate_rich_summary(
                    narrative=fusion_result.narrative,
                    target_words=target_words,
                    style=job.style,
                    video_titles=video_titles,
                )

                # If Gemini produced a summary, use it over BART's
                if gemini_result.summary and len(gemini_result.summary.split()) > 50:
                    summary_text = gemini_result.summary
                    print(f"[Gemini] Using Gemini summary ({len(summary_text.split())} words)")

                rich_output = RichOutput(
                    summary=summary_text,
                    key_takeaways=gemini_result.key_takeaways,
                    best_quotes=[
                        {"text": q["text"], "speaker": q.get("speaker", "")}
                        for q in gemini_result.best_quotes
                    ] if gemini_result.best_quotes else [],
                    chapters=[
                        {"title": ch["title"], "text": ch["text"]}
                        for ch in gemini_result.chapters
                    ] if gemini_result.chapters else [],
                    who_should_watch=gemini_result.who_should_watch,
                    who_can_skip=gemini_result.who_can_skip,
                    action_steps=gemini_result.action_steps,
                    tldr=gemini_result.tldr,
                    style_applied=gemini_result.style_applied,
                )

                await update_status(
                    JobStatus.ENRICHING,
                    90,
                    f"AI enrichment complete: {len(rich_output.chapters)} chapters, "
                    f"{len(rich_output.key_takeaways)} takeaways"
                )
            else:
                print("[Gemini] Not available — using BART summary only")
                rich_output = RichOutput(summary=summary_text, style_applied=job.style)

        except Exception as e:
            print(f"[WARN] Gemini enrichment failed (using BART fallback): {e}")
            rich_output = RichOutput(summary=summary_text, style_applied=job.style)

        # STAGE 5: Voice Generation (90-97%) - Optional (FREE with Edge TTS)
        audio_path = None
        subtitle_path = None
        if job.generate_audio:
            await update_status(
                JobStatus.GENERATING_VOICE,
                92,
                "Generating AI voice narration + subtitles (FREE Edge TTS)..."
            )

            try:
                from ..services.voice_service import get_voice_service
                voice_service = get_voice_service()

                # Use the specified voice or default
                voice_key = job.voice_id or "aria"

                # Format text for better narration
                narration_text = voice_service.format_for_narration(summary_text)

                # Generate audio + subtitles
                audio_dir = "audio_cache"
                os.makedirs(audio_dir, exist_ok=True)
                audio_path = os.path.join(audio_dir, f"summary_{job_id}.mp3")
                subtitle_path = os.path.join(audio_dir, f"summary_{job_id}.srt")

                try:
                    await voice_service.generate_audio_with_subtitles(
                        text=narration_text,
                        audio_path=audio_path,
                        subtitle_path=subtitle_path,
                        voice_key=voice_key,
                    )
                    print(f"[OK] Generated FREE audio + subtitles for job {job_id}")
                except Exception as sub_err:
                    print(f"[WARN] Subtitle generation failed, falling back to audio-only: {sub_err}")
                    subtitle_path = None
                    await voice_service.generate_audio_file(
                        text=narration_text,
                        output_path=audio_path,
                        voice_key=voice_key
                    )

            except Exception as e:
                print(f"[WARN] Voice generation failed (continuing without audio): {e}")
                audio_path = None
                subtitle_path = None

            await update_status(
                JobStatus.GENERATING_VOICE,
                97,
                "Voice generation complete"
            )

        # COMPLETED
        job.status = JobStatus.COMPLETED
        job.progress_percent = 100
        job.stage_message = "Your summary is ready!"
        job.summary_text = summary_text
        job.rich_output = rich_output
        job.fusion_metadata = fusion_metadata
        job.audio_path = audio_path
        job.subtitle_path = subtitle_path
        job.completed_at = datetime.utcnow()

        rich_output_dict = rich_output.model_dump() if rich_output else None

        await jobs_collection.update_one(
            {"job_id": job_id},
            {"$set": {
                "status": JobStatus.COMPLETED.value,
                "progress_percent": 100,
                "stage_message": "Your summary is ready!",
                "summary_text": summary_text,
                "rich_output": rich_output_dict,
                "fusion_metadata": fusion_metadata.model_dump(),
                "audio_path": audio_path,
                "subtitle_path": subtitle_path,
                "completed_at": job.completed_at,
            }}
        )

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


async def fetch_transcripts(video_ids: list) -> Dict[str, str]:
    """
    Fetch transcripts for multiple videos in parallel.

    Uses the 3-tier transcript service (YouTube API → yt-dlp → Whisper).
    Handles both video IDs and full YouTube URLs.
    """
    from ..services.transcript_service import get_transcript_service, extract_video_id

    service = await get_transcript_service()

    async def _fetch_one(raw_id: str):
        video_id = extract_video_id(raw_id)
        try:
            result = await service.get_transcript(video_id)
            if result and result.get("transcript"):
                source = result.get("source", "unknown")
                if isinstance(result["transcript"], list):
                    text = " ".join(
                        seg.get("text", "") for seg in result["transcript"]
                    )
                else:
                    text = str(result["transcript"])

                if text.strip():
                    print(f"[Merge] Got transcript for {video_id} via {source} ({len(text.split())} words)")
                    return (video_id, text)
        except Exception as e:
            print(f"[WARN] Could not fetch transcript for {video_id}: {e}")
        return None

    results = await asyncio.gather(*[_fetch_one(raw_id) for raw_id in video_ids])
    return {vid: text for vid, text in results if vid is not None}
