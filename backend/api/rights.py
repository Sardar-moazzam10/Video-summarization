"""
Rights API Routes - Provenance tracking, attestations, permissions, and rights manifest
"""

from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.security import get_current_user
from ..core.database import get_database
from ..services.rights_service import (
    get_rights_record,
    record_user_attestation,
    record_permission,
    evaluate_publication_gate,
    build_source_reuse_report,
    ensure_source_rights_for_videos,
    build_job_rights_snapshot,
    manifest_from_snapshot,
)
from ..services.transcript_service import extract_video_id
from ..models.rights import (
    SourceRightsRecord,
    RightsBasis,
    PublicationGateStatus,
)

router = APIRouter(prefix="/api/v1/rights", tags=["rights"])


class AttestationRequest(BaseModel):
    source_id: str
    source_type: str = "youtube"
    claim_type: str = Field(..., pattern="^(ownership|fair_use|public_domain)$")
    notes: Optional[str] = None


class PermissionRequest(BaseModel):
    source_id: str
    source_type: str = "youtube"
    grantor: Optional[str] = None
    evidence_url: Optional[str] = None
    scope_adaptation: bool = False
    scope_publication: bool = False
    document_ref: Optional[str] = None


@router.get("/{video_id}")
async def get_source_rights(
    video_id: str,
    source_type: str = "youtube",
    current_user: dict = Depends(get_current_user),
):
    """Get stored rights record for a source belonging to current user."""
    user_id = current_user["sub"]
    canonical_id = extract_video_id(video_id) if source_type == "youtube" else video_id
    record = await get_rights_record(user_id, source_type, canonical_id)
    if not record:
        return {
            "source_id": canonical_id,
            "source_type": source_type,
            "rights_basis": RightsBasis.UNKNOWN.value,
            "recorded": False,
        }
    return record.model_dump()


@router.post("/attest")
async def attest_rights(
    request: AttestationRequest,
    current_user: dict = Depends(get_current_user),
):
    """Record an unverified user declaration (e.g. ownership, fair use)."""
    user_id = current_user["sub"]
    canonical_id = extract_video_id(request.source_id) if request.source_type == "youtube" else request.source_id
    record = await record_user_attestation(
        user_id=user_id,
        source_type=request.source_type,
        source_id=canonical_id,
        claim_type=request.claim_type,
        notes=request.notes,
    )
    return {"status": "recorded", "record": record.model_dump()}


@router.post("/permission")
async def record_source_permission(
    request: PermissionRequest,
    current_user: dict = Depends(get_current_user),
):
    """Record third-party permission evidence and grant scope."""
    user_id = current_user["sub"]
    canonical_id = extract_video_id(request.source_id) if request.source_type == "youtube" else request.source_id
    record = await record_permission(
        user_id=user_id,
        source_type=request.source_type,
        source_id=canonical_id,
        grantor=request.grantor,
        evidence_url=request.evidence_url,
        scope_adaptation=request.scope_adaptation,
        scope_publication=request.scope_publication,
        document_ref=request.document_ref,
    )
    return {"status": "recorded", "record": record.model_dump()}


@router.get("/job/{job_id}/manifest")
async def get_job_rights_manifest(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Generate complete Rights and Attribution Manifest for a job.
    Enforces strict ownership authorization:
      Denies access without leaking job existence to unauthorized users.
    Combines:
      - Source rights records (with coexisting platform & user evidence)
      - Objective Source Reuse Report (from highlight_segments + source_durations)
      - Source rights records (authoritatively resolved & persisted)
      - Objective Source Reuse Report (unioned physical clip intervals)
      - Publication gate evaluation & warnings
      - Composite attribution text block
    """
    db = await get_database()
    job_data = await db["jobs"].find_one({"job_id": job_id})
    if not job_data:
        raise HTTPException(404, "Job not found")

    user_id = current_user["sub"]
    # Verify ownership unless admin — deny without leaking existence
    if current_user.get("role") != "admin" and job_data.get("user_id") != user_id:
        raise HTTPException(404, "Job not found")

    job_owner_id = job_data.get("user_id", user_id)
    highlight_segments = job_data.get("highlight_segments", [])
    source_durations = job_data.get("source_durations", {})
    reuse_report = build_source_reuse_report(highlight_segments, source_durations)

    snapshot = job_data.get("rights_snapshot")
    if not snapshot:
        # Legacy reconstruction is inspection-only. It is deliberately not
        # persisted and can never authorize media delivery.
        source_records = await ensure_source_rights_for_videos(
            user_id=job_owner_id,
            video_ids=job_data.get("used_video_ids") or job_data.get("video_ids", []),
            db=db,
        )
        snapshot = build_job_rights_snapshot(source_records)
        snapshot["snapshot_origin"] = "reconstructed_legacy"
        snapshot["aggregate"]["warnings"] = [
            "Legacy manifest reconstructed from current records; it is not historical job evidence.",
            *snapshot["aggregate"].get("warnings", []),
        ]

    manifest = manifest_from_snapshot(snapshot, reuse_report)
    return {"job_id": job_id, **manifest}

