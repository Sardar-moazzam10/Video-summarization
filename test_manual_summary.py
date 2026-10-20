#!/usr/bin/env python3
"""
Quick manual test script for Video Summarization pipeline.
Usage:
    ./venv/bin/python test_manual_summary.py <YOUTUBE_ID_OR_URL> [duration_minutes]

Example:
    ./venv/bin/python test_manual_summary.py _QXjl-4IuzY 5
"""
import sys
import os
import time
import asyncio
import re

# Set environment
os.environ.setdefault("VIDEO_CACHE_ENABLED", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.api.merge import process_merge_job, _active_jobs, get_jobs_collection
from backend.models.job import MergeJob, JobStatus


def extract_video_id(url_or_id: str) -> str:
    """Extract YouTube video ID from URL or return raw ID."""
    match = re.search(r"(?:v=|\/embed\/|\/watch\?v=|youtu\.be\/|\/v\/)([a-zA-Z0-9_-]{11})", url_or_id)
    if match:
        return match.group(1)
    if len(url_or_id) == 11 and not ("/" in url_or_id or "?" in url_or_id):
        return url_or_id
    # Fallback to stripped string
    return url_or_id.strip()


async def main():
    if len(sys.argv) < 2:
        print("\n❌ Error: Please provide a YouTube Video ID or URL!")
        print("\nUsage:")
        print("  ./venv/bin/python test_manual_summary.py <YOUTUBE_ID_OR_URL> [target_minutes]")
        print("\nExample:")
        print("  ./venv/bin/python test_manual_summary.py _QXjl-4IuzY 5")
        sys.exit(1)

    raw_input = sys.argv[1]
    video_id = extract_video_id(raw_input)
    target_duration = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    job_id = f"manual_test_{int(time.time())}"

    print("=" * 65)
    print(f"🎬 VidFusion Manual Test")
    print(f"   Video ID:        {video_id}")
    print(f"   Target Duration: {target_duration} minutes")
    print(f"   Job ID:          {job_id}")
    print("=" * 65)

    job = MergeJob(
        job_id=job_id,
        video_ids=[video_id],
        target_duration_minutes=target_duration,
        highlight_duration_seconds=target_duration * 60,
        generate_video=True,
        generate_audio=True,
        style="analytical",
    )
    _active_jobs[job_id] = job

    jobs_collection = await get_jobs_collection()
    await jobs_collection.insert_one(job.model_dump())

    video_ready_time = None
    start_time = time.time()

    async def watch_db():
        nonlocal video_ready_time
        while job_id in _active_jobs:
            doc = await jobs_collection.find_one({"job_id": job_id})
            if doc and doc.get("video_path") and not video_ready_time:
                video_ready_time = time.time() - start_time
                print("\n" + "⚡" * 30)
                print(f"🎉 VIDEO HIGHLIGHT REEL READY IN: {video_ready_time:.1f}s ({video_ready_time/60:.2f} min)!")
                print(f"📁 Video Path: {doc.get('video_path')}")
                print(f"⚡" * 30 + "\n")
            await asyncio.sleep(0.5)

    watcher = asyncio.create_task(watch_db())

    try:
        await process_merge_job(job_id)
    finally:
        watcher.cancel()

    total_time = time.time() - start_time
    final_doc = await jobs_collection.find_one({"job_id": job_id})

    print("\n" + "=" * 65)
    print("🏁 TEST SUMMARY:")
    if video_ready_time:
        print(f"   ⚡ Video Highlight Reel Ready:  {video_ready_time:.1f}s")
    print(f"   ⏱️  Total Processing Time:       {total_time:.1f}s")
    print(f"   📊 Final Job Status:             {final_doc.get('status') if final_doc else 'UNKNOWN'}")
    print(f"   🎬 Video Path:                   {final_doc.get('video_path') if final_doc else 'None'}")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())

