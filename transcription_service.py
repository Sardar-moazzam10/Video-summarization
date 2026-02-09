"""
Transcription Service - Dedicated service for audio downloading and transcription.
Features:
- Disk caching of transcripts in transcripts/<video_id>.txt
- Whisper optimization for CPU (base model, no FP16 on CPU)
- Background task execution via ThreadPoolExecutor
- GPU auto-detection and optimization
"""

import os
import sys
import json
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, Any, Optional, List
import whisper
import torch

# === Configuration ===
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "transcripts")
AUDIO_CACHE_DIR = os.path.join(BASE_DIR, "audio_cache")

os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)

# Resolve yt-dlp binary
def _resolve_binary(env_name: str, default_name: str) -> str:
    override = os.getenv(env_name)
    if override:
        return override

    # Check if we're in a virtual environment and prefer venv binary
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        # We're in a venv - check Scripts directory first
        venv_bin = os.path.join(sys.prefix, "Scripts", f"{default_name}.exe")
        if os.path.exists(venv_bin):
            return venv_bin

    return shutil.which(default_name) or default_name

YTDLP_BIN = _resolve_binary("YTDLP_PATH", "yt-dlp")
FFMPEG_BIN = _resolve_binary("FFMPEG_PATH", "ffmpeg")
COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")

# Configuration
WHISPER_ALLOW_PARALLEL = os.getenv("WHISPER_ALLOW_PARALLEL", "0") == "1"
DOWNLOAD_RETRY_ATTEMPTS = int(os.getenv("DOWNLOAD_RETRY_ATTEMPTS", "3"))

# === Whisper Model (Lazy Loading with CPU Optimization) ===
_whisper_model = None
_whisper_lock = threading.Lock()
_inference_lock = threading.Lock()  # Global lock for model inference

def get_whisper_model():
    """
    Load Whisper model with CPU optimization:
    - Uses 'base' model for speed
    - Auto-detects GPU availability
    - Avoids FP16 on CPU for stability
    """
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"🎤 Loading Whisper 'base' model on {device}...")
            _whisper_model = whisper.load_model("base", device=device)
            print("✅ Whisper model loaded successfully")
    return _whisper_model


class TranscriptionService:
    """
    Service for transcribing YouTube videos with disk caching.
    """
    
    def __init__(self, max_workers: int = 2):
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="transcribe_")
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
    
    def get_cache_path(self, video_id: str) -> str:
        """Get the path to cached transcript file."""
        return os.path.join(TRANSCRIPTS_DIR, f"{video_id}.txt")
    
    def get_json_cache_path(self, video_id: str) -> str:
        """Get the path to cached transcript JSON with segments."""
        return os.path.join(TRANSCRIPTS_DIR, f"{video_id}.json")
    
    def is_cached(self, video_id: str) -> bool:
        """Check if transcript is already cached on disk."""
        return os.path.exists(self.get_json_cache_path(video_id))
    
    def get_cached_transcript(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Load transcript from disk cache if available."""
        json_path = self.get_json_cache_path(video_id)
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"📦 Using cached transcript for {video_id}")
                    return data
            except Exception as e:
                print(f"⚠️ Failed to load cached transcript: {e}")
        return None
    
    def save_transcript(self, video_id: str, segments: List[Dict], full_text: str):
        """Save transcript to disk cache."""
        # Save JSON with segments for merging
        json_path = self.get_json_cache_path(video_id)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                "video_id": video_id,
                "segments": segments,
                "full_text": full_text,
                "cached_at": datetime.now().isoformat()
            }, f, indent=2)
        
        # Save plain text for quick access
        txt_path = self.get_cache_path(video_id)
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(full_text)
        
        print(f"💾 Cached transcript for {video_id}")
    
    def download_audio(self, video_id: str, work_dir: str) -> str:
        """
        Download YouTube audio using yt-dlp with retry logic.
        Returns path to the downloaded audio file.
        """
        url = f"https://www.youtube.com/watch?v={video_id}"
        output_path = os.path.join(work_dir, f"{video_id}_audio.mp3")

        # Check if already downloaded
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"📦 Using cached audio for {video_id}")
            return output_path

        cmd = [
            YTDLP_BIN,
            "--cookies", COOKIES_FILE,
            "--js-runtimes", "node",
            "--extractor-args", "youtube:player_client=web",
            "--no-check-certificates",
            "--socket-timeout", "60",
            "--retries", "10",
            "--ffmpeg-location", FFMPEG_BIN,
            "-x", "--audio-format", "mp3",
            "-o", output_path,
            url,
        ]

        # Retry logic with exponential backoff
        import time
        for attempt in range(1, DOWNLOAD_RETRY_ATTEMPTS + 1):
            try:
                print(f"▶ Downloading audio for {video_id} (attempt {attempt}/{DOWNLOAD_RETRY_ATTEMPTS})...")
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

                # Validate download
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    print(f"✅ Successfully downloaded audio for {video_id}")
                    return output_path
                else:
                    print(f"⚠️ Download completed but file invalid for {video_id}")

            except subprocess.CalledProcessError as e:
                print(f"❌ Audio download attempt {attempt} failed for {video_id}:")
                print(e.stderr if e.stderr else str(e))

                if attempt < DOWNLOAD_RETRY_ATTEMPTS:
                    wait_time = 2 ** attempt  # Exponential backoff: 2, 4, 8 seconds
                    print(f"⏳ Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)

        raise Exception(f"Audio download failed for {video_id} after {DOWNLOAD_RETRY_ATTEMPTS} attempts")
    
    def transcribe_audio(self, audio_path: str) -> Dict[str, Any]:
        """
        Transcribe audio file using Whisper.
        Optimized for CPU with base model and no FP16.
        Optional parallel inference if WHISPER_ALLOW_PARALLEL=1.
        """
        model = get_whisper_model()
        device = "cuda" if torch.cuda.is_available() else "cpu"

        print(f"🎤 Transcribing with Whisper ({device})...")

        # Use inference lock only if parallel mode is disabled
        if WHISPER_ALLOW_PARALLEL:
            # Allow parallel inference (for GPU systems or multiple model instances)
            result = model.transcribe(audio_path, fp16=(device == "cuda"))
        else:
            # Serial inference with lock (safer for CPU systems)
            with _inference_lock:
                result = model.transcribe(audio_path, fp16=(device == "cuda"))

        return result
    
    def transcribe_video(self, video_id: str, callback=None) -> Dict[str, Any]:
        """
        Transcribe a YouTube video. Uses cache if available.
        
        Args:
            video_id: YouTube video ID
            callback: Optional callback function(video_id, result) called when done
            
        Returns:
            Dict with segments, full_text, and metadata
        """
        # Check cache first
        cached = self.get_cached_transcript(video_id)
        if cached:
            if callback:
                callback(video_id, cached)
            return cached
        
        # Create temp work directory
        work_dir = tempfile.mkdtemp(prefix=f"transcribe_{video_id}_", dir=AUDIO_CACHE_DIR)
        
        try:
            # Download audio
            audio_path = self.download_audio(video_id, work_dir)
            
            # Transcribe
            result = self.transcribe_audio(audio_path)
            
            # Extract segments and full text
            segments = []
            full_text = ""
            for seg in result.get("segments", []):
                segments.append({
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"]
                })
                full_text += seg["text"] + " "
            
            full_text = full_text.strip()
            
            # Cache the result
            self.save_transcript(video_id, segments, full_text)
            
            output = {
                "video_id": video_id,
                "segments": segments,
                "full_text": full_text,
                "cached_at": datetime.now().isoformat()
            }
            
            if callback:
                callback(video_id, output)
            
            return output
            
        finally:
            # Cleanup temp directory - improved robustness
            if os.path.exists(work_dir):
                try:
                    shutil.rmtree(work_dir, ignore_errors=True)
                    print(f"🧹 Cleaned up temp directory for {video_id}")
                except Exception as e:
                    print(f"⚠️ Failed to clean temp directory {work_dir}: {e}")
    
    def transcribe_async(self, video_id: str) -> str:
        """
        Start async transcription job.
        Returns job_id for status tracking.
        """
        job_id = f"trans_{video_id}_{datetime.now().strftime('%H%M%S')}"
        
        with self._lock:
            self.jobs[job_id] = {
                "video_id": video_id,
                "status": "pending",
                "result": None,
                "error": None,
                "created_at": datetime.now().isoformat()
            }
        
        def _run():
            try:
                with self._lock:
                    self.jobs[job_id]["status"] = "processing"
                
                result = self.transcribe_video(video_id)
                
                with self._lock:
                    self.jobs[job_id]["status"] = "completed"
                    self.jobs[job_id]["result"] = result
                    
            except Exception as e:
                with self._lock:
                    self.jobs[job_id]["status"] = "error"
                    self.jobs[job_id]["error"] = str(e)
        
        self.executor.submit(_run)
        return job_id
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get status of async transcription job."""
        with self._lock:
            return self.jobs.get(job_id)
    
    def transcribe_multiple(self, video_ids: List[str], progress_callback=None) -> Dict[str, Dict[str, Any]]:
        """
        Transcribe multiple videos, using cache where available.
        
        Args:
            video_ids: List of video IDs
            progress_callback: Optional callback(video_id, index, total, result)
            
        Returns:
            Dict mapping video_id to transcript data
        """
        results = {}
        total = len(video_ids)
        
        for idx, video_id in enumerate(video_ids):
            try:
                result = self.transcribe_video(video_id)
                results[video_id] = result
                
                if progress_callback:
                    progress_callback(video_id, idx + 1, total, result)
                    
            except Exception as e:
                print(f"❌ Failed to transcribe {video_id}: {e}")
                results[video_id] = {"error": str(e)}
        
        return results


# Singleton instance
_transcription_service = None

def get_transcription_service() -> TranscriptionService:
    """Get singleton TranscriptionService instance."""
    global _transcription_service
    if _transcription_service is None:
        _transcription_service = TranscriptionService()
    return _transcription_service


# === Flask API (optional, for standalone use) ===
if __name__ == "__main__":
    from flask import Flask, request, jsonify
    from flask_cors import CORS
    
    app = Flask(__name__)
    CORS(app)
    
    service = get_transcription_service()
    
    @app.route('/transcribe/<video_id>', methods=['GET'])
    def transcribe_endpoint(video_id):
        """GET /transcribe/<video_id> - Get or start transcription."""
        # Check cache first
        if service.is_cached(video_id):
            cached = service.get_cached_transcript(video_id)
            return jsonify({"status": "cached", "data": cached})
        
        # Start async job
        job_id = service.transcribe_async(video_id)
        return jsonify({"status": "started", "job_id": job_id})
    
    @app.route('/transcribe/status/<job_id>', methods=['GET'])
    def transcribe_status(job_id):
        """GET /transcribe/status/<job_id> - Check transcription job status."""
        status = service.get_job_status(job_id)
        if not status:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(status)
    
    @app.route('/transcribe/cached', methods=['GET'])
    def list_cached():
        """GET /transcribe/cached - List all cached transcripts."""
        cached = []
        for fname in os.listdir(TRANSCRIPTS_DIR):
            if fname.endswith('.json'):
                video_id = fname.replace('.json', '')
                cached.append(video_id)
        return jsonify({"cached_transcripts": cached})
    
    print("✅ Transcription service running at http://localhost:5003")
    app.run(port=5003, debug=True)
