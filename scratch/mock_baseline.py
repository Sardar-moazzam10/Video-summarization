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

# Mock MongoDB
class MockCollection:
    async def insert_one(self, doc): return None
    async def find_one(self, query): return doc_store.get(query.get("job_id"))
    async def update_one(self, query, update):
        if query.get("job_id") in doc_store:
            doc = doc_store[query.get("job_id")]
            if "$set" in update:
                doc.update(update["$set"])
        return None

doc_store = {}
mock_col = MockCollection()

async def mock_get_jobs_collection():
    return mock_col

import backend.api.merge
backend.api.merge.get_jobs_collection = mock_get_jobs_collection

from backend.api.merge import process_merge_job, _active_jobs
from backend.models.job import MergeJob

async def run():
    video_id = "_QXjl-4IuzY"
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
        doc_store[job_id] = job.model_dump()
        
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
        job_doc = doc_store.get(job_id)
        if job_doc and "fusion_metadata" in job_doc:
            print(f"Fusion Metadata: {job_doc['fusion_metadata']}")
        if job_doc and "selection_metrics" in job_doc:
            print(f"Selection Metrics: {job_doc['selection_metrics']}")

if __name__ == "__main__":
    asyncio.run(run())
