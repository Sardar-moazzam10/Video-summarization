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

    value(S) = W_CONCEPT   * concept_coverage(S)              <- facility location
             + W_SEMANTIC  * relevance(S) * (1 - redundancy)  <- MMR-discounted
             + W_COVERAGE  * temporal_coverage(S) * value(S) <- concave, value-gated
             + W_COHERENCE * coherence(S)                     <- modular
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


# The optimizer may only stop early (because nothing left adds value) once the
# reel has reached this fraction of the requested duration. See the guard in
# select_segments() for why an unguarded early stop is dangerous.
# 0.90 caps the shortfall at 10% of the requested duration, which is the
# "approximately respected" tolerance the product asks for, while still leaving
# the escape hatch open for a source whose remaining material is pure filler.
# Overridable via SELECT_MIN_BUDGET_FILL in .env.
MIN_BUDGET_FILL = 0.90

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


def _make_unit(segments, idx_run, concept_name, importance, unit_type) -> CandidateUnit:
    members = [segments[i] for i in idx_run]
    completeness = [float(getattr(s, "completeness", 1.0)) for s in members]
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

        for window in (getattr(concept, "timestamps", []) or []):
            try:
                w_start, w_end = float(window[0]), float(window[1])
            except (TypeError, IndexError, ValueError):
                continue
            w_len = w_end - w_start
            if w_len < min_seconds:
                continue

            overlap = np.minimum(ends, w_end) - np.maximum(starts, w_start)
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
            # Only a contiguous run is one explanation; a gap means two.
            groups, current = [], [run[0]]
            for prev, nxt in zip(run, run[1:]):
                if nxt == prev + 1:
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

    # Timeline length, used to judge how localised each concept is.
    timeline = max((float(getattr(s, "end_time", 0.0)) for s in segments), default=0.0) or 1.0

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
    for concept in concepts:
        merged: List[List[float]] = []
        for (c_start, c_end) in sorted(getattr(concept, "timestamps", []) or []):
            c_start, c_end = float(c_start), float(c_end)
            if merged and c_start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], c_end)
            else:
                merged.append([c_start, c_end])
        covered = sum(b - a for a, b in merged)
        localities.append(1.0 - min(covered / timeline, 1.0))

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
            affinity[i, j] = best * localities[j]

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
    # Set before any early return: every exit path must report honestly
    # whether the concept term actually participated in this run.
    result.concept_signal = "available" if len(concepts) else "unavailable"
    if not segments or budget_seconds <= 0:
        return result

    # Requested summary longer than the source: take everything, in order.
    # Overlaps are still dropped — showing the viewer the same footage twice is
    # wrong whether or not there is budget left to spare.
    total_available = sum(float(getattr(s, "duration", 0.0)) for s in segments)
    if total_available <= budget_seconds:
        ordered = sorted(segments, key=lambda s: (getattr(s, "video_id", ""), s.start_time))
        kept: List = []
        for seg in ordered:
            if any(_overlaps(seg, other) for other in kept):
                continue
            kept.append(seg)
        result.segments = kept
        result.total_duration = sum(float(getattr(s, "duration", 0.0)) for s in kept)
        result.concepts_covered = [getattr(c, "name", "") for c in concepts]
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
    # best_affinity[j] = how well the BEST already-selected segment covers concept j.
    best_affinity = np.zeros(len(concepts), dtype=float)
    bin_seconds = np.zeros(n_bins, dtype=float)
    total_selected = 0.0

    def bin_gain(indices) -> float:
        """
        Concave temporal-coverage gain from adding every segment in `indices`.

        sqrt() is the whole trick. Adding the first 30 seconds to an empty bin
        gains sqrt(30) = 5.48; adding 30 more to a bin that already has 60 gains
        sqrt(90) - sqrt(60) = 1.74. Under-represented regions are worth ~3x more
        without any bin ever being mandatory.

        Takes a set because a candidate may commit to a whole concept
        occurrence; for the single-segment case this is identical to the
        original per-segment computation.
        """
        before = np.sqrt(bin_seconds).sum()
        trial = bin_seconds.copy()
        for i in indices:
            _accumulate_bins(trial, segments[i], total_duration, n_bins)
        return float(np.sqrt(trial).sum() - before)

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
            temporal_gain = (bin_gain(members) / max_bin_gain) * gated

            if vectors is not None and selected:
                redundancy = float(max(
                    vectors[i] @ vectors[s] for i in members for s in selected
                ))
                redundancy = max(0.0, redundancy)
            else:
                redundancy = 0.0

            # Relevance is discounted by redundancy before the explicit penalty
            # is applied. Subtracting a penalty alone is not enough: a segment
            # identical to one already selected still scored FULL relevance,
            # because relevance measures "is this on-topic?" and a duplicate of
            # an on-topic segment trivially is. The tenth explanation of
            # overfitting was therefore still claiming credit for being about
            # overfitting. Redundancy now cancels the relevance a duplicate is
            # double-counting, and the penalty term prices the duplication on
            # top of that.
            #
            # Concept gain needs no such treatment — it is submodular already,
            # so a covered concept cannot be claimed twice. Temporal coverage is
            # deliberately NOT discounted: footage from an untouched region is
            # new footage no matter how familiar the words are.
            gain = (
                weights.concept * concept_gain
                + weights.semantic * group_relevance * (1.0 - redundancy)
                + weights.coverage * temporal_gain
                + weights.coherence * group_coherence
                - weights.redundancy * redundancy
                - weights.duration_penalty * (dur / longest)
            )

            # Cost-benefit greedy: value per second, not value.
            density = gain / dur
            if density > best_density:
                best_density = density
                best_idx = idx
                best_commitment = commitment
                best_parts = {
                    "concept": round(concept_gain, 4),
                    "semantic": round(group_relevance, 4),
                    "coverage": round(temporal_gain, 4),
                    "coherence": round(group_coherence, 4),
                    "redundancy": round(redundancy, 4),
                    "gain": round(gain, 4),
                    "gain_per_second": round(density, 6),
                    "committed_segments": len(commitment),
                }

        if best_idx < 0:
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
                print(f"[Selector] Stopping at {total_selected:.0f}s/{budget_seconds:.0f}s "
                      f"({fill:.0%}) — no remaining segment adds positive value")
                break

        # Commit the WHOLE occurrence, not just the winning segment. This is
        # what makes "complete concept or reject" hold: the candidate was
        # already priced and budget-checked as a group above, so taking it
        # partially here would reintroduce the fragment the check prevented.
        seg = segments[best_idx]
        committed = sorted(best_commitment)
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

        result.trace.append({
            "rank": len(selected),
            "start_time": round(float(min(segments[i].start_time for i in committed)), 1),
            "end_time": round(float(max(segments[i].end_time for i in committed)), 1),
            "duration": round(float(sum(durations[i] for i in committed)), 1),
            **best_parts,
        })

        # Drop anything that overlaps the pick. Overlapping clips would show the
        # viewer the same footage twice.
        for idx in list(remaining):
            if any(_overlaps(segments[idx], segments[i]) for i in committed):
                remaining.discard(idx)

    chosen = [segments[i] for i in selected]
    chosen.sort(key=lambda s: (getattr(s, "video_id", ""), s.start_time))

    if vectors is not None and len(segments) > 2:
        all_sims = vectors @ vectors.T
        np.fill_diagonal(all_sims, -1.0)
        result.baseline_similarity = float(np.clip(all_sims.max(axis=1).mean(), 0.0, 1.0))

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
