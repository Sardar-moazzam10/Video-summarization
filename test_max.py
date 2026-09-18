from backend.services.coverage_selector import select_segments
from backend.services.semantic_segmenter import SemanticSegment
from backend.services.concept_extractor import Concept

seg = SemanticSegment("vid1", 0.0, 20.0, "hello")
concepts = [Concept(name="test", timestamps=[(0.0, 5.0)])]
durations = {"vid1": 20.0}

try:
    select_segments([seg], 10.0, concepts=concepts, total_duration=durations)
except Exception as e:
    import traceback
    traceback.print_exc()
