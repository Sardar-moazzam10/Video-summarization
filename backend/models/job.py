"""
Job Models - Merge job persistence and tracking

Features:
- Full job lifecycle tracking
- Progress and stage monitoring
- Fusion metadata storage
- Error handling
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
import uuid


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


class MergeJobCreate(BaseModel):
    """Request to create a new merge job"""
    video_ids: List[str] = Field(..., min_length=1, max_length=10)
    target_duration_minutes: int = Field(default=10, ge=5, le=20)
    voice_id: Optional[str] = None
    generate_audio: bool = True
    generate_video: bool = False
    highlight_duration_seconds: int = Field(default=120, ge=30, le=600)
    style: str = "educational"


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
    voice_id: Optional[str] = None
    generate_audio: bool = True
    generate_video: bool = False
    highlight_duration_seconds: int = 120
    style: str = "educational"

    # Processing results
    highlight_segments: List[Dict] = []
    segments: List[VideoSegment] = []
    summary_text: Optional[str] = None
    rich_output: Optional[RichOutput] = None
    fusion_metadata: Optional[FusionMetadata] = None

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
    retry_count: int = 0
    max_retries: int = 3

    class Config:
        use_enum_values = True


class MergeJobResponse(BaseModel):
    """Response when creating/querying a job"""
    job_id: str
    status: str
    progress_percent: int
    stage_message: str
    estimated_seconds: Optional[int] = None


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


# =====================================================
# DURATION PROFILE MAPPING
# =====================================================

def get_duration_style(minutes: int) -> DurationStyle:
    """Map duration to style."""
    if minutes <= 5:
        return DurationStyle.HEADLINE
    elif minutes <= 10:
        return DurationStyle.BRIEF
    elif minutes <= 15:
        return DurationStyle.STANDARD
    else:
        return DurationStyle.COMPREHENSIVE


DURATION_CONFIGS = {
    DurationStyle.HEADLINE: {
        "target_words": 750,
        "words_per_minute": 160,
        "include_examples": False,
        "include_transitions": False,
        "include_sources": False,
        "max_topics": 5
    },
    DurationStyle.BRIEF: {
        "target_words": 1500,
        "words_per_minute": 150,
        "include_examples": True,
        "include_transitions": True,
        "include_sources": False,
        "max_topics": 8
    },
    DurationStyle.STANDARD: {
        "target_words": 2200,
        "words_per_minute": 145,
        "include_examples": True,
        "include_transitions": True,
        "include_sources": True,
        "max_topics": 12
    },
    DurationStyle.COMPREHENSIVE: {
        "target_words": 2800,
        "words_per_minute": 140,
        "include_examples": True,
        "include_transitions": True,
        "include_sources": True,
        "max_topics": 15
    }
}
