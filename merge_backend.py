"""
Merge Backend - Refactored for microservice architecture.
Features:
- Only handles FFmpeg video merging (no downloads/transcription/summarization)
- Uses transcription_service and summarization_service
- ThreadPoolExecutor for background task execution
- Detailed progress tracking with stages
- Fast/Demo mode for aggressive cache reuse
"""

from flask import Flask, request, jsonify, Response, send_file
from flask_cors import CORS
import uuid
import random
import requests
import os
import threading
import subprocess
import tempfile
import shutil
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List
from datetime import datetime

# Import our services
from transcription_service import get_transcription_service, TranscriptionService
from summarization_service import get_summarization_service, SummarizationService
from video_cache_manager import get_video_cache_manager
from cleanup_scheduler import get_cleanup_scheduler

app = Flask(__name__)
CORS(app)

# === Configuration ===
MERGE_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "audio_cache"))
MERGE_WORK_DIR = os.path.join(MERGE_BASE_DIR, "merge_work")
MERGE_OUTPUT_DIR = os.path.join(MERGE_BASE_DIR, "merged")

os.makedirs(MERGE_WORK_DIR, exist_ok=True)
os.makedirs(MERGE_OUTPUT_DIR, exist_ok=True)

# Demo Mode - aggressive cache reuse
DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"
if DEMO_MODE:
    print("🚀 DEMO_MODE enabled - aggressive cache reuse active")

# Resolve external tool binaries
def _resolve_binary(env_name: str, default_name: str) -> str:
    override = os.getenv(env_name)
    if override:
        return override
    return shutil.which(default_name) or default_name

FFMPEG_BIN = _resolve_binary("FFMPEG_PATH", "ffmpeg")
YTDLP_BIN = _resolve_binary("YTDLP_PATH", "yt-dlp")

# === Thread Pool for Background Tasks ===
# Increased workers to handle parallel transcription and downloads
_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="merge_worker_")

# === Status Store ===
# stored_merges[merge_id] = {
#   "status": "pending" | "transcribing" | "summarizing" | "merging" | "completed" | "partial_success" | "error",
#   "stage": "Detailed stage description",
#   "progress_percent": 0-100,
#   "segments": [ { videoId, start, end }, ... ],
#   "output_path": "/abs/path/to/merged.mp4" | None,
#   "summary": "unified summary text",
#   "error": "optional error message",
#   "warnings": [ "warning messages for partial failures" ],
#   "failed_videos": [ "video_id1", "video_id2" ],
#   "total_videos": 0,
#   "successful_videos": 0,
#   "created_at": datetime,
#   "updated_at": datetime
# }
stored_merges: Dict[str, Dict[str, Any]] = {}
_store_lock = threading.Lock()

# ElevenLabs API Key
ELEVENLABS_API_KEY = os.getenv("ELEVEN_API_KEY", "sk_064bcc68571fad7f59ffc7db6b43dd734610fe329009b648")


def _update_job_status(merge_id: str, status: str = None, stage: str = None, 
                       progress_percent: int = None, **kwargs):
    """Thread-safe job status update."""
    with _store_lock:
        if merge_id in stored_merges:
            job = stored_merges[merge_id]
            if status:
                job["status"] = status
            if stage:
                job["stage"] = stage
            if progress_percent is not None:
                job["progress_percent"] = progress_percent
            job["updated_at"] = datetime.now().isoformat()
            for k, v in kwargs.items():
                job[k] = v


def generate_trimmed_segment(video_id: str, duration_seconds: int = 300) -> Dict[str, float]:
    """
    Generate a trimmed segment for a given video.
    Now uses start=0 for predictable behavior instead of random.
    """
    duration_seconds = max(int(duration_seconds), 30)
    return {
        "videoId": video_id,
        "start": 0.0,
        "end": float(duration_seconds)
    }


def _download_video(video_id: str, work_dir: str) -> str:
    """
    Download a YouTube video using persistent cache or yt-dlp.
    Uses video_cache_manager for efficient caching and retry logic.
    """
    # Check persistent cache first via video_cache_manager
    cache_manager = get_video_cache_manager()

    try:
        # Try to get from persistent cache or download with retry
        cached_path = cache_manager.download_and_cache_video(video_id, work_dir)
        return cached_path
    except Exception as e:
        # If cache manager fails, fall back to direct download
        print(f"⚠️ Cache manager failed for {video_id}, attempting direct download: {e}")

        # Check if already exists in work dir (fallback)
        for fname in os.listdir(work_dir):
            if fname.startswith(video_id + ".") and fname.endswith(('.mp4', '.webm', '.mkv')):
                existing_path = os.path.join(work_dir, fname)
                print(f"📦 Using work dir cached video {video_id}")
                return existing_path

        url = f"https://www.youtube.com/watch?v={video_id}"
        output_template = os.path.join(work_dir, f"{video_id}.%(ext)s")

        cmd = [
            YTDLP_BIN,
            "--ffmpeg-location", FFMPEG_BIN,
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "-o", output_template,
            url,
        ]
        print(f"▶ Downloading video {video_id} for merge job (fallback)...")

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        except subprocess.CalledProcessError as e:
            print(f"❌ yt-dlp failed for {video_id}:")
            print(e.stderr)
            raise Exception(f"Download failed for {video_id}: {e.stderr}")

        # Find the downloaded file
        for fname in os.listdir(work_dir):
            if fname.startswith(video_id + "."):
                return os.path.join(work_dir, fname)
        raise FileNotFoundError(f"Downloaded file for {video_id} not found in {work_dir}")


def _map_summary_to_segments(summary: str, transcripts: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    """Map summary sentences back to original video timestamps."""
    sentences = re.split(r'(?<=[.!?]) +', summary)
    selected_segments = []
    seen_segments = set()

    for sentence in sentences:
        best_match = None
        max_overlap = 0
        
        words1 = set(re.findall(r'\w+', sentence.lower()))
        if not words1: 
            continue

        for vid, segments in transcripts.items():
            for seg in segments:
                words2 = set(re.findall(r'\w+', seg['text'].lower()))
                overlap = len(words1.intersection(words2))
                
                if overlap > max_overlap:
                    seg_id = f"{vid}_{seg['start']}"
                    if seg_id not in seen_segments:
                        max_overlap = overlap
                        best_match = {
                            "videoId": vid,
                            "start": float(seg['start']),
                            "end": float(seg['end'])
                        }
                        best_match_id = seg_id

        if best_match:
            selected_segments.append(best_match)
            seen_segments.add(best_match_id)

    # If too few segments found, add some from start
    if len(selected_segments) < 2:
        for vid in transcripts:
            if transcripts[vid]:
                selected_segments.append({
                    "videoId": vid,
                    "start": 0.0,
                    "end": min(30.0, float(transcripts[vid][-1]['end']))
                })
    
    return selected_segments


def _select_segments_for_duration(summary: str, transcripts: Dict[str, List[Any]], 
                                   target_duration: int, video_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Select video segments that match summary content until target duration is reached.
    Allocates time proportionally across videos.
    
    Args:
        summary: The generated summary text
        transcripts: Dict mapping video_id to list of segments
        target_duration: Target total duration in seconds
        video_ids: List of video IDs in order
    
    Returns:
        List of selected segments with videoId, start, end
    """
    # Calculate time allocation per video
    num_videos = len(video_ids)
    if num_videos == 0:
        return []
    
    time_per_video = target_duration / num_videos
    
    # Map summary sentences to segments
    sentences = re.split(r'(?<=[.!?]) +', summary)
    
    # Score all segments by relevance to summary
    scored_segments = []
    for vid in video_ids:
        segments = transcripts.get(vid, [])
        for seg in segments:
            # Calculate relevance score based on word overlap with summary
            seg_words = set(re.findall(r'\w+', seg['text'].lower()))
            total_overlap = 0
            for sentence in sentences:
                sent_words = set(re.findall(r'\w+', sentence.lower()))
                total_overlap += len(seg_words.intersection(sent_words))
            
            scored_segments.append({
                "videoId": vid,
                "start": float(seg['start']),
                "end": float(seg['end']),
                "duration": float(seg['end']) - float(seg['start']),
                "score": total_overlap,
                "text": seg['text']
            })
    
    # Sort by score (highest first)
    scored_segments.sort(key=lambda x: x['score'], reverse=True)
    
    # Select segments respecting per-video time budget
    selected = []
    video_time_used = {vid: 0.0 for vid in video_ids}
    total_duration_so_far = 0.0
    seen_starts = set()
    
    for seg in scored_segments:
        vid = seg["videoId"]
        seg_duration = seg["duration"]
        seg_key = f"{vid}_{seg['start']}"
        
        # Skip if already selected or exceeds video budget
        if seg_key in seen_starts:
            continue
        
        # Check if we can add this segment
        if video_time_used[vid] + seg_duration <= time_per_video * 1.2:  # Allow 20% overage
            if total_duration_so_far + seg_duration <= target_duration * 1.1:  # Allow 10% overage
                selected.append({
                    "videoId": vid,
                    "start": seg["start"],
                    "end": seg["end"]
                })
                video_time_used[vid] += seg_duration
                total_duration_so_far += seg_duration
                seen_starts.add(seg_key)
        
        # Stop if we've reached target duration
        if total_duration_so_far >= target_duration:
            break
    
    # Sort by video order and start time for coherent playback
    video_order = {vid: idx for idx, vid in enumerate(video_ids)}
    selected.sort(key=lambda x: (video_order.get(x["videoId"], 99), x["start"]))
    
    return selected, total_duration_so_far


def _expand_segments_to_target(selected_segments: List[Dict[str, Any]], 
                                transcripts: Dict[str, List[Any]],
                                current_duration: float, 
                                target_duration: int,
                                video_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Expand content if current duration is below target.
    Adds adjacent segments to already-selected ones.
    
    Args:
        selected_segments: Currently selected segments
        transcripts: Dict mapping video_id to segments
        current_duration: Current total duration
        target_duration: Target duration in seconds
        video_ids: List of video IDs
    
    Returns:
        Expanded list of segments
    """
    if current_duration >= target_duration * 0.8:  # Already at 80%+ of target
        return selected_segments
    
    print(f"⚠ Content too short ({current_duration:.1f}s < {target_duration * 0.8:.1f}s), expanding...")
    
    # Get all selected segment keys
    selected_keys = set(f"{s['videoId']}_{s['start']}" for s in selected_segments)
    duration_needed = target_duration - current_duration
    
    expanded = list(selected_segments)
    time_per_video = duration_needed / len(video_ids) if video_ids else 0
    
    for vid in video_ids:
        segments = transcripts.get(vid, [])
        video_time_added = 0.0
        
        for seg in segments:
            seg_key = f"{vid}_{seg['start']}"
            if seg_key not in selected_keys:
                seg_duration = float(seg['end']) - float(seg['start'])
                if video_time_added + seg_duration <= time_per_video * 1.5:
                    expanded.append({
                        "videoId": vid,
                        "start": float(seg['start']),
                        "end": float(seg['end'])
                    })
                    video_time_added += seg_duration
                    current_duration += seg_duration
                    
            if current_duration >= target_duration:
                break
        
        if current_duration >= target_duration:
            break
    
    # Sort by video order and start time
    video_order = {vid: idx for idx, vid in enumerate(video_ids)}
    expanded.sort(key=lambda x: (video_order.get(x["videoId"], 99), x["start"]))
    
    print(f"✅ Expanded to {current_duration:.1f}s")
    return expanded


def _create_trimmed_segments(segments: List[Dict[str, Any]], work_dir: str, 
                             merge_id: str, total_segments: int) -> List[str]:
    """
    For each segment, trim the corresponding local video file using ffmpeg -c copy.
    Returns list of segment file paths.
    Downloads videos in parallel for better performance.
    """
    # Download each unique video once (in parallel)
    video_files: Dict[str, str] = {}
    unique_videos = list(set([seg["videoId"] for seg in segments]))
    downloaded_count = 0
    download_lock = threading.Lock()
    
    def _download_single(vid: str, idx: int):
        """Helper function to download a single video with progress tracking."""
        nonlocal downloaded_count
        try:
            file_path = _download_video(vid, work_dir)
            with download_lock:
                video_files[vid] = file_path
                downloaded_count += 1
                progress = 70 + int((downloaded_count / len(unique_videos)) * 15)
                _update_job_status(merge_id, stage=f"Downloading video {downloaded_count}/{len(unique_videos)}", 
                                  progress_percent=progress)
            return file_path
        except Exception as e:
            print(f"❌ Download error for {vid}: {e}")
            raise
    
    # Download all videos in parallel (limit to 2 concurrent downloads)
    if unique_videos:
        with ThreadPoolExecutor(max_workers=min(2, len(unique_videos)), thread_name_prefix="download_") as executor:
            futures = {executor.submit(_download_single, vid, idx): vid for idx, vid in enumerate(unique_videos)}
            for future in futures:
                future.result()  # Wait for all to complete

    segment_files: List[str] = []
    for idx, seg in enumerate(segments):
        src = video_files[seg["videoId"]]
        out_seg = os.path.join(work_dir, f"seg_{idx}.mp4")
        start = float(seg["start"])
        duration = float(seg["end"] - seg["start"])

        cmd = [
            FFMPEG_BIN,
            "-y",
            "-ss", str(start),
            "-i", src,
            "-t", str(duration),
            "-c", "copy",
            out_seg,
        ]
        print(f"▶ Trimming segment {idx} ({seg['videoId']} [{start}-{start+duration}]s)")
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        segment_files.append(out_seg)
        
        _update_job_status(merge_id, stage=f"Trimming segment {idx + 1}/{len(segments)}",
                          progress_percent=85 + int((idx / len(segments)) * 10))

    return segment_files


def _concat_segments(segment_files: List[str], merge_id: str, work_dir: str) -> str:
    """Concatenate multiple segment files into a single file using ffmpeg concat demuxer."""
    list_path = os.path.join(work_dir, "concat_list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for path in segment_files:
            f.write(f"file '{path}'\n")

    output_name = f"merged_{merge_id}.mp4"
    output_path = os.path.join(MERGE_OUTPUT_DIR, output_name)

    cmd = [
        FFMPEG_BIN,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        output_path,
    ]
    print(f"▶ Concatenating {len(segment_files)} segments for merge job {merge_id}...")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path


def _process_merge_job(merge_id: str) -> None:
    """
    Background worker that orchestrates:
    1. Transcribing all selected videos using TranscriptionService (with caching).
    2. Summarizing the unified document using SummarizationService (with caching).
    3. Selecting segments based on target duration.
    4. Trimming and concatenating video clips with FFmpeg.
    
    This function uses duration-aware segment selection.
    """
    job = stored_merges.get(merge_id)
    if not job:
        return

    # Get target duration from job
    target_duration = job.get("target_duration", 300)
    print(f"🎯 Target duration: {target_duration}s ({target_duration/60:.1f} minutes)")

    # Verify external tools
    if not shutil.which(YTDLP_BIN) and not os.getenv("YTDLP_PATH"):
        _update_job_status(merge_id, status="error", error="yt-dlp not found.")
        return

    _update_job_status(merge_id, status="transcribing", stage="Starting transcription...", progress_percent=5)
    
    # Get unique video IDs, preserving order
    seen = set()
    video_ids = []
    for seg in job.get("segments", []):
        vid = seg["videoId"]
        if vid not in seen:
            seen.add(vid)
            video_ids.append(vid)
    
    work_dir = tempfile.mkdtemp(prefix=f"merge_{merge_id}_", dir=MERGE_WORK_DIR)
    
    # Get services
    transcription_service = get_transcription_service()
    summarization_service = get_summarization_service()
    
    transcripts = {}
    unified_text = ""
    failed_videos = []
    warnings = []

    try:
        # PHASE 1: Parallel Transcription with fault tolerance (using service with caching)
        total_videos = len(video_ids)
        completed_count = 0
        transcription_lock = threading.Lock()

        def _transcribe_single(vid: str, idx: int):
            """Helper function to transcribe a single video with progress tracking and error handling."""
            nonlocal completed_count, unified_text
            try:
                result = transcription_service.transcribe_video(vid)

                if "error" in result:
                    raise Exception(f"Transcription failed for {vid}: {result['error']}")

                with transcription_lock:
                    transcripts[vid] = result["segments"]
                    unified_text += result["full_text"] + " "
                    completed_count += 1
                    progress = 5 + int((completed_count / total_videos) * 35)
                    _update_job_status(
                        merge_id,
                        stage=f"Transcribing video {completed_count}/{total_videos} ({vid})",
                        progress_percent=progress
                    )

                print(f"✅ Transcribed {vid} ({len(result['segments'])} segments)")
                return result
            except Exception as e:
                error_msg = f"Failed to transcribe {vid}: {str(e)}"
                print(f"❌ {error_msg}")
                with transcription_lock:
                    failed_videos.append(vid)
                    warnings.append(error_msg)
                    completed_count += 1
                    progress = 5 + int((completed_count / total_videos) * 35)
                    _update_job_status(
                        merge_id,
                        stage=f"Video {completed_count}/{total_videos} - ⚠️ {vid} failed",
                        progress_percent=progress
                    )
                # Don't raise - continue with other videos
                return None

        # Transcribe all videos in parallel (limit to 3 concurrent to avoid overwhelming system)
        _update_job_status(merge_id, stage=f"Starting parallel transcription of {total_videos} videos...", progress_percent=5)

        with ThreadPoolExecutor(max_workers=min(3, total_videos), thread_name_prefix="transcribe_") as executor:
            futures = {executor.submit(_transcribe_single, vid, idx): vid for idx, vid in enumerate(video_ids)}
            for future in futures:
                future.result()  # Wait for all to complete (but don't fail on individual errors)

        # Check if we have any successful transcriptions
        successful_count = len(transcripts)
        if successful_count == 0:
            raise Exception(f"All {total_videos} videos failed to transcribe. Cannot proceed with merge.")

        if failed_videos:
            print(f"⚠️ Partial success: {successful_count}/{total_videos} videos transcribed successfully")
            _update_job_status(
                merge_id,
                warnings=warnings,
                failed_videos=failed_videos,
                total_videos=total_videos,
                successful_videos=successful_count
            )

        # PHASE 2: Summarization (using service with caching)
        _update_job_status(merge_id, status="summarizing", 
                          stage="Generating AI summary...", progress_percent=45)
        
        # Use full text for summary
        summary = summarization_service.summarize_text(unified_text.strip())
        
        job["summary"] = summary
        print(f"✅ Summary generated: {summary[:100]}...")

        # PHASE 3: Select Segments for Target Duration
        _update_job_status(merge_id, stage="Selecting key clips for target duration...", progress_percent=55)
        
        # Use duration-aware segment selection
        final_segments, actual_duration = _select_segments_for_duration(
            summary, transcripts, target_duration, video_ids
        )
        
        print(f"📊 Selected {len(final_segments)} segments, estimated duration: {actual_duration:.1f}s")
        
        # Apply expansion guard if needed
        if actual_duration < target_duration * 0.8:
            final_segments = _expand_segments_to_target(
                final_segments, transcripts, actual_duration, target_duration, video_ids
            )
        
        job["segments"] = final_segments

        # PHASE 4: Merging (FFmpeg only)
        _update_job_status(merge_id, status="merging", 
                          stage="Preparing video segments...", progress_percent=60)
        
        trimmed_files = _create_trimmed_segments(final_segments, work_dir, merge_id, len(final_segments))
        
        _update_job_status(merge_id, stage="Concatenating final video...", progress_percent=95)
        output_path = _concat_segments(trimmed_files, merge_id, work_dir)

        # COMPLETE
        final_status = "partial_success" if failed_videos else "completed"
        final_message = f"Merge completed with {len(failed_videos)} warnings!" if failed_videos else "Merge completed successfully!"

        _update_job_status(
            merge_id,
            status=final_status,
            stage=final_message,
            progress_percent=100,
            output_path=output_path,
            warnings=warnings,
            failed_videos=failed_videos,
            total_videos=total_videos,
            successful_videos=len(transcripts)
        )
        print(f"✅ Merge job {merge_id} finished. Output: {output_path}")

    except Exception as e:
        print(f"❌ Merge job {merge_id} failed:", e)
        import traceback
        traceback.print_exc()
        _update_job_status(merge_id, status="error", stage="Failed", error=str(e))

    finally:
        # CRITICAL: Always clean up work directory
        if os.path.exists(work_dir):
            try:
                print(f"🧹 Cleaning up work directory: {work_dir}")
                shutil.rmtree(work_dir, ignore_errors=True)
                print(f"✅ Work directory cleaned")
            except Exception as e:
                print(f"⚠️ Failed to clean work directory: {e}")


@app.route('/merge', methods=['POST'])
def save_merge_segments():
    """
    POST /merge - Start a new merge job.
    Returns immediately with mergeId for polling.
    """
    data = request.get_json()
    if not data or "selectedSegments" not in data:
        return jsonify({"error": "Missing selectedSegments"}), 400

    # Accept targetDuration (new) or durationSeconds (fallback for compatibility)
    target_duration = int(data.get("targetDuration", data.get("durationSeconds", 300)))
    selected_segments = data.get("selectedSegments", [])
    validated = []

    for seg in selected_segments:
        try:
            video_id = seg.get("videoId")
            if not video_id:
                raise ValueError("Missing videoId")

            start = seg.get("start")
            end = seg.get("end")

            if start is not None and end is not None:
                start = float(start)
                end = float(end)
                if end <= start:
                    raise ValueError("Invalid segment timing")
                validated.append({
                    "videoId": video_id,
                    "start": start,
                    "end": end
                })
            else:
                # Don't pre-generate segments - let the duration-aware logic handle it
                validated.append({"videoId": video_id})
        except Exception as e:
            print("Invalid input:", seg, e)

    if not validated:
        return jsonify({"error": "No valid video IDs provided"}), 400

    merge_id = str(uuid.uuid4())
    
    with _store_lock:
        stored_merges[merge_id] = {
            "status": "pending",
            "stage": "Initializing...",
            "progress_percent": 0,
            "segments": validated,
            "target_duration": target_duration,  # Store target duration
            "output_path": None,
            "summary": "",
            "error": None,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

    print(f"✅ Received merge request with {len(validated)} segments for merge ID: {merge_id}")

    # Submit to thread pool for background processing
    _executor.submit(_process_merge_job, merge_id)

    # Return immediately so Flask stays responsive
    return jsonify({
        "mergeId": merge_id, 
        "status": "pending",
        "message": "Merge job started. Poll /merge/<id> for status."
    })


@app.route('/merge/<merge_id>', methods=['GET'])
def get_merge_segments(merge_id):
    """
    GET /merge/<id> - Get merge job status.
    Enhanced with detailed stages, progress percentage, and failure tracking.
    """
    with _store_lock:
        job = stored_merges.get(merge_id)

    if not job:
        return jsonify({"error": "Merge ID not found"}), 404

    response: Dict[str, Any] = {
        "status": job.get("status", "pending"),
        "stage": job.get("stage", "Initializing..."),
        "progress": job.get("stage", ""),  # Legacy compatibility
        "progress_percent": job.get("progress_percent", 0),
        "segments": job.get("segments", []),
        "summary": job.get("summary", ""),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "warnings": job.get("warnings", []),
        "failed_videos": job.get("failed_videos", []),
        "total_videos": job.get("total_videos", 0),
        "successful_videos": job.get("successful_videos", 0)
    }

    if job.get("status") in ["completed", "partial_success"] and job.get("output_path"):
        response["merged_file"] = f"/merge/{merge_id}/file"

    if job.get("status") == "error":
        response["error"] = job.get("error")

    return jsonify(response)


@app.route('/merge/<merge_id>/file', methods=['GET'])
def get_merged_file(merge_id):
    """GET /merge/<id>/file - Download the merged video file."""
    with _store_lock:
        job = stored_merges.get(merge_id)

    if not job or job.get("status") not in ["completed", "partial_success"] or not job.get("output_path"):
        return jsonify({"error": "Merged file not ready"}), 409

    return send_file(job["output_path"], mimetype="video/mp4")


@app.route('/merge/list', methods=['GET'])
def list_merge_jobs():
    """GET /merge/list - List all merge jobs (for debugging)."""
    with _store_lock:
        jobs = []
        for merge_id, job in stored_merges.items():
            jobs.append({
                "merge_id": merge_id,
                "status": job.get("status"),
                "stage": job.get("stage"),
                "progress_percent": job.get("progress_percent"),
                "created_at": job.get("created_at")
            })
    return jsonify({"jobs": jobs})


@app.route('/voiceover', methods=['POST'])
def generate_voiceover():
    """POST /voiceover - Generate voiceover using ElevenLabs."""
    data = request.get_json()
    text = data.get("text", "")
    voice_id = data.get("voice_id", "21m00Tcm4TlvDq8ikWAM")

    if not text:
        return jsonify({"error": "Missing text for voiceover"}), 400

    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }

    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }

    try:
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream",
            headers=headers,
            json=payload,
            stream=True
        )

        if response.status_code != 200 or "audio" not in response.headers.get("Content-Type", ""):
            print("❌ ElevenLabs error:", response.text)
            return jsonify({"error": "Voice generation failed"}), 500

        def generate():
            for chunk in response.iter_content(chunk_size=4096):
                yield chunk

        return Response(generate(), content_type="audio/mpeg")

    except Exception as e:
        print("❌ Voiceover Exception:", str(e))
        return jsonify({"error": f"Voiceover failed: {str(e)}"}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """GET /health - Health check endpoint with cache stats."""
    cache_manager = get_video_cache_manager()
    cleanup_scheduler = get_cleanup_scheduler()

    return jsonify({
        "status": "healthy",
        "demo_mode": DEMO_MODE,
        "ffmpeg": shutil.which(FFMPEG_BIN) is not None,
        "ytdlp": shutil.which(YTDLP_BIN) is not None,
        "active_jobs": len([j for j in stored_merges.values() if j.get("status") in ["pending", "transcribing", "summarizing", "merging"]]),
        "cache": cache_manager.get_cache_stats(),
        "cleanup": cleanup_scheduler.get_stats()
    })


@app.route('/cleanup/manual', methods=['POST'])
def manual_cleanup():
    """POST /cleanup/manual - Run manual cleanup immediately."""
    cleanup_scheduler = get_cleanup_scheduler()
    results = cleanup_scheduler.run_manual_cleanup()
    return jsonify({
        "message": "Manual cleanup completed",
        "results": results
    })


@app.route('/cache/stats', methods=['GET'])
def cache_stats():
    """GET /cache/stats - Get detailed cache statistics."""
    cache_manager = get_video_cache_manager()
    return jsonify(cache_manager.get_cache_stats())


if __name__ == '__main__':
    print("=" * 60)
    print("🎬 Merge Backend v2.0 - Microservice Architecture")
    print("=" * 60)
    print(f"   Demo Mode: {'ON' if DEMO_MODE else 'OFF'}")
    print(f"   FFmpeg: {FFMPEG_BIN}")
    print(f"   yt-dlp: {YTDLP_BIN}")
    print("=" * 60)

    # Initialize and start cleanup scheduler
    cleanup_scheduler = get_cleanup_scheduler()
    cleanup_scheduler.start()

    print("✅ Merge backend running at http://localhost:5002")
    app.run(port=5002, debug=True, threaded=True)
