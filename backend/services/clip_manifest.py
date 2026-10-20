"""Immutable handoff from semantic selection to the renderer."""
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class Clip:
    order: int
    video_id: str
    start_time: float
    end_time: float
    segment_id: str
    text: str
    covered_concepts: tuple
    keyword_matches: tuple
    keyword_scores: tuple = ()
    canonical_concepts: tuple = ()
    concept_block: str | None = None
    concept_block_role: str | None = None
    knowledge_units: tuple = ()
    unit_evidence: tuple = ()
    query_relevance: float | None = None
    completeness: float = 1.0
    information_density: float = 0.0
    filler_penalty: float = 0.0
    selection_reason: str = "Complete thought selected for concept coverage and relevance"
    original_core_start: float | None = None
    original_core_end: float | None = None
    provenance_segment_ids: tuple = ()
    start_boundary_evidence: tuple = ()
    end_boundary_evidence: tuple = ()
    non_content_guard_hits: tuple = ()

    def to_dict(self):
        result = asdict(self)
        result["covered_concepts"] = list(self.covered_concepts)
        result["keyword_matches"] = list(self.keyword_matches)
        result["keyword_scores"] = dict(self.keyword_scores)
        result["canonical_concepts"] = list(self.canonical_concepts)
        result["knowledge_units"] = list(self.knowledge_units)
        result["unit_evidence"] = dict(self.unit_evidence)
        result["reason"] = self.selection_reason
        result["provenance_segment_ids"] = list(self.provenance_segment_ids)
        result["start_boundary_evidence"] = dict(self.start_boundary_evidence)
        result["end_boundary_evidence"] = dict(self.end_boundary_evidence)
        result["non_content_guard_hits"] = list(self.non_content_guard_hits)
        return result


def freeze_manifest(segments):
    manifest = tuple(Clip(
        order=i, video_id=s.video_id, start_time=float(s.start_time),
        end_time=float(s.end_time), segment_id=s.segment_id, text=s.text,
        covered_concepts=tuple(getattr(s, "concept_scores", {})),
        keyword_matches=tuple(getattr(s, "keyword_matches", ())),
        keyword_scores=tuple((getattr(s, "keyword_scores", {}) or {}).items()),
        canonical_concepts=tuple(getattr(s, "canonical_concepts", ())),
        concept_block=getattr(s, "concept_block", None),
        concept_block_role=getattr(s, "concept_block_role", None),
        knowledge_units=tuple(getattr(s, "knowledge_unit_scores", {})),
        unit_evidence=tuple(getattr(s, "knowledge_unit_scores", {}).items()),
        query_relevance=getattr(s, "query_relevance", None),
        completeness=float(getattr(s, "completeness", 1.0)),
        information_density=float(getattr(s, "information_density", 0.0)),
        filler_penalty=float(getattr(s, "filler_penalty", 0.0)),
        original_core_start=getattr(s, "original_core_start", float(s.start_time)),
        original_core_end=getattr(s, "original_core_end", float(s.end_time)),
        provenance_segment_ids=tuple(getattr(s, "provenance_segment_ids", ()) or (s.segment_id,)),
        start_boundary_evidence=tuple(
            (getattr(s, "start_boundary_evidence", {}) or {}).items()),
        end_boundary_evidence=tuple(
            (getattr(s, "end_boundary_evidence", {}) or {}).items()),
        non_content_guard_hits=tuple(getattr(s, "non_content_guard_hits", ()) or ()),
    ) for i, s in enumerate(segments))
    validate_manifest([c.to_dict() for c in manifest])
    return manifest


def validate_manifest(clips, video_paths=None):
    previous = None
    for i, clip in enumerate(clips):
        start, end = float(clip["start_time"]), float(clip["end_time"])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
            raise ValueError(f"Invalid interval in clip {i}")
        if clip.get("order", i) != i:
            raise ValueError(f"Manifest order changed at clip {i}")
        if not clip.get("video_id"):
            raise ValueError(f"Missing source for clip {i}")
        if video_paths is not None and clip["video_id"] not in video_paths:
            raise ValueError(f"Selected source unavailable: {clip['video_id']}")
        if (
            previous is not None
            and previous.get("video_id") == clip.get("video_id")
            and float(clip["start_time"]) < float(previous["end_time"]) - 1e-6
        ):
            raise ValueError(f"Overlapping adjacent source intervals at clip {i - 1}->{i}")
        previous = clip
