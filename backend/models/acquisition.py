"""Acquisition Compliance V1A shadow-observability domain models.

These records describe acquisition policy observations and execution facts.
They are deliberately independent from Rights V1 and have no authorization
effect while ``evaluation_mode`` is ``shadow``.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AcquisitionMode(str, Enum):
    NO_LOCAL_ACQUISITION = "no_local_acquisition"
    LOCAL_ACQUISITION = "local_acquisition"


class AcquisitionBasis(str, Enum):
    DOCUMENTED_PLATFORM_API = "documented_platform_api"
    USER_PROVIDED_SOURCE = "user_provided_source"
    OWNER_PROVIDED_SOURCE = "owner_provided_source"
    AUTHORIZED_DIRECT_SOURCE = "authorized_direct_source"
    ORGANIZATION_LICENSED_SOURCE = "organization_licensed_source"
    WRITTEN_PLATFORM_APPROVAL = "written_platform_approval"
    LEGACY_UNVERIFIED = "legacy_unverified"
    UNKNOWN = "unknown"


class AcquisitionDecisionStatus(str, Enum):
    ALLOWED_WITH_LIMITS = "allowed_with_limits"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    RESTRICTED_BY_PRODUCT_POLICY = "restricted_by_product_policy"
    SHADOW_ONLY = "shadow_only"


class AcquisitionOperation(str, Enum):
    METADATA_READ = "metadata_read"
    CAPTION_READ = "caption_read"
    TRANSCRIPT_PROCESS = "transcript_process"
    AUDIO_DOWNLOAD = "audio_download"
    VIDEO_DOWNLOAD = "video_download"
    TEMPORARY_MEDIA_PROCESS = "temporary_media_process"
    PERSISTENT_CACHE_WRITE = "persistent_cache_write"
    CACHE_REUSE = "cache_reuse"
    CROSS_USER_REUSE = "cross_user_reuse"
    KEYFRAME_GENERATE = "keyframe_generate"
    DERIVED_MEDIA_GENERATE = "derived_media_generate"
    DERIVED_MEDIA_DELIVER = "derived_media_deliver"


class AcquisitionEvidence(BaseModel):
    evidence_id: str
    evidence_type: str
    issuer_ref: Optional[str] = None
    scope: List[str] = Field(default_factory=list)
    reference: Optional[str] = None
    digest: Optional[str] = None
    asserted_at: datetime = Field(default_factory=utc_now)
    verification: Literal["asserted", "verified", "rejected"] = "asserted"


class SourceRef(BaseModel):
    source_type: str
    source_id: str
    canonical_reference: str


class AcquisitionDecision(BaseModel):
    decision_id: str
    schema_version: str = "1.0"
    policy_version: str = "acquisition-v1a-shadow"
    evaluation_mode: Literal["shadow"] = "shadow"
    authorization_effect: Literal["none"] = "none"
    job_id: str
    user_id: str
    organization_id: Optional[str] = None
    source_ref: SourceRef
    mode: AcquisitionMode
    basis: AcquisitionBasis
    status: AcquisitionDecisionStatus = AcquisitionDecisionStatus.SHADOW_ONLY
    evidence: List[AcquisitionEvidence] = Field(default_factory=list)
    permitted_operations: List[AcquisitionOperation] = Field(default_factory=list)
    cache_scope: Literal["none", "job", "user", "organization", "shared"] = "job"
    retention_class: str = "legacy_current_behavior_observed"
    evaluated_at: datetime = Field(default_factory=utc_now)
    evaluator: str = "acquisition-v1a-shadow-evaluator"
    decision_hash: str = ""
    event_sequence: int = 0


class AcquisitionEvent(BaseModel):
    event_id: str
    sequence: int
    occurred_at: datetime = Field(default_factory=utc_now)
    evaluation_mode: Literal["shadow"] = "shadow"
    decision_id: str
    job_id: str
    user_id: str
    source_id: str
    operation: AcquisitionOperation
    phase: Literal["requested", "attempted", "succeeded", "failed", "skipped", "blocked"]
    method: str
    provider: Optional[str] = None
    outcome_code: str
    cache_result: Literal["not_applicable", "hit", "miss"] = "not_applicable"
    storage_class: Literal[
        "none", "memory", "temporary", "job", "user", "organization", "shared"
    ] = "none"
    artifact_ref: Optional[str] = None
    fallback_from_event_id: Optional[str] = None
    reason_code: Optional[str] = None
    safe_details: Dict[str, str] = Field(default_factory=dict)
    previous_event_hash: Optional[str] = None
    event_hash: str = ""


class AcquisitionArtifact(BaseModel):
    artifact_ref: str
    source_id: str
    storage_class: str
    operation: str


class AcquisitionViolation(BaseModel):
    event_id: str
    operation: str
    reason: str


class FinalAcquisitionManifest(BaseModel):
    manifest_id: str
    schema_version: str = "1.0"
    policy_version: str = "acquisition-v1a-shadow"
    evaluation_mode: Literal["shadow"] = "shadow"
    authorization_effect: Literal["none"] = "none"
    job_id: str
    decision_ids: List[str]
    decision_hashes: List[str]
    event_sequence_end: Dict[str, int]
    event_chain_hashes: Dict[str, Optional[str]]
    permitted_operations: List[str]
    attempted_operations: List[str]
    successful_operations: List[str]
    selected_methods: List[str]
    fallback_chain: List[str]
    artifacts: List[AcquisitionArtifact]
    violations: List[AcquisitionViolation]
    retention_classes: List[str]
    cache_scopes: List[str]
    final_gate: Literal["shadow_not_authoritative"] = "shadow_not_authoritative"
    finalized_at: datetime = Field(default_factory=utc_now)
    finalization_reason: Literal["job_completed", "job_failed", "job_cancelled"]
    manifest_hash: str = ""

