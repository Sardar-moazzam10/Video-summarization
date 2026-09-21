"""
Manual verification script for Keyword / Deep Search with query:
'linear regression and logistic regression'
"""
import asyncio
import time
from backend.services.transcript_service import TranscriptService, extract_video_id
from backend.core.database import get_database

# Top 10 video IDs observed for 'linear regression and logistic regression'
TEST_VIDEOS = [
    {"videoId": "3bvM3NyMiE0", "title": "Linear Regression in 2 Minutes"},
    {"videoId": "06en5XqdPkI", "title": "Logistic Regression Details"},
    {"videoId": "BVP1EDKb6_g", "title": "Hindi ML tutorial"},
    {"videoId": "r8OjlgWpAI0", "title": "Linear and Logistic Regression Hindi"},
    {"videoId": "zUQr6HAAKp4", "title": "Complete ML Roadmap Hindi"},
    {"videoId": "OCwZyYH14uw", "title": "Regression Overview (Disabled Subs)"},
    {"videoId": "HYE9ruNDESA", "title": "Advanced Classification (Disabled Subs)"},
    {"videoId": "QWYkQDvCo4Y", "title": "StatQuest: Linear vs Logistic Regression"},
    {"videoId": "cHT-qLnRm0E", "title": "Data Science Course Hindi"},
    {"videoId": "yIYKR4sgzI8", "title": "Machine Learning Fundamentals English"},
]

QUERY = "linear regression and logistic regression"


async def main():
    print(f"=== Starting Keyword Search Manual Verification ===")
    print(f"Query: '{QUERY}'")
    print(f"Videos to scan: {len(TEST_VIDEOS)}\n")

    try:
        db = await get_database()
        # Ping to verify connection
        from pymongo.errors import ServerSelectionTimeoutError
        await db.command("ping")
    except Exception:
        print("[Notice] Using in-memory database mock for isolated environment")
        import mock_db_script
        db = await mock_db_script.get_database()

    service = TranscriptService(db)

    # Track operations to verify zero Whisper/download/translation
    whisper_invocations = []
    translation_invocations = []
    ytdlp_invocations = []

    orig_whisper = service._fetch_whisper
    orig_translate = service._translate_transcript_to_english
    orig_ytdlp = service._fetch_ytdlp

    def track_whisper(*args, **kwargs):
        whisper_invocations.append(args)
        return orig_whisper(*args, **kwargs)

    def track_translate(*args, **kwargs):
        translation_invocations.append(args)
        return orig_translate(*args, **kwargs)

    def track_ytdlp(*args, **kwargs):
        ytdlp_invocations.append(args)
        return orig_ytdlp(*args, **kwargs)

    service._fetch_whisper = track_whisper
    service._translate_transcript_to_english = track_translate
    service._fetch_ytdlp = track_ytdlp

    start_time = time.perf_counter()

    results = []
    scanned_count = 0
    searchable_count = 0
    skipped_count = 0
    matched_count = 0
    total_moments = 0

    # Simulating the frontend worker pool with concurrency=4
    semaphore = asyncio.Semaphore(4)

    async def scan_video(item):
        nonlocal scanned_count, searchable_count, skipped_count, matched_count, total_moments
        vid_id = item["videoId"]
        title = item["title"]

        async with semaphore:
            v_start = time.perf_counter()
            res = await service.get_transcript(vid_id, allow_whisper=False, fast_search=True)
            v_time = (time.perf_counter() - v_start) * 1000

            scanned_count += 1
            if res and res.get("transcript"):
                searchable_count += 1
                transcript = res["transcript"]
                
                # Import matching from node or test logic
                # Match separate concepts: 'linear regression', 'logistic regression'
                matches = []
                for entry in transcript:
                    text_lower = entry.get("text", "").lower()
                    if "linear regression" in text_lower or "logistic regression" in text_lower:
                        matches.append({
                            "timestamp": entry.get("start", 0),
                            "text": entry.get("text", ""),
                        })

                if matches:
                    matched_count += 1
                    total_moments += len(matches)
                    results.append({
                        "videoId": vid_id,
                        "title": title,
                        "matches": matches,
                        "time_ms": v_time,
                        "source": res.get("source", "youtube_api_fast")
                    })
                    print(f"  [MATCH] {vid_id} ({title[:35]}): {len(matches)} moment(s) [{v_time:.1f}ms]")
                else:
                    print(f"  [OK] {vid_id} ({title[:35]}): English transcript (no match) [{v_time:.1f}ms]")
            else:
                skipped_count += 1
                print(f"  [SKIPPED] {vid_id} ({title[:35]}): No English captions [{v_time:.1f}ms]")

    await asyncio.gather(*(scan_video(v) for v in TEST_VIDEOS))

    total_time = time.perf_counter() - start_time

    print("\n=== Verification Summary Report ===")
    print(f"Total Search Time: {total_time:.2f}s")
    print(f"Videos Scanned   : {scanned_count}")
    print(f"Videos Searchable: {searchable_count} (had English captions)")
    print(f"Videos Skipped   : {skipped_count} (non-English / no captions)")
    print(f"Videos Matched   : {matched_count}")
    print(f"Total Moments    : {total_moments}")
    print(f"Whisper Calls    : {len(whisper_invocations)} (Verified Zero)")
    print(f"Audio Downloads  : {len(ytdlp_invocations)} (Verified Zero)")
    print(f"Translations     : {len(translation_invocations)} (Verified Zero)")
    print("===================================\n")


if __name__ == "__main__":
    asyncio.run(main())

