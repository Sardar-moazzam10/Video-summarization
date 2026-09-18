import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

async def main():
    print("Starting test...")
    db_writes = []
    async def fake_update(query, update, **kw):
        print(f"fake_update called with: {update}")
        db_writes.append(update.get("$set", {}))

    jobs_collection = AsyncMock()
    jobs_collection.update_one = fake_update
    jobs_collection.find_one = AsyncMock(return_value=None)

    job = MagicMock()
    job.job_id = "test-hindi-job-001"
    job.video_ids = ["dummyHindiVid"]
    job.generate_video = False

    text_map = {"dummyHindiVid": "hi " * 50}
    seg_map = {"dummyHindiVid": [{"text": "hi", "start": 0, "duration": 5}]}

    with (
        patch("backend.api.merge.get_jobs_collection", return_value=jobs_collection),
        patch("backend.api.merge.fetch_transcripts_with_segments", new_callable=AsyncMock, return_value=(text_map, seg_map)),
        patch("backend.api.merge.get_fusion_engine", return_value=MagicMock()),
        patch("backend.services.vector_store.get_vector_store"),
        patch("langdetect.detect", return_value="hi"),
        patch("backend.api.merge._active_jobs", {"test-hindi-job-001": job}),
    ):
        from backend.api.merge import process_merge_job
        print("Calling process_merge_job...")
        await process_merge_job("test-hindi-job-001")
        print("process_merge_job finished!")
        print("db_writes:", db_writes)

if __name__ == "__main__":
    asyncio.run(main())
