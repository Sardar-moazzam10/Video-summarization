"""Cache each video's analysis once, then sweep the coverage/importance balance."""
import sys, os, json, pickle, asyncio
import numpy as np
sys.path.insert(0,'/home/weiblocks/Desktop/Video-summarization')
HERE=os.path.dirname(os.path.abspath(__file__))
import pymongo
from backend.services.semantic_segmenter import build_semantic_segments, build_sentences
from backend.services.concept_extractor import extract_concepts, clear_cache
from backend.services.coverage_selector import select_segments, SelectionWeights
from backend.core.config import get_settings
sys.path.insert(0,HERE)
from evaluate import evaluate, TIER_W

S=get_settings(); db=pymongo.MongoClient('mongodb://localhost:27017/')['aivideosummerizer']
GOLD=json.load(open(f'{HERE}/gold.json'))
CACHE=f'{HERE}/analyses.pkl'

if os.path.exists(CACHE):
    A=pickle.load(open(CACHE,'rb'))
else:
    A={}
    for vid,meta in GOLD.items():
        if vid.startswith('_'): continue
        raw=db.transcripts.find_one({'video_id':vid})['transcript']
        total=float(raw[-1]['start'])+float(raw[-1].get('duration',0))
        sents=build_sentences(raw)
        segs=build_semantic_segments(raw,vid,S.SEGMENT_MIN_SECONDS,S.SEGMENT_MAX_SECONDS)
        clear_cache()
        cps=asyncio.run(extract_concepts(segs,total_duration=total,top_k=S.CONCEPT_TOP_K,use_llm=False))
        A[vid]=dict(segs=segs,cps=cps,sents=sents,total=total,pool=sum(s.duration for s in segs),
                    gold=meta['concepts'],genre=meta['genre'])
        print(f"cached {vid}",flush=True)
    pickle.dump(A,open(CACHE,'wb'))

def run(cov):
    """coverage weight cov; concept takes the remainder of the 0.60 content budget."""
    con=max(0.0, 0.80-cov-0.20)           # semantic fixed at 0.20
    w=SelectionWeights(concept=con,semantic=0.20,coverage=cov,coherence=0.10,
                       redundancy=0.25,duration_penalty=0.05)
    out=[]
    for vid,a in A.items():
        for mins in (5,10,15,20,30):
            r=select_segments(a['segs'],mins*60,a['cps'],w,None,None,a['total'])
            if not r.segments: continue
            m=evaluate(r.segments,a['gold'],a['sents'],mins*60,a['total'],a['pool'])
            m.update(video=vid,genre=a['genre'],minutes=mins,cov=cov)
            m['f1']=2*m['precision']*m['recall']/max(m['precision']+m['recall'],1e-9)
            out.append(m)
    return out

GRID=[0.05,0.15,0.25,0.35,0.45,0.55,0.65]
allres={}
print(f"\n{'cov':>5} {'concept':>8} | {'recall':>7} {'precis':>7} {'F1':>7} {'redund':>7} {'dur_acc':>8} {'deciles':>8}")
for cov in GRID:
    res=run(cov); allres[cov]=res
    print(f"{cov:>5.2f} {max(0.0,0.60-cov):>8.2f} | {np.mean([r['recall'] for r in res]):>7.3f} "
          f"{np.mean([r['precision'] for r in res]):>7.3f} {np.mean([r['f1'] for r in res]):>7.3f} "
          f"{np.mean([r['redundancy'] for r in res]):>7.3f} {np.mean([r['dur_acc'] for r in res]):>8.3f} "
          f"{np.mean([r['deciles'] for r in res]):>8.1f}", flush=True)

print("\nF1 by genre at each coverage weight:")
genres=sorted({r['genre'] for r in allres[GRID[0]]})
print(f"{'genre':<20} " + " ".join(f"{c:>6.2f}" for c in GRID) + "   best")
for g in genres:
    vals=[np.mean([r['f1'] for r in allres[c] if r['genre']==g]) for c in GRID]
    print(f"{g:<20} " + " ".join(f"{v:>6.3f}" for v in vals) + f"   {GRID[int(np.argmax(vals))]:.2f}")

print("\nLEAVE-ONE-GENRE-OUT: pick coverage on the other genres, score on the held-out one")
print(f"{'held-out genre':<20} {'picked':>7} {'held-out F1':>12} {'F1 @0.25 default':>18} {'delta':>7}")
deltas=[]
for g in genres:
    train=[(c,np.mean([r['f1'] for r in allres[c] if r['genre']!=g])) for c in GRID]
    pick=max(train,key=lambda x:x[1])[0]
    held=np.mean([r['f1'] for r in allres[pick] if r['genre']==g])
    base=np.mean([r['f1'] for r in allres[0.25] if r['genre']==g])
    deltas.append(held-base)
    print(f"{g:<20} {pick:>7.2f} {held:>12.3f} {base:>18.3f} {held-base:>+7.3f}")
print(f"{'mean delta':<20} {'':>7} {'':>12} {'':>18} {np.mean(deltas):>+7.3f}")
json.dump({str(k):v for k,v in allres.items()}, open(f'{HERE}/sweep.json','w'))
