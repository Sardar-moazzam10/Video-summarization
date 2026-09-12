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

from backend.api.merge import process_merge_job, _active_jobs
from backend.models.job import MergeJob
import shutil

async def run_diagnostics():
    job_id = "diag_test_after_fix"
    print(f"Starting diagnostic job: {job_id}")
    
    # clear cache for this video to ensure we test the download path
    vid_cache = os.path.join("audio_cache", "video_cache", "xAt1xcC6qfM")
    if os.path.exists(vid_cache):
        print(f"Clearing cache dir: {vid_cache}")
        shutil.rmtree(vid_cache)
        
    job = MergeJob(
        job_id=job_id,
        video_ids=["xAt1xcC6qfM"],
        target_duration_minutes=10,
        highlight_duration_seconds=600,
        generate_video=True,
        style="analytical"
    )
    _active_jobs[job_id] = job
    
    # insert into db
    from backend.api.merge import get_jobs_collection
    jobs_collection = await get_jobs_collection()
    await jobs_collection.insert_one(job.model_dump())
    
    start_time = time.time()
    await process_merge_job(job_id)
    end_time = time.time()
    
    print(f"DIAGNOSTIC COMPLETE. Total time: {end_time - start_time:.2f}s")

if __name__ == "__main__":
    asyncio.run(run_diagnostics())
