import json, os, sys
import numpy as np
from collections import defaultdict
HERE=os.path.dirname(os.path.abspath(__file__))
rows=[r for r in json.load(open(os.path.join(HERE,'results.json')))]
live=[r for r in rows if not r['saturated']]
print(f"{len(rows)} evaluations, {len(live)} non-saturated (budget < 90% of selectable pool)\n")

def f1(r):
    p,q=r['precision'],r['recall']
    return 2*p*q/(p+q) if p+q else 0.0
for r in rows: r['f1']=f1(r)

CFG=['A_coverage','B_importance','C_balanced']

print("="*78); print("OVERALL (mean over all videos x durations, non-saturated)"); print("="*78)
print(f"{'objective':<14} {'recall':>7} {'precis':>7} {'F1':>7} {'redund':>7} {'deciles':>8} {'complete':>9} {'midcut':>7} {'dur_acc':>8}")
for c in CFG:
    s=[r for r in live if r['config']==c]
    print(f"{c:<14} {np.mean([r['recall'] for r in s]):>7.3f} {np.mean([r['precision'] for r in s]):>7.3f} "
          f"{np.mean([r['f1'] for r in s]):>7.3f} {np.mean([r['redundancy'] for r in s]):>7.3f} "
          f"{np.mean([r['deciles'] for r in s]):>8.1f} {np.mean([r['complete_rate'] for r in s]):>9.3f} "
          f"{sum(r['midcut'] for r in s):>7} {np.mean([r['dur_acc'] for r in s]):>8.3f}")

print("\n"+"="*78); print("BY GENRE  (does one objective win everywhere, or only on average?)"); print("="*78)
genres=sorted({r['genre'] for r in live})
print(f"{'genre':<20} {'metric':<10} " + " ".join(f"{c:>13}" for c in CFG) + "   winner")
for g in genres:
    for metric in ('recall','precision','f1'):
        vals=[np.mean([r[metric] for r in live if r['genre']==g and r['config']==c]) for c in CFG]
        win=CFG[int(np.argmax(vals))]
        print(f"{g:<20} {metric:<10} " + " ".join(f"{v:>13.3f}" for v in vals) + f"   {win}")
    print()

print("="*78); print("BY DURATION"); print("="*78)
print(f"{'minutes':>7} {'metric':<10} " + " ".join(f"{c:>13}" for c in CFG) + "   winner")
for m in (5,10,15,20,30):
    for metric in ('recall','precision','f1'):
        sub=[r for r in live if r['minutes']==m]
        if not sub: continue
        vals=[np.mean([r[metric] for r in sub if r['config']==c]) for c in CFG]
        print(f"{m:>7} {metric:<10} " + " ".join(f"{v:>13.3f}" for v in vals) + f"   {CFG[int(np.argmax(vals))]}")
    print()

print("="*78); print("GENERALISATION: per-(video,duration) head-to-head on F1"); print("="*78)
wins=defaultdict(int); pairs=defaultdict(list)
for r in live: pairs[(r['video'],r['minutes'])].append(r)
n=0
for k,v in pairs.items():
    if len(v)<3: continue
    n+=1
    wins[max(v,key=lambda x:x['f1'])['config']]+=1
print(f"cases: {n}")
for c in CFG: print(f"  {c:<14} wins {wins[c]:>3}  ({wins[c]/max(n,1)*100:.0f}%)")

print("\nper-video F1 (mean over durations):")
print(f"{'video':<14} {'genre':<20} " + " ".join(f"{c:>13}" for c in CFG) + "   winner")
for vid in sorted({r['video'] for r in live}):
    sub=[r for r in live if r['video']==vid]
    g=sub[0]['genre']
    vals=[np.mean([r['f1'] for r in sub if r['config']==c]) for c in CFG]
    print(f"{vid:<14} {g:<20} " + " ".join(f"{v:>13.3f}" for v in vals) + f"   {CFG[int(np.argmax(vals))]}")
