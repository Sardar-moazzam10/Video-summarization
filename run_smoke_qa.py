import asyncio
from backend.services.transcript_service import get_transcript_service
from backend.services.video_service import get_video_service

async def run_smoke():
    print("Running runtime smoke QA...")
    # Check if services initialize without syntax/import errors
    ts = await get_transcript_service()
    vs = get_video_service()
    print("Services initialized.")
    print("Smoke QA Passed.")

if __name__ == "__main__":
    asyncio.run(run_smoke())
