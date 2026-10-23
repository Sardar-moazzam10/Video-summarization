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

from ..services.acquisition_service import create_shadow_job_decisions, set_observation_context, reset_observation_context, finalize_shadow_manifest, append_event, load_job_decision_ids
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
from typing import Any, Dict, List, Literal, Optional, Callable, Awaitable
import asyncio
import json
import logging
from datetime import datetime
import os
from time import perf_counter
from pydantic import BaseModel, Field

from ..models.job import (
    MergeJobCreate,
    MergeJob,
    MergeJobResponse,
    JobStatus,
    FusionMetadata,
    RichOutput,
    get_duration_style,
)
from ..models.output_contracts import (
    ComponentStatus,
    OutputComponentState,
    derive_output_status,
)
from ..services.duration_profiles import (
    DURATION_PROFILES, get_all_profiles, get_profile,
)
from ..services.media_probe import format_duration, get_durations
from ..services.transcript_service import extract_video_id
from ..services.fusion_engine import get_fusion_engine
from ..core.database import get_database
from ..core.config import get_settings
from ..core.security import (
    create_media_token,
    get_current_user,
    get_current_user_optional,
    verify_media_token,
)

router = APIRouter(prefix="/api/v1/merge", tags=["merge"])
settings = get_settings()
logger = logging.getLogger(__name__)


# =====================================================
# LOCAL TF-IDF ENRICHMENT
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


def _generate_local_enrichment(summary_text: str, style: str, content_plan=None, embedder=None) -> RichOutput:
    """
    Backward-compatible wrapper for deterministic content-aware enrichment.
    """
    from ..services.content_intelligence import enrich_summary
    if content_plan is None:
        from ..services.content_intelligence import build_content_plan
        import re
        fallback_evidence = [
            {"video_id": "summary", "start_time": index, "end_time": index + 1,
             "order": index, "text": sentence}
            for index, sentence in enumerate(re.split(r"(?<=[.!?])\s+", summary_text.strip()))
            if sentence.strip()
        ]
        content_plan = build_content_plan(fallback_evidence, "explanatory", 0.0)
    output, _topics = enrich_summary(summary_text, content_plan, style, embedder=embedder)
    return output


# =====================================================
# IN-MEMORY JOB TRACKING (for quick access)
# Jobs are also persisted to MongoDB
# =====================================================
_active_jobs: Dict[str, MergeJob] = {}


def _component_state(value, *, default_status=ComponentStatus.QUEUED) -> OutputComponentState:
    """Read new component state while remaining compatible with old job rows."""
    if isinstance(value, OutputComponentState):
        return value
    if isinstance(value, dict):
        return OutputComponentState.model_validate(value)
    return OutputComponentState(status=default_status)


def _output_state_payload(value) -> Dict[str, Any]:
    """Return component states plus their independently derived presentation state."""
    def _field(name, default=None):
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    raw_status = _field("status")
    job_status = raw_status.value if hasattr(raw_status, "value") else str(raw_status or "")
    generate_video = bool(_field("generate_video", False))
    has_video = bool(_field("video_path"))
    has_summary = bool(_field("summary_text"))
    summary_unavailable = bool(_field("summary_unavailable", False))

    if not generate_video:
        video_default = ComponentStatus.NOT_REQUESTED
    elif job_status in ("completed", "partial_success", "video_ready") and has_video:
        video_default = ComponentStatus.READY
    elif job_status in ("completed", "partial_success") and not has_video:
        video_default = ComponentStatus.FAILED
    elif job_status == "error":
        video_default = ComponentStatus.FAILED
    elif job_status == "cancelled":
        video_default = ComponentStatus.CANCELLED
    else:
        video_default = ComponentStatus.QUEUED

    if job_status in ("completed", "partial_success") and has_summary:
        text_default = ComponentStatus.READY
    elif job_status in ("completed", "partial_success") and (summary_unavailable or not has_summary):
        text_default = ComponentStatus.FAILED
    elif job_status == "error":
        text_default = ComponentStatus.FAILED
    elif job_status == "cancelled":
        text_default = ComponentStatus.CANCELLED
    else:
        text_default = ComponentStatus.QUEUED

    video = _component_state(
        _field("video_component"),
        default_status=video_default,
    )
    text = _component_state(
        _field("text_component"),
        default_status=text_default,
    )

    if job_status in ("completed", "partial_success"):
        if has_summary and text.status in (ComponentStatus.QUEUED, ComponentStatus.RUNNING):
            text = OutputComponentState(status=ComponentStatus.READY, stage="ready", progress_percent=100)
        if generate_video and has_video and video.status in (ComponentStatus.QUEUED, ComponentStatus.RUNNING):
            video = OutputComponentState(status=ComponentStatus.READY, stage="ready", progress_percent=100)

    return {
        "output_status": derive_output_status(video, text),
        "video_component": video,
        "text_component": text,
    }


def _resolve_intent_contract(value, source_count: Optional[int] = None) -> Dict[str, Any]:
    """Resolve canonical intent while keeping legacy API/jobs readable.

    Explicit ``summary_scope`` is authoritative. Only callers/jobs that do not
    provide it use the old ``query``/``selected_keywords`` keyword inference.
    Source scope is derived from the canonical source list, never trusted from
    a potentially stale client payload.
    """
    explicit_scope = getattr(value, "summary_scope", None)
    selected_keywords = [
        str(item).strip()
        for item in (getattr(value, "selected_keywords", None) or [])
        if str(item).strip()
    ]
    legacy_query = str(getattr(value, "query", None) or "").strip() or None
    summary_query = str(getattr(value, "summary_query", None) or "").strip() or None
    discovery_query = str(getattr(value, "discovery_query", None) or "").strip() or None

    if explicit_scope in {"overall", "keyword"}:
        summary_scope = explicit_scope
    else:
        summary_scope = "keyword" if (summary_query or selected_keywords or legacy_query) else "overall"

    if summary_scope == "keyword":
        summary_query = summary_query or (" ".join(selected_keywords) if selected_keywords else legacy_query)
    else:
        summary_query = None

    if source_count is None:
        source_count = len(getattr(value, "video_ids", None) or [])

    return {
        "summary_scope": summary_scope,
        "source_scope": "single" if source_count == 1 else "multi",
        "discovery_query": discovery_query,
        "summary_query": summary_query,
        "selected_keywords": selected_keywords,
    }


def _semantic_intent_terms(job) -> List[str]:
    """Return semantic constraints only for resolved keyword jobs."""
    intent = _resolve_intent_contract(job)
    if intent["summary_scope"] != "keyword":
        return []
    terms = intent["selected_keywords"]
    if not terms and intent["summary_query"]:
        terms = [intent["summary_query"]]
    return list(dict.fromkeys(terms))


def _final_per_video_metrics(
    manifest,
    global_segments,
    raw_segments,
    concepts,
    selection_result,
) -> Dict[str, Dict[str, Any]]:
    """Describe source usage from the frozen final manifest only."""
    result = {}
    for vid in raw_segments:
        vid_candidates = [
            segment for segment in global_segments
            if getattr(segment, "video_id", "") == vid
        ]
        vid_clips = [clip for clip in manifest if clip.video_id == vid]
        result[vid] = {
            "candidates": len(vid_candidates),
            "selected": len(vid_clips),
            "seconds": round(sum(clip.end_time - clip.start_time for clip in vid_clips), 1),
            "budget": 0.0,
            "concepts_found": len(concepts),
            "concepts_covered": list(dict.fromkeys(
                concept for clip in vid_clips for concept in clip.covered_concepts
            )),
            "concept_signal": selection_result.concept_signal,
            "concepts_omitted_for_budget": selection_result.concepts_omitted_for_budget,
        }
    return result


async def get_jobs_collection():
    """Get MongoDB jobs collection."""
    db = await get_database()
    return db["jobs"]


def _assert_job_owner(job_data: dict, principal: dict) -> None:
    """Deny cross-account job access without revealing that the job exists."""
    if principal.get("role") == "admin":
        return
    if not job_data.get("user_id") or job_data.get("user_id") != principal.get("sub"):
        raise HTTPException(404, "Job not found")


async def _get_owned_job(job_id: str, principal: dict) -> dict:
    jobs_collection = await get_jobs_collection()
    job_data = await jobs_collection.find_one({"job_id": job_id})
    if not job_data:
        raise HTTPException(404, "Job not found")
    _assert_job_owner(job_data, principal)
    return job_data


def _job_error(job_data: dict) -> Optional[str]:
    """Read the canonical error field with narrow legacy DB compatibility."""
    return job_data.get("error") or job_data.get("error_message")


async def _get_media_job(
    job_id: str,
    media_kind: str,
    token: Optional[str],
    principal: Optional[dict],
) -> dict:
    jobs_collection = await get_jobs_collection()
    job_data = await jobs_collection.find_one({"job_id": job_id})
    if not job_data:
        raise HTTPException(404, "Job not found")
    if token and verify_media_token(token, job_id, media_kind):
        return job_data
    if principal:
        _assert_job_owner(job_data, principal)
        return job_data
    raise HTTPException(401, "Authentication required")


def _media_capabilities(job_data: dict) -> dict:
    """Derive preview/export capabilities without changing the frozen snapshot."""
    snapshot = job_data.get("rights_snapshot")
    if not snapshot or snapshot.get("snapshot_origin") != "job_evaluation":
        return {
            "generated_summary_visible": False,
            "copy_summary_allowed": False,
            "txt_export_allowed": False,
            "pdf_export_allowed": False,
            "preview_allowed": False,
            "download_allowed": False,
            "public_export_allowed": False,
        }
    aggregate = snapshot.get("aggregate") or {}
    status = aggregate.get("publication_gate_status")
    if status == "eligible_by_recorded_rights":
        return {
            "generated_summary_visible": True,
            "copy_summary_allowed": True,
            "txt_export_allowed": True,
            "pdf_export_allowed": True,
            "preview_allowed": True,
            "download_allowed": True,
            "public_export_allowed": True,
        }

    sources = snapshot.get("sources") or []
    standard_preview = bool(sources) and all(
        source.get("publication_gate_status") == "eligible_by_recorded_rights"
        or (
            source.get("publication_gate_status") == "restricted_by_product_policy"
            and source.get("verification_status") == "verified_metadata"
            and ((source.get("evidence") or {}).get("platform") or {}).get("status_license") == "youtube"
        )
        for source in sources
    )
    return {
        "generated_summary_visible": standard_preview,
        "copy_summary_allowed": standard_preview,
        "txt_export_allowed": standard_preview,
        "pdf_export_allowed": standard_preview,
        "preview_allowed": bool(
            status == "restricted_by_product_policy" and standard_preview
        ),
        "download_allowed": False,
        "public_export_allowed": False,
    }


def _media_delivery_allowed(job_data: dict) -> bool:
    """Backward-compatible name for unrestricted media delivery only."""
    return _media_capabilities(job_data)["download_allowed"]


def _assert_media_capability(job_data: dict, capability: str) -> None:
    if not _media_capabilities(job_data).get(capability, False):
        raise HTTPException(
            403,
            "This media action is blocked by the recorded rights policy.",
        )


async def _freeze_job_rights(job: MergeJob, jobs_collection) -> dict:
    """Persist a write-once snapshot and mirror its aggregate on the in-memory job."""
    from ..services.rights_service import freeze_job_rights_snapshot

    video_ids = getattr(job, "used_video_ids", None) or job.video_ids
    snapshot = await freeze_job_rights_snapshot(
        jobs_collection=jobs_collection,
        job_id=job.job_id,
        user_id=job.user_id or "anonymous",
        video_ids=video_ids,
    )
    aggregate = snapshot.get("aggregate") or {}
    job.rights_snapshot = snapshot
    job.publication_gate_status = aggregate.get(
        "publication_gate_status", "restricted_by_product_policy"
    )
    job.rights_summary = {
        "gate_status": job.publication_gate_status,
        "warnings": aggregate.get("warnings", []),
        "source_count": aggregate.get("source_count", 0),
    }
    return snapshot


# =====================================================
# ENDPOINTS
# =====================================================

@router.get("/profiles")
async def get_duration_profiles(_user: dict = Depends(get_current_user)):
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
    Core Invariant: requested_summary_duration < total_unique_selected_source_duration
    A summary must be strictly shorter than the source material it is made from.
    """
    return [m for m in sorted(DURATION_PROFILES) if m * 60 < source_seconds]


def _duration_error(source_seconds: float, requested_minutes: int) -> Dict:
    """Structured SUMMARY_DURATION_EXCEEDS_SOURCE payload."""
    allowed = eligible_durations(source_seconds)
    pretty = format_duration(source_seconds)
    if allowed:
        message = (
            f"Source is only {pretty} long. "
            f"{requested_minutes}-minute summary cannot be created from {pretty} of source content. "
            f"Please choose {max(allowed)} minutes or less."
        )
    else:
        message = (
            f"Source is only {pretty} long. A 5-minute summary requires more than 5 minutes of source content."
        )
    return {
        "code": "SUMMARY_DURATION_EXCEEDS_SOURCE",
        "error_code": "SUMMARY_DURATION_EXCEEDS_SOURCE",
        "message": message,
        "requested_seconds": int(requested_minutes * 60),
        "source_seconds": round(float(source_seconds), 1),
        "source_duration_seconds": round(float(source_seconds), 1),
        "requested_duration_minutes": int(requested_minutes),
        "max_allowed_minutes": max(allowed) if allowed else None,
        "allowed_durations": allowed,
    }


@router.get("/video-durations")
async def get_video_durations(
    video_ids: str,
    _user: dict = Depends(get_current_user),
):
    """
    Real media duration for each requested video, and which summary lengths
    that makes possible.

    The picker calls this once the user's selection is known so it can disable
    the impossible options with a reason, instead of letting them start a job
    that the API will refuse. Comma-separated ids, e.g.
    `/video-durations?video_ids=abc123,def456`.

    Frontend use is a convenience only — create_merge_job re-checks this
    server-side, so a client that skips or fakes the call gains nothing.
    Fails closed: if any video's duration cannot be verified, allowed_durations is empty
    and status is 'verification_failed'.
    """
    raw_ids = [v.strip() for v in (video_ids or "").split(",") if v.strip()]
    if not raw_ids:
        raise HTTPException(400, "At least one video_id is required")
    unique_ids = list(dict.fromkeys(raw_ids))
    if len(unique_ids) > 10:
        raise HTTPException(400, "Maximum 10 videos allowed")

    # Combined, because _allocate_budgets splits the reel across every source
    # in proportion to its length — the material available is the pool, not
    # any single video. Matching that here keeps validation and production
    # behaviour consistent for multi-video jobs.
    resolved = await asyncio.to_thread(get_durations, unique_ids)
    known = {vid: d for vid, d in resolved.items() if d is not None}
    unresolved = [vid for vid, d in resolved.items() if d is None]

    # Fail closed on partial resolution
    if len(known) != len(unique_ids):
        return {
            "status": "verification_failed",
            "durations": {vid: (round(d, 1) if d else None) for vid, d in resolved.items()},
            "unresolved": unresolved,
            "combined_duration_seconds": None,
            "combined_duration_label": None,
            "allowed_durations": [],
            "all_durations": sorted(DURATION_PROFILES),
            "message": "Source duration could not be verified for all selected videos.",
        }

    combined = float(sum(known.values()))
    allowed = eligible_durations(combined)
    status = "valid" if allowed else "too_short"

    return {
        "durations": {vid: (round(d, 1) if d else None) for vid, d in resolved.items()},
        "unresolved": [vid for vid, d in resolved.items() if not d],
        "status": status,
        "durations": {vid: round(d, 1) for vid, d in known.items()},
        "unresolved": [],
        "combined_duration_seconds": round(combined, 1),
        "combined_duration_label": format_duration(combined) if combined else None,
        "allowed_durations": eligible_durations(combined) if known else sorted(DURATION_PROFILES),
        "combined_duration_label": format_duration(combined),
        "allowed_durations": allowed,
        "all_durations": sorted(DURATION_PROFILES),
    }


@router.post("", response_model=MergeJobResponse)
async def create_merge_job(
    request: MergeJobCreate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
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
    # Deduplicate video IDs.
    clean_ids = list(dict.fromkeys(
        video_id for value in request.video_ids
        if (video_id := extract_video_id(value))
    ))
    if len(clean_ids) < 1:
        raise HTTPException(400, "At least 1 valid video required")
    if len(clean_ids) > 10:
        raise HTTPException(400, "Maximum 10 videos allowed")

    # Do not hard-reject a non-English caption transcript at create-time.
    # The implementation may still normalize it to canonical English via the
    # existing text-translation / Whisper translate flow before the terminal
    # unsupported-language decision is made.

    # Duration feasibility — checked BEFORE the job exists.
    # Fail closed: ALL unique videos must have their duration resolved.
    
    import uuid
    job_id = str(uuid.uuid4())
    dec_ids = await create_shadow_job_decisions(
        job_id=job_id,
        user_id=current_user.get("sub", "anonymous") if isinstance(current_user, dict) else "anonymous",
        source_ids=clean_ids,
    )
    acq_token = set_observation_context(
        job_id=job_id, user_id=current_user.get("sub", "anonymous") if isinstance(current_user, dict) else "anonymous", decision_ids=dec_ids
    )
    try:
        for vid in clean_ids:
            await append_event(source_id=vid, operation="metadata_read", phase="attempted", method="duration_probe", outcome_code="started")
        resolved = await asyncio.to_thread(get_durations, clean_ids)
        for vid in clean_ids:
            d = resolved.get(vid)
            await append_event(source_id=vid, operation="metadata_read", phase="succeeded" if d is not None else "failed", method="duration_probe", outcome_code="success" if d is not None else "not_found")
    finally:
        reset_observation_context(acq_token)

    known = {vid: d for vid, d in resolved.items() if d is not None}
    unresolved = [vid for vid, d in resolved.items() if d is None]

    if len(known) != len(clean_ids):
        raise HTTPException(422, detail={
            "code": "SOURCE_DURATION_UNAVAILABLE",
            "error_code": "SOURCE_DURATION_UNAVAILABLE",
            "message": "Source duration could not be verified for all selected videos.",
            "requested_duration_minutes": request.target_duration_minutes,
            "unresolved_video_ids": unresolved,
        })

    combined = float(sum(known.values()))
    # Strict rule: requested_duration_seconds < total_source_seconds
    if request.target_duration_minutes * 60 >= combined:
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

    canonical_video_ids = [extract_video_id(v) for v in request.video_ids]
    source_durations_map = {extract_video_id(vid): round(float(d), 1) for vid, d in known.items()}

    intent = _resolve_intent_contract(request, source_count=len(canonical_video_ids))

    # Create job
    job = MergeJob(
        job_id=job_id,
        user_id=current_user["sub"],
        video_ids=canonical_video_ids,
        requested_video_ids=canonical_video_ids,
        used_video_ids=canonical_video_ids,
        target_duration_minutes=request.target_duration_minutes,
        duration_style=get_duration_style(request.target_duration_minutes),
        generate_audio=request.generate_audio,
        generate_video=request.generate_video,
        highlight_duration_seconds=reel_seconds,
        style=request.style,
        summary_scope=intent["summary_scope"],
        source_scope=intent["source_scope"],
        discovery_query=intent["discovery_query"],
        summary_query=intent["summary_query"],
        query=getattr(request, "query", None),
        selected_keywords=intent["selected_keywords"],
        source_durations=source_durations_map,
        allow_partial_sources=getattr(request, "allow_partial_sources", False),
        video_component=OutputComponentState(
            status=(ComponentStatus.QUEUED if request.generate_video else ComponentStatus.NOT_REQUESTED)
        ),
        text_component=OutputComponentState(status=ComponentStatus.QUEUED),
    )

    # Store in memory and database
    _active_jobs[job.job_id] = job

    jobs_collection = await get_jobs_collection()
    await jobs_collection.insert_one(job.model_dump())

    # Start background processing: Dispatch to Redis worker queue if available, with safe fallback
    enqueued = False
    if settings.REDIS_QUEUE_ENABLED:
        try:
            from ..core.redis_queue import enqueue_merge_job
            enqueued = await enqueue_merge_job(job.job_id)
            if enqueued:
                logger.info("Job %s successfully dispatched to Redis worker queue", job.job_id)
                _active_jobs.pop(job.job_id, None)
        except Exception as exc:
            logger.warning("Redis enqueue failed for job %s: %s; falling back to in-memory processing", job.job_id, exc)

    if not enqueued:
        background_tasks.add_task(process_merge_job, job.job_id)

    # Estimate time (rough: 30s per video + 60s for fusion)
    estimated_seconds = len(request.video_ids) * 30 + 60

    output_state = _output_state_payload(job)
    return MergeJobResponse(
        job_id=job.job_id,
        status=job.status,
        progress_percent=job.progress_percent,
        stage_message=job.stage_message,
        estimated_seconds=estimated_seconds,
        summary_scope=job.summary_scope,
        source_scope=job.source_scope,
        discovery_query=job.discovery_query,
        summary_query=job.summary_query,
        query=job.query,
        selected_keywords=job.selected_keywords,
        stage_timings_seconds=job.stage_timings_seconds,
        active_source=job.active_source,
        elapsed_seconds=job.elapsed_seconds,
        transcript_preflight=job.transcript_preflight,
        **output_state,
    )


class PreflightRequest(BaseModel):
    video_ids: List[str]
    per_source_timeout: float = 20.0


@router.post("/preflight")
async def preflight_merge_sources_post(
    request: PreflightRequest,
    current_user: dict = Depends(get_current_user_optional),
):
    """
    Transcript-availability preflight check before merge creation.
    Identifies fast-ready vs slow-recovery vs unavailable sources.
    """
    from ..services.transcript_service import get_transcript_service
    service = await get_transcript_service()
    results = await service.preflight_sources(request.video_ids, per_source_timeout=request.per_source_timeout)
    ready_ids = [vid for vid, r in results.items() if r.get("ready")]
    unavailable_ids = [vid for vid, r in results.items() if not r.get("ready")]
    unsupported_ids = [vid for vid, r in results.items() if r.get("error_code") in ("UNSUPPORTED_TRANSCRIPT_LANGUAGE", "AUDIO_TRANSCRIPTION_EXCEEDED")]
    translation_required_ids = [vid for vid, r in results.items() if r.get("status") == "translation_required"]
    return {
        "can_merge": len(unavailable_ids) == 0,
        "requested_video_ids": request.video_ids,
        "ready_video_ids": ready_ids,
        "unavailable_video_ids": unavailable_ids,
        "unsupported_video_ids": unsupported_ids,
        "translation_required_video_ids": translation_required_ids,
        "sources": results,
        "ready_count": len(ready_ids),
        "total_count": len(request.video_ids),
    }


@router.get("/preflight")
async def preflight_merge_sources_get(
    video_ids: List[str] = Query(..., description="List of YouTube video IDs or URLs"),
    per_source_timeout: float = Query(20.0, description="Per-source preflight timeout in seconds"),
    current_user: dict = Depends(get_current_user_optional),
):
    """GET version of preflight for easy querying."""
    from ..services.transcript_service import get_transcript_service
    service = await get_transcript_service()
    results = await service.preflight_sources(video_ids, per_source_timeout=per_source_timeout)
    ready_ids = [vid for vid, r in results.items() if r.get("ready")]
    unavailable_ids = [vid for vid, r in results.items() if not r.get("ready")]
    unsupported_ids = [vid for vid, r in results.items() if r.get("error_code") in ("UNSUPPORTED_TRANSCRIPT_LANGUAGE", "AUDIO_TRANSCRIPTION_EXCEEDED")]
    translation_required_ids = [vid for vid, r in results.items() if r.get("status") == "translation_required"]
    return {
        "can_merge": len(unavailable_ids) == 0,
        "requested_video_ids": video_ids,
        "ready_video_ids": ready_ids,
        "unavailable_video_ids": unavailable_ids,
        "unsupported_video_ids": unsupported_ids,
        "translation_required_video_ids": translation_required_ids,
        "sources": results,
        "ready_count": len(ready_ids),
        "total_count": len(video_ids),
    }


@router.get("/{job_id}", response_model=MergeJobResponse)
async def get_job_status(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Get current status of a merge job.

    Poll this endpoint to track progress.
    """
    job_data = await _get_owned_job(job_id, current_user)

    # Check memory first only if Redis queue is disabled and job is actively tracked locally
    if not settings.REDIS_QUEUE_ENABLED and job_id in _active_jobs:
        job = _active_jobs[job_id]
        output_state = _output_state_payload(job)
        return MergeJobResponse(
            job_id=job.job_id,
            status=job.status,
            progress_percent=job.progress_percent,
            stage_message=job.stage_message,
            error=job.error,
            warning=job.warning,
            summary_scope=job.summary_scope,
            source_scope=job.source_scope,
            discovery_query=job.discovery_query,
            summary_query=job.summary_query,
            query=job.query,
            selected_keywords=job.selected_keywords,
            stage_timings_seconds=job.stage_timings_seconds,
            active_source=job.active_source,
            elapsed_seconds=job.elapsed_seconds,
            transcript_preflight=job.transcript_preflight,
            has_video_ready=bool(getattr(job, "video_path", None)),
            manifest_version=(job.evidence_manifest or {}).get("manifest_version"),
            **output_state,
        )

    output_state = _output_state_payload(job_data)
    return MergeJobResponse(
        job_id=job_data["job_id"],
        status=job_data["status"],
        progress_percent=job_data["progress_percent"],
        stage_message=job_data["stage_message"],
        error=_job_error(job_data),
        warning=job_data.get("warning"),
        summary_scope=job_data.get("summary_scope"),
        source_scope=job_data.get("source_scope"),
        discovery_query=job_data.get("discovery_query"),
        summary_query=job_data.get("summary_query"),
        query=job_data.get("query"),
        selected_keywords=job_data.get("selected_keywords", []),
        stage_timings_seconds=job_data.get("stage_timings_seconds", {}),
        active_source=job_data.get("active_source"),
        elapsed_seconds=job_data.get("elapsed_seconds"),
        transcript_preflight=job_data.get("transcript_preflight"),
        has_video_ready=bool(job_data.get("video_path")),
        manifest_version=(job_data.get("evidence_manifest") or {}).get("manifest_version"),
        **output_state,
    )


@router.post("/{job_id}/retry-{output_type}")
async def retry_output_component(
    job_id: str,
    output_type: Literal["video", "text"],
    current_user: dict = Depends(get_current_user),
):
    """Requeue one failed output without repeating acquisition or selection."""
    job_data = await _get_owned_job(job_id, current_user)
    manifest = job_data.get("evidence_manifest") or {}
    manifest_version = manifest.get("manifest_version")
    if not manifest_version:
        raise HTTPException(409, "This job has no reusable evidence manifest.")
    if output_type == "video" and not job_data.get("generate_video"):
        raise HTTPException(409, "Video output was not requested for this job.")
    if output_type == "text" and job_data.get("summary_unavailable_reason") in {
        "UNSUPPORTED_LANGUAGE", "UNSUPPORTED_TRANSCRIPT_LANGUAGE",
    }:
        raise HTTPException(409, "Written output is unavailable for this transcript language.")

    component = _component_state(job_data.get(f"{output_type}_component"))
    if component.status in {ComponentStatus.QUEUED, ComponentStatus.RUNNING}:
        raise HTTPException(409, f"{output_type.title()} output is already in progress.")

    from ..services.output_task_queue import requeue_output_task
    database = await get_database()
    task = await requeue_output_task(
        database,
        job_id=job_id,
        manifest_version=int(manifest_version),
        output_type=output_type,
    )
    if task is None:
        raise HTTPException(409, f"{output_type.title()} output could not be requeued.")

    state = OutputComponentState(
        status=ComponentStatus.QUEUED,
        stage="queued",
        progress_percent=0,
        attempts=0,
    )
    jobs_collection = await get_jobs_collection()
    await jobs_collection.update_one(
        {"job_id": job_id},
        {"$set": {f"{output_type}_component": state.model_dump()}},
    )
    if job_id in _active_jobs:
        setattr(_active_jobs[job_id], f"{output_type}_component", state)
    return {
        "job_id": job_id,
        "output_type": output_type,
        "task_id": task["task_id"],
        "component": state.model_dump(),
    }


@router.get("/{job_id}/result")
async def get_job_result(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Get the result of a merge job.

    Available once status is 'completed', 'partial_success', or
    'video_ready'. In the 'video_ready' case the highlight video is done but
    the text summary is still being generated in the background —
    `summary_pending` is True and `summary_text`/`rich_output`/`metadata`
    are withheld (returned as None/empty) rather than exposed as an empty
    finished summary.
    """
    job_data = await _get_owned_job(job_id, current_user)

    video_ready_statuses = {
        JobStatus.VIDEO_READY.value,
        JobStatus.GENERATING_VIDEO.value,
        JobStatus.FUSING.value,
        JobStatus.SUMMARIZING.value,
        JobStatus.ENRICHING.value,
        JobStatus.GENERATING_VOICE.value,
    }
    
    allowed_statuses = {
        JobStatus.COMPLETED.value,
        JobStatus.PARTIAL_SUCCESS.value,
    } | video_ready_statuses
    
    has_video = bool(job_data.get("video_path"))
    if job_data["status"] in {JobStatus.ERROR.value, JobStatus.CANCELLED.value}:
        raise HTTPException(
            400,
            f"Job {job_data['status']}: {_job_error(job_data) or 'Job was not completed successfully'}"
        )

    if job_data["status"] not in allowed_statuses and not has_video:
        raise HTTPException(
            400,
            f"Job not completed. Current status: {job_data['status']}"
        )

    text_component_status = (job_data.get("text_component") or {}).get("status")
    if job_data["status"] in {JobStatus.COMPLETED.value, JobStatus.PARTIAL_SUCCESS.value} and job_data.get("summary_text"):
        summary_pending = False
    elif text_component_status:
        summary_pending = text_component_status in {
            ComponentStatus.QUEUED.value,
            ComponentStatus.RUNNING.value,
        }
    else:
        summary_pending = (
            job_data["status"] in video_ready_statuses
            or job_data["status"] not in {
                JobStatus.COMPLETED.value, JobStatus.PARTIAL_SUCCESS.value
            }
        )

    highlight_segments = job_data.get("highlight_segments", [])
    video_duration_seconds = sum(
        (seg.get("end_time", 0) - seg.get("start_time", 0)) for seg in highlight_segments
    )

    media_subject = current_user["sub"]
    capabilities = _media_capabilities(job_data)
    preview_allowed = capabilities["preview_allowed"]
    download_allowed = capabilities["download_allowed"]
    audio_preview_token = create_media_token(job_id, "audio_preview", media_subject) if preview_allowed else None
    video_preview_token = create_media_token(job_id, "video_preview", media_subject) if preview_allowed else None
    audio_download_token = create_media_token(job_id, "audio_download", media_subject) if download_allowed else None
    video_download_token = create_media_token(job_id, "video_download", media_subject) if download_allowed else None
    subtitle_token = create_media_token(job_id, "subtitles_download", media_subject) if download_allowed else None

    raw_meta = {} if summary_pending else (job_data.get("fusion_metadata") or {})
    cleaned_metadata = dict(raw_meta) if isinstance(raw_meta, dict) else {}
    if cleaned_metadata:
        if not cleaned_metadata.get("topics_found") and job_data.get("concepts"):
            concepts_topics = [
                c["name"].strip() if isinstance(c, dict) and c.get("name") else (str(c).strip() if isinstance(c, str) else "")
                for c in job_data.get("concepts", [])
            ]
            cleaned_metadata["topics_found"] = list(dict.fromkeys(t for t in concepts_topics if t))[:10]
        if cleaned_metadata.get("compression_ratio") is not None:
            raw_ratio = float(cleaned_metadata.get("compression_ratio", 0.0))
            if raw_ratio > 1.0:
                tot = cleaned_metadata.get("total_source_words", 0)
                out = cleaned_metadata.get("output_words", 0)
                if tot > 0 and out > 0:
                    cleaned_metadata["compression_ratio"] = round(min(max(out / tot, 0.0), 1.0), 4)
                else:
                    cleaned_metadata["compression_ratio"] = min(max(raw_ratio, 0.0), 1.0)
            else:
                cleaned_metadata["compression_ratio"] = min(max(raw_ratio, 0.0), 1.0)

    detected_language = job_data.get("detected_language")
    unavailable_reason = job_data.get("summary_unavailable_reason")
    summary_unavailable = bool(
        job_data.get("summary_unavailable")
        or unavailable_reason in {"UNSUPPORTED_LANGUAGE", "UNSUPPORTED_TRANSCRIPT_LANGUAGE"}
        or (detected_language and detected_language != "en" and not (job_data.get("summary_text") or "").strip())
    )
    if summary_unavailable:
        cleaned_metadata = {
            **cleaned_metadata,
            "topics_found": [],
            "compression_ratio": None,
            "output_words": None,
        }

    return {
        "job_id": job_data["job_id"],
        "status": job_data["status"],
        **_output_state_payload(job_data),
        "manifest_version": (job_data.get("evidence_manifest") or {}).get("manifest_version"),
        # True only while video_ready — the AI summary (text/TL;DR/
        # takeaways/chapters) has not finished yet.
        "summary_pending": summary_pending,
        # None (not "") means "not ready yet" — same convention already
        # used for the language-unavailable case — so a pending summary is
        # never mistaken for a finished, empty one.
        "summary_text": None if summary_pending else job_data.get("summary_text", ""),
        "rich_output": None if summary_pending else job_data.get("rich_output"),
        "structured_text_output": (
            None if summary_pending else job_data.get("structured_text_output")
        ),
        "generated_summary_visible": capabilities["generated_summary_visible"],
        "copy_summary_allowed": capabilities["copy_summary_allowed"],
        "txt_export_allowed": capabilities["txt_export_allowed"],
        "pdf_export_allowed": capabilities["pdf_export_allowed"],
        "preview_allowed": preview_allowed,
        "download_allowed": download_allowed,
        "public_export_allowed": capabilities["public_export_allowed"],
        "media_delivery_allowed": download_allowed,
        "audio_url": f"/api/v1/merge/{job_id}/audio?access=preview&token={audio_preview_token}" if preview_allowed and job_data.get("audio_path") else None,
        "video_url": f"/api/v1/merge/{job_id}/video?access=preview&token={video_preview_token}" if preview_allowed and job_data.get("video_path") else None,
        "audio_download_url": f"/api/v1/merge/{job_id}/audio?access=download&token={audio_download_token}" if download_allowed and job_data.get("audio_path") else None,
        "video_download_url": f"/api/v1/merge/{job_id}/video?access=download&token={video_download_token}" if download_allowed and job_data.get("video_path") else None,
        "subtitle_url": f"/api/v1/merge/{job_id}/subtitles?access=download&token={subtitle_token}" if download_allowed and job_data.get("subtitle_path") else None,
        "video_ids": job_data.get("used_video_ids") or job_data.get("video_ids", []),
        "requested_video_ids": job_data.get("requested_video_ids") or job_data.get("video_ids", []),
        "used_video_ids": job_data.get("used_video_ids") or job_data.get("video_ids", []),
        # Echoed back so a follow-up job (e.g. the highlight re-compile on the
        # player page) can reuse this job's settings instead of hardcoding them.
        "target_duration_minutes": job_data.get("target_duration_minutes"),
        "summary_scope": job_data.get("summary_scope"),
        "source_scope": job_data.get("source_scope"),
        "content_type": job_data.get("content_type", "explanatory"),
        "content_type_confidence": job_data.get("content_type_confidence", 0.0),
        "discovery_query": job_data.get("discovery_query"),
        "summary_query": job_data.get("summary_query"),
        "query": job_data.get("query"),
        "selected_keywords": job_data.get("selected_keywords", []),
        # Actual selected/rendered reel length — available as soon as the
        # video is, independent of the target duration requested.
        "video_duration_seconds": round(video_duration_seconds, 1),
        "highlight_segments": highlight_segments,
        "keyframes_extracted": job_data.get("keyframes_extracted", {}),
        # Semantic pipeline output. Absent on jobs produced before this
        # pipeline existed, so the frontend must treat all of it as optional.
        "concepts": job_data.get("concepts", []),
        "selection_metrics": job_data.get("selection_metrics"),
        "selection_trace": job_data.get("selection_trace", []),
        "summarization_decision": job_data.get("summarization_decision"),
        "selection_mode": job_data.get("selection_mode", "legacy"),
        "warning": job_data.get("warning"),
        "error": _job_error(job_data),
        "metadata": cleaned_metadata,
        # Language-abort fields — present on language-abort jobs so the frontend
        # can skip QualityPanel and show the correct unavailable-summary state
        # without hitting /evaluate (which would previously 500).
        "summary_unavailable": summary_unavailable,
        "summary_unavailable_reason": (
            "UNSUPPORTED_TRANSCRIPT_LANGUAGE" if summary_unavailable else unavailable_reason
        ),
        "detected_language": detected_language,
        "supported_languages": job_data.get("supported_languages") or ["en"],
        "preflight_failure": job_data.get("preflight_failure"),
        # Rights & Publication Guidance (private study export remains unrestricted)
        "publication_gate_status": job_data.get("publication_gate_status") or "manual_review_required",
        "gate_warnings": (job_data.get("rights_summary") or {}).get("warnings", []),
        "rights_manifest_url": f"/api/v1/rights/job/{job_id}/manifest",
        "source_durations": job_data.get("source_durations", {}),
        "stage_timings_seconds": job_data.get("stage_timings_seconds", {}),
        "elapsed_seconds": job_data.get("elapsed_seconds"),
        "transcript_preflight": job_data.get("transcript_preflight"),
        "created_at": job_data["created_at"],
        "completed_at": job_data.get("completed_at"),
    }


@router.get("/{job_id}/evaluate")
async def evaluate_job_quality(
    job_id: str,
    llm: bool = False,
    current_user: dict = Depends(get_current_user),
):
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
    job_data = await _get_owned_job(job_id, current_user)

    if job_data["status"] not in {JobStatus.COMPLETED.value, JobStatus.PARTIAL_SUCCESS.value}:
        raise HTTPException(400, f"Job not completed. Current status: {job_data['status']}")

    # Language-abort jobs have no summary — quality evaluation is impossible.
    # Return a controlled response instead of propagating to _build_quality_report
    # which would crash on None summary_text.
    if job_data.get("summary_unavailable"):
        return {
            "unavailable": True,
            "reason": job_data.get("warning") or "No written summary was generated for this job (unsupported language).",
            "summary_score": None,
            "video_score": None,
            "check_a": {},
            "check_b": {},
        }

    cache_field = _QUALITY_CACHE_FIELD_LLM if llm else _QUALITY_CACHE_FIELD
    cached = job_data.get(cache_field)
    if cached:
        return cached

    # If already running asynchronously in background, return non-blocking running status
    if not llm and job_data.get("evaluation_state") == "running":
        return {
            "job_id": job_id,
            "evaluation_state": "running",
            "unavailable": False,
            "summary_score": None,
            "video_score": None,
            "check_a": {},
            "check_b": {},
            "message": "Quality scorecard is currently computing in the background...",
        }

    now = datetime.utcnow()
    await jobs_collection.update_one({"job_id": job_id}, {"$set": {
        "evaluation_state": "running",
        "evaluation_error": None,
        "evaluation_updated_at": now,
    }})
    timeout_seconds = 240.0 if llm else 120.0
    try:
        report = await asyncio.wait_for(
            _build_quality_report(job_data, use_llm=bool(llm)),
            timeout=timeout_seconds,
        )
        report["evaluation_state"] = "completed"
        await jobs_collection.update_one({"job_id": job_id}, {"$set": {
            cache_field: report,
            "evaluation_state": "completed",
            "evaluation_error": None,
            "evaluation_updated_at": datetime.utcnow(),
        }})
        return report
    except asyncio.TimeoutError:
        reason = f"Quality evaluation exceeded the {int(timeout_seconds)} second limit."
        report = {"unavailable": True, "reason": reason,
                  "summary_score": None, "video_score": None,
                  "check_a": {}, "check_b": {}, "evaluation_state": "unavailable"}
        await jobs_collection.update_one({"job_id": job_id}, {"$set": {
            cache_field: report, "evaluation_state": "unavailable",
            "evaluation_error": reason, "evaluation_updated_at": datetime.utcnow(),
        }})
        return report
    except Exception as exc:
        reason = f"Quality evaluation failed: {type(exc).__name__}"
        report = {"unavailable": True, "reason": reason,
                  "summary_score": None, "video_score": None,
                  "check_a": {}, "check_b": {}, "evaluation_state": "failed"}
        await jobs_collection.update_one({"job_id": job_id}, {"$set": {
            cache_field: report, "evaluation_state": "failed",
            "evaluation_error": str(exc), "evaluation_updated_at": datetime.utcnow(),
        }})
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
    # Defend against None (language-abort jobs) and empty string.
    summary_text = job_data.get("summary_text") or ""
    if not summary_text.strip():
        # Return a safe, structured response instead of crashing with
        # AttributeError or a raw HTTP 400 that surfaces as a red error in the UI.
        return {
            "unavailable": True,
            "reason": "No written summary was generated for this job.",
            "summary_score": None,
            "video_score": None,
            "check_a": {},
            "check_b": {},
        }

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


async def precompute_job_quality_scorecard(job_id: str, jobs_collection) -> None:
    """Precompute the llm=false quality scorecard in the background upon job completion."""
    try:
        job_data = await jobs_collection.find_one({"job_id": job_id})
        if not job_data:
            return
        if job_data.get(_QUALITY_CACHE_FIELD):
            return
        if job_data.get("summary_unavailable") or not (job_data.get("summary_text") or "").strip():
            return

        now = datetime.utcnow()
        await jobs_collection.update_one({"job_id": job_id}, {"$set": {
            "evaluation_state": "running",
            "evaluation_updated_at": now,
        }})
        report = await _build_quality_report(job_data, use_llm=False)
        report["evaluation_state"] = "completed"
        await jobs_collection.update_one({"job_id": job_id}, {"$set": {
            _QUALITY_CACHE_FIELD: report,
            "evaluation_state": "completed",
            "evaluation_error": None,
            "evaluation_updated_at": datetime.utcnow(),
        }})
        print(f"[Quality] Scorecard precomputed and cached for job {job_id}")
    except Exception as exc:
        print(f"[Quality] Background scorecard precomputation failed for job {job_id}: {exc}")



@router.get("/{job_id}/audio")
async def get_job_audio(
    job_id: str,
    token: Optional[str] = Query(None),
    current_user: Optional[dict] = Depends(get_current_user_optional),
    access: str = Query("preview", pattern="^(preview|download)$"),
):
    """
    Preview or download generated audio according to the frozen rights policy.
    """
    job_data = await _get_media_job(job_id, f"audio_{access}", token, current_user)
    _assert_media_capability(job_data, "preview_allowed" if access == "preview" else "download_allowed")

    audio_path = job_data.get("audio_path")
    if not audio_path or not os.path.exists(audio_path):
        raise HTTPException(404, "Audio not available")

    decision_ids = await load_job_decision_ids(job_id)
    acq_token = set_observation_context(
        job_id=job_id,
        user_id=job_data.get("user_id") or "anonymous",
        decision_ids=decision_ids
    )
    try:
        for vid in (job_data.get("used_video_ids") or job_data.get("video_ids") or []):
            await append_event(
                source_id=vid,
                operation="derived_media_deliver",
                phase="succeeded",
                method="http_download",
                outcome_code="success",
            )
    finally:
        reset_observation_context(acq_token)

    return FileResponse(
        audio_path,
        media_type="audio/mpeg",
        filename=f"summary_{job_id}.mp3" if access == "download" else None,
        content_disposition_type="attachment" if access == "download" else "inline",
    )


@router.get("/{job_id}/video")
async def get_job_video(
    job_id: str,
    token: Optional[str] = Query(None),
    access: str = Query("preview", pattern="^(preview|download)$"),
    current_user: Optional[dict] = Depends(get_current_user_optional),
):
    """
    Preview or download the reel according to the frozen rights policy.
    """
    job_data = await _get_media_job(job_id, f"video_{access}", token, current_user)
    _assert_media_capability(job_data, "preview_allowed" if access == "preview" else "download_allowed")

    video_path = job_data.get("video_path")
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(404, "Video highlight reel not available")

    decision_ids = await load_job_decision_ids(job_id)
    acq_token = set_observation_context(
        job_id=job_id,
        user_id=job_data.get("user_id") or "anonymous",
        decision_ids=decision_ids
    )
    try:
        for vid in (job_data.get("used_video_ids") or job_data.get("video_ids") or []):
            await append_event(
                source_id=vid,
                operation="derived_media_deliver",
                phase="succeeded",
                method="http_download",
                outcome_code="success",
            )
    finally:
        reset_observation_context(acq_token)

    return FileResponse(
        video_path,
        media_type="video/mp4",
        filename=f"highlights_{job_id}.mp4" if access == "download" else None,
        content_disposition_type="attachment" if access == "download" else "inline",
    )


@router.get("/{job_id}/subtitles")
async def get_job_subtitles(
    job_id: str,
    access: str = Query("download", pattern="^download$"),
    token: Optional[str] = Query(None),
    current_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Download SRT subtitle file for a completed job."""
    job_data = await _get_media_job(job_id, "subtitles_download", token, current_user)
    _assert_media_capability(job_data, "download_allowed")

    subtitle_path = job_data.get("subtitle_path")
    if not subtitle_path or not os.path.exists(subtitle_path):
        raise HTTPException(404, "Subtitles not available")

    return FileResponse(
        subtitle_path,
        media_type="application/x-subrip",
        filename=f"summary_{job_id}.srt"
    )


@router.get("/{job_id}/export")
async def export_job(
    job_id: str,
    format: str = "text",
    current_user: dict = Depends(get_current_user),
):
    """
    Export summary as text or PDF.

    Query params:
        format: "text" or "pdf"
    """
    job_data = await _get_owned_job(job_id, current_user)
    note_capability = "pdf_export_allowed" if format == "pdf" else "txt_export_allowed"
    if not _media_capabilities(job_data).get(note_capability, False):
        raise HTTPException(403, "Generated-note export is blocked by policy.")

    if job_data["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(400, "Job not completed")

    summary_text = job_data.get("summary_text", "")
    rich_output = job_data.get("rich_output")

    from ..services.export_service import format_as_text, generate_pdf

    if format == "pdf":
        pdf_bytes = bytes(generate_pdf(summary_text, rich_output, job_data.get("content_type", "explanatory")))
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=summary_{job_id}.pdf"}
        )
    else:
        text = format_as_text(summary_text, rich_output, job_data.get("content_type", "explanatory"))
        return StreamingResponse(
            iter([text.encode("utf-8")]),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=summary_{job_id}.txt"}
        )


@router.get("/{job_id}/stream")
async def stream_job_progress(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    SSE endpoint for real-time job progress.
    The browser connects once and receives updates every ~1 second.
    Closes automatically when the job completes or errors.
    """
    await _get_owned_job(job_id, current_user)

    async def event_generator():
        while True:
            job = None if settings.REDIS_QUEUE_ENABLED else _active_jobs.get(job_id)

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


def _merge_overlapping_clips(clips: list) -> list:
    """
    Merge overlapping or adjacent clips from the same video.
    Prevents repeated speech at the boundary of adjacent semantic segments.
    """
    merged_clips = []
    for h in clips:
        if merged_clips and merged_clips[-1].get("video_id") == h.get("video_id"):
            # if overlap or touch (e.g. within 0.1s)
            if float(h["start_time"]) <= float(merged_clips[-1]["end_time"]) + 0.1:
                merged_clips[-1]["end_time"] = max(float(merged_clips[-1]["end_time"]), float(h["end_time"]))
                merged_clips[-1]["text"] = merged_clips[-1].get("text", "") + " " + h.get("text", "")
                continue
        merged_clips.append(dict(h))
    return merged_clips


async def _legacy_select_highlights(
    job,
    video_paths: Dict[str, str],
    raw_segments: Dict[str, list],
    semantic_bias_text: str,
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
                await append_event(
                    source_id=vid,
                    operation="keyframe_generate",
                    phase="attempted",
                    method="opencv_extraction",
                    outcome_code="started",
                )
                visual_keyframes = await asyncio.wait_for(
                    asyncio.to_thread(
                        extract_keyframes_for_segments, vid, vid_path, transcript_groups
                    ),
                    timeout=90.0,
                )
                await append_event(
                    source_id=vid,
                    operation="keyframe_generate",
                    phase="succeeded",
                    method="opencv_extraction",
                    outcome_code="success",
                )
            except asyncio.TimeoutError:
                await append_event(
                    source_id=vid,
                    operation="keyframe_generate",
                    phase="failed",
                    method="opencv_extraction",
                    outcome_code="timeout",
                )
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
                summary_text=semantic_bias_text,
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


def _keyword_evidence_matches(keywords, scores, text, threshold=0.65):
    """Return only keywords with strong semantic or explicit lexical evidence."""
    folded_text = (text or "").casefold()
    return [keyword for keyword, score in zip(keywords, scores)
            if float(score) >= threshold or keyword.casefold() in folded_text]


async def run_semantic_selection(
    job,
    raw_segments: Dict[str, list],
    semantic_bias_text: str,
    progress=None,
) -> Optional[Dict]:
    """
    The coverage-aware selection pipeline.

        transcript -> sentences -> semantic segments   (semantic_segmenter)
                   -> concepts                          (concept_extractor)
                   -> budgeted submodular selection     (coverage_selector)
                   -> metrics                           (summary_metrics)

    Returns None when it cannot produce a usable selection, which tells the
    caller to run the legacy scorer instead. It never raises for operational
    failures, but WILL propagate programmer/integration errors (TypeError,
    AttributeError) so the call site can distinguish a bad call from a bad
    input.

    Args:
        job: the MergeJob being processed
        raw_segments: {video_id: [{text, start, duration}]}
        semantic_bias_text: the baseline fusion narrative, used as the
            relevance reference for semantic selection.  This is the
            FIRST-PASS fusion output (full transcript), NOT the final
            summary — passing the final summary would create a circular
            dependency (Select-First -> Summarize-Selected).
        progress: optional async callback(message) for status updates
    """
    from ..services.semantic_segmenter import build_semantic_segments
    from ..services.concept_extractor import extract_concepts
    from ..services.coverage_selector import (
        SelectionWeights,
        resolve_selection_policy,
        select_segments,
        DEFAULT_BINS,
    )
    from ..services.knowledge_plan import build_knowledge_plan
    from ..services.summary_metrics import compute_selection_metrics, format_metrics_report

    async def say(message: str):
        print(f"[Semantic] {message}")
        if progress:
            try:
                await progress(message)
            except Exception:
                pass

    budget = float(job.highlight_duration_seconds)
    timings = {name: 0.0 for name in ("segmentation", "concept_extraction", "embedding", "selection", "ordering")}
    base_weights = SelectionWeights.from_settings(settings)
    intent = _resolve_intent_contract(job, source_count=len(raw_segments))
    policy = resolve_selection_policy(
        intent["summary_scope"], intent["source_scope"], base_weights
    )
    weights = policy.weights

    durations = {vid: _source_duration(segs) for vid, segs in raw_segments.items() if segs}
    if not durations:
        return None

    # --- Reference vector for the relevance term ---
    # semantic_bias_text is the FIRST-PASS fusion output over the full
    # transcript — used only as a soft relevance reference so the optimizer
    # can distinguish "on-topic" segments from digressions.  It is NOT the
    # final summary (that would require a circular dependency).
    summary_embedding = None
    query_embedding = None
    embedder = None
    keywords = _semantic_intent_terms(job)
    embedding_started = perf_counter()
    try:
        from ..services.fusion_engine import get_sentence_transformer
        from ..services.cache_identity import MeasuredEmbedder
        embedder = MeasuredEmbedder(await asyncio.to_thread(get_sentence_transformer))
        if semantic_bias_text.strip():
            summary_embedding = (await asyncio.to_thread(
                embedder.encode,
                [semantic_bias_text[:4000]],
                show_progress_bar=False,
            ))[0]
        if keywords:
            query_embedding = await asyncio.to_thread(
                embedder.encode, keywords, show_progress_bar=False
            )
    except Exception as exc:
        print(f"[Semantic] Embedder unavailable ({exc}) — continuing without a relevance reference")
    timings["embedding"] += perf_counter() - embedding_started

    all_selected = []
    baselines = []
    all_concepts = []
    all_trace = []
    per_video = {}

    global_segments = []

    for vid, segs in raw_segments.items():
        if not segs:
            continue

        # --- 1. semantic segmentation ---
        await say(f"Building semantic segments for {vid}...")
        stage_started = perf_counter()
        embed_before = embedder.elapsed if embedder is not None else 0.0
        segments = await asyncio.to_thread(
            build_semantic_segments,
            segs,
            vid,
            settings.SEGMENT_MIN_SECONDS,
            settings.SEGMENT_MAX_SECONDS,
            embedder,
        )
        embedded = (embedder.elapsed - embed_before) if embedder is not None else 0.0
        timings["segmentation"] += max(0.0, perf_counter() - stage_started - embedded)
        timings["embedding"] += embedded
        if not segments:
            print(f"[Semantic] {vid}: no semantic segments (unusable timestamps) — skipping")
            continue
        print(f"[Semantic] {vid}: {len(segs)} caption entries -> {len(segments)} complete thoughts "
              f"(avg {sum(s.duration for s in segments) / len(segments):.0f}s)")
        global_segments.extend(segments)

    from ..services.content_intelligence import detect_content_type
    content_type_started = perf_counter()
    structural_segments = []
    for video_id, caption_segments in raw_segments.items():
        for caption in caption_segments:
            if isinstance(caption, dict):
                start = caption.get("start_time", caption.get("start", 0.0)) or 0.0
                end = caption.get("end_time", start + (caption.get("duration", 0.0) or 0.0)) or start
                text = caption.get("text", "")
            else:
                start = getattr(caption, "start_time", getattr(caption, "start", 0.0)) or 0.0
                end = getattr(caption, "end_time", start + (getattr(caption, "duration", 0.0) or 0.0)) or start
                text = getattr(caption, "text", "")
            structural_segments.append({
                "video_id": video_id,
                "start_time": start,
                "end_time": end,
                "text": text,
            })
    content_type_result = await asyncio.to_thread(
        detect_content_type,
        global_segments,
        structural_segments=structural_segments,
    )
    timings["content_type_detection"] = perf_counter() - content_type_started
    print(
        f"[ContentType] {content_type_result.content_type} "
        f"(confidence={content_type_result.confidence:.2f})"
    )

    # --- 2. concept extraction (Global) ---
    await say(f"Extracting key concepts globally across {len(raw_segments)} videos...")
    total_len = sum(durations.values())
    stage_started = perf_counter()
    embed_before = embedder.elapsed if embedder is not None else 0.0
    try:
        concepts = await extract_concepts(
            global_segments,
            total_duration=total_len,
            top_k=settings.CONCEPT_TOP_K,
            use_llm=False,
            per_chunk_timeout=settings.CONCEPT_CHUNK_TIMEOUT_SECONDS,
            total_timeout=settings.CONCEPT_TOTAL_TIMEOUT_SECONDS,
            embedder=embedder,
        )
    except Exception as exc:
        print(f"[Semantic] Concept extraction failed globally: {exc}")
        concepts = []
    embedded = (embedder.elapsed - embed_before) if embedder is not None else 0.0
    timings["concept_extraction"] = max(0.0, perf_counter() - stage_started - embedded)
    timings["embedding"] += embedded

    if not concepts:
        print(f"[Semantic] WARNING: 0 concepts extracted globally — "
              f"concept-driven selection is DISABLED; falling back to relevance + temporal coverage only")

    # One shared intent/knowledge-plan layer serves both normal Search (`query`)
    # and Deep Search (`query` + `selected_keywords`). TF-IDF remains the
    # candidate generator; this stage filters/canonicalises and adds unit labels.
    intent_text = " ".join(keywords).strip()
    knowledge_plan = await asyncio.to_thread(
        build_knowledge_plan,
        global_segments,
        concepts,
        query=intent_text,
        query_embedding=(
            query_embedding.mean(axis=0) if query_embedding is not None else None
        ),
        budget_seconds=budget,
        content_type=content_type_result.content_type,
    )
    concepts = knowledge_plan.concepts
    print(
        f"[KnowledgePlan] {len(concepts)} canonical concepts, "
        f"{len(knowledge_plan.units)} observed knowledge units"
    )

    # --- 3. budgeted selection (Global) ---
    await say(f"Selecting the best {budget:.0f}s from the global candidate pool...")
    result = await asyncio.to_thread(
        select_segments,
        global_segments,
        budget,
        concepts,
        weights,
        summary_embedding,
        embedder,
        durations,  # Dict of video durations
        DEFAULT_BINS,
        query_embedding,
        timings,
        knowledge_plan.units,
        policy,
    )
    if query_embedding is not None:
        import numpy as np
        q = np.atleast_2d(query_embedding)
        q = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-9)
        for seg in result.segments:
            vec = getattr(seg, "embedding", None)
            scores = q @ (vec / max(np.linalg.norm(vec), 1e-9)) if vec is not None else np.zeros(len(keywords))
            seg.keyword_scores = {
                keyword: float(score) for keyword, score in zip(keywords, scores)
            }
            # BGE cosine values are not calibrated probabilities.  A 0.50
            # cutoff falsely labelled unrelated clips as evidence in the real
            # no-evidence E2E flow (for example, ML clips "covered" quantum
            # chromodynamics).  Keep query relevance for ranking unchanged,
            # but make the user-facing coverage claim fail closed.
            seg.keyword_matches = _keyword_evidence_matches(keywords, scores, seg.text)

    if result.segments:
        baselines.append(result.baseline_similarity)
        all_selected.extend(result.segments)
        all_concepts.extend(concepts)
        all_trace.extend(result.trace)

        # Approximate per-video stats
        for vid in raw_segments:
            vid_selected = [s for s in result.segments if getattr(s, "video_id", "") == vid]
            vid_cands = [s for s in global_segments if getattr(s, "video_id", "") == vid]
            if not vid_cands:
                continue
            per_video[vid] = {
                "candidates": len(vid_cands),
                "selected": len(vid_selected),
                "seconds": round(sum(s.duration for s in vid_selected), 1),
                "budget": 0.0,
                "concepts_found": len(concepts),
                "concepts_covered": list(dict.fromkeys(c for s in vid_selected for c in s.concept_scores)),
                "concept_signal": result.concept_signal,
                "concepts_omitted_for_budget": result.concepts_omitted_for_budget,
            }

    selector_per_video = {}
    for vid in raw_segments:
        selected_now = [
            segment for segment in result.segments
            if getattr(segment, "video_id", "") == vid
        ]
        selector_per_video[vid] = {
            "candidates": sum(
                getattr(segment, "video_id", "") == vid
                for segment in global_segments
            ),
            "selected": len(selected_now),
            "seconds": round(sum(segment.duration for segment in selected_now), 1),
            "source_diversity_bonus": round(sum(
                float(item.get("source_diversity_bonus", 0.0))
                for item in result.trace
                if item.get("video_id") == vid
            ), 4),
        }

    if not all_selected:
        return None

    from ..services.concept_block_organizer import organize_concept_blocks
    all_selected, concept_block_stats = organize_concept_blocks(
        all_selected, global_segments, all_concepts
    )

    # The semantic segmenter consumes overlapping display-caption timestamps.
    # Selection remains unchanged; this final physical pass prevents those
    # source intervals from being rendered twice.
    from ..services.manifest_boundary_repair import (
        aggregate_normalization_metrics,
        rebuild_final_texts,
        reconcile_physical_duration,
        repair_explanation_boundaries,
        repair_physical_boundaries,
    )
    selector_duration = float(result.total_duration)
    semantic_cores_selected = len(all_selected)
    normalization_metrics = aggregate_normalization_metrics(raw_segments)
    all_selected, boundary_expansions = repair_explanation_boundaries(
        all_selected, raw_segments, global_segments
    )
    expanded_duration = sum(s.duration for s in all_selected)
    all_selected, boundary_stats = repair_physical_boundaries(all_selected)
    merged_duration = sum(s.duration for s in all_selected)
    cta_audit = {}
    all_selected = rebuild_final_texts(
        all_selected, raw_segments, global_segments, audit_stats=cta_audit
    )
    incomplete_rejections = sum(
        float(getattr(segment, "completeness", 0.0)) < 1.0
        for segment in all_selected
    )
    for s in all_selected:
        if float(getattr(s, "completeness", 0.0)) < 1.0:
            print(f"REJECTED: {s.start_time:.2f}-{s.end_time:.2f} dur={s.duration:.1f} start_ev={s.start_boundary_evidence} end_ev={s.end_boundary_evidence} hits={s.non_content_guard_hits}")

    initial_non_content_rejections = sum(
        bool(getattr(segment, "non_content_guard_hits", ())) for segment in all_selected
    )
    all_selected = [segment for segment in all_selected
                    if float(getattr(segment, "completeness", 0.0)) >= 1.0]
    post_cta_duration = sum(s.duration for s in all_selected)
    all_selected, post_cta_boundary_stats = repair_physical_boundaries(all_selected)
    from ..services.coverage_selector import OVERSHOOT_TOLERANCE
    all_selected, reconciliation_stats = reconcile_physical_duration(
        all_selected, global_segments, raw_segments, global_segments, budget,
        min_fill=weights.min_budget_fill,
        overshoot_tolerance=OVERSHOOT_TOLERANCE,
    )
    post_reconciliation_duration = sum(s.duration for s in all_selected)
    keyword_evidence_preserved = 0
    if query_embedding is not None:
        import numpy as np
        q = np.atleast_2d(query_embedding)
        q = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-9)
        for segment in all_selected:
            before = set(getattr(segment, "keyword_matches", ()) or ())
            vector = getattr(segment, "embedding", None)
            scores = (q @ (vector / max(np.linalg.norm(vector), 1e-9))
                      if vector is not None else np.zeros(len(keywords)))
            segment.keyword_scores = {
                keyword: float(score) for keyword, score in zip(keywords, scores)
            }
            segment.keyword_matches = list(dict.fromkeys(
                list(before) + _keyword_evidence_matches(keywords, scores, segment.text)
            ))
            keyword_evidence_preserved += len(before & set(segment.keyword_matches))
    all_selected, final_boundary_stats = repair_physical_boundaries(all_selected)
    if not all_selected:
        return None

    # Freeze the canonical output before reporting source usage. Earlier
    # selector-level counts become stale after organization, boundary merging,
    # rejection, and underfill reconciliation.
    from ..services.clip_manifest import freeze_manifest
    manifest = freeze_manifest(all_selected)
    per_video = _final_per_video_metrics(
        manifest, global_segments, raw_segments, concepts, result
    )

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
    metrics["policy_name"] = policy.name
    metrics["selector_per_video"] = selector_per_video
    metrics["early_stop_diagnostics"] = result.early_stop_diagnostics
    metrics["stage_timings_seconds"] = timings
    metrics["candidate_count"] = len(global_segments)
    metrics["duplicates_rejected"] = getattr(result, "duplicates_rejected", 0)
    metrics["selection_mode"] = "keyword" if keywords else "automatic"
    metrics["selected_keywords"] = keywords
    metrics["incomplete_thought_clips"] = 0
    metrics["semantic_cores_selected"] = semantic_cores_selected
    metrics["repaired_clips_accepted"] = len(all_selected)
    metrics["incomplete_explanation_rejections"] = incomplete_rejections
    metrics["candidates_rejected_without_closure"] = (
        incomplete_rejections
        + reconciliation_stats["closure_rejections_during_reconciliation"]
    )
    metrics["cta_outro_rejections"] = (
        initial_non_content_rejections
        + reconciliation_stats["non_content_candidates_rejected"]
    )
    metrics["mid_thought_starts"] = sum(
        not bool((getattr(segment, "start_boundary_evidence", {}) or {}).get("is_complete"))
        for segment in all_selected
    )
    metrics["mid_thought_ends"] = sum(
        not bool((getattr(segment, "end_boundary_evidence", {}) or {}).get("is_complete"))
        for segment in all_selected
    )
    metrics.update(normalization_metrics)
    metrics.update(boundary_stats.to_dict())
    metrics["adjacent_same_source_merges"] = (
        boundary_stats.adjacent_intervals_merged
        + post_cta_boundary_stats.adjacent_intervals_merged
        + final_boundary_stats.adjacent_intervals_merged
    )
    metrics["explanation_boundary_expansions"] = boundary_expansions
    metrics["expansion_seconds_added"] = round(max(0.0, expanded_duration - selector_duration), 3)
    metrics["merge_seconds_removed"] = round(max(0.0, expanded_duration - merged_duration), 3)
    metrics.update(reconciliation_stats)
    metrics.update(cta_audit)
    metrics["keyword_evidence_preservation_count"] = keyword_evidence_preserved
    metrics.update(concept_block_stats.to_dict())
    metrics["requested_duration"] = round(budget, 1)
    metrics["selector_duration"] = round(selector_duration, 3)
    metrics["post_boundary_duration"] = round(merged_duration, 3)
    metrics["post_cta_duration"] = round(post_cta_duration, 3)
    metrics["post_reconciliation_duration"] = round(post_reconciliation_duration, 3)
    metrics["final_manifest_duration"] = round(sum(s.duration for s in all_selected), 3)
    metrics["largest_physical_block_seconds"] = round(
        max((s.duration for s in all_selected), default=0.0), 3
    )
    metrics["final_budget_fill_ratio"] = round(
        metrics["final_manifest_duration"] / max(float(budget), 1e-6), 4
    )
    metrics["bounded_infeasibility_evidence"] = {
        "candidates_examined": reconciliation_stats.get("candidates_examined", 0),
        "refill_candidates_total": reconciliation_stats.get("refill_candidates_total", 0),
        "refill_candidates_examined": reconciliation_stats.get("refill_candidates_examined", 0),
        "refill_candidates_added": reconciliation_stats.get("refill_candidates_added", 0),
        "rejected_reason_counts": reconciliation_stats.get("rejected_reason_counts", {}),
        "eligible_remaining_candidates": reconciliation_stats.get("eligible_remaining_candidates", 0),
        "eligible_remaining_duration": reconciliation_stats.get("eligible_remaining_duration", 0.0),
        "final_fill_ratio": metrics["final_budget_fill_ratio"],
        "infeasibility_proven": reconciliation_stats.get("infeasibility_proven", False),
        "infeasibility_reason": reconciliation_stats.get("infeasibility_reason"),
    }
    metrics["rendered_duration"] = None
    metrics["manifest_render_delta_seconds"] = None
    metrics["selected_duration"] = metrics["final_manifest_duration"]
    metrics["useful_fill_ratio"] = round(result.useful_fill_ratio, 4)
    metrics["early_stop_reason"] = result.early_stop_reason
    metrics["knowledge_units_covered"] = result.knowledge_units_covered
    metrics["knowledge_plan"] = knowledge_plan.to_dict()
    metrics["content_type"] = content_type_result.content_type
    metrics["content_type_confidence"] = content_type_result.confidence
    metrics["content_type_signals"] = content_type_result.signals
    print(format_metrics_report(metrics, "Semantic selection"))

    # --- 5. hand back the already-frozen canonical manifest ---
    highlights = [clip.to_dict() for clip in manifest]

    return {
        "highlights": highlights,
        "concepts": [c.to_dict() for c in all_concepts],
        "metrics": metrics,
        "trace": all_trace,
        "content_type": content_type_result.content_type,
        "content_type_confidence": content_type_result.confidence,
    }


# =====================================================
# BACKGROUND PROCESSING
# =====================================================

async def process_merge_job(job_id: str, is_worker: bool = False):
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

    acq_token = None
    was_cancelled = False
    delegated_outputs = False
    try:
        job = _active_jobs.get(job_id)
        if not job:
            doc = await jobs_collection.find_one({"job_id": job_id})
            if not doc:
                logger.error("Job %s not found in memory or database; aborting", job_id)
                return
            doc.pop("_id", None)
            job = MergeJob.model_validate(doc)
            _active_jobs[job_id] = job
        content_type = "explanatory"
        content_type_confidence = 0.0
        if not getattr(job, "job_started_at", None):
            job.job_started_at = datetime.utcnow()

        decisions = await create_shadow_job_decisions(
            job_id=job.job_id,
            user_id=job.user_id or "anonymous",
            source_ids=job.video_ids,
        )
        acq_token = set_observation_context(
            job_id=job.job_id,
            user_id=job.user_id or "anonymous",
            decision_ids=decisions,
        )

        pipeline_timings = {name: 0.0 for name in (
            "download_cache", "transcription", "segmentation", "concept_extraction",
            "embedding", "selection", "ordering", "rendering")}

        async def timed_stage(name, operation):
            started = perf_counter()
            try:
                return await operation
            finally:
                pipeline_timings[name] += perf_counter() - started

        # Update status helper with timing and active source tracking
        async def update_status(
            status: JobStatus,
            progress: int,
            message: str,
            active_source: Optional[str] = None,
            stage_name: Optional[str] = None,
            stage_duration: Optional[float] = None,
        ):
            job.status = status
            job.progress_percent = progress
            job.stage_message = message
            job.updated_at = datetime.utcnow()
            if active_source is not None:
                job.active_source = active_source
            if stage_name and stage_duration is not None:
                job.stage_timings_seconds[stage_name] = round(stage_duration, 3)

            elapsed = None
            if getattr(job, "job_started_at", None):
                elapsed = round((datetime.utcnow() - job.job_started_at).total_seconds(), 2)
                job.elapsed_seconds = elapsed

            status_value = status.value if hasattr(status, "value") else status
            job.checkpoint = str(stage_name or status_value)
            job.worker_heartbeat_at = job.updated_at
            set_payload = {
                "status": status_value,
                "progress_percent": progress,
                "stage_message": message,
                "updated_at": job.updated_at,
                "worker_heartbeat_at": job.updated_at,
                "checkpoint": job.checkpoint,
                "stage_timings_seconds": job.stage_timings_seconds,
                "elapsed_seconds": elapsed,
                "transcript_preflight": job.transcript_preflight,
            }
            if active_source is not None:
                set_payload["active_source"] = active_source

            await jobs_collection.update_one(
                {"job_id": job_id},
                {"$set": set_payload}
            )

        async def update_component(
            name: str,
            status: ComponentStatus,
            stage: str,
            progress: int,
            error: Optional[str] = None,
        ):
            """Persist an output lifecycle without changing the legacy job status."""
            state = OutputComponentState(
                status=status,
                stage=stage,
                progress_percent=progress,
                attempts=1,
                error=error,
                updated_at=datetime.utcnow(),
            )
            setattr(job, f"{name}_component", state)
            await jobs_collection.update_one(
                {"job_id": job_id},
                {"$set": {f"{name}_component": state.model_dump()}},
            )

        # Multilingual recovery is part of transcript acquisition for both
        # single- and multi-source jobs. Whisper serializes model inference.
        _is_multi_video = len(job.video_ids) > 1
        _allow_whisper = True
        _per_source_timeout: Optional[float] = float(
            getattr(settings, "TRANSCRIPT_SOURCE_TIMEOUT_SECONDS", 900)
        ) * len(job.video_ids) + settings.TRANSCRIPT_TRANSLATION_TIMEOUT_SECONDS + 90

        # STAGE 1: Transcribing (0-15%)
        await update_status(
            JobStatus.TRANSCRIBING,
            5,
            f"Fetching transcripts for {len(job.video_ids)} video(s)..."
        )

        async def _transcript_progress(message: str):
            # Keep heartbeats/messages live even at the stage ceiling. Only
            # completed sources advance the percentage, not callback count.
            await update_status(JobStatus.TRANSCRIBING, job.progress_percent, message)

        preflight_record: dict = {}
        _completed_sources = 0

        # Persist transcript-preflight progress after EACH individual source completes
        # so UI genuinely shows 1/3 -> 2/3 -> 3/3 in real time.
        async def _on_single_source_completed(vid: str, record: dict):
            nonlocal _completed_sources
            _completed_sources += 1
            ready_c = sum(1 for v in record.values() if v.get("ready"))
            total_c = len(job.video_ids)
            msg = f"Transcripts ready: {ready_c} / {total_c}"
            pct = min(5 + int((_completed_sources / max(total_c, 1)) * 10), 14)
            job.transcript_preflight = dict(record)
            await update_status(JobStatus.TRANSCRIBING, pct, msg, active_source=vid)
            print(f"[Merge] Source completed {vid} ({record.get(vid, {}).get('status')}) -> {msg}")

        t_tr_start = perf_counter()
        transcripts, raw_segments = await fetch_transcripts_with_segments(
            job.video_ids,
            progress_cb=_transcript_progress,
            allow_whisper=_allow_whisper,
            per_source_timeout=_per_source_timeout,
            preflight_record=preflight_record,
            on_source_completed=_on_single_source_completed,
        )
        t_tr_dur = round(perf_counter() - t_tr_start, 3)
        job.stage_timings_seconds["transcript_acquisition"] = t_tr_dur
        pipeline_timings["transcription"] = t_tr_dur

        # INVARIANT: Multi-video requests must never silently drop unavailable sources!
        requested_ids = [extract_video_id(v) for v in job.video_ids]
        ready_ids = list(transcripts.keys())
        unavailable_ids = [vid for vid in requested_ids if vid not in ready_ids]

        if _is_multi_video and unavailable_ids:
            if not getattr(job, "allow_partial_sources", False):
                err_detail = {
                    "error_code": "TRANSCRIPT_UNAVAILABLE_FOR_SOURCES",
                    "message": f"Transcript recovery failed for {len(unavailable_ids)} of {len(requested_ids)} selected videos.",
                    "requested_video_ids": requested_ids,
                    "ready_video_ids": ready_ids,
                    "unavailable_video_ids": unavailable_ids,
                    "sources": preflight_record,
                }
                job.status = JobStatus.ERROR
                job.error = json.dumps(err_detail)
                job.stage_message = f"Error: transcript recovery failed for {len(unavailable_ids)} video(s)."
                job.completed_at = datetime.utcnow()
                await jobs_collection.update_one(
                    {"job_id": job_id},
                    {"$set": {
                        "status": JobStatus.ERROR.value,
                        "error": job.error,
                        "stage_message": job.stage_message,
                        "transcript_preflight": preflight_record,
                        "stage_timings_seconds": job.stage_timings_seconds,
                        "completed_at": job.completed_at,
                    }}
                )
                print(f"[Merge] Job {job_id} halted: TRANSCRIPT_UNAVAILABLE_FOR_SOURCES: {err_detail}")
                return
            else:
                job.requested_video_ids = list(requested_ids)
                job.used_video_ids = list(ready_ids)
                job.video_ids = list(ready_ids)
                await jobs_collection.update_one(
                    {"job_id": job_id},
                    {"$set": {
                        "requested_video_ids": list(requested_ids),
                        "used_video_ids": list(ready_ids),
                        "video_ids": list(ready_ids),
                    }}
                )
                print(f"[Merge] Job {job_id} proceeding with partial sources ({len(ready_ids)}/{len(requested_ids)}) due to explicit allow_partial_sources=True")

        await update_status(
            JobStatus.TRANSCRIBING,
            15,
            f"Fetched {len(transcripts)} transcripts",
            stage_name="transcript_acquisition",
            stage_duration=t_tr_dur,
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

        # English-only capability gate. This is terminal: no vector indexing,
        # semantic segmentation, concept extraction, BGE selection, or media
        # rendering may run after rejection.
        if untranslated_langs:
            detected_languages = sorted(set(untranslated_langs.values()))
            langs = ", ".join(detected_languages)
            rejected_sources = [
                {
                    "source_id": source_id,
                    "detected_language": language,
                    "supported_languages": ["en"],
                }
                for source_id, language in untranslated_langs.items()
            ]
            preflight_failure = {
                "reason": "UNSUPPORTED_TRANSCRIPT_LANGUAGE",
                "error_code": "UNSUPPORTED_TRANSCRIPT_LANGUAGE",
                "detected_language": langs,
                "supported_languages": ["en"],
                "source_id": rejected_sources[0]["source_id"] if len(rejected_sources) == 1 else None,
                "sources": rejected_sources,
            }
            message = (
                f"Summary unavailable — we couldn't convert this video's transcript into supported English text. "
                "Try another video."
            )
            print(
                f"[WARN] LANGUAGE CAPABILITY ABORT: {preflight_failure}; "
                "stopping before semantic and video stages"
            )
            job.status = JobStatus.PARTIAL_SUCCESS
            job.progress_percent = 100
            job.stage_message = "Summary unavailable — unsupported transcript language"
            job.warning = message
            job.summary_unavailable = True
            job.summary_unavailable_reason = "UNSUPPORTED_TRANSCRIPT_LANGUAGE"
            job.detected_language = langs
            job.supported_languages = ["en"]
            job.preflight_failure = preflight_failure
            job.summary_text = None
            job.rich_output = None
            job.fusion_metadata = None
            job.highlight_segments = []
            job.video_path = None
            job.audio_path = None
            job.completed_at = datetime.utcnow()
            await jobs_collection.update_one(
                {"job_id": job_id},
                {"$set": {
                    "status": JobStatus.PARTIAL_SUCCESS.value,
                    "progress_percent": 100,
                    "stage_message": job.stage_message,
                    "warning": message,
                    "summary_unavailable": True,
                    "summary_unavailable_reason": "UNSUPPORTED_TRANSCRIPT_LANGUAGE",
                    "detected_language": langs,
                    "supported_languages": ["en"],
                    "preflight_failure": preflight_failure,
                    "summary_text": None,
                    "rich_output": None,
                    "fusion_metadata": None,
                    "highlight_segments": [],
                    "video_path": None,
                    "audio_path": None,
                    "transcript_preflight": preflight_record,
                    "stage_timings_seconds": job.stage_timings_seconds,
                    "completed_at": job.completed_at,
                }}
            )
            return

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
            job_warning = (
                f"This video's transcript is in '{langs}' and could not be translated. "
                f"Written summary unavailable ('{langs}' transcript). "
                f"Generating video highlights..."
            )
            job.warning = job_warning
            job.summary_unavailable = True
            job.summary_unavailable_reason = "UNSUPPORTED_LANGUAGE"
            job.detected_language = langs

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
            fusion_result = None

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

            # Do NOT set PARTIAL_SUCCESS here — video generation has not run yet.
            # Store the language metadata without changing the terminal status, so
            # the frontend stays on the processing screen until VIDEO_READY.
            job.stage_message = (
                f"Written summary unavailable ('{langs}' transcript). "
                f"Generating video highlights..."
            )
            job.warning = job_warning
            job.summary_unavailable = True
            job.summary_unavailable_reason = "UNSUPPORTED_LANGUAGE"
            job.detected_language = langs
            await jobs_collection.update_one(
                {"job_id": job_id},
                {"$set": {
                    # Status intentionally NOT changed here — keep the job in its
                    # current processing state (ANALYZING / TRANSCRIBING) so the
                    # frontend does not interpret this as a terminal result.
                    "stage_message": job.stage_message,
                    
                    "summary_unavailable": True,
                    "summary_unavailable_reason": "UNSUPPORTED_LANGUAGE",
                    "detected_language": langs,
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

        selection_bias_fusion = None

        if not _language_abort:
            # STAGE 2: Fusion / Analysis (15-25%)
            await update_status(
                JobStatus.ANALYZING,
                18,
                "Analyzing content structure across sources..."
            )

            # Get duration profile
            profile = get_profile(job.target_duration_minutes)
            target_words = profile.target_words
            fusion_budget = profile.target_minutes * profile.words_per_minute

            await update_status(
                JobStatus.FUSING,
                20,
                f"Fusing transcripts (Target: {target_words} words, {profile.style.value} style)..."
            )

            # Run the expensive full-transcript bias fusion only for an
            # explicit keyword summary. Overall highlight selection already
            # optimizes concept coverage and temporal diversity directly; a
            # second representation of the same transcript adds substantial
            # latency without adding a user-supplied relevance target.
            fusion_engine = await asyncio.to_thread(get_fusion_engine)
            needs_selection_bias = (
                getattr(job, "summary_scope", None) == "keyword"
                and bool(
                    getattr(job, "summary_query", None)
                    or getattr(job, "query", None)
                    or getattr(job, "selected_keywords", None)
                )
            )
            if needs_selection_bias:
                t_fus_start = perf_counter()
                selection_bias_fusion = await asyncio.to_thread(
                    fusion_engine.fuse_transcripts,
                    transcripts=transcripts,
                    target_words=fusion_budget,
                    include_sources=profile.include_sources,
                    include_transitions=profile.include_transitions,
                    raw_segments=raw_segments,
                )
                t_fus_dur = round(perf_counter() - t_fus_start, 3)
            else:
                t_fus_dur = 0.0
                print("[Fusion 1/2] Skipped for overall video-first selection")
            job.stage_timings_seconds["fusion_analysis"] = t_fus_dur
            pipeline_timings["fusion_analysis"] = t_fus_dur

            topics_count = len(selection_bias_fusion.topics) if selection_bias_fusion else 0
            await update_status(
                JobStatus.FUSING,
                25,
                (
                    f"Fusion analysis complete ({topics_count} topics identified)"
                    if needs_selection_bias
                    else "Video-first selection ready"
                ),
                stage_name="fusion_analysis",
                stage_duration=t_fus_dur,
            )

        if not _language_abort:
            # -------------------------------------------------------------
            # NEW ARCHITECTURE: SELECT FIRST, THEN SUMMARIZE
            # -------------------------------------------------------------
            video_path = None
            audio_path = None
            subtitle_path = None
            job_warning = None
            highlight_segments_result = []
            keyframes_extracted = {}
            job_concepts = []
            selection_metrics = None
            selection_trace = []
            selection_mode = "legacy"
            content_type = "explanatory"
            content_type_confidence = 0.0

            video_paths = {}

        video_error = False
        if job.generate_video:
            await update_status(
                JobStatus.GENERATING_VIDEO,
                50,
                (
                    "Selecting evidence for independent output workers..."
                    if settings.SEPARATE_OUTPUT_WORKERS_ENABLED
                    else "Downloading source videos and selecting highlights..."
                )
            )

            try:
                from ..services.video_service import get_video_service
                from ..services.visual_keyframe_extractor import extract_keyframes_for_segments
                from ..services.segment_extractor import extract_highlight_segments, group_transcript_segments

                video_svc = get_video_service()

                await update_status(
                    JobStatus.GENERATING_VIDEO, 55,
                    (
                        "Selecting complete evidence segments..."
                        if settings.SEPARATE_OUTPUT_WORKERS_ENABLED
                        else "Downloading source videos for highlight extraction..."
                    )
                )
                unique_video_ids = list(raw_segments.keys())

                async def video_progress(msg):
                    # Once the concurrent text branch has started, FFmpeg
                    # progress must not move the shared job status backwards.
                    if job.progress_percent < 84:
                        await update_status(JobStatus.GENERATING_VIDEO, 60, msg)

                _total_source_seconds = sum(
                    _source_duration(raw_segments.get(v, []))
                    for v in unique_video_ids
                )

                download_task = None
                if not settings.SEPARATE_OUTPUT_WORKERS_ENABLED:
                    download_task = asyncio.create_task(
                        timed_stage("download_cache", video_svc.download_videos(
                            unique_video_ids,
                            job_id=job_id,
                            progress_callback=video_progress,
                            source_duration_seconds=_total_source_seconds,
                        ))
                    )

                semantic_task = None
                if settings.ENABLE_SEMANTIC_SELECTION:
                    semantic_task = asyncio.create_task(
                        run_semantic_selection(
                            job=job,
                            raw_segments={v: raw_segments.get(v, []) for v in unique_video_ids},
                            semantic_bias_text=selection_bias_fusion.narrative if selection_bias_fusion else "",
                            progress=video_progress,
                        )
                    )

                if semantic_task and download_task:
                    dl_result, sem_result = await asyncio.gather(download_task, semantic_task, return_exceptions=True)
                elif semantic_task:
                    dl_result = {}
                    sem_result = await semantic_task
                else:
                    if download_task is None:
                        raise RuntimeError(
                            "Separate output workers require semantic selection to publish a manifest."
                        )
                    dl_result = await download_task
                    sem_result = None

                if isinstance(dl_result, Exception):
                    raise dl_result
                video_paths = dl_result
                
                if not video_paths and not settings.SEPARATE_OUTPUT_WORKERS_ENABLED:
                    raise Exception("Could not download any source videos")

                semantic = None
                if semantic_task:
                    if isinstance(sem_result, (TypeError, AttributeError)):
                        import traceback
                        traceback.print_exception(sem_result)
                        raise RuntimeError(
                            f"[Semantic] Integration error in run_semantic_selection — "
                            f"semantic path is broken, NOT falling back to legacy: {sem_result}"
                        ) from sem_result
                    elif isinstance(sem_result, Exception):
                        if len(unique_video_ids) > 1:
                            raise RuntimeError(f"Multi-video semantic selection failed: {sem_result}") from sem_result
                        print(f"[Semantic] Pipeline failed with operational error: {sem_result}")
                        import traceback
                        traceback.print_exception(sem_result)
                        print("[Semantic] Falling back to legacy scorer (operational failure, not a coding error)")
                    else:
                        semantic = sem_result
                        if semantic and semantic.get("highlights"):
                            from ..services.clip_manifest import validate_manifest
                            validate_manifest(
                                semantic["highlights"],
                                video_paths or None,
                            )

                if semantic and semantic["highlights"]:
                    highlight_segments_result = semantic["highlights"]
                    job_concepts = semantic["concepts"]
                    selection_metrics = semantic["metrics"]
                    pipeline_timings.update(selection_metrics.get("stage_timings_seconds", {}))
                    selection_metrics["stage_timings_seconds"] = pipeline_timings
                    selection_trace = semantic["trace"]
                    selection_mode = "semantic"
                    content_type = semantic.get("content_type", "explanatory")
                    content_type_confidence = float(semantic.get("content_type_confidence", 0.0))
                    all_highlights = list(highlight_segments_result)
                else:
                    if settings.ENABLE_SEMANTIC_SELECTION and len(unique_video_ids) > 1:
                        raise RuntimeError("Multi-video semantic selection returned no complete clips")
                    if settings.ENABLE_SEMANTIC_SELECTION:
                        print("[Semantic] No usable selection — running legacy scorer")
                    all_highlights = await _legacy_select_highlights(
                        job=job,
                        video_paths=video_paths,
                        raw_segments=raw_segments,
                        semantic_bias_text=selection_bias_fusion.narrative if selection_bias_fusion else "",
                        update_status=update_status,
                        keyframes_extracted=keyframes_extracted,
                    )

                if all_highlights:
                    if selection_mode != "semantic":
                        all_highlights.sort(
                            key=lambda h: h.get("importance_score", 0), reverse=True
                        )
                        highlight_segments_result = _fit_to_duration(
                            all_highlights, job.highlight_duration_seconds
                        )
                        highlight_segments_result.sort(
                            key=lambda h: (h["video_id"], h["start_time"])
                        )
                    
                    if selection_mode != "semantic":
                        highlight_segments_result = _merge_overlapping_clips(highlight_segments_result)

                    _reel_seconds = sum(
                        h["end_time"] - h["start_time"] for h in highlight_segments_result
                    )
                    print(f"[Video] {len(highlight_segments_result)} clips kept "
                          f"({_reel_seconds:.0f}s) for a {job.highlight_duration_seconds}s reel "
                          f"[{selection_mode} selection]")
                else:
                    video_error = True
                    w_msg = "Video generation skipped because no highlight segments were identified."
                    job_warning = (job_warning + " | " + w_msg) if job_warning else w_msg
                    print(f"[Video] {w_msg}")

            except Exception as e:
                video_error = True
                w_msg = f"Video selection failed: {e}"
                job_warning = (job_warning + " | " + w_msg) if job_warning else w_msg
                print(f"[WARN] {w_msg}")
                import traceback
                traceback.print_exc()

        async def _run_video_output_branch():
            nonlocal video_path, audio_path, job_warning
            if not (job.generate_video and highlight_segments_result and not video_error):
                if job.generate_video:
                    await update_component(
                        "video", ComponentStatus.FAILED, "selection_failed", 100,
                        job_warning or "No valid highlight evidence was selected.",
                    )
                return
            try:
                await update_component("video", ComponentStatus.RUNNING, "rendering", 10)
                # Video output has no dependency on BART/enrichment. This
                # branch runs concurrently with the text branch below.
                if job.progress_percent < 84:
                    await update_status(
                        JobStatus.GENERATING_VIDEO, 68,
                        f"Cutting and stitching {len(highlight_segments_result)} highlight clips..."
                    )

                t_render_start = perf_counter()
                rendered_sources = set(h.get("video_id") for h in highlight_segments_result if h.get("video_id"))
                for vid in rendered_sources:
                    await append_event(
                        source_id=vid,
                        operation="derived_media_generate",
                        phase="attempted",
                        method="ffmpeg_concat",
                        outcome_code="started",
                    )
                video_path = await timed_stage("rendering", video_svc.generate_highlight_reel(
                    job_id=job.job_id,
                    highlight_segments=highlight_segments_result,
                    video_paths=video_paths,
                    audio_path=None,   # never overlaid; reel keeps source audio
                    progress_callback=video_progress,
                ))
                for vid in rendered_sources:
                    await append_event(
                        source_id=vid,
                        operation="derived_media_generate",
                        phase="succeeded" if video_path else "failed",
                        method="ffmpeg_concat",
                        outcome_code="success" if video_path else "error",
                    )
                t_render_dur = round(perf_counter() - t_render_start, 3)
                job.stage_timings_seconds["concat_render"] = t_render_dur

                print(f"[Video] Highlight reel generated: {video_path}")

                if selection_metrics is not None:
                    from ..services.manifest_boundary_repair import probe_rendered_duration
                    rendered_duration = probe_rendered_duration(video_path)
                    selection_metrics["rendered_duration"] = (
                        round(rendered_duration, 3) if rendered_duration is not None else None
                    )
                    manifest_duration = selection_metrics.get("final_manifest_duration")
                    selection_metrics["manifest_render_delta_seconds"] = (
                        round(abs(float(manifest_duration) - rendered_duration), 3)
                        if rendered_duration is not None and manifest_duration is not None else None
                    )

                # Rights evidence and the aggregate gate must be frozen before
                # VIDEO_READY or the media path is exposed to any client.
                t_rights_start = perf_counter()
                await _freeze_job_rights(job, jobs_collection)
                job.stage_timings_seconds["rights_snapshot"] = round(
                    perf_counter() - t_rights_start, 3
                )
                # Persist the media immediately. The text branch may already
                # be running, so the checkpoint below never moves its shared
                # status/progress backwards.
                job.video_path = video_path
                job.highlight_segments = highlight_segments_result
                job.keyframes_extracted = keyframes_extracted
                job.concepts = job_concepts
                job.selection_metrics = selection_metrics
                job.selection_trace = selection_trace
                job.selection_mode = selection_mode
                job.content_type = content_type
                job.content_type_confidence = content_type_confidence
                # Publish VIDEO_READY only if the text branch has not already
                # advanced farther. Otherwise persist the media fields without
                # regressing SUMMARIZING (86/90%) back to 82%.
                publish_video_ready = job.progress_percent < 84
                if publish_video_ready:
                    job.status = JobStatus.VIDEO_READY
                    job.progress_percent = 82
                    job.stage_message = (
                        "Highlight video ready — written summary unavailable for this language."
                        if _language_abort
                        else "Highlight video ready — generating AI summary..."
                    )
                job.updated_at = datetime.utcnow()
                if getattr(job, "job_started_at", None):
                    job.elapsed_seconds = round((datetime.utcnow() - job.job_started_at).total_seconds(), 2)

                video_checkpoint = {
                        "updated_at": job.updated_at,
                        "video_path": video_path,
                        "has_video_ready": True,
                        "highlight_segments": highlight_segments_result,
                        "keyframes_extracted": keyframes_extracted,
                        "concepts": job_concepts,
                        "selection_metrics": selection_metrics,
                        "selection_trace": selection_trace,
                        "selection_mode": selection_mode,
                        "content_type": content_type,
                        "content_type_confidence": content_type_confidence,
                        "warning": job_warning,
                        "stage_timings_seconds": job.stage_timings_seconds,
                        "elapsed_seconds": job.elapsed_seconds,
                        "active_source": job.active_source,
                        "transcript_preflight": getattr(job, "transcript_preflight", None),
                        "summary_unavailable": job.summary_unavailable,
                        "summary_unavailable_reason": job.summary_unavailable_reason,
                        "detected_language": job.detected_language,
                }
                if publish_video_ready:
                    video_checkpoint.update({
                        "status": JobStatus.VIDEO_READY.value,
                        "progress_percent": 82,
                        "stage_message": job.stage_message,
                    })
                await jobs_collection.update_one(
                    {"job_id": job_id},
                    {"$set": video_checkpoint}
                )

                # MP3 extraction is a separate downloadable artifact, not a
                # gate on VIDEO_READY — the reel's own audio track is already
                # embedded and playable. It runs here, after the checkpoint
                # above, and rides along in the job's final $set once done.
                if job.generate_audio and video_path:
                    audio_path = await asyncio.to_thread(
                        _extract_audio_from_reel, video_path, job.job_id
                    )
                await update_component("video", ComponentStatus.READY, "ready", 100)

            except Exception as e:
                job_warning = f"Video stitching failed: {e}"
                print(f"[WARN] {job_warning}")
                import traceback
                traceback.print_exc()
                video_path = None
                await update_component(
                    "video", ComponentStatus.FAILED, "render_failed", 100, str(e)
                )
            finally:
                import shutil as _shutil
                _dl_dir = os.path.join("audio_cache", "video_downloads", job_id)
                if os.path.isdir(_dl_dir):
                    _shutil.rmtree(_dl_dir, ignore_errors=True)
                    print(f"[Video] Cleaned up download dir: {_dl_dir}")

        # Persist the immutable shared handoff before either output branch
        # consumes it. This is additive during the migration: existing branch
        # inputs remain untouched until the dedicated workers are introduced.
        if highlight_segments_result:
            from ..services.evidence_manifest import build_evidence_manifest
            try:
                evidence_manifest = build_evidence_manifest(job, highlight_segments_result)
                job.evidence_manifest = evidence_manifest.model_dump()
                await jobs_collection.update_one(
                    {"job_id": job_id},
                    {"$set": {"evidence_manifest": job.evidence_manifest}},
                )
            except (TypeError, ValueError) as exc:
                # Additive migration safety: legacy clips can lack transcript
                # text. Do not turn a contract rollout into a media regression.
                logger.warning("Evidence manifest not published for job %s: %s", job_id, exc)

        # Production manifest-first path. Dispatch is all-or-nothing: if queue
        # publication fails, this process continues through the proven inline
        # branches rather than leaving a job with no output owner.
        if (
            settings.SEPARATE_OUTPUT_WORKERS_ENABLED
            and job.evidence_manifest
            and job.generate_video
        ):
            try:
                from ..services.output_task_queue import (
                    activate_output_tasks,
                    cancel_held_output_tasks,
                    enqueue_output_task,
                )
                database = await get_database()
                manifest_version = int(job.evidence_manifest["manifest_version"])
                await enqueue_output_task(
                    database, job_id=job_id, manifest_version=manifest_version,
                    output_type="video", initial_status="held",
                )
                expected_tasks = 1
                if not _language_abort:
                    await enqueue_output_task(
                        database, job_id=job_id, manifest_version=manifest_version,
                        output_type="text", initial_status="held",
                    )
                    expected_tasks = 2

                # Record durable ownership before releasing either task. If
                # the API dies after this write, startup recovery preserves
                # the job and the held tasks can safely remain unclaimed until
                # dispatch is retried. Once activation succeeds, ownership is
                # irrevocably with the output workers and inline generation
                # must not run as a fallback.
                await jobs_collection.update_one(
                    {"job_id": job_id},
                    {"$set": {
                        "output_execution_mode": "durable_workers",
                        "output_dispatch_state": "prepared",
                        "output_manifest_version": manifest_version,
                        "output_expected_tasks": expected_tasks,
                        "updated_at": datetime.utcnow(),
                    }},
                )
                activated = await activate_output_tasks(
                    database, job_id=job_id, manifest_version=manifest_version
                )
                if activated != expected_tasks:
                    await cancel_held_output_tasks(
                        database, job_id=job_id, manifest_version=manifest_version
                    )
                    await jobs_collection.update_one(
                        {"job_id": job_id},
                        {"$unset": {
                            "output_execution_mode": "",
                            "output_dispatch_state": "",
                            "output_manifest_version": "",
                            "output_expected_tasks": "",
                        }},
                    )
                    raise RuntimeError(
                        f"Expected {expected_tasks} held output tasks, activated {activated}."
                    )
                job.video_component = OutputComponentState(
                    status=ComponentStatus.QUEUED, stage="queued", progress_percent=0
                )
                job.text_component = OutputComponentState(
                    status=(ComponentStatus.FAILED if _language_abort else ComponentStatus.QUEUED),
                    stage=("unsupported_language" if _language_abort else "queued"),
                    progress_percent=(100 if _language_abort else 0),
                    error=(job.summary_unavailable_reason if _language_abort else None),
                )
                job.status = JobStatus.GENERATING_VIDEO
                job.progress_percent = 65
                job.stage_message = "Evidence ready — video and text outputs queued independently."
                await jobs_collection.update_one(
                    {"job_id": job_id},
                    {"$set": {
                        "status": JobStatus.GENERATING_VIDEO.value,
                        "progress_percent": 65,
                        "stage_message": job.stage_message,
                        "video_component": job.video_component.model_dump(),
                        "text_component": job.text_component.model_dump(),
                        "highlight_segments": highlight_segments_result,
                        "concepts": job_concepts,
                        "selection_metrics": selection_metrics,
                        "selection_trace": selection_trace,
                        "selection_mode": selection_mode,
                        "content_type": content_type,
                        "content_type_confidence": content_type_confidence,
                        "stage_timings_seconds": job.stage_timings_seconds,
                        "output_execution_mode": "durable_workers",
                        "output_dispatch_state": "active",
                        "output_manifest_version": manifest_version,
                        "output_expected_tasks": expected_tasks,
                    }},
                )
                delegated_outputs = True
                return
            except Exception as exc:
                logger.exception(
                    "Output dispatch failed for job %s; continuing inline: %s",
                    job_id, exc,
                )

        if _language_abort:
            await update_component(
                "text", ComponentStatus.FAILED, "unsupported_language", 100,
                job.summary_unavailable_reason or "Written summary unavailable.",
            )
        else:
            await update_component("text", ComponentStatus.RUNNING, "planning", 5)

        # Start rendering immediately, then continue into transcript
        # reconstruction/BART without waiting for FFmpeg. Both branches are
        # joined before the terminal job status is persisted.
        video_output_task = asyncio.create_task(_run_video_output_branch())

        summary_failed = False
        summary_error_msg = None
        if not _language_abort:
            try:
                # --- Transcript Reconstruction & Selected Fusion ---
                await update_status(
                    JobStatus.FUSING, 84,
                    "Reconstructing transcript from selected video segments..."
                )
                selected_transcripts_map = {}
                selected_raw_segments = {}
                selected_evidence = None
                if job.generate_video and highlight_segments_result and not video_error:
                    selected_evidence = [
                        {
                            "order": index,
                            "video_id": h.get("video_id"),
                            "start_time": h.get("start_time", 0.0),
                            "end_time": h.get("end_time", 0.0),
                            "text": h.get("text", ""),
                            "start_boundary_evidence": h.get("start_boundary_evidence"),
                            "repair_lineage": h.get("repair_lineage"),
                        }
                        for index, h in enumerate(highlight_segments_result)
                    ]
                    for h in highlight_segments_result:
                        vid = h.get("video_id")
                        if vid not in selected_raw_segments:
                            selected_raw_segments[vid] = []
                        selected_raw_segments[vid].append(h)

                    for vid, segs in selected_raw_segments.items():
                        segs.sort(key=lambda x: x.get("start_time", 0))
                        selected_transcripts_map[vid] = " ".join(s.get("text", "") for s in segs)
                else:
                    if job.generate_video and not highlight_segments_result:
                        print("[WARN] Video selection yielded empty segments. Falling back to full transcript for text summary.")
                    selected_transcripts_map = transcripts
                    selected_raw_segments = raw_segments

                from ..services.content_intelligence import (
                    build_content_plan,
                    detect_content_type,
                    enrich_summary,
                )
                if not content_type_confidence:
                    flattened = [segment for segments in selected_raw_segments.values() for segment in segments]
                    detected = detect_content_type(flattened)
                    content_type = detected.content_type
                    content_type_confidence = detected.confidence

                plan_evidence = selected_evidence
                if plan_evidence is None:
                    plan_evidence = []
                    for video_id, segments in selected_raw_segments.items():
                        for order, segment in enumerate(segments):
                            start = float(segment.get("start", segment.get("start_time", 0.0)) or 0.0)
                            duration = float(segment.get("duration", 0.0) or 0.0)
                            end = float(segment.get("end", segment.get("end_time", start + duration)) or start + duration)
                            plan_evidence.append({
                                "order": order,
                                "video_id": video_id,
                                "start_time": start,
                                "end_time": end,
                                "text": segment.get("text", ""),
                            })
                phase3_timings = {}
                content_plan_started = perf_counter()
                content_plan = build_content_plan(
                    plan_evidence, content_type, content_type_confidence
                )
                phase3_timings["content_plan_construction"] = round(
                    perf_counter() - content_plan_started, 4
                )

                clean_selected_evidence = [
                    {
                        "video_id": block.video_id,
                        "start_time": block.start_time,
                        "end_time": block.end_time,
                        "text": block.clean_text,
                    }
                    for block in content_plan.blocks
                ]

                # SECOND PASS — fuse ONLY the selected segments → this is the BART input.
                fusion_result = await asyncio.to_thread(
                    fusion_engine.fuse_transcripts,
                    transcripts=selected_transcripts_map,
                    target_words=fusion_budget,
                    # Provenance remains on selected_evidence and fusion
                    # metadata. Never serialize source IDs into BART prose.
                    include_sources=False,
                    # ContentPlan paragraphs are already organized. Synthetic
                    # connective scaffolding wastes BART context and can leak
                    # into short-path summaries.
                    include_transitions=False,
                    raw_segments=selected_raw_segments,
                    selected_evidence=clean_selected_evidence,
                )
                print(
                    f"[Fusion 2/2] Selected-segments pass: "
                    f"{len(fusion_result.topics)} topics, "
                    f"{len(fusion_result.narrative.split())} words "
                    f"— this is the BART input"
                )

                # STAGE 4: Summarizing (85-92%) - BART-large-CNN Hierarchical
                await update_status(
                    JobStatus.SUMMARIZING,
                    86,
                    "Running BART-large-CNN hierarchical summarization on selected content..."
                )

                from ..services.summarization_service import get_summarization_service

                print(f"[BART] Input narrative: {len(fusion_result.narrative.split())} words")
                summarizer_svc = get_summarization_service()
                t_bart_start = perf_counter()
                loop = asyncio.get_running_loop()

                def on_bart_chunk_done(done: int, total: int):
                    pct = min(91, 86 + int(5 * (done / max(total, 1))))
                    msg = f"Running BART-large-CNN summarization (Chunk {done}/{total})..."
                    try:
                        asyncio.run_coroutine_threadsafe(
                            update_status(JobStatus.SUMMARIZING, pct, msg),
                            loop
                        )
                    except Exception:
                        pass

                summary_text, summarization_decision = await asyncio.to_thread(
                    summarizer_svc.summarize_with_policy,
                    fusion_result.narrative,
                    target_words,
                    profile,
                    None,
                    content_type,
                    on_bart_chunk_done,
                )
                from ..services.text_normalization import sanitize_summary_text
                summary_text = sanitize_summary_text(summary_text)
                t_bart_dur = round(perf_counter() - t_bart_start, 3)
                job.stage_timings_seconds["bart_summarization"] = t_bart_dur

                # Store metadata
                total_src_words = sum(len(t.split()) for t in transcripts.values()) if transcripts else fusion_result.metadata.get("total_source_words", 0)
                out_words = len(summary_text.split())
                comp_ratio = round(min(max(out_words / max(total_src_words, 1), 0.0), 1.0), 4) if total_src_words > 0 else 0.0

                from ..services.text_normalization import sanitize_asr_items
                clean_topics = sanitize_asr_items(fusion_result.topics, min_words=2, limit=10)
                if not clean_topics and job_concepts:
                    clean_topics = [
                        c["name"].strip() if isinstance(c, dict) and c.get("name") else (str(c).strip() if isinstance(c, str) else "")
                        for c in job_concepts
                    ]
                    clean_topics = list(dict.fromkeys(t for t in clean_topics if t))[:10]

                fusion_metadata = FusionMetadata(
                    total_source_words=total_src_words,
                    output_words=out_words,
                    compression_ratio=comp_ratio,
                    topics_found=clean_topics,
                    clusters_created=fusion_result.metadata.get("clusters_created", 0),
                    dedup_ratio=fusion_result.metadata.get("dedup_ratio", 0),
                    processing_time_seconds=fusion_result.metadata.get("processing_time_seconds", 0),
                    video_count=len(transcripts),
                )

                await update_status(
                    JobStatus.SUMMARIZING,
                    90,
                    f"BART summary ready: {len(summary_text.split())} words",
                    stage_name="bart_summarization",
                    stage_duration=t_bart_dur,
                )

                # STAGE 4.5: deterministic content-aware enrichment (90-95%)
                t_enr_start = perf_counter()
                print("[LocalEnrich] Generating global TLDR, highlights and chapters...")
                enrichment_embedder = None
                try:
                    enrichment_embedder = fusion_engine.embedder
                except Exception:
                    pass
                rich_output, enriched_topics = await asyncio.to_thread(
                    enrich_summary,
                    summary_text,
                    content_plan,
                    job.style,
                    embedder=enrichment_embedder,
                    timings=phase3_timings,
                )
                if content_type == "narrative" and rich_output.summary:
                    summary_text = rich_output.summary
                if enriched_topics:
                    # Preserve the selected-evidence BGE clusters.  Content-plan
                    # labels only fill gaps after the cluster labels have been
                    # cleaned; they never replace clustering.
                    existing_topics = list(fusion_metadata.topics_found or [])
                    seen_topics = {topic.casefold() for topic in existing_topics}
                    existing_topics.extend(
                        topic for topic in enriched_topics
                        if topic.casefold() not in seen_topics
                    )
                    fusion_metadata.topics_found = existing_topics[:10]

                t_enr_dur = round(perf_counter() - t_enr_start, 3)
                job.stage_timings_seconds["enrichment"] = t_enr_dur
                phase3_timings["total_enrichment"] = t_enr_dur
                job.stage_timings_seconds.update(phase3_timings)
                await update_component("text", ComponentStatus.READY, "ready", 100)
            except Exception as e:
                # The error classification depends on whether the independent
                # video branch succeeded, so join it before choosing between a
                # partial result and a terminal job failure.
                await video_output_task
                if video_path:
                    summary_failed = True
                    summary_error_msg = str(e)
                    summary_text = None
                    rich_output = None
                    summarization_decision = None
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
                    print(f"[ERROR] Summary generation failed after video was ready: {summary_error_msg}")
                    await update_component(
                        "text", ComponentStatus.FAILED, "generation_failed", 100,
                        summary_error_msg,
                    )
                    import traceback
                    traceback.print_exc()
                else:
                    raise

        # Both independent output branches must settle before the final result
        # is classified and exposed as complete.
        await video_output_task

        # COMPLETED
        if _language_abort:
            job.status = JobStatus.PARTIAL_SUCCESS
            if video_path:
                job.stage_message = "Highlight video ready — written summary unavailable for this language."
            else:
                job.stage_message = "Highlight video generation failed — written summary also unavailable for this language."
        elif summary_failed and video_path:
            job.status = JobStatus.PARTIAL_SUCCESS
            job.stage_message = "Highlight video ready, but AI summary generation failed."
            job_warning = job_warning or summary_error_msg
        elif job.generate_video and not video_path:
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
        selection_metrics = selection_metrics or {}
        selection_metrics["stage_timings_seconds"] = pipeline_timings
        job.highlight_segments = highlight_segments_result
        job.keyframes_extracted = keyframes_extracted
        job.concepts = job_concepts
        job.selection_metrics = selection_metrics
        job.selection_trace = selection_trace
        job.summarization_decision = summarization_decision
        job.selection_mode = selection_mode
        job.content_type = content_type
        job.content_type_confidence = content_type_confidence
        job.warning = job_warning
        job.completed_at = datetime.utcnow()
        if getattr(job, "job_started_at", None):
            job.elapsed_seconds = round((datetime.utcnow() - job.job_started_at).total_seconds(), 2)

        # Jobs without early video readiness still freeze rights before their
        # final result becomes visible. Existing snapshots are returned intact.
        if not getattr(job, "rights_snapshot", None):
            t_rights_start = perf_counter()
            try:
                await _freeze_job_rights(job, jobs_collection)
            except Exception as e:
                # Notes may complete, but absent evidence can never authorize
                # source-footage delivery.
                print(f"[Rights] Could not freeze snapshot for job {job_id}: {e}")
                job.publication_gate_status = "restricted_by_product_policy"
                job.rights_summary = {
                    "gate_status": "restricted_by_product_policy",
                    "warnings": ["Rights evidence could not be frozen; media delivery is blocked."],
                    "source_count": 0,
                }
            job.stage_timings_seconds["rights_snapshot"] = round(
                perf_counter() - t_rights_start, 3
            )

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
                "content_type": content_type,
                "content_type_confidence": content_type_confidence,
                "warning": job_warning,
                "publication_gate_status": getattr(job, "publication_gate_status", "manual_review_required"),
                "rights_summary": getattr(job, "rights_summary", {}),
                "source_durations": getattr(job, "source_durations", {}),
                "stage_timings_seconds": getattr(job, "stage_timings_seconds", {}),
                "elapsed_seconds": getattr(job, "elapsed_seconds", 0.0),
                "active_source": getattr(job, "active_source", None),
                "transcript_preflight": getattr(job, "transcript_preflight", None),
                "completed_at": getattr(job, "completed_at", None),
                "summary_unavailable": getattr(job, "summary_unavailable", False),
                "summary_unavailable_reason": getattr(job, "summary_unavailable_reason", None),
                "detected_language": getattr(job, "detected_language", None),
            }}
        )

        # Trigger background precomputation of quality scorecard so frontend gets instant cached result
        if summary_text and not getattr(job, "summary_unavailable", False):
            try:
                asyncio.create_task(precompute_job_quality_scorecard(job_id, jobs_collection))
            except Exception as qc_err:
                print(f"[Quality] Scorecard task schedule warning: {qc_err}")




    except Exception as e:
        error_msg = str(e)
        print(f"[ERROR] Job {job_id} failed: {error_msg}")
        import traceback
        traceback.print_exc()

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

    except asyncio.CancelledError:
        was_cancelled = True
        if job.status not in (JobStatus.COMPLETED, JobStatus.PARTIAL_SUCCESS, JobStatus.VIDEO_READY):
            job.status = JobStatus.CANCELLED
            job.error = "Job was cancelled"
            try:
                loop = asyncio.get_running_loop()
                if not loop.is_closed():
                    await jobs_collection.update_one(
                        {"job_id": job_id},
                        {"$set": {
                            "status": JobStatus.CANCELLED.value,
                            "error": job.error,
                            "updated_at": datetime.utcnow(),
                        }}
                    )
            except Exception as exc:
                logger.warning(
                    "Cancellation state persistence failed for job %s: %s",
                    job_id,
                    exc,
                )
        raise
    finally:
        try:
            if acq_token is not None:
                try:
                    loop = asyncio.get_running_loop()
                    if not loop.is_closed():
                        if job.status == JobStatus.CANCELLED:
                            finalization_reason = "job_cancelled"
                        elif job.status in (
                            JobStatus.COMPLETED,
                            JobStatus.PARTIAL_SUCCESS,
                            JobStatus.VIDEO_READY,
                        ):
                            finalization_reason = "job_completed"
                        else:
                            finalization_reason = "job_failed"
                        await finalize_shadow_manifest(job_id, finalization_reason)
                except Exception as exc:
                    logger.warning(
                        "Acquisition manifest finalization failed for job %s: %s",
                        job_id,
                        exc,
                    )

            # Preserve the existing five-minute in-memory retention for normal
            # completion/error paths. Cancellation performs minimal cleanup and
            # must propagate immediately.
            if not was_cancelled and not delegated_outputs and not is_worker:
                try:
                    loop = asyncio.get_running_loop()
                    if not loop.is_closed():
                        await asyncio.sleep(300)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "Job retention cleanup failed for job %s: %s",
                        job_id,
                        exc,
                    )
        finally:
            if acq_token is not None:
                reset_observation_context(acq_token)
            _active_jobs.pop(job_id, None)


async def fetch_transcripts_with_segments(
    video_ids: list,
    progress_cb=None,
    allow_whisper: bool = True,
    per_source_timeout: Optional[float] = None,
    preflight_record: Optional[dict] = None,
    on_source_completed: Optional[Callable[[str, dict], Awaitable[None]]] = None,
):
    """
    Fetch transcripts for multiple videos truly concurrently.

    Bounded latency guarantees:
    * allow_whisper explicitly controls local audio recovery.
    * per_source_timeout: hard wall-clock cap per video.
    * on_source_completed: called as each source finishes so the caller
      can persist live progress (e.g. Transcripts ready: 1 / 3) immediately.
    """
    from ..services.transcript_service import get_transcript_service, extract_video_id
    import time as _time

    service = await get_transcript_service()

    async def _fetch_one(raw_id: str):
        video_id = extract_video_id(raw_id)
        t0 = _time.perf_counter()
        method = "youtube_api"
        res_tuple = None
        try:
            async def _do_fetch():
                nonlocal method
                result = await service.get_transcript(
                    video_id,
                    progress_cb=progress_cb,
                    allow_whisper=allow_whisper,
                )
                if result and result.get("transcript"):
                    method = result.get("source", "unknown")
                    segments = []
                    if isinstance(result["transcript"], list):
                        segments = result["transcript"]
                        text = " ".join(seg.get("text", "") for seg in segments)
                    else:
                        text = str(result["transcript"])

                    if text.strip():
                        print(f"[Merge] Got transcript for {video_id} via {method} ({len(text.split())} words, {len(segments)} segments)")
                        return (video_id, text, segments)
                return None

            if per_source_timeout:
                res_tuple = await asyncio.wait_for(_do_fetch(), timeout=per_source_timeout)
            else:
                res_tuple = await _do_fetch()
        except asyncio.TimeoutError:
            print(f"[WARN] Transcript fetch timed out after {per_source_timeout}s for {video_id}")
            method = "timeout"
        except Exception as e:
            print(f"[WARN] Could not fetch transcript for {video_id}: {e}")
            method = "error"

        t_elapsed = round(_time.perf_counter() - t0, 3)
        if preflight_record is not None:
            preflight_record[video_id] = {
                "video_id": video_id,
                "status": "cached_transcript" if "cache" in method else ("caption_ready" if res_tuple else "slow_recovery_required"),
                "ready": res_tuple is not None,
                "method": method,
                "time_seconds": t_elapsed,
                "error": None if res_tuple else ("Timeout" if method == "timeout" else "Fast transcript unavailable"),
            }

        if on_source_completed:
            try:
                await on_source_completed(video_id, preflight_record or {})
            except Exception as e:
                print(f"[Merge] on_source_completed callback error: {e}")

        return res_tuple

    results = await asyncio.gather(*[_fetch_one(raw_id) for raw_id in video_ids])

    text_map = {}
    segments_map = {}
    for r in results:
        if r is not None:
            vid, text, segs = r
            text_map[vid] = text
            segments_map[vid] = segs

    return text_map, segments_map
