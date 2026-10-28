"""
VidFusion Reel Studio API Endpoints.
Enables generating 9:16 vertical shorts/reels from completed jobs.
"""
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..core.database import get_database
from ..core.security import get_current_user_optional
from ..services.reel_service import get_reel_service

router = APIRouter(prefix="/api/v1/reel", tags=["Reel Studio"])


class RenderReelRequest(BaseModel):
    candidate_idx: int = Field(0, description="Index of the chosen highlight moment (0-3)")
    audio_mode: str = Field("original", pattern="^(original|voiceover)$", description="Audio track mode")
    voice_language: str = Field("en", pattern="^(en|ur|hi)$", description="Voice language if voiceover is selected")


class CandidateItem(BaseModel):
    id: str
    index: int
    title: str
    text: str
    start_time: float
    duration_seconds: float
    video_id: str
    is_cc_by: bool
    license_label: str
    safe_to_export: bool


class ReelCandidatesResponse(BaseModel):
    job_id: str
    candidates: List[CandidateItem]


@router.get("/{job_id}/candidates", response_model=ReelCandidatesResponse)
async def get_candidates(
    job_id: str,
    current_user: Optional[dict] = Depends(get_current_user_optional),
):
    """
    Get top 3-4 viral moments available for 9:16 reel generation from this job.
    """
    db = await get_database()
    job = await db["jobs"].find_one({"job_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    svc = get_reel_service()
    candidates = svc.get_reel_candidates(job)
    return ReelCandidatesResponse(job_id=job_id, candidates=candidates)


@router.post("/{job_id}/render")
async def render_reel_endpoint(
    job_id: str,
    payload: RenderReelRequest,
    current_user: Optional[dict] = Depends(get_current_user_optional),
):
    """
    Render a 9:16 vertical reel from the selected moment.
    """
    db = await get_database()
    job = await db["jobs"].find_one({"job_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    svc = get_reel_service()
    try:
        result = await svc.render_reel(
            job_id=job_id,
            job_data=job,
            candidate_idx=payload.candidate_idx,
            audio_mode=payload.audio_mode,
            voice_lang=payload.voice_language,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render reel: {str(e)}")


@router.get("/{job_id}/download/{reel_id}")
async def download_or_stream_reel(
    job_id: str,
    reel_id: str,
    download: bool = Query(False, description="Whether to trigger download attachment"),
):
    """
    Stream or download the generated 9:16 MP4 reel.
    """
    filename = f"reel_{job_id}_{reel_id}.mp4"
    reel_path = Path("audio_cache/reels") / filename

    if not reel_path.exists():
        raise HTTPException(status_code=404, detail="Reel video not found or not rendered yet")

    return FileResponse(
        str(reel_path),
        media_type="video/mp4",
        filename=f"vidfusion_reel_{job_id[:8]}.mp4" if download else None,
        content_disposition_type="attachment" if download else "inline",
    )

