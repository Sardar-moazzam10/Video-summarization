"""Tests for summary_metrics — the numbers used to claim improvement."""

import numpy as np
import pytest

from backend.services.summary_metrics import compute_selection_metrics, format_metrics_report
from backend.services.semantic_segmenter import SemanticSegment


def segs(spans, video_id="v1"):
    return [SemanticSegment(video_id, a, b, f"text {a}") for a, b in spans]


class TestMetrics:
    def test_basic_counts(self):
        m = compute_selection_metrics(
            segs([(0, 30), (100, 140), (200, 225)]),
            total_duration=1000.0, requested_seconds=100.0,
        )
        assert m["num_segments"] == 3
        assert m["num_cuts"] == 2
        assert m["actual_seconds"] == pytest.approx(95.0)
        assert m["earliest_timestamp"] == 0.0
        assert m["latest_timestamp"] == 225.0
        assert m["avg_segment_seconds"] == pytest.approx(31.7, abs=0.1)
        assert m["min_segment_seconds"] == 25.0
        assert m["max_segment_seconds"] == 40.0

    def test_timeline_coverage(self):
        m = compute_selection_metrics(
            segs([(0, 100), (500, 600)]), total_duration=1000.0, requested_seconds=200.0
        )
        assert m["timeline_coverage_percent"] == pytest.approx(20.0)

    def test_duration_accuracy(self):
        exact = compute_selection_metrics(segs([(0, 300)]), 1000.0, 300.0)
        assert exact["duration_accuracy_percent"] == pytest.approx(100.0)
        short = compute_selection_metrics(segs([(0, 150)]), 1000.0, 300.0)
        assert short["duration_accuracy_percent"] == pytest.approx(50.0)

    def test_the_histogram_detects_a_beginning_heavy_selection(self):
        """The exact shape of the failure this project set out to fix."""
        m = compute_selection_metrics(
            segs([(0, 100), (100, 200), (200, 300)]),
            total_duration=1000.0, requested_seconds=300.0,
        )
        assert m["bins_occupied"] == 3
        assert m["first_half_share_percent"] == 100.0
        assert m["second_half_share_percent"] == 0.0
        assert sum(m["temporal_histogram"][5:]) == 0

    def test_the_histogram_confirms_a_balanced_selection(self):
        m = compute_selection_metrics(
            segs([(i * 100.0, i * 100.0 + 50.0) for i in range(10)]),
            total_duration=1000.0, requested_seconds=500.0,
        )
        assert m["bins_occupied"] == 10
        assert m["first_half_share_percent"] == pytest.approx(50.0)

    def test_a_segment_spanning_two_bins_is_split_between_them(self):
        m = compute_selection_metrics(
            segs([(90, 110)]), total_duration=1000.0, requested_seconds=20.0
        )
        assert m["temporal_histogram"][0] == pytest.approx(10.0)
        assert m["temporal_histogram"][1] == pytest.approx(10.0)

    def test_concept_metrics(self):
        class C:
            def __init__(self, name, importance):
                self.name, self.importance = name, importance

        m = compute_selection_metrics(
            segs([(0, 100)]), 1000.0, 100.0,
            concepts=[C("A", 0.9), C("B", 0.5), C("C", 0.1)],
            concepts_covered=["A", "B"],
        )
        assert m["unique_concepts"] == 2
        assert m["avg_concept_importance"] == pytest.approx(0.7)
        assert set(m["concepts_covered"]) == {"A", "B"}

    def test_redundancy_is_measured_not_guessed(self):
        picked = segs([(0, 30), (100, 130), (200, 230)])
        identical = np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]])
        orthogonal = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])

        high = compute_selection_metrics(picked, 1000.0, 90.0, segment_vectors=identical)
        low = compute_selection_metrics(picked, 1000.0, 90.0, segment_vectors=orthogonal)
        assert high["redundancy_percent"] == pytest.approx(100.0)
        assert low["redundancy_percent"] == pytest.approx(0.0)

    def test_redundancy_is_none_when_it_cannot_be_measured(self):
        m = compute_selection_metrics(segs([(0, 30), (100, 130)]), 1000.0, 60.0)
        assert m["redundancy_percent"] is None, "an unmeasurable value must not be invented"

    def test_empty_selection(self):
        m = compute_selection_metrics([], 1000.0, 300.0)
        assert m["num_segments"] == 0
        assert m["actual_seconds"] == 0.0
        assert m["earliest_timestamp"] is None

    def test_zero_total_duration_does_not_divide_by_zero(self):
        m = compute_selection_metrics(segs([(0, 30)]), 0.0, 30.0)
        assert m["timeline_coverage_percent"] > 0

    def test_output_is_json_serialisable(self):
        import json
        json.dumps(compute_selection_metrics(segs([(0, 30), (100, 130)]), 1000.0, 60.0))


class TestReport:
    def test_renders_every_required_metric(self):
        m = compute_selection_metrics(
            segs([(0, 100), (500, 600)]), 1000.0, 200.0, concepts_covered=["A", "B"]
        )
        report = format_metrics_report(m)
        for label in ("Requested duration", "Actual duration", "Semantic segments",
                      "Timeline coverage", "Deciles occupied", "Unique concepts",
                      "Redundancy", "Span"):
            assert label in report

    def test_handles_an_empty_selection(self):
        assert "no segments" in format_metrics_report(compute_selection_metrics([], 1000.0, 300.0))
