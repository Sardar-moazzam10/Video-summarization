"""
Video Cache Manager - Persistent caching of downloaded YouTube videos.
Features:
- LRU cache cleanup based on size and age limits
- File locking for concurrent download safety
- Metadata tracking (last_accessed, file_size)
- Cache hit/miss statistics
"""

import os
import json
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
# File locking is handled by threading locks instead of OS-level locks for cross-platform compatibility

# === Configuration ===
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
AUDIO_CACHE_DIR = os.path.join(BASE_DIR, "audio_cache")
VIDEO_CACHE_DIR = os.path.join(AUDIO_CACHE_DIR, "video_cache")

os.makedirs(VIDEO_CACHE_DIR, exist_ok=True)

# Environment configuration with defaults
VIDEO_CACHE_ENABLED = os.getenv("VIDEO_CACHE_ENABLED", "1") == "1"
VIDEO_CACHE_MAX_SIZE_GB = float(os.getenv("VIDEO_CACHE_MAX_SIZE_GB", "10"))
VIDEO_CACHE_MAX_AGE_DAYS = int(os.getenv("VIDEO_CACHE_MAX_AGE_DAYS", "30"))
MAX_PARALLEL_DOWNLOADS = int(os.getenv("MAX_PARALLEL_DOWNLOADS", "2"))
DOWNLOAD_RETRY_ATTEMPTS = int(os.getenv("DOWNLOAD_RETRY_ATTEMPTS", "3"))

# Resolve binaries
def _resolve_binary(env_name: str, default_name: str) -> str:
    override = os.getenv(env_name)
    if override:
        return override
    return shutil.which(default_name) or default_name

YTDLP_BIN = _resolve_binary("YTDLP_PATH", "yt-dlp")
FFMPEG_BIN = _resolve_binary("FFMPEG_PATH", "ffmpeg")
COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")


class VideoCacheManager:
    """
    Manages persistent video cache with LRU cleanup.
    Thread-safe with file locking for concurrent access.
    """

    def __init__(self):
        self.cache_dir = VIDEO_CACHE_DIR
        self._lock = threading.Lock()
        self._download_locks: Dict[str, threading.Lock] = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "downloads": 0,
            "errors": 0
        }

    def _get_video_dir(self, video_id: str) -> str:
        """Get the directory path for a video cache entry."""
        return os.path.join(self.cache_dir, video_id)

    def _get_video_path(self, video_id: str) -> str:
        """Get the file path for cached video."""
        video_dir = self._get_video_dir(video_id)
        video_file = os.path.join(video_dir, "video.mp4")
        return video_file

    def _get_metadata_path(self, video_id: str) -> str:
        """Get the metadata file path for a video."""
        video_dir = self._get_video_dir(video_id)
        return os.path.join(video_dir, "metadata.json")

    def _get_download_lock(self, video_id: str) -> threading.Lock:
        """Get or create a lock for a specific video download."""
        with self._lock:
            if video_id not in self._download_locks:
                self._download_locks[video_id] = threading.Lock()
            return self._download_locks[video_id]

    def _update_metadata(self, video_id: str, file_size: int):
        """Update or create metadata for a cached video."""
        metadata = {
            "video_id": video_id,
            "file_size": file_size,
            "last_accessed": datetime.now().isoformat(),
            "downloaded_at": datetime.now().isoformat()
        }

        metadata_path = self._get_metadata_path(video_id)
        os.makedirs(os.path.dirname(metadata_path), exist_ok=True)

        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)

    def _touch_access_time(self, video_id: str):
        """Update last accessed time for cache hit."""
        metadata_path = self._get_metadata_path(video_id)
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)

                metadata["last_accessed"] = datetime.now().isoformat()

                with open(metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
            except Exception as e:
                print(f"⚠️ Failed to update access time for {video_id}: {e}")

    def _validate_cached_video(self, video_path: str) -> bool:
        """Validate that a cached video file is usable."""
        if not os.path.exists(video_path):
            return False

        # Check file size > 0
        file_size = os.path.getsize(video_path)
        if file_size == 0:
            print(f"⚠️ Cached video has zero size: {video_path}")
            return False

        # File exists and has content
        return True

    def get_cached_video(self, video_id: str) -> Optional[str]:
        """
        Check if video is in cache and return path if available.
        Updates access time on cache hit.

        Returns:
            Path to cached video file, or None if not cached
        """
        if not VIDEO_CACHE_ENABLED:
            return None

        video_path = self._get_video_path(video_id)

        if self._validate_cached_video(video_path):
            print(f"📦 Cache HIT for video {video_id}")
            self._touch_access_time(video_id)
            with self._lock:
                self._stats["hits"] += 1
            return video_path

        with self._lock:
            self._stats["misses"] += 1
        return None

    def _download_with_retry(self, video_id: str, output_path: str) -> bool:
        """
        Download video with retry logic and exponential backoff.

        Returns:
            True if successful, False otherwise
        """
        url = f"https://www.youtube.com/watch?v={video_id}"

        for attempt in range(1, DOWNLOAD_RETRY_ATTEMPTS + 1):
            try:
                cmd = [
                    YTDLP_BIN,
                    "--ffmpeg-location", FFMPEG_BIN,
                    "--cookies", COOKIES_FILE,
                    "--js-runtimes", "node",
                    "--extractor-args", "youtube:player_client=web",
                    "--no-check-certificates",
                    "--socket-timeout", "60",
                    "--retries", "10",
                    "-f", "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio/best/bestvideo+bestaudio",
                    "-o", output_path,
                    url,
                ]

                print(f"▶ Downloading video {video_id} (attempt {attempt}/{DOWNLOAD_RETRY_ATTEMPTS})...")

                subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True
                )

                # Validate download
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    print(f"✅ Successfully downloaded {video_id}")
                    return True
                else:
                    print(f"⚠️ Download completed but file invalid for {video_id}")

            except subprocess.CalledProcessError as e:
                print(f"❌ Download attempt {attempt} failed for {video_id}:")
                print(e.stderr if e.stderr else str(e))

                if attempt < DOWNLOAD_RETRY_ATTEMPTS:
                    # Exponential backoff: 2, 4, 8 seconds
                    wait_time = 2 ** attempt
                    print(f"⏳ Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
            except Exception as e:
                print(f"❌ Unexpected error downloading {video_id}: {e}")
                break

        return False

    def download_and_cache_video(self, video_id: str, work_dir: Optional[str] = None) -> str:
        """
        Download a video and cache it persistently.
        Uses file locking to prevent concurrent downloads of the same video.

        Args:
            video_id: YouTube video ID
            work_dir: Optional work directory for temp files

        Returns:
            Path to the cached video file

        Raises:
            Exception if download fails after all retries
        """
        if not VIDEO_CACHE_ENABLED:
            # Fallback to direct download without caching
            if not work_dir:
                raise ValueError("work_dir required when cache disabled")
            return self._download_to_work_dir(video_id, work_dir)

        # Check cache first
        cached_path = self.get_cached_video(video_id)
        if cached_path:
            return cached_path

        # Acquire download lock for this video
        download_lock = self._get_download_lock(video_id)

        with download_lock:
            # Double-check after acquiring lock (another thread might have downloaded it)
            cached_path = self.get_cached_video(video_id)
            if cached_path:
                return cached_path

            # Create video directory
            video_dir = self._get_video_dir(video_id)
            os.makedirs(video_dir, exist_ok=True)

            # Download to temp location first (atomic)
            temp_path = os.path.join(video_dir, "video.temp.mp4")
            final_path = self._get_video_path(video_id)

            try:
                success = self._download_with_retry(video_id, temp_path)

                if not success:
                    with self._lock:
                        self._stats["errors"] += 1
                    raise Exception(f"Failed to download {video_id} after {DOWNLOAD_RETRY_ATTEMPTS} attempts")

                # Atomic move to final location
                shutil.move(temp_path, final_path)

                # Update metadata
                file_size = os.path.getsize(final_path)
                self._update_metadata(video_id, file_size)

                with self._lock:
                    self._stats["downloads"] += 1

                print(f"💾 Cached video {video_id} ({file_size / (1024*1024):.1f} MB)")

                return final_path

            except Exception as e:
                # Cleanup on failure
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                if os.path.exists(video_dir) and not os.listdir(video_dir):
                    os.rmdir(video_dir)
                raise

    def _download_to_work_dir(self, video_id: str, work_dir: str) -> str:
        """Fallback: download directly to work dir without caching."""
        output_template = os.path.join(work_dir, f"{video_id}.%(ext)s")
        url = f"https://www.youtube.com/watch?v={video_id}"

        cmd = [
            YTDLP_BIN,
            "--ffmpeg-location", FFMPEG_BIN,
            "--cookies", COOKIES_FILE,
            "--js-runtimes", "node",
            "--extractor-args", "youtube:player_client=web",
            "--no-check-certificates",
            "--socket-timeout", "60",
            "--retries", "10",
            "-f", "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio/best/bestvideo+bestaudio",
            "-o", output_template,
            url,
        ]

        print(f"▶ Downloading video {video_id} (no cache)...")
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

        # Find downloaded file
        for fname in os.listdir(work_dir):
            if fname.startswith(video_id + "."):
                return os.path.join(work_dir, fname)

        raise FileNotFoundError(f"Downloaded file for {video_id} not found")

    def cleanup_old_cache(self) -> Dict[str, Any]:
        """
        Clean up old cache entries based on LRU policy.
        Enforces size and age limits.

        Returns:
            Stats about cleanup operation
        """
        if not VIDEO_CACHE_ENABLED:
            return {"message": "Cache disabled"}

        print("🧹 Running video cache cleanup...")

        # Collect all cached videos with metadata
        cache_entries = []
        total_size = 0

        for video_id in os.listdir(self.cache_dir):
            video_dir = self._get_video_dir(video_id)
            video_path = self._get_video_path(video_id)
            metadata_path = self._get_metadata_path(video_id)

            if not os.path.isdir(video_dir):
                continue

            if not os.path.exists(video_path):
                # Orphaned directory, remove it
                shutil.rmtree(video_dir, ignore_errors=True)
                continue

            file_size = os.path.getsize(video_path)
            total_size += file_size

            # Load metadata
            last_accessed = None
            if os.path.exists(metadata_path):
                try:
                    with open(metadata_path, 'r') as f:
                        metadata = json.load(f)
                        last_accessed = datetime.fromisoformat(metadata.get("last_accessed", metadata.get("downloaded_at")))
                except:
                    pass

            if not last_accessed:
                # Fallback to file modification time
                last_accessed = datetime.fromtimestamp(os.path.getmtime(video_path))

            cache_entries.append({
                "video_id": video_id,
                "video_dir": video_dir,
                "file_size": file_size,
                "last_accessed": last_accessed
            })

        # Sort by last accessed (oldest first)
        cache_entries.sort(key=lambda x: x["last_accessed"])

        removed_count = 0
        freed_space = 0
        max_size_bytes = VIDEO_CACHE_MAX_SIZE_GB * 1024 * 1024 * 1024
        age_cutoff = datetime.now() - timedelta(days=VIDEO_CACHE_MAX_AGE_DAYS)

        # Remove old entries
        for entry in cache_entries:
            should_remove = False
            reason = ""

            # Check age limit
            if entry["last_accessed"] < age_cutoff:
                should_remove = True
                reason = f"older than {VIDEO_CACHE_MAX_AGE_DAYS} days"

            # Check size limit (remove oldest until under limit)
            elif total_size > max_size_bytes:
                should_remove = True
                reason = f"cache over size limit ({total_size / (1024**3):.2f} GB > {VIDEO_CACHE_MAX_SIZE_GB} GB)"

            if should_remove:
                try:
                    shutil.rmtree(entry["video_dir"], ignore_errors=True)
                    removed_count += 1
                    freed_space += entry["file_size"]
                    total_size -= entry["file_size"]
                    print(f"🗑️  Removed {entry['video_id']} ({reason})")
                except Exception as e:
                    print(f"⚠️ Failed to remove {entry['video_id']}: {e}")

        result = {
            "removed_count": removed_count,
            "freed_space_mb": freed_space / (1024 * 1024),
            "remaining_size_mb": total_size / (1024 * 1024),
            "remaining_count": len(cache_entries) - removed_count
        }

        print(f"✅ Cleanup complete: removed {removed_count} videos, freed {result['freed_space_mb']:.1f} MB")

        return result

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive cache statistics.

        Returns:
            Dict with cache stats including size, count, hit rate
        """
        if not VIDEO_CACHE_ENABLED:
            return {"enabled": False}

        # Calculate current cache size and count
        total_size = 0
        video_count = 0

        for video_id in os.listdir(self.cache_dir):
            video_path = self._get_video_path(video_id)
            if os.path.exists(video_path):
                total_size += os.path.getsize(video_path)
                video_count += 1

        # Calculate hit rate
        total_requests = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total_requests * 100) if total_requests > 0 else 0

        return {
            "enabled": True,
            "video_count": video_count,
            "total_size_mb": total_size / (1024 * 1024),
            "total_size_gb": total_size / (1024 * 1024 * 1024),
            "max_size_gb": VIDEO_CACHE_MAX_SIZE_GB,
            "max_age_days": VIDEO_CACHE_MAX_AGE_DAYS,
            "hit_rate_percent": round(hit_rate, 1),
            "stats": {
                "cache_hits": self._stats["hits"],
                "cache_misses": self._stats["misses"],
                "downloads": self._stats["downloads"],
                "errors": self._stats["errors"]
            }
        }


# Singleton instance
_video_cache_manager = None
_manager_lock = threading.Lock()

def get_video_cache_manager() -> VideoCacheManager:
    """Get singleton VideoCacheManager instance."""
    global _video_cache_manager
    with _manager_lock:
        if _video_cache_manager is None:
            _video_cache_manager = VideoCacheManager()
            print(f"✅ Video cache manager initialized (enabled={VIDEO_CACHE_ENABLED}, max_size={VIDEO_CACHE_MAX_SIZE_GB}GB)")
    return _video_cache_manager
