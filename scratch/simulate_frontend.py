import asyncio
import httpx
import time

API_BASE = "http://127.0.0.1:8000"
VIDEO_ID = "xAt1xcC6qfM"

async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        print("Starting merge job...")
        resp = await client.post(f"{API_BASE}/api/v1/merge", json={
            "video_ids": [VIDEO_ID],
            "target_duration_minutes": 10,
            "generate_audio": True,
            "generate_video": True,
            "style": "educational"
        })
        if resp.status_code != 200:
            print(f"Merge failed: {resp.status_code} {resp.text}")
            return
            
        data = resp.json()
        job_id = data["job_id"]
        print(f"Job started: {job_id}")
        
        status = data["status"]
        video_url = None
        visited_video_ready = False
        
        while status not in ['completed', 'partial_success', 'error']:
            time.sleep(2)
            status_resp = await client.get(f"{API_BASE}/api/v1/merge/{job_id}")
            if status_resp.status_code != 200:
                print(f"Failed to fetch status: {status_resp.status_code}")
                break
                
            status_data = status_resp.json()
            status = status_data["status"]
            print(f"Status tick: {status} ({status_data.get('progress_percent')}%) - {status_data.get('stage_message')}")
            
            if status == 'video_ready':
                visited_video_ready = True
            
            should_fetch_result = (status == 'video_ready' or status in ['summarizing', 'enriching', 'generating_voice'] or visited_video_ready)
            
            if should_fetch_result and not video_url:
                print(f"Frontend detected {status}, fetching /result ONCE to get video_url...")
                res_resp = await client.get(f"{API_BASE}/api/v1/merge/{job_id}/result")
                print(f"GET /result -> {res_resp.status_code}")
                
                if res_resp.status_code == 200:
                    res_data = res_resp.json()
                    if res_data.get("video_url"):
                        video_url = res_data["video_url"]
                        print(f"SUCCESS: video_url obtained: {video_url}")
                    else:
                        print(f"Warning: /result 200 OK but no video_url yet.")
                else:
                    print(f"ERROR: /result returned {res_resp.status_code} {res_resp.text}")
                    # Frontend catches this, video_url remains None, so it will retry.
                    
        if status in ['completed', 'partial_success']:
            print(f"Final status reached: {status}. Fetching final result...")
            res_resp = await client.get(f"{API_BASE}/api/v1/merge/{job_id}/result")
            print(f"Final GET /result -> {res_resp.status_code}")
            eval_resp = await client.get(f"{API_BASE}/api/v1/merge/{job_id}/evaluate")
            print(f"Final GET /evaluate -> {eval_resp.status_code}")

if __name__ == "__main__":
    asyncio.run(main())
