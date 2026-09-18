import asyncio
from backend.services.coverage_selector import select_segments, SemanticSegment
from backend.services.concept_extractor import Concept

async def run():
    segments = [SemanticSegment("vid1", 0.0, 10.0, "hello")]
    concepts = [Concept(name="test", timestamps=[(0.0, 5.0)])]
    
    # Try passing dict
    select_segments(segments, 10.0, concepts=concepts, total_duration={"vid1": 10.0})
    
asyncio.run(run())
