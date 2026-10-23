"""
Job Models - Merge job persistence and tracking

Features:
- Full job lifecycle tracking
- Progress and stage monitoring
- Fusion metadata storage
- Error handling
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Literal
from datetime import datetime
from enum import Enum
import uuid

from .output_contracts import OutputComponentState


class JobStatus(str, Enum):
    """Job processing stages"""
    PENDING = "pending"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    FUSING = "fusing"
    SUMMARIZING = "summarizing"
    ENRICHING = "enriching"
    GENERATING_VOICE = "generating_voice"
    GENERATING_VIDEO = "generating_video"
    # Video-first checkpoint: the highlight reel has been generated and
    # persisted (video_path set), and the job is now continuing on to BART
    # summarization/enrichment in the background. Distinct from
    # PARTIAL_SUCCESS, which is a terminal state — VIDEO_READY is not
    # terminal, the job always moves on from here to COMPLETED or
    # PARTIAL_SUCCESS.
    VIDEO_READY = "video_ready"
    COMPLETED = "completed"
    PARTIAL_SUCCESS = "partial_success"
    ERROR = "error"
    CANCELLED = "cancelled"


class DurationStyle(str, Enum):
    """Summary style based on duration"""
    HEADLINE = "headline"       # 5 min - Key points only
    BRIEF = "brief"             # 10 min - Main ideas + context
    STANDARD = "standard"       # 15 min - Full coverage + examples
    COMPREHENSIVE = "comprehensive"  # 20 min - Deep dive


class ConflictInfo(BaseModel):
    """Information about detected conflicts between sources"""
    topic: str
    positions: Dict[str, str]  # video_id -> position/statement
    resolution: str  # How it was handled


class FusionMetadata(BaseModel):
    """Metadata about the fusion process"""
    total_source_words: int = 0
    output_words: int = 0
    compression_ratio: float = 0.0
    topics_found: List[str] = []
    clusters_created: int = 0
    dedup_ratio: float = 0.0
    conflicts_detected: List[ConflictInfo] = []
    processing_time_seconds: float = 0.0
    video_count: int = 0


class HighlightSegment(BaseModel):
    """A segment identified by Gemini AI as a highlight"""
    video_id: str
    start_time: float
    end_time: float
    reason: str = ""
    importance_score: float = 0.0


class VideoSegment(BaseModel):
    """Selected video segment for merging"""
    video_id: str
    title: Optional[str] = None
    start_time: float = 0.0
    end_time: float = 0.0
    transcript_excerpt: Optional[str] = None


class ChapterInfo(BaseModel):
    """Chapter/section in the rich summary"""
    title: str
    text: str
    timestamp_seconds: Optional[int] = None
    timestamp_label: Optional[str] = None
    video_id: Optional[str] = None


class QuoteInfo(BaseModel):
    """Notable quote from the content"""
    text: str
    speaker: str = ""


class RichOutput(BaseModel):
    """Structured rich output from Gemini AI"""
    summary: str = ""
    key_takeaways: List[str] = []
    best_quotes: List[QuoteInfo] = []
    chapters: List[ChapterInfo] = []
    who_should_watch: str = ""
    who_can_skip: str = ""
    action_steps: List[str] = []
    tldr: str = ""
    style_applied: str = "educational"


class ConceptOccurrenceInfo(BaseModel):
    """One source-qualified place where a concept occurs."""
    video_id: str
    start: float
    end: float


class ConceptInfo(BaseModel):
    """An important concept extracted from the source video."""
    concept: str
    importance: float = 0.0
    reason: str = ""
    evidence: List[str] = []
    timestamps: List[List[float]] = []
    occurrences: List[ConceptOccurrenceInfo] = []
    support: int = 1
    aliases: List[str] = []
    source: str = "llm"


class MergeJobCreate(BaseModel):
    """Request to create a new merge job"""
    video_ids: List[str] = Field(..., min_length=1, max_length=10)
    # le=30 adds the "Comprehensive Summary" mode.
    target_duration_minutes: int = Field(default=10, ge=5, le=30)
    # The highlight MP4 already contains the original audio. A separate MP3 is
    # optional and disabled by default because extracting a long reel can add
    # minutes without improving the core video-summary result.
    generate_audio: bool = False
    generate_video: bool = False
    # le raised from 1200 to 1800 alongside the 30-minute profile. The reel is
    # the product itself (original audio), not a companion to a narration.
    highlight_duration_seconds: int = Field(default=120, ge=30, le=1800)
    style: str = "educational"
    # Explicit intent contract. ``None`` preserves compatibility with older
    # callers, whose legacy query fields are resolved at job creation time.
    summary_scope: Optional[Literal["overall", "keyword"]] = None
    source_scope: Optional[Literal["single", "multi"]] = None
    discovery_query: Optional[str] = None
    summary_query: Optional[str] = None
    query: Optional[str] = None
    selected_keywords: List[str] = Field(default_factory=list, max_length=30)
    allow_partial_sources: bool = False


class MergeJob(BaseModel):
    """Full merge job model"""
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Optional[str] = None

    # Status tracking
    status: JobStatus = JobStatus.PENDING
    progress_percent: int = Field(default=0, ge=0, le=100)
    stage_message: str = "Initializing..."

    # Input configuration
    video_ids: List[str]
    target_duration_minutes: int
    duration_style: DurationStyle = DurationStyle.BRIEF
    generate_audio: bool = False
    generate_video: bool = False
    highlight_duration_seconds: int = 120
    style: str = "educational"
    summary_scope: Optional[Literal["overall", "keyword"]] = None
    source_scope: Optional[Literal["single", "multi"]] = None
    discovery_query: Optional[str] = None
    summary_query: Optional[str] = None
    query: Optional[str] = None
    selected_keywords: List[str] = Field(default_factory=list, max_length=30)

    # Processing results
    highlight_segments: List[Dict] = []
    segments: List[VideoSegment] = []
    summary_text: Optional[str] = None
    rich_output: Optional[RichOutput] = None
    fusion_metadata: Optional[FusionMetadata] = None
    keyframes_extracted: Dict[str, int] = {}

    # Semantic selection pipeline output (coverage_selector + concept_extractor).
    # All optional so a job produced by the legacy path still validates.
    concepts: List[ConceptInfo] = []
    selection_metrics: Optional[Dict] = None
    selection_trace: List[Dict] = []
    summarization_decision: Optional[Dict] = None
    selection_mode: str = "legacy"      # "semantic" | "legacy"
    content_type: Literal["explanatory", "narrative"] = "explanatory"
    content_type_confidence: float = 0.0

    # Additive migration fields. The legacy aggregate status remains available
    # until video and text execution are moved to independent workers.
    evidence_manifest: Optional[Dict] = None
    structured_text_output: Optional[Dict] = None
    video_component: OutputComponentState = Field(default_factory=OutputComponentState)
    text_component: OutputComponentState = Field(default_factory=OutputComponentState)

    # Source duration snapshot (resolved at creation time, used for duration gating & Source Reuse Report)
    source_durations: Dict[str, float] = Field(default_factory=dict)

    # Rights & Publication Gate status
    publication_gate_status: Optional[str] = None
    rights_summary: Optional[Dict] = None
    # Write-once historical evidence used for this job's media decision.
    # Normal application flows must never replace an existing value.
    rights_snapshot: Optional[Dict] = None

    # Output paths
    audio_path: Optional[str] = None
    subtitle_path: Optional[str] = None
    video_path: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Error tracking
    error: Optional[str] = None
    warning: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3

    # Language-capability metadata. Unsupported transcripts terminate during
    # preflight, before semantic selection or media rendering.
    summary_unavailable: bool = False
    summary_unavailable_reason: Optional[str] = None
    detected_language: Optional[str] = None
    supported_languages: List[str] = Field(default_factory=lambda: ["en"])
    preflight_failure: Optional[Dict] = None

    # M1 Hardening: Preflight, timings and active source observability
    allow_partial_sources: bool = False
    transcript_preflight: Optional[Dict[str, dict]] = None
    stage_timings_seconds: Dict[str, float] = Field(default_factory=dict)
    active_source: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    job_started_at: Optional[datetime] = None

    checkpoint: str = "created"
    worker_heartbeat_at: Optional[datetime] = None
    recovery_state: Optional[str] = None
    recoverable: bool = False

    evaluation_state: str = "pending"
    evaluation_error: Optional[str] = None
    evaluation_updated_at: Optional[datetime] = None

    class Config:
        use_enum_values = True
        extra = "allow"


class MergeJobResponse(BaseModel):
    """Response when creating/querying a job"""
    job_id: str
    status: str
    progress_percent: int
    stage_message: str
    estimated_seconds: Optional[int] = None
    error: Optional[str] = None
    warning: Optional[str] = None
    summary_scope: Optional[Literal["overall", "keyword"]] = None
    source_scope: Optional[Literal["single", "multi"]] = None
    discovery_query: Optional[str] = None
    summary_query: Optional[str] = None
    query: Optional[str] = None
    selected_keywords: List[str] = Field(default_factory=list)
    stage_timings_seconds: Dict[str, float] = Field(default_factory=dict)
    active_source: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    transcript_preflight: Optional[Dict[str, dict]] = None
    has_video_ready: Optional[bool] = None
    output_status: Optional[str] = None
    video_component: Optional[OutputComponentState] = None
    text_component: Optional[OutputComponentState] = None
    manifest_version: Optional[int] = None

    class Config:
        use_enum_values = True
        extra = "allow"


class MergeJobResult(BaseModel):
    """Final result of a completed job"""
    job_id: str
    status: str
    summary_text: str
    audio_url: Optional[str] = None
    video_url: Optional[str] = None
    metadata: FusionMetadata
    created_at: datetime
    completed_at: datetime
    processing_time_seconds: float
    summary_scope: Optional[Literal["overall", "keyword"]] = None
    source_scope: Optional[Literal["single", "multi"]] = None
    discovery_query: Optional[str] = None
    summary_query: Optional[str] = None
    query: Optional[str] = None
    selected_keywords: List[str] = Field(default_factory=list)


# =====================================================
# DURATION PROFILE MAPPING
# =====================================================

def get_duration_style(minutes: int) -> DurationStyle:
    """Map duration to style. 20 and 30 both map to COMPREHENSIVE."""
    if minutes <= 5:
        return DurationStyle.HEADLINE
    elif minutes <= 10:
        return DurationStyle.BRIEF
    elif minutes <= 15:
        return DurationStyle.STANDARD
    else:
        return DurationStyle.COMPREHENSIVE


# NOTE: the former DURATION_CONFIGS dict lived here. It duplicated the profile
# table in backend/services/duration_profiles.py (DURATION_PROFILES) and was
# never read, so it was a divergence hazard — it had no 2-minute entry after the
# Express profile was added. duration_profiles.get_profile() is the single
# source of truth for target_words and related generation settings.
