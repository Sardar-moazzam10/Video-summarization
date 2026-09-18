import asyncio
import os
from backend.services.video_service import VideoService

async def main():
    vs = VideoService()
    video_paths = {
        "2nIoXBvQKhs": "audio_cache/video_cache/2nIoXBvQKhs/video.mp4",
        "PeMlggyqz0Y": "audio_cache/video_cache/PeMlggyqz0Y/video.mp4"
    }
    
    seg1 = {"video_id": "2nIoXBvQKhs", "start_time": 10.0, "end_time": 15.0}
    seg2 = {"video_id": "PeMlggyqz0Y", "start_time": 10.0, "end_time": 15.0}
    
    work_dir = os.path.abspath("scratch")
    
    c1 = await vs._trim_and_normalize_segment(seg1, video_paths, work_dir, 3)
    c2 = await vs._trim_and_normalize_segment(seg2, video_paths, work_dir, 4)
    
    concat = await vs._concat_with_transitions([c1, c2], "debug_job2", work_dir)
    print(f"Concat {concat}")

asyncio.run(main())
