import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.acquisition_service import create_shadow_job_decisions, set_observation_context, reset_observation_context, append_event, finalize_shadow_manifest

async def main():
    decisions = await create_shadow_job_decisions(
        job_id="test_job_123",
        user_id="test_user_456",
        source_ids=["video1", "video2"]
    )
    print("Decisions:", decisions)
    
    token = set_observation_context(
        job_id="test_job_123",
        user_id="test_user_456",
        decision_ids=decisions
    )
    
    evt1 = await append_event(
        source_id="video1",
        operation="caption_read",
        phase="attempted",
        method="youtube_api",
        outcome_code="started"
    )
    print("Event 1:", evt1)
    
    evt2 = await append_event(
        source_id="video2",
        operation="caption_read",
        phase="attempted",
        method="youtube_api",
        outcome_code="started"
    )
    print("Event 2:", evt2)
    
    manifest = await finalize_shadow_manifest("test_job_123", "job_completed")
    print("Manifest hash:", manifest["manifest_hash"] if manifest else None)
    
    reset_observation_context(token)

if __name__ == "__main__":
    asyncio.run(main())
