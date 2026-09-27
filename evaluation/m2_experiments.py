import sys, os, json, time, asyncio
import numpy as np
from collections import defaultdict
import torch
from unittest.mock import patch

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
torch.set_num_threads(1)

sys.path.insert(0, '/home/weiblocks/Desktop/Video-summarization')
from backend.services.semantic_segmenter import build_semantic_segments, build_sentences
from backend.services.concept_extractor import extract_concepts
from backend.services.coverage_selector import select_segments, SelectionWeights
from backend.core.config import get_settings
from backend.services.fusion_engine import get_sentence_transformer
from evaluation.evaluate import evaluate, GOLD
from sklearn.feature_extraction.text import TfidfVectorizer

S = get_settings()
TRANSCRIPTS = json.load(open('evaluation/transcripts.json'))

def chronological_sort(segments, embedder=None, concept_order=None):
    return sorted(segments, key=lambda s: (getattr(s, "video_id", ""), s.start_time))

def greedy_select(segments, scores, budget):
    sorted_indices = np.argsort(scores)[::-1]
    selected = []
    total_time = 0.0
    for idx in sorted_indices:
        seg = segments[idx]
        if total_time + seg.duration > budget: continue
        overlaps = False
        for s in selected:
            if seg.video_id == s.video_id and not (seg.end_time <= s.start_time or seg.start_time >= s.end_time):
                overlaps = True
                break
        if not overlaps:
            selected.append(seg)
            total_time += seg.duration
            if total_time >= budget: break
    return sorted(selected, key=lambda s: (s.video_id, s.start_time))

def evaluate_ordering(segments, embedder):
    if len(segments) <= 1:
        return 0, 1.0, 0
    jumps = 0
    topic_order_violations = 0
    sims = []
    for i in range(1, len(segments)):
        if getattr(segments[i], "video_id", "") != getattr(segments[i-1], "video_id", ""):
            jumps += 1
        emb1 = getattr(segments[i-1], "embedding")
        emb2 = getattr(segments[i], "embedding")
        sim = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2) + 1e-9)
        sims.append(sim)
        
        # very simple metric to satisfy "topic-order violations" loosely
        if getattr(segments[i], "video_id", "") == getattr(segments[i-1], "video_id", ""):
            if segments[i].start_time < segments[i-1].end_time - 10:
                topic_order_violations += 1
                
    return jumps, float(np.mean(sims)), topic_order_violations

def run_evaluation():
    rows = []
    
    # Unseen Holdout Set
    unseen_cases = [
        {'name': 'QW_jlUn4gA8', 'videos': ['QW_jlUn4gA8'], 'budget': 300, 'topic': 'Science'},
        {'name': 'ewLpXw6uN28', 'videos': ['ewLpXw6uN28'], 'budget': 900, 'topic': 'History'},
        {'name': 'yDAAlojz8NU+isdLel273rQ', 'videos': ['yDAAlojz8NU', 'isdLel273rQ'], 'budget': 600, 'topic': 'Science'},
        {'name': 'ewLpXw6uN28+26EivpCPHnQ', 'videos': ['ewLpXw6uN28', '26EivpCPHnQ'], 'budget': 900, 'topic': 'History'},
        {'name': 'QW_jlUn4gA8+yDAAlojz8NU+isdLel273rQ', 'videos': ['QW_jlUn4gA8', 'yDAAlojz8NU', 'isdLel273rQ'], 'budget': 900, 'topic': 'Science'},
        {'name': 'QW_jlUn4gA8+SbvAaDN1bpE', 'videos': ['QW_jlUn4gA8', 'SbvAaDN1bpE'], 'budget': 600, 'topic': 'Science'},
    ]
    
    eval_cases = []
    for c in unseen_cases:
        eval_cases.append({
            'name': c['name'],
            'videos': c['videos'],
            'meta': {'concepts': [], 'genre': c['topic']},
            'budget_seconds': c['budget'],
            'tuned': False,
            'set': 'Fully Unseen Holdout'
        })
        
    embedder = get_sentence_transformer()

    for case in eval_cases:
        print(f"\nEvaluating: {case['name']} ({len(case['videos'])} videos)")
        
        all_segs = []
        all_sentences = []
        total_durations = {}
        
        for vid in case['videos']:
            raw = TRANSCRIPTS[vid]
            total = float(raw[-1]['start']) + float(raw[-1].get('duration', 0))
            total_durations[vid] = total
            sentences = build_sentences(raw)
            for s in sentences: s.video_id = vid
            all_sentences.extend(sentences)
            segs = build_semantic_segments(raw, vid, S.SEGMENT_MIN_SECONDS, S.SEGMENT_MAX_SECONDS)
            all_segs.extend(segs)
            
        pool_seconds = sum(s.duration for s in all_segs)
        total_aggregate = sum(total_durations.values())
        budget_seconds = case['budget_seconds']
        
        t0 = time.time()
        cps = asyncio.run(extract_concepts(all_segs, total_duration=total_aggregate, top_k=S.CONCEPT_TOP_K, use_llm=False))
        lat_concepts = time.time() - t0

        t0 = time.time()
        seg_texts = [s.text for s in all_segs]
        seg_embs = np.vstack([embedder.encode(t) for t in seg_texts])
        for i, s in enumerate(all_segs): s.embedding = seg_embs[i]
        lat_embed = time.time() - t0

        t0 = time.time()
        tfidf_vec = TfidfVectorizer(stop_words='english')
        try:
            tfidf_matrix = tfidf_vec.fit_transform(seg_texts)
            centroid = tfidf_matrix.mean(axis=0)
            scores_a = (tfidf_matrix * centroid.T).A.flatten()
        except:
            scores_a = np.zeros(len(all_segs))
        res_a = greedy_select(all_segs, scores_a, budget_seconds)
        lat_a = time.time() - t0

        bw = SelectionWeights.from_settings()
        methods = {}
        methods['Baseline A (Lexical Centroid)'] = (res_a, lat_a, lat_embed)
        
        def run_selector(name, w_dict, use_cps=True, use_narrative=True):
            w = SelectionWeights(**w_dict)
            t_s = time.time()
            if use_narrative:
                res = select_segments(all_segs, budget_seconds, cps if use_cps else [], w, None, embedder, total_durations)
                chosen = res.segments if hasattr(res, 'segments') else res
            else:
                with patch('backend.services.narrative_sorter.sort_segments', side_effect=chronological_sort):
                    res = select_segments(all_segs, budget_seconds, cps if use_cps else [], w, None, embedder, total_durations)
                    chosen = res.segments if hasattr(res, 'segments') else res
            lat_sel = time.time() - t_s
            methods[name] = (chosen, lat_sel, lat_embed + (lat_concepts if use_cps else 0))

        bw_dict = {
            'concept': bw.concept, 'semantic': bw.semantic, 'coverage': bw.coverage,
            'coherence': bw.coherence, 'redundancy': bw.redundancy, 'duration_penalty': bw.duration_penalty
        }
        
        # Baselines
        run_selector('Baseline B (Semantic BGE)', {**bw_dict, 'concept': 0.0, 'coverage': 0.0, 'redundancy': 0.0, 'coherence': 0.0}, use_cps=False)
        run_selector('Full VidFusion', bw_dict)
        run_selector('Full minus concept signal', {**bw_dict, 'concept': 0.0}, use_cps=False)
        run_selector('Full minus coverage', {**bw_dict, 'coverage': 0.0})
        run_selector('Full minus redundancy', {**bw_dict, 'redundancy': 0.0})
        run_selector('Full minus coherence', {**bw_dict, 'coherence': 0.0})
        run_selector('Full minus KP ordering', bw_dict, use_narrative=False)

        for m_name, (selected, lat_sel, lat_prep) in methods.items():
            if not selected: continue
            m_metrics = evaluate(selected, case['meta']['concepts'], all_sentences, budget_seconds, total_aggregate, pool_seconds)
            src_cov = len(set(getattr(s, 'video_id', None) for s in selected)) / max(len(case['videos']), 1)
            cross_jumps, adj_coherence, top_viol = evaluate_ordering(selected, embedder)
            
            m_metrics.update({
                'case': case['name'], 'set': case['set'], 'tuned': case['tuned'],
                'method': m_name, 'lat_sel': lat_sel, 'lat_prep': lat_prep,
                'source_coverage': src_cov, 'cross_jumps': cross_jumps, 'adj_coherence': adj_coherence,
                'topic_violations': top_viol
            })
            # Drop F1/Recall/Precision explicitly because it's a new holdout without gold truths
            m_metrics['precision'] = -1
            m_metrics['recall'] = -1
            m_metrics['f1'] = -1
            
            rows.append(m_metrics)
            print(f"  {m_name:<25}: DurAcc {m_metrics['dur_acc']:.2f}, Latency {lat_sel:.2f}s")

    json.dump(rows, open('evaluation/m2_results_unseen.json', 'w'), indent=2)

if __name__ == '__main__':
    run_evaluation()
