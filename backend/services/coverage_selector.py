"""
Coverage Selector — the duration-aware optimizer.

What was wrong before
---------------------
_select_within_budget() sorted candidates by score and took them until the
budget ran out. That is greedy in the worst sense: the score had no memory, so
the tenth clip about overfitting scored exactly as well as the first, and there
was no term at all for *where in the video* a candidate came from. Measured on
this repo's own completed jobs, a 5-minute summary of a 24.8-minute source put
80% of its runtime in the first half and left the last two deciles empty.

What this does instead
----------------------
Maximise total value under a time budget, where value is SUBMODULAR — the gain
from adding a segment shrinks as similar material is already selected. That one
property gives diversity, redundancy avoidance and coverage for free, because
the second explanation of overfitting genuinely adds less than the first.

    value(S) = W_CONCEPT   * concept_coverage(S)      <- facility location
             + W_SEMANTIC  * relevance(S)             <- modular
             + W_COVERAGE  * temporal_coverage(S)     <- concave, sqrt
             + W_COHERENCE * coherence(S)             <- modular
             - W_REDUNDANCY * redundancy(S)

Selection is cost-benefit greedy: at each step take the segment with the best
marginal gain PER SECOND, not the best absolute gain. That stops one 90-second
segment from eating a 300-second budget just because it scored highest, and it
is the standard 1/2(1 - 1/e) approximation for a budgeted submodular maximum —
so the result is provably close to optimal, which is a real thing to say in a
viva.

Coverage is rewarded, never mandated. There is no "one clip per bin" rule: the
temporal term is sqrt(seconds in bin) summed over bins, so the FIRST second
spent in an untouched region is worth much more than the sixtieth second in a
region already well covered. A genuinely front-loaded video still selects mostly
from the front — it just stops doing so by accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np


@dataclass
class SelectionWeights:
    """
    Scoring weights. Every one of these is configurable from .env — see
    core/config.py — because the right balance differs between a dense podcast
    and a slide-driven lecture, and hardcoding it would be a guess.
    """
    concept: float = 0.35       # explains a high-importance concept
    semantic: float = 0.20      # relevant to the video's overall subject
    coverage: float = 0.25      # comes from an under-represented part of the timeline
    coherence: float = 0.10     # is a clean, complete thought
    redundancy: float = 0.25    # penalty: says what an already-picked segment said
    duration_penalty: float = 0.05  # mild bias against very long segments

    @classmethod
    def from_settings(cls, settings=None) -> "SelectionWeights":
        """Build from the app settings object, tolerating missing fields."""
        if settings is None:
            try:
                from ..core.config import get_settings
                settings = get_settings()
            except Exception:
                return cls()
        return cls(
            concept=getattr(settings, "SELECT_CONCEPT_WEIGHT", cls.concept),
            semantic=getattr(settings, "SELECT_SEMANTIC_WEIGHT", cls.semantic),
            coverage=getattr(settings, "SELECT_COVERAGE_WEIGHT", cls.coverage),
            coherence=getattr(settings, "SELECT_COHERENCE_WEIGHT", cls.coherence),
            redundancy=getattr(settings, "SELECT_REDUNDANCY_PENALTY", cls.redundancy),
            duration_penalty=getattr(settings, "SELECT_DURATION_PENALTY", cls.duration_penalty),
        )


@dataclass
class SelectionResult:
    segments: List = field(default_factory=list)      # SemanticSegment objects, chronological
    total_duration: float = 0.0
    budget: float = 0.0
    concepts_covered: List[str] = field(default_factory=list)
    trace: List[Dict] = field(default_factory=list)   # per-pick gain breakdown, for the viva


# How many temporal bins the timeline is divided into for the coverage term.
# 10 gives deciles, which is also what the reporting metrics use.
DEFAULT_BINS = 10

# A segment may exceed the remaining budget by this fraction and still be taken,
# rather than being truncated. Preserving a complete thought beats hitting an
# exact second — a hard requirement of this project.
OVERSHOOT_TOLERANCE = 0.08


# =====================================================================
# FEATURE PREPARATION
# =====================================================================

def _embed_segments(segments: Sequence, embedder=None) -> Optional[np.ndarray]:
    """L2-normalised SBERT matrix for the candidate segments, or None."""
    if not segments:
        return None

    cached = [getattr(s, "embedding", None) for s in segments]
    if all(v is not None for v in cached):
        matrix = np.asarray(cached, dtype=float)
    else:
        if embedder is None:
            try:
                from .fusion_engine import get_sentence_transformer
                embedder = get_sentence_transformer()
            except Exception as exc:
                print(f"[Selector] SBERT unavailable ({exc}) — semantic/redundancy terms disabled")
                return None
        texts = [getattr(s, "text", "") for s in segments]
        try:
            try:
                matrix = np.asarray(embedder.encode(texts, show_progress_bar=False, batch_size=32))
            except TypeError:
                matrix = np.asarray(embedder.encode(texts))
        except Exception as exc:
            print(f"[Selector] Embedding failed ({exc}) — semantic/redundancy terms disabled")
            return None
        for seg, vec in zip(segments, matrix):
            try:
                seg.embedding = vec
            except Exception:
                pass

    if matrix.ndim != 2 or matrix.shape[0] != len(segments):
        return None

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms < 1e-9, 1e-9, norms)


def build_concept_affinity(
    segments: Sequence,
    concepts: Sequence,
    segment_vectors: Optional[np.ndarray],
    embedder=None,
) -> np.ndarray:
    """
    Affinity matrix A[i, j] = how well segment i explains concept j, in [0, 1].

    Two independent signals, combined by taking the stronger:

      * SEMANTIC — cosine similarity between the segment text and the concept
        name+reason. Catches a segment that explains the idea without naming it.

      * TEMPORAL — did this segment fall inside a time window where the concept
        extractor actually saw this concept discussed? This is the grounded
        signal: the LLM told us "overfitting is discussed from 12:40 to 14:10",
        and a segment inside that window is about overfitting whatever its
        wording.

    Returns a zero matrix when there are no concepts, which cleanly disables the
    concept term rather than special-casing it at every call site.
    """
    n, m = len(segments), len(concepts)
    if n == 0 or m == 0:
        return np.zeros((n, max(m, 0)), dtype=float)

    affinity = np.zeros((n, m), dtype=float)

    # --- temporal grounding ---
    for i, seg in enumerate(segments):
        s_start = float(getattr(seg, "start_time", 0.0))
        s_end = float(getattr(seg, "end_time", 0.0))
        s_span = max(s_end - s_start, 1e-6)
        for j, concept in enumerate(concepts):
            best = 0.0
            for (c_start, c_end) in getattr(concept, "timestamps", []) or []:
                overlap = min(s_end, float(c_end)) - max(s_start, float(c_start))
                if overlap > 0:
                    best = max(best, min(1.0, overlap / s_span))
            affinity[i, j] = best

    # --- semantic similarity ---
    concept_vectors = _concept_vectors(concepts, embedder)
    if segment_vectors is not None and concept_vectors is not None:
        sims = segment_vectors @ concept_vectors.T          # [-1, 1]
        sims = np.clip((sims + 1.0) / 2.0, 0.0, 1.0)        # -> [0, 1]
        # Rescale so the term is comparable across videos: SBERT similarities
        # between a transcript passage and a 3-word concept name cluster in a
        # narrow band, and an unscaled value would make every segment look
        # equally on-topic.
        lo, hi = sims.min(), sims.max()
        if hi > lo:
            sims = (sims - lo) / (hi - lo)
        affinity = np.maximum(affinity, sims)

    return affinity


def _concept_vectors(concepts: Sequence, embedder=None) -> Optional[np.ndarray]:
    cached = [getattr(c, "embedding", None) for c in concepts]
    if all(v is not None for v in cached):
        matrix = np.asarray(cached, dtype=float)
    else:
        if embedder is None:
            try:
                from .fusion_engine import get_sentence_transformer
                embedder = get_sentence_transformer()
            except Exception:
                return None
        texts = [f"{getattr(c, 'name', '')}. {getattr(c, 'reason', '')}".strip() for c in concepts]
        try:
            try:
                matrix = np.asarray(embedder.encode(texts, show_progress_bar=False))
            except TypeError:
                matrix = np.asarray(embedder.encode(texts))
        except Exception:
            return None

    if matrix.ndim != 2 or matrix.shape[0] != len(concepts):
        return None
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms < 1e-9, 1e-9, norms)


def _relevance_scores(segment_vectors: Optional[np.ndarray], reference: Optional[np.ndarray]) -> np.ndarray:
    """
    How on-topic each segment is, min-max normalised to [0, 1].

    The reference is the summary embedding when one is supplied, otherwise the
    centroid of all segments (i.e. "the video's own subject"). Falling back to
    the centroid is what keeps this working when the summary is poor — which,
    given the BART bypass bug, it sometimes was.
    """
    if segment_vectors is None:
        return np.full(0 if segment_vectors is None else len(segment_vectors), 0.5)

    if reference is None:
        reference = segment_vectors.mean(axis=0)
    reference = np.asarray(reference, dtype=float).reshape(-1)
    norm = np.linalg.norm(reference) or 1e-9
    scores = segment_vectors @ (reference / norm)

    lo, hi = scores.min(), scores.max()
    if hi > lo:
        return (scores - lo) / (hi - lo)
    return np.full(len(scores), 0.5)


# =====================================================================
# THE OPTIMIZER
# =====================================================================

def select_segments(
    segments: Sequence,
    budget_seconds: float,
    concepts: Sequence = (),
    weights: Optional[SelectionWeights] = None,
    summary_embedding: Optional[np.ndarray] = None,
    embedder=None,
    total_duration: float = 0.0,
    n_bins: int = DEFAULT_BINS,
) -> SelectionResult:
    """
    Choose the highest-value set of complete segments that fits the budget.

    Args:
        segments:       SemanticSegment candidates (any video, any order)
        budget_seconds: the user's chosen duration, as a time budget
        concepts:       Concept objects from concept_extractor (may be empty)
        weights:        SelectionWeights; defaults to values from .env
        summary_embedding: optional reference vector for the relevance term
        total_duration: source timeline length; inferred from segments if 0
        n_bins:         temporal bins for the coverage term

    Returns:
        SelectionResult with segments in chronological order and a per-pick
        trace of why each was chosen.
    """
    segments = list(segments)
    weights = weights or SelectionWeights.from_settings()

    result = SelectionResult(budget=float(budget_seconds))
    if not segments or budget_seconds <= 0:
        return result

    # Requested summary longer than the source: take everything, in order.
    total_available = sum(float(getattr(s, "duration", 0.0)) for s in segments)
    if total_available <= budget_seconds:
        ordered = sorted(segments, key=lambda s: (getattr(s, "video_id", ""), s.start_time))
        result.segments = ordered
        result.total_duration = total_available
        result.concepts_covered = [getattr(c, "name", "") for c in concepts]
        print(f"[Selector] Source ({total_available:.0f}s) fits inside budget "
              f"({budget_seconds:.0f}s) — keeping all {len(ordered)} segments")
        return result

    if total_duration <= 0:
        total_duration = max(float(getattr(s, "end_time", 0.0)) for s in segments)
    total_duration = max(total_duration, 1.0)

    vectors = _embed_segments(segments, embedder=embedder)
    affinity = build_concept_affinity(segments, concepts, vectors, embedder=embedder)
    relevance = (
        _relevance_scores(vectors, summary_embedding)
        if vectors is not None
        else np.full(len(segments), 0.5)
    )

    concept_importance = np.asarray(
        [float(getattr(c, "importance", 0.0)) for c in concepts], dtype=float
    )
    coherence = np.asarray(
        [
            0.5 * float(getattr(s, "completeness", 1.0))
            + 0.5 * float(getattr(s, "boundary_confidence", 0.0))
            for s in segments
        ],
        dtype=float,
    )
    durations = np.asarray([max(float(getattr(s, "duration", 0.0)), 1e-6) for s in segments])

    # Normalising the duration penalty by the longest candidate keeps it in the
    # same [0, 1] range as every other term, so the weights stay comparable.
    longest = float(durations.max())

    # --- mutable state of the greedy run ---
    selected: List[int] = []
    remaining = set(range(len(segments)))
    # best_affinity[j] = how well the BEST already-selected segment covers concept j.
    best_affinity = np.zeros(len(concepts), dtype=float)
    bin_seconds = np.zeros(n_bins, dtype=float)
    total_selected = 0.0

    def bin_gain(idx: int) -> float:
        """
        Concave temporal-coverage gain from adding segment idx.

        sqrt() is the whole trick. Adding the first 30 seconds to an empty bin
        gains sqrt(30) = 5.48; adding 30 more to a bin that already has 60 gains
        sqrt(90) - sqrt(60) = 1.74. Under-represented regions are worth ~3x more
        without any bin ever being mandatory.
        """
        seg = segments[idx]
        before = np.sqrt(bin_seconds).sum()
        trial = bin_seconds.copy()
        _accumulate_bins(trial, seg, total_duration, n_bins)
        return float(np.sqrt(trial).sum() - before)

    # Normaliser for the temporal term: the gain of filling one whole empty bin.
    max_bin_gain = float(np.sqrt(total_duration / n_bins)) or 1.0

    while remaining:
        budget_left = budget_seconds - total_selected
        if budget_left <= 0:
            break

        best_idx = -1
        best_density = -np.inf
        best_parts: Dict[str, float] = {}

        for idx in list(remaining):
            dur = float(durations[idx])

            # A segment that would overshoot beyond tolerance cannot be taken.
            # It stays in `remaining` for no reason, so drop it — this is also
            # what lets the loop terminate when only long segments are left.
            if dur > budget_left * (1.0 + OVERSHOOT_TOLERANCE):
                remaining.discard(idx)
                continue

            if len(concepts):
                # Facility location: gain only from concepts this segment covers
                # BETTER than anything already selected. Diminishing by nature.
                gains = np.maximum(affinity[idx] - best_affinity, 0.0)
                concept_gain = float((gains * concept_importance).sum())
                concept_gain /= max(concept_importance.sum(), 1e-6)
            else:
                concept_gain = 0.0

            temporal_gain = bin_gain(idx) / max_bin_gain

            if vectors is not None and selected:
                redundancy = float(max(vectors[idx] @ vectors[s] for s in selected))
                redundancy = max(0.0, redundancy)
            else:
                redundancy = 0.0

            gain = (
                weights.concept * concept_gain
                + weights.semantic * float(relevance[idx])
                + weights.coverage * temporal_gain
                + weights.coherence * float(coherence[idx])
                - weights.redundancy * redundancy
                - weights.duration_penalty * (dur / longest)
            )

            # Cost-benefit greedy: value per second, not value.
            density = gain / dur
            if density > best_density:
                best_density = density
                best_idx = idx
                best_parts = {
                    "concept": round(concept_gain, 4),
                    "semantic": round(float(relevance[idx]), 4),
                    "coverage": round(temporal_gain, 4),
                    "coherence": round(float(coherence[idx]), 4),
                    "redundancy": round(redundancy, 4),
                    "gain": round(gain, 4),
                    "gain_per_second": round(density, 6),
                }

        if best_idx < 0:
            break

        # A negative-gain pick means everything left is redundant filler. Taking
        # it would actively make the summary worse, so stop early and hand back
        # a shorter, better reel. This is why "actual < requested" is sometimes
        # the correct outcome rather than a failure.
        if best_parts.get("gain", 0.0) <= 0 and selected:
            print(f"[Selector] Stopping at {total_selected:.0f}s/{budget_seconds:.0f}s — "
                  f"no remaining segment adds positive value")
            break

        seg = segments[best_idx]
        selected.append(best_idx)
        remaining.discard(best_idx)
        total_selected += float(durations[best_idx])
        _accumulate_bins(bin_seconds, seg, total_duration, n_bins)
        if len(concepts):
            best_affinity = np.maximum(best_affinity, affinity[best_idx])

        result.trace.append({
            "rank": len(selected),
            "start_time": round(float(seg.start_time), 1),
            "end_time": round(float(seg.end_time), 1),
            "duration": round(float(durations[best_idx]), 1),
            **best_parts,
        })

        # Drop anything that overlaps the pick. Overlapping clips would show the
        # viewer the same footage twice.
        for idx in list(remaining):
            if _overlaps(segments[idx], seg):
                remaining.discard(idx)

    chosen = [segments[i] for i in selected]
    chosen.sort(key=lambda s: (getattr(s, "video_id", ""), s.start_time))

    result.segments = chosen
    result.total_duration = total_selected
    if len(concepts):
        result.concepts_covered = [
            getattr(c, "name", "")
            for c, cov in zip(concepts, best_affinity)
            if cov >= 0.35
        ]

    print(f"[Selector] {len(chosen)} segments, {total_selected:.0f}s of a "
          f"{budget_seconds:.0f}s budget ({total_selected / budget_seconds * 100:.0f}%), "
          f"{len(result.concepts_covered)}/{len(concepts)} concepts covered")

    return result


def _accumulate_bins(bins: np.ndarray, segment, total_duration: float, n_bins: int) -> None:
    """Add a segment's seconds into the temporal bins it spans."""
    width = total_duration / n_bins
    start = float(getattr(segment, "start_time", 0.0))
    end = float(getattr(segment, "end_time", 0.0))
    for b in range(n_bins):
        lo, hi = b * width, (b + 1) * width
        overlap = min(end, hi) - max(start, lo)
        if overlap > 0:
            bins[b] += overlap


def _overlaps(a, b, gap: float = 0.0) -> bool:
    """True when two segments from the same video share screen time."""
    if getattr(a, "video_id", "") != getattr(b, "video_id", ""):
        return False
    return not (
        float(a.end_time) + gap <= float(b.start_time)
        or float(a.start_time) >= float(b.end_time) + gap
    )
