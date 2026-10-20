import asyncio
from backend.core.database import get_sync_database
from backend.services.coverage_selector import select_segments, SelectionWeights
from backend.services.manifest_boundary_repair import (
    repair_explanation_boundaries,
    repair_physical_boundaries,
    rebuild_final_texts,
    assess_start_boundary,
    assess_end_boundary,
    _entries,
    _score_boundary,
)
from backend.services.semantic_segmenter import build_semantic_segments

raw = get_sync_database().transcripts.find_one({"video_id": "kqtD5dpn9C8"})["transcript"]
raw_segments = {"kqtD5dpn9C8": raw}

segs = build_semantic_segments(raw, "kqtD5dpn9C8")
print(f"Total semantic segments: {len(segs)}")

weights = SelectionWeights.from_settings()
weights.min_budget_fill = 0.90
result = select_segments(
    segments=segs,
    budget_seconds=1800.0,
    weights=weights,
    total_duration={"kqtD5dpn9C8": 3660.0},
)
print(f"Selector picked {len(result.segments)} segments, duration: {result.total_duration:.2f}s")

# Step 1: repair explanation boundaries
all_selected, _ = repair_explanation_boundaries(result.segments, raw_segments, segs)
print(f"Step 1: {len(all_selected)} segments, total dur={sum(s.duration for s in all_selected):.2f}s")
step1_incomplete = sum(float(getattr(s, "completeness", 0.0)) < 1.0 for s in all_selected)
print(f"Step 1 incomplete count: {step1_incomplete}")

# Step 2: repair physical boundaries
all_selected, stats = repair_physical_boundaries(all_selected)
print(f"Step 2: {len(all_selected)} segments, total dur={sum(s.duration for s in all_selected):.2f}s, merges={stats.adjacent_intervals_merged}")

# Step 3: rebuild final texts
all_selected = rebuild_final_texts(all_selected, raw_segments, segs)
print(f"Step 3: {len(all_selected)} segments, total dur={sum(s.duration for s in all_selected):.2f}s")
for i, s in enumerate(all_selected):
    comp = float(getattr(s, "completeness", 0.0))
    if comp < 1.0:
        print(f"  Step 3 REJECTED [{i}]: {s.start_time:.2f}-{s.end_time:.2f} dur={s.duration:.2f}s")
        print(f"     start_ev: {getattr(s, 'start_boundary_evidence', {})}")
        print(f"     end_ev:   {getattr(s, 'end_boundary_evidence', {})}")
        print(f"     hits:     {getattr(s, 'non_content_guard_hits', [])}")
    else:
        print(f"  Step 3 KEPT [{i}]: {s.start_time:.2f}-{s.end_time:.2f} dur={s.duration:.2f}s")
