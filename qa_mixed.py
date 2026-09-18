import requests
import time

base_url = "http://127.0.0.1:8003"
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
        time.sleep(3)
