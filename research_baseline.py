import asyncio
import time
import builtins
import sys
import os

from dotenv import load_dotenv
load_dotenv()
os.environ["VIDEO_CACHE_ENABLED"] = "1"

original_print = builtins.print
def timestamped_print(*args, **kwargs):
    now = time.time()
    ms = int((now % 1) * 1000)
    ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))
    original_print(f"[{ts}.{ms:03d}]", *args, **kwargs)
    sys.stdout.flush()

builtins.print = timestamped_print

from backend.api.merge import process_merge_job, _active_jobs
from backend.models.job import MergeJob
from backend.api.merge import get_jobs_collection

async def run():
    video_id = "_QXjl-4IuzY"
    
    # 2 warm runs
    for i in range(2):
        print(f"\n--- WARM RUN {i+1} ---")
        job_id = f"research_base_{i}"
        
        job = MergeJob(
            job_id=job_id,
            video_ids=[video_id],
            target_duration_minutes=10,
            highlight_duration_seconds=600,
            generate_video=True,
            style="analytical"
        )
        _active_jobs[job_id] = job
        
        jobs_collection = await get_jobs_collection()
        await jobs_collection.insert_one(job.model_dump())
        
        # Override asyncio.sleep to prevent 5m hang at the end
        import backend.api.merge
        import asyncio
        original_sleep = asyncio.sleep
        
        async def mock_sleep(seconds):
            if seconds == 300:
                print("Skipping 300s sleep")
            else:
                await original_sleep(seconds)
                
        backend.api.merge.asyncio.sleep = mock_sleep
        
        start_time = time.time()
        await process_merge_job(job_id)
        end_time = time.time()
        
        backend.api.merge.asyncio.sleep = original_sleep
        
        print(f"RUN {i+1} COMPLETE. Total time: {end_time - start_time:.2f}s")
        
        job_doc = await jobs_collection.find_one({"job_id": job_id})
        
        if job_doc and "fusion_metadata" in job_doc:
            print(f"Fusion Metadata: {job_doc['fusion_metadata']}")
        if job_doc and "selection_metrics" in job_doc:
            print(f"Selection Metrics: {job_doc['selection_metrics']}")

if __name__ == "__main__":
    asyncio.run(run())
