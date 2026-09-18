import os, sys, json, time, re
sys.path.insert(0, '.')

from backend.services.duration_profiles import get_profile
from backend.services.summarization_service import get_summarization_service, _looks_degenerate
from backend.services.duration_profiles import get_summarization_config
import backend.services.summarization_service as s_mod

# MOCK OUT GROUNDING CHECK TO AVOID SBERT!
import backend.services.summarization_policy
def dummy_check(s, t, p): return True, None
backend.services.summarization_policy.check_grounding = dummy_check

print("Loading summaries...")
SUMMARIES = json.load(open("evaluation/summaries.json"))
vid = "7eh4d6sabA0"
narrative = SUMMARIES[vid]
print(f"Narrative words: {len(narrative.split())}")

PROFILE = get_profile(10)

def test_frac(frac, pen):
    print(f"\n--- Testing FRAC={frac}, PENALTY={pen} ---")
    s_mod.MAX_MIN_LENGTH_INPUT_FRACTION = frac
    svc = get_summarization_service()
    cfg = get_summarization_config(PROFILE)
    cfg.length_penalty = pen
    
    t0 = time.time()
    try:
        sm, _ = svc.summarize_with_policy(narrative, PROFILE.target_words, PROFILE)
        wc = len(sm.split())
        degen, _ = _looks_degenerate(sm)
        print(f"Result: {wc} words. Degen? {degen}. Time: {time.time()-t0:.1f}s")
    except Exception as e:
        print("ERR", e)

test_frac(0.25, 1.5)
test_frac(0.40, 2.0)
test_frac(0.60, 2.5)
test_frac(0.80, 2.5)
