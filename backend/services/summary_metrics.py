"""
Selection Metrics — the numbers that prove the summary is actually better.

Every claim this project makes about the new pipeline ("later portions are no
longer ignored", "concepts are more diverse") is checkable here. The report is
computed once per job, stored on the job document, and returned by
GET /api/v1/merge/{job_id}/result so the frontend and the viva demo can show it.

Nothing here calls a model or the network — it is arithmetic over the selection
that already happened, so it costs microseconds and can never fail a job.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np


def compute_selection_metrics(
    selected: Sequence,
    total_duration: float,
    requested_seconds: float,
    concepts: Sequence = (),
    concepts_covered: Sequence[str] = (),
    segment_vectors: Optional[np.ndarray] = None,
    n_bins: int = 10,
) -> Dict:
    """
    Build the validation report for one completed selection.

    Args:
        selected:        chosen segments (objects with start_time/end_time/duration)
        total_duration:  length of the source timeline, seconds
        requested_seconds: the user's chosen budget
        concepts:        ranked Concept objects for this video
        concepts_covered: names the optimizer reported as covered
        segment_vectors: L2-normalised embeddings of the SELECTED segments, in
                         the same order. Supplied -> real redundancy is measured;
                         omitted -> redundancy is reported as None rather than
                         guessed.

    Returns a JSON-safe dict.
    """
    items = list(selected)
    if not items:
        return {
            "requested_seconds": round(float(requested_seconds), 1),
            "actual_seconds": 0.0,
            "duration_accuracy_percent": 0.0,
            "num_segments": 0,
            "num_cuts": 0,
            "timeline_coverage_percent": 0.0,
            "bins_occupied": 0,
            "bins_total": n_bins,
            "temporal_histogram": [0.0] * n_bins,
            "first_half_share_percent": 0.0,
            "second_half_share_percent": 0.0,
            "unique_concepts": 0,
            "avg_concept_importance": 0.0,
            "redundancy_percent": None,
            "earliest_timestamp": None,
            "latest_timestamp": None,
            "avg_segment_seconds": 0.0,
            "min_segment_seconds": 0.0,
            "max_segment_seconds": 0.0,
        }

    starts = [float(getattr(s, "start_time", 0.0)) for s in items]
    ends = [float(getattr(s, "end_time", 0.0)) for s in items]
    durations = [max(0.0, e - s) for s, e in zip(starts, ends)]
    actual = float(sum(durations))
    total_duration = max(float(total_duration), 1e-6)

    # --- temporal distribution ---
    histogram = [0.0] * n_bins
    width = total_duration / n_bins
    for s, e in zip(starts, ends):
        for b in range(n_bins):
            lo, hi = b * width, (b + 1) * width
            overlap = min(e, hi) - max(s, lo)
            if overlap > 0:
                histogram[b] += overlap

    occupied = sum(1 for h in histogram if h > 0)
    first_half = sum(histogram[: n_bins // 2])
    second_half = sum(histogram[n_bins // 2:])
    halves_total = max(first_half + second_half, 1e-6)

    # --- concepts ---
    covered = [c for c in concepts_covered if c]
    importances = [
        float(getattr(c, "importance", 0.0))
        for c in concepts
        if getattr(c, "name", "") in set(covered)
    ]

    # --- redundancy ---
    redundancy = None
    if segment_vectors is not None and len(segment_vectors) == len(items) and len(items) > 1:
        matrix = np.asarray(segment_vectors, dtype=float)
        sims = matrix @ matrix.T
        # Mean of the strongest off-diagonal similarity per segment: "how much
        # does each clip echo its nearest neighbour?". Cosine similarity of
        # unrelated passages sits near 0.2-0.3, so the floor is subtracted and
        # the result rescaled — otherwise a perfectly diverse reel would report
        # ~25% redundancy and the number would be meaningless.
        np.fill_diagonal(sims, -1.0)
        peak_per_segment = sims.max(axis=1)
        raw = float(np.clip(peak_per_segment.mean(), 0.0, 1.0))
        redundancy = round(float(np.clip((raw - 0.30) / 0.70, 0.0, 1.0)) * 100, 1)

    return {
        "requested_seconds": round(float(requested_seconds), 1),
        "actual_seconds": round(actual, 1),
        "duration_accuracy_percent": round(
            100.0 - abs(actual - requested_seconds) / max(requested_seconds, 1e-6) * 100.0, 1
        ),
        "num_segments": len(items),
        "num_cuts": max(len(items) - 1, 0),
        "timeline_coverage_percent": round(actual / total_duration * 100.0, 1),
        "bins_occupied": occupied,
        "bins_total": n_bins,
        "temporal_histogram": [round(h, 1) for h in histogram],
        "first_half_share_percent": round(first_half / halves_total * 100.0, 1),
        "second_half_share_percent": round(second_half / halves_total * 100.0, 1),
        "unique_concepts": len(covered),
        "concepts_covered": covered[:20],
        "avg_concept_importance": round(float(np.mean(importances)), 4) if importances else 0.0,
        "redundancy_percent": redundancy,
        "earliest_timestamp": round(min(starts), 1),
        "latest_timestamp": round(max(ends), 1),
        "avg_segment_seconds": round(actual / len(items), 1),
        "min_segment_seconds": round(min(durations), 1),
        "max_segment_seconds": round(max(durations), 1),
    }


def format_metrics_report(metrics: Dict, title: str = "Selection metrics") -> str:
    """Human-readable block for logs and the before/after comparison."""
    if not metrics or not metrics.get("num_segments"):
        return f"{title}: no segments selected"

    def mmss(seconds: Optional[float]) -> str:
        if seconds is None:
            return "-"
        seconds = int(seconds)
        return f"{seconds // 60}:{seconds % 60:02d}"

    redundancy = metrics.get("redundancy_percent")
    lines = [
        f"--- {title} ---",
        f"  Requested duration    : {mmss(metrics['requested_seconds'])}",
        f"  Actual duration       : {mmss(metrics['actual_seconds'])} "
        f"({metrics['duration_accuracy_percent']}% of target)",
        f"  Semantic segments     : {metrics['num_segments']}  (cuts: {metrics['num_cuts']})",
        f"  Avg segment length    : {metrics['avg_segment_seconds']}s "
        f"(min {metrics['min_segment_seconds']}s, max {metrics['max_segment_seconds']}s)",
        f"  Timeline coverage     : {metrics['timeline_coverage_percent']}% of source",
        f"  Deciles occupied      : {metrics['bins_occupied']}/{metrics['bins_total']}",
        f"  Temporal balance      : {metrics['first_half_share_percent']}% first half / "
        f"{metrics['second_half_share_percent']}% second half",
        f"  Unique concepts       : {metrics['unique_concepts']}",
        f"  Avg concept weight    : {metrics['avg_concept_importance']}",
        f"  Redundancy            : {redundancy if redundancy is not None else 'n/a'}%",
        f"  Span                  : {mmss(metrics['earliest_timestamp'])} -> "
        f"{mmss(metrics['latest_timestamp'])}",
    ]
    return "\n".join(lines)
