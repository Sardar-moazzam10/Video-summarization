"""
Manual verification script for Phase 1 fixes:
1. Cross-source inverted chunk bug (Video A ends at 290-310s, Video B begins at 0-20s).
2. Cross-source concept leakage (Video A concept at 30-50s vs Video B at 30-50s).
"""
from backend.services.concept_extractor import build_chunks, Concept, ConceptOccurrence
from backend.services.semantic_segmenter import SemanticSegment
from backend.services.coverage_selector import build_candidate_units, build_concept_affinity

print("=" * 60)
print("TEST 1: Inverted Chunk & Boundary Crossing Bug")
print("=" * 60)
segs = [
    SemanticSegment("vidA", 290.0, 310.0, "video A last segment on machine learning"),
    SemanticSegment("vidB", 0.0, 20.0, "video B first segment on cooking recipes")
]
chunks = build_chunks(segs)
for i, c in enumerate(chunks, 1):
    print(f"Chunk #{i}: Video ID={c.video_id} | Time={c.start}s -> {c.end}s | Text='{c.text}'")

has_inverted = any(c.start > c.end for c in chunks)
has_cross_video = any("machine learning" in c.text and "cooking" in c.text for c in chunks)

if not has_inverted and not has_cross_video and len(chunks) == 2:
    print(">> RESULT: PASSED! (No cross-video chunk, no inverted timestamps)")
else:
    print(">> RESULT: FAILED!")

print("\n" + "=" * 60)
print("TEST 2: Cross-Source Concept Leakage Bug")
print("=" * 60)
# Concept belongs strictly to vidA at 30-50s
concept = Concept("Machine Learning", 1.0, occurrences=[ConceptOccurrence("vidA", 30.0, 50.0)])
test_segs = [
    SemanticSegment("vidA", 30.0, 50.0, "vidA discussion on machine learning"),
    SemanticSegment("vidB", 30.0, 50.0, "vidB discussion on pasta sauce")
]
aff = build_concept_affinity(test_segs, [concept], segment_vectors=None)
print(f"Video A (source video, 30-50s)   Concept Affinity: {aff[0,0]:.4f}  (Expected: > 0)")
print(f"Video B (unrelated video, 30-50s) Concept Affinity: {aff[1,0]:.4f}  (Expected: 0.0)")

if aff[0,0] > 0 and aff[1,0] == 0.0:
    print(">> RESULT: PASSED! (Video B got 0.0 credit; zero leakage)")
else:
    print(">> RESULT: FAILED!")
print("=" * 60)

