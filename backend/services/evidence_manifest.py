"""Build the immutable handoff shared by video and text output workers."""

from typing import Any, Iterable

from ..models.output_contracts import (
    EvidenceIntent,
    EvidenceManifest,
    EvidenceSegment,
    EvidenceSource,
)


def _value(item: Any, name: str, default=None):
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def build_evidence_manifest(job, clips: Iterable[Any]) -> EvidenceManifest:
    """Convert a frozen clip list into a strict, versioned output contract."""
    keywords = list(dict.fromkeys(
        str(value).strip() for value in (getattr(job, "selected_keywords", None) or [])
        if str(value).strip()
    ))
    source_ids = list(dict.fromkeys(getattr(job, "video_ids", None) or []))
    durations = getattr(job, "source_durations", None) or {}
    sources = [
        EvidenceSource(video_id=video_id, duration_seconds=durations.get(video_id))
        for video_id in source_ids
    ]
    segments = []
    for order, clip in enumerate(clips):
        matches = list(_value(clip, "keyword_matches", ()) or ())
        keyword_scores = {
            str(keyword): float(score)
            for keyword, score in dict(_value(clip, "keyword_scores", {}) or {}).items()
        }
        concepts = list(dict.fromkeys(
            list(_value(clip, "canonical_concepts", ()) or ())
            + list(_value(clip, "covered_concepts", ()) or ())
        ))
        segments.append(EvidenceSegment(
            segment_id=str(_value(clip, "segment_id", "") or f"{_value(clip, 'video_id')}:{order}"),
            order=order,
            video_id=str(_value(clip, "video_id", "")),
            start_time=float(_value(clip, "start_time", 0.0)),
            end_time=float(_value(clip, "end_time", 0.0)),
            text=str(_value(clip, "text", "")),
            concepts=concepts,
            keyword_matches=matches,
            keyword_scores=keyword_scores,
            importance=float(_value(clip, "importance_score", _value(clip, "information_density", 0.0)) or 0.0),
            completeness=float(_value(clip, "completeness", 1.0) or 0.0),
        ))

    scope = getattr(job, "summary_scope", None) or "overall"
    source_scope = "single" if len(source_ids) == 1 else "multi"
    return EvidenceManifest(
        job_id=job.job_id,
        intent=EvidenceIntent(
            summary_scope=scope,
            source_scope=source_scope,
            keywords=keywords if scope == "keyword" else [],
            target_duration_minutes=job.target_duration_minutes,
            style=job.style,
            content_type=getattr(job, "content_type", "explanatory"),
        ),
        sources=sources,
        segments=segments,
    )
