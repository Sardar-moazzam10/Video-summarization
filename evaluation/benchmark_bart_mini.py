import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import torch; torch.set_num_threads(1); os.environ['OMP_NUM_THREADS']='1'

from backend.services.duration_profiles import get_profile
from backend.services.summarization_service import get_summarization_service
from backend.services.duration_profiles import get_summarization_config
import backend.services.summarization_service as s_mod

print("Loading summaries...")
SUMMARIES = json.load(open("evaluation/summaries.json"))
vid = "7eh4d6sabA0"
narrative = SUMMARIES[vid]

PROFILE = get_profile(10)
svc = get_summarization_service()
cfg = get_summarization_config(PROFILE)

print("Running summarize_with_policy...")
try:
    summary, decision = svc.summarize_with_policy(narrative, PROFILE.target_words, PROFILE)
    print("Done! Words:", len(summary.split()))
except Exception as e:
    import traceback
    traceback.print_exc()
