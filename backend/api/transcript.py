"""
Transcript API routes
"""
from typing import List
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from ..services.transcript_service import (
    TranscriptService,
    get_transcript_service,
    extract_video_id,
)

router = APIRouter(prefix="/api/v1/transcript", tags=["transcript"])


class SummarizeRequest(BaseModel):
    text: str
    max_length: int = 150
    min_length: int = 50


@router.get("")
async def get_transcript(
    videoId: str = Query(..., description="YouTube video ID or URL"),
):
    """
    Fetch transcript for a YouTube video.

    Accepts both video IDs and full YouTube URLs.
    Uses 3-tier fallback: YouTube API → yt-dlp → Whisper.
    """
    service = await get_transcript_service()
    result = await service.get_transcript(videoId)

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Transcript not available for this video"
        )

    return result


@router.post("/summarize")
async def summarize_text(request: SummarizeRequest):
    """Summarize transcript text"""
    service = await get_transcript_service()
    summary = service.summarize(
        request.text,
        max_length=request.max_length,
        min_length=request.min_length
    )
    return {"summary": summary}


@router.delete("/cache")
async def clear_transcript_cache(
    videoId: str = Query(None, description="Specific video ID to clear, or omit to clear all"),
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
async def compile_highlights(request: CompileRequest):
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
