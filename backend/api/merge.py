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

    # Create job
    job = MergeJob(
        video_ids=request.video_ids,
        target_duration_minutes=request.target_duration_minutes,
        duration_style=get_duration_style(request.target_duration_minutes),
        voice_id=request.voice_id,
        generate_audio=request.generate_audio,
        generate_video=request.generate_video,
        highlight_duration_seconds=request.highlight_duration_seconds,
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
        "highlight_segments": job_data.get("highlight_segments", []),
        "keyframes_extracted": job_data.get("keyframes_extracted", {}),
        "warning": job_data.get("warning"),
        "error": job_data.get("error"),
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
# HELPERS
# =====================================================

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
                        transcripts[vid] = _nllb_translate(transcripts[vid], src_lang=lang)
                        print(f"[Transcript] NLLB translation: {vid} ({lang} → en)")
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
        try:
            from ..services.ollama_service import get_ollama_service
            ollama = get_ollama_service()

            if ollama.is_available():
                await update_status(
                    JobStatus.ENRICHING,
                    82,
                    f"AI enriching with Ollama/{settings.OLLAMA_MODEL} (chapters, takeaways, quotes)..."
                )

                video_titles = ", ".join(job.video_ids)
                rich_output = await ollama.generate_rich_summary(
                    narrative=fusion_result.narrative,
                    target_words=target_words,
                    style=job.style,
                    video_titles=video_titles,
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

        except Exception as e:
            print(f"[WARN] Ollama enrichment failed: {e}")

        # Always fall back to local TF-IDF if Ollama produced no structured output
        if not rich_output or not rich_output.tldr or not rich_output.key_takeaways:
            print("[LocalEnrich] Generating TLDR+takeaways locally (TF-IDF)...")
            rich_output = _generate_local_enrichment(summary_text, job.style)

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
                from ..services.visual_keyframe_extractor import extract_keyframes
                from ..services.clip_feature_extractor import augment_keyframes_with_clip
                from ..services.segment_extractor import extract_highlight_segments

                video_svc = get_video_service()

                # Step 1: Download source videos
                await update_status(
                    JobStatus.GENERATING_VIDEO, 97,
                    "Downloading source videos for highlight extraction..."
                )
                unique_video_ids = list(raw_segments.keys())

                async def video_progress(msg):
                    await update_status(JobStatus.GENERATING_VIDEO, 98, msg)

                video_paths = await video_svc.download_videos(
                    unique_video_ids, job_id=job_id, progress_callback=video_progress
                )

                if not video_paths:
                    raise Exception("Could not download any source videos")

                all_highlights = []
                per_video_seconds = job.highlight_duration_seconds // max(len(video_paths), 1)

                for vid, vid_path in video_paths.items():
                    segs = raw_segments.get(vid, [])
                    if not segs:
                        continue

                    # Step 2a: Extract keyframes + temporal scores (PySceneDetect + PGL-SUM)
                    await update_status(
                        JobStatus.GENERATING_VIDEO, 98,
                        f"Extracting keyframes + temporal attention for {vid}..."
                    )
                    visual_keyframes = await asyncio.to_thread(
                        extract_keyframes, vid, vid_path
                    )
                    keyframes_extracted[vid] = len(visual_keyframes)

                    # Step 2b: Add CLIP cross-modal scores (requires summary_text, available now)
                    if visual_keyframes:
                        await asyncio.to_thread(
                            augment_keyframes_with_clip, visual_keyframes, summary_text
                        )
                        print(
                            f"[Video] {vid}: {len(visual_keyframes)} keyframes "
                            f"→ CLIP + temporal scores ready"
                        )

                    # Step 2c: Score and select highlight segments (4-signal blend)
                    highlights = extract_highlight_segments(
                        video_id=vid,
                        transcript_segments=segs,
                        summary_text=summary_text,
                        target_duration_seconds=per_video_seconds,
                        context_padding_seconds=2.0,
                        visual_keyframes=visual_keyframes or None,
                    )
                    all_highlights.extend(highlights)

                if all_highlights:
                    # Sort by importance, trim to duration budget, then sort chronologically
                    all_highlights.sort(
                        key=lambda h: h.get("importance_score", 0), reverse=True
                    )
                    highlight_segments_result = _fit_to_duration(
                        all_highlights, job.highlight_duration_seconds
                    )
                    highlight_segments_result.sort(
                        key=lambda h: (h["video_id"], h["start_time"])
                    )

                    # Step 3: Generate the highlight reel
                    await update_status(
                        JobStatus.GENERATING_VIDEO, 99,
                        f"Cutting and stitching {len(highlight_segments_result)} highlight clips..."
                    )

                    video_path = await video_svc.generate_highlight_reel(
                        job_id=job.job_id,
                        highlight_segments=highlight_segments_result,
                        video_paths=video_paths,
                        audio_path=audio_path if job.generate_audio else None,
                        progress_callback=video_progress,
                    )

                    print(f"[Video] Highlight reel generated: {video_path}")
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
