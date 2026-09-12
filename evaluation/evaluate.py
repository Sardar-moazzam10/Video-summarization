"""
Evaluate the EXISTING selector (unmodified) against hand-authored gold sets.

Three objectives compared, differing only in weights:
  A coverage-heavy    - represent the whole timeline
  B importance-heavy  - take the most important material wherever it is
  C balanced          - the shipped default

Metrics, all computed against gold windows the pipeline never sees.
"""
import sys, os, json, asyncio, time
import numpy as np
sys.path.insert(0, '/home/weiblocks/Desktop/Video-summarization')
HERE = os.path.dirname(os.path.abspath(__file__))
import pymongo

from backend.services.semantic_segmenter import build_semantic_segments, build_sentences
from backend.services.concept_extractor import extract_concepts, clear_cache
from backend.services.coverage_selector import select_segments, SelectionWeights
from backend.core.config import get_settings

S = get_settings()
db = pymongo.MongoClient('mongodb://localhost:27017/')['aivideosummerizer']
GOLD = json.load(open(os.path.join(HERE, 'gold.json')))

CONFIGS = {
    'A_coverage':   dict(concept=0.20, semantic=0.15, coverage=0.45, coherence=0.10, redundancy=0.25, duration_penalty=0.05),
    'B_importance': dict(concept=0.55, semantic=0.25, coverage=0.05, coherence=0.10, redundancy=0.25, duration_penalty=0.05),
    'C_balanced':   dict(concept=0.35, semantic=0.20, coverage=0.25, coherence=0.10, redundancy=0.25, duration_penalty=0.05),
}
TIER_W = {'core': 1.0, 'secondary': 0.5}
MIN_OVERLAP = 8.0          # seconds of a gold window a segment must hit to "cover" it


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def evaluate(picked, gold_concepts, sentences, budget, total, seg_pool_seconds):
    sel = [(s.start_time, s.end_time) for s in picked]
    sel_total = sum(b - a for a, b in sel) or 1e-6

    # --- 1/2/3: gold-concept recall, precision, redundancy ---
    covered_w = 0.0; total_w = 0.0
    first_hit_time = 0.0; extra_hit_time = 0.0
    for c in gold_concepts:
        w = TIER_W[c['tier']]; total_w += w
        hits = []
        for (s0, s1) in sel:
            ov = max(overlap(s0, s1, g0, g1) for g0, g1 in c['windows'])
            if ov >= MIN_OVERLAP:
                hits.append(ov)
        if hits:
            covered_w += w
            first_hit_time += hits[0]
            extra_hit_time += sum(hits[1:])
    recall = covered_w / max(total_w, 1e-6)

    on_gold = 0.0
    for (s0, s1) in sel:
        best = 0.0
        for c in gold_concepts:
            for g0, g1 in c['windows']:
                best = max(best, overlap(s0, s1, g0, g1))
        on_gold += best
    precision = on_gold / sel_total
    redundancy = extra_hit_time / max(first_hit_time + extra_hit_time, 1e-6)

    # --- 4: temporal coverage ---
    bins = np.zeros(10)
    for (s0, s1) in sel:
        for b in range(10):
            lo, hi = b * total / 10, (b + 1) * total / 10
            bins[b] += overlap(s0, s1, lo, hi)
    deciles = int((bins > 0).sum())

    # --- 5/6: complete thoughts and mid-sentence cuts ---
    starts = {round(s.start, 3) for s in sentences}
    ends = {round(s.end, 3) for s in sentences}
    midcut = sum(1 for s in picked
                 if round(s.start_time, 3) not in starts or round(s.end_time, 3) not in ends)
    complete = sum(1 for s in picked
                   if round(s.start_time, 3) in starts and round(s.end_time, 3) in ends
                   and len(s.sentences) >= 2)
    complete_rate = complete / max(len(picked), 1)

    # --- 7: duration accuracy ---
    reachable = min(budget, seg_pool_seconds)
    dur_acc = 1.0 - abs(sel_total - reachable) / max(reachable, 1e-6)

    return dict(recall=recall, precision=precision, redundancy=redundancy,
                deciles=deciles, complete_rate=complete_rate, midcut=midcut,
                dur_acc=max(dur_acc, 0.0), seconds=sel_total, n=len(picked),
                saturated=budget > 0.9 * seg_pool_seconds)


if __name__ == "__main__":
    rows = []
    for vid, meta in GOLD.items():
        if vid.startswith('_'):
            continue
        raw = db.transcripts.find_one({'video_id': vid})['transcript']
        total = float(raw[-1]['start']) + float(raw[-1].get('duration', 0))
        sentences = build_sentences(raw)
        t0 = time.time()
        segs = build_semantic_segments(raw, vid, S.SEGMENT_MIN_SECONDS, S.SEGMENT_MAX_SECONDS)
        clear_cache()
        cps = asyncio.run(extract_concepts(segs, total_duration=total, top_k=S.CONCEPT_TOP_K, use_llm=False))
        pool = sum(s.duration for s in segs)
        print(f"[{vid}] {meta['genre']:<20} {len(segs)} segments, pool {pool/60:.0f}min, "
              f"analysis {time.time()-t0:.0f}s", flush=True)

        for cname, cfg in CONFIGS.items():
            w = SelectionWeights(**cfg)
            for mins in (5, 10, 15, 20, 30):
                r = select_segments(segs, mins * 60, cps, w, None, None, total)
                if not r.segments:
                    continue
                m = evaluate(r.segments, meta['concepts'], sentences, mins * 60, total, pool)
                m.update(video=vid, genre=meta['genre'], config=cname, minutes=mins)
                rows.append(m)

    json.dump(rows, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    print(f"\n{len(rows)} evaluations -> results.json")
