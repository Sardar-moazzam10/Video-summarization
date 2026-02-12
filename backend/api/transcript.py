"""
Transcript API routes
"""
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
