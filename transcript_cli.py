import argparse
from youtube_transcript_api import YouTubeTranscriptApi

def main():
    parser = argparse.ArgumentParser(description="Fetch YouTube transcript with optional cookies.txt")
    parser.add_argument("video_id", help="The YouTube video ID (e.g. mYVzme2fybU)")
    parser.add_argument("--cookies", help="Path to cookies.txt (Netscape format)", default=None)

    args = parser.parse_args()

    try:
        if args.cookies:
            transcript = YouTubeTranscriptApi.get_transcript(args.video_id, cookies=args.cookies)
        else:
            transcript = YouTubeTranscriptApi.get_transcript(args.video_id)

        for entry in transcript:
            print(f"{entry['start']:.2f}s: {entry['text']}")
    except Exception as e:
        print(f"❌ Error fetching transcript: {e}")

if __name__ == "__main__":
    main()
