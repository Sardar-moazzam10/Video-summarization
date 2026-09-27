import json
from youtube_transcript_api import YouTubeTranscriptApi

videos = {
    'QW_jlUn4gA8': 'This Is What a Godlike Civilization Would Look Like',
    'yDAAlojz8NU': 'This Is the Scariest Place in The Universe',
    'isdLel273rQ': 'The Paradox of an Infinite Universe',
    'SbvAaDN1bpE': 'Why Scientists Are Puzzled By This Virus',
    'lsbcN9-jU1Y': 'The Second Punic War - OverSimplified (Part 1)',
    'ewLpXw6uN28': 'Henry VIII - OverSimplified',
    '26EivpCPHnQ': 'Three Kingdoms - OverSimplified'
}

with open('evaluation/transcripts.json', 'r') as f:
    transcripts = json.load(f)

for vid in videos.keys():
    try:
        tl = YouTubeTranscriptApi().list(vid)
        try:
            fetched = tl.find_manually_created_transcript(['en'])
        except:
            fetched = tl.find_generated_transcript(['en'])
        
        data = fetched.fetch()
        
        clean_data = []
        for d in data:
            try:
                # older versions might use attributes
                clean_data.append({'text': str(d.text), 'start': float(d.start), 'duration': float(d.duration)})
            except:
                pass
            
        if clean_data:
            transcripts[vid] = clean_data
            print(f"Added {vid}")
    except Exception as e:
        print(f"Failed {vid}: {e}")

with open('evaluation/transcripts.json', 'w') as f:
    json.dump(transcripts, f, indent=2)

