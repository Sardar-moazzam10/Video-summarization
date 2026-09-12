"""Condensed timestamped read of a transcript, for manual gold-set construction."""
import sys, pymongo
vid=sys.argv[1]; block=float(sys.argv[2]) if len(sys.argv)>2 else 60.0
words=int(sys.argv[3]) if len(sys.argv)>3 else 32
db=pymongo.MongoClient('mongodb://localhost:27017/')['aivideosummerizer']
t=db.transcripts.find_one({'video_id':vid})['transcript']
total=float(t[-1]['start'])+float(t[-1].get('duration',0))
print(f"# {vid}  {total/60:.1f} min")
cur=0.0; buf=[]
for s in t:
    st=float(s.get('start',0))
    if st >= cur+block and buf:
        txt=" ".join(" ".join(buf).split()[:words])
        print(f"{int(cur)//60:>3}:{int(cur)%60:02d}  {txt}")
        cur=st; buf=[]
    if not buf: cur=min(cur,st) if buf else (cur if st<cur+block else st)
    buf.append(s.get('text',''))
if buf:
    print(f"{int(cur)//60:>3}:{int(cur)%60:02d}  {' '.join(' '.join(buf).split()[:words])}")
