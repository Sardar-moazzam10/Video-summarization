"""
Cleanup Scheduler - Background thread for automatic cleanup of temp directories.
Features:
- Runs cleanup tasks periodically
- Cleans old merge_work directories
- Cleans old transcription temp directories
- Runs video cache LRU cleanup
- Configurable intervals and age thresholds
"""

import os
import shutil
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any
from pathlib import Path

# Configuration from environment
ENABLE_AUTO_CLEANUP = os.getenv("ENABLE_AUTO_CLEANUP", "1") == "1"
CLEANUP_INTERVAL_HOURS = float(os.getenv("CLEANUP_INTERVAL_HOURS", "1"))
TEMP_DIR_MAX_AGE_HOURS = int(os.getenv("TEMP_DIR_MAX_AGE_HOURS", "24"))
TRANSCRIPTION_TEMP_MAX_AGE_HOURS = int(os.getenv("TRANSCRIPTION_TEMP_MAX_AGE_HOURS", "1"))

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
AUDIO_CACHE_DIR = os.path.join(BASE_DIR, "audio_cache")
MERGE_WORK_DIR = os.path.join(AUDIO_CACHE_DIR, "merge_work")


class CleanupScheduler:
    """
    Background scheduler for automatic cleanup of temporary directories.
    Runs in a separate daemon thread.
    """

    def __init__(self):
        self.running = False
        self.thread = None
        self._stop_event = threading.Event()
        self.cleanup_stats = {
            "last_run": None,
            "total_runs": 0,
            "last_cleanup_results": {}
        }
        self._stats_lock = threading.Lock()

    def _clean_old_directories(self, base_dir: str, prefix: str, max_age_hours: int) -> Dict[str, Any]:
        """
        Clean directories older than max_age_hours.

        Args:
            base_dir: Base directory to search
            prefix: Prefix of directories to clean
            max_age_hours: Maximum age in hours before cleanup

        Returns:
            Stats about cleanup operation
        """
        if not os.path.exists(base_dir):
            return {"removed": 0, "freed_mb": 0, "error": "Base directory not found"}

        removed_count = 0
        freed_bytes = 0
        errors = []
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)

        try:
            for item in os.listdir(base_dir):
                item_path = os.path.join(base_dir, item)

                # Check if it matches prefix and is a directory
                if not item.startswith(prefix) or not os.path.isdir(item_path):
                    continue

                try:
                    # Get directory modification time
                    mtime = datetime.fromtimestamp(os.path.getmtime(item_path))

                    if mtime < cutoff_time:
                        # Calculate size before deletion
                        dir_size = self._get_dir_size(item_path)

                        # Remove directory
                        shutil.rmtree(item_path, ignore_errors=False)

                        removed_count += 1
                        freed_bytes += dir_size

                        print(f"🗑️  Removed old directory: {item} (age: {(datetime.now() - mtime).total_seconds() / 3600:.1f}h)")

                except Exception as e:
                    error_msg = f"Failed to remove {item}: {e}"
                    errors.append(error_msg)
                    print(f"⚠️ {error_msg}")

        except Exception as e:
            errors.append(f"Failed to list directory {base_dir}: {e}")
            print(f"⚠️ Failed to list directory {base_dir}: {e}")

        return {
            "removed": removed_count,
            "freed_mb": freed_bytes / (1024 * 1024),
            "errors": errors
        }

    def _get_dir_size(self, path: str) -> int:
        """Calculate total size of directory in bytes."""
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    if os.path.exists(filepath):
                        total_size += os.path.getsize(filepath)
        except Exception as e:
            print(f"⚠️ Error calculating size for {path}: {e}")
        return total_size

    def _run_cleanup_cycle(self) -> Dict[str, Any]:
        """
        Run a single cleanup cycle.

        Returns:
            Combined stats from all cleanup operations
        """
        print(f"🧹 Starting cleanup cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        results = {}

        # 1. Clean old merge_work directories
        print(f"🧹 Cleaning merge_work directories older than {TEMP_DIR_MAX_AGE_HOURS}h...")
        results["merge_work"] = self._clean_old_directories(
            MERGE_WORK_DIR,
            "merge_",
            TEMP_DIR_MAX_AGE_HOURS
        )

        # 2. Clean old transcription temp directories
        print(f"🧹 Cleaning transcription temp directories older than {TRANSCRIPTION_TEMP_MAX_AGE_HOURS}h...")
        results["transcription_temp"] = self._clean_old_directories(
            AUDIO_CACHE_DIR,
            "transcribe_",
            TRANSCRIPTION_TEMP_MAX_AGE_HOURS
        )

        # 3. Run video cache LRU cleanup
        try:
            from video_cache_manager import get_video_cache_manager
            cache_manager = get_video_cache_manager()
            print("🧹 Running video cache LRU cleanup...")
            results["video_cache"] = cache_manager.cleanup_old_cache()
        except Exception as e:
            results["video_cache"] = {"error": str(e)}
            print(f"⚠️ Video cache cleanup failed: {e}")

        # Calculate totals
        total_removed = (
            results.get("merge_work", {}).get("removed", 0) +
            results.get("transcription_temp", {}).get("removed", 0) +
            results.get("video_cache", {}).get("removed_count", 0)
        )

        total_freed_mb = (
            results.get("merge_work", {}).get("freed_mb", 0) +
            results.get("transcription_temp", {}).get("freed_mb", 0) +
            results.get("video_cache", {}).get("freed_space_mb", 0)
        )

        results["totals"] = {
            "total_removed": total_removed,
            "total_freed_mb": round(total_freed_mb, 2),
            "completed_at": datetime.now().isoformat()
        }

        print(f"✅ Cleanup cycle complete: removed {total_removed} items, freed {total_freed_mb:.1f} MB")

        return results

    def _cleanup_loop(self):
        """Main cleanup loop that runs in background thread."""
        print(f"🚀 Cleanup scheduler started (interval: {CLEANUP_INTERVAL_HOURS}h)")

        while not self._stop_event.is_set():
            try:
                # Run cleanup cycle
                results = self._run_cleanup_cycle()

                # Update stats
                with self._stats_lock:
                    self.cleanup_stats["last_run"] = datetime.now().isoformat()
                    self.cleanup_stats["total_runs"] += 1
                    self.cleanup_stats["last_cleanup_results"] = results

            except Exception as e:
                print(f"❌ Cleanup cycle failed: {e}")
                import traceback
                traceback.print_exc()

            # Wait for next cycle (or until stop event)
            wait_seconds = CLEANUP_INTERVAL_HOURS * 3600
            self._stop_event.wait(timeout=wait_seconds)

        print("🛑 Cleanup scheduler stopped")

    def start(self):
        """Start the cleanup scheduler in a background thread."""
        if not ENABLE_AUTO_CLEANUP:
            print("⏸️  Auto cleanup is disabled (ENABLE_AUTO_CLEANUP=0)")
            return

        if self.running:
            print("⚠️ Cleanup scheduler is already running")
            return

        self.running = True
        self._stop_event.clear()

        # Create and start daemon thread
        self.thread = threading.Thread(
            target=self._cleanup_loop,
            name="cleanup_scheduler",
            daemon=True
        )
        self.thread.start()

        print(f"✅ Cleanup scheduler started (interval: {CLEANUP_INTERVAL_HOURS}h)")

    def stop(self):
        """Stop the cleanup scheduler."""
        if not self.running:
            return

        print("🛑 Stopping cleanup scheduler...")
        self.running = False
        self._stop_event.set()

        if self.thread:
            self.thread.join(timeout=5)

        print("✅ Cleanup scheduler stopped")

    def run_manual_cleanup(self) -> Dict[str, Any]:
        """
        Run a manual cleanup cycle immediately.

        Returns:
            Cleanup results
        """
        print("🔧 Running manual cleanup...")
        results = self._run_cleanup_cycle()

        with self._stats_lock:
            self.cleanup_stats["last_manual_run"] = datetime.now().isoformat()
            self.cleanup_stats["last_cleanup_results"] = results

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get cleanup scheduler statistics."""
        with self._stats_lock:
            return {
                "enabled": ENABLE_AUTO_CLEANUP,
                "running": self.running,
                "interval_hours": CLEANUP_INTERVAL_HOURS,
                "temp_dir_max_age_hours": TEMP_DIR_MAX_AGE_HOURS,
                "transcription_temp_max_age_hours": TRANSCRIPTION_TEMP_MAX_AGE_HOURS,
                **self.cleanup_stats
            }


# Singleton instance
_cleanup_scheduler = None
_scheduler_lock = threading.Lock()


def get_cleanup_scheduler() -> CleanupScheduler:
    """Get singleton CleanupScheduler instance."""
    global _cleanup_scheduler
    with _scheduler_lock:
        if _cleanup_scheduler is None:
            _cleanup_scheduler = CleanupScheduler()
    return _cleanup_scheduler
