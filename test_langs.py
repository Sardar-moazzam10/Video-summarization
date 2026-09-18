from youtube_transcript_api import YouTubeTranscriptApi

video_ids = ["2nIoXBvQKhs", "cqDQV5g7zHo", "Nkaa8fPEtQk", "WCM1MKndvnQ", "35lS7gJVTyA", "isdQsBs5U3U", "nm1TxQj9IsQ", "qYNweeDHiyU", "xAt1xcC6qfM", "4orFNDnOeNY", "jGwO_UgTS7I", "PeMlggyqz0Y", "7eh4d6sabA0", "JpYA7WXkHyI", "QmOF0crdyRU", "ukzFI9rgwfU"]

api = YouTubeTranscriptApi()
for vid in video_ids:
    try:
        tlist = api.list(vid)
        langs = [t.language_code for t in tlist]
        print(f"{vid}: {langs}")
    except Exception:
        pass
