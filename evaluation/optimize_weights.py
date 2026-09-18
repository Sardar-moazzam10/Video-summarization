import os; os.environ["OMP_NUM_THREADS"] = "1"; os.environ["MKL_NUM_THREADS"] = "1"; os.environ["TOKENIZERS_PARALLELISM"] = "false"
import sys, os, json, time, random, copy, pickle
import numpy as np
import torch
torch.set_num_threads(1)
sys.path.insert(0, '/home/weiblocks/Desktop/Video-summarization')
HERE = os.path.dirname(os.path.abspath(__file__))

from backend.services.semantic_segmenter import build_semantic_segments, build_sentences
from backend.services.concept_extractor import extract_concepts_tfidf, Chunk
from backend.services.coverage_selector import select_segments, SelectionWeights
from backend.core.config import get_settings
from evaluation.evaluate import evaluate, GOLD
from sentence_transformers import SentenceTransformer

TRANSCRIPTS = json.load(open(os.path.join(HERE, "transcripts.json")))
CACHE_FILE = os.path.join(HERE, "bge_cache.pkl")

class CachedEmbedder:
    def __init__(self, real_embedder):
        self.real = real_embedder
        self.cache = {}
        if os.path.exists(CACHE_FILE):
            print("Loading cache from disk...")
            with open(CACHE_FILE, 'rb') as f:
                self.cache = pickle.load(f)
        
    def encode(self, texts, **kwargs):
        uncached = [t for t in texts if t not in self.cache]
        if uncached:
            vecs = self.real.encode(uncached, **kwargs)
            for t, v in zip(uncached, vecs):
                self.cache[t] = v
            with open(CACHE_FILE, 'wb') as f:
                pickle.dump(self.cache, f)
        return np.array([self.cache[t] for t in texts])

def main():
    print("Pre-computing segments and concepts for all videos...")
    real_embedder = SentenceTransformer("BAAI/bge-base-en-v1.5")
    embedder = CachedEmbedder(real_embedder)
    
    videos = {}
    for vid in GOLD:
        if vid == "_method" or vid not in TRANSCRIPTS:
            continue
        v_type = GOLD[vid].get("genre", "unknown")
            
        print(f"[{vid}] {v_type}")
        sentences = build_sentences(TRANSCRIPTS[vid])
        chunks = [Chunk(s.text, s.start, s.end, i) for i, s in enumerate(sentences)]
        
        segments = build_semantic_segments(TRANSCRIPTS[vid], video_id=vid, embedder=embedder)
        concepts = extract_concepts_tfidf(chunks, max_concepts=25)
        
        total_dur = GOLD[vid]["duration"]
        pool_dur = sum(s.duration for s in segments)
        
        videos[vid] = {
            "segments": segments,
            "concepts": concepts,
            "budget": 600,
            "type": v_type,
            "gold_concepts": GOLD[vid]["concepts"],
            "sentences": sentences,
            "total": total_dur,
            "pool": pool_dur
        }

    print("\nStarting LOOCV Weight Search...")
    def sample_weights():
        w = SelectionWeights(
            concept = random.uniform(0.2, 1.0),
            semantic = random.uniform(0.2, 1.0),
            coverage = random.uniform(0.0, 0.2),
            coherence = random.uniform(0.0, 0.5),
            redundancy = random.uniform(0.0, 0.3),
            duration_penalty = random.uniform(0.0, 0.2),
            min_budget_fill = 0.8
        )
        tot = w.concept + w.semantic + w.coverage + w.coherence + w.redundancy + w.duration_penalty
        w.concept /= tot
        w.semantic /= tot
        w.coverage /= tot
        w.coherence /= tot
        w.redundancy /= tot
        w.duration_penalty /= tot
        return w
        
    def eval_weights(weights_obj, vid):
        v = videos[vid]
        res = select_segments(
            segments=v["segments"],
            concepts=v["concepts"],
            summary_embedding=None,
            budget_seconds=v["budget"],
            embedder=embedder,
            weights=weights_obj
        )
        return evaluate(res.segments, v["gold_concepts"], v["sentences"], v["budget"], v["total"], v["pool"])
        
    NUM_SAMPLES = 200
    configs = [sample_weights() for _ in range(NUM_SAMPLES)]
    
    results = {vid: [] for vid in videos}
    for i, w in enumerate(configs):
        if i % 20 == 0:
            print(f"Evaluating config {i}/{NUM_SAMPLES}")
        for vid in videos:
            sys.stdout = open(os.devnull, 'w')
            try:
                metrics = eval_weights(w, vid)
            finally:
                sys.stdout = sys.__stdout__
            f1 = 0
            if metrics["recall"] + metrics["precision"] > 0:
                f1 = 2 * (metrics["recall"] * metrics["precision"]) / (metrics["recall"] + metrics["precision"])
            metrics["f1"] = f1
            results[vid].append(metrics)
            
    print("\n=== LOOCV Results ===")
    test_metrics = []
    
    for holdout_vid in videos:
        best_i = -1
        best_f1 = -1
        for i in range(NUM_SAMPLES):
            train_f1 = np.mean([results[v][i]["f1"] for v in videos if v != holdout_vid])
            if train_f1 > best_f1:
                best_f1 = train_f1
                best_i = i
                
        test_res = results[holdout_vid][best_i]
        test_metrics.append(test_res)
        w = configs[best_i]
        print(f"Holdout {holdout_vid}: Selected config {best_i} (w_c={w.concept:.2f}, w_s={w.semantic:.2f}, w_cov={w.coverage:.2f}, w_coh={w.coherence:.2f}, w_red={w.redundancy:.2f}, w_dur={w.duration_penalty:.2f})")
        print(f"  -> Test F1: {test_res['f1']:.3f} (Recall: {test_res['recall']:.3f}, Prec: {test_res['precision']:.3f})")
        
    avg = lambda k: sum(r[k] for r in test_metrics) / len(test_metrics)
    print("\n### Optimized Hybrid (Method F) LOOCV Average")
    print(f"| F_Optimized_Hybrid | {avg('recall'):.3f} | {avg('precision'):.3f} | {avg('redundancy'):.3f} | {avg('deciles'):.1f} deciles | {avg('complete_rate'):.3f} | {avg('n'):.1f} | N/A | {avg('dur_acc'):.3f} |")
    
if __name__ == "__main__":
    main()
