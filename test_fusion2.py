import sys, os, json
sys.path.insert(0, '/home/weiblocks/Desktop/Video-summarization')
from backend.services.fusion_engine import FusionEngine

TRANSCRIPTS = json.load(open('evaluation/transcripts.json'))
vid = 'HVqWN7IVzwU'
raw = TRANSCRIPTS[vid]
text = " ".join(s['text'] for s in raw)

engine = FusionEngine()
res = engine.fuse_transcripts(
    transcripts={vid: text},
    video_titles={vid: "Test"},
    raw_segments={vid: raw}
)
print("Narrative length:", len(res.narrative.split()))
print("Metadata:", res.metadata)
