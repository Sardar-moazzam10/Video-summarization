"""
Transcript API routes
"""
import asyncio
import hashlib
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from ..services.transcript_service import (
    get_transcript_service,
    extract_video_id,
)
from ..core.security import get_current_user, require_role
from ..core.redis_queue import get_redis_pool

router = APIRouter(prefix="/api/v1/transcript", tags=["transcript"])


class SummarizeRequest(BaseModel):
    text: str
    max_length: int = 150
    min_length: int = 50


@router.get("")
async def get_transcript(
    videoId: str = Query(..., description="YouTube video ID or URL"),
    allow_whisper: bool = Query(True, description="Whether to fall back to Whisper STT"),
    fast_search: bool = Query(False, description="Fast path for keyword search: English captions only, no Whisper/translation/download"),
    _user: dict = Depends(get_current_user),
):
    """
    Fetch transcript for a YouTube video.

    Accepts both video IDs and full YouTube URLs.
    Uses 3-tier fallback: YouTube API → yt-dlp → Whisper.
    When fast_search=True, uses fast English-only caption path without fallback or audio processing.
    """
    service = await get_transcript_service()
    result = await service.get_transcript(
        videoId,
        allow_whisper=allow_whisper,
        fast_search=fast_search,
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Transcript not available for this video"
        )

    return result


@router.post("/summarize")
async def summarize_text(request: SummarizeRequest, _user: dict = Depends(get_current_user)):
    """Summarize transcript text using threadpool execution and Redis cache."""
    cache_key = None
    pool = None
    try:
        pool = await get_redis_pool()
        if pool is not None:
            text_hash = hashlib.sha256(request.text.strip().encode("utf-8")).hexdigest()
            cache_key = f"quick_summary:{text_hash}:{request.max_length}:{request.min_length}"
            cached = await pool.get(cache_key)
            if cached:
                cached_text = cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
                return {"summary": cached_text}
    except Exception:
        pass

    service = await get_transcript_service()
    summary = await asyncio.to_thread(
        service.summarize,
        request.text,
        max_length=request.max_length,
        min_length=request.min_length
    )

    if pool is not None and cache_key is not None and summary:
        try:
            await pool.set(cache_key, summary, ex=86400)
        except Exception:
            pass

    return {"summary": summary}


@router.delete("/cache")
async def clear_transcript_cache(
    videoId: str = Query(None, description="Specific video ID to clear, or omit to clear all"),
    _admin: dict = Depends(require_role("admin")),
):
    """
    Clear cached transcripts so they get re-fetched in English.

    - Pass videoId to clear a specific video's cache
    - Omit videoId to clear all cached transcripts
    """
    service = await get_transcript_service()
    vid = extract_video_id(videoId) if videoId else None

    if vid:
        result = await service.transcripts.delete_one({"video_id": vid})
        return {"message": f"Cleared cache for {vid}", "deleted": result.deleted_count}
    else:
        result = await service.transcripts.delete_many({})
        return {"message": "Cleared all transcript cache", "deleted": result.deleted_count}


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "service": "transcript"}


class CompileRequest(BaseModel):
    video_id: str
    summary_text: str = ""
    highlight_duration_seconds: int = 120
    context_padding_seconds: float = 3.0


class CompileResponse(BaseModel):
    video_id: str
    segments: List[dict]
    total_duration_seconds: float
    segment_count: int


@router.post("/compile", response_model=CompileResponse)
async def compile_highlights(request: CompileRequest, _user: dict = Depends(get_current_user)):
    """
    Extract highlight segments from a video by aligning its summary
    with transcript timestamps.

    Returns ranked segments with start/end times, ready to forward
    to POST /api/v1/merge with generate_video=true.
    """
    from ..services.segment_extractor import extract_highlight_segments

    video_id = extract_video_id(request.video_id)

    service = await get_transcript_service()
    result = await service.get_transcript(video_id)

    if not result or not result.get("transcript"):
        raise HTTPException(
            status_code=404,
            detail=f"Transcript not available for video: {video_id}"
        )

    transcript_segments = result["transcript"]

    if not isinstance(transcript_segments, list):
        raise HTTPException(
            status_code=422,
            detail="Transcript has no timestamps. Delete its cache and re-fetch the video."
        )

    segments = extract_highlight_segments(
        video_id=video_id,
        transcript_segments=transcript_segments,
        summary_text=request.summary_text,
        target_duration_seconds=request.highlight_duration_seconds,
        context_padding_seconds=request.context_padding_seconds,
    )

    total_duration = sum(s["end_time"] - s["start_time"] for s in segments)

    return CompileResponse(
        video_id=video_id,
        segments=segments,
        total_duration_seconds=round(total_duration, 2),
        segment_count=len(segments),
    )
