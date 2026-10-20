"""
Rights Models - Source Provenance, Attestation, and Rights Metadata
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class RightsBasis(str, Enum):
    USER_OWNED = "user_owned"
    CC_BY = "cc_by"
    PERMISSION_GRANTED = "permission_granted"
    PUBLIC_DOMAIN = "public_domain"
    COPYRIGHT_EXCEPTION = "copyright_exception_review"
    UNKNOWN = "unknown"


class PublicationGateStatus(str, Enum):
    ELIGIBLE_BY_RECORDED_RIGHTS = "eligible_by_recorded_rights"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    RESTRICTED_BY_PRODUCT_POLICY = "restricted_by_product_policy"


class PlatformEvidence(BaseModel):
    """Platform-verified metadata from official API."""
    source_platform: str = "youtube"
    status_license: Optional[str] = None  # e.g., "creativeCommon", "youtube"
    verified_at: datetime = Field(default_factory=datetime.utcnow)
    verified: bool = False


class UserClaim(BaseModel):
    """Explicit declaration made by the user."""
    claim_type: str  # "ownership", "public_domain", "fair_use"
    user_id: str
    attested_at: datetime = Field(default_factory=datetime.utcnow)
    notes: Optional[str] = None


class PermissionEvidence(BaseModel):
    """External license or direct permission from copyright holder."""
    grantor: Optional[str] = None
    evidence_url: Optional[str] = None
    scope_adaptation: bool = False
    scope_publication: bool = False
    recorded_at: datetime = Field(default_factory=datetime.utcnow)
    document_ref: Optional[str] = None


class SourceRightsRecord(BaseModel):
    record_id: str
    user_id: str
    source_type: str = "youtube"  # "youtube", future: "upload", "vimeo"
    source_id: str  # e.g., YouTube video ID
    source_url: str

    owner_or_creator: Optional[str] = None
    source_title: Optional[str] = None

    rights_basis: RightsBasis = RightsBasis.UNKNOWN
    license_identifier: Optional[str] = None  # e.g. "CC BY (YouTube)", "YouTube Standard"
    license_version: Optional[str] = None  # None unless independently verified

    attribution_required: bool = False
    attribution_text: Optional[str] = None

    # Coexisting evidence layers:
    platform_evidence: Optional[PlatformEvidence] = None
    user_claim: Optional[UserClaim] = None
    permission_evidence: Optional[PermissionEvidence] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True

