"""Deterministic physical-boundary repair after selection, before manifest freeze."""

from __future__ import annotations

import copy
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from typing import Sequence
import re
import shutil
import subprocess
import unicodedata


SMALL_NATURAL_GAP_SECONDS = 1.2
MAX_BOUNDARY_EXPANSION_SECONDS = 15.0
MAX_BOUNDARY_EXPANSION_UNITS = 12
PAUSE_CLOSURE_SECONDS = 1.2
SEMANTIC_CONTINUITY_THRESHOLD = 0.68
SEMANTIC_TRANSITION_THRESHOLD = 0.52
SAFE_BOUNDARY_THRESHOLD = 0.50
MAX_SEMANTIC_PROJECTION_SECONDS = 6.0
MIN_MERGED_BLOCK_SECONDS = 90.0
MAX_MERGED_BLOCK_SECONDS = 180.0
MERGE_CAP_P95_MULTIPLIER = 3.0

_NON_CONTENT_PATTERNS = (
    r"\b(?:like|comment)\b.{0,35}\b(?:video|channel|below)\b",
    r"\bsubscribe\b(?:.{0,35}\b(?:channel|below|us)\b)?",
    r"\bfollow\s+(?:us|me)\b",
    r"\b(?:hit|click|press|ring)\b.{0,25}\b(?:bell|notification|subscribe)\b",
    r"\bthanks? for watching\b", r"\bsee you in (?:the )?next (?:one|video)\b",
    r"\blink (?:is )?(?:in|below|under) (?:the |this )?(?:description|video)\b",
    r"\bsponsor(?:ed|ship)?\b",
    r"\b(?:buy|join|check out|look at)\b.{0,30}\b(?:course|merch|channel|school)\b",
    r"\b(?:online (?:coding )?school|money-back guarantee|certificate of completion)\b",
)
_DISCOURSE_TRANSITIONS = (
    "now ", "next ", "moving on", "another ", "in contrast", "on the other hand",
    "let's move", "let us move", "finally ", "in conclusion",
)

_CONTINUATION_STARTS = (
    "and ", "but ", "because ", "where ", "underlying ", "weights ",
    "predictions ", "out there ", "related to ", "which ", "that ",
)
_CLOSURE_PHRASES = ("thanks for watching", "see you in the next one", "in conclusion")


def _words(text):
    return re.findall(r"[\w']+", (text or "").casefold())


def has_complete_start(text: str) -> bool:
    folded = " ".join(_words(text))
    return bool(folded) and not any(folded.startswith(item.strip()) for item in _CONTINUATION_STARTS)


def has_complete_end(text: str) -> bool:
    """Compatibility helper: text alone can prove closure only via punctuation."""
    raw = (text or "").strip()
    folded = " ".join(_words(raw))
    if not folded:
        return False
    if raw.endswith((".", "!", "?", "।")) or any(p in folded for p in _CLOSURE_PHRASES):
        return True
    return False


def explanation_completeness(text: str) -> float:
    return (float(has_complete_start(text)) + float(has_complete_end(text))) / 2.0


@dataclass(frozen=True)
class BoundaryDecision:
    is_complete: bool
    strength: float
    reasons: tuple[str, ...]
    needs_expansion: bool
    classification: str = "SAFE"

    def to_dict(self):
        result = asdict(self)
        result["classification"] = self.classification
        return result


@dataclass
class NormalizedSpeechUnit:
    text: str
    source_id: str
    effective_start: float
    effective_end: float
    raw_caption_ids: tuple[int, ...]
    textual_overlap_removed: bool = False
    textual_correction_resolved: bool = False
    temporal_overlap_normalized: bool = False
    raw_start: float = 0.0
    raw_end: float = 0.0

    def as_entry(self):
        return self.effective_start, self.effective_end, self.text


@dataclass(frozen=True)
class CaptionNormalizationStats:
    raw_caption_count: int = 0
    raw_temporal_overlap_count: int = 0
    raw_overlapping_seconds: float = 0.0
    textual_rolling_overlaps_resolved: int = 0
    textual_corrections_resolved: int = 0
    normalized_speech_unit_count: int = 0
    normalized_overlap_count: int = 0
    preserved_genuine_pause_count: int = 0

    def to_dict(self):
        result = asdict(self)
        result["raw_overlapping_seconds"] = round(result["raw_overlapping_seconds"], 3)
        return result


@dataclass(frozen=True)
class ProjectedSemanticBoundary:
    source_id: str
    original_semantic_timestamp: float
    projected_normalized_timestamp: float
    left_raw_caption_ids: tuple[int, ...]
    right_raw_caption_ids: tuple[int, ...]
    original_confidence: float
    normalized_similarity: float | None
    projection_distance: float
    mapping_method: str

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class SemanticProjectionStats:
    raw_semantic_boundary_count: int = 0
    provenance_mapped_boundaries: int = 0
    fallback_mapped_boundaries: int = 0
    unmapped_boundaries: int = 0
    average_projection_distance: float = 0.0
    max_projection_distance: float = 0.0
    projected_boundaries_rejected_by_cta: int = 0

    def to_dict(self):
        return asdict(self)


def _source_caption_index(raw):
    ordered = []
    for raw_id, item in enumerate(sorted(
            raw or (), key=lambda x: float(x.get("start", x.get("start_time", 0))))):
        start = float(item.get("start", item.get("start_time", 0)))
        duration = float(item.get("duration", 0) or 0)
        end = float(item.get("end", item.get("end_time", start + duration)))
        ordered.append((raw_id, start, end, str(item.get("text", "") or "").strip()))
    return ordered


def _project_core_to_normalized(segment, raw):
    units, _ = normalize_caption_timeline(raw, getattr(segment, "video_id", ""))
    if not units:
        return None
    start = float(getattr(segment, "start_time", 0.0))
    end = float(getattr(segment, "end_time", 0.0))
    overlapping = [unit for unit in units if not (unit.effective_end <= start + 1e-6
                                             or unit.effective_start >= end - 1e-6)]
    if not overlapping:
        return None
    return {
        "original_core_start": start,
        "original_core_end": end,
        "normalized_core_start": overlapping[0].effective_start,
        "normalized_core_end": overlapping[-1].effective_end,
        "source_segment_ids": list(getattr(segment, "provenance_segment_ids", ()) or ()) or [
            getattr(segment, "segment_id", "")
        ],
        "raw_caption_ids": tuple(dict.fromkeys(
            raw_id for unit in overlapping for raw_id in unit.raw_caption_ids
        )),
        "concepts": list(getattr(segment, "canonical_concepts", ()) or ()),
        "keyword_evidence": list(getattr(segment, "keyword_matches", ()) or ()),
        "selection_score": float(getattr(segment, "query_relevance", 0.0) or 0.0),
    }


def _candidate_left_right(units, point, raw_entries):
    if not units:
        return None, None
    raw_catalog = _source_caption_index(raw_entries)
    left_candidates = [raw_id for raw_id, start, _, _ in raw_catalog if start <= point + 1e-6]
    right_candidates = [raw_id for raw_id, start, _, _ in raw_catalog if start >= point - 1e-6]
    left_id = max(left_candidates, default=None)
    right_id = min(right_candidates, default=None)
    if left_id is None or right_id is None:
        return None, None
    if left_id == right_id:
        return None, None
    left_unit = None
    right_unit = None
    for unit in units:
        if left_id in unit.raw_caption_ids and left_unit is None:
            left_unit = unit
        if right_id in unit.raw_caption_ids:
            right_unit = unit
    if left_unit is None or right_unit is None:
        return None, None
    if max(left_unit.raw_caption_ids) >= min(right_unit.raw_caption_ids):
        return None, None
    return left_unit, right_unit


def _transition_fallback(units, point, max_distance):
    if not units or len(units) < 2:
        return None
    best = None
    for idx in range(len(units) - 1):
        left = units[idx]
        right = units[idx + 1]
        boundary = float(left.effective_end)
        distance = abs(boundary - point)
        if distance > max_distance:
            continue
        text = " ".join(part for part in (left.text, right.text) if part).strip()
        if non_content_hits(text) or non_content_hits(left.text) or non_content_hits(right.text):
            continue
        if best is None or distance < best[0]:
            best = (distance, boundary, left, right)
    return best[1:] if best is not None else None


def project_semantic_boundaries(raw_by_video, semantic_segments, max_distance=MAX_SEMANTIC_PROJECTION_SECONDS):
    """Project each raw TextTiling boundary onto the normalized speech timeline."""
    projected = []
    seen = set()
    unique_video_ids = sorted(set(getattr(item, "video_id", "") for item in semantic_segments) | set(raw_by_video))
    for video_id in unique_video_ids:
        raw = raw_by_video.get(video_id, ()) or ()
        if not raw:
            continue
        units, _ = normalize_caption_timeline(raw, video_id)
        if not units:
            continue
        video_segments = sorted(
            [item for item in semantic_segments if getattr(item, "video_id", "") == video_id],
            key=lambda item: item.start_time
        )
        boundary_pairs = list(zip(video_segments, video_segments[1:]))
        for left, right in boundary_pairs:
            if left is right:
                continue
            point = float(getattr(left, "end_time", 0.0))
            left_unit, right_unit = _candidate_left_right(units, point, raw)
            if left_unit is not None and right_unit is not None:
                projected_ts = float(left_unit.effective_end)
                distance = abs(projected_ts - point)
                if distance > max_distance:
                    continue
                boundary = ProjectedSemanticBoundary(
                    source_id=video_id,
                    original_semantic_timestamp=point,
                    projected_normalized_timestamp=projected_ts,
                    left_raw_caption_ids=tuple(left_unit.raw_caption_ids),
                    right_raw_caption_ids=tuple(right_unit.raw_caption_ids),
                    original_confidence=float(getattr(left, "boundary_confidence", 0.0) or 0.0),
                    normalized_similarity=SequenceMatcher(None, left_unit.text, right_unit.text).ratio(),
                    projection_distance=distance,
                    mapping_method="provenance",
                )
                key = (boundary.source_id, boundary.original_semantic_timestamp, boundary.projected_normalized_timestamp)
                if key not in seen:
                    projected.append(boundary)
                    seen.add(key)
                continue
            fallback = _transition_fallback(units, point, max_distance)
            if fallback is None:
                continue
            boundary_ts, left_unit, right_unit = fallback
            distance = abs(boundary_ts - point)
            boundary = ProjectedSemanticBoundary(
                source_id=video_id,
                original_semantic_timestamp=point,
                projected_normalized_timestamp=boundary_ts,
                left_raw_caption_ids=tuple(left_unit.raw_caption_ids),
                right_raw_caption_ids=tuple(right_unit.raw_caption_ids),
                original_confidence=float(getattr(left, "boundary_confidence", 0.0) or 0.0),
                normalized_similarity=SequenceMatcher(None, left_unit.text, right_unit.text).ratio(),
                projection_distance=distance,
                mapping_method="bounded_timestamp_fallback",
            )
            key = (boundary.source_id, boundary.original_semantic_timestamp, boundary.projected_normalized_timestamp)
            if key not in seen:
                projected.append(boundary)
                seen.add(key)
    return projected


def semantic_projection_stats(raw_by_video, semantic_segments, max_distance=MAX_SEMANTIC_PROJECTION_SECONDS):
    projections = project_semantic_boundaries(raw_by_video, semantic_segments, max_distance=max_distance)
    count = 0
    for video_id in sorted(set(getattr(seg, "video_id", "") for seg in semantic_segments)):
        entries = [item for item in semantic_segments if getattr(item, "video_id", "") == video_id]
        count += max(0, len(entries) - 1)
    values = [item.projection_distance for item in projections]
    stats = SemanticProjectionStats(
        raw_semantic_boundary_count=count,
        provenance_mapped_boundaries=sum(1 for item in projections if item.mapping_method == "provenance"),
        fallback_mapped_boundaries=sum(1 for item in projections if item.mapping_method == "bounded_timestamp_fallback"),
        unmapped_boundaries=max(0, count - len(projections)),
        average_projection_distance=(sum(values) / len(values)) if values else 0.0,
        max_projection_distance=max(values) if values else 0.0,
        projected_boundaries_rejected_by_cta=0,
    )
    return stats


def non_content_hits(text: str) -> list[str]:
    folded = " ".join(_words(text))
    return [pattern for pattern in _NON_CONTENT_PATTERNS if re.search(pattern, folded)]


_FUNCTION_WORDS = {
    "and", "or", "but", "because", "although", "if", "when", "while",
    "the", "a", "an", "this", "that", "these", "those", "my", "your",
    "his", "her", "its", "our", "their", "to", "in", "on", "at", "of",
    "for", "with", "by", "from", "into", "as", "is", "are", "was", "were",
    "be", "been", "being", "has", "have", "had", "will", "would", "can",
    "could", "should", "may", "might", "must", "do", "does", "did",
}


def _obvious_continuation(text: str) -> bool:
    """Detect unfinished grammatical structure, not memorised trailing phrases."""
    words = _words(text)
    if not words:
        return True
    if words[-1] in _FUNCTION_WORDS:
        return True
    # Coordinating conjunction followed by a bare noun/adjective fragment,
    # e.g. "... useful for us and machine".
    return len(words) >= 2 and words[-2] in {"and", "or", "but"}


def _cosine(left, right):
    if left is None or right is None:
        return None
    try:
        import numpy as np
        a, b = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        return float(a @ b / denom) if denom > 1e-9 else None
    except (TypeError, ValueError):
        return None


def _comparison_tokens(text):
    folded = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return re.findall(r"[\w']+", folded)


def _exact_token_overlap(left, right, limit=16):
    a, b = _comparison_tokens(left), _comparison_tokens(right)
    for size in range(min(limit, len(a), len(b)), 0, -1):
        if a[-size:] == b[:size]:
            return size
    return 0


def _correction_overlap(left, right, limit=12):
    a, b = _comparison_tokens(left)[-limit:], _comparison_tokens(right)[:limit]
    best = (0, 0.0)
    for size in range(2, min(len(a), len(b)) + 1):
        ratio = sum(
            SequenceMatcher(None, x, y, autojunk=False).ratio()
            for x, y in zip(a[-size:], b[:size])
        ) / size
        if ratio >= .72 and (ratio, size) > (best[1], best[0]):
            best = (size, ratio)
    return best[0]


_NORMALIZATION_CACHE: dict = {}
_ENTRIES_CACHE: dict = {}


def normalize_caption_timeline(raw, source_id=""):
    """Convert overlapping display captions into exclusive local speech units."""
    raw_list = raw or ()
    cache_key = (
        id(raw),
        source_id,
        len(raw_list),
        raw_list[0].get("text", "") if raw_list else "",
        raw_list[-1].get("text", "") if raw_list else "",
    )
    if cache_key in _NORMALIZATION_CACHE:
        cached_units, cached_stats = _NORMALIZATION_CACHE[cache_key]
        return [copy.deepcopy(u) for u in cached_units], cached_stats

    parsed = []
    for raw_id, item in enumerate(sorted(
            raw or (), key=lambda x: float(x.get("start", x.get("start_time", 0))))):
        start = float(item.get("start", item.get("start_time", 0)))
        duration = float(item.get("duration", 0) or 0)
        end = float(item.get("end", item.get("end_time", start + duration)))
        text = " ".join(str(item.get("text", "")).split())
        if text and end > start:
            parsed.append((raw_id, start, end, text))

    units = []
    temporal_count = rolling_count = corrections = pauses = 0
    overlap_seconds = 0.0
    for index, (raw_id, start, raw_end, text) in enumerate(parsed):
        next_start = parsed[index + 1][1] if index + 1 < len(parsed) else None
        temporal = next_start is not None and next_start < raw_end - 1e-6
        if temporal:
            temporal_count += 1
            overlap_seconds += raw_end - next_start
            effective_end = next_start
        else:
            effective_end = raw_end
            if next_start is not None and next_start > raw_end + 1e-6:
                pauses += 1
        effective_end = max(start, effective_end)

        exact = _exact_token_overlap(units[-1].text, text) if units else 0
        corrected = 0
        tokens = text.split()
        provenance = (raw_id,)
        if exact:
            tokens = tokens[exact:]
            rolling_count += 1
        elif units:
            corrected = _correction_overlap(units[-1].text, text)
            if corrected:
                previous_tokens = units[-1].text.split()
                units[-1].text = " ".join(previous_tokens[:-corrected]).strip()
                units[-1].textual_correction_resolved = True
                corrections += 1
                if not units[-1].text:
                    provenance = units[-1].raw_caption_ids + provenance
                    units.pop()

        normalized_text = " ".join(tokens).strip()
        if not normalized_text:
            if units:
                units[-1].raw_caption_ids = tuple(dict.fromkeys(
                    units[-1].raw_caption_ids + provenance))
                units[-1].textual_overlap_removed = True
            continue
        units.append(NormalizedSpeechUnit(
            text=normalized_text, source_id=source_id,
            effective_start=start, effective_end=effective_end,
            raw_caption_ids=provenance,
            textual_overlap_removed=bool(exact),
            textual_correction_resolved=bool(corrected),
            temporal_overlap_normalized=temporal,
            raw_start=start, raw_end=raw_end,
        ))

    # Empty/zero-width display updates carry text provenance but are not useful
    # physical intervals. Attach them to the following unit where possible.
    units = [unit for unit in units if unit.effective_end > unit.effective_start + 1e-6]
    overlap_count = sum(
        current.effective_end > following.effective_start + 1e-6
        for current, following in zip(units, units[1:])
    )
    stats = CaptionNormalizationStats(
        raw_caption_count=len(parsed), raw_temporal_overlap_count=temporal_count,
        raw_overlapping_seconds=overlap_seconds,
        textual_rolling_overlaps_resolved=rolling_count,
        textual_corrections_resolved=corrections,
        normalized_speech_unit_count=len(units),
        normalized_overlap_count=overlap_count,
        preserved_genuine_pause_count=pauses,
    )
    _NORMALIZATION_CACHE[cache_key] = ([copy.deepcopy(u) for u in units], stats)
    return units, stats


def _entries(raw, source_id=""):
    raw_list = raw or ()
    cache_key = (
        id(raw),
        source_id,
        len(raw_list),
        raw_list[0].get("text", "") if raw_list else "",
        raw_list[-1].get("text", "") if raw_list else "",
    )
    if cache_key in _ENTRIES_CACHE:
        return list(_ENTRIES_CACHE[cache_key])
    units, _ = normalize_caption_timeline(raw, source_id)
    result = [unit.as_entry() for unit in units]
    _ENTRIES_CACHE[cache_key] = result
    return list(result)


def aggregate_normalization_metrics(raw_by_video):
    totals = {key: 0 for key in CaptionNormalizationStats().__dict__}
    for source_id, raw in raw_by_video.items():
        _, stats = normalize_caption_timeline(raw, source_id)
        for key, value in asdict(stats).items():
            totals[key] += value
    totals["raw_overlapping_seconds"] = round(totals["raw_overlapping_seconds"], 3)
    return totals


def _text_for_interval(entries, start, end):
    return stitch_caption_entries([
        item for item in entries if min(item[1], end) - max(item[0], start) > 0
    ])


def _semantic_sides(point, video_id, semantic_segments):
    neighbours = sorted(
        (item for item in semantic_segments if item.video_id == video_id),
        key=lambda item: item.start_time,
    )
    left = max((item for item in neighbours if item.end_time <= point + .25),
               key=lambda item: item.end_time, default=None)
    right = min((item for item in neighbours if item.start_time >= point - .25),
                key=lambda item: item.start_time, default=None)
    if left is right:
        right = next((item for item in neighbours if item.start_time >= point - .25
                      and item is not left), None)
    return left, right


def _boundary_context(point, entries):
    previous = max((item for item in entries if item[1] <= point + 1e-6),
                   key=lambda item: item[1], default=None)
    following = min((item for item in entries if item[0] >= point - 1e-6),
                    key=lambda item: item[0], default=None)
    return previous, following


def _classify_boundary(score: float, reasons: tuple[str, ...], hits: list[str]) -> str:
    """Classify a candidate boundary as SAFE / SOFT_SAFE / UNSAFE.

    The goal is to distinguish direct closure evidence from weak neutral signals:
    a short pause or missing punctuation alone never seals a boundary.  Editorial
    transitions can still be safe when they are supported by multiple independent
    semantic or discourse cues, while obvious phrase continuation remains unsafe.
    """
    reason_set = set(reasons)
    if hits or "non_content_guard" in reason_set:
        return "UNSAFE"
    if "source_edge_requires_completion" in reason_set:
        return "UNSAFE"
    if "sentence_ending_punctuation" in reason_set or "meaningful_pause" in reason_set:
        return "SAFE"
    if "cta_outro_transition" in reason_set:
        return "SAFE"

    positive_signals = {
        "semantic_continuity_drop",
        "discourse_transition",
        "texttiling_boundary",
        "cta_outro_transition",
    }
    support = sum(1 for signal in positive_signals if signal in reason_set)
    if "unfinished_grammatical_structure" in reason_set or "mid_proposition_start" in reason_set:
        if support >= 2 or (support == 1 and score >= SAFE_BOUNDARY_THRESHOLD):
            return "SOFT_SAFE"
        return "UNSAFE"
    if "high_semantic_continuity" in reason_set or support >= 1:
        if "coherent_explanation_tail" in reason_set or "coherent_explanation_start" in reason_set:
            return "SOFT_SAFE"
    if support >= 2:
        return "SOFT_SAFE"
    if support == 1 and score >= SAFE_BOUNDARY_THRESHOLD:
        return "SOFT_SAFE"
    if "small_or_no_pause" in reason_set and support == 0:
        return "UNSAFE"
    if not reason_set or ("source_edge" in reason_set and support == 0):
        return "SAFE"
    return "UNSAFE"


def _score_boundary(point, segment, entries, semantic_segments, *, side):
    previous, following = _boundary_context(point, entries)
    following_text = (following[2].casefold().strip() if following else "")
    reasons, score = [], 0.0
    inside_caption = any(start + 1e-6 < point < end - 1e-6 for start, end, _ in entries)
    if inside_caption:
        decision = BoundaryDecision(False, 0.0, ("boundary_inside_normalized_speech_unit",), True, "UNSAFE")
        return decision, []
    if previous is None or following is None:
        reasons.append("source_edge")
        if side == "start" and previous is None:
            score += .60
        elif side == "end" and following is None:
            score += .20

    if side == "end":
        retained = _text_for_interval(entries, segment.start_time, point)
        if _obvious_continuation(retained):
            score -= .55; reasons.append("unfinished_grammatical_structure")
        elif has_complete_end(retained):
            score += .40; reasons.append("coherent_explanation_tail")
        else:
            score += .20; reasons.append("coherent_explanation_tail")
        if following is None and not has_complete_end(retained):
            score -= .50; reasons.append("source_edge_requires_completion")
        expansion_text = _text_for_interval(entries, segment.end_time, point)
        hits = non_content_hits(expansion_text)
    else:
        previous_text = (previous[2].casefold().strip() if previous else "")
        retained = _text_for_interval(entries, point, segment.end_time)
        starts_mid = (
            not has_complete_start(retained)
            or (bool(previous_text) and _obvious_continuation(previous_text))
            or following_text.startswith(("to ", "of ", "in ", "for ", "with ", "which ", "that "))
        )
        if starts_mid:
            score -= .55; reasons.append("mid_proposition_start")
        elif has_complete_start(retained):
            score += .40; reasons.append("coherent_explanation_start")
        if previous is None and not has_complete_start(retained):
            score -= .50; reasons.append("source_edge_requires_completion")
        expansion_text = _text_for_interval(entries, point, segment.start_time)
        hits = non_content_hits(expansion_text)
    if hits:
        score -= 1.0; reasons.append("non_content_guard")

    gap = (following[0] - previous[1]) if previous and following else 0.0
    if gap >= PAUSE_CLOSURE_SECONDS:
        score += .55; reasons.append("meaningful_pause")
    elif previous and following:
        score -= .15; reasons.append("small_or_no_pause")

    left, right = _semantic_sides(point, segment.video_id, semantic_segments)
    similarity = _cosine(getattr(left, "embedding", None), getattr(right, "embedding", None))
    if similarity is not None and similarity <= SEMANTIC_TRANSITION_THRESHOLD:
        score += .40; reasons.append("semantic_continuity_drop")
    elif similarity is not None and similarity >= SEMANTIC_CONTINUITY_THRESHOLD:
        score -= .25; reasons.append("high_semantic_continuity")
    at_tiling = bool(left and right and abs(left.end_time - point) <= .25
                     and abs(right.start_time - point) <= .25)
    if at_tiling and float(getattr(left, "boundary_confidence", 0.0)) >= .5:
        score += .25; reasons.append("texttiling_boundary")

    punctuated = bool(previous and previous[2].rstrip().endswith((".", "!", "?", "।")))
    if punctuated:
        score += .65; reasons.append("sentence_ending_punctuation")
    if any(following_text.startswith(marker) for marker in _DISCOURSE_TRANSITIONS):
        score += .30; reasons.append("discourse_transition")
    if side == "end" and following_text and non_content_hits(following_text):
        score += .55; reasons.append("cta_outro_transition")

    classification = _classify_boundary(score, tuple(reasons), hits)
    safe = classification in {"SAFE", "SOFT_SAFE"}
    decision = BoundaryDecision(safe, round(max(0.0, min(1.0, score)), 3),
                               tuple(reasons), not safe, classification)
    return decision, hits


def assess_start_boundary(segment, raw, semantic_segments=()) -> BoundaryDecision:
    decision, _ = _score_boundary(float(segment.start_time), segment, _entries(raw),
                                  semantic_segments, side="start")
    return decision


def assess_end_boundary(segment, raw, semantic_segments=()) -> BoundaryDecision:
    entries = _entries(raw)
    if not entries:
        return BoundaryDecision(False, 0.0, ("no_local_caption_evidence",), True)
    decision, _ = _score_boundary(float(segment.end_time), segment, entries,
                                  semantic_segments, side="end")
    return decision


def _token_overlap(left: str, right: str, limit: int = 16) -> int:
    a, b = _words(left), _words(right)
    for size in range(min(limit, len(a), len(b)), 0, -1):
        if a[-size:] == b[:size]:
            return size
    return 0


def stitch_caption_entries(entries) -> str:
    """Join captions, removing rolling-caption text only when time overlaps."""
    output = []
    previous_end = None
    for start, end, text in entries:
        tokens = str(text or "").split()
        if output and previous_end is not None and float(start) < previous_end - 1e-6:
            overlap = _token_overlap(" ".join(output), " ".join(tokens))
            if overlap:
                tokens = tokens[overlap:]
        output.extend(tokens)
        previous_end = max(float(end), previous_end or float(end))
    return " ".join(output).strip()


def _semantic_neighbours(segment, semantic_segments):
    return sorted(
        [item for item in semantic_segments if item.video_id == segment.video_id],
        key=lambda item: item.start_time,
    )


def repair_explanation_boundaries(segments: Sequence, raw_by_video: dict, semantic_segments=(), precomputed_projections=None):
    """Resolve each semantic core to the nearest safe local physical cuts."""
    repaired = [copy.deepcopy(segment) for segment in segments]
    expansions = 0
    if precomputed_projections is not None:
        projected_by_video = precomputed_projections
    else:
        all_projections = project_semantic_boundaries(raw_by_video, semantic_segments)
        projected_by_video = {}
        for b in all_projections:
            projected_by_video.setdefault(b.source_id, []).append(b)
    by_video = {}
    for idx, segment in enumerate(repaired):
        by_video.setdefault(segment.video_id, []).append((idx, segment))
    for video_id, items in by_video.items():
        items.sort(key=lambda pair: (float(pair[1].start_time), float(pair[1].end_time), pair[0]))
        for local_index, (_, segment) in enumerate(items):
            previous_same = items[local_index - 1][1] if local_index > 0 else None
            next_same = items[local_index + 1][1] if local_index + 1 < len(items) else None
            lower_bound = float(getattr(previous_same, "end_time", segment.start_time))
            upper_bound = float(getattr(next_same, "start_time", segment.end_time))
            raw = raw_by_video.get(video_id, ()) or ()
            entries = _entries(raw)
            if not entries:
                segment.completeness = 0.0
                continue

            core_start, core_end = float(segment.start_time), float(segment.end_time)
            if previous_same is not None and float(segment.start_time) < lower_bound:
                segment.start_time = lower_bound
            if next_same is not None and float(segment.end_time) > upper_bound:
                segment.end_time = upper_bound

            segment.original_core_start = core_start
            segment.original_core_end = core_end
            segment.provenance_segment_ids = list(dict.fromkeys(
                list(getattr(segment, "provenance_segment_ids", ()) or ()) + [segment.segment_id]
            ))
            core_text = _text_for_interval(entries, core_start, core_end)
            core_hits = non_content_hits(core_text)
            neighbours = _semantic_neighbours(segment, semantic_segments)

            start_points = {core_start}
            start_points.update(start for start, _, _ in entries
                                if abs(start - core_start) <= MAX_BOUNDARY_EXPANSION_SECONDS)
            start_points.update(float(item.start_time) for item in neighbours
                                if abs(item.start_time - core_start) <= MAX_BOUNDARY_EXPANSION_SECONDS)
            for boundary in projected_by_video.get(segment.video_id, ()):
                if abs(boundary.projected_normalized_timestamp - core_start) <= MAX_BOUNDARY_EXPANSION_SECONDS:
                    start_points.add(boundary.projected_normalized_timestamp)
            end_points = {core_end}
            end_points.update(end for _, end, _ in entries
                              if end > core_start and abs(end - core_end) <= MAX_BOUNDARY_EXPANSION_SECONDS)
            end_points.update(float(item.end_time) for item in neighbours
                              if item.end_time > core_start
                              and abs(item.end_time - core_end) <= MAX_BOUNDARY_EXPANSION_SECONDS)
            for boundary in projected_by_video.get(segment.video_id, ()):
                if abs(boundary.projected_normalized_timestamp - core_end) <= MAX_BOUNDARY_EXPANSION_SECONDS:
                    end_points.add(boundary.projected_normalized_timestamp)

            if previous_same is not None:
                start_points = {point for point in start_points if point >= lower_bound - 1e-6}
            if next_same is not None:
                end_points = {point for point in end_points if point <= upper_bound + 1e-6}

            chosen_start = None
            for point in sorted(start_points, key=lambda p: (abs(p - core_start), p))[:MAX_BOUNDARY_EXPANSION_UNITS + 1]:
                if previous_same is not None and point < lower_bound - 1e-6:
                    continue
                probe = copy.copy(segment); probe.start_time = point; probe.end_time = core_end
                decision, hits = _score_boundary(point, probe, entries, semantic_segments, side="start")
                if decision.is_complete and not hits:
                    chosen_start = (point, decision)
                    break
            chosen_end = None
            for point in sorted(end_points, key=lambda p: (abs(p - core_end), p))[:MAX_BOUNDARY_EXPANSION_UNITS + 1]:
                if next_same is not None and point > upper_bound + 1e-6:
                    continue
                probe = copy.copy(segment); probe.start_time = chosen_start[0] if chosen_start else core_start
                probe.end_time = point
                decision, hits = _score_boundary(point, probe, entries, semantic_segments, side="end")
                if decision.is_complete and not hits:
                    chosen_end = (point, decision)
                    break

            if chosen_start:
                segment.start_time = chosen_start[0]
            if chosen_end:
                segment.end_time = chosen_end[0]
            if previous_same is not None and segment.start_time < lower_bound:
                segment.start_time = lower_bound
            if next_same is not None and segment.end_time > upper_bound:
                segment.end_time = upper_bound
            if segment.start_time >= segment.end_time:
                segment.start_time = float(core_start)
                segment.end_time = float(core_end)
            segment.text = _text_for_interval(entries, segment.start_time, segment.end_time)
            segment.start_boundary_evidence = (
                chosen_start[1].to_dict() if chosen_start else
                BoundaryDecision(False, 0.0, ("no_safe_start_in_window",), True).to_dict()
            )
            segment.end_boundary_evidence = (
                chosen_end[1].to_dict() if chosen_end else
                BoundaryDecision(False, 0.0, ("no_safe_end_in_window",), True).to_dict()
            )
            segment.boundary_evidence = segment.end_boundary_evidence
            segment.non_content_guard_hits = core_hits
            pure_cta = bool(core_hits and len(core_text.split()) < 30)
            segment.completeness = float(bool(chosen_start and chosen_end and not pure_cta))
            if segment.start_time != core_start or segment.end_time != core_end:
                expansions += 1
    return repaired, expansions


def _coalesced_source_intervals(intervals):
    by_source = {}
    for source_id, start, end in intervals:
        start, end = float(start), float(end)
        if end > start:
            by_source.setdefault(source_id, []).append((start, end))
    result = []
    for source_id, source_intervals in by_source.items():
        ordered = sorted(source_intervals)
        if not ordered:
            continue
        current_start, current_end = ordered[0]
        for start, end in ordered[1:]:
            if start <= current_end + 1e-6:
                current_end = max(current_end, end)
            else:
                result.append((source_id, current_start, current_end))
                current_start, current_end = start, end
        result.append((source_id, current_start, current_end))
    return result


def _source_interval_duration(intervals) -> float:
    return sum(end - start for _, start, end in _coalesced_source_intervals(intervals))


def rebuild_final_texts(segments: Sequence, raw_by_video: dict, semantic_segments=(), audit_stats=None):
    """Rebuild text once from final intervals with exclusive caption ownership and local CTA removal."""
    work = [copy.deepcopy(segment) for segment in segments]
    owned = {id(segment): [] for segment in work}
    by_source = {}
    for segment in work:
        by_source.setdefault(segment.video_id, []).append(segment)
    for video_id, source_segments in by_source.items():
        raw = sorted(raw_by_video.get(video_id, ()) or (), key=lambda x: float(x.get("start", 0)))
        for item in raw:
            start = float(item.get("start", item.get("start_time", 0)))
            duration = float(item.get("duration", 0) or 0)
            end = float(item.get("end", item.get("end_time", start + duration)))
            text = " ".join(str(item.get("text", "")).split())
            choices = []
            for index, segment in enumerate(source_segments):
                overlap = min(end, float(segment.end_time)) - max(start, float(segment.start_time))
                if overlap > 0:
                    choices.append((overlap, -index, segment))
            if choices:
                segment = max(choices, key=lambda value: (value[0], value[1]))[2]
                owned[id(segment)].append((start, end, text))

    rebuilt_segments = []
    detected_intervals = []
    removed_intervals = []
    for segment in work:
        entries = owned[id(segment)]
        if not entries:
            segment.text = ""
            segment.completeness = 0.0
            segment.non_content_guard_hits = []
            rebuilt_segments.append(segment)
            continue

        clean_entries = [e for e in entries if not non_content_hits(e[2])]
        offending_entries = [e for e in entries if non_content_hits(e[2])]
        detected_intervals.extend((segment.video_id, e[0], e[1]) for e in offending_entries)

        if not clean_entries:
            segment.text = stitch_caption_entries(entries)
            segment.non_content_guard_hits = non_content_hits(segment.text)
            segment.completeness = 0.0
            removed_intervals.extend((segment.video_id, e[0], e[1]) for e in offending_entries)
            rebuilt_segments.append(segment)
            continue

        if not offending_entries:
            segment.text = stitch_caption_entries(clean_entries) if clean_entries else segment.text
            segment.non_content_guard_hits = []
            segment.completeness = float(getattr(segment, "completeness", 1.0))
            rebuilt_segments.append(segment)
            continue

        first_clean_idx = next(i for i, e in enumerate(entries) if not non_content_hits(e[2]))
        last_clean_idx = len(entries) - 1 - next(i for i, e in enumerate(reversed(entries)) if not non_content_hits(e[2]))
        trimmed_entries = entries[first_clean_idx:last_clean_idx + 1]

        internal_offending = [e for e in trimmed_entries if non_content_hits(e[2])]
        if not internal_offending:
            removed_intervals.extend((segment.video_id, e[0], e[1]) for e in offending_entries)
            segment.start_time = float(trimmed_entries[0][0])
            segment.end_time = float(trimmed_entries[-1][1])
            segment.text = stitch_caption_entries(trimmed_entries)
            start_decision = assess_start_boundary(
                segment, raw_by_video.get(segment.video_id, ()), semantic_segments)
            end_decision = assess_end_boundary(
                segment, raw_by_video.get(segment.video_id, ()), semantic_segments)
            segment.start_boundary_evidence = start_decision.to_dict()
            segment.end_boundary_evidence = end_decision.to_dict()
            segment.boundary_evidence = end_decision.to_dict()
            segment.non_content_guard_hits = []
            segment.completeness = float(start_decision.is_complete and end_decision.is_complete)
            rebuilt_segments.append(segment)
        else:
            removed_intervals.extend((segment.video_id, e[0], e[1]) for e in offending_entries)
            from itertools import groupby
            for is_offending, grp_iter in groupby(trimmed_entries, key=lambda e: bool(non_content_hits(e[2]))):
                if not is_offending:
                    grp = list(grp_iter)
                    if not grp:
                        continue
                    sub_seg = copy.deepcopy(segment)
                    sub_seg.start_time = float(grp[0][0])
                    sub_seg.end_time = float(grp[-1][1])
                    sub_seg.text = stitch_caption_entries(grp)
                    if sub_seg.duration < 3.0:
                        continue
                    start_decision = assess_start_boundary(
                        sub_seg, raw_by_video.get(sub_seg.video_id, ()), semantic_segments)
                    end_decision = assess_end_boundary(
                        sub_seg, raw_by_video.get(sub_seg.video_id, ()), semantic_segments)
                    sub_seg.start_boundary_evidence = start_decision.to_dict()
                    sub_seg.end_boundary_evidence = end_decision.to_dict()
                    sub_seg.boundary_evidence = end_decision.to_dict()
                    sub_seg.non_content_guard_hits = []
                    sub_seg.completeness = float(start_decision.is_complete and end_decision.is_complete)
                    rebuilt_segments.append(sub_seg)

    if audit_stats is not None:
        audit_stats["cta_spans_detected"] = len(_coalesced_source_intervals(detected_intervals))
        audit_stats["cta_spans_removed"] = len(_coalesced_source_intervals(removed_intervals))
        audit_stats["cta_removed_seconds"] = round(_source_interval_duration(removed_intervals), 3)
    return rebuilt_segments

def _value(segment):
    evidence = list((getattr(segment, "knowledge_unit_scores", {}) or {}).values())
    evidence += list((getattr(segment, "concept_scores", {}) or {}).values())
    return (max(evidence or [0.0]) + float(getattr(segment, "query_relevance", 0.0) or 0.0)
            + float(getattr(segment, "information_density", 0.0) or 0.0))


def reconcile_physical_duration(selected, candidates, raw_by_video, semantic_segments,
                                budget, min_fill=0.9, overshoot_tolerance=0.08):
    """Reconcile only whole, contextually closed physical intervals with bounded infeasibility evidence."""
    work = list(selected)
    rejected_reasons = {
        "temporal_overlap": 0,
        "non_content": 0,
        "closure_incomplete": 0,
        "budget_overshoot": 0,
    }
    candidates_examined = 0
    added = 0
    removed = 0

    maximum = float(budget) * (1.0 + float(overshoot_tolerance))
    victim_ids = set()
    while work and sum(item.duration for item in work) > maximum:
        victim = min(range(len(work)), key=lambda i: (_value(work[i]), -work[i].duration, i))
        victim_seg = work.pop(victim)
        victim_ids.add(getattr(victim_seg, "segment_id", ""))
        for prov_id in (getattr(victim_seg, "provenance_segment_ids", ()) or ()):
            victim_ids.add(prov_id)
        removed += 1

    minimum = float(budget) * float(min_fill)
    current_duration = sum(item.duration for item in work)
    selected_ids = set()
    for item in work:
        selected_ids.add(getattr(item, "segment_id", ""))
        for prov_id in (getattr(item, "provenance_segment_ids", ()) or ()):
            selected_ids.add(prov_id)

    unused = sorted(
        (copy.deepcopy(item) for item in candidates
         if getattr(item, "segment_id", "") not in selected_ids
         and getattr(item, "segment_id", "") not in victim_ids),
        key=lambda item: (-_value(item), item.video_id, item.start_time),
    )

    all_projections = project_semantic_boundaries(raw_by_video, semantic_segments)
    projected_by_video = {}
    for b in all_projections:
        projected_by_video.setdefault(b.source_id, []).append(b)

    for candidate in unused:
        if current_duration >= minimum:
            break
        candidates_examined += 1

        cand_start = float(candidate.start_time)
        cand_end = float(candidate.end_time)
        same_source_work = [item for item in work if item.video_id == candidate.video_id]

        overlapping_items = [
            item for item in same_source_work
            if min(float(item.end_time), cand_end) > max(float(item.start_time), cand_start) + 0.05
        ]
        if overlapping_items:
            enveloped = any(
                float(item.start_time) <= cand_start + 0.05 and float(item.end_time) >= cand_end - 0.05
                for item in overlapping_items
            )
            if enveloped or len(overlapping_items) > 1:
                rejected_reasons["temporal_overlap"] += 1
                continue
            item = overlapping_items[0]
            if cand_start < float(item.start_time) and cand_end <= float(item.end_time):
                cand_end = float(item.start_time)
            elif cand_start >= float(item.start_time) and cand_end > float(item.end_time):
                cand_start = float(item.end_time)
            else:
                rejected_reasons["temporal_overlap"] += 1
                continue
            if cand_end - cand_start < 15.0:
                rejected_reasons["temporal_overlap"] += 1
                continue
            candidate.start_time = cand_start
            candidate.end_time = cand_end

        raw = raw_by_video.get(candidate.video_id, ())
        candidate_text = _text_for_interval(
            _entries(raw),
            float(candidate.start_time), float(candidate.end_time),
        )
        if non_content_hits(candidate_text) and len(candidate_text.split()) < 30:
            rejected_reasons["non_content"] += 1
            continue

        trial, _ = repair_explanation_boundaries(
            [candidate], raw_by_video, semantic_segments, precomputed_projections=projected_by_video
        )
        trial = rebuild_final_texts(trial, raw_by_video, semantic_segments)
        trial = [t for t in trial if float(getattr(t, "completeness", 0.0)) >= 1.0]
        if not trial:
            rejected_reasons["closure_incomplete"] += 1
            continue

        for t in trial:
            if any(
                item.video_id == t.video_id
                and min(float(item.end_time), float(t.end_time))
                    > max(float(item.start_time), float(t.start_time)) + 0.05
                for item in work
            ):
                rejected_reasons["temporal_overlap"] += 1
                continue
            if current_duration + t.duration > maximum:
                rejected_reasons["budget_overshoot"] += 1
                continue
            work.append(t)
            current_duration += t.duration
            added += 1
            if current_duration >= minimum:
                break

    final_fill_ratio = current_duration / max(float(budget), 1e-6)
    underfilled = current_duration < minimum
    exhausted = candidates_examined == len(unused)
    eligible_remaining_candidates = 0 if exhausted else len(unused) - candidates_examined
    eligible_remaining_duration = 0.0 if exhausted else sum(
        item.duration for item in unused[candidates_examined:]
    )
    infeasibility_proven = bool(underfilled and exhausted and eligible_remaining_candidates == 0)
    if infeasibility_proven:
        infeasibility_reason = "all_reserve_candidates_exhausted_without_legal_fill"
    elif underfilled:
        infeasibility_reason = "reserve_candidates_not_exhausted"
    else:
        infeasibility_reason = None

    stats = {
        "budget_blocks_removed": removed,
        "closure_rejections_during_reconciliation": rejected_reasons["closure_incomplete"],
        "non_content_candidates_rejected": rejected_reasons["non_content"],
        "candidates_added_during_underfill_reconciliation": added,
        "candidates_examined": candidates_examined,
        "refill_candidates_total": len(unused),
        "refill_candidates_examined": candidates_examined,
        "refill_candidates_added": added,
        "rejected_reason_counts": rejected_reasons,
        "eligible_remaining_candidates": eligible_remaining_candidates,
        "eligible_remaining_duration": round(eligible_remaining_duration, 3),
        "available_remaining_duration": round(eligible_remaining_duration, 3),
        "final_fill_ratio": round(final_fill_ratio, 4),
        "infeasibility_proven": infeasibility_proven,
        "infeasibility_reason": infeasibility_reason,
    }
    return work, stats

def probe_rendered_duration(path: str):
    """Return local rendered MP4 duration without network access."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not path:
        return None
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=15,
        )
        value = float((result.stdout or "").strip())
        return value if result.returncode == 0 and value > 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


@dataclass(frozen=True)
class BoundaryRepairStats:
    overlap_count_before: int = 0
    overlapping_seconds_before: float = 0.0
    overlap_count_after: int = 0
    overlapping_seconds_after: float = 0.0
    adjacent_intervals_merged: int = 0
    ownership_boundaries_repaired: int = 0
    max_merged_block_seconds: float = MAX_MERGED_BLOCK_SECONDS
    semantic_segment_duration_distribution: dict | None = None

    def to_dict(self):
        return {
            "boundary_overlap_count_before": self.overlap_count_before,
            "repeated_interval_seconds_before": round(self.overlapping_seconds_before, 3),
            "boundary_overlap_count": self.overlap_count_after,
            "repeated_interval_seconds": round(self.overlapping_seconds_after, 3),
            "adjacent_same_source_merges": self.adjacent_intervals_merged,
            "ownership_boundaries_repaired": self.ownership_boundaries_repaired,
            "max_merged_block_seconds": round(self.max_merged_block_seconds, 3),
            "semantic_segment_duration_distribution": self.semantic_segment_duration_distribution or {},
        }


def _labels(segment) -> set[str]:
    labels = set(getattr(segment, "canonical_concepts", ()) or ())
    labels.update((getattr(segment, "concept_scores", {}) or {}).keys())
    labels.update((getattr(segment, "knowledge_unit_scores", {}) or {}).keys())
    return {str(item).casefold() for item in labels if item}


def _same_explanation(left, right) -> bool:
    if getattr(left, "video_id", None) != getattr(right, "video_id", None):
        return False
    left_concepts = set(getattr(left, "canonical_concepts", ()) or ())
    right_concepts = set(getattr(right, "canonical_concepts", ()) or ())
    if left_concepts and right_concepts and (left_concepts & right_concepts):
        sim = _cosine(getattr(left, "embedding", None), getattr(right, "embedding", None))
        if sim is not None and sim < SEMANTIC_TRANSITION_THRESHOLD:
            return False
        return True
    sim = _cosine(getattr(left, "embedding", None), getattr(right, "embedding", None))
    if sim is not None and sim >= SEMANTIC_CONTINUITY_THRESHOLD:
        return True
    return False


def _merge(left, right):
    left.end_time = max(float(left.end_time), float(right.end_time))
    left.start_time = min(float(left.start_time), float(right.start_time))
    left.text = " ".join(part for part in (left.text.strip(), right.text.strip()) if part)
    left.sentences = list(getattr(left, "sentences", ()) or ()) + list(
        getattr(right, "sentences", ()) or ()
    )
    for attr in ("concept_scores", "knowledge_unit_scores"):
        target = dict(getattr(left, attr, {}) or {})
        for key, value in (getattr(right, attr, {}) or {}).items():
            target[key] = max(float(value), float(target.get(key, 0.0)))
        setattr(left, attr, target)
    meta = dict(getattr(left, "knowledge_unit_metadata", {}) or {})
    meta.update(getattr(right, "knowledge_unit_metadata", {}) or {})
    left.knowledge_unit_metadata = meta
    left.canonical_concepts = list(dict.fromkeys(
        list(getattr(left, "canonical_concepts", ()) or ())
        + list(getattr(right, "canonical_concepts", ()) or ())
    ))
    left.keyword_matches = list(dict.fromkeys(
        list(getattr(left, "keyword_matches", ()) or ())
        + list(getattr(right, "keyword_matches", ()) or ())
    ))
    left.provenance_segment_ids = list(dict.fromkeys(
        list(getattr(left, "provenance_segment_ids", ()) or ())
        + list(getattr(right, "provenance_segment_ids", ()) or ())
        + [getattr(left, "segment_id", ""), getattr(right, "segment_id", "")]
    ))
    left.original_core_start = min(
        float(getattr(left, "original_core_start", left.start_time)),
        float(getattr(right, "original_core_start", right.start_time)),
    )
    left.original_core_end = max(
        float(getattr(left, "original_core_end", left.end_time)),
        float(getattr(right, "original_core_end", right.end_time)),
    )
    left.completeness = min(float(getattr(left, "completeness", 1.0)), float(getattr(right, "completeness", 1.0)))
    left.start_boundary_evidence = getattr(left, "start_boundary_evidence", None)
    left.end_boundary_evidence = getattr(right, "end_boundary_evidence", None)
    left.boundary_evidence = left.end_boundary_evidence
    return left


def _overlap_totals(segments: Sequence) -> tuple[int, float]:
    count, seconds = 0, 0.0
    for left, right in zip(segments, segments[1:]):
        if getattr(left, "video_id", None) != getattr(right, "video_id", None):
            continue
        overlap = min(float(left.end_time), float(right.end_time)) - max(float(left.start_time), float(right.start_time))
        if overlap > 1e-6:
            count += 1
            seconds += overlap
    return count, seconds


def _percentile(values, percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def semantic_segment_duration_distribution(segments: Sequence) -> dict:
    durations = [float(segment.duration) for segment in segments if float(segment.duration) > 0]
    return {
        "count": len(durations),
        "p50": round(_percentile(durations, 0.50), 3),
        "p75": round(_percentile(durations, 0.75), 3),
        "p90": round(_percentile(durations, 0.90), 3),
        "p95": round(_percentile(durations, 0.95), 3),
        "max": round(max(durations, default=0.0), 3),
    }


def derive_max_merged_block_seconds(segments: Sequence) -> tuple[float, dict]:
    distribution = semantic_segment_duration_distribution(segments)
    observed_cap = distribution["p95"] * MERGE_CAP_P95_MULTIPLIER
    cap = max(MIN_MERGED_BLOCK_SECONDS, min(MAX_MERGED_BLOCK_SECONDS, observed_cap))
    return cap, distribution


def repair_physical_boundaries(segments: Sequence, max_merged_block_seconds: float | None = None):
    """Return repaired copies and audit metrics; never alter cross-source times."""
    work = [copy.deepcopy(segment) for segment in segments]
    observed_cap, duration_distribution = derive_max_merged_block_seconds(work)
    merge_cap = observed_cap if max_merged_block_seconds is None else float(max_merged_block_seconds)
    before_count, before_seconds = _overlap_totals(work)
    merged = ownership = 0
    same_source_order = {}
    for idx, segment in enumerate(work):
        same_source_order.setdefault(segment.video_id, []).append((idx, segment))

    final_by_slot = {}
    for video_id, items in same_source_order.items():
        original_slots = sorted(pair[0] for pair in items)
        ordered_items = sorted(items, key=lambda pair: (float(pair[1].start_time), float(pair[1].end_time), pair[0]))
        repaired_video = []
        for _, current in ordered_items:
            if not repaired_video:
                repaired_video.append(current)
                continue
            previous = repaired_video[-1]
            gap = float(current.start_time) - float(previous.end_time)
            projected_duration = float(current.end_time) - float(previous.start_time)
            if (gap <= SMALL_NATURAL_GAP_SECONDS
                and projected_duration <= merge_cap
                and _same_explanation(previous, current)):
                repaired_video[-1] = _merge(previous, current)
                merged += 1
                continue
            if gap < 0:
                current.start_time = float(previous.end_time)
                ownership += 1
            if current.end_time > current.start_time + 1e-3:
                repaired_video.append(current)

        for slot, repaired_segment in zip(original_slots, repaired_video):
            final_by_slot[slot] = repaired_segment

    repaired = [final_by_slot[idx] for idx in sorted(final_by_slot)]
    filtered = []
    for segment in repaired:
        if filtered and getattr(segment, "video_id", None) == getattr(filtered[-1], "video_id", None):
            previous = filtered[-1]
            overlap = min(float(segment.end_time), float(previous.end_time)) - max(float(segment.start_time), float(previous.start_time))
            if overlap > 1e-6:
                if float(segment.end_time) <= float(previous.end_time) + 1e-6:
                    ownership += 1
                    continue
                segment.start_time = float(previous.end_time)
                ownership += 1
        if segment.end_time > segment.start_time + 1e-3:
            filtered.append(segment)
    repaired = filtered

    after_count, after_seconds = _overlap_totals(repaired)
    stats = BoundaryRepairStats(
        before_count, before_seconds, after_count, after_seconds, merged, ownership,
        merge_cap, duration_distribution,
    )
    return repaired, stats
