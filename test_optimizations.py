
from youtube_transcript_api import YouTubeTranscriptApi
import subprocess
import shutil
import os


def test_transcript():
    video_id = "KTn61FEkIHo" # From the user's logs
    print(f"Testing transcript for {video_id}...")
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        print(f"Success! Got {len(transcript)} segments.")
        print(f"First segment: {transcript[0]}")
    except Exception as e:
        print(f"Failed: {e}")

def test_ytdlp_sections():
    print("Testing yt-dlp --download-sections support...")
    video_id = "KTn61FEkIHo"
    url = f"https://www.youtube.com/watch?v={video_id}"
    # Download 5 seconds
    cmd = [
        "yt-dlp",
        "--download-sections", "*00:00-00:05",
        "-f", "mp4",
        "-o", "test_section.mp4",
        url
    ]
    try:
        subprocess.run(cmd, check=True)
        if os.path.exists("test_section.mp4"):
            print("Success! Downloaded section.")
            os.remove("test_section.mp4")
        else:
            print("Failed: File not found after download.")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_transcript()
    test_ytdlp_sections()

