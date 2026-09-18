import requests
import time
import json

base_url = "http://127.0.0.1:8003"
# 3 English videos
video_ids = ["2nIoXBvQKhs", "PeMlggyqz0Y", "ukzFI9rgwfU"]
durations = [5, 10, 15]

def run_test(duration):
    print(f"\n==================== Testing Duration: {duration} mins ====================")
    payload = {
        "video_ids": video_ids,
        "target_duration_minutes": duration,
        "generate_audio": True,
        "generate_video": True,
        "highlight_duration_seconds": 120,
        "style": "educational"
    }
    
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
            print(f">>> Fetching evaluate details...")
            eval_resp = requests.get(f"{base_url}/api/v1/merge/{job_id}/evaluate")
            if eval_resp.status_code == 200:
                with open(f"qa_result_4c_{duration}.json", "w") as f:
                    json.dump(eval_resp.json(), f, indent=2)
            break
        elif status == "failed":
            print(f"Job failed! {message}")
            break
            
        time.sleep(5)

time.sleep(10) # wait for server
for d in durations:
    run_test(d)

print("\n==================== Testing Mixed Language ====================")
payload_mixed = {
    "video_ids": ["2nIoXBvQKhs", "PeMlggyqz0Y", "zVr5KjThiF0"], # zVr5KjThiF0 is Hindi
    "target_duration_minutes": 5,
    "generate_audio": True,
    "generate_video": True,
    "highlight_duration_seconds": 120,
    "style": "educational"
}
resp = requests.post(f"{base_url}/api/v1/merge", json=payload_mixed)
if resp.status_code != 200:
    print(f"Error creating mixed job: {resp.text}")
else:
    job_id = resp.json()["job_id"]
    print(f"Mixed Job ID: {job_id}")
    while True:
        status_resp = requests.get(f"{base_url}/api/v1/merge/{job_id}")
        if status_resp.status_code != 200:
            break
        status_data = status_resp.json()
        status = status_data["status"]
        print(f"[{status}] {status_data.get('progress', 0)}% - {status_data.get('message', '')}")
        if status in ["completed", "failed"]:
            if status == "completed":
                print("Mixed job completed successfully.")
            break
        time.sleep(5)
