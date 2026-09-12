import os
import sys
import subprocess
import requests
from pymongo import MongoClient

tests_passed = True

def print_status(component, success, message=""):
    global tests_passed
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} | {component.ljust(25)} | {message}")
    if not success:
        tests_passed = False

def run_smoke_test():
    print("="*60)
    print("VIDFUSION SUPERVISOR SMOKE TEST")
    print("="*60)

    # 1. Python dependencies
    try:
        import fastapi
        import torch
        import transformers
        import motor
        import yt_dlp
        import librosa
        print_status("Python Dependencies", True, f"Found fastapi, torch v{torch.__version__}, transformers")
    except ImportError as e:
        print_status("Python Dependencies", False, str(e))

    # 2. FFmpeg
    try:
        res = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=True)
        version = res.stdout.split('\n')[0]
        print_status("FFmpeg", True, version)
    except Exception as e:
        print_status("FFmpeg", False, "ffmpeg not found in system PATH")

    # 3. yt-dlp
    try:
        res = subprocess.run(["./venv/bin/yt-dlp", "--version"], capture_output=True, text=True, check=True)
        print_status("yt-dlp Binary", True, f"v{res.stdout.strip()}")
    except Exception as e:
        print_status("yt-dlp Binary", False, "yt-dlp binary not found in ./venv/bin/")

    # 4. MongoDB Connectivity
    try:
        client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=2000)
        client.server_info() # forces a call
        print_status("MongoDB Connectivity", True, "Connected to localhost:27017")
    except Exception as e:
        print_status("MongoDB Connectivity", False, "Could not connect to MongoDB. Is Docker running?")

    # 5. BART model availability
    try:
        from transformers import pipeline
        try:
            pl = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6", local_files_only=True)
            print_status("BART Model (Local)", True, "sshleifer/distilbart-cnn-12-6 is cached locally")
        except Exception as e:
            print("⚠️ WARN | BART Model (Local)          | Not cached. Will download on first run.")
    except Exception as e:
        pass

    # 6. BGE model availability
    try:
        from sentence_transformers import SentenceTransformer
        try:
            model = SentenceTransformer("BAAI/bge-base-en-v1.5", local_files_only=True)
            print_status("BGE Model (Local)", True, "BAAI/bge-base-en-v1.5 is cached locally")
        except Exception:
            print("⚠️ WARN | BGE Model (Local)           | Not cached. Will download on first run.")
    except Exception as e:
        pass

    # 7. Backend API Health
    try:
        res = requests.get("http://localhost:8000/docs", timeout=2)
        if res.status_code == 200:
            print_status("Backend API Health", True, "FastAPI is running on port 8000")
        else:
            print_status("Backend API Health", False, f"Returned HTTP {res.status_code}")
    except Exception as e:
        print_status("Backend API Health", False, "FastAPI not currently running on port 8000")

    print("="*60)
    print("Smoke test completed.")
    if not tests_passed:
        sys.exit(1)

if __name__ == "__main__":
    run_smoke_test()
