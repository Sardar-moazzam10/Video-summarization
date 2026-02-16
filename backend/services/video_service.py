"""
Video Highlight Service — FFmpeg-based video clip extraction and assembly.

Ported from merge_backend.py's proven FFmpeg pipeline, adapted for
the FastAPI async architecture.

Pipeline:
    1. Download source videos (via video_cache_manager.py)
    2. Trim highlight segments with FFmpeg -c copy (fast, no re-encode)
    3. Normalize clips to 1280x720 H.264/AAC (ensures reliable concat)
    4. Concatenate via FFmpeg concat demuxer
    5. Optionally overlay TTS narration audio

All FFmpeg calls run in threads via asyncio.to_thread to avoid blocking.
"""

import os
import shutil
import subprocess
import tempfile
import asyncio
from typing import List, Dict, Optional, Callable, Awaitable
from pathlib import Path


# Resolve FFmpeg binary
def _resolve_binary(env_name: str, default_name: str) -> str:
    override = os.getenv(env_name)
    if override:
        return override
    return shutil.which(default_name) or default_name


FFMPEG_BIN = _resolve_binary("FFMPEG_PATH", "ffmpeg")
YTDLP_BIN = _resolve_binary("YTDLP_PATH", "yt-dlp")


class VideoService:
    """
    Generates video highlight reels from YouTube videos.

    Uses FFmpeg for all video operations:
    - Trim: -ss / -t / -c copy (fast lossless cut)
    - Normalize: libx264/aac re-encode to uniform format
    - Concat: concat demuxer
    - Overlay: map video from one source + audio from another
    """

    def __init__(self):
        self.ffmpeg = FFMPEG_BIN
        self.output_dir = Path("audio_cache/highlights")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate_highlight_reel(
        self,
        job_id: str,
        highlight_segments: List[Dict],
        video_paths: Dict[str, str],
        audio_path: Optional[str] = None,
        progress_callback: Optional[Callable[[str], Awaitable]] = None,
    ) -> str:
        """
        Main entry point: trim, normalize, concatenate, overlay.

        Args:
            job_id: Unique job identifier
            highlight_segments: List of {video_id, start_time, end_time, reason}
            video_paths: Dict mapping video_id to local file path
            audio_path: Optional TTS narration MP3 to overlay
            progress_callback: Async callback for progress updates

        Returns:
            Path to the final highlight reel MP4
        """
        work_dir = tempfile.mkdtemp(prefix=f"highlight_{job_id}_")

        try:
            # Step 1: Trim segments
            if progress_callback:
                await progress_callback("Trimming highlight clips...")
            trimmed = await self._trim_segments(
                highlight_segments, video_paths, work_dir, progress_callback
            )

            if not trimmed:
                raise Exception("No segments could be trimmed")

            # Step 2: Normalize to uniform format for reliable concat
            if progress_callback:
                await progress_callback("Normalizing video format...")
            normalized = await self._normalize_segments(trimmed, work_dir)

            # Step 3: Concatenate
            if progress_callback:
                await progress_callback("Stitching clips together...")
            concat_path = await self._concat_segments(normalized, job_id, work_dir)

            # Step 4: Overlay audio if provided
            if audio_path and os.path.exists(audio_path):
                if progress_callback:
                    await progress_callback("Overlaying narration audio...")
                final_path = await self._overlay_audio(concat_path, audio_path, job_id)
            else:
                final_path = str(self.output_dir / f"highlight_{job_id}.mp4")
                shutil.copy2(concat_path, final_path)

            print(f"[Video] Highlight reel ready: {final_path}")
            return final_path

        finally:
            # Clean up work directory
            shutil.rmtree(work_dir, ignore_errors=True)

    async def download_videos(
        self,
        video_ids: List[str],
        progress_callback: Optional[Callable[[str], Awaitable]] = None,
    ) -> Dict[str, str]:
        """
        Download videos using the existing video_cache_manager.

        Returns dict mapping video_id to local file path.
        """
        import sys
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        video_paths = {}
        work_dir = tempfile.mkdtemp(prefix="video_dl_")

        for i, vid in enumerate(video_ids):
            if progress_callback:
                await progress_callback(f"Downloading video {i + 1}/{len(video_ids)}...")
            try:
                path = await self._download_single(vid, work_dir)
                if path:
                    video_paths[vid] = path
                    print(f"[Video] Downloaded {vid}: {path}")
            except Exception as e:
                print(f"[Video] Failed to download {vid}: {e}")

        return video_paths

    async def _download_single(self, video_id: str, work_dir: str) -> Optional[str]:
        """Download a single video using video_cache_manager or yt-dlp fallback."""
        try:
            from video_cache_manager import get_video_cache_manager
            cache_manager = get_video_cache_manager()
            path = await asyncio.to_thread(
                cache_manager.download_and_cache_video, video_id, work_dir
            )
            return path
        except Exception as e:
            print(f"[Video] Cache manager failed for {video_id}: {e}")

        # Fallback: direct yt-dlp download
        url = f"https://www.youtube.com/watch?v={video_id}"
        output_template = os.path.join(work_dir, f"{video_id}.%(ext)s")
        cookies_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "cookies.txt"
        )

        cmd = [
            YTDLP_BIN,
            "--ffmpeg-location", self.ffmpeg,
            "-f", "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio/best",
            "-o", output_template,
            url,
        ]
        if os.path.exists(cookies_file):
            cmd.extend(["--cookies", cookies_file])

        print(f"[Video] Downloading {video_id} via yt-dlp...")
        await asyncio.to_thread(
            subprocess.run, cmd, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )

        # Find downloaded file
        for fname in os.listdir(work_dir):
            if fname.startswith(f"{video_id}."):
                return os.path.join(work_dir, fname)

        return None

    async def _trim_segments(
        self,
        segments: List[Dict],
        video_paths: Dict[str, str],
        work_dir: str,
        progress_callback: Optional[Callable[[str], Awaitable]] = None,
    ) -> List[str]:
        """Trim video clips using ffmpeg -ss -t -c copy (fast, no re-encode)."""
        trimmed = []

        for i, seg in enumerate(segments):
            vid = seg["video_id"]
            if vid not in video_paths:
                print(f"[Video] Skipping segment {i} — video {vid} not downloaded")
                continue

            src = video_paths[vid]
            out = os.path.join(work_dir, f"seg_{i:04d}.mp4")
            start = float(seg["start_time"])
            duration = float(seg["end_time"]) - start

            if duration <= 0:
                continue

            cmd = [
                self.ffmpeg, "-y",
                "-ss", str(start),
                "-i", src,
                "-t", str(duration),
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                out,
            ]

            await asyncio.to_thread(
                subprocess.run, cmd, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            trimmed.append(out)

            if progress_callback:
                await progress_callback(f"Trimming clip {i + 1}/{len(segments)}")

        return trimmed

    async def _normalize_segments(
        self, segment_files: List[str], work_dir: str
    ) -> List[str]:
        """
        Re-encode segments to uniform 1280x720 H.264/AAC format.

        This ensures reliable concatenation — different source videos
        may have different codecs, resolutions, or frame rates.
        """
        normalized = []

        for i, f in enumerate(segment_files):
            out = os.path.join(work_dir, f"norm_{i:04d}.mp4")
            cmd = [
                self.ffmpeg, "-y", "-i", f,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-r", "30",
                "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
                       "pad=1280:720:-1:-1:color=black",
                "-movflags", "+faststart",
                out,
            ]
            await asyncio.to_thread(
                subprocess.run, cmd, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            normalized.append(out)

        return normalized

    async def _concat_segments(
        self, segment_files: List[str], job_id: str, work_dir: str
    ) -> str:
        """Concatenate segments using FFmpeg concat demuxer."""
        list_path = os.path.join(work_dir, "concat.txt")
        with open(list_path, "w") as f:
            for path in segment_files:
                f.write(f"file '{path}'\n")

        output = os.path.join(work_dir, f"concat_{job_id}.mp4")
        cmd = [
            self.ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            output,
        ]
        await asyncio.to_thread(
            subprocess.run, cmd, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return output

    async def _overlay_audio(
        self, video_path: str, audio_path: str, job_id: str
    ) -> str:
        """Overlay TTS narration audio onto the highlight reel video."""
        output = str(self.output_dir / f"highlight_{job_id}.mp4")
        cmd = [
            self.ffmpeg, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            output,
        ]
        await asyncio.to_thread(
            subprocess.run, cmd, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return output


# =====================================================
# SINGLETON
# =====================================================

_video_service = None


def get_video_service() -> VideoService:
    """Get singleton video service instance."""
    global _video_service
    if _video_service is None:
        _video_service = VideoService()
    return _video_service
