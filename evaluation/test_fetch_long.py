import json
from youtube_transcript_api import YouTubeTranscriptApi

vids = ['KkMDCCdjyW8', 'sRuyBNxCkGQ']
for vid in vids:
    try:
        tl = YouTubeTranscriptApi().list(vid)
        try:
            t = tl.find_manually_created_transcript(['en'])
        except:
            t = tl.find_generated_transcript(['en'])
        data = t.fetch()
        print(f"Fetched {vid}: {len(data)} snippets, total dur ~{data[-1].start/60:.1f} min")
    except Exception as e:
        print(f"Failed {vid}: {e}")
