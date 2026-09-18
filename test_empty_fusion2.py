import os, sys, json
sys.path.insert(0, '.')
import torch; torch.set_num_threads(1)
os.environ['OMP_NUM_THREADS']='1'

from backend.services.fusion_engine import FusionEngine

TRANSCRIPTS = json.load(open('evaluation/transcripts.json'))
vid = 'HVqWN7IVzwU'
raw = TRANSCRIPTS[vid]
text = " ".join(s['text'] for s in raw)

engine = FusionEngine()
res = engine.fuse_transcripts(
    transcripts={vid: text},
    video_titles={vid: "Test"},
    raw_segments={vid: raw},
    target_words=250
)
print("Target: 250 -> Narrative length:", len(res.narrative.split()))
print("Metadata:", res.metadata)
