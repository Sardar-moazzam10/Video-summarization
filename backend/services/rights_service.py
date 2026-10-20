"""
Rights Service - Source Provenance, Rights Normalization, Attribution & Publication Gating

Core Invariants:
1. Never makes legal conclusions or claims content is "copyright safe".
2. Distinguishes verified platform metadata from user declarations.
3. Decoupled from video processing, transcripts, and content summarization.
4. Evaluates publication gating for public distribution without restricting private study summaries.
3. Server is authoritative for platform verification; client badges are not trusted blindly.
4. Uses canonical 11-character YouTube video IDs across all storage and calculations.
5. Reuses unioned source intervals to calculate physical usage without counting duplicated cuts twice.
6. Evaluates publication gating for public distribution without restricting private study summaries.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from .acquisition_service import append_event
import uuid
import httpx

from ..models.rights import (
    RightsBasis,
    PublicationGateStatus,
    PlatformEvidence,
    UserClaim,
    PermissionEvidence,
    SourceRightsRecord,
)
from ..core.database import get_database
from ..core.config import get_settings
from .transcript_service import extract_video_id


RIGHTS_SNAPSHOT_SCHEMA_VERSION = "1.0"
RIGHTS_POLICY_VERSION = "rights-v1-fail-closed"


def normalize_youtube_license(api_license_str: Optional[str]) -> RightsBasis:
    """
    Map YouTube API status.license value to internal RightsBasis.
    
    YouTube Data API status.license returns:
      - "creativeCommon" -> mapped to RightsBasis.CC_BY
      - "youtube" -> Standard YouTube License (no redistribution grant, mapped to UNKNOWN)
    """
    if not api_license_str:
        return RightsBasis.UNKNOWN
    
    clean = api_license_str.strip()
    if clean == "creativeCommon":
        return RightsBasis.CC_BY
    return RightsBasis.UNKNOWN


def generate_attribution_text(
    title: Optional[str],
    channel: Optional[str],
    video_id: str,
    basis: RightsBasis,
) -> Optional[str]:
    """
    Generate required attribution line when rights basis mandates it.
    Complies with Point 11:
      "<title>" by <channel> — <url> — licensed under CC BY on YouTube.
    """
    canonical_id = extract_video_id(video_id)
    t = (title or "").strip() or f"Video {canonical_id}"
    c = (channel or "").strip() or "creator"
    url = f"https://www.youtube.com/watch?v={canonical_id}"
    
    if basis == RightsBasis.CC_BY:
        return f'"{t}" by {c} — {url} — licensed under CC BY on YouTube.'
    elif basis == RightsBasis.PERMISSION_GRANTED:
        return f'"{t}" by {c} — {url} (used with permission)'
    return f'"{t}" by {c} — {url}'


def union_intervals(intervals: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """
    Merge overlapping or contiguous time intervals [start, end].
    Ensures physical source duration is measured without double-counting duplicated cuts.
    """
    if not intervals:
        return []
    # Normalize valid intervals where end >= start
    valid = [(float(s), float(e)) for s, e in intervals if float(e) >= float(s)]
    if not valid:
        return []
    
    sorted_intervals = sorted(valid, key=lambda x: x[0])
    merged = [sorted_intervals[0]]
    
    for current_start, current_end in sorted_intervals[1:]:
        last_start, last_end = merged[-1]
        if current_start <= last_end:
            merged[-1] = (last_start, max(last_end, current_end))
        else:
            merged.append((current_start, current_end))
            
    return merged


def evaluate_source_gate(source: SourceRightsRecord) -> Tuple[PublicationGateStatus, List[str]]:
    """
    Evaluate publication gate for a single source according to the V1 Truth Table.
    Returns: (PublicationGateStatus, List of warning strings)
    """
    warnings: List[str] = []
    
    # 1. Verified YouTube CC BY
    if (
        source.platform_evidence
        and source.platform_evidence.verified
        and source.platform_evidence.status_license == "creativeCommon"
    ):
        warnings.append(
            "Recorded CC BY metadata reflects platform status; it is not a guarantee concerning embedded third-party material or future platform claims."
        )
        if source.attribution_required and not source.attribution_text:
            warnings.append("Attribution statement required for CC BY publication.")
        return PublicationGateStatus.ELIGIBLE_BY_RECORDED_RIGHTS, warnings

    # 2. Permission with recorded adaptation and publication scope
    if (
        source.permission_evidence
        and source.permission_evidence.scope_adaptation
        and source.permission_evidence.scope_publication
    ):
        return PublicationGateStatus.ELIGIBLE_BY_RECORDED_RIGHTS, warnings

    # 3. User claims (ownership, fair use, public domain) on external URLs are unverified declarations
    if source.user_claim:
        if source.user_claim.claim_type == "ownership":
            warnings.append(f"User ownership declaration for source {source.source_id} requires manual review.")
        elif source.user_claim.claim_type == "fair_use":
            warnings.append(f"Copyright exception / fair use claim for source {source.source_id} requires manual review.")
        elif source.user_claim.claim_type == "public_domain":
            warnings.append(f"Public domain declaration for source {source.source_id} requires manual review.")
        else:
            warnings.append(f"User declaration ({source.user_claim.claim_type}) requires review.")
        return PublicationGateStatus.MANUAL_REVIEW_REQUIRED, warnings

    # 4. Incomplete permission evidence
    if source.permission_evidence:
        warnings.append(
            f"Permission recorded for source {source.source_id} does not explicitly grant both adaptation and publication."
        )
        return PublicationGateStatus.MANUAL_REVIEW_REQUIRED, warnings

    # 5. Verified Standard YouTube License with no additional permission
    if (
        source.platform_evidence
        and source.platform_evidence.verified
        and source.platform_evidence.status_license == "youtube"
    ):
        warnings.append(
            f"Source {source.source_id} is under Standard YouTube License; redistribution is restricted by product policy."
        )
        return PublicationGateStatus.RESTRICTED_BY_PRODUCT_POLICY, warnings

    # 6. Default closed: Unknown or unrecorded rights
    warnings.append(f"Source {source.source_id} has unresolved rights metadata.")
    return PublicationGateStatus.RESTRICTED_BY_PRODUCT_POLICY, warnings


def evaluate_publication_gate(
    sources: List[SourceRightsRecord],
) -> Tuple[PublicationGateStatus, List[str]]:
    """
    Evaluate overall publication gate for a multi-source job.
    Invariance: Most restrictive source gate wins.
    """
    if not sources:
        return (
            PublicationGateStatus.RESTRICTED_BY_PRODUCT_POLICY,
            ["No sources provided for publication gate evaluation."],
        )

    all_warnings: List[str] = []
    statuses: List[PublicationGateStatus] = []

    for src in sources:
        status, src_warnings = evaluate_source_gate(src)
        statuses.append(status)
        all_warnings.extend(src_warnings)

    if PublicationGateStatus.RESTRICTED_BY_PRODUCT_POLICY in statuses:
        overall = PublicationGateStatus.RESTRICTED_BY_PRODUCT_POLICY
    elif PublicationGateStatus.MANUAL_REVIEW_REQUIRED in statuses:
        overall = PublicationGateStatus.MANUAL_REVIEW_REQUIRED
    else:
        overall = PublicationGateStatus.ELIGIBLE_BY_RECORDED_RIGHTS

    deduped_warnings = list(dict.fromkeys(w.strip() for w in all_warnings if isinstance(w, str) and w.strip()))
    return overall, deduped_warnings


def _verification_status(source: SourceRightsRecord) -> str:
    """Describe evidence provenance without conflating declarations with metadata."""
    if source.platform_evidence and source.platform_evidence.verified:
        return "verified_metadata"
    if source.permission_evidence:
        return "permission_recorded"
    if source.user_claim:
        return "user_attested"
    return "unverified"


def build_job_rights_snapshot(
    sources: List[SourceRightsRecord],
    *,
    evaluated_at: Optional[datetime] = None,
) -> Dict:
    """Build the complete, serializable evidence snapshot for one job."""
    source_snapshots: List[Dict] = []
    for source in sources:
        gate_status, warnings = evaluate_source_gate(source)
        source_snapshots.append({
            "source_id": source.source_id,
            "provider": source.source_type,
            "source_url": source.source_url,
            "license": {
                "identifier": source.license_identifier,
                "version": source.license_version,
            },
            "rights_basis": (
                source.rights_basis.value
                if hasattr(source.rights_basis, "value")
                else source.rights_basis
            ),
            "verification_status": _verification_status(source),
            "evidence": {
                "platform": (
                    source.platform_evidence.model_dump(mode="json")
                    if source.platform_evidence else None
                ),
                "user_claim": (
                    source.user_claim.model_dump(mode="json")
                    if source.user_claim else None
                ),
                "permission": (
                    source.permission_evidence.model_dump(mode="json")
                    if source.permission_evidence else None
                ),
            },
            "creator": source.owner_or_creator,
            "title": source.source_title,
            "attribution": {
                "required": source.attribution_required,
                "text": source.attribution_text,
            },
            "publication_gate_status": gate_status.value,
            "warnings": list(warnings),
        })

    aggregate_status, aggregate_warnings = evaluate_publication_gate(sources)
    evaluated = evaluated_at or datetime.now(timezone.utc)
    return {
        "schema_version": RIGHTS_SNAPSHOT_SCHEMA_VERSION,
        "policy_version": RIGHTS_POLICY_VERSION,
        "evaluated_at": evaluated.isoformat(),
        "snapshot_origin": "job_evaluation",
        "sources": source_snapshots,
        "aggregate": {
            "publication_gate_status": aggregate_status.value,
            "warnings": list(aggregate_warnings),
            "source_count": len(source_snapshots),
        },
    }


async def freeze_job_rights_snapshot(
    *,
    jobs_collection,
    job_id: str,
    user_id: str,
    video_ids: List[str],
    db=None,
) -> Dict:
    """Resolve and atomically persist a job's rights snapshot once."""
    existing_job = await jobs_collection.find_one({"job_id": job_id})
    if existing_job and existing_job.get("rights_snapshot"):
        return existing_job["rights_snapshot"]

    records = await ensure_source_rights_for_videos(
        user_id=user_id,
        video_ids=video_ids,
        db=db,
    )
    snapshot = build_job_rights_snapshot(records)
    aggregate = snapshot["aggregate"]
    result = await jobs_collection.update_one(
        {
            "job_id": job_id,
            "$or": [
                {"rights_snapshot": {"$exists": False}},
                {"rights_snapshot": None},
            ],
        },
        {"$set": {
            "rights_snapshot": snapshot,
            "publication_gate_status": aggregate["publication_gate_status"],
            "rights_summary": {
                "gate_status": aggregate["publication_gate_status"],
                "warnings": aggregate["warnings"],
                "source_count": aggregate["source_count"],
            },
        }},
    )
    if getattr(result, "matched_count", 1) == 0:
        winner = await jobs_collection.find_one({"job_id": job_id})
        if winner and winner.get("rights_snapshot"):
            return winner["rights_snapshot"]
    return snapshot


def manifest_from_snapshot(snapshot: Dict, source_reuse_report: Optional[Dict] = None) -> Dict:
    """Render the public manifest shape from frozen job evidence only."""
    aggregate = snapshot.get("aggregate") or {}
    sources = snapshot.get("sources") or []
    attribution_lines = [
        (source.get("attribution") or {}).get("text")
        for source in sources
        if (source.get("attribution") or {}).get("text")
    ]
    return {
        "snapshot_origin": snapshot.get("snapshot_origin", "job_evaluation"),
        "schema_version": snapshot.get("schema_version"),
        "policy_version": snapshot.get("policy_version"),
        "evaluated_at": snapshot.get("evaluated_at"),
        "publication_gate_status": aggregate.get(
            "publication_gate_status",
            PublicationGateStatus.RESTRICTED_BY_PRODUCT_POLICY.value,
        ),
        "gate_warnings": aggregate.get("warnings", []),
        "sources": sources,
        "source_reuse_report": source_reuse_report,
        "attribution_required": bool(attribution_lines),
        "attribution_block": "\n".join(attribution_lines) if attribution_lines else None,
    }


def build_source_reuse_report(
    highlight_segments: List[Dict],
    source_durations: Dict[str, float],
) -> Dict:
    """
    Compute objective source usage metrics from ClipManifest and persisted source durations.
    Does NOT calculate subjective copyright risk scores or clearance percentages.
    Uses unioned physical source intervals so overlapping cuts are not counted twice.
    """
    per_source: Dict[str, Dict] = {}
    total_output = 0.0
    per_source_raw_intervals: Dict[str, List[Tuple[float, float]]] = {}
    per_source_clip_counts: Dict[str, int] = {}
    per_source_max_interval: Dict[str, float] = {}

    # Aggregate clips per source
    # Normalize canonical IDs in source_durations
    norm_source_durations = {
        extract_video_id(k): float(v) for k, v in source_durations.items()
    }

    # Group segments by canonical video ID
    for seg in highlight_segments:
        vid = seg.get("video_id") or "unknown"
        raw_vid = seg.get("video_id") or "unknown"
        vid = extract_video_id(raw_vid)
        start = float(seg.get("start_time", 0.0))
        end = float(seg.get("end_time", 0.0))
        clip_dur = max(0.0, end - start)
        total_output += clip_dur
        dur = max(0.0, end - start)

        if vid not in per_source:
            s_dur = float(source_durations.get(vid, 0.0))
            per_source[vid] = {
                "video_id": vid,
                "source_media_seconds": round(s_dur, 1),
                "used_seconds": 0.0,
                "clip_count": 0,
                "max_continuous_interval_seconds": 0.0,
                "usage_ratio": 0.0,
            }
        if vid not in per_source_raw_intervals:
            per_source_raw_intervals[vid] = []
            per_source_clip_counts[vid] = 0
            per_source_max_interval[vid] = 0.0

        per_source[vid]["used_seconds"] += clip_dur
        per_source[vid]["clip_count"] += 1
        if clip_dur > per_source[vid]["max_continuous_interval_seconds"]:
            per_source[vid]["max_continuous_interval_seconds"] = clip_dur
        per_source_raw_intervals[vid].append((start, end))
        per_source_clip_counts[vid] += 1
        if dur > per_source_max_interval[vid]:
            per_source_max_interval[vid] = dur

    # Finalize ratios
    for vid, stat in per_source.items():
        stat["used_seconds"] = round(stat["used_seconds"], 1)
        stat["max_continuous_interval_seconds"] = round(stat["max_continuous_interval_seconds"], 1)
        src_total = stat["source_media_seconds"]
        if src_total > 0:
            stat["usage_ratio"] = round(min(1.0, stat["used_seconds"] / src_total), 4)
        else:
            stat["usage_ratio"] = 0.0
    per_source: Dict[str, Dict] = {}
    total_output = 0.0

    for vid, raw_intervals in per_source_raw_intervals.items():
        unioned = union_intervals(raw_intervals)
        used_sec = sum(e - s for s, e in unioned)
        total_output += used_sec

        src_total = float(norm_source_durations.get(vid, 0.0))
        ratio = round(min(1.0, used_sec / src_total), 4) if src_total > 0 else 0.0

        per_source[vid] = {
            "video_id": vid,
            "source_media_seconds": round(src_total, 1),
            "used_seconds": round(used_sec, 1),
            "clip_count": per_source_clip_counts[vid],
            "max_continuous_interval_seconds": round(per_source_max_interval[vid], 1),
            "usage_ratio": ratio,
        }

    return {
        "total_output_seconds": round(total_output, 1),
        "source_count": len(per_source),
        "sources": per_source,
    }


# =====================================================
# PERSISTENCE HELPERS
# PERSISTENCE & AUTHORITATIVE SERVER-SIDE ENRICHMENT
# =====================================================

async def get_source_rights_collection(db=None):
    if db is None:
        db = await get_database()
    return db["source_rights"]


async def ensure_rights_indexes(db=None):
    """Ensure compound index on (user_id, source_type, source_id)."""
    """Ensure compound unique index on (user_id, source_type, source_id)."""
    coll = await get_source_rights_collection(db)
    await coll.create_index(
        [("user_id", 1), ("source_type", 1), ("source_id", 1)],
        unique=True,
    )


async def get_rights_record(
    user_id: str,
    source_type: str,
    source_id: str,
    db=None,
) -> Optional[SourceRightsRecord]:
    canonical_id = extract_video_id(source_id) if source_type == "youtube" else source_id
    coll = await get_source_rights_collection(db)
    doc = await coll.find_one({
        "user_id": user_id,
        "source_type": source_type,
        "source_id": source_id,
        "source_id": canonical_id,
    })
    if not doc:
        return None
    doc.pop("_id", None)
    return SourceRightsRecord(**doc)


async def upsert_rights_record(record: SourceRightsRecord, db=None) -> None:
    coll = await get_source_rights_collection(db)
    record.updated_at = datetime.utcnow()
    data = record.model_dump()
    await coll.update_one(
        {
            "user_id": record.user_id,
            "source_type": record.source_type,
            "source_id": record.source_id,
        },
        {"$set": data},
        upsert=True,
    )


async def create_or_update_platform_metadata(
    user_id: str,
    video_id: str,
    status_license: Optional[str],
    source_title: Optional[str] = None,
    channel: Optional[str] = None,
    db=None,
) -> SourceRightsRecord:
    """Record verified platform metadata from YouTube API."""
    existing = await get_rights_record(user_id, "youtube", video_id, db=db)
    canonical_id = extract_video_id(video_id)
    existing = await get_rights_record(user_id, "youtube", canonical_id, db=db)
    basis = normalize_youtube_license(status_license)
    lic_ident = "CC BY (YouTube)" if basis == RightsBasis.CC_BY else "YouTube Standard"
    attr_req = (basis == RightsBasis.CC_BY)
    attr_text = generate_attribution_text(source_title, channel, video_id, basis) if attr_req else None
    attr_text = generate_attribution_text(source_title, channel, canonical_id, basis) if attr_req else None

    if existing:
        existing.source_title = source_title or existing.source_title
        existing.owner_or_creator = channel or existing.owner_or_creator
        existing.platform_evidence = PlatformEvidence(
            source_platform="youtube",
            status_license=status_license,
            verified=True,
            verified_at=datetime.utcnow(),
        )
        # Only update rights basis if user hasn't recorded explicit permission
        if not existing.permission_evidence or not existing.permission_evidence.scope_adaptation:
            existing.rights_basis = basis
            existing.license_identifier = lic_ident
            existing.attribution_required = attr_req
            existing.attribution_text = attr_text
        await upsert_rights_record(existing, db=db)
        return existing

    record = SourceRightsRecord(
        record_id=str(uuid.uuid4()),
        user_id=user_id,
        source_type="youtube",
        source_id=canonical_id,
        source_url=f"https://www.youtube.com/watch?v={canonical_id}",
        owner_or_creator=channel,
        source_title=source_title,
        rights_basis=basis,
        license_identifier=lic_ident,
        license_version=None,
        attribution_required=attr_req,
        attribution_text=attr_text,
        platform_evidence=PlatformEvidence(
            source_platform="youtube",
            status_license=status_license,
            verified=True,
            verified_at=datetime.utcnow(),
        ),
    )
    await upsert_rights_record(record, db=db)
    return record


async def ensure_source_rights_for_videos(
    user_id: str,
    video_ids: List[str],
    db=None,
) -> List[SourceRightsRecord]:
    """
    Authoritative server-side rights lookup and persistence for selected video IDs.
    
    Invariance:
    - Normalizes raw URLs and bare IDs to canonical 11-char IDs.
    - If a verified record already exists in MongoDB, reuses it.
    - If not, queries YouTube Data API directly on the server to verify status.license
      and persists the verified platform record.
    - CC BY sources selected during search NEVER silently degrade to UNKNOWN.
    """
    canonical_ids = [extract_video_id(vid) for vid in video_ids if vid]
    records: List[SourceRightsRecord] = []
    missing_ids: List[str] = []

    for cid in canonical_ids:
        rec = await get_rights_record(user_id, "youtube", cid, db=db)
        if rec and rec.platform_evidence and rec.platform_evidence.verified:
            records.append(rec)
        else:
            missing_ids.append(cid)

    # Server-side authoritative fetch for missing IDs
    if missing_ids:
        api_key = get_settings().REACT_APP_YOUTUBE_API_KEY.strip()
        status_map = {}
        snippet_map = {}

        if api_key:
            try:
                for mid in missing_ids:
                    await append_event(
                        source_id=mid,
                        operation="metadata_read",
                        phase="attempted",
                        method="youtube_api_videos_list",
                        outcome_code="started"
                    )
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/videos",
                        params={
                            "part": "status,snippet",
                            "id": ",".join(missing_ids),
                            "key": api_key,
                        },
                    )
                for mid in missing_ids:
                    await append_event(
                        source_id=mid,
                        operation="metadata_read",
                        phase="succeeded" if not resp.is_error else "failed",
                        method="youtube_api_videos_list",
                        outcome_code="success" if not resp.is_error else "error"
                    )
                    if not resp.is_error:
                        for v_item in resp.json().get("items", []):
                            raw_id = v_item.get("id")
                            vid_str = raw_id if isinstance(raw_id, str) else (raw_id.get("videoId") if isinstance(raw_id, dict) else None)
                            if vid_str:
                                status_map[vid_str] = v_item.get("status", {}).get("license")
                                snippet = v_item.get("snippet", {})
                                snippet_map[vid_str] = {
                                    "title": snippet.get("title"),
                                    "channel": snippet.get("channelTitle"),
                                }
            except Exception as e:
                print(f"[Rights] Server-side rights fetch warning: {e}")

        for cid in missing_ids:
            if cid in status_map:
                lic = status_map[cid]
                snip = snippet_map.get(cid, {})
                rec = await create_or_update_platform_metadata(
                    user_id=user_id,
                    video_id=cid,
                    status_license=lic,
                    source_title=snip.get("title"),
                    channel=snip.get("channel"),
                    db=db,
                )
            else:
                # Fallback to existing unverified record or ephemeral unrecorded record
                rec = await get_rights_record(user_id, "youtube", cid, db=db)
                if not rec:
                    rec = SourceRightsRecord(
                        record_id=f"ephemeral-{cid}",
                        user_id=user_id,
                        source_type="youtube",
                        source_id=cid,
                        source_url=f"https://www.youtube.com/watch?v={cid}",
                        rights_basis=RightsBasis.UNKNOWN,
                    )
            records.append(rec)

    return records


async def record_user_attestation(
    user_id: str,
    source_type: str,
    source_id: str,
    claim_type: str,
    notes: Optional[str] = None,
    db=None,
) -> SourceRightsRecord:
    """Record an unverified user declaration (e.g. ownership, fair use)."""
    existing = await get_rights_record(user_id, source_type, source_id, db=db)
    canonical_id = extract_video_id(source_id) if source_type == "youtube" else source_id
    existing = await get_rights_record(user_id, source_type, canonical_id, db=db)
    claim = UserClaim(claim_type=claim_type, user_id=user_id, notes=notes)

    if existing:
        existing.user_claim = claim
        if claim_type == "ownership":
            existing.rights_basis = RightsBasis.USER_OWNED
        elif claim_type == "public_domain":
            existing.rights_basis = RightsBasis.PUBLIC_DOMAIN
        elif claim_type == "fair_use":
            existing.rights_basis = RightsBasis.COPYRIGHT_EXCEPTION
        await upsert_rights_record(existing, db=db)
        return existing

    basis_map = {
        "ownership": RightsBasis.USER_OWNED,
        "public_domain": RightsBasis.PUBLIC_DOMAIN,
        "fair_use": RightsBasis.COPYRIGHT_EXCEPTION,
    }
    record = SourceRightsRecord(
        record_id=str(uuid.uuid4()),
        user_id=user_id,
        source_type=source_type,
        source_id=canonical_id,
        source_url=f"https://www.youtube.com/watch?v={canonical_id}" if source_type == "youtube" else canonical_id,
        rights_basis=basis_map.get(claim_type, RightsBasis.UNKNOWN),
        user_claim=claim,
    )
    await upsert_rights_record(record, db=db)
    return record


async def record_permission(
    user_id: str,
    source_type: str,
    source_id: str,
    grantor: Optional[str],
    evidence_url: Optional[str],
    scope_adaptation: bool,
    scope_publication: bool,
    document_ref: Optional[str] = None,
    db=None,
) -> SourceRightsRecord:
    """Record direct copyright permission document and scope."""
    canonical_id = extract_video_id(source_id) if source_type == "youtube" else source_id
    existing = await get_rights_record(user_id, source_type, canonical_id, db=db)
    perm = PermissionEvidence(
        grantor=grantor,
        evidence_url=evidence_url,
        scope_adaptation=scope_adaptation,
        scope_publication=scope_publication,
        document_ref=document_ref,
    )

    if existing:
        existing.permission_evidence = perm
        if scope_adaptation and scope_publication:
            existing.rights_basis = RightsBasis.PERMISSION_GRANTED
            existing.license_identifier = f"Permission granted by {grantor or 'copyright holder'}"
        await upsert_rights_record(existing, db=db)
        return existing

    record = SourceRightsRecord(
        record_id=str(uuid.uuid4()),
        user_id=user_id,
        source_type=source_type,
        source_id=canonical_id,
        source_url=f"https://www.youtube.com/watch?v={canonical_id}" if source_type == "youtube" else canonical_id,
        rights_basis=RightsBasis.PERMISSION_GRANTED if (scope_adaptation and scope_publication) else RightsBasis.UNKNOWN,
        license_identifier=f"Permission granted by {grantor or 'copyright holder'}" if (scope_adaptation and scope_publication) else None,
        permission_evidence=perm,
    )
    await upsert_rights_record(record, db=db)
    return record

