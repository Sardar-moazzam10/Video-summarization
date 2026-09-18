import os, sys, json, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))

import torch
torch.set_num_threads(1)
os.environ['OMP_NUM_THREADS'] = '1'

from evaluation.evaluate import GOLD
from backend.services.duration_profiles import get_profile
from backend.services.summarization_service import get_summarization_service
from backend.services.duration_profiles import get_summarization_config
import backend.services.summarization_service as s_mod

SUMMARIES = json.load(open(os.path.join(HERE, "summaries.json")))
PROFILE = get_profile(10)
TARGET_WORDS = PROFILE.target_words

def _words(text): return re.findall(r"[a-z']+", text.lower())
def bigram_repetition_ratio(text):
    words = _words(text)
    if len(words) < 3: return 0.0
    grams = [tuple(words[i:i+2]) for i in range(len(words) - 1)]
    from collections import Counter
    counts = Counter(grams)
    return sum(c - 1 for c in counts.values() if c > 1) / max(len(grams), 1)
def unique_sentence_ratio(text):
    sentences = [s.lower().strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if len(s.split()) > 3]
    return len(set(sentences)) / len(sentences) if sentences else 1.0
def concept_coverage(text, concepts):
    if not concepts: return 0.0
    t = text.lower()
    return sum(1 for c in concepts if c["name"].lower().split()[0] in t) / len(concepts)
def faithfulness(summary, source):
    src = set(_words(source)); sum_words = _words(summary)
    return sum(1 for w in sum_words if w in src) / len(sum_words) if sum_words else 0.0

def run_bart_config(narrative, config_name):
    svc = get_summarization_service()
    cfg = get_summarization_config(PROFILE)
    
    # Defaults
    s_mod.MAX_MIN_LENGTH_INPUT_FRACTION = 0.25
    cfg.length_penalty = 1.5
    
    if config_name == "B_Revised_Policy":
        s_mod.MAX_MIN_LENGTH_INPUT_FRACTION = 0.40
        cfg.length_penalty = 2.0
    
    if config_name == "C_Max_Input_Fraction":
        s_mod.MAX_MIN_LENGTH_INPUT_FRACTION = 0.60
        cfg.length_penalty = 2.5
        
    t0 = time.time()
    try:
        summary, decision = svc.summarize_with_policy(narrative, TARGET_WORDS, PROFILE)
    except Exception as e:
        print("ERR", e)
        summary, decision = "", {}
    
    latency = time.time() - t0
    return {"summary": summary, "latency": latency}

print("="*60)
print(f"Phase 3B: BART Length Benchmark (target={TARGET_WORDS} words)")
print("="*60)

methods = ["A_Current", "B_Revised_Policy", "C_Max_Input_Fraction"]
all_results = []

for vid in GOLD:
    if vid.startswith("_") or vid not in SUMMARIES: continue
    narrative = SUMMARIES[vid]
    if not narrative: continue
    gold = GOLD[vid].get("concepts", [])
    
    print(f"\n[{vid}] Narrative: {len(narrative.split())} words")
    
    for m in methods:
        print(f"  {m}...", end=" ", flush=True)
        res = run_bart_config(narrative, m)
        sm = res["summary"]
        
        if not sm:
            print("FAILED")
            continue
            
        wc = len(sm.split())
        faith = faithfulness(sm, narrative)
        cov = concept_coverage(sm, gold)
        bgram = bigram_repetition_ratio(sm)
        uniq = unique_sentence_ratio(sm)
        lenacc = 1.0 - abs(wc - TARGET_WORDS) / max(TARGET_WORDS, 1)
        
        all_results.append({
            "video": vid, "method": m, "words": wc, "faith": faith, 
            "cov": cov, "bgram": bgram, "uniq": uniq, "lenacc": lenacc
        })
        print(f"{wc}w | faith={faith:.2f} cov={cov:.2f} rep={bgram:.3f}")

print("\n"+"="*60)
print("AVERAGES")
print("="*60)
for m in methods:
    rows = [r for r in all_results if r["method"] == m]
    if not rows: continue
    def avg(k): return sum(r[k] for r in rows)/len(rows)
    print(f"{m:<20} words={avg('words'):.0f} len_acc={avg('lenacc'):.3f} faith={avg('faith'):.3f} cov={avg('cov'):.3f} rep={avg('bgram'):.3f} uniq={avg('uniq'):.3f}")

