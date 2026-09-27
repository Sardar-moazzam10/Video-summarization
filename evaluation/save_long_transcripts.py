import json
from youtube_transcript_api import YouTubeTranscriptApi

vids = {
    'KkMDCCdjyW8': 'Stanford CS106A - Programming Methodology Lecture 1',
    'sRuyBNxCkGQ': 'Stanford CS149 - Parallel Computing Lecture 15'
}

with open('evaluation/transcripts.json', 'r') as f:
    transcripts = json.load(f)

for vid in vids:
    tl = YouTubeTranscriptApi().list(vid)
    try:
        t = tl.find_manually_created_transcript(['en'])
    except:
        t = tl.find_generated_transcript(['en'])
    data = t.fetch()
    clean_data = [{'text': str(d.text), 'start': float(d.start), 'duration': float(d.duration)} for d in data]
    transcripts[vid] = clean_data
    print(f"Saved {vid}: {len(clean_data)} segments")

with open('evaluation/transcripts.json', 'w') as f:
    json.dump(transcripts, f, indent=2)

print("Saved long-form transcripts successfully.")
