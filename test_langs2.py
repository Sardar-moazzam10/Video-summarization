from youtube_transcript_api import YouTubeTranscriptApi
video_ids = ["2nIoXBvQKhs", "PeMlggyqz0Y", "ukzFI9rgwfU", "qYNweeDHiyU"]
api = YouTubeTranscriptApi()
for vid in video_ids:
    try:
        tlist = api.list(vid)
        langs = [t.language_code for t in tlist]
        print(f"{vid}: {langs}")
    except Exception as e:
        print(f"{vid}: Error")
