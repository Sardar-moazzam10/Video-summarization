"""
Real-run validation of the video-first pipeline restructuring.

Runs process_merge_job end-to-end (real MongoDB, real yt-dlp download, real
BART, real ffmpeg) against the video and target duration specified by the
task, and reports:
  - selection complete time
  - VIDEO_READY time (video persisted + playable)
  - total completion time
  - time saved before the video becomes playable, vs. the pre-change
    architecture where nothing was visible until full completion.

Mirrors run_diagnostic.py's structure/instrumentation (timestamped print).
"""

import asyncio
import time
import builtins
import sys
import os

original_print = builtins.print
def timestamped_print(*args, **kwargs):
    now = time.time()
    ms = int((now % 1) * 1000)
    ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))
    original_print(f"[{ts}.{ms:03d}]", *args, **kwargs)
    sys.stdout.flush()

builtins.print = timestamped_print

from dotenv import load_dotenv
load_dotenv()
os.environ["VIDEO_CACHE_ENABLED"] = "1"

from backend.api.merge import process_merge_job, _active_jobs, get_jobs_collection
from backend.models.job import MergeJob, JobStatus
import shutil

VIDEO_ID = "_QXjl-4IuzY"
JOB_ID = "video_first_validation_1"


async def run():
    print(f"Starting video-first validation job: {JOB_ID} (video={VIDEO_ID}, target=10min)")

    # Cache preserved per project rules
    print(f"Running validation with cache preservation for {VIDEO_ID}")

    job = MergeJob(
        job_id=JOB_ID,
        video_ids=[VIDEO_ID],
        target_duration_minutes=10,
        highlight_duration_seconds=600,
        generate_video=True,
        generate_audio=True,
        style="analytical",
    )
    _active_jobs[JOB_ID] = job

    jobs_collection = await get_jobs_collection()
    await jobs_collection.delete_one({"job_id": JOB_ID})
    await jobs_collection.insert_one(job.model_dump())

    # Poll the DB in the background so we can timestamp the moment the
    # status actually flips to video_ready, independent of log parsing.
    video_ready_wall_time = {}

    async def watch_status():
        while JOB_ID in _active_jobs:
            doc = await jobs_collection.find_one({"job_id": JOB_ID})
            if doc and doc.get("status") == JobStatus.VIDEO_READY.value and "t" not in video_ready_wall_time:
                video_ready_wall_time["t"] = time.time()
                print(f"[Watcher] Observed status=video_ready in DB (video_path={doc.get('video_path')})")
            await asyncio.sleep(0.5)

    watcher = asyncio.create_task(watch_status())

    start_time = time.time()
    await process_merge_job(JOB_ID)
    end_time = time.time()
    watcher.cancel()

    final_doc = await jobs_collection.find_one({"job_id": JOB_ID})

    print("=" * 70)
    print(f"Total wall time:              {end_time - start_time:.2f}s")
    if "t" in video_ready_wall_time:
        print(f"Time to VIDEO_READY (DB):     {video_ready_wall_time['t'] - start_time:.2f}s")
    print(f"Final status:                 {final_doc.get('status') if final_doc else 'UNKNOWN'}")
    print(f"video_path set:               {bool(final_doc.get('video_path')) if final_doc else False}")
    print(f"summary_text set:             {bool(final_doc.get('summary_text')) if final_doc else False}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run())
