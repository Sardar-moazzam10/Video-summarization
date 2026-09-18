import asyncio
import os
from backend.services.video_service import VideoService

async def main():
    vs = VideoService()
    video_paths = {"ukzFI9rgwfU": "audio_cache/video_cache/ukzFI9rgwfU/video.mp4"}
    
    seg1 = {"video_id": "ukzFI9rgwfU", "start_time": 10.0, "end_time": 15.0}
    seg2 = {"video_id": "ukzFI9rgwfU", "start_time": 30.0, "end_time": 36.0}
    
    work_dir = os.path.abspath("scratch")
    
    c1 = await vs._trim_and_normalize_segment(seg1, video_paths, work_dir, 1)
    c2 = await vs._trim_and_normalize_segment(seg2, video_paths, work_dir, 2)
    
    concat = await vs._concat_with_transitions([c1, c2], "debug_job", work_dir)
    print(f"Concat {concat}")

asyncio.run(main())
