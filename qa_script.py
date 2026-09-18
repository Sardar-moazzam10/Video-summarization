import requests
import time
import sys
import json

video_ids = ["2nIoXBvQKhs", "PeMlggyqz0Y", "ukzFI9rgwfU"]
durations = [5, 10, 15]

base_url = "http://127.0.0.1:8002"

def run_test(duration):
    print(f"\n==================================================")
    print(f"--- Testing Duration: {duration} mins ---")
    print(f"==================================================")
    payload = {
        "video_ids": video_ids,
        "target_duration_minutes": duration,
        "generate_audio": True,
        "generate_video": True,
        "highlight_duration_seconds": 120,
        "style": "educational"
    }
    
    try:
        resp = requests.post(f"{base_url}/api/v1/merge", json=payload)
        if resp.status_code != 200:
            print(f"Error creating job: {resp.text}")
            return
        
        job_id = resp.json()["job_id"]
        print(f"Job ID: {job_id}")
        
        while True:
            status_resp = requests.get(f"{base_url}/api/v1/merge/{job_id}")
            if status_resp.status_code != 200:
                print("Status fetch error")
                break
            
            status_data = status_resp.json()
            status = status_data["status"]
            progress = status_data.get("progress", 0)
            message = status_data.get("message", "")
            print(f"[{status}] {progress}% - {message}")
            
            if status == "completed":
                print(f"\n>>> Job completed. Result: {status_data.get('result')}")
                print(f">>> Fetching evaluate details...")
                eval_resp = requests.get(f"{base_url}/api/v1/merge/{job_id}/evaluate")
                if eval_resp.status_code == 200:
                    with open(f"qa_result_{duration}.json", "w") as f:
                        json.dump(eval_resp.json(), f, indent=2)
                    print(f"Evaluate details saved to qa_result_{duration}.json")
                else:
                    print(f"Evaluate API error: {eval_resp.text}")
                break
            elif status == "failed":
                print(f"Job failed! Message: {message}")
                break
                
            time.sleep(5)
    except Exception as e:
        print(f"Connection error: {e}")

print("Waiting for server to fully start (30s)...")
time.sleep(30)
for d in durations:
    run_test(d)
