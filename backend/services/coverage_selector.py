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
Maximise useful coverage under a time budget. The concept coverage gain
from adding a segment shrinks as similar material is already selected. That one
property gives diversity, redundancy avoidance and coverage for free, because
the second explanation of overfitting genuinely adds less than the first.

    value(S) = W_CONCEPT   * concept_coverage(S)              <- facility location
             + W_SEMANTIC  * relevance(S) * (1 - redundancy)  <- MMR-discounted
             + W_COVERAGE  * temporal_coverage(S) * value(S) <- concave, value-gated
             + W_COHERENCE * coherence(S)                     <- modular
             - W_REDUNDANCY * redundancy(S)

Selection is cost-benefit greedy: at each step take the segment with the best
marginal gain PER SECOND, not the best absolute gain. That stops one 90-second
segment from eating a 300-second budget just because it scored highest.
The combined penalties, commitments and fill rules form a heuristic; no
approximation guarantee is claimed for this implementation.

Coverage is rewarded, never mandated. There is no "one clip per bin" rule: the
temporal term is sqrt(seconds in bin) summed over bins, so the FIRST second
spent in an untouched region is worth much more than the sixtieth second in a
region already well covered. A genuinely front-loaded video still selects mostly
from the front — it just stops doing so by accident.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from time import perf_counter
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


# The optimizer may only stop early (because nothing left adds value) once the
# reel has reached this fraction of the requested duration. See the guard in
# select_segments() for why an unguarded early stop is dangerous.
# 0.90 caps the shortfall at 10% of the requested duration, which is the
# "approximately respected" tolerance the product asks for, while still leaving
# the escape hatch open for a source whose remaining material is pure filler.
# Overridable via SELECT_MIN_BUDGET_FILL in .env.
MIN_BUDGET_FILL = 0.90
UNIT_COVERED_THRESHOLD = 0.20
MIN_MARGINAL_UNIT_GAIN = 0.01

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
    min_budget_fill: float = MIN_BUDGET_FILL   # see the module constant

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
            min_budget_fill=getattr(settings, "SELECT_MIN_BUDGET_FILL", MIN_BUDGET_FILL),
        )


@dataclass
class SelectionResult:
    segments: List = field(default_factory=list)      # SemanticSegment objects, chronological
    total_duration: float = 0.0
    budget: float = 0.0
    concepts_covered: List[str] = field(default_factory=list)
    trace: List[Dict] = field(default_factory=list)   # per-pick gain breakdown, for the viva
    # Mean nearest-neighbour cosine across ALL candidates. The redundancy metric
    # is reported relative to this, because "how similar are two passages of one
    # podcast" is a property of the video and the encoder, not of the selection.
    baseline_similarity: Optional[float] = None
    semantic_redundancy: float = 0.0
    same_source_overlap: int = 0
    duplicates_rejected: int = 0
    knowledge_categories: Dict[str, int] = field(default_factory=dict)

    # --- concept-completeness reporting ---
    # "concept-driven" only when concepts were actually supplied. With an empty
    # concept list the concept term contributes exactly nothing (it carries the
    # largest single weight), so calling that run concept-driven is a false
    # claim — the caller needs to be able to tell the two apart and say so.
    concept_signal: str = "unavailable"     # "available" | "unavailable"
    # Concept occurrences that were rejected because the complete occurrence did
    # not fit the remaining budget. Recorded rather than silently truncated.
    concepts_omitted_for_budget: List[str] = field(default_factory=list)
    # Occurrences kept whole because a candidate inside them was selected.
    concepts_completed: List[str] = field(default_factory=list)
    knowledge_units_covered: List[str] = field(default_factory=list)
    useful_fill_ratio: float = 0.0
    early_stop_reason: Optional[str] = None

    @property
    def selected_duration(self) -> float:
        """Compatibility alias used by diagnostics written before total_duration."""
        return self.total_duration


# How many temporal bins the timeline is divided into for the coverage term.
# 10 gives deciles, which is also what the reporting metrics use.
DEFAULT_BINS = 10

# A segment may exceed the remaining budget by this fraction and still be taken,
# rather than being truncated. Preserving a complete thought beats hitting an
# exact second — a hard requirement of this project.
OVERSHOOT_TOLERANCE = 0.08

# Share of the temporal-coverage reward a zero-value segment still receives.
# 0 would make coverage useless on a uniform video (min-max normalisation puts
# the weakest segment at exactly 0); 1 restores the quota behaviour this gate
# exists to prevent.
COVERAGE_VALUE_FLOOR = 0.25

# Only occurrences of concepts at least this important are protected from being
# shown as a fragment. Protecting every concept would put nearly every segment
# into some block and make the selection rigid; protecting none reproduces the
# reported bug, where an important discussion appeared half-shown.
CONCEPT_PROTECT_MIN_IMPORTANCE = 0.45

# An occurrence window is only worth protecting if it is a discussion rather
# than a passing mention. Below this the "complete explanation" is a single
# clause and the segment containing it already holds all of it.
CONCEPT_PROTECT_MIN_SECONDS = 8.0

# A segment joins a concept occurrence only if it genuinely participates in it:
# either a real share of the SEGMENT lies inside the window, or the segment
# carries a real share of the WINDOW. Without this an occurrence ending 0.1s
# into the next segment dragged that whole segment in, and the reel then showed
# a 0.1-second sliver of a topic — the exact "1 second of a concept" artifact
# this module must never produce.
UNIT_MIN_OVERLAP_RATIO = 0.20

# A sub-thought must be a usable clip in its own right. Shorter than this it is
# a scrap regardless of where its boundaries fall.
SUBTHOUGHT_MIN_SECONDS = 15.0

# Segments are emitted by semantic_segmenter at detected topic boundaries and
# carry a completeness score. A run only qualifies as an independently
# meaningful sub-thought when every segment in it is itself a complete thought.
SUBTHOUGHT_MIN_COMPLETENESS = 0.5


@dataclass
class CandidateUnit:
    """
    A complete, independently meaningful span, ready for the optimizer.

    The optimizer never invents a boundary: it chooses between whole units
    built here, and every unit is a contiguous run of whole semantic segments.
    That is what makes "no partial concepts" structural rather than a scoring
    preference.

    unit_type:
        "concept"    — the full occurrence of a concept
        "subthought" — a self-contained part of that occurrence, selectable on
                       its own when the full occurrence will not fit
    """
    indices: frozenset
    start_time: float
    end_time: float
    duration: float
    text: str
    parent_concept: str
    importance_score: float
    semantic_completeness_score: float
    unit_type: str
    naturally_bounded: bool
    video_id: str = ""


def _concept_windows(concept, segments: Sequence) -> List[Tuple[str, float, float]]:
    """Return valid source-qualified windows for a concept.

    Legacy two-number timestamps are safe only when every candidate belongs to
    one source. In a multi-video pool there is no honest way to infer which
    source owns such a timestamp, so they are ignored instead of matching every
    video at the same clock position.
    """
    windows: List[Tuple[str, float, float]] = []
    occurrences = getattr(concept, "occurrences", None) or []
    for occurrence in occurrences:
        try:
            if isinstance(occurrence, dict):
                video_id = str(occurrence.get("video_id") or "")
                start = float(occurrence["start"])
                end = float(occurrence["end"])
            else:
                video_id = str(getattr(occurrence, "video_id", "") or "")
                start = float(occurrence.start)
                end = float(occurrence.end)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if video_id and end > start >= 0:
            windows.append((video_id, start, end))
    if windows:
        return windows

    source_ids = {
        str(getattr(segment, "video_id", "") or "")
        for segment in segments
        if getattr(segment, "video_id", "")
    }
    single_source = next(iter(source_ids)) if len(source_ids) == 1 else ""
    for window in (getattr(concept, "timestamps", []) or []):
        try:
            if len(window) == 3 and isinstance(window[0], str):
                video_id, start, end = str(window[0]), float(window[1]), float(window[2])
            elif single_source:
                video_id, start, end = single_source, float(window[0]), float(window[1])
            else:
                continue
        except (TypeError, IndexError, ValueError):
            continue
        if video_id and end > start >= 0:
            windows.append((video_id, start, end))
    return windows


def _make_unit(segments, idx_run, concept_name, importance, unit_type) -> CandidateUnit:
    members = [segments[i] for i in idx_run]
    completeness = [float(getattr(s, "completeness", 1.0)) for s in members]
    vid = getattr(members[0], "video_id", "") if members else ""
    return CandidateUnit(
        indices=frozenset(idx_run),
        start_time=float(min(s.start_time for s in members)),
        end_time=float(max(s.end_time for s in members)),
        duration=float(sum(float(getattr(s, "duration", 0.0)) for s in members)),
        text=" ".join(str(getattr(s, "text", "") or "") for s in members).strip(),
        parent_concept=concept_name,
        importance_score=float(importance),
        semantic_completeness_score=float(sum(completeness) / max(len(completeness), 1)),
        unit_type=unit_type,
        # Every boundary here is one semantic_segmenter detected; units are
        # unions of whole segments, so no unit can start or end mid-thought.
        naturally_bounded=True,
        video_id=vid,
    )


def build_candidate_units(
    segments: Sequence,
    concepts: Sequence,
    min_importance: float = CONCEPT_PROTECT_MIN_IMPORTANCE,
    min_seconds: float = CONCEPT_PROTECT_MIN_SECONDS,
) -> List[CandidateUnit]:
    """
    Decompose concept occurrences into complete selectable units.

    For each occurrence of an important concept this yields:

      * one "concept" unit — the whole explanation, and
      * every contiguous sub-run of it that stands on its own, as
        "subthought" units.

    A large topic is therefore NOT one indivisible block. A lecture segment on
    neural networks that runs 02:00-08:00 offers the full six minutes, and also
    the forward-propagation explanation at 02:50-04:20 on its own, so a
    two-minute budget can take a complete sub-explanation instead of either
    truncating the topic or dropping it entirely.

    Sub-runs are built from whole segments only, and segments are emitted at
    boundaries semantic_segmenter detected — so a sub-thought can never begin
    or end mid-sentence or mid-thought. Selection between these units happens
    in select_segments; this function only enumerates what is legal to pick.
    """
    units: List[CandidateUnit] = []
    if not len(concepts) or not segments:
        return units

    starts = np.asarray([float(getattr(s, "start_time", 0.0)) for s in segments])
    ends = np.asarray([float(getattr(s, "end_time", 0.0)) for s in segments])
    durs = np.maximum(ends - starts, 1e-6)

    seen: set = set()

    for concept in concepts:
        importance = float(getattr(concept, "importance", 0.0))
        if importance < min_importance:
            continue
        name = str(getattr(concept, "name", "") or "")

        windows = _concept_windows(concept, segments)

        for (occ_vid, w_start, w_end) in windows:
            w_len = w_end - w_start
            if w_len < min_seconds:
                continue

            # Cross-source isolation: only segments from the same video can match
            vid_mask = np.asarray(
                [getattr(s, "video_id", "") == occ_vid for s in segments],
                dtype=bool,
            )

            overlap = np.minimum(ends, w_end) - np.maximum(starts, w_start)
            overlap = np.where(vid_mask, overlap, 0.0)
            # Participates if a real share of the segment is inside the window,
            # or the segment covers a real share of the window.
            share_of_segment = overlap / durs
            share_of_window = overlap / max(w_len, 1e-6)
            hit = np.nonzero(
                (overlap > 0)
                & ((share_of_segment >= UNIT_MIN_OVERLAP_RATIO)
                   | (share_of_window >= UNIT_MIN_OVERLAP_RATIO))
            )[0]
            if hit.size == 0:
                continue

            run = sorted(int(i) for i in hit)
            # Only a contiguous run within the SAME video is one explanation; a gap or different video means two.
            groups, current = [], [run[0]]
            for prev, nxt in zip(run, run[1:]):
                if nxt == prev + 1 and getattr(segments[nxt], "video_id", "") == getattr(segments[prev], "video_id", ""):
                    current.append(nxt)
                else:
                    groups.append(current)
                    current = [nxt]
            groups.append(current)

            for group in groups:
                full_key = ("concept", frozenset(group))
                if full_key not in seen:
                    seen.add(full_key)
                    units.append(_make_unit(segments, group, name, importance, "concept"))

                if len(group) < 2:
                    continue    # a single segment has no proper sub-run
                # Proper contiguous sub-runs, each judged on its own merits.
                for a in range(len(group)):
                    for b in range(a, len(group)):
                        if a == 0 and b == len(group) - 1:
                            continue          # that is the full unit
                        sub = group[a:b + 1]
                        span = sum(float(durs[i]) for i in sub)
                        if span < SUBTHOUGHT_MIN_SECONDS:
                            continue
                        if any(float(getattr(segments[i], "completeness", 1.0))
                               < SUBTHOUGHT_MIN_COMPLETENESS for i in sub):
                            continue          # not self-contained
                        key = ("subthought", frozenset(sub))
                        if key in seen:
                            continue
                        seen.add(key)
                        units.append(
                            _make_unit(segments, sub, name, importance, "subthought")
                        )

    return units


def build_concept_blocks(
    segments: Sequence,
    concepts: Sequence,
    min_importance: float = CONCEPT_PROTECT_MIN_IMPORTANCE,
    min_seconds: float = CONCEPT_PROTECT_MIN_SECONDS,
) -> List[Dict]:
    """
    Full concept occurrences only, in the older dict shape.

    Retained for reporting and for the "source fits inside budget" fast path,
    where nothing is budget-rejected and only whole occurrences matter.
    """
    return [
        {
            "concept": u.parent_concept,
            "importance": u.importance_score,
            "start": u.start_time,
            "end": u.end_time,
            "indices": u.indices,
        }
        for u in build_candidate_units(segments, concepts, min_importance, min_seconds)
        if u.unit_type == "concept"
    ]


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
        missing = [i for i, vector in enumerate(cached) if vector is None]
        texts = [getattr(segments[i], "text", "") for i in missing]
        try:
            try:
                encoded = np.asarray(embedder.encode(texts, show_progress_bar=False, batch_size=32))
            except TypeError:
                encoded = np.asarray(embedder.encode(texts))
        except Exception as exc:
            print(f"[Selector] Embedding failed ({exc}) — semantic/redundancy terms disabled")
            return None
        for idx, vec in zip(missing, encoded):
            cached[idx] = vec
            try:
                segments[idx].embedding = vec
            except Exception:
                pass
        matrix = np.asarray(cached, dtype=float)

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

    # Aggregate duration across independent source timelines. Overlaying every
    # source at t=0 would make two distinct occurrences look like one.
    source_ends: Dict[str, float] = {}
    for segment in segments:
        source_id = str(getattr(segment, "video_id", "") or "")
        source_ends[source_id] = max(
            source_ends.get(source_id, 0.0),
            float(getattr(segment, "end_time", 0.0)),
        )
    timeline = sum(source_ends.values()) or 1.0

    # --- temporal grounding, weighted by how localised the concept is ---
    #
    # The locality weight is not a refinement, it is the difference between this
    # term working and being a constant. Grounding asks "was this concept being
    # discussed here?", which only carries information if the concept is
    # discussed in SOME places and not others. Measured on a 75-minute lecture,
    # the TF-IDF concept "learning" spanned 93.8% of the runtime and "learn"
    # 98.9%, so every segment sat inside one of their windows and every entry in
    # this matrix came out at exactly 1.000 — the highest-weighted term in the
    # whole objective contributing nothing to the ranking.
    #
    # Scaling by (1 - covered fraction) fixes that at the source: a concept
    # covering 94% of the video grounds at 0.06, a concept covering 7% grounds
    # at 0.93, and the semantic similarity below takes over for the broad ones.
    localities = []
    concept_windows: List[List[Tuple[str, float, float]]] = []
    for concept in concepts:
        windows = _concept_windows(concept, segments)

        concept_windows.append(windows)

        covered = 0.0
        for source_id in {window[0] for window in windows}:
            merged: List[List[float]] = []
            source_windows = sorted(
                (window for window in windows if window[0] == source_id),
                key=lambda window: window[1],
            )
            for _, c_start, c_end in source_windows:
                if merged and c_start <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], c_end)
                else:
                    merged.append([c_start, c_end])
            covered += sum(b - a for a, b in merged)
        localities.append(1.0 - min(covered / timeline, 1.0))

    for i, seg in enumerate(segments):
        s_vid = getattr(seg, "video_id", "")
        s_start = float(getattr(seg, "start_time", 0.0))
        s_end = float(getattr(seg, "end_time", 0.0))
        s_span = max(s_end - s_start, 1e-6)
        for j, concept in enumerate(concepts):
            best = 0.0
            for (c_vid, c_start, c_end) in concept_windows[j]:
                # Cross-source isolation: If both have video_ids and they don't match, zero credit!
                if c_vid != s_vid:
                    continue
                overlap = min(s_end, float(c_end)) - max(s_start, float(c_start))
                if overlap > 0:
                    best = max(best, min(1.0, overlap / s_span))
            affinity[i, j] = best * localities[j]

    # --- semantic similarity ---
    concept_vectors = _concept_vectors(concepts, embedder)
    if segment_vectors is not None and concept_vectors is not None:
        if segment_vectors.shape[1] != concept_vectors.shape[1]:
            lexical = np.zeros((n, m), dtype=float)
            for i, seg in enumerate(segments):
                for j, concept in enumerate(concepts):
                    lexical[i, j] = _lexical_overlap(seg.text, f"{concept.name} {getattr(concept, 'reason', '')}")
            affinity = np.maximum(affinity, lexical)
        else:
            cosine = segment_vectors @ concept_vectors.T
            # A global min/max manufactured strong matches for unrelated pairs:
            # whichever random pair was largest became 1.0. Keep absolute cosine
            # meaning instead; below 0.55 is insufficient semantic evidence.
            sims = np.clip((cosine - 0.55) / 0.45, 0.0, 1.0)
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

        for concept, vector in zip(concepts, matrix):
            concept.embedding = vector

    if matrix.ndim != 2 or matrix.shape[0] != len(concepts):
        return None
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms < 1e-9, 1e-9, norms)


def _lexical_overlap(text_a: str, text_b: str) -> float:
    tokens_a = set(re.findall(r"\b[\w-]{3,}\b", (text_a or "").casefold()))
    tokens_b = set(re.findall(r"\b[\w-]{3,}\b", (text_b or "").casefold()))
    if not tokens_a and not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / max(len(tokens_a | tokens_b), 1)


def _semantic_similarity(seg_a, seg_b) -> float:
    """Generic semantic relation score for cross-video comparisons.

    Prefer the actual embedding cosine when both segments carry vectors;
    otherwise fall back to lexical overlap so the selector still behaves on
    text-only inputs without a model.
    """
    a_vec = getattr(seg_a, "embedding", None)
    b_vec = getattr(seg_b, "embedding", None)
    if a_vec is not None and b_vec is not None:
        try:
            a = np.asarray(a_vec, dtype=float).reshape(-1)
            b = np.asarray(b_vec, dtype=float).reshape(-1)
            denom = float(np.linalg.norm(a) * np.linalg.norm(b))
            if denom > 1e-9:
                return float(np.clip(np.dot(a, b) / denom, -1.0, 1.0))
        except Exception:
            pass
    return _lexical_overlap(getattr(seg_a, "text", ""), getattr(seg_b, "text", ""))


def _same_underlying_knowledge(seg_a, seg_b) -> bool:
    """True when two segments from different sources are essentially the same fact.

    The rule is deliberately generic: same knowledge can be expressed with a
    different surface form, so semantic embedding similarity is the primary
    signal and unit overlap is an additional confirmation.
    """
    if getattr(seg_a, "video_id", "") == getattr(seg_b, "video_id", ""):
        return False
    overlap = set(getattr(seg_a, "knowledge_unit_scores", {}) or {}) & set(getattr(seg_b, "knowledge_unit_scores", {}) or {})
    semantic = _semantic_similarity(seg_a, seg_b)
    if semantic >= 0.85:
        return True
    if overlap and semantic >= 0.45:
        return True
    return False


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
    total_duration: float | dict = 0.0,
    n_bins: int = DEFAULT_BINS,
    query_embedding: Optional[np.ndarray] = None,
    stage_timings: Optional[Dict[str, float]] = None,
    knowledge_units: Sequence = (),
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
        query_embedding: optional query reference vector to prioritize search keywords

    Returns:
        SelectionResult with segments in chronological order and a per-pick
        trace of why each was chosen.
    """
    segments = list(segments)
    weights = weights or SelectionWeights.from_settings()

    result = SelectionResult(budget=float(budget_seconds))
    timings = stage_timings if stage_timings is not None else {}
    selection_started = perf_counter()
    multi_source = len({getattr(s, "video_id", "") for s in segments}) > 1
    # Set before any early return: every exit path must report honestly
    # whether the concept term actually participated in this run.
    result.concept_signal = "available" if len(concepts) else "unavailable"
    if not segments or budget_seconds <= 0:
        return result

    # Requested summary longer than the source: take everything, in order.
    # Overlaps are still dropped — showing the viewer the same footage twice is
    # wrong whether or not there is budget left to spare.
    total_available = sum(float(getattr(s, "duration", 0.0)) for s in segments)
    if total_available <= budget_seconds and not multi_source:
        vectors = _embed_segments(segments, embedder=embedder) if concepts else None
        affinity = build_concept_affinity(segments, concepts, vectors, embedder=embedder)
        for seg, scores in zip(segments, affinity):
            seg.concept_scores = {getattr(c, "name", ""): float(score)
                                  for c, score in zip(concepts, scores) if score >= 0.35}
        ordered = sorted(segments, key=lambda s: (getattr(s, "video_id", ""), s.start_time))
        kept: List = []
        for seg in ordered:
            if any(_overlaps(seg, other) for other in kept):
                continue
            kept.append(seg)
        result.segments = kept
        result.total_duration = sum(float(getattr(s, "duration", 0.0)) for s in kept)
        result.useful_fill_ratio = result.total_duration / max(float(budget_seconds), 1e-6)
        result.early_stop_reason = "all_available_content_selected"
        result.knowledge_units_covered = sorted({
            unit_id
            for segment in kept
            for unit_id, evidence in getattr(segment, "knowledge_unit_scores", {}).items()
            if float(evidence) >= UNIT_COVERED_THRESHOLD
        })
        result.concepts_covered = list(dict.fromkeys(c for s in kept for c in s.concept_scores))
        # Nothing was budget-rejected on this path, so every occurrence whose
        # segments all survived the overlap filter is present in full.
        kept_ids = {id(s) for s in kept}
        for block in build_concept_blocks(segments, concepts):
            if all(id(segments[i]) in kept_ids for i in block["indices"]):
                name = block["concept"]
                if name and name not in result.concepts_completed:
                    result.concepts_completed.append(name)
        print(f"[Selector] Source ({total_available:.0f}s) fits inside budget "
              f"({budget_seconds:.0f}s) — keeping {len(kept)}/{len(ordered)} segments")
        timings["selection"] = perf_counter() - selection_started
        return result

    if isinstance(total_duration, dict):
        sum_duration = sum(total_duration.values())
    else:
        if total_duration <= 0:
            total_duration = max(float(getattr(s, "end_time", 0.0)) for s in segments) if segments else 0.0
        sum_duration = max(total_duration, 1.0)
    
    capacity = (np.repeat([max(v, 1.0) / n_bins for v in total_duration.values()], n_bins)
                if isinstance(total_duration, dict) else sum_duration / n_bins)

    embedding_started = perf_counter()
    vectors = _embed_segments(segments, embedder=embedder)
    affinity = build_concept_affinity(segments, concepts, vectors, embedder=embedder)
    timings["embedding"] = timings.get("embedding", 0.0) + perf_counter() - embedding_started
    selection_started = perf_counter()
    for seg, scores in zip(segments, affinity):
        seg.concept_scores = {getattr(c, "name", ""): float(score)
                              for c, score in zip(concepts, scores) if score >= 0.35}
    relevance = (
        _relevance_scores(vectors, summary_embedding)
        if vectors is not None
        else np.full(len(segments), 0.5)
    )
    if vectors is not None:
        if query_embedding is not None:
            query_vectors = np.atleast_2d(query_embedding)
            query_vectors = query_vectors / np.maximum(np.linalg.norm(query_vectors, axis=1, keepdims=True), 1e-9)
            q_relevance = np.clip((vectors @ query_vectors.T).max(axis=1), 0.0, 1.0)
            s_relevance = _relevance_scores(vectors, summary_embedding)
            relevance = 0.70 * q_relevance + 0.30 * s_relevance
        else:
            q_relevance = None
            relevance = _relevance_scores(vectors, summary_embedding)
    else:
        q_relevance = None
        relevance = np.full(len(segments), 0.5)

    for idx, segment in enumerate(segments):
        segment.query_relevance = (
            float(q_relevance[idx]) if q_relevance is not None else None
        )

    # --- concept signal quality diagnostic ---
    # Logs how much of the nominal concept weight actually reaches the optimizer.
    # TF-IDF concepts tend to span large fractions of the transcript, so their
    # locality weight (1 - covered_fraction) collapses toward zero, and the
    # effective contribution is far below the configured SELECT_CONCEPT_WEIGHT.
    # This log makes that degradation visible without changing any scores.
    if len(concepts):
        covered_fracs = [
            min(
                sum(float(b) - float(a) for a, b in (getattr(c, "timestamps", None) or []))
                / max(sum_duration, 1.0),
                1.0,
            )
            for c in concepts
        ]
        mean_locality = 1.0 - float(np.mean(covered_fracs))
        mean_affinity = float(affinity.mean()) if affinity.size else 0.0
        concept_source = (
            "llm"
            if any(getattr(c, "source", "") == "llm" for c in concepts)
            else "tfidf"
        )
        eff_weight = weights.concept * mean_affinity
        print(
            f"[Selector] Concept signal: {len(concepts)} concepts ({concept_source}), "
            f"mean_locality={mean_locality:.2f}, mean_affinity={mean_affinity:.2f} "
            f"→ effective_concept_weight={eff_weight:.3f} "
            f"(nominal {weights.concept:.2f}"
            + (
                " — TF-IDF concepts are broad; enable ENABLE_CONCEPT_LLM for stronger signal"
                if concept_source == "tfidf" and mean_locality < 0.40
                else ""
            )
            + ")"
        )

    concept_importance = np.asarray(
        [float(getattr(c, "importance", 0.0)) for c in concepts], dtype=float
    )
    if query_embedding is not None and len(concepts):
        concept_vectors = _concept_vectors(concepts, embedder)
        if concept_vectors is not None:
            q = np.atleast_2d(query_embedding)
            q = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-9)
            concept_importance *= 1.0 + np.clip((concept_vectors @ q.T).max(axis=1), 0.0, 1.0)
    coherence = np.asarray(
        [
            0.5 * float(getattr(s, "completeness", 1.0))
            + 0.5 * float(getattr(s, "boundary_confidence", 0.0))
            for s in segments
        ],
        dtype=float,
    )
    durations = np.asarray([max(float(getattr(s, "duration", 0.0)), 1e-6) for s in segments])

    # Cheap explanation-quality features. They only influence competition among
    # clips that cover the same knowledge unit; no additional model is loaded.
    information_density = np.asarray(
        [float(getattr(s, "information_density", 0.0)) for s in segments], dtype=float
    )
    filler_penalty = np.asarray(
        [float(getattr(s, "filler_penalty", 0.0)) for s in segments], dtype=float
    )
    boundary_quality = np.asarray(
        [float(getattr(s, "boundary_confidence", 0.0)) for s in segments], dtype=float
    )
    completeness_quality = np.asarray(
        [float(getattr(s, "completeness", 1.0)) for s in segments], dtype=float
    )
    duration_efficiency = np.clip(45.0 / np.maximum(durations, 45.0), 0.0, 1.0)
    explanation_quality = np.clip(
        0.30 * completeness_quality
        + 0.20 * boundary_quality
        + 0.20 * information_density
        + 0.15 * duration_efficiency
        + 0.15 * (1.0 - filler_penalty),
        0.0,
        1.0,
    )

    unit_importance = {
        str(getattr(unit, "unit_id", "")): float(getattr(unit, "importance", 0.0))
        for unit in (knowledge_units or ())
        if getattr(unit, "unit_id", "")
    }
    essential_units = {
        str(getattr(unit, "unit_id", ""))
        for unit in (knowledge_units or ())
        if getattr(unit, "essential", False)
    }
    best_unit_coverage = {unit_id: 0.0 for unit_id in unit_importance}

    # Normalising the duration penalty by the longest candidate keeps it in the
    # same [0, 1] range as every other term, so the weights stay comparable.
    longest = float(durations.max())

    # --- concept completeness ---
    # A segment that participates in an important concept can only be taken as
    # part of a COMPLETE unit: the whole occurrence, or one of its
    # self-contained sub-thoughts. Units are enumerated up front, so the
    # optimizer only ever picks between complete things and never invents a
    # boundary of its own. Segments in no unit are unconstrained, so the reel
    # can always still be filled.
    units = build_candidate_units(segments, concepts) if len(concepts) else []
    units_of: Dict[int, List[int]] = {}
    for u_id, unit in enumerate(units):
        for idx in unit.indices:
            units_of.setdefault(idx, []).append(u_id)
    # Largest first: prefer the fullest explanation that still fits, and fall
    # back to a smaller complete sub-thought only when it does not.
    for idx in units_of:
        units_of[idx].sort(key=lambda u_id: units[u_id].duration, reverse=True)
    if units:
        n_concept = sum(1 for u in units if u.unit_type == "concept")
        print(f"[Selector] {n_concept} complete concept occurrence(s), "
              f"{len(units) - n_concept} self-contained sub-thought(s) available")

    def commitment_for(idx: int, already: set, budget_left: float):
        """
        The complete unit to take in order to include `idx`, or None if no
        complete unit containing it fits the remaining budget.

        Returning None is the "reject rather than fragment" rule: there is no
        option to take part of a unit, so a candidate that cannot be completed
        is simply not on offer.
        """
        if idx not in units_of:
            need = frozenset({idx})
            fits = float(durations[idx]) <= budget_left * (1.0 + OVERSHOOT_TOLERANCE)
            return need if fits else None

        for u_id in units_of[idx]:
            members = frozenset(units[u_id].indices)
            # A unit is only offerable while every one of its segments is
            # still obtainable — already selected, or still a candidate.
            # Segments are dropped from `remaining` when they overlap an
            # earlier pick (adjacent semantic segments do overlap by a second
            # or two), and without this check such a drop would punch a hole
            # in the middle of a unit.
            if not members <= (already | remaining):
                continue
            need = _close_gaps(members - already, already)
            if not need:
                continue
            span = float(sum(durations[i] for i in need))
            if span <= budget_left * (1.0 + OVERSHOOT_TOLERANCE):
                return need
        return None

    def _close_gaps(need: frozenset, already: set):
        """
        Extend `need` until no unit is left holding a gapped subset.

        Concept occurrences overlap, so a segment can belong to several units.
        Completing unit A can leave unit B holding its first and last segment
        with the middle missing — each individual pick legal, the result still
        a topic that jumps. Observed on a real English video: a unit spanning
        5:32-9:07 held 5:32-6:06 and 7:53-9:07 with two segments missing
        between them.

        Any in-between segments are pulled in so every unit's selected subset
        stays contiguous. Returns None when a gap cannot be closed because the
        missing segment is no longer available, in which case the caller moves
        on to a smaller unit rather than accepting the hole.
        """
        total = set(already) | set(need)
        changed = True
        while changed:
            changed = False
            for unit in units:
                inside = sorted(unit.indices & total)
                if len(inside) < 2:
                    continue
                missing = {
                    i for i in range(inside[0], inside[-1] + 1)
                    if i in unit.indices and i not in total
                }
                if not missing:
                    continue
                if not missing <= remaining:
                    return None       # gap is unclosable
                total |= missing
                changed = True
        return frozenset(total) - set(already)

    # --- mutable state of the greedy run ---
    selected: List[int] = []
    remaining = set(range(len(segments)))
    max_selected_similarity = np.zeros(len(segments), dtype=float)
    duplicate_rejections = set()
    # best_affinity[j] = how well the BEST already-selected segment covers concept j.
    best_affinity = np.zeros(len(concepts), dtype=float)
    bin_seconds = np.zeros(n_bins * (len(total_duration) if isinstance(total_duration, dict) else 1), dtype=float)
    total_selected = 0.0

    def bin_gain(indices) -> float:
        """
        Concave temporal-coverage gain from adding every segment in `indices`.

        By normalising against bin capacity and taking the mean across bins,
        the total coverage value is strictly bounded to [0, 1] (1.0 = 100% of
        the video covered). Marginal gain is bounded to [0, 1] and scales
        correctly with other metrics.
        """
        
        def coverage_value(bins):
            # Safe divide: capacity is > 0 since total_duration >= 1.0
            return float(np.mean(np.sqrt(bins / capacity)))
            
        before = coverage_value(bin_seconds)
        trial = bin_seconds.copy()
        for i in indices:
            _accumulate_bins(trial, segments[i], total_duration, n_bins)
        return coverage_value(trial) - before

    # Normaliser for the temporal term.
    #
    # The obvious choice — the gain of filling one entire empty bin — is wrong,
    # and measurably so. A bin of a 25-minute video is 150 seconds, while a
    # segment is 20-90, so a segment landing in a virgin bin would score at most
    # sqrt(30)/sqrt(150) = 0.45 while the relevance term still spans the full
    # [0, 1]. The coverage signal would be permanently outranked by relevance,
    # which is exactly the bias being fixed. Normalising by a TYPICAL segment
    # instead puts "first content in this region" at ~1.0 and "more of what is
    # already here" well below it, so the two terms are finally comparable.
    typical = float(np.median(durations)) or 1.0
    max_bin_gain = float(np.sqrt(typical)) or 1.0

    while remaining:
        budget_left = budget_seconds - total_selected
        if budget_left <= 0:
            break

        # Same-source overlap is never acceptable in the final reel. This must be
        # rejected before a candidate is considered for a pick, not after the fact.
        for idx in list(remaining):
            seg = segments[idx]
            same_vid_selected = [segments[i] for i in selected if getattr(segments[i], "video_id", "") == getattr(seg, "video_id", "")]
            if any(_overlaps(seg, selected_seg) for selected_seg in same_vid_selected):
                remaining.discard(idx)

        best_idx = -1
        best_density = -np.inf
        best_parts: Dict[str, float] = {}
        best_commitment: frozenset = frozenset()

        selected_set = set(selected)
        for idx in list(remaining):
            # The only thing on offer is a COMPLETE unit containing idx: the
            # full occurrence if it fits, else its largest self-contained
            # sub-thought that does. None means nothing complete fits, so the
            # candidate is rejected rather than truncated — and dropped for
            # good, since the budget only ever shrinks.
            commitment = commitment_for(idx, selected_set, budget_left)
            if commitment is None:
                remaining.discard(idx)
                for u_id in units_of.get(idx, ()):
                    name = units[u_id].parent_concept
                    if name and name not in result.concepts_omitted_for_budget:
                        result.concepts_omitted_for_budget.append(name)
                continue
            dur = float(sum(durations[i] for i in commitment))

            # Every term below is evaluated over the full commitment, because
            # the commitment is what actually gets added to the reel. For a
            # single-segment commitment — every candidate when no concepts are
            # supplied, and most candidates when they are — each of these
            # reduces exactly to the original per-segment expression, so
            # behaviour on the existing path is unchanged.
            members = sorted(commitment)

            if len(concepts):
                # Facility location: gain only from concepts this commitment
                # covers BETTER than anything already selected. Diminishing by
                # nature. The group's affinity is its best member's.
                group_affinity = affinity[members].max(axis=0)
                gains = np.maximum(group_affinity - best_affinity, 0.0)
                concept_gain = float((gains * concept_importance).sum())
                concept_gain /= max(concept_importance.sum(), 1e-6)
            else:
                concept_gain = 0.0

            # Knowledge-unit novelty is the primary meaning of "new useful
            # information". Evidence is quality-adjusted before facility-location
            # gain, so a clear complete 45-second explanation beats a longer,
            # filler-heavy explanation of the same unit.
            group_unit_coverage: Dict[str, float] = {}
            for member in members:
                for unit_id, evidence in getattr(
                    segments[member], "knowledge_unit_scores", {}
                ).items():
                    quality_adjusted = float(evidence) * float(explanation_quality[member])
                    group_unit_coverage[unit_id] = max(
                        group_unit_coverage.get(unit_id, 0.0), quality_adjusted
                    )
            unit_gain = 0.0
            if group_unit_coverage:
                numerator = sum(
                    max(score - best_unit_coverage.get(unit_id, 0.0), 0.0)
                    * max(unit_importance.get(unit_id, 0.5), 0.1)
                    for unit_id, score in group_unit_coverage.items()
                )
                denominator = sum(max(value, 0.1) for value in unit_importance.values())
                unit_gain = numerator / max(denominator, 1e-6)

            # Duration-weighted means: a long segment should carry more of the
            # group's relevance/coherence than a short one.
            member_durs = np.asarray([durations[i] for i in members], dtype=float)
            weight_share = member_durs / max(member_durs.sum(), 1e-6)
            group_relevance = float(np.dot(weight_share, relevance[members]))
            group_coherence = float(np.dot(weight_share, coherence[members]))

            # Temporal coverage is GATED by the segment's own value. Rewarding an
            # empty region unconditionally is how a coverage term turns into a
            # quota: a segment of dead air scores full coverage credit purely for
            # being somewhere nothing else is, and the reel fills up with silence
            # and ad reads. The requirement is to reward meaningful
            # representation from different parts of the timeline WHEN VALUABLE
            # CONTENT EXISTS there — so the reward is scaled by how much value
            # the segment actually carries.
            #
            # The floor keeps the term alive for merely-average material: without
            # it, min-max normalised relevance hands the weakest segment of an
            # otherwise-uniform video a coverage credit of exactly zero, and a
            # late region containing only average content would be starved again.
            content_value = group_relevance
            if len(concepts):
                content_value = max(content_value, float(affinity[members].max()))
            gated = COVERAGE_VALUE_FLOOR + (1.0 - COVERAGE_VALUE_FLOOR) * content_value
            # --- Phase 2C Normalization ---
            # Extensive components (concept, coverage) naturally return tiny marginal gains 
            # because they represent 1/N of the global objective. To put them on a comparable 
            # scale [0, 1] as intensive components (semantic, coherence), we scale them up 
            # by the expected number of clips needed to fill the budget.
            N_expected = max(budget_seconds / typical, 1.0)
            
            concept_scaled = concept_gain * N_expected
            unit_scaled = unit_gain * N_expected
            
            # The coverage function `bin_gain` averages across bins, so its marginal value is 
            # essentially `(1/N_bins) * sqrt(duration / capacity)`. We scale it so a typical 
            # clip returns ~1.0. 
            temporal_scaled = bin_gain(members) * N_expected * gated

            if vectors is not None and selected:
                redundancy = float(max_selected_similarity[members].max())
            else:
                redundancy = 0.0

            has_meaningful_concept = bool(len(concepts)) and bool(
                np.any(affinity[members].max(axis=0) >= 0.35)
            )
            best_group_unit_score = max(group_unit_coverage.values(), default=0.0)
            meaningful_unit = bool(group_unit_coverage) and best_group_unit_score >= 0.55
            candidate_filler = float(max(float(getattr(segments[i], "filler_penalty", 0.0)) for i in members))
            if candidate_filler >= 0.35 and not has_meaningful_concept and not meaningful_unit:
                duplicate_rejections.update(members)
                continue

            # Near-identical cross-source explanations must not be forced in by
            # the minimum-fill rule. Require every member to be redundant so a
            # complete unit containing new evidence can still compete.
            if multi_source and selected and vectors is not None:
                if any(
                    other.video_id != segments[best_idx].video_id and _same_underlying_knowledge(other, segments[best_idx])
                    for other in [segments[i] for i in selected]
                ):
                    duplicate_rejections.update(members)
                    continue
                if np.all(max_selected_similarity[members] >= 0.96):
                    duplicate_rejections.update(members)
                    continue

            density = 0.0
            if dur > 0:
                gain = (
                    weights.concept * (unit_scaled if unit_importance else concept_scaled)
                    + weights.semantic * group_relevance
                    + weights.coverage * temporal_scaled
                    + weights.coherence * group_coherence
                    - weights.redundancy * redundancy
                    - weights.duration_penalty * (dur / longest)
                )
                density = gain / dur

            if density > best_density:
                best_density = density
                best_idx = idx
                best_commitment = commitment
                best_parts = {
                    "concept": round(concept_scaled, 4),
                    "knowledge_unit": round(unit_scaled, 4),
                    "semantic": round(group_relevance, 4),
                    "query_relevance": round(float(np.dot(weight_share, q_relevance[members])), 4) if q_relevance is not None else None,
                    "coverage": round(temporal_scaled, 4),
                    "coherence": round(group_coherence, 4),
                    "redundancy": round(redundancy, 4),
                    # Weighted contributions (what actually entered the gain formula)
                    "concept_weighted":   round(weights.concept * concept_scaled, 4),
                    "knowledge_unit_weighted": round(weights.concept * unit_scaled, 4),
                    "semantic_weighted":  round(weights.semantic * group_relevance, 4),
                    "coverage_weighted":  round(weights.coverage * temporal_scaled, 4),
                    "coherence_weighted": round(weights.coherence * group_coherence, 4),
                    "redundancy_penalty": round(weights.redundancy * redundancy, 4),
                    "duration_penalty":   round(weights.duration_penalty * (dur / longest), 4),
                    # Summary
                    "gain": round(gain, 4),
                    "gain_per_second": round(density, 6),
                    "committed_segments": len(commitment),
                    "knowledge_units": sorted(group_unit_coverage),
                }

        if best_idx < 0:
            if selected and remaining:
                result.early_stop_reason = "remaining_marginal_knowledge_gain_below_threshold"
                print(
                    f"[Selector] Useful early stop at {total_selected:.0f}s/"
                    f"{budget_seconds:.0f}s — remaining clips add no material knowledge unit"
                )
            break

        committed = sorted(best_commitment)
        same_video_selected = [segments[i] for i in selected if getattr(segments[i], "video_id", "") == getattr(segments[best_idx], "video_id", "")]
        if any(_overlaps(segments[i], seg) for i in committed for seg in same_video_selected):
            remaining.discard(best_idx)
            continue

        if unit_importance and selected:
            if best_parts.get("knowledge_unit", 0.0) <= MIN_MARGINAL_UNIT_GAIN:
                result.early_stop_reason = "remaining_marginal_knowledge_gain_below_threshold"
                print(
                    f"[Selector] Useful early stop at {total_selected:.0f}s/"
                    f"{budget_seconds:.0f}s — remaining clips add no material knowledge unit"
                )
                break

        # A non-positive best gain means everything left is redundant filler, and
        # taking it makes the summary worse rather than longer. Stopping is the
        # right call — but ONLY once the reel is substantially built.
        #
        # Without the fill guard this is a trap: on dense material where every
        # segment resembles every other, the penalty term drives the best gain
        # negative after a handful of picks and the job ships a near-empty reel.
        # That is not hypothetical — a real job in this repo returned 49 seconds
        # against a 600-second budget. Below min_budget_fill, the best available
        # segment is taken even at a marginal loss, because a slightly redundant
        # summary of the right length beats a tiny one.
        if best_parts.get("gain", 0.0) <= 0 and selected:
            fill = total_selected / budget_seconds
            if fill >= weights.min_budget_fill:
                result.early_stop_reason = "remaining_total_gain_non_positive"
                print(f"[Selector] Stopping at {total_selected:.0f}s/{budget_seconds:.0f}s "
                      f"({fill:.0%}) — no remaining segment adds positive value")
                break

        # Commit the WHOLE occurrence, not just the winning segment. This is
        # what makes "complete concept or reject" hold: the candidate was
        # already priced and budget-checked as a group above, so taking it
        # partially here would reintroduce the fragment the check prevented.
        seg = segments[best_idx]
        committed = sorted(best_commitment)
        if vectors is not None:
            max_selected_similarity = np.maximum(
                max_selected_similarity,
                np.maximum((vectors @ vectors[committed].T).max(axis=1), 0.0),
            )
        for i in committed:
            selected.append(i)
            remaining.discard(i)
            total_selected += float(durations[i])
            _accumulate_bins(bin_seconds, segments[i], total_duration, n_bins)
        if len(concepts):
            best_affinity = np.maximum(best_affinity, affinity[committed].max(axis=0))
            # Record what was represented, and as what. The unit actually taken
            # is the one whose index set matches the commitment.
            committed_set = frozenset(committed)
            for u_id in units_of.get(best_idx, ()):
                unit = units[u_id]
                if frozenset(unit.indices) != committed_set:
                    continue
                name = unit.parent_concept
                if not name:
                    continue
                label = name if unit.unit_type == "concept" else f"{name} (sub-thought)"
                if label not in result.concepts_completed:
                    result.concepts_completed.append(label)
                break
        if unit_importance:
            for i in committed:
                for unit_id, evidence in getattr(segments[i], "knowledge_unit_scores", {}).items():
                    best_unit_coverage[unit_id] = max(
                        best_unit_coverage.get(unit_id, 0.0),
                        float(evidence) * float(explanation_quality[i]),
                    )

        result.trace.append({
            "video_id": getattr(seg, "video_id", ""),
            "rank": len(selected),
            "start_time": round(float(min(segments[i].start_time for i in committed)), 1),
            "end_time": round(float(max(segments[i].end_time for i in committed)), 1),
            "duration": round(float(sum(durations[i] for i in committed)), 1),
            **best_parts,
        })

        # Per-pick log — one compact line so selection decisions are visible in
        # server logs without scrolling through the full trace dict.
        _seg = segments[best_idx]
        print(
            f"  [Pick #{len(selected):02d}] "
            f"{getattr(_seg, 'video_id', '?')} "
            f"{getattr(_seg, 'start_time', 0):.1f}s–{getattr(_seg, 'end_time', 0):.1f}s "
            f"| gain={best_parts['gain']:+.4f} ({best_parts['gain_per_second']:+.6f}/s) "
            f"| cncpt={best_parts['concept']:.3f}→{best_parts['concept_weighted']:.3f} "
            f"sem={best_parts['semantic']:.3f}→{best_parts['semantic_weighted']:.3f} "
            f"cov={best_parts['coverage']:.3f}→{best_parts['coverage_weighted']:.3f} "
            f"cohr={best_parts['coherence']:.3f}→{best_parts['coherence_weighted']:.3f} "
            f"redund=-{best_parts['redundancy_penalty']:.3f} "
            f"dur_pen=-{best_parts['duration_penalty']:.3f} "
            f"| commits={best_parts['committed_segments']} "
            f"budget_left={budget_seconds - total_selected:.0f}s"
        )

        # Drop anything that overlaps the pick. Overlapping clips would show the
        # viewer the same footage twice.
        for idx in list(remaining):
            if any(_overlaps(segments[idx], segments[i]) for i in committed):
                remaining.discard(idx)

    chosen = [segments[i] for i in selected]
    result.same_source_overlap = 0
    for i in range(len(chosen)):
        for j in range(i + 1, len(chosen)):
            if chosen[i].video_id == chosen[j].video_id and _overlaps(chosen[i], chosen[j]):
                result.same_source_overlap += 1
    timings["selection"] = perf_counter() - selection_started
    ordering_started = perf_counter()
    try:
        from .narrative_sorter import sort_segments
        chosen = sort_segments(chosen, embedder, concept_order=[getattr(c, "name", "") for c in concepts])
        result.segments = chosen
    except Exception as e:
        print(f"[Selector] Narrative sort failed: {e}, falling back")
        chosen.sort(key=lambda s: (getattr(s, "video_id", ""), s.start_time))
    timings["ordering"] = perf_counter() - ordering_started
    result.duplicates_rejected = len(duplicate_rejections - set(selected))

    if vectors is not None and len(segments) > 2:
        nearest = []
        for start in range(0, len(vectors), 256):
            sims = vectors[start:start + 256] @ vectors.T
            sims[np.arange(len(sims)), np.arange(start, start + len(sims))] = -1.0
            nearest.extend(sims.max(axis=1))
        result.baseline_similarity = float(np.clip(np.mean(nearest), 0.0, 1.0))

    chosen_vectors = np.asarray([
        getattr(seg, "embedding", np.zeros(1, dtype=float)) for seg in chosen
    ], dtype=float)
    if chosen_vectors.ndim == 2 and len(chosen_vectors) > 1:
        sims = chosen_vectors @ chosen_vectors.T
        sims = np.clip(sims, 0.0, 1.0)
        np.fill_diagonal(sims, 0.0)
        upper = sims[np.triu_indices(len(chosen), k=1)]
        result.semantic_redundancy = float(np.mean(upper)) if upper.size else 0.0
    else:
        pairwise = []
        for i in range(len(chosen)):
            for j in range(i + 1, len(chosen)):
                pairwise.append(_lexical_overlap(chosen[i].text, chosen[j].text))
        result.semantic_redundancy = float(np.mean(pairwise)) if pairwise else 0.0

    result.knowledge_categories = {}
    for seg in chosen:
        if getattr(seg, "filler_penalty", 0.0) > 0.5 or not getattr(seg, "semantic_knowledge_unit", ""):
            cat = "NOISE/WEAK"
        else:
            same_source = [other for other in chosen if other.video_id == seg.video_id and other is not seg]
            if same_source and any(_overlaps(seg, other) for other in same_source):
                cat = "NOISE/WEAK"
            else:
                cross_video = [other for other in chosen if other.video_id != seg.video_id and other is not seg]
                shared = any(_same_underlying_knowledge(seg, other) for other in cross_video)
                if shared:
                    cat = "SHARED"
                elif any(_semantic_similarity(seg, other) >= 0.35 for other in cross_video):
                    cat = "COMPLEMENTARY"
                else:
                    cat = "UNIQUE"
        seg.semantic_category = cat
        result.knowledge_categories[cat] = result.knowledge_categories.get(cat, 0) + 1

    result.segments = chosen
    result.total_duration = total_selected
    result.useful_fill_ratio = total_selected / max(float(budget_seconds), 1e-6)
    result.knowledge_units_covered = sorted(
        unit_id for unit_id, coverage in best_unit_coverage.items()
        if coverage >= UNIT_COVERED_THRESHOLD
    )
    if len(concepts):
        result.concepts_covered = [
            getattr(c, "name", "")
            for c, cov in zip(concepts, best_affinity)
            if cov >= 0.35
        ]

    print(f"[Selector] {len(chosen)} segments, {total_selected:.0f}s of a "
          f"{budget_seconds:.0f}s budget ({total_selected / budget_seconds * 100:.0f}%), "
          f"{len(result.concepts_covered)}/{len(concepts)} concepts covered")

    # Weighted-contribution summary: shows which scoring term actually drove selection.
    # Format: raw_avg × weight = effective_contribution
    if result.trace:
        _trace_keys = ("concept", "semantic", "coverage", "coherence", "redundancy")
        _avg = {
            k: sum(t.get(k, 0.0) for t in result.trace) / len(result.trace)
            for k in _trace_keys
        }
        w = weights
        print(
            f"[Selector] Avg weighted contributions over {len(result.trace)} picks: "
            f"concept={_avg['concept']:.3f}×{w.concept}={_avg['concept']*w.concept:.3f} | "
            f"semantic={_avg['semantic']:.3f}×{w.semantic}={_avg['semantic']*w.semantic:.3f} | "
            f"coverage={_avg['coverage']:.3f}×{w.coverage}={_avg['coverage']*w.coverage:.3f} | "
            f"coherence={_avg['coherence']:.3f}×{w.coherence}={_avg['coherence']*w.coherence:.3f} | "
            f"redundancy_penalty={_avg['redundancy']:.3f}×{w.redundancy}={_avg['redundancy']*w.redundancy:.3f}"
        )

    return result


def _accumulate_bins(bins: np.ndarray, segment, total_duration, n_bins: int) -> None:
    """Add a segment's seconds into the temporal bins it spans."""
    if isinstance(total_duration, dict):
        vid_duration = total_duration.get(getattr(segment, "video_id", ""), 1.0)
        offset = list(total_duration).index(getattr(segment, "video_id", "")) * n_bins
    else:
        vid_duration = total_duration
        offset = 0
    vid_duration = max(vid_duration, 1.0)
    
    width = vid_duration / n_bins
    start = float(getattr(segment, "start_time", 0.0))
    end = float(getattr(segment, "end_time", 0.0))
    for b in range(n_bins):
        lo, hi = b * width, (b + 1) * width
        overlap = min(end, hi) - max(start, lo)
        if overlap > 0:
            bins[offset + b] += overlap


def _overlaps(a, b, gap: float = 0.0) -> bool:
    """True when two segments from the same video share screen time."""
    if getattr(a, "video_id", "") != getattr(b, "video_id", ""):
        return False
    return not (
        float(a.end_time) + gap <= float(b.start_time)
        or float(a.start_time) >= float(b.end_time) + gap
    )
