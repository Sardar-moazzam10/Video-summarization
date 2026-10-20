"""Server-side YouTube Data API proxy used by the video search pages."""

import httpx
import re
from fastapi import APIRouter, HTTPException, Query

from ..services.media_probe import prime_duration_cache

from ..core.config import get_settings


router = APIRouter(prefix="/api/v1/youtube", tags=["youtube"])

_ISO_DURATION = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")

def _duration_seconds(value):
    match = _ISO_DURATION.match(str(value or ""))
    if not match:
        return None
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    total = hours * 3600 + minutes * 60 + seconds
    return float(total) if total > 0 else None


@router.get("/search")
async def search_videos(
    q: str = Query(..., min_length=1, max_length=200),
    duration: str = Query("any", pattern="^(any|short|medium|long)$"),
    max_results: int = Query(20, ge=1, le=50),
    license: str = Query("any", pattern="^(any|creativeCommon|youtube)$"),
    include_rights: bool = Query(False, description="Whether to enrich items with status.license from videos.list"),
):
    api_key = get_settings().REACT_APP_YOUTUBE_API_KEY.strip()
    if not api_key:
        raise HTTPException(503, "YouTube search is not configured on the server.")

    params = {
        "part": "snippet",
        "q": q,
        "type": "video",
        "videoDuration": duration,
        "maxResults": max_results,
        "key": api_key,
    }
    license_val = license.default if hasattr(license, "default") else license
    if license_val and license_val != "any":
        params["videoLicense"] = license_val

    # Support both FastAPI dependency injection and direct function calls in tests
    is_rights_enabled = include_rights is True
    if hasattr(include_rights, "default"):
        is_rights_enabled = include_rights.default is True

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params=params,
            )

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

            data = response.json()
            items = data.get("items", [])

            # Opt-in Rights Enrichment: one batched call to videos.list(part=status)
            if is_rights_enabled and items:
                video_ids = [
                    item["id"]["videoId"]
                    for item in items
                    if isinstance(item.get("id"), dict) and item["id"].get("videoId")
                ]
                if video_ids:
                    videos_resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/videos",
                        params={
                            "part": "status,contentDetails",
                            "id": ",".join(video_ids),
                            "key": api_key,
                        },
                    )
                    status_map = {}
                    duration_map = {}
                    if not videos_resp.is_error:
                        for v_item in videos_resp.json().get("items", []):
                            raw_id = v_item.get("id")
                            vid_str = raw_id if isinstance(raw_id, str) else (raw_id.get("videoId") if isinstance(raw_id, dict) else None)
                            if vid_str:
                                status_map[vid_str] = v_item.get("status", {}).get("license")
                                seconds = _duration_seconds(v_item.get("contentDetails", {}).get("duration"))
                                if seconds:
                                    duration_map[vid_str] = seconds
                                    prime_duration_cache(vid_str, seconds)

                    # A failed or incomplete videos.list response is explicit
                    # unverified evidence; the search filter alone grants nothing.
                    for item in items:
                        vid = item.get("id", {}).get("videoId")
                        raw_lic = status_map.get(vid)
                        if duration_map.get(vid):
                            item["duration_seconds"] = duration_map[vid]
                        if raw_lic == "creativeCommon":
                            item["rights"] = {
                                "youtube_license": "creativeCommon",
                                "license_identifier": "CC BY (YouTube)",
                                "license_version": None,
                                "attribution_required": True,
                                "verified_metadata": True,
                            }
                        elif raw_lic == "youtube":
                            item["rights"] = {
                                "youtube_license": "youtube",
                                "license_identifier": "YouTube Standard",
                                "license_version": None,
                                "attribution_required": False,
                                "verified_metadata": True,
                            }
                        else:
                            item["rights"] = {
                                "youtube_license": None,
                                "license_identifier": None,
                                "license_version": None,
                                "attribution_required": False,
                                "verified_metadata": False,
                            }

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

    return {"items": items}
