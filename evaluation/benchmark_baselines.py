import os; os.environ["OMP_NUM_THREADS"] = "1"; os.environ["MKL_NUM_THREADS"] = "1"; os.environ["TOKENIZERS_PARALLELISM"] = "false"
import sys, os, json, time
import numpy as np
import torch
torch.set_num_threads(1)
sys.path.insert(0, '/home/weiblocks/Desktop/Video-summarization')
HERE = os.path.dirname(os.path.abspath(__file__))
import json
import asyncio

from backend.services.semantic_segmenter import build_semantic_segments, build_sentences
from backend.services.concept_extractor import extract_concepts, clear_cache, extract_concepts_tfidf, Chunk
from backend.services.coverage_selector import select_segments, SelectionWeights, build_concept_affinity
from backend.core.config import get_settings
from evaluation.evaluate import evaluate, GOLD

S = get_settings()
TRANSCRIPTS = json.load(open(os.path.join(HERE, "transcripts.json")))

def greedy_select(segments, scores, budget):
    sorted_indices = np.argsort(scores)[::-1]
    selected = []
    total_time = 0.0
    for idx in sorted_indices:
        seg = segments[idx]
        if total_time + seg.duration > budget: continue
        overlaps = False
        for s in selected:
            if not (seg.end_time <= s.start_time or seg.start_time >= s.end_time):
                overlaps = True
                break
        if not overlaps:
            selected.append(seg)
            total_time += seg.duration
            if total_time >= budget: break
    return sorted(selected, key=lambda s: s.start_time)

def main():
    from backend.services.fusion_engine import get_fusion_engine, get_sentence_transformer
    rows = []
    hybrid_traces = []
    budget_seconds = 10 * 60

    for vid, meta in GOLD.items():
        if vid.startswith('_'): continue
        raw_doc = TRANSCRIPTS.get(vid)
        if not raw_doc: continue
        raw = raw_doc
        total = float(raw[-1]['start']) + float(raw[-1].get('duration', 0))
        sentences = build_sentences(raw)
        
        print(f"\n[{vid}] {meta['genre']}", flush=True)
        print("Building semantic segments...", flush=True)
        segs = build_semantic_segments(raw, vid, S.SEGMENT_MIN_SECONDS, S.SEGMENT_MAX_SECONDS)
        clear_cache()
        print(f"Segments built! ({len(segs)})", flush=True)
        
        # Now use the original extract_concepts (with LLM=False) so it mimics evaluate.py exactly
        print("Extracting concepts...", flush=True)
        cps = asyncio.run(extract_concepts(segs, total_duration=total, top_k=S.CONCEPT_TOP_K, use_llm=False))
        print("Concepts extracted!", flush=True)
        
        pool = sum(s.duration for s in segs)
        
        print("Getting Fusion Engine...", flush=True)
        fusion_engine = get_fusion_engine()
        print("Fusing...", flush=True)
        fusion_result = fusion_engine.fuse_transcripts(
            transcripts={vid: " ".join(s['text'] for s in raw)},
            target_words=budget_seconds * 2.5,
            include_sources=False,
            include_transitions=False,
            raw_segments={vid: raw},
        )
        semantic_bias_text = fusion_result.narrative if fusion_result else ""
        print("Fusing done!", flush=True)
        
        print("Getting Embedder...", flush=True)
        embedder = get_sentence_transformer()
        print("Embedder Got!", flush=True)
        
        methods = {}
        t0 = time.time()
        scores_a = [-s.start_time for s in segs]
        methods['A_Chronological'] = (greedy_select(segs, scores_a, budget_seconds), time.time() - t0)
        
        t0 = time.time()
        if not cps:
            scores_b = [0] * len(segs)
        else:
            affinity = build_concept_affinity(segs, cps, None, embedder)
            concept_importance = np.asarray([float(getattr(c, "importance", 0.0)) for c in cps], dtype=float)
            scores_b = np.dot(concept_importance, affinity.T) if affinity.size else np.zeros(len(segs))
        methods['B_TFIDF'] = (greedy_select(segs, scores_b, budget_seconds), time.time() - t0)
        
        t0 = time.time()
        if not semantic_bias_text:
            bias_emb = None
            scores_c = [0] * len(segs)
        else:
            bias_emb = embedder.encode(semantic_bias_text)
            seg_embs = np.vstack([s.embedding if s.embedding is not None else embedder.encode(s.text) for s in segs])
            scores_c = np.dot(seg_embs, bias_emb) / (np.linalg.norm(seg_embs, axis=1) * np.linalg.norm(bias_emb) + 1e-9)
        methods['C_Semantic'] = (greedy_select(segs, scores_c, budget_seconds), time.time() - t0)
        
        t0 = time.time()
        w = SelectionWeights(**{'concept':0.35, 'semantic':0.20, 'coverage':0.25, 'coherence':0.10, 'redundancy':0.25, 'duration_penalty':0.05})
        res_d = select_segments(segs, budget_seconds, cps, w, bias_emb if semantic_bias_text else None, embedder, total)
        methods['E_Hybrid_Normalized'] = (res_d.segments, time.time() - t0)
        if res_d.trace: hybrid_traces.extend(res_d.trace)

        for m_name, (selected, latency) in methods.items():
            if not selected: continue
            m_metrics = evaluate(selected, meta['concepts'], sentences, budget_seconds, total, pool)
            m_metrics.update(video=vid, genre=meta['genre'], method=m_name, latency=latency)
            rows.append(m_metrics)
            print(f"  {m_name:<16}: Recall {m_metrics['recall']:.2f}, Prec {m_metrics['precision']:.2f}, Latency {latency:.2f}s", flush=True)
            
    json.dump(rows, open(os.path.join(HERE, 'benchmark_results.json'), 'w'), indent=1)
    
    print("\n\n### Benchmark Results (Averaged over 7 videos, 10 min budget)\n")
    print("| Method | Recall | Precision (Gold) | Redundancy | Temporal Cov | Complete Thought | Selected Clips | Latency | Duration Acc |")
    print("|---|---|---|---|---|---|---|---|---|")
    for m_name in ['A_Chronological', 'B_TFIDF', 'C_Semantic', 'E_Hybrid_Normalized']:
        m_rows = [r for r in rows if r['method'] == m_name]
        if not m_rows: continue
        avg = lambda k: sum(r[k] for r in m_rows) / len(m_rows)
        print(f"| {m_name} "
              f"| {avg('recall'):.3f} "
              f"| {avg('precision'):.3f} "
              f"| {avg('redundancy'):.3f} "
              f"| {avg('deciles'):.1f} deciles "
              f"| {avg('complete_rate'):.3f} "
              f"| {avg('n'):.1f} "
              f"| {avg('latency'):.2f}s "
              f"| {avg('dur_acc'):.3f} |")
              
    if hybrid_traces:
        print("\n### Hybrid Selector (Method E) Average Trace Contributions\n")
        for k in ("concept", "semantic", "coverage", "coherence", "redundancy", "duration_penalty"):
            if k in hybrid_traces[0]:
                avg_val = sum(t.get(k, 0.0) for t in hybrid_traces) / len(hybrid_traces)
                w_val = w.__dict__.get(k, w.__dict__.get(k.replace('_penalty',''), 1.0))
                if k == "redundancy": w_val = w.redundancy
                if k == "duration_penalty": w_val = w.duration_penalty
                print(f"- **{k.capitalize()}**: Raw = {avg_val:.3f}, Effective Weight = {avg_val * w_val:.3f} (Config: {w_val})")

if __name__ == "__main__":
    main()
