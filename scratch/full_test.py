import asyncio
import httpx
import time
import json
from datetime import datetime

API_BASE = "http://127.0.0.1:8000"
VIDEO_ID = "xAt1xcC6qfM"

def now():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

async def run_job(target_minutes):
    print(f"\n{'='*50}\nSTARTING TEST: {target_minutes} MINUTES\n{'='*50}")
    
    t0 = time.time()
    print(f"[{now()}] T0: User clicks Generate")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{API_BASE}/api/v1/merge", json={
            "video_ids": [VIDEO_ID],
            "target_duration_minutes": target_minutes,
            "generate_audio": True,
            "generate_video": True,
            "style": "educational"
        })
        
        data = resp.json()
        job_id = data["job_id"]
        print(f"[{now()}] Job started: {job_id}")
        
        status = data["status"]
        
        t_transcript = None
        t_semantic = None
        t_video_gen = None
        t_video_ready = None
        t_video_playable = None
        t_bart = None
        t_completed = None
        
        last_stage = None
        
        while status not in ['completed', 'partial_success', 'error']:
            await asyncio.sleep(1)
            try:
                status_resp = await client.get(f"{API_BASE}/api/v1/merge/{job_id}")
                if status_resp.status_code != 200:
                    continue
            except:
                continue
                
            status_data = status_resp.json()
            status = status_data["status"]
            
            # Map statuses to timestamps
            if status == "analyzing" and not t_transcript:
                t_transcript = time.time()
                print(f"[{now()}] T1: Transcript available")
                
            if status == "generating_video" and not t_semantic:
                t_semantic = time.time()
                print(f"[{now()}] T2: Semantic selection complete")
                
            if status == "video_ready" and not t_video_ready:
                t_video_gen = time.time() # End of generation
                print(f"[{now()}] T3: Highlight video generated")
                t_video_ready = time.time()
                print(f"[{now()}] T4: VIDEO_READY received")
                
                # Fetch video URL like frontend
                print(f"[{now()}] T5: Requesting /result for playable video...")
                res = await client.get(f"{API_BASE}/api/v1/merge/{job_id}/result")
                if res.status_code == 200 and res.json().get("video_url"):
                    t_video_playable = time.time()
                    print(f"[{now()}] T5: Video becomes playable in browser")
                else:
                    print(f"[{now()}] ERROR: 400 on /result or no video!")
                    
            if status == "summarizing" and not t_bart:
                t_bart = time.time()
                print(f"[{now()}] T6: BART summary starts")
                
            if status != last_stage:
                print(f"[{now()}] Stage change: {status} ({status_data.get('progress_percent')}%)")
                last_stage = status
                
        t_completed = time.time()
        print(f"[{now()}] T9: Final COMPLETED state")
        
        # Get final result
        res = await client.get(f"{API_BASE}/api/v1/merge/{job_id}/result")
        final_data = res.json()
        
        print(f"\n--- VALIDATION: {target_minutes} MIN ---")
        print(f"Video URL: {final_data.get('video_url')}")
        print(f"Text Summary Length: {len(final_data.get('summary_text', ''))} chars")
        metadata = final_data.get('metadata', {})
        print(f"Clips Selected: {len(metadata.get('segments', []))}")
        print(f"Final Duration: {metadata.get('final_duration_seconds', 0)} seconds")
        
        print("\n--- LATENCY ---")
        print(f"Video-ready latency: {t_video_ready - t0:.2f}s")
        print(f"Full completion latency: {t_completed - t0:.2f}s")
        if t_semantic and t_transcript:
            print(f"Semantic analysis time: {t_semantic - t_transcript:.2f}s")
        if t_video_ready and t_semantic:
            print(f"FFmpeg time: {t_video_ready - t_semantic:.2f}s")
            
        return {
            "target": target_minutes,
            "clips": len(metadata.get('segments', [])),
            "duration": metadata.get('final_duration_seconds', 0),
            "video_ready": t_video_ready - t0 if t_video_ready else 0,
            "full_completion": t_completed - t0 if t_completed else 0,
            "data": final_data
        }

async def run_all():
    res10 = await run_job(10)
    res15 = await run_job(15)
    
    print("\n\n" + "="*50)
    print("FINAL COMPARISON")
    print("="*50)
    print(f"Metric | 10 min | 15 min")
    print(f"Video Duration (s) | {res10['duration']} | {res15['duration']}")
    print(f"Clips Selected | {res10['clips']} | {res15['clips']}")
    print(f"Video-Ready Latency (s) | {res10['video_ready']:.1f} | {res15['video_ready']:.1f}")
    print(f"Full Latency (s) | {res10['full_completion']:.1f} | {res15['full_completion']:.1f}")
    
    # Save results to a file for analysis
    with open("scratch/test_results.json", "w") as f:
        json.dump({"10min": res10, "15min": res15}, f, indent=2)

if __name__ == "__main__":
    asyncio.run(run_all())
