"""
Duration Intelligence System

Adaptive summarization that matches user's time budget.
Each profile has specific characteristics for natural output.

Duration Psychology:
- 5 min: "Quick scan" - User wants highlights only
- 10 min: "Coffee break" - User wants main ideas
- 15 min: "Deep read" - User wants full understanding
- 20 min: "Study session" - User wants comprehensive coverage
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, List, Optional


class SummaryStyle(str, Enum):
    """Summary style based on duration."""
    HEADLINE = "headline"
    BRIEF = "brief"
    STANDARD = "standard"
    COMPREHENSIVE = "comprehensive"


@dataclass
class DurationProfile:
    """
    Configuration for a specific duration target.

    Attributes:
        target_minutes: Target output duration
        style: Summary style
        target_words: Target word count for output
        words_per_minute: Speaking rate assumption
        max_tokens_per_source: Max tokens from each source video
        include_examples: Whether to include examples
        include_transitions: Whether to add transition phrases
        include_sources: Whether to attribute sources
        include_conflicts: Whether to mention disagreements
        max_topics: Maximum topics to cover
        compression_target: Target compression ratio
    """
    target_minutes: int
    style: SummaryStyle
    target_words: int
    words_per_minute: int
    max_tokens_per_source: int
    include_examples: bool
    include_transitions: bool
    include_sources: bool
    include_conflicts: bool
    max_topics: int
    compression_target: float

    @property
    def description(self) -> str:
        """Human-readable description."""
        descriptions = {
            SummaryStyle.HEADLINE: "Quick highlights - key points only",
            SummaryStyle.BRIEF: "Brief summary with main ideas",
            SummaryStyle.STANDARD: "Full coverage with examples",
            SummaryStyle.COMPREHENSIVE: "Deep dive with all details"
        }
        return descriptions.get(self.style, "Summary")

    @property
    def icon(self) -> str:
        """Icon for UI display."""
        icons = {
            SummaryStyle.HEADLINE: "⚡",
            SummaryStyle.BRIEF: "📝",
            SummaryStyle.STANDARD: "📚",
            SummaryStyle.COMPREHENSIVE: "🎓"
        }
        return icons.get(self.style, "📄")


# =====================================================
# PREDEFINED DURATION PROFILES
# =====================================================

DURATION_PROFILES: Dict[int, DurationProfile] = {
    5: DurationProfile(
        target_minutes=5,
        style=SummaryStyle.HEADLINE,
        target_words=150,
        words_per_minute=160,  # Slightly faster for headlines
        max_tokens_per_source=200,
        include_examples=False,
        include_transitions=False,
        include_sources=False,
        include_conflicts=False,
        max_topics=5,
        compression_target=0.05  # 5% of original
    ),
    10: DurationProfile(
        target_minutes=10,
        style=SummaryStyle.BRIEF,
        target_words=250,
        words_per_minute=150,
        max_tokens_per_source=400,
        include_examples=True,
        include_transitions=True,
        include_sources=False,
        include_conflicts=True,
        max_topics=8,
        compression_target=0.10
    ),
    15: DurationProfile(
        target_minutes=15,
        style=SummaryStyle.STANDARD,
        target_words=350,
        words_per_minute=145,
        max_tokens_per_source=600,
        include_examples=True,
        include_transitions=True,
        include_sources=True,
        include_conflicts=True,
        max_topics=12,
        compression_target=0.15
    ),
    20: DurationProfile(
        target_minutes=20,
        style=SummaryStyle.COMPREHENSIVE,
        target_words=450,
        words_per_minute=140,  # Slower for complex content
        max_tokens_per_source=800,
        include_examples=True,
        include_transitions=True,
        include_sources=True,
        include_conflicts=True,
        max_topics=15,
        compression_target=0.20
    ),
    # 30 min = "Comprehensive Summary". No separate algorithm: the duration is a
    # time budget handed to coverage_selector.select_segments(), exactly like
    # every other mode. Only target_words (the summary text length) and the reel
    # budget change.
    30: DurationProfile(
        target_minutes=30,
        style=SummaryStyle.COMPREHENSIVE,
        target_words=600,
        words_per_minute=140,
        max_tokens_per_source=1200,
        include_examples=True,
        include_transitions=True,
        include_sources=True,
        include_conflicts=True,
        max_topics=20,
        compression_target=0.30
    )
}


# User-facing names for each mode. These are labels only — every mode runs the
# same pipeline with a different time budget.
MODE_LABELS: Dict[int, str] = {
    5: "Quick Highlights",
    10: "Key Concepts",
    15: "Balanced Summary",
    20: "Detailed Summary",
    30: "Comprehensive Summary",
}


def get_profile(duration_minutes: int) -> DurationProfile:
    """
    Get the appropriate profile for a duration.

    Args:
        duration_minutes: Target duration in minutes

    Returns:
        Matching or closest DurationProfile
    """
    # Exact match
    if duration_minutes in DURATION_PROFILES:
        return DURATION_PROFILES[duration_minutes]

    # Find closest
    available = sorted(DURATION_PROFILES.keys())
    closest = min(available, key=lambda x: abs(x - duration_minutes))
    return DURATION_PROFILES[closest]


def get_all_profiles() -> List[Dict[str, Any]]:
    """
    Get all profiles for frontend display.

    Returns:
        List of profile dictionaries for UI
    """
    return [
        {
            "value": minutes,
            "label": f"{minutes} min",
            "mode": MODE_LABELS.get(minutes, profile.description),
            "style": profile.style.value,
            "description": profile.description,
            "icon": profile.icon,
            "target_words": profile.target_words
        }
        for minutes, profile in sorted(DURATION_PROFILES.items())
    ]


def calculate_estimated_duration(word_count: int, profile: DurationProfile) -> float:
    """
    Calculate estimated audio duration for given word count.

    Args:
        word_count: Number of words in summary
        profile: Duration profile being used

    Returns:
        Estimated duration in minutes
    """
    return word_count / profile.words_per_minute


def get_target_words_per_video(
    num_videos: int,
    profile: DurationProfile,
    weights: Optional[List[float]] = None
) -> List[int]:
    """
    Calculate target word count per video.

    Args:
        num_videos: Number of source videos
        profile: Duration profile
        weights: Optional importance weights per video

    Returns:
        List of target word counts
    """
    total_words = profile.target_words

    if weights:
        # Weighted distribution
        total_weight = sum(weights)
        return [int(total_words * w / total_weight) for w in weights]
    else:
        # Equal distribution
        per_video = total_words // num_videos
        return [per_video] * num_videos


# =====================================================
# ADAPTIVE SUMMARIZATION SETTINGS
# =====================================================

@dataclass
class SummarizationConfig:
    """Configuration for the summarization model."""
    model_name: str = "facebook/bart-large-cnn"
    max_input_length: int = 1024
    max_output_length: int = 512
    min_output_length: int = 50
    num_beams: int = 4
    length_penalty: float = 2.0
    early_stopping: bool = True
    # Discourages the model from re-using tokens it has already generated.
    # 1.0 = no penalty (the old, silently-applied default — see the bug this
    # fixes in summarization_service._get_pipeline). Raised for styles that
    # produce longer output / go through more chunking, since paraphrase-level
    # degeneration ("not to worry... not to fear... not in fear...") showed up
    # specifically on long COMPREHENSIVE-style runs.
    repetition_penalty: float = 1.3


def get_summarization_config(profile: DurationProfile) -> SummarizationConfig:
    """
    Get model configuration based on profile.

    Different styles require different generation parameters.
    """
    configs = {
        SummaryStyle.HEADLINE: SummarizationConfig(
            max_output_length=300,
            min_output_length=80,
            num_beams=2,  # Faster
            length_penalty=1.0,  # Don't penalize short
            repetition_penalty=1.2
        ),
        SummaryStyle.BRIEF: SummarizationConfig(
            max_output_length=600,
            min_output_length=200,
            num_beams=4,
            length_penalty=2.0,
            repetition_penalty=1.3
        ),
        SummaryStyle.STANDARD: SummarizationConfig(
            max_output_length=900,
            min_output_length=350,
            num_beams=4,
            length_penalty=2.5,
            repetition_penalty=1.3
        ),
        SummaryStyle.COMPREHENSIVE: SummarizationConfig(
            max_output_length=1024,
            min_output_length=450,
            num_beams=4,
            length_penalty=2.5,  # Encourage longer
            repetition_penalty=1.4
        )
    }

    return configs.get(profile.style, SummarizationConfig())


# =====================================================
# TRANSITION PHRASES BY STYLE
# =====================================================

TRANSITIONS = {
    SummaryStyle.HEADLINE: [],  # No transitions for headlines
    SummaryStyle.BRIEF: [
        "Also,",
        "Additionally,",
        "Furthermore,",
        "Moreover,"
    ],
    SummaryStyle.STANDARD: [
        "Building on this point,",
        "In a related vein,",
        "Expanding further,",
        "Another key insight is that",
        "It's also worth noting that",
        "This connects to",
        "Looking at another perspective,"
    ],
    SummaryStyle.COMPREHENSIVE: [
        "To elaborate on this concept,",
        "Diving deeper into this topic,",
        "From a broader perspective,",
        "Examining this more closely,",
        "An important nuance here is that",
        "This raises an interesting point about",
        "Connecting this to the bigger picture,",
        "One critical aspect to consider is",
        "Taking a step back,"
    ]
}


def get_transitions(profile: DurationProfile) -> List[str]:
    """Get appropriate transition phrases for profile."""
    return TRANSITIONS.get(profile.style, [])
