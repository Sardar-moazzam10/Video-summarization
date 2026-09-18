import os, sys, json
sys.path.insert(0, '.')
import torch; torch.set_num_threads(1)
os.environ['OMP_NUM_THREADS']='1'

from backend.services.semantic_segmenter import build_semantic_segments, build_sentences
from backend.services.concept_extractor import extract_concepts_tfidf, Chunk
from backend.services.coverage_selector import select_segments, SelectionWeights
from backend.services.fusion_engine import FusionEngine
from sentence_transformers import SentenceTransformer

def test_empty_fusion():
    TRANSCRIPTS = json.load(open('evaluation/transcripts.json'))
    vid = 'HVqWN7IVzwU'
    raw = TRANSCRIPTS[vid]
    embedder = SentenceTransformer("BAAI/bge-base-en-v1.5")

    # 1. build segments
    sentences = build_sentences(raw)
    chunks = [Chunk(s.text, s.start, s.end, i) for i, s in enumerate(sentences)]
    segments = build_semantic_segments(raw, video_id=vid, embedder=embedder)
    concepts = extract_concepts_tfidf(chunks, max_concepts=25)

    # 2. optimal weights from Phase 2C
    w = SelectionWeights(
        concept=0.36, semantic=0.34, coverage=0.02, coherence=0.17, redundancy=0.10, duration_penalty=0.02
    )
    res = select_segments(segments, 600, concepts=concepts, summary_embedding=None, embedder=embedder, weights=w)
    print(f"Selected {len(res.selected_indices)} segments, total duration {res.selected_duration:.1f}s")

    # 3. prepare fusion input
    raw_segs_fusion = []
    for s in res.selected_segments:
        raw_segs_fusion.append({
            "text": " ".join(sen.text for sen in getattr(s, "sentences", [])),
            "start": s.start_time,
            "duration": s.end_time - s.start_time
        })

    engine = FusionEngine()
    fusion_res = engine.fuse_transcripts(
        transcripts={vid: " ".join(r["text"] for r in raw_segs_fusion)},
        video_titles={vid: "Test"},
        raw_segments={vid: raw_segs_fusion}
    )
    print("Narrative length:", len(fusion_res.narrative.split()))
    print("Metadata:", fusion_res.metadata)

if __name__ == '__main__':
    test_empty_fusion()
