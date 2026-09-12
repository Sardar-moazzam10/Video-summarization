import asyncio
import time
import os
import subprocess
import tempfile
import shutil
import psutil

async def benchmark_ffmpeg():
    video_id = "_QXjl-4IuzY"
    work_dir_dl = tempfile.mkdtemp()
    
    from backend.services.video_service import VideoService
    vs = VideoService()
    
    print("Downloading video...")
    vid_path = await vs._download_single(video_id, work_dir_dl)
    if not vid_path:
        print("Failed to download video")
        return
        
    print(f"Using {vid_path}")
    
    # Mock segments for 10 minutes total
    # Let's say 12 segments of 50s each
    segments = []
    for i in range(12):
        start = i * 60 + 10 # start at 10s, 70s, 130s...
        end = start + 50 # 50s clip
        segments.append({"video_id": video_id, "start_time": start, "end_time": end})
    
    video_paths = {video_id: vid_path}
    
    def monitor_resources():
        cpu_percents = []
        mem_usages = []
        for _ in range(20):
            cpu_percents.append(psutil.cpu_percent(interval=0.1))
            mem_usages.append(psutil.virtual_memory().used / (1024**2))
        return sum(cpu_percents)/len(cpu_percents), max(mem_usages)
    
    async def run_trim_with_workers(n_workers):
        import backend.services.video_service as _vs
        _vs.MAX_CONCURRENT_CLIP_ENCODES = n_workers
        work_dir = tempfile.mkdtemp(prefix=f"ffmpeg_w{n_workers}_")
        t0 = time.time()
        
        # start resource monitor in thread
        import threading
        res = {"cpu": 0, "mem": 0}
        def mon():
            import psutil
            cpus = []
            mems = []
            while getattr(threading.current_thread(), "do_run", True):
                cpus.append(psutil.cpu_percent(interval=0.5))
                mems.append(psutil.virtual_memory().used / (1024**2))
            res["cpu"] = sum(cpus)/len(cpus) if cpus else 0
            res["mem"] = max(mems) if mems else 0
        t = threading.Thread(target=mon)
        t.start()
        
        clips = await vs._trim_segments_bounded(segments, video_paths, work_dir)
        concat_path = await vs._concat_with_transitions(clips, "bench", work_dir)
        
        t.do_run = False
        t.join()
        t1 = time.time()
        
        shutil.rmtree(work_dir)
        return t1 - t0, res
        
    print("\n--- A. Current bounded 6 workers ---")
    time_6, res_6 = await run_trim_with_workers(6)
    print(f"Time: {time_6:.2f}s, CPU: {res_6['cpu']:.1f}%, Peak Mem: {res_6['mem']:.1f}MB")
    
    print("\n--- B. 4 workers ---")
    time_4, res_4 = await run_trim_with_workers(4)
    print(f"Time: {time_4:.2f}s, CPU: {res_4['cpu']:.1f}%, Peak Mem: {res_4['mem']:.1f}MB")
    
    print("\n--- C. 8 workers ---")
    time_8, res_8 = await run_trim_with_workers(8)
    print(f"Time: {time_8:.2f}s, CPU: {res_8['cpu']:.1f}%, Peak Mem: {res_8['mem']:.1f}MB")
    
    print("\n--- D. One-process filter_complex ---")
    work_dir = tempfile.mkdtemp()
    
    t0 = time.time()
    res = {"cpu": 0, "mem": 0}
    
    # Build complex filter
    filter_parts = []
    for i, seg in enumerate(segments):
        start = seg["start_time"]
        end = seg["end_time"]
        # trim video and audio
        filter_parts.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:-1:-1:color=black[v{i}];")
        filter_parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];")
    
    concat_filter = ""
    for i in range(len(segments)):
        concat_filter += f"[v{i}][a{i}]"
    concat_filter += f"concat=n={len(segments)}:v=1:a=1[outv][outa]"
    
    complex_filter = "".join(filter_parts) + concat_filter
    out_path = os.path.join(work_dir, "filter_complex.mp4")
    
    cmd = [
        "ffmpeg", "-y", "-i", vid_path,
        "-filter_complex", complex_filter,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        out_path
    ]
    
    import threading
    def mon2():
        import psutil
        cpus = []
        mems = []
        while getattr(threading.current_thread(), "do_run", True):
            cpus.append(psutil.cpu_percent(interval=0.5))
            mems.append(psutil.virtual_memory().used / (1024**2))
        res["cpu"] = sum(cpus)/len(cpus) if cpus else 0
        res["mem"] = max(mems) if mems else 0
    t2 = threading.Thread(target=mon2)
    t2.start()
    
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _, stderr = await proc.communicate()
    except Exception as e:
        print(f"Error: {e}")
        
    t2.do_run = False
    t2.join()
    t1 = time.time()
    print(f"Time: {t1-t0:.2f}s, CPU: {res['cpu']:.1f}%, Peak Mem: {res['mem']:.1f}MB")
    
    # Check if stream-copy is faster
    print("\n--- E. Stream-copy approach ---")
    t0 = time.time()
    for i, seg in enumerate(segments):
        start = seg["start_time"]
        duration = seg["end_time"] - start
        out_clip = os.path.join(work_dir, f"copy_{i}.mp4")
        cmd_copy = [
            "ffmpeg", "-y", "-ss", str(start), "-i", vid_path, "-t", str(duration),
            "-c", "copy", out_clip
        ]
        await asyncio.create_subprocess_exec(*cmd_copy, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t1 = time.time()
    print(f"Stream-copy Time (trim only): {t1-t0:.2f}s (NOTE: can result in broken A/V sync at cut points due to keyframe gaps)")
    
    shutil.rmtree(work_dir)
    shutil.rmtree(work_dir_dl, ignore_errors=True)

if __name__ == "__main__":
    asyncio.run(benchmark_ffmpeg())
