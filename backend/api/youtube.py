"""Server-side YouTube Data API proxy used by the video search pages."""

import httpx
from fastapi import APIRouter, HTTPException, Query

from ..core.config import get_settings


router = APIRouter(prefix="/api/v1/youtube", tags=["youtube"])


@router.get("/search")
async def search_videos(
    q: str = Query(..., min_length=1, max_length=200),
    duration: str = Query("any", pattern="^(any|short|medium|long)$"),
    max_results: int = Query(20, ge=1, le=50),
):
    api_key = get_settings().REACT_APP_YOUTUBE_API_KEY.strip()
    if not api_key:
        raise HTTPException(503, "YouTube search is not configured on the server.")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "q": q,
                    "type": "video",
                    "videoDuration": duration,
                    "maxResults": max_results,
                    "key": api_key,
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(502, "Could not connect to YouTube. Please try again.") from exc

    if response.is_error:
        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {}
        reason = next(
            (item.get("reason") for item in error.get("errors", []) if item.get("reason")),
            None,
        )
        if reason in {"quotaExceeded", "dailyLimitExceeded"}:
            detail = "YouTube search quota has been reached. Please try again later."
        elif reason in {"keyInvalid", "accessNotConfigured"}:
            detail = "YouTube search is not configured correctly."
        else:
            detail = error.get("message") or "YouTube search failed. Please try again."
        raise HTTPException(response.status_code, detail)

    return {"items": response.json().get("items", [])}
