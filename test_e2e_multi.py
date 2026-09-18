import asyncio
import uuid
import json
from datetime import datetime
import sys
sys.path.insert(0, '.')

from backend.api.merge import process_merge_job, _active_jobs
from backend.models.job import MergeJob
from backend.core.database import get_database

async def run_test(duration_minutes):
    db = await get_database()
    jobs = db["jobs"]
    
    # 3 short videos on Machine Learning
    video_ids = ["ukzFI9rgwfU", "PeMlggyqz0Y", "qYNweeDHiyU"]
    
    job_id = str(uuid.uuid4())
    job = MergeJob(
        job_id=job_id,
        user_id="test_user",
        video_ids=video_ids,
        target_duration_minutes=duration_minutes,
        highlight_duration_seconds=duration_minutes * 60,
        generate_audio=False,
        generate_video=True,
        status="pending"
    )
    
    await jobs.insert_one(job.dict())
    _active_jobs[job_id] = job
    
    print(f"Starting {duration_minutes}-minute job {job_id}")
    import unittest.mock
    with unittest.mock.patch("asyncio.sleep", new_callable=unittest.mock.AsyncMock):
        await process_merge_job(job_id)
    
    # Save the job data to a JSON file for analysis
    job_data = await jobs.find_one({"job_id": job_id})
    job_data.pop("_id", None)
    with open(f"e2e_multi_{duration_minutes}m.json", "w") as f:
        json.dump(job_data, f, default=str, indent=2)
    
    print(f"Job finished. MP4: {job_data.get('video_path')}")
    print(f"Selected segments: {len(job_data.get('highlight_segments', []))}")

async def main():
    await run_test(5)
    await run_test(10)
    await run_test(15)

if __name__ == "__main__":
    asyncio.run(main())
