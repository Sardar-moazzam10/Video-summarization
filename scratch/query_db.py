import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def get_jobs():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["video_summarization"]
    jobs_collection = db["jobs"]
    
    # Get the latest 10-minute and 15-minute jobs
    job10 = await jobs_collection.find_one({"target_duration_minutes": 10}, sort=[("created_at", -1)])
    job15 = await jobs_collection.find_one({"target_duration_minutes": 15}, sort=[("created_at", -1)])
    
    print("=== 10 MINUTE JOB ===")
    if job10:
        print(f"Status: {job10.get('status')}")
        print(f"Video URL: {job10.get('video_url')}")
        print(f"Summary Length: {len(job10.get('summary_text', ''))} chars")
        meta = job10.get('metadata', {})
        print(f"Segments selected: {meta.get('selected_segments_count', len(meta.get('segments', [])))}")
        print(f"Final Duration: {meta.get('final_duration_seconds')}")
    else:
        print("Not found")
        
    print("\n=== 15 MINUTE JOB ===")
    if job15:
        print(f"Status: {job15.get('status')}")
        print(f"Video URL: {job15.get('video_url')}")
        print(f"Summary Length: {len(job15.get('summary_text', ''))} chars")
        meta = job15.get('metadata', {})
        print(f"Segments selected: {meta.get('selected_segments_count', len(meta.get('segments', [])))}")
        print(f"Final Duration: {meta.get('final_duration_seconds')}")
    else:
        print("Not found")

asyncio.run(get_jobs())
