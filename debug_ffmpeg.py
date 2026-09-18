import asyncio
from backend.services.video_service import VideoService

async def main():
    vs = VideoService()
    seg = {"video_id": "ukzFI9rgwfU", "start_time": 10.0, "end_time": 15.0}
    video_paths = {"ukzFI9rgwfU": "audio_cache/video_cache/ukzFI9rgwfU/video.mp4"}
    
    out = await vs._trim_and_normalize_segment(seg, video_paths, "scratch", 1)
    print(f"Generated {out}")

asyncio.run(main())
