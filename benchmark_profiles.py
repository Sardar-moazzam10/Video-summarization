import asyncio
import os
import sys

from backend.api.merge import process_merge_job, MergeJob, JobStatus, _active_jobs
from backend.core.config import get_settings
from backend.services.duration_profiles import get_profile

async def main():
    durations = [5, 15, 20, 30]
    
    for duration in durations:
        print(f"\n{'='*40}")
        print(f"Testing profile: {duration} minutes")
        print(f"{'='*40}")
        
        job_id = f"test_{duration}m"
        job = MergeJob(
            job_id=job_id,
            video_ids=["xAt1xcC6qfM"],
            target_duration_minutes=duration,
            style="analytical",
            generate_video=True
        )
        _active_jobs[job_id] = job
        
        # Override sleep at the end to prevent hanging
        import backend.api.merge
        import asyncio
        original_sleep = asyncio.sleep
        
        import backend.services.video_service
        
        async def mock_sleep(seconds):
            if seconds == 300:
                print("Skipping 300s sleep")
            else:
                await original_sleep(seconds)
                
        async def mock_highlight_reel(*args, **kwargs):
            print("Skipping FFmpeg highlight generation")
            return "video.mp4"
            
        async def mock_extract_audio(*args, **kwargs):
            return "audio.mp3"
            
        backend.api.merge.asyncio.sleep = mock_sleep
        original_reel = backend.services.video_service.VideoService.generate_highlight_reel
        original_audio = backend.api.merge._extract_audio_from_reel
        backend.services.video_service.VideoService.generate_highlight_reel = mock_highlight_reel
        backend.api.merge._extract_audio_from_reel = mock_extract_audio
        
        try:
            await process_merge_job(job_id)
        finally:
            backend.api.merge.asyncio.sleep = original_sleep
            backend.services.video_service.VideoService.generate_highlight_reel = original_reel
            backend.api.merge._extract_audio_from_reel = original_audio
            
        print(f"\nJob {duration}m completed. Status: {job.status.value}")
        if job.status.value != "completed" and job.status.value != "partial_success":
            print(f"Error: {job.error}")

if __name__ == "__main__":
    asyncio.run(main())
