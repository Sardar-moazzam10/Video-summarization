"""Versioned contracts at the selection/output boundary.

These models are intentionally independent from the legacy ``JobStatus``.
They let video and text outputs acquire separate lifecycles while old clients
continue to consume the existing aggregate status during the migration.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ComponentStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OutputComponentState(BaseModel):
    status: ComponentStatus = ComponentStatus.QUEUED
    stage: str = "queued"
    progress_percent: int = Field(default=0, ge=0, le=100)
    attempts: int = Field(default=0, ge=0)
    error: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class EvidenceIntent(BaseModel):
    summary_scope: Literal["overall", "keyword"] = "overall"
    source_scope: Literal["single", "multi"] = "single"
    keywords: List[str] = Field(default_factory=list)
    target_duration_minutes: int = Field(ge=1)
    style: str = "educational"
    content_type: Literal["explanatory", "narrative"] = "explanatory"


class EvidenceSource(BaseModel):
    video_id: str
    duration_seconds: Optional[float] = Field(default=None, ge=0)


class EvidenceSegment(BaseModel):
    segment_id: str
    order: int = Field(ge=0)
    video_id: str
    start_time: float = Field(ge=0)
    end_time: float = Field(gt=0)
    text: str
    concepts: List[str] = Field(default_factory=list)
    keyword_matches: List[str] = Field(default_factory=list)
    keyword_scores: Dict[str, float] = Field(default_factory=dict)
    importance: float = 0.0
    completeness: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_interval(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be greater than start_time")
        if not self.text.strip():
            raise ValueError("evidence text must not be empty")
        return self


class EvidenceManifest(BaseModel):
    manifest_version: int = Field(default=1, ge=1)
    job_id: str
    intent: EvidenceIntent
    sources: List[EvidenceSource]
    segments: List[EvidenceSegment]
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def validate_identity_and_order(self):
        source_ids = {source.video_id for source in self.sources}
        segment_ids = set()
        for expected_order, segment in enumerate(self.segments):
            if segment.order != expected_order:
                raise ValueError("evidence segment order must be contiguous")
            if segment.video_id not in source_ids:
                raise ValueError("evidence segment references an unknown source")
            if segment.segment_id in segment_ids:
                raise ValueError("evidence segment IDs must be unique")
            segment_ids.add(segment.segment_id)
        return self


class GroundedText(BaseModel):
    text: str
    evidence_ids: List[str] = Field(default_factory=list)


class GroundedTakeaway(GroundedText):
    keywords: List[str] = Field(default_factory=list)


class KeywordCoverage(BaseModel):
    keyword: str
    status: Literal["supported", "partial", "unsupported"]
    evidence_ids: List[str] = Field(default_factory=list)


class StructuredTextOutput(BaseModel):
    schema_version: int = 1
    mode: Literal[
        "overall_single", "overall_multi", "keyword_single", "keyword_multi"
    ]
    generation_mode: Literal["generated", "extractive_fallback"]
    summary: List[GroundedText] = Field(default_factory=list)
    tldr: GroundedText
    key_takeaways: List[GroundedTakeaway] = Field(default_factory=list)
    keyword_coverage: List[KeywordCoverage] = Field(default_factory=list)
    source_contributions: Dict[str, List[str]] = Field(default_factory=dict)
    validation: Dict[str, object] = Field(default_factory=dict)


def derive_output_status(video: OutputComponentState, text: OutputComponentState) -> str:
    """Derive a presentation state without coupling either worker lifecycle."""
    requested = [item for item in (video, text) if item.status != ComponentStatus.NOT_REQUESTED]
    if not requested:
        return "processing"
    ready = sum(item.status == ComponentStatus.READY for item in requested)
    terminal = all(
        item.status in {ComponentStatus.READY, ComponentStatus.FAILED, ComponentStatus.CANCELLED}
        for item in requested
    )
    if ready == len(requested):
        return "completed"
    if ready:
        return "partial_success" if terminal else "partial_ready"
    if terminal:
        return "failed"
    return "processing"
